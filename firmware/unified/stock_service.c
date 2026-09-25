#include "stock_service.h"
#include <stddef.h>

_Static_assert(sizeof(void *) == 4, "reviewed ARM32 ABI only");
_Static_assert(sizeof(wgd_attribute) == 28, "stock attribute stride");
_Static_assert(_Alignof(wgd_attribute) == 4, "stock attribute alignment");
_Static_assert(offsetof(wgd_attribute, flags) == 0, "flags ABI");
_Static_assert(offsetof(wgd_attribute, type_value) == 2, "type/value ABI");
_Static_assert(offsetof(wgd_attribute, value_len) == 18, "length ABI");
_Static_assert(offsetof(wgd_attribute, value) == 20, "value pointer ABI");
_Static_assert(offsetof(wgd_attribute, permissions) == 24, "permissions ABI");

/* GATT UUID byte order, not Microsoft's mixed-endian GUID representation.
 * Development service 33cdf03c-77d9-458b-aedf-12a7a189ef20;
 * RX/TX/discovery differ only in the final octet: 21/22/23.
 * Primary uses a 16-bit type (0x2800) with an external 128-bit VALUE.
 * Characteristic values use inline 128-bit TYPES, supplied by the application.
 */
#define UUID_LE(last) {last, 0xef, 0x89, 0xa1, 0xa7, 0x12, 0xdf, 0xae, \
                       0x8b, 0x45, 0xd9, 0x77, 0x3c, 0xf0, 0xcd, 0x33}
const uint8_t wgd_service_uuid[16] = UUID_LE(0x20);

/* Exact stock six-entry RX/TX shape, followed by a separate read-only
 * discovery declaration/value. VALUE_APPL and null pointers do not invent
 * storage or make callbacks optional. Permissions mirror the stock transport;
 * no cryptographic identity, pairing or authorization is supplied here.
 * All unspecified bytes are zero, including the default disabled CCCD.
 */
const wgd_attribute wgd_database[WGD_ATTRIBUTES] = {
    {0x0800, {0x00, 0x28},       16, wgd_service_uuid, 0x0001},
    {0x0002, {0x03, 0x28, 0x0c}, 1, 0,                0x0001},
    {0x0005, UUID_LE(0x21),       0, 0,                0x0010},
    {0x0002, {0x03, 0x28, 0x10}, 1, 0,                0x0001},
    {0x0005, UUID_LE(0x22),       0, 0,                0x0100},
    {0x0012, {0x02, 0x29},       2, 0,                0x0011},
    {0x0002, {0x03, 0x28, 0x02}, 1, 0,                0x0001},
    {0x0005, UUID_LE(0x23),       0, 0,                0x0001},
};
