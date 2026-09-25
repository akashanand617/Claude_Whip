/* Artificial-address test memory only, never a stock RAM allocation. */
#include <stddef.h>
#include "wire.h"
typedef struct { ww_rx rx; uint8_t output[WW_CONTROL_BYTES]; } proof_wire;
unsigned proof_wire_size(void) { return sizeof(proof_wire); }
unsigned proof_wire_output_offset(void) { return offsetof(proof_wire, output); }
unsigned proof_wire_body_offset(void) { return offsetof(ww_rx, body); }

/* Host-side reference decoder, not ring code: the ring only emits motion.
 * The production inbound control path still validates every request/CRC.
 * Keep compiled ARM/Swift decoder parity coverage without linking an unused
 * host receiver into the firmware append region. */
bool ww_motion_valid(const uint8_t *p, uint32_t length, uint32_t session) {
    if (!p || length != WW_FRAME_BYTES || p[0] != 0x57u ||
        p[1] != 1u || p[2] != WW_MOTION) return false;
    return ww_crc(p, 18) == (uint16_t)((uint16_t)p[18] | ((uint16_t)p[19] << 8)) &&
        p[3] == 0 && session != 0 && ww_get32(p + 4) == session && ww_get32(p + 8) != 0;
}
