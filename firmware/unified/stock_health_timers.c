#include "stock_health_timers.h"

#define WORD(address) (*(volatile const uint32_t *)(uintptr_t)(address))
#define BYTE(address) (*(volatile const uint8_t *)(uintptr_t)(address))

/* Fixed SRAM access bounds only, not a claim of free/owned RAM. Share the full
 * predicate across the three checked spans; no bound is removed to save code. */
static __attribute__((noinline)) int ram_span(uint32_t address, uint32_t size) {
    return !(address & 3u) && address >= UINT32_C(0x200000) &&
        size <= UINT32_C(0x18000) && address <= UINT32_C(0x218000) - size;
}

wht_result wht_stop_reviewed(uint32_t job) {
    static const uint32_t slots[WHT_REVIEWED_COUNT] = {
        0x20c0c4u, 0x20c0acu, 0x20c0e8u, 0x20c0f0u, 0x20c104u,
        0x209d40u, 0x209d44u, 0x20c018u, 0x20bc54u, 0x209cc0u,
        0x209d14u, 0x209d10u
    };
    uint32_t exception, prior;
    __asm volatile ("mrs %0, ipsr" : "=r"(exception));
    __asm volatile ("mrs %0, primask" : "=r"(prior));
    if (exception || prior || job >= WHT_REVIEWED_COUNT) return WHT_REFUSED;
    __asm volatile ("cpsid i" ::: "memory");
    uint32_t handle = WORD(slots[job]);
    wht_result result = WHT_REFUSED;
    if (!handle) {
        result = WHT_EMPTY;
        goto out;
    }
    /* Captured xTimerGenericCommand uses these same pool/count/mask fields.
     * Unlike its STOP path, require the allocation bit even for STOP.
     */
    uint32_t pool = WORD(0x201488u), mask = WORD(0x20148cu);
    uint32_t count = BYTE(0x20037bu);
    if (!count || !ram_span(WORD(0x201478u), 4u) || !ram_span(pool, count * 48u) ||
        !ram_span(mask, ((count + 31u) / 32u) * 4u) || handle < pool)
        goto out;
    uint32_t delta = handle - pool;
    if (delta >= count * 48u) goto out;
    uint32_t index = delta / 48u;
    if (index * 48u != delta || WORD(handle + 0x24u) != index ||
        !(WORD(mask + (index / 32u) * 4u) & (UINT32_C(1) << (index & 31u))))
        goto out;
    __asm volatile ("msr primask, %0" :: "r"(prior) : "memory");
    /* No blocking or RTOS call while interrupts are masked. Do NOT clear the
     * slot or free/reuse the timer, regardless of enqueue outcome.
     */
    typedef int32_t (*command_fn)(uint32_t, int32_t, uint32_t, void *, uint32_t);
    int32_t accepted = ((command_fn)(uintptr_t)UINT32_C(0x108e1))(handle, 3, 0u, (void *)0, 0u);
    return accepted == 1 ? WHT_ACCEPTED : WHT_QUEUE_FAILED;
out:
    __asm volatile ("msr primask, %0" :: "r"(prior) : "memory");
    return result;
}

wht_result wht_stop_scheduled(uint32_t job) {
    return job < WHT_SCHEDULED_COUNT ? wht_stop_reviewed(job) : WHT_REFUSED;
}
