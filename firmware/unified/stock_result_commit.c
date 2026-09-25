#include "stock_result_commit.h"

#define BYTE(address) (*(volatile uint8_t *)(uintptr_t)(address))
#define HALF(address) (*(volatile uint16_t *)(uintptr_t)(address))

bool wrc_commit_hr(const wh_adapter *h, wh_ticket original, bool measured,
                   int32_t value, uint16_t auxiliary) {
    if (!h || value <= 0) return false;
    uint32_t exception, prior;
    __asm volatile ("mrs %0, ipsr" : "=r"(exception));
    if (exception) return false;
    __asm volatile ("mrs %0, primask\n\tcpsid i" : "=r"(prior) :: "memory");
    /* wh_result_allowed is bounded, read-only C with no external operations.
     * Check inventory here too: a malformed HEALTH state must not open it.
     */
    bool accepted = h->inventory_proven && wh_result_allowed(h, original, measured);
    if (accepted) {
        BYTE(0x20c020u) = 2u;
        BYTE(0x20c01eu) = (uint8_t)value;
        BYTE(0x20c028u) = (uint8_t)value;
        HALF(0x20c022u) = auxiliary;
    }
    __asm volatile ("msr primask, %0" :: "r"(prior) : "memory");
    return accepted;
}
