#ifndef WHIP_STOCK_DISCOVERY_READ_H
#define WHIP_STOCK_DISCOVERY_READ_H
#include "discovery.h"

/* UNATTACHED six-argument ARM32 attribute-read callback, no context argument.
 * The stack provides valid, mutually disjoint writable output slots, disjoint
 * from identity/owner storage. Each nonnull output is cleared on every refusal.
 * Success borrows the whole immutable descriptor at offset0; no stack scratch,
 * slicing, session, mode transition, send receipt or authorization is created.
 * Connection is unused: this identity is public and read-only.
 *
 * Results:0 success,0x40a unavailable service/attribute,0x407 unsupported offset,
 * 0x411 missing result storage. These reviewed scalar ATT/application codes
 * are not an imported enum layout or measured ring/client-visible behavior.
 * Publication, real callback context and borrowed-buffer lifetime remain open.
 */
uint32_t wdr_read(uint8_t connection, uint8_t service, uint16_t attribute,
                  uint16_t offset, uint16_t *length, const uint8_t **value);

/* Mandatory STRONG storage binding, intentionally undefined. Mutable ONLY so
 * a real boot owner can successfully wdi_encode a qualified fresh nonzero boot
 * ID and reviewed build tag BEFORE publishing wgs_service_id. Thereafter all
 * WDI_BYTES remain immutable for the entire stack read lifetime. No storage,
 * boot-ID generator, initialized flag, alias permission or ownership supplied.
 * The callback never writes this object and returns only a const borrowed view.
 * The declaration does not prove initialization; no service-ID reuse/reset
 * publication is permitted while an old stack read or callback can remain.
 * This20-byte value is already counted in identity RAM planning, not new RAM.
 */
extern uint8_t wdr_identity[WDI_BYTES];
#endif
