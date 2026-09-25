#include "stock_legacy_gate.h"

typedef void (*receive_fn)(const uint8_t *, uint32_t);

void wlg_receive(const uint8_t *packet, uint32_t length) {
    if (!packet) return;
    if (*(volatile const uint8_t *)(uintptr_t)0x208c44u == 1u) return;
    if (length == 16u) {
        uint8_t opcode = packet[0];
        if (opcode == 0xa1u || opcode == 0xbfu || opcode == 0xceu || opcode == 0xcdu) return;
    }
    ((receive_fn)(uintptr_t)0x82bbd3u)(packet, length);
}
