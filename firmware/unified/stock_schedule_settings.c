#include "stock_schedule_settings.h"

#define BYTE(address) (*(volatile const uint8_t *)(uintptr_t)(address))

uint32_t wss_read_controls(void) {
    uint32_t prior;
    __asm volatile ("mrs %0, primask" : "=r"(prior));
    __asm volatile ("cpsid i" ::: "memory");
    uint32_t interval = BYTE(0x208aacu);
    uint32_t enables = BYTE(0x208aadu);
    uint32_t mode = BYTE(0x208c44u);
    uint32_t time_set = BYTE(0x208c46u);
    __asm volatile ("msr primask, %0" :: "r"(prior) : "memory");
    return interval | (enables << 8) | (mode << 16) | (time_set << 24);
}
