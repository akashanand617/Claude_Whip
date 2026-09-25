#include "stock_discovery_read.h"
#include "stock_service.h"
#include "stock_service_slot.h"

uint32_t wdr_read(uint8_t connection, uint8_t service, uint16_t attribute,
                  uint16_t offset, uint16_t *length, const uint8_t **value) {
    (void)connection;
    if (length) *length = 0;
    if (value) *value = 0;
    if (!length || !value) return 0x411u;
    if (service == 0xffu || service != wgs_service_id ||
        attribute != WGD_DISCOVERY_VALUE) return 0x40au;
    if (offset) return 0x407u;
    *length = WDI_BYTES;
    *value = wdr_identity;
    return 0;
}
