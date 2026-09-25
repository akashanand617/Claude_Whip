#include "control_owner.h"

/* SIZE EXPERIMENT ONLY. These absolute fixtures claim no RAM, connection,
 * callback, clock or transport ownership. */
__asm__(".global wco_bound_owner\n.set wco_bound_owner, 0x20010000");
__asm__(".global wco_bound_stock\n.set wco_bound_stock, 0x20011000");
uint32_t wco_monotonic_ms(void) { return 1u; }
void wum_post20(const uint8_t *frame) { (void)frame; }
