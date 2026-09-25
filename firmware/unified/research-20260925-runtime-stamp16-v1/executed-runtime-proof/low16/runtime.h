#ifndef WHIP_RUNTIME_H
#define WHIP_RUNTIME_H
#include "mode_controller.h"
#include "sample_tap.h"

/* Integrated OFFLINE runtime, not a stock/RTOS or BLE adapter.
 * Every call belongs to ONE serialized task. Physical actions remain explicit
 * in mode.action/token; completion must verify their physical postconditions.
 * No boot hook, addresses, wire opcodes or allocation are supplied here.
 */
typedef struct {
    wm_controller mode;
    wt_tap tap;
    wt_sample pending;
    uint32_t last_sent;
    bool awaiting_send, have_sent;
    uint16_t queued_at[WT_CAPACITY];
    uint32_t pending_at, last_source_at;
    bool have_source;
} wr_runtime;

/* Matches the app's bounded-latency stream contract; not a ring measurement.
 * The real source must deliver frequently enough or Gesture fails closed.
 */
#define WR_MAX_SAMPLE_AGE_MS 250u
/* A live head has at most31 later successful positive-count offers.
 * Each advances source by at most249ms; wr_next adds at most249.
 * Bound:32*249=7968, strictly below the low16 modulus. This
 * requires runtime-exclusive tap ownership and current cleanup.
 * Keep pending_at full32: awaiting-send time is not re-encoded. */
_Static_assert(WR_MAX_SAMPLE_AGE_MS > 0u, "positive horizon");
_Static_assert(WT_CAPACITY > 0u && WT_CAPACITY <= UINT8_MAX, "count fits");
_Static_assert((uint64_t)WT_CAPACITY * (WR_MAX_SAMPLE_AGE_MS - 1u) <= UINT16_MAX,
               "live FIFO ages must fit losslessly in low16");

/* Once per boot, after successful stock Health initialization. */
void wr_init(wr_runtime *r);
void wr_tick(wr_runtime *r, uint32_t now);
void wr_link(wr_runtime *r, bool connected, bool charging, uint32_t now);
bool wr_request(wr_runtime *r, bool gesture, uint32_t now);
/* source_baseline is the last reviewed Gesture acquisition ID at START_25HZ;
 * only relevant to successful START. The tap starts before publishing Gesture;
 * the first verified acquisition must arrive within WR_MAX_SAMPLE_AGE_MS.
 */
bool wr_complete(wr_runtime *r, uint32_t token, bool success,
                 uint32_t source_baseline, uint32_t now);
/* Called only by the reviewed fresh 25 Hz source; this runtime does not convert
 * the stock FIFO ODR. False verification, a missing batch or overflow requests
 * cleanup; it never changes stock Health's acquisition or cursor. oldest_at is
 * the oldest physical acquisition time in the batch, NOT callback arrival time.
 * Each queued entry conservatively inherits it. Only a reviewed source may
 * assert this timestamp; stock raw notifications do not provide it.
 */
wt_result wr_offer(wr_runtime *r, uint32_t session, uint32_t acquisition,
                   const wt_axes *batch, uint8_t count, bool verified,
                   uint32_t oldest_at, uint32_t now);
/* At most one notification is in flight. Adapter must revalidate the generation
 * at the actual BLE enqueue, not only when taking the sample here. Return/STOP
 * must fence queued transport work. sent=true means the reviewed enqueue
 * succeeded, not that the phone processed it. A subsequent heartbeat proves
 * processing and cannot claim a sequence that has not been sent.
 */
bool wr_next(wr_runtime *r, uint32_t session, wt_sample *sample, uint32_t now);
bool wr_sent(wr_runtime *r, uint32_t session, uint32_t sequence, bool success, uint32_t now);
bool wr_renew(wr_runtime *r, uint32_t session, uint32_t processed_sequence, uint32_t now);
#endif
