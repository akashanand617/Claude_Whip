#ifndef WHIP_STOCK_TIMER_FENCE_H
#define WHIP_STOCK_TIMER_FENCE_H
#include <stdbool.h>
#include <stdint.h>

/* Exact RTL8762E timer-daemon binding candidate, not installed hooks.
 * A callback through this API proves ONLY passage through the timer queue,
 * conditional on the audited ROM FIFO semantics. Before request, all relevant
 * timer stop/delete commands must have been accepted and restart admissions
 * closed. Hub work, IRQs, RUN writes and publications need their own fences.
 * Never convert this receipt alone into wh_fenced or physical STOP.
 * Storage must live for the whole boot, including after abandon/timeouts.
 */
typedef struct {
    volatile uint32_t issued, acknowledged;
    volatile uint8_t pending, accepted, fault, enqueuing;
} wf_timer_fence;

/* Exactly once per boot, before any callback can exist. */
void wf_init(wf_timer_fence *f);
/* Task context with interrupts enabled, one nonblocking request, no retry.
 * IDs are nonzero/strictly increasing. Queue rejection permanently faults this
 * instance, as does an absent stock timer queue (ROM would assert). The queue
 * must already exist and remain alive for this boot. This is not a scheduler
 * or queue-lifetime proof; reboot/reinit is NOT automatic recovery.
 */
bool wf_request(wf_timer_fence *f, uint32_t ticket);
/* Consume only an acknowledged AND accepted request. Safe under preemption;
 * early callback during enqueue cannot create an early success receipt.
 */
bool wf_complete(wf_timer_fence *f, uint32_t ticket);
/* Reject late completion without freeing/reusing the object's storage.
 * If enqueue is still in flight, a new request remains refused until it returns.
 */
bool wf_abandon(wf_timer_fence *f, uint32_t ticket);
#endif
