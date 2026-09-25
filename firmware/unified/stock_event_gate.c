#include "stock_event_gate.h"
#include "stock_service_slot.h"

typedef uint32_t (*common_fn)(uint8_t, void *);

uint32_t wge_common(uint8_t service, void *event) {
    uint8_t owned = wgs_service_id;
    if (owned != 0xffu && service == owned) return 0;
    /* Pinned stock file0x6f28, ordinary execution bias0x825fb0. */
    return ((common_fn)(uintptr_t)0x82ced9u)(service, event);
}
