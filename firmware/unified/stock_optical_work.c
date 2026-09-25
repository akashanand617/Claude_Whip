#include "stock_optical_work.h"

typedef int32_t (*stock_read_fn)(uint8_t *, uint8_t *, uint32_t);
typedef void (*stock_clear_fn)(uint8_t *);

static void leave(void) { __asm volatile ("cpsie i" ::: "memory"); }
static bool enter(const wh_adapter *h, uint8_t *buffer, uint8_t *status) {
    if (!h || !buffer || !status) return false;
    uint32_t exception, mask;
    __asm volatile ("mrs %0, ipsr\n\tmrs %1, primask" : "=r"(exception), "=r"(mask));
    if (exception || mask) return false;
    __asm volatile ("cpsid i" ::: "memory");
    if (buffer == *(uint8_t *volatile *)(uintptr_t)0x20859cu &&
        status == *(uint8_t *volatile *)(uintptr_t)0x2085a8u) return true;
    leave();
    return false;
}

int32_t wop_read(wh_adapter *h, wh_ticket original, uint8_t *buffer, uint8_t *status) {
    if (!enter(h, buffer, status)) return WOP_REJECTED;
    bool accepted = h->inventory_proven && wh_run_begin(h, original);
    leave();
    if (!accepted) return WOP_REJECTED;
    int32_t result = ((stock_read_fn)(uintptr_t)0x837945u)(buffer, status + 10, status[11]);
    uint32_t returned_mask;
    __asm volatile ("mrs %0, primask\n\tcpsid i" : "=r"(returned_mask) :: "memory");
    bool okay = !returned_mask && (result == 0 || result == -2 || result == -3);
    /* Recheck lifetime only: this true is NOT measurement provenance and no
     * result publication occurs here. Every downstream commit rechecks its
     * own original ticket and independently established source provenance. */
    accepted = wh_run_end(h, original, okay) && wh_result_allowed(h, original, true);
    /* A broken callee mask contract faults Health; never enable interrupts
     * that the stock path unexpectedly left disabled. */
    __asm volatile ("msr primask, %0" :: "r"(returned_mask) : "memory");
    return result ? result : (accepted ? 0 : WOP_REJECTED);
}

bool wop_retire(const wh_adapter *h, uint32_t token, uint8_t *buffer, uint8_t *status) {
    if (!enter(h, buffer, status)) return false;
    bool accepted = wh_retirement_allowed(h, token);
    if (accepted) {
        /* Exact stock clear reads readiness through the global status pointer.
         * Caller must supply that same live object, not a copied status block.
         */
        status[26] = 1;
        ((stock_clear_fn)(uintptr_t)0x835b71u)(buffer);
        for (uint8_t i = 24; i < 28; i++) status[i] = 0;
    }
    leave();
    return accepted;
}
