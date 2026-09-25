#ifndef WHIP_FRESH_SOURCE_H
#define WHIP_FRESH_SOURCE_H
#include "sample_tap.h"

/* OFFLINE evidence validator/selector, NOT an installed physical adapter.
 * There is deliberately NO qualified stock profile in this repository.
 * One serialized observer copies existing Health-owned FIFO transactions;
 * it must never read/drain/reconfigure the sensor or advance Health's cursor.
 * Profile metadata references independently reviewed physical measurements;
 * this component validates consistency, not the authenticity of those claims.
 */
#define WS_FIFO_FRAMES 32u
#define WS_PERIOD_MS 40u
#define WS_MAX_AGE_MS 250u
_Static_assert(WS_MAX_AGE_MS > 0u && WS_PERIOD_MS > 0u, "nonzero source time bounds");
_Static_assert(WS_MAX_AGE_MS <= UINT8_MAX + 1u, "receipt ages must fit without truncation");
/* Earliest endpoints all lie in one <250ms window. At worst its first
 * endpoint has phase 39 within a 40ms bucket: floor((249+39)/40)+1 = 8.
 * This bounds temporary selection scratch, NOT FIFO/tap/transport capacity.
 * It does not assume a nominal physical sensor cadence or exact timestamps.
 */
#define WS_DELIVERY_FRAMES ((WS_MAX_AGE_MS - 1u + WS_PERIOD_MS - 1u) / WS_PERIOD_MS + 1u)
_Static_assert(WS_DELIVERY_FRAMES <= WS_FIFO_FRAMES, "delivery bound must fit input capacity");
typedef struct {
    uint32_t config_epoch, binding_id;
    uint8_t evidence_sha256[32];
    uint32_t observed_frames, observed_span_ms;
    uint16_t minimum_period_ms, maximum_period_ms;
    uint8_t timestamp_uncertainty_ms;
    uint8_t chip_id, range, bandwidth, power, fifo_config;
} ws_profile;

typedef struct { uint32_t earliest, latest; } ws_time_bound;
/* Lossless inside the existing <250 ms validity horizon. These are ages
 * relative to status_at, NOT quantized times or callback-arrival timestamps.
 * Use ws_set_bounds: unchecked u32->u8 casts could turn stale/future into fresh.
 */
typedef struct { uint8_t earliest_age, latest_age; } ws_age_bound;
typedef struct {
    uint32_t session, config_epoch, binding_id, transaction;
    /* Earliest possible time of the full status snapshot; completion is AFTER
     * the entire FIFO burst. Their span proves sufficient FIFO headroom even
     * if no frame was popped until completion. A post-read OVR=0 is NOT proof:
     * reading FIFO data clears OVR. Stock's full-32-frame case cannot pass.
     */
    uint32_t status_at, completed_at;
    uint16_t requested_bytes, completed_bytes;
    uint8_t fifo_status;       /* UNMASKED pre-read FIFOSTS, including bit 7 */
    uint8_t transport_result;  /* 0=proved complete; not stock's ignored result */
    uint8_t count;
    /* Original FIFO bytes, little-endian native axis order. Bounds describe
     * PHYSICAL acquisitions, never BLE/callback/queue arrival timestamps.
     * Byte-count completion and these bounds are unavailable in stock today.
     */
    uint8_t bytes[WS_FIFO_FRAMES * 6u];
    ws_age_bound acquired[WS_FIFO_FRAMES];
} ws_receipt;

typedef struct {
    wt_axes values[WS_DELIVERY_FRAMES];
    uint32_t session, acquisition, oldest_at;
    uint8_t count;
} ws_delivery;
typedef enum { WS_IGNORED, WS_ACCEPTED, WS_DELIVER, WS_FAULT } ws_result;
typedef struct {
    uint32_t last_earliest, last_latest, last_bucket;
    bool active, have_frame, have_bucket;
} ws_progress;
typedef struct {
    ws_profile profile;
    uint32_t session, transaction, acquisition, started_at;
    /* Transactional loop progress, separate from the immutable profile. */
    ws_progress progress;
} ws_source;

/* Numeric/identity consistency only. A nonzero digest is not attestation.
 * The real binding must allow ONLY an independently reviewed exact profile.
 */
bool ws_profile_valid(const ws_profile *profile);
/* Caller exclusively owns a receipt with its FINAL status_at already set.
 * Encodes exact millisecond bounds; no rounding. Invalid/reversed/future/stale
 * bounds poison transport_result, including an out-of-range index. Null fails.
 * Never reset that error or change status_at after encoding. No physical
 * provenance is inferred here. Zero-initialization is not acquisition evidence.
 */
bool ws_set_bounds(ws_receipt *receipt, uint32_t index,
                   uint32_t earliest, uint32_t latest);
void ws_init(ws_source *source);
/* Session IDs are boot-unique and strictly increasing; a stopped/failed
 * session cannot restart. START is not physically complete until DELIVER.
 * The first physical acquisition must occupy start's first 40 ms bucket.
 * profile is copied by value; it may be &source->profile. No caller pointer
 * survives the call. The entire replacement value is formed before assignment.
 */
bool ws_start(ws_source *source, uint32_t session,
              const ws_profile *profile, uint32_t now);
void ws_stop(ws_source *source, uint32_t session);
/* Every observed transaction, including empty FIFO snapshots, has consecutive
 * IDs starting at 1. Old sessions are ignored without touching current state.
 * Output is all-or-nothing, one original frame per 40 ms physical-time bucket;
 * no interpolation, duplicate suppression by value, or assumed decimation.
 * source, receipt and delivery must not overlap. The caller owns delivery
 * exclusively until return; no interrupt/concurrent consumer may inspect it.
 * Scratch output is cleared on rejection; publish only after WS_DELIVER.
 * An ambiguous/crossed or missing bucket, I2C failure, overflow, ownership/config
 * mismatch, stale frame or insufficient overflow headroom fails Gesture only.
 */
ws_result ws_observe(ws_source *source, const ws_receipt *receipt,
                     ws_delivery *delivery, uint32_t now);
/* False when inactive/faulted or acquisition evidence has become too old. */
bool ws_tick(ws_source *source, uint32_t now);
#endif
