#ifndef WHIP_CONTROL_OWNER_H
#define WHIP_CONTROL_OWNER_H
#include "control_mailbox.h"
#include "dispatch.h"
#include "stock_coordinator.h"

/* UNATTACHED task-owned control integration, not a physical executor or GATT
 * binding. Embed ONE dispatcher; all coordinator/receipt/send operations must
 * reference this same dispatcher.adapter in the same serialized task. Do not
 * run those physical operations inside this module's short PRIMASK sections.
 * Valid nonaliasing storage is a prerequisite, not allocated or proved here.
 */
typedef struct {
    wd_dispatch dispatch;
    wim_mailbox inbox;
    uint32_t first_arrival; /* valid only while dispatch.state == WD_RECEIVING */
    wc_owner coordinator;
    wc_stop_receipt stop; /* reusable submission output, NEVER a completion */
} wco_owner;
typedef struct {
    const volatile uint32_t *revision;
    uint8_t *buffer, *status;
} wco_stock;

/* Once per boot after stock Health and before any producers/callbacks. The
 * boot ID, inventory and source profile still require independent evidence.
 */
bool wco_init(wco_owner *o, uint32_t jobs, bool inventory_proven,
              uint32_t boot_lo, uint32_t boot_hi);
/* Only after genuine service admission and old physical callbacks/sends are
 * fenced; a closed old mailbox must already have been logically retired.
 * No command/session retry, automatic generation reuse or physical fence.
 */
bool wco_open(wco_owner *o, uint32_t generation, bool charging, uint32_t now);
/* Thread mode with IRQs enabled on entry. Samples at most two queued frames;
 * pure dispatcher/validation calls are serialized with producer latches under
 * one bounded PRIMASK section. All core calls see fresh current now, NEVER a
 * queued arrival timestamp. The first arrival independently anchors the whole
 * fragment deadline, including passes with no traffic. Future/backward queued
 * chronology refuses. Caller qualifies monotonic-ms clock and elapsed bounds.
 * No coordinator, ROM, RTOS, notification or hardware call occurs here.
 * This step is not a proof of periodic service, physical drain or Health resume.
 */
bool wco_step(wco_owner *o, uint32_t now);
/* Real C composition: fresh clock -> pure control step -> actual wc_pump with
 * interrupts enabled -> NEW clock/control step after any blocking stock work.
 * A phase invalidated by the second step returns WC_REJECTED. An asynchronous
 * STOP observer must COPY original identity at submission: stop is reused by
 * later submissions, so rereading it later would mislabel stale completion.
 * It is never a physical STOP/cancellation/fence receipt.
 * No completion APIs are called. All external receipts still need the same
 * task owner and a fresh control reconciliation before commit/publication.
 */
wc_result wco_service(wco_owner *o, const wco_stock *stock);

/* Mandatory strong bindings, deliberately undefined in this candidate.
 * Supply exactly one initialized, owned, boot/retention-qualified object and a
 * reviewed fresh monotonic clock. Never a guessed RAM address or constant time.
 * wuw_supervise is implemented here, so stock_supervisor_wait can call the real
 * dispatcher step; a whole link still refuses these missing physical bindings.
 */
extern wco_owner wco_bound_owner;
extern const wco_stock wco_bound_stock;
uint32_t wco_monotonic_ms(void);
void wuw_supervise(void);
#endif
