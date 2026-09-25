#include "dispatch.h"

_Static_assert(WM_HEALTH == 0 && WM_ENTERING == 1 && WM_GESTURE == 2 &&
               WM_RETURNING == 3 && WM_FAULT == 4, "wire mode mapping changed");

static bool current(const wd_dispatch *d, uint32_t connection) {
    return d->state != WD_CLOSED && connection != 0u && connection == d->connection;
}
/* SCRATCH ONLY: preserve both exact zeroing operations in one shared body. */
static __attribute__((noinline)) void clear_exchange(wd_dispatch *d) {
    d->rx = (ww_rx){0};
    for (unsigned i = 0; i < WW_BODY_BYTES; ++i) d->reply[i] = 0;
}
static void close_current(wd_dispatch *d, uint32_t now) {
    d->state = WD_CLOSED;
    d->offered = false;
    clear_exchange(d);
    /* In Fault this does not pretend recovery. Explicit Health on a newly
     * admitted connection still needs the whole physical resume chain. */
    wa_link(&d->adapter, false, d->adapter.runtime.mode.charging, now);
}
void wd_init(wd_dispatch *d, uint32_t jobs, bool proven, uint32_t lo, uint32_t hi) {
    *d = (wd_dispatch){ .boot_lo = lo, .boot_hi = hi };
    wa_init(&d->adapter, jobs, proven);
}
bool wd_open(wd_dispatch *d, uint32_t connection, bool charging, uint32_t now) {
    if (d->state != WD_CLOSED || !(d->boot_lo | d->boot_hi) ||
        !connection || connection <= d->connection) return false;
    d->connection = connection;
    d->last_id = 0;
    d->state = WD_IDLE;
    wa_link(&d->adapter, true, charging, now);
    return true;
}
bool wd_close(wd_dispatch *d, uint32_t connection, uint32_t now) {
    if (!current(d, connection)) return false;
    close_current(d, now);
    return true;
}
bool wd_charging(wd_dispatch *d, uint32_t connection, bool charging, uint32_t now) {
    if (!current(d, connection)) return false;
    wa_link(&d->adapter, true, charging, now);
    wd_tick(d, now);
    return true;
}
static void ready(wd_dispatch *d, uint8_t result, uint32_t now) {
    const wm_controller *m = &d->adapter.runtime.mode;
    for (unsigned i = 0; i < WW_BODY_BYTES; ++i) d->reply[i] = 0;
    d->reply[0] = d->operation;
    d->reply[1] = result;
    d->reply[2] = (uint8_t)m->state;
    d->reply[3] = m->charging ? 1u : 0u;
    ww_put32(d->reply + 4, d->boot_lo);
    ww_put32(d->reply + 8, d->boot_hi);
    ww_put32(d->reply + 12, m->session);
    if (!ww_body_valid(WW_REPLY, d->reply, WW_BODY_BYTES, d->boot_lo, d->boot_hi)) {
        close_current(d, now);
        return;
    }
    d->state = WD_REPLY;
    d->started = now;
    d->part = 0;
    d->offered = false;
}
void wd_tick(wd_dispatch *d, uint32_t now) {
    wa_tick(&d->adapter, now); /* Always runs, including CLOSED/idle. */
    const wm_controller *m = &d->adapter.runtime.mode;
    if (d->state != WD_CLOSED && !m->connected) {
        close_current(d, now);
        return;
    }
    if (d->state == WD_RECEIVING && (uint32_t)(now - d->rx.started) > WW_TIMEOUT_MS) {
        close_current(d, now);
    } else if (d->state == WD_WAITING) {
        if ((uint32_t)(now - d->started) > WD_OPERATION_MS) {
            close_current(d, now);
        } else if (d->operation == WW_HEALTH) {
            if (m->state == WM_HEALTH && wa_health_allowed(&d->adapter, WM_HEALTH_MEASUREMENT))
                ready(d, WD_OK, now);
            else if (m->state != WM_RETURNING) ready(d, WD_FAULT, now);
        } else if (m->session != d->session) {
            ready(d, WD_FAULT, now);
        } else if (m->state == WM_GESTURE) {
            ready(d, WD_OK, now);
        } else if (m->state != WM_ENTERING) {
            ready(d, WD_FAULT, now);
        }
    } else if (d->state == WD_REPLY) {
        /* Never finish half of an obsolete success reply. Binding must drain
         * already offered/enqueued work on closure; rewriting fragment 1 would
         * let the host assemble a status that never existed. */
        if ((uint32_t)(now - d->started) > WW_TIMEOUT_MS ||
            d->reply[2] != (uint8_t)m->state || d->reply[3] != (uint8_t)m->charging ||
            ww_get32(d->reply + 12) != m->session) close_current(d, now);
    }
}
static void dispatch(wd_dispatch *d, uint32_t now) {
    wa_adapter *a = &d->adapter;
    wm_controller *m = &a->runtime.mode;
    d->operation = d->rx.body[0];
    d->started = now;
    d->session = m->session;
    if (d->operation == WW_STATUS) { ready(d, WD_OK, now); return; }
    if (d->operation == WW_RENEW) {
        bool accepted = wa_renew(a, ww_get32(d->rx.body + 10), ww_get32(d->rx.body + 14), now);
        ready(d, accepted ? WD_OK : WD_INVALID, now);
        return;
    }
    bool gesture = d->operation == WW_GESTURE;
    if (!wa_request(a, gesture, now)) {
        ready(d, m->state == WM_FAULT ? WD_FAULT :
              m->state == WM_HEALTH && !m->charging ? WD_UNAVAILABLE : WD_BUSY, now);
        return;
    }
    d->session = m->session;
    d->state = WD_WAITING;
    wd_tick(d, now);
}
bool wd_receive(wd_dispatch *d, const uint8_t *p, uint32_t length,
                uint32_t connection, uint32_t now) {
    if (!current(d, connection)) return false;
    wd_tick(d, now);
    if (!current(d, connection)) return false;
    if (d->state == WD_IDLE) {
        if (!p || length != WW_FRAME_BYTES || p[3] != 0 || ww_get32(p + 4) <= d->last_id) {
            close_current(d, now);
            return false;
        }
        ww_rx_begin(&d->rx, WW_REQUEST, ww_get32(p + 4), connection,
                    d->boot_lo, d->boot_hi, p[8], now);
        d->state = WD_RECEIVING;
    } else if (d->state != WD_RECEIVING) {
        close_current(d, now);
        return false;
    }
    uint8_t result = ww_rx_feed(&d->rx, p, length, connection, now);
    if (result == WW_REJECT) { close_current(d, now); return false; }
    d->last_id = d->rx.id; /* No reuse even if the second fragment never arrives. */
    if (result == WW_DONE) dispatch(d, now);
    return d->state != WD_CLOSED;
}
bool wd_reply_next(wd_dispatch *d, uint32_t connection, uint8_t *frame, uint32_t now) {
    if (!current(d, connection) || !frame) return false;
    wd_tick(d, now);
    if (d->state != WD_REPLY || d->offered) return false;
    if (!ww_pack_control(WW_REPLY, d->rx.id, d->reply, WW_BODY_BYTES, d->part, frame)) {
        close_current(d, now);
        return false;
    }
    d->offered = true;
    return true;
}
bool wd_reply_sent(wd_dispatch *d, uint32_t connection, uint32_t request,
                   uint8_t part, bool accepted, uint32_t now) {
    if (!current(d, connection)) return false;
    wd_tick(d, now);
    if (d->state != WD_REPLY || !d->offered || request != d->rx.id || part != d->part) return false;
    if (!accepted) { close_current(d, now); return false; }
    d->offered = false;
    if (++d->part == 2u) {
        d->state = WD_IDLE;
        clear_exchange(d);
    }
    return true;
}
