#include "control_owner.h"

_Static_assert(sizeof(wco_owner) == 816, "review whole control-owner RAM budget");
_Static_assert(sizeof(wco_stock) == 12, "review stock binding placement");

static bool context(const wco_owner *o) {
    uint32_t exception, mask;
    __asm volatile ("mrs %0, ipsr\n\tmrs %1, primask" : "=r"(exception), "=r"(mask));
    return o && !exception && !mask;
}
static uint32_t lock(void) {
    uint32_t prior;
    __asm volatile ("mrs %0, primask\n\tcpsid i" : "=r"(prior) :: "memory");
    return prior;
}
static void unlock(uint32_t prior) {
    __asm volatile ("msr primask, %0" :: "r"(prior) : "memory");
}
static void close(wco_owner *o, uint32_t now) {
    (void)wd_close(&o->dispatch, o->dispatch.connection, now);
    (void)wim_close(&o->inbox, o->dispatch.connection, WIM_FAULT);
}
bool wco_init(wco_owner *o, uint32_t jobs, bool proven, uint32_t lo, uint32_t hi) {
    if (!context(o) || !(lo | hi)) return false;
    wd_init(&o->dispatch, jobs, proven, lo, hi);
    wim_init(&o->inbox);
    o->first_arrival = 0u;
    wc_init(&o->coordinator, &o->dispatch.adapter);
    o->stop = (wc_stop_receipt){0};
    return true;
}
bool wco_open(wco_owner *o, uint32_t generation, bool charging, uint32_t now) {
    if (!context(o)) return false;
    uint32_t prior = lock();
    bool ok = wd_open(&o->dispatch, generation, charging, now);
    if (ok && !wim_open(&o->inbox, generation)) {
        close(o, now);
        ok = false;
    }
    unlock(prior);
    return ok;
}
bool wco_step(wco_owner *o, uint32_t now) {
    if (!context(o) || !(o->dispatch.boot_lo | o->dispatch.boot_hi)) return false;
    uint32_t prior = lock();
    wd_dispatch *d = &o->dispatch;
    if (d->state == WD_RECEIVING && (uint32_t)(now - o->first_arrival) > WW_TIMEOUT_MS)
        close(o, now);
    wd_tick(d, now); /* Must service cleanup even with no traffic/connection. */
    if (d->state == WD_CLOSED && wim_admitted(&o->inbox, d->connection))
        (void)wim_close(&o->inbox, d->connection, WIM_FAULT);
    for (unsigned i = 0; i < 2u; ++i) {
        wim_event event;
        uint32_t kind = wim_take(&o->inbox, now, &event);
        if (kind == WIM_NONE) break;
        if (kind == WIM_CLOSED) {
            if ((event.reasons & WIM_CHARGING) && event.generation == d->connection)
                wa_link(&d->adapter, d->state != WD_CLOSED, true, now);
            (void)wd_close(d, event.generation, now);
            break;
        }
        if (!wim_admitted(&o->inbox, event.generation) || event.generation != d->connection ||
            (d->state == WD_RECEIVING &&
             (uint32_t)(event.received - o->first_arrival) > WW_TIMEOUT_MS)) {
            close(o, now);
            break;
        }
        bool first = d->state == WD_IDLE;
        if (!wd_receive(d, event.frame, WW_FRAME_BYTES, event.generation, now)) {
            close(o, now);
            break;
        }
        if (first && d->state == WD_RECEIVING) o->first_arrival = event.received;
    }
    unlock(prior);
    return true;
}
wc_result wco_service(wco_owner *o, const wco_stock *stock) {
    if (!context(o) || !stock || !(o->dispatch.boot_lo | o->dispatch.boot_hi)) return WC_REJECTED;
    uint32_t now = wco_monotonic_ms();
    if (!wco_step(o, now)) return WC_REJECTED;
    wc_result result = wc_pump(&o->coordinator, stock->revision, stock->buffer,
                               stock->status, now, &o->stop);
    if (!context(o)) return WC_FAILED; /* Never clear a broken callee's mask. */
    const wm_controller *mode = &o->dispatch.adapter.runtime.mode;
    uint32_t token = mode->token, session = mode->session;
    wm_action action = mode->action;
    if (!wco_step(o, wco_monotonic_ms()) || token != mode->token ||
        session != mode->session || action != mode->action) return WC_REJECTED;
    return result;
}
void wuw_supervise(void) {
    (void)wco_service(&wco_bound_owner, &wco_bound_stock);
}
