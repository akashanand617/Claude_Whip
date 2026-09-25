#include "stock_service_slot.h"
#include "stock_service.h"

uint8_t wgs_replace_fee7(uint32_t legacy_general_callback) {
    (void)legacy_general_callback;
    wgs_service_id = 0xffu;
    if (!(wgs_callbacks.read & 1u) || !(wgs_callbacks.write & 1u) ||
        !(wgs_callbacks.cccd & 1u)) return 0xffu;
    uint8_t assigned;
    if (wg_stock_add(&assigned, (const uint8_t *)wgd_database,
                     WGD_ATTRIBUTES, &wgs_callbacks))
        wgs_service_id = assigned;
    return 0xffu;
}
