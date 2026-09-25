#ifndef WHIP_STOCK_SUPERVISOR_WAIT_H
#define WHIP_STOCK_SUPERVISOR_WAIT_H
#include <stdint.h>

/* UNATTACHED exact-stock qc_app wait-site candidate. Only the BL at file
 * 0x135c in stock b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0
 * has the reviewed original arguments/continuation. No image writer or hook.
 * The stock semaphore must already be valid and alive for this entire boot.
 * SDK wait_ms semantics are source-supported; the ROM body is not captured.
 * A failed take is NOT uniquely a timeout. Repeated immediate failures could
 * spin: neither this wrapper nor its 100 ms request proves elapsed cadence.
 */
#define WUW_WAIT_MS 100u
/* Exact two-register original call ABI. Valid thread context only. Poll after
 * either take result, then preserve stock's raw zero/nonzero branch semantics.
 * Unexpected context/argument refuses with zero, never enables interrupts.
 * This is not an invalid-context recovery policy or a live deadline guarantee.
 */
uint32_t wuw_take(void *semaphore, uint32_t original_wait);

/* REQUIRED real owner binding, intentionally undefined here. No weak/no-op
 * fallback: a whole firmware link must refuse until this is implemented.
 * Runs in qc_app, must preserve thread/interrupt context, obtain a fresh clock,
 * service current dispatcher/lifecycle work and honor original event identities.
 * It must not fabricate physical receipts. Its own blocking/stack/time cost,
 * and every stock handler after this wait, still need qualification. This hook
 * only removes the unconditional idle-wait obstacle; it cannot preempt a stuck
 * stock body, solve cross-task ownership, or prove successful Health restoration.
 */
void wuw_supervise(void);
#endif
