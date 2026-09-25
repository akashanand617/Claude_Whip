#ifndef WHIP_CONTROL_MAILBOX_H
#define WHIP_CONTROL_MAILBOX_H
#include <stdbool.h>
#include <stdint.h>
#include "wire.h"

/* UNATTACHED control-input handoff, not a complete firmware owner/transport.
 * Two fixed slots (one complete fragmented command), bounded PRIMASK-preserving
 * copies, no allocation or RTOS call. Not an arbitrary backlog of commands.
 * It NEVER calls the dispatcher/coordinator and NEVER creates physical receipts.
 * Producers may be tasks or maskable IRQs on the reviewed single-core MCU;
 * NMI, HardFault and DMA must never mutate this mailbox (PRIMASK cannot fence them).
 * The consumer and open/retire operations belong to one serialized owner.
 * All nonnull pointers must refer to valid, disjoint objects of their declared
 * size; a frame input must remain readable for its 20-byte synchronous copy.
 * This module cannot validate arbitrary firmware pointers or physical lifetime.
 */
enum { WIM_NONE, WIM_FRAME, WIM_CLOSED };
enum { WIM_LINK_LOST = 4u, WIM_CHARGING = 8u, WIM_FAULT = 16u };
typedef struct {
    uint32_t generation;
    uint32_t flags; /* private; never use these bits as a mode/capability */
    struct { uint32_t received; uint8_t frame[WW_FRAME_BYTES]; } slots[2];
} wim_mailbox;
typedef struct {
    uint32_t generation, received;
    uint8_t frame[WW_FRAME_BYTES];
    uint32_t reasons; /* zero for FRAME; close reasons for CLOSED */
} wim_event;

/* Initialize once per boot, before any producer or retained callback exists. */
void wim_init(wim_mailbox *m);
/* New generation must increase, never wrap/reuse. Only after old physical
 * callbacks/sends are fenced and the closed old mailbox has been retired. */
bool wim_open(wim_mailbox *m, uint32_t generation);
/* Exactly one 20-byte frame per call, at most two queued; no overwrite or
 * coalescing. Sender must wait for a complete reply before another command.
 * Current-generation overflow/bad input closes this mailbox and drops its
 * pending frame; it does NOT mutate a newer generation on stale input.
 * A false result may have latched CLOSE: wake/service the consumer on rejected
 * current traffic too. Clock is captured at arrival; caller qualifies units.
 */
bool wim_post(wim_mailbox *m, uint32_t generation, const uint8_t *frame,
              uint32_t length, uint32_t received);
/* Close outranks an undelivered frame; reasons accumulate until retirement.
 * It cannot retract a frame already copied to a consumer or an in-flight send.
 * The real binding must still revalidate ownership at actual operation commit.
 */
bool wim_close(wim_mailbox *m, uint32_t generation, uint32_t reasons);
/* Snapshot only, not a lease. A consumer may hold its own outer PRIMASK section
 * across this query and a bounded pure-software commit; never across ROM/RTOS,
 * coordinator/hardware or a blocking call. It cannot authorize a later send.
 */
bool wim_admitted(const wim_mailbox *m, uint32_t generation);
/* At most one event, copied while interrupts are masked; no core operation
 * runs under that mask. Close is emitted once per newly added reason set.
 * Current frame older than WW_TIMEOUT_MS closes with FAULT before delivery.
 * now must be the consumer's fresh monotonic ms sample, with intervals <2^31.
 * NONE/null refusal leaves out untouched. FRAME retains its original generation
 * and arrival time. CLOSED retains generation but zeroes payload/arrival time;
 * callers must branch on the returned event kind.
 */
uint32_t wim_take(wim_mailbox *m, uint32_t now, wim_event *out);
/* Logical retirement only after the close has been consumed AND the caller
 * has genuinely fenced its physical callbacks/sends. Does not prove that fence.
 */
bool wim_retire(wim_mailbox *m, uint32_t generation);
#endif
