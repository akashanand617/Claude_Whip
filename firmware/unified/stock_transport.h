#ifndef WHIP_STOCK_TRANSPORT_H
#define WHIP_STOCK_TRANSPORT_H
#include <stdbool.h>
#include <stdint.h>

/* UNATTACHED, exact stock RT02CR_3.12.02 only; NOT a registered service.
 * File SHA256 b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0.
 * Caller must prove service/table lifetime, stack context, identity, placement,
 * subscription/MTU, admission, captured send ownership and disconnect fencing.
 * No ability to use these wrappers on V2/25 Hz or any unapproved linked image.
 */
typedef struct { uint32_t read, write, cccd; } wg_callbacks;
/* Database has entry_count reviewed 28-byte entries; callback addresses are 32-bit Thumb
 * pointers or zero. Neither syntax check attests the table or memory ownership.
 * service output is 0xff on ANY failure. SDK callback structure is BY VALUE.
 */
bool wg_stock_add(uint8_t *service, const uint8_t *database, uint16_t entry_count,
                   const wg_callbacks *callbacks);
/* Only stack submission acceptance, NEVER delivery/physical completion.
 * Caller owns 20 readable, non-overlapping bytes with a reviewed stack lifetime.
 * The legacy 16-byte UART queue is not called. No retry or busy waiting.
 */
bool wg_stock_notify20(uint8_t connection, uint8_t service, uint16_t attribute,
                      const uint8_t *frame);
#endif
