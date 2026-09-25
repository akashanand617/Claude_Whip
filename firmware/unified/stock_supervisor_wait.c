#include "stock_supervisor_wait.h"
#include <stdbool.h>

static bool thread_enabled(void) {
    uint32_t exception, mask;
    __asm volatile ("mrs %0, ipsr\n\tmrs %1, primask" : "=r"(exception), "=r"(mask));
    return !exception && !mask;
}

uint32_t wuw_take(void *semaphore, uint32_t original_wait) {
    if (!semaphore || original_wait != UINT32_MAX || !thread_enabled()) return 0u;
    /* Keep the full register result: stock branches on nonzero, rather than
     * relying on a newly imported compiler's enum/bool representation. */
    typedef uint32_t (*take_fn)(void *, uint32_t);
    uint32_t result = ((take_fn)(uintptr_t)UINT32_C(0x13361))(semaphore, WUW_WAIT_MS);
    if (!thread_enabled()) return 0u;
    wuw_supervise();
    return thread_enabled() ? result : 0u;
}
