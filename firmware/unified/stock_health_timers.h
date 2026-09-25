#ifndef WHIP_STOCK_HEALTH_TIMERS_H
#define WHIP_STOCK_HEALTH_TIMERS_H
#include <stdint.h>

/* Exact STOCK reviewed optical-producer timers, NOT a full Health adapter.
 * Caller must first close all creation/restart/deletion admissions and own the
 * serialization domain through this call. It must prevent timer-pool reuse,
 * including queued deletes, between validation and ROM enqueue. PRIMASK alone
 * is NOT that domain. This component remains unattached until it is proved.
 *
 * Does not stop the motion driver, delete timer objects, clear health working
 * state, write settings/clock/history or synthesize cancellation/STOP receipts.
 * An empty slot is NOT evidence that an earlier callback has drained. Accepted
 * STOPs still require the timer barrier AND hub/IRQ/RUN/result fences. This
 * list covers reviewed timer slots, NOT a closed producer/result inventory.
 * In particular, activity and wear timers can have non-optical obligations;
 * exposing checked cancellation is NOT approval to pause all of them in a
 * production mode switch. Their preserved-state/fresh-resume bindings remain
 * mandatory. No main motion-driver timer is included.
 */
typedef enum { WHT_HR, WHT_SPO2, WHT_OWNER_200, WHT_OWNER_100, WHT_OWNER_1000,
               WHT_SCHEDULED_COUNT,
               WHT_REALTIME = WHT_SCHEDULED_COUNT, WHT_ON_DEMAND_1E,
               WHT_WEAR, WHT_ACTIVITY, WHT_RAW,
               WHT_INDICATOR_BRIGHTNESS, WHT_INDICATOR_PATTERN,
               WHT_REVIEWED_COUNT } wht_job;
typedef enum { WHT_EMPTY, WHT_ACCEPTED, WHT_REFUSED, WHT_QUEUE_FAILED } wht_result;

/* One nonblocking STOP, no automatic retry. Only exact return 1 is accepted.
 * Refuses ISR/masked context, bad job, invalid queue and invalid/free pool entry.
 * No resume API: restarting old handles wholesale would replay stale work.
 * Current-settings eligibility and fresh-job restart need separate bindings.
 */
wht_result wht_stop_scheduled(uint32_t job);
/* Same checked primitive for any of the reviewed slots. Does not cancel a
 * collection, acknowledge quiescence or restart an old job. Callers retain and
 * handle each individual failure; no best-effort cancel-all hides a failure.
 */
wht_result wht_stop_reviewed(uint32_t job);
#endif
