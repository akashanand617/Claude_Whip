#include "sample_tap.h"

void wt_init(wt_tap *t) { *t = (wt_tap){0}; }

bool wt_start(wt_tap *t, uint32_t session, uint32_t last_acquisition) {
    if (t->active || session == 0 || session <= t->session) return false;
    t->session = session;
    t->acquisition = last_acquisition;
    t->sequence = 0;
    t->head = t->count = 0;
    t->fault = WT_OK;
    t->active = true;
    return true;
}

void wt_stop(wt_tap *t, uint32_t session) {
    if (t->session != session) return;
    t->active = false;
    t->head = t->count = 0;
}

static wt_result fail(wt_tap *t, wt_result reason) {
    wt_stop(t, t->session);
    t->fault = reason;
    return reason;
}

wt_result wt_offer(wt_tap *t, uint32_t session, uint32_t acquisition,
                   const wt_axes *batch, uint8_t count, bool verified) {
    if (!t->active || session != t->session) return WT_STALE_SESSION;
    if (!verified || !batch || count == 0 || count > WT_CAPACITY ||
            (uint32_t)(acquisition - t->acquisition) != 1u)
        return fail(t, WT_BAD_ACQUISITION);
    if (count > WT_CAPACITY - t->count) return fail(t, WT_OVERFLOW);
    if (UINT32_MAX - t->sequence < count) return fail(t, WT_SEQUENCE_EXHAUSTED);
    for (uint8_t i = 0; i < count; i++) {
        uint8_t slot = (uint8_t)((t->head + t->count) % WT_CAPACITY);
        t->queue[slot] = batch[i];
        t->count++;
    }
    t->sequence += count;
    t->acquisition = acquisition;
    return WT_OK;
}

bool wt_take(wt_tap *t, uint32_t session, wt_sample *sample) {
    if (!t->active || session != t->session || !t->count || !sample) return false;
    /* All accepted batches append consecutive sequences, take removes only
     * the oldest entry, and exhaustion rejects before any append. Therefore
     * count <= sequence and this subtraction cannot underflow in a live queue.
     * The physical ring index may wrap; the session sequence never does.
     */
    sample->sequence = t->sequence - t->count + 1u;
    sample->value = t->queue[t->head];
    t->head = (uint8_t)((t->head + 1u) % WT_CAPACITY);
    t->count--;
    return true;
}
