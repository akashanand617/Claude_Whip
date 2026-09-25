#ifndef WHIP_STOCK_LEGACY_GATE_H
#define WHIP_STOCK_LEGACY_GATE_H
#include <stdint.h>

/* UNATTACHED exact-STOCK receive guard, not an installed patch or capability.
 * Stock SHA256 b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0,
 * file-to-runtime bias 0x825fb0. Proposed call site: complete four-byte BL at
 * file 0x7b0a, original bytes fe f7 8a f8; target gate file 0x5c22, Thumb
 * address 0x82bbd3. No call site or diagnostic image is changed here.
 *
 * Caller owns a readable immutable packet and its lifetime through delegation.
 * NULL is rejected defensively. Stock mode==1 rejects before opcode access;
 * an opcode is read only for the FULL 32-bit length exactly equal to 16.
 * A1/BF/CE/CD are silently retired before any original receive prelude, with no
 * subcommand exceptions. All other eligible input is delegated with the original
 * pointer and untruncated length. Unified Gesture requires its separate qualified
 * source/service; there is no legacy A1 fallback. Ingress denial does not drain
 * queued work or retire existing raw timers/callbacks and does not own their code.
 * The original gate rechecks its volatile mode byte: this helper does not
 * serialize concurrent mode changes or replace the original mode gate.
 * Current app/V2 identification uses CD01 diagnostic reads. Dedicated unified
 * identity/discovery migration is a prerequisite to future attachment; this
 * candidate is not installed on stock/V2 and does not preserve a CD exception
 * or change those deployed images' raw/diagnostic behavior.
 *
 * No reply, state owner, settings revision, mode switch, authentication,
 * placement approval, packet storage or production attachment is supplied.
 */
void wlg_receive(const uint8_t *packet, uint32_t length);
#endif
