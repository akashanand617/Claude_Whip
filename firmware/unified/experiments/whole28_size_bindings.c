#include "control_owner.h"
#include "stock_discovery_read.h"
#include "stock_service_slot.h"

/* SIZE EXPERIMENT ONLY. Absolute fixtures claim no RAM or physical ownership. */
__asm__(".global wco_bound_owner\n.set wco_bound_owner, 0x20010000");
__asm__(".global wco_bound_stock\n.set wco_bound_stock, 0x20011000");
uint32_t wco_monotonic_ms(void) { return 1u; }
__asm__(".global wdr_identity\n.set wdr_identity, 0x20012000");
__asm__(".global wgs_service_id\n.set wgs_service_id, 0x20012020");
static void missing_callback_placeholder(void) {}
const wg_callbacks wgs_callbacks = {
    (uint32_t)(uintptr_t)&wdr_read,
    (uint32_t)(uintptr_t)&missing_callback_placeholder,
    (uint32_t)(uintptr_t)&missing_callback_placeholder,
};
