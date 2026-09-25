#ifndef WHIP_STOCK_BINDING_H
#define WHIP_STOCK_BINDING_H
#include <stdbool.h>
#include <stdint.h>

/* OFFLINE exact-stock ABI shim, UNATTACHED and not part of an OTA candidate.
 * Only for stock hash b58fd303...b750b0 at file-to-runtime bias 0x825fb0.
 * Caller must already prove task context, shared lifecycle serialization and
 * absence of late RUN/queued work. No initialization, timer cancellation,
 * Health-state change, allocator, automatic bus recovery or readiness claim.
 * This does NOT establish physical emitter-off and must never by itself create
 * a successful wh_stopped/wa_optics_stopped receipt.
 */
#define WB_NOT_ATTEMPTED UINT32_MAX
typedef struct {
    uint32_t mutex_taken; /* vendor bool normalized to 0 or 1, NOT raw ROM r0 */
    uint32_t reset_bus_status;
    uint32_t stop_bus_status;
    uint32_t mutex_released; /* vendor bool normalized to 0 or 1 */
} wb_stop_report;

/* Hold stock I2C mutex once, submit RESET then STOP with two stack bytes via
 * the exact caller-buffer bus routine, always attempt STOP after RESET status,
 * and preserve both bus statuses plus mutex release. True means only that the
 * calls reported both writes successful AND mutex release succeeded.
 * Any false result leaves real lifecycle success unproved. No retry loop.
 */
bool wb_stock_stop_writes(wb_stop_report *report);
#endif
