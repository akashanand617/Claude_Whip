#ifndef WHIP_STOCK_SERVICE_SLOT_H
#define WHIP_STOCK_SERVICE_SLOT_H
#include "stock_transport.h"

/* UNATTACHED stock RT02CR_3.12.02 FEE7-slot substitution candidate.
 * Exact setup callsite file0x76de normally calls0x7d5e, then stores its return
 * at0x209e1e. This adapter ALWAYS returns0xff to prevent publishing the new ID
 * into that SETUP slot. This does NOT disable shared callback0x6f28: its actual
 * selectors are different bytes0x209df7/0x209df8. Dedicated common-callback
 * demultiplexing/fencing and full feature/advertising closure remain required.
 * The legacy general-callback argument is deliberately ignored, not retained.
 * No stock patch, sixth service, callback implementation or admission follows.
 */
uint8_t wgs_replace_fee7(uint32_t legacy_general_callback);

/* Mandatory STRONG bindings, intentionally undefined. One separately owned
 * byte starts at0xff before the once-per-boot stock setup; never re-register
 * while old callbacks/sends can exist. Callback providers/storage must already
 * have qualified context, lifetime, ABI and identity semantics. All three are
 * required; nonzero Thumb syntax is NOT executable-address attestation.
 * Keep external discovery/control/send admission closed until registration,
 * ID uniqueness, owner/boot identity and callback/service fences are proven.
 * In particular, the unchanged common callback must never route a new ID to
 * either legacy handler; the sentinel returned here does not establish this.
 * The returned stack ID is published here only after checked add success;
 * registration may invoke callbacks before publication, which must fail closed.
 * Stock setup context and stack-return semantics remain binding obligations.
 */
extern uint8_t wgs_service_id;
extern const wg_callbacks wgs_callbacks;
#endif
