#ifndef WHIP_UNIFIED_WIRE_H
#define WHIP_UNIFIED_WIRE_H
#include <stdbool.h>
#include <stdint.h>

/* Shared byte-wise little-endian primitives. Caller owns a readable/writable
 * four-byte span; unaligned addresses are valid. No frame validation here. */
uint32_t ww_get32(const uint8_t *p);
void ww_put32(uint8_t *p, uint32_t value);

/* OFFLINE protocol candidate for a DISTINCT, reviewed GATT service only.
 * NOT a legacy UART opcode, discovery probe, registered service or BLE driver.
 * CRC detects corruption, not authentication. No hardware action in this file.
 * A binding must prove build authorization, boot/connection identity, serialized
 * ownership, no request-ID reuse, admission, physical completion and backpressure.
 */
#define WW_FRAME_BYTES 20u
#define WW_BODY_BYTES 20u
#define WW_CONTROL_BYTES 40u
#define WW_TIMEOUT_MS 1000u
enum { WW_REQUEST = 1, WW_REPLY = 2, WW_MOTION = 3 };
enum { WW_STATUS = 1, WW_HEALTH = 2, WW_GESTURE = 3, WW_RENEW = 4 };
enum { WW_MORE = 0, WW_DONE = 1, WW_REJECT = 2 };
typedef struct {
    uint32_t id, connection, boot_lo, boot_hi, started;
    uint8_t kind, next, state, operation;
    uint8_t body[WW_BODY_BYTES];
} ww_rx;

uint16_t ww_crc(const uint8_t *bytes, uint32_t length);
bool ww_body_valid(uint8_t kind, const uint8_t *body, uint32_t length,
                   uint32_t boot_lo, uint32_t boot_hi);
/* Encodes ONE 20-byte fragment. Caller retains a stable validated body across
 * the two sends; part must be 0 or 1. No duplicate 40-byte stack scratch. */
bool ww_pack_control(uint8_t kind, uint32_t id, const uint8_t *body,
                     uint32_t length, uint8_t part, uint8_t *frame);
void ww_rx_begin(ww_rx *r, uint8_t kind, uint32_t id, uint32_t connection,
                 uint32_t boot_lo, uint32_t boot_hi, uint8_t operation, uint32_t now);
/* connection is captured when the callback is scheduled, NOT reassigned on
 * delivery. Reject poisons the assembler until a new, explicitly bound begin.
 * Only WW_DONE permits publication of body; fragments are never a mode reply.
 */
uint8_t ww_rx_feed(ww_rx *r, const uint8_t *frame, uint32_t length,
                   uint32_t connection, uint32_t now);
bool ww_pack_motion(uint32_t session, uint32_t sequence,
                    const int16_t *model_xyz, uint8_t *frame);
#endif
