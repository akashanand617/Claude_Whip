#ifndef WHIP_STOCK_SCHEDULE_SETTINGS_H
#define WHIP_STOCK_SCHEDULE_SETTINGS_H
#include <stdint.h>

/* Unattached, exact STOCK-only read primitive; NOT a resume/eligibility receipt.
 * Packs four current bytes, least-significant first:
 *   HR interval, all schedule-control bits, operating mode, time-set gate.
 * The five reviewed enables are bits 0..4 of the second byte. Preserve other
 * bits too: their changes must not be hidden by a partial settings comparison.
 *
 * No settings writes, timer operations, old-mask replay, clock/history changes,
 * static RAM, heap or RTOS calls. The bounded read preserves caller PRIMASK.
 * Normal maskable writers cannot interleave; NMI/debug/DMA/reset writers are
 * outside this contract. Caller must prove exact image/map and initialization.
 *
 * This is only the controls for five scheduled optical jobs, not every Health
 * setting, a monotonic revision, or proof that any measurement is due. Final
 * resume must recheck current controls and all other eligibility in its proven
 * serialization domain. A read followed by an unlocked commit is insufficient.
 */
uint32_t wss_read_controls(void);

#endif
