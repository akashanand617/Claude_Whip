/* Size witnesses are test-only. Execute the SAME freestanding EABI primitives
 * as the real-address placement link, not duplicate test-only replacements.
 * This still does not provide ring startup or an allocated RAM region.
 */
#include <stddef.h>
#include "runtime.h"
#include "dispatch.h"
#include "stock_timer_fence.h"
#include "../../firmware/unified/compiler_runtime.c"
unsigned proof_runtime_size(void) { return sizeof(wr_runtime); }
unsigned proof_tap_offset(void) { return offsetof(wr_runtime, tap); }
unsigned proof_tap_size(void) { return sizeof(wt_tap); }
unsigned proof_tap_sequence_offset(void) { return offsetof(wt_tap, sequence); }
unsigned proof_pending_offset(void) { return offsetof(wr_runtime, pending); }
unsigned proof_sent_offset(void) { return offsetof(wr_runtime, last_sent); }
unsigned proof_dispatch_context_size(void) { return sizeof(wd_dispatch); }
unsigned proof_source_profile_size(void) { return sizeof(ws_profile); }
unsigned proof_source_receipt_size(void) { return sizeof(ws_receipt); }
unsigned proof_source_delivery_size(void) { return sizeof(ws_delivery); }
unsigned proof_source_delivery_frames(void) { return WS_DELIVERY_FRAMES; }
unsigned proof_timer_fence_size(void) { return sizeof(wf_timer_fence); }
