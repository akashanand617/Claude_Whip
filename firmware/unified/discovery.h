#ifndef WHIP_UNIFIED_DISCOVERY_H
#define WHIP_UNIFIED_DISCOVERY_H
#include <stdbool.h>
#include <stdint.h>

/* UNATTACHED discovery candidate for the separate reviewed GATT service.
 * Identification is NOT authentication, a capability declaration or permission
 * to open Gesture. Neither ID is generated here. Caller must establish a fresh
 * nonzero per-boot identity and an independently reviewed build-tag mapping.
 * Production admission remains disabled; stock/V2 must never be probed with
 * an unknown UART command to obtain this value.
 */
#define WDI_BYTES 20u
/* Wire: 'W','I',schema=1,reserved=0, boot64 LE, build-tag64 LE. No host layout. */
/* Caller provides WDI_BYTES writable bytes; failure leaves them untouched.
 * Initialize before publication; publish only after true and never rewrite a
 * published/borrowed value. No ownership or one-time-init guard is supplied. */
bool wdi_encode(uint8_t *out, uint32_t boot_lo, uint32_t boot_hi,
                uint32_t build_lo, uint32_t build_hi);

typedef struct { const uint8_t *value; uint16_t length; } wdi_span;
/* A bounded borrowed view, NOT the stock callback ABI. Only offset zero is
 * supported, avoiding assumptions about ROM's later offset handling. The
 * eventual callback must map refusal to its reviewed ATT result.
 * Caller owns a successfully encoded immutable 20-byte value throughout the
 * stack's read lifetime, and a disjoint writable span output. This does not
 * allocate storage, serialize initialization or prove stack buffer lifetime.
 * Failure clears output fields when output is nonnull; no descriptor read or
 * write occurs here. Do not pass an unpublished or short value.
 */
bool wdi_read(const uint8_t *value, uint32_t offset, wdi_span *out);
#endif
