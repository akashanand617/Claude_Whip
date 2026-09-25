#ifndef WHIP_STOCK_OPTICAL_WORK_H
#define WHIP_STOCK_OPTICAL_WORK_H
#include "health_adapter.h"

/* Unattached exact-STOCK optical work binding, not a deployable adapter.
 * Caller proves stock identity, initialized/lifetime-owned buffer/status objects,
 * complete inventory, and serialization of all job/physical lifecycle writers.
 * NMI/HardFault/DMA must not mutate these objects. Never stamp a current ticket
 * onto old work. No production inventory or RAM allocation is made here.
 *
 * All calls must be in thread mode with interrupts initially enabled. The read
 * releases PRIMASK before stock's blocking mutex/I2C path. Its in-flight job bit
 * prevents cancellation/fence/STOP receipts until that operation has returned.
 * wh_run_begin/end's legacy name also covers this shared-sensor I/O operation;
 * another RUN/read for the same job is forbidden until it finishes.
 *
 * Read preserves stock's nonzero signed statuses. A would-be zero success is
 * replaced by WOP_REJECTED if stale/unavailable. The supplied object pointers
 * must also match the live stock registration slots; equality is not ownership.
 * Only zero can be a candidate for NEW sample use. Zero still does NOT prove
 * physical FIFO timing, complete delivery, acquisition epoch or algorithm/job
 * provenance; it must never directly set wrc_commit_hr's measured argument.
 * It is not a lasting permission: pause can occur immediately after return.
 * Downstream consumers/commits must retain and recheck the original ticket.
 * Transport/invalid/partial-result faults latch WH_FAULT. Stock -2 (no data)
 * and -3 (not yet a complete group) reject new sample use without faulting Health.
 * No cursor rollback/retry: the sensor operation may already have side effects.
 * A callee that unexpectedly returns with interrupts masked faults Health and
 * keeps that returned mask; this binding does not enable an unknown critical
 * section. On unmodified stock the FE-write allocator/ignored release status
 * remain. The separately checked two-call-site woi_samples_io plan removes
 * those two wrapper defects only when BOTH edits are integrated; this wrapper
 * alone does not install or attest them. Object lifetime, RTOS and peripheral
 * preconditions remain even with that plan. Fixture success is not approval.
 */
#define WOP_REJECTED INT32_MIN
int32_t wop_read(wh_adapter *h, wh_ticket original, uint8_t *buffer, uint8_t *status);

/* After fully evidenced quiet in PAUSED or RESUMING, before READY. Partial
 * entry recovery must supply fresh cancellation/fence/STOP evidence under its
 * new resume token/generation; a state name alone never permits retirement.
 * Unconditionally retires the stock
 * software sample arrays via its bounded clear routine, then clears four
 * acquisition flags. Unlike stock's unwrapped helper this cannot silently skip
 * retirement merely because readiness was zero. Keeps config, cursors, settings,
 * published HR cache and steps/sleep state; does not flush hardware FIFO or prove
 * a new acquisition epoch. No bus/RTOS/heap call under PRIMASK.
 */
bool wop_retire(const wh_adapter *h, uint32_t token, uint8_t *buffer, uint8_t *status);
#endif
