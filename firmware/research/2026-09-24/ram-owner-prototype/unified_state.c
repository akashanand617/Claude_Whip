/* SCRATCH PROTOTYPE, not a repo source. Candidate static owner for unified
 * state in the post-boot BootOnce overlay + gap region (docs/UNIFIED_RAM_OWNERSHIP.md).
 * Stock startup never clears this region: uw_state_init must run once per
 * boot, after stock pre_main/Health init, before any other unified call.
 */
#include <stddef.h>
#include "dispatch.h"
#include "stock_timer_fence.h"
#include "stock_health_commit.h"
#include "stock_coordinator.h"

void __aeabi_memclr4(void *destination, size_t length);

typedef struct {
    wd_dispatch dispatch;
    uint8_t frame[WW_FRAME_BYTES];
    wf_timer_fence fence;
    wc_owner coordinator;
    wc_stop_receipt stop;       /* asynchronous STOP-observer receipt */
    wc_resume_receipt resume;   /* contains wsc_prepared; synchronous, may live on stack */
    uint32_t settings_revision; /* monotonic revision owner (UNIFIED_HEALTH_COMMIT) */
    ws_receipt receipt;
} uw_state;

static uw_state g_state __attribute__((section(".bss.unified_state"), aligned(8)));

/* Clears the whole owned region; the caller then runs wd_init/wf_init. */
uw_state *uw_state_claim(void) {
    __aeabi_memclr4(&g_state, sizeof g_state);
    return &g_state;
}
