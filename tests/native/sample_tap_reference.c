/* TEST ONLY: pre-compaction FIFO implementation retained as an independent
 * behavioral reference. This is the prior sample_tap.c algorithm/struct, with
 * entry points renamed. Never included in the stock-address component link.
 * Current input/output types and result codes remain ABI-identical.
 */
#include "sample_tap.h"
#include <stddef.h>

typedef struct {
    wt_sample queue[32];
    uint32_t session, acquisition, sequence;
    uint8_t head, count;
    bool active;
    wt_result fault;
} old_tap;
_Static_assert(WT_CAPACITY == 32u, "this reference preserves original capacity");
_Static_assert(sizeof(old_tap) == 404u, "review pre-compaction reference ABI");

unsigned proof_old_tap_size(void) { return sizeof(old_tap); }
unsigned proof_old_tap_sequence_offset(void) { return offsetof(old_tap, sequence); }
void proof_old_tap_init(old_tap *t) { *t = (old_tap){0}; }
bool proof_old_tap_start(old_tap *t, uint32_t session, uint32_t last_acquisition) {
    if (t->active || session == 0 || session <= t->session) return false;
    t->session = session;
    t->acquisition = last_acquisition;
    t->sequence = 0;
    t->head = t->count = 0;
    t->fault = WT_OK;
    t->active = true;
    return true;
}
void proof_old_tap_stop(old_tap *t, uint32_t session) {
    if (t->session != session) return;
    t->active = false;
    t->head = t->count = 0;
}
static wt_result old_fail(old_tap *t, wt_result reason) {
    proof_old_tap_stop(t, t->session);
    t->fault = reason;
    return reason;
}
wt_result proof_old_tap_offer(old_tap *t, uint32_t session, uint32_t acquisition,
                             const wt_axes *batch, uint8_t count, bool verified) {
    if (!t->active || session != t->session) return WT_STALE_SESSION;
    if (!verified || !batch || count == 0 || count > 32u ||
            (uint32_t)(acquisition - t->acquisition) != 1u)
        return old_fail(t, WT_BAD_ACQUISITION);
    if (count > 32u - t->count) return old_fail(t, WT_OVERFLOW);
    if (UINT32_MAX - t->sequence < count) return old_fail(t, WT_SEQUENCE_EXHAUSTED);
    for (uint8_t i = 0; i < count; i++) {
        uint8_t slot = (uint8_t)((t->head + t->count) % 32u);
        t->queue[slot].value = batch[i];
        t->queue[slot].sequence = ++t->sequence;
        t->count++;
    }
    t->acquisition = acquisition;
    return WT_OK;
}
bool proof_old_tap_take(old_tap *t, uint32_t session, wt_sample *sample) {
    if (!t->active || session != t->session || !t->count || !sample) return false;
    *sample = t->queue[t->head];
    t->head = (uint8_t)((t->head + 1u) % 32u);
    t->count--;
    return true;
}
