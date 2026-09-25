#include "stock_binding.h"

/* Reviewed Thumb ABI addresses, never V2 offsets or guessed ROM wrappers. */
#define WB_MUTEX_SLOT ((void * volatile *)(uintptr_t)UINT32_C(0x208c98))
/* Match the vendor os_sync.h declarations: bool results, opaque handles. */
typedef bool (*wb_mutex_take_fn)(void *, uint32_t);
typedef bool (*wb_mutex_give_fn)(void *);
typedef uint32_t (*wb_bus_write_fn)(uint32_t, const uint8_t *, uint32_t);

bool wb_stock_stop_writes(wb_stop_report *report) {
    if (report == 0) return false;
    report->mutex_taken = 0u;
    report->reset_bus_status = WB_NOT_ATTEMPTED;
    report->stop_bus_status = WB_NOT_ATTEMPTED;
    report->mutex_released = 0u;
    void *mutex = *WB_MUTEX_SLOT;
    if (mutex == 0) return false;
    wb_mutex_take_fn take = (wb_mutex_take_fn)(uintptr_t)UINT32_C(0x133f5);
    wb_mutex_give_fn give = (wb_mutex_give_fn)(uintptr_t)UINT32_C(0x1341d);
    wb_bus_write_fn write = (wb_bus_write_fn)(uintptr_t)UINT32_C(0x833af3);
    report->mutex_taken = take(mutex, 100u);
    if (report->mutex_taken == 0u) return false;
    uint8_t command[2] = { 0x7bu, 0xa5u };
    report->reset_bus_status = write(0x33u, command, 2u);
    command[1] = 0u;
    report->stop_bus_status = write(0x33u, command, 2u);
    report->mutex_released = give(mutex);
    return report->reset_bus_status == 0u && report->stop_bus_status == 0u &&
           report->mutex_released != 0u;
}
