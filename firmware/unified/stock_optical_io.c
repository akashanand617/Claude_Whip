#include "stock_optical_io.h"
#include <stdbool.h>

typedef bool (*take_fn)(void *, uint32_t);
typedef bool (*give_fn)(void *);
typedef uint32_t (*write_fn)(uint32_t, const uint8_t *, uint32_t);
typedef uint32_t (*read_fn)(uint32_t, const uint8_t *, uint32_t, uint8_t *, uint32_t);

uint32_t woi_samples_io(uint32_t reg, uint8_t *bytes, uint32_t length) {
    if (!bytes || !length || length > 128u ||
        (reg != 0xffu && (reg != 0xfeu || length != 1u))) return UINT32_MAX;
    uint32_t exception, mask;
    __asm volatile ("mrs %0, ipsr\n\tmrs %1, primask" : "=r"(exception), "=r"(mask));
    if (exception || mask) return UINT32_MAX;
    void *mutex = *(void *volatile *)(uintptr_t)0x208c98u;
    if (!mutex || !((take_fn)(uintptr_t)0x133f5u)(mutex, 100u)) return UINT32_MAX;
    uint8_t command[2] = { (uint8_t)reg, 0u };
    uint32_t result;
    if (reg == 0xfeu) {
        command[1] = bytes[0];
        result = ((write_fn)(uintptr_t)0x833af3u)(0x33u, command, 2u);
    } else {
        /* Caller-buffer RX directly; do not re-enter stock's wrapper, which
         * would reacquire the mutex and discard its release status. */
        result = ((read_fn)(uintptr_t)0x833bf1u)(0x33u, command, 1u, bytes, length);
    }
    bool released = ((give_fn)(uintptr_t)0x1341du)(mutex);
    return result == 0u && released ? 0u : UINT32_MAX;
}
