#include <stdbool.h>
#include <stdint.h>

typedef uint8_t (*send_fn)(uint8_t, uint8_t, uint16_t,
                           const uint8_t *, uint16_t, uint32_t);

/* Exact existing-UART send wrapper for the size experiment. Service ID and
 * attribute 4 must be captured from the retained stock UART registration. */
bool wg_stock_notify20(uint8_t connection, uint8_t service, uint16_t attribute,
                       const uint8_t *frame) {
    if (!frame || connection == 0xff || service == 0xff || !attribute) return false;
    return ((send_fn)(uintptr_t)0x83b89fu)(connection, service, attribute,
                                           frame, 20u, 1u) == 1u;
}
