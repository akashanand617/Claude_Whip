#ifndef WHIP_SAMPLE_TAP_H
#define WHIP_SAMPLE_TAP_H
#include <stdbool.h>
#include <stdint.h>

/* OFFLINE COMPONENT, NOT A STOCK ADAPTER.
 * One serialized owner; caller supplies a verified fresh acquisition batch.
 * Never pass cached raw-reader results or infer freshness from BLE arrivals.
 * No sensor I/O, stock pointers/cursors, timer changes, NVM or allocation here.
 * Queue failure affects Gesture only; caller must initiate mode cleanup.
 */
#define WT_CAPACITY 32u

typedef struct { int16_t axis[3]; } wt_axes; /* native driver order, NOT wire XYZ */
typedef struct { uint32_t sequence; wt_axes value; } wt_sample;
typedef enum {
    WT_OK, WT_STALE_SESSION, WT_BAD_ACQUISITION, WT_OVERFLOW, WT_SEQUENCE_EXHAUSTED
} wt_result;
typedef struct {
    /* FIFO entries have contiguous, nonwrapping session sequences. Store only
     * axes: the oldest sequence is sequence - count + 1. Capacity, ordering and
     * public wt_sample output are unchanged. No packed/unaligned word fields.
     */
    wt_axes queue[WT_CAPACITY];
    uint32_t session, acquisition, sequence;
    uint8_t head, count;
    bool active;
    wt_result fault;
} wt_tap;

/* Only after boot; session IDs must never repeat during this boot. */
void wt_init(wt_tap *tap);
/* Start AFTER physical entry verification, with last acquisition as a baseline.
 * Only strictly newer sessions can start; stop/fault cannot be undone by replay.
 * A uint32 acquisition counter may wrap using serial-number arithmetic.
 */
bool wt_start(wt_tap *tap, uint32_t session, uint32_t last_acquisition);
void wt_stop(wt_tap *tap, uint32_t session);
/* An all-or-nothing independent copy; never advances a stock health cursor.
 * verified=false covers failed I2C, hardware FIFO overflow, lost ownership or
 * unknown cadence. Even stock producer advancement alone is NOT sufficient.
 * Zero-length, replayed, missing or out-of-order batch IDs fail the session.
 * Immutable batch storage must remain valid for the duration of this call.
 */
wt_result wt_offer(wt_tap *tap, uint32_t session, uint32_t acquisition,
                   const wt_axes *batch, uint8_t count, bool verified);
bool wt_take(wt_tap *tap, uint32_t session, wt_sample *sample);
#endif
