#include "discovery.h"
#include "wire.h"

bool wdi_encode(uint8_t *out, uint32_t boot_lo, uint32_t boot_hi,
                uint32_t build_lo, uint32_t build_hi) {
    if (!out || !(boot_lo | boot_hi) || !(build_lo | build_hi)) return false;
    out[0] = 0x57; out[1] = 0x49; out[2] = 1; out[3] = 0;
    ww_put32(out + 4, boot_lo);
    ww_put32(out + 8, boot_hi);
    ww_put32(out + 12, build_lo);
    ww_put32(out + 16, build_hi);
    return true;
}

bool wdi_read(const uint8_t *value, uint32_t offset, wdi_span *out) {
    if (!out) return false;
    out->value = 0; out->length = 0;
    if (!value || offset) return false;
    out->value = value; out->length = WDI_BYTES;
    return true;
}
