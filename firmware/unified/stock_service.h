#ifndef WHIP_STOCK_SERVICE_H
#define WHIP_STOCK_SERVICE_H
#include <stdint.h>

/* OFFLINE, UNLINKED service-table candidate for the exact reviewed stock ABI.
 * This is NOT service admission, a callback implementation or a capability.
 * There is no production caller or iOS UUID registration. Existing stock reserves
 * five services and uses all five; this table does not authorize a sixth.
 * UUIDs are development-only assignments, unrelated to the legacy UART service.
 * The read-only discovery slot needs a separately reviewed, immutable-per-boot
 * identity/capability value BEFORE requests containing an expected boot ID.
 * That format, owner, bounded read callback and authorization remain absent.
 */
enum {
    WGD_ATTRIBUTES = 8,
    WGD_RX_VALUE = 2,
    WGD_TX_VALUE = 4,
    WGD_TX_CCCD = 5,
    WGD_DISCOVERY_VALUE = 7,
};

/* Explicit-width fields, ARM32 pointer. Do not import a host SDK structure:
 * this layout is checked below against the pinned stock's 28-byte entries.
 */
typedef struct {
    uint16_t flags;
    uint8_t type_value[16];
    uint16_t value_len;
    const uint8_t *value;
    uint32_t permissions;
} wgd_attribute;

extern const uint8_t wgd_service_uuid[16];
extern const wgd_attribute wgd_database[WGD_ATTRIBUTES];
#endif
