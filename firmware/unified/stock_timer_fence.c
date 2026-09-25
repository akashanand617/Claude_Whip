#include "stock_timer_fence.h"
_Static_assert(sizeof(wf_timer_fence) == 12, "review timer-fence RAM budget");

/* Cortex-M0+ save/restore: never unconditionally enable a caller's interrupts.
 * Critical sections contain bounded word/byte operations only, no RTOS call.
 */
static uint32_t lock(void) {
    uint32_t prior;
    __asm volatile ("mrs %0, primask\n\tcpsid i" : "=r"(prior) :: "memory");
    return prior;
}
static void unlock(uint32_t prior) {
    __asm volatile ("msr primask, %0" :: "r"(prior) : "memory");
}
static void timer_passed(void *context, uint32_t ticket) {
    wf_timer_fence *f = context;
    if (!f) return;
    uint32_t prior = lock();
    if (f->pending && f->issued == ticket) f->acknowledged = ticket;
    unlock(prior);
}
void wf_init(wf_timer_fence *f) {
    if (f) *f = (wf_timer_fence){0};
}
bool wf_request(wf_timer_fence *f, uint32_t ticket) {
    if (!f || !ticket) return false;
    uint32_t exception;
    __asm volatile ("mrs %0, ipsr" : "=r"(exception));
    if (exception) return false;
    uint32_t prior = lock();
    if (prior || f->fault || f->pending || f->enqueuing || ticket <= f->issued) {
        unlock(prior);
        return false;
    }
    /* Captured ROM 0x10d5e loads this exact slot and ASSERTS if it is NULL.
     * Binding requires the stock timer queue to remain alive for the boot;
     * this guard is not a queue-lifetime/RTOS-initialization proof.
     */
    if (!*(volatile const uint32_t *)(uintptr_t)UINT32_C(0x201478)) {
        f->fault = 1u;
        unlock(prior);
        return false;
    }
    f->issued = ticket;
    f->acknowledged = 0u;
    f->accepted = 0u;
    f->pending = 1u;
    f->enqueuing = 1u;
    unlock(prior);
    /* SDK FreeRTOS V10.2.1: signed BaseType_t, 32-bit TickType_t; wait=0.
     * The map locates xTimerPendFunctionCall, not its FromISR counterpart.
     */
    typedef int32_t (*pend_fn)(void (*)(void *, uint32_t), void *, uint32_t, uint32_t);
    int32_t result = ((pend_fn)(uintptr_t)UINT32_C(0x10d5f))(timer_passed, f, ticket, 0u);
    prior = lock();
    f->enqueuing = 0u;
    bool accepted = result == 1 && f->pending && f->issued == ticket;
    if (result != 1) {
        f->fault = 1u;
        f->pending = 0u;
        f->acknowledged = 0u;
    }
    if (f->issued == ticket) f->accepted = accepted;
    unlock(prior);
    return accepted;
}
bool wf_complete(wf_timer_fence *f, uint32_t ticket) {
    if (!f || !ticket) return false;
    uint32_t prior = lock();
    bool complete = !f->fault && f->pending && f->accepted &&
        f->issued == ticket && f->acknowledged == ticket;
    if (complete) {
        f->pending = 0u;
        f->accepted = 0u;
        f->acknowledged = 0u;
    }
    unlock(prior);
    return complete;
}
bool wf_abandon(wf_timer_fence *f, uint32_t ticket) {
    if (!f || !ticket) return false;
    uint32_t prior = lock();
    bool pending = f->pending && f->issued == ticket;
    if (pending) {
        f->pending = 0u;
        f->accepted = 0u;
        f->acknowledged = 0u;
    }
    unlock(prior);
    return pending;
}
