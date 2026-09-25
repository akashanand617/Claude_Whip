#ifndef WHIP_STOCK_COORDINATOR_H
#define WHIP_STOCK_COORDINATOR_H
#include "adapter.h"
#include "stock_binding.h"
#include "stock_health_commit.h"

/* UNATTACHED exact-stock orchestration candidate, not a production capability.
 * One serialized task owns this object AND every adapter/lifecycle operation.
 * It references the existing adapter: no second mode machine, timer inventory,
 * source profile, physical observer, GATT owner or default evidence is supplied.
 * Initialize once after stock Health; never reinitialize to revive old work.
 *
 * All entry points require thread mode with interrupts enabled. The real STOP
 * calls may block with interrupts enabled. Return from them is NOT physical
 * completion; a later observer supplies a fresh now and original receipt.
 * If a callee unexpectedly leaves interrupts masked, latch failure and preserve
 * that mask. This is not automatic recovery or permission to clear its mask.
 * Validity/lifetime/non-aliasing of owner, adapter, receipts, output, revision,
 * buffer and status are caller obligations. Captured buffer/status objects stay
 * alive until the operation and every old callback are drained. Both pointers
 * must be the exact objects registered by stock; wop_retire rechecks them.
 * All relevant settings writers must implement wsc_commit_health's monotonic
 * revision contract. This module does not create that writer map or counter.
 * No new RAM ownership, complete code budget, physical evidence or OTA approval.
 */
typedef struct {
    wa_adapter *adapter;
    uint32_t token, session, generation;
    uint8_t *buffer, *status;
    uint8_t phase;
    bool retired;
} wc_owner;

typedef struct {
    uint32_t token, session, generation;
    /* Diagnostic copy only. The owner retains success in its one-shot phase;
     * changing these copied fields cannot turn a failed write into permission. */
    wb_stop_report writes;
} wc_stop_receipt;

typedef struct {
    wsc_prepared prepared;
    bool health_preserved, scheduler_rebound;
} wc_resume_receipt;

typedef enum {
    WC_IDLE, WC_WAIT_DRAIN, WC_STOP_SUBMITTED, WC_WAIT_STOP,
    WC_HOLD_READY, WC_WAIT_RESUME, WC_REJECTED, WC_FAILED
} wc_result;

void wc_init(wc_owner *owner, wa_adapter *adapter);
/* Poll with a current clock value, even while disconnected. Never fabricates
 * wa_cancelled/wa_fenced: those need actual producer/queue completion. In
 * QUIESCE or partial RESUME, submits RESET/STOP at most once for that identity,
 * only after the real cancellation+fence gates close. out is written only for
 * an actual submission, successful or failed; its storage belongs to the caller.
 * A successful return/submission never advances to HOLD or restored Health.
 */
wc_result wc_pump(wc_owner *owner, const volatile uint32_t *current_revision,
                  uint8_t *buffer, uint8_t *status, uint32_t now,
                  wc_stop_receipt *out);
/* Called only by the eventual reviewed physical STOP observer. Identity must
 * be copied from the original submission, not assembled from current state.
 * Successful STOP advances the adapter, then retires software optical work
 * with the ORIGINAL Health token before this owner permits HOLD. Retirement
 * failure faults the resulting HOLD/RESUME action. No hardware FIFO flush.
 */
bool wc_optics_stopped(wc_owner *owner, const wc_stop_receipt *original,
                       bool physical_stop_verified, uint8_t *buffer,
                       uint8_t *status, uint32_t now);
/* Current-settings fresh-job preparation remains an external real binding.
 * That binding may BEGIN preparation only after WC_WAIT_RESUME, while retaining
 * the same owned identity and serialization. Receipt arrival after retirement
 * does not establish when its work was actually performed: an old preparation
 * withheld under the same token is not fresh proof. No preparation is issued
 * by this API and no default scheduler success exists.
 * Consumes its original immutable preparation through READY and atomic final
 * wsc_commit_health. Stale preparation never borrows newer token/revision bits.
 */
bool wc_resume_prepared(wc_owner *owner, const wc_resume_receipt *original,
                        const volatile uint32_t *current_revision, uint32_t now);
/* All HOLD completions must use this gate, not call wa_physical_done directly.
 * STOP/RELEASE still require their existing physical drain/preservation bits.
 * START remains exclusively the first verified wa_observe delivery.
 */
bool wc_physical_done(wc_owner *owner, const wa_physical_receipt *original,
                      uint32_t now);
#endif
