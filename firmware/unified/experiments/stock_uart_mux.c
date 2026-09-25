#include "wire.h"
#include <stdint.h>

typedef void (*receive_fn)(const uint8_t *, uint32_t);

/* SIZE/ROUTING EXPERIMENT ONLY. The eventual binding must synchronously copy
 * the frame with its original connection generation and arrival timestamp.
 * It is deliberately undefined here; a current-connection lookup is unsafe. */
void wum_post20(const uint8_t *frame);

void wlg_receive(const uint8_t *packet, uint32_t length) {
    if (!packet) return;
    /* Stock accepts only 16 bytes. A versioned 20-byte request can therefore
     * be demultiplexed before the stateful legacy prelude without stealing an
     * accepted Health packet. Malformed unified frames stay on the validator's
     * fail-closed path instead of becoming speculative legacy commands. */
    if (length == WW_FRAME_BYTES && packet[0] == 0x57u &&
        packet[1] == 1u && packet[2] == WW_REQUEST) {
        wum_post20(packet);
        return;
    }
    if (*(volatile const uint8_t *)(uintptr_t)0x208c44u == 1u) return;
    if (length == 16u) {
        uint8_t opcode = packet[0];
        if (opcode == 0xa1u || opcode == 0xbfu ||
            opcode == 0xceu || opcode == 0xcdu) return;
    }
    ((receive_fn)(uintptr_t)0x82bbd3u)(packet, length);
}
