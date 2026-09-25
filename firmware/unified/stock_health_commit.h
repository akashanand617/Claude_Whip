#ifndef WHIP_STOCK_HEALTH_COMMIT_H
#define WHIP_STOCK_HEALTH_COMMIT_H
#include "adapter.h"

/* Unattached, exact-STOCK final software commit boundary. NOT a scheduler,
 * physical resume receipt, revision source, or production RAM allocation.
 * Record these values when CURRENT-settings scheduler preparation completes,
 * in the same serialization domain as wa_resume_ready. Keep this record
 * immutable until this attempt ends; never substitute a newer job/token.
 */
typedef struct {
    uint32_t token, generation, revision, controls;
} wsc_prepared;

/* Task context only. Bounded, PRIMASK-preserving current-controls + current
 * revision check and wa_commit_health in ONE interrupt-excluded operation.
 * No RTOS, timer, sensor, bus, heap, clock/history or stock-state writes.
 * A successful return means only that the supplied READY evidence was accepted
 * and the two software Health gates committed, not that hardware restarted.
 *
 * REQUIRED UNRESOLVED BINDING CONTRACT: current_revision points to a separate,
 * aligned, live caller-owned word. Every relevant settings/eligibility writer
 * must advance it monotonically without wrap BEFORE becoming visible, in the
 * SAME serialization domain. Raw controls alone cannot detect ABA. No default
 * owner/address or revision counter is supplied here. All other preparation,
 * adapter and stock-state writers must obey that domain too. Maskable Cortex-M
 * preemption is excluded; NMI, DMA, debug and reset are outside this contract.
 * Pointer validity/lifetime, non-aliasing, initialization and exact image/map
 * remain caller obligations; alignment checks do not establish ownership.
 *
 * Stale identity/preparation is refused without changing adapter state. A new
 * current revision invalidates READY through existing wa_commit_health. Raw
 * controls changed WITHOUT revision advancement expose a broken writer
 * contract: permanently fail this attempt closed instead of inventing a
 * revision or allowing change-and-change-back to reuse its preparation.
 * Retrying needs the normal explicit recovery/current-settings preparation;
 * this primitive never retries or manufactures missing receipts.
 */
bool wsc_commit_health(wa_adapter *a, const wsc_prepared *prepared,
                       const volatile uint32_t *current_revision, uint32_t now);
#endif
