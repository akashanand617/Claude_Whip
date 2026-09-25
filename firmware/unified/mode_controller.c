#include "mode_controller.h"

static bool expired(uint32_t now, uint32_t deadline) {
    return (uint32_t)(now - deadline) < 0x80000000u;
}

/* Share the checked transition body instead of duplicating it at each action.
 * Keep token-exhaustion handling and deadlines identical at every caller. */
static __attribute__((noinline)) void issue(wm_controller *c, wm_action action, uint32_t now) {
    /* Never reuse a callback token during this boot. Fail closed on exhaustion. */
    if (c->token == UINT32_MAX) {
        c->state = WM_FAULT;
        c->action = WM_NONE;
        return;
    }
    c->token++;
    c->action = action;
    c->deadline_ms = now + WM_ACTION_TIMEOUT_MS;
}

static void leave(wm_controller *c, wm_reason reason, uint32_t now) {
    if (c->state == WM_HEALTH || c->state == WM_RETURNING) return;
    c->state = WM_RETURNING;
    c->reason = reason;
    /* Idempotent even if entry failed before acquiring either resource. Adapter
     * MUST fence/cancel old work before acknowledging this stop. */
    issue(c, WM_STOP_STREAM, now);
}

void wm_init(wm_controller *c) {
    *c = (wm_controller){ .state = WM_HEALTH };
}

void wm_link(wm_controller *c, bool connected, bool charging, uint32_t now) {
    c->connected = connected;
    c->charging = charging;
    if (c->state == WM_FAULT) return; /* recovery requires an explicit Health request */
    if (!connected) leave(c, WM_DISCONNECT, now);
    else if (charging) leave(c, WM_CHARGING, now);
}

bool wm_request(wm_controller *c, bool gesture, uint32_t now) {
    wm_tick(c, now);
    if (!gesture) {
        leave(c, WM_USER, now);
        return true; /* accepted, NOT a claim that Health is already restored */
    }
    if (!c->connected || c->charging) return false;
    if (c->state == WM_ENTERING || c->state == WM_GESTURE) return true;
    if (c->state != WM_HEALTH) return false;
    c->state = WM_ENTERING;
    c->reason = WM_USER;
    c->have_sequence = false;
    issue(c, WM_QUIESCE_OPTICS, now);
    c->session = c->token;
    return c->state != WM_FAULT;
}

bool wm_complete(wm_controller *c, uint32_t token, bool success, uint32_t now) {
    /* A completion arriving after its deadline must not resurrect a session. */
    wm_tick(c, now);
    if (c->action == WM_NONE || c->token != token) return false;
    if (!success) {
        if (c->state == WM_RETURNING) {
            c->state = WM_FAULT;
            c->reason = WM_ACTION_FAILED;
            c->action = WM_NONE;
        } else leave(c, WM_ACTION_FAILED, now);
        return true;
    }
    switch (c->action) {
    case WM_QUIESCE_OPTICS: issue(c, WM_HOLD_ACCEL, now); break;
    case WM_HOLD_ACCEL: issue(c, WM_START_25HZ, now); break;
    case WM_START_25HZ:
        c->state = WM_GESTURE;
        c->action = WM_NONE;
        c->lease_ms = now + WM_LEASE_MS;
        break;
    case WM_STOP_STREAM: issue(c, WM_RELEASE_ACCEL, now); break;
    case WM_RELEASE_ACCEL: issue(c, WM_RESUME_HEALTH, now); break;
    case WM_RESUME_HEALTH:
        c->state = WM_HEALTH;
        c->action = WM_NONE;
        break;
    default: return false;
    }
    return true;
}

bool wm_renew(wm_controller *c, uint32_t session, uint32_t sequence, uint32_t now) {
    wm_tick(c, now);
    if (c->state != WM_GESTURE || session != c->session || !c->connected || c->charging)
        return false;
    /* Serial-number arithmetic permits stream sequence rollover, not replay. */
    uint32_t advance = sequence - c->last_sequence;
    if (c->have_sequence && (advance == 0 || advance >= 0x80000000u)) return false;
    c->last_sequence = sequence;
    c->have_sequence = true;
    c->lease_ms = now + WM_LEASE_MS;
    return true;
}

void wm_tick(wm_controller *c, uint32_t now) {
    if (c->action != WM_NONE && expired(now, c->deadline_ms)) {
        if (c->state == WM_RETURNING) {
            c->state = WM_FAULT;
            c->reason = WM_ACTION_TIMEOUT;
            c->action = WM_NONE;
        } else leave(c, WM_ACTION_TIMEOUT, now);
    } else if (c->state == WM_GESTURE && expired(now, c->lease_ms)) {
        leave(c, WM_LEASE, now);
    }
}

bool wm_optics_allowed(const wm_controller *c) {
    return c->state == WM_HEALTH;
}

void wm_stream_failed(wm_controller *c, uint32_t now) {
    wm_tick(c, now);
    if (c->state == WM_ENTERING || c->state == WM_GESTURE)
        leave(c, WM_STREAM_FAILED, now);
}

bool wm_optical_start_allowed(const wm_controller *c, wm_optical_purpose purpose) {
    /* Health retains genuine measurements, not charging/find-ring animations or
     * raw optical debug flashing. Every stock RUN caller must be classified. */
    return wm_optics_allowed(c) && purpose == WM_HEALTH_MEASUREMENT;
}
