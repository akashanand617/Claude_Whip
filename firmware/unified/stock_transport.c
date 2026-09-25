#include "stock_transport.h"

_Static_assert(sizeof(wg_callbacks) == 12, "stock callback ABI is three ARM words");
typedef uint8_t (*add_fn)(uint8_t *, const uint8_t *, uint16_t, wg_callbacks);
typedef uint8_t (*send_fn)(uint8_t, uint8_t, uint16_t, const uint8_t *, uint16_t, uint32_t);

bool wg_stock_add(uint8_t *service, const uint8_t *database, uint16_t entry_count,
                   const wg_callbacks *callbacks) {
    if (!service) return false;
    *service = 0xff;
    if (!database || !callbacks || !entry_count || entry_count > 2340u) return false;
    if ((callbacks->read && !(callbacks->read & 1u)) ||
        (callbacks->write && !(callbacks->write & 1u)) ||
        (callbacks->cccd && !(callbacks->cccd & 1u))) return false;
    /* Original app wrapper at file 0x15824, bias 0x825fb0. */
    uint8_t status = ((add_fn)(uintptr_t)0x83b7d5u)(service, database,
                                                   (uint16_t)(entry_count * 28u), *callbacks);
    if (status == 1u && *service != 0xff) return true;
    *service = 0xff;
    return false;
}

bool wg_stock_notify20(uint8_t connection, uint8_t service, uint16_t attribute,
                      const uint8_t *frame) {
    if (!frame || connection == 0xff || service == 0xff || !attribute) return false;
    /* Original app wrapper at file 0x158ee. Notification PDU is literal 1;
     * use explicit word width, not compiler-dependent SDK enum layout. */
    return ((send_fn)(uintptr_t)0x83b89fu)(connection, service, attribute, frame, 20u, 1u) == 1u;
}
