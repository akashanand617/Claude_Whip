#include "wire.h"

uint32_t ww_get32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
void ww_put32(uint8_t *p, uint32_t value) {
    for (unsigned i = 0; i < 4; ++i) p[i] = (uint8_t)(value >> (8u * i));
}
uint16_t ww_crc(const uint8_t *bytes, uint32_t length) {
    uint16_t crc = 0xffffu;
    for (uint32_t i = 0; i < length; ++i) {
        crc ^= (uint16_t)((uint16_t)bytes[i] << 8);
        for (unsigned bit = 0; bit < 8; ++bit)
            crc = (uint16_t)((crc << 1) ^ ((crc & 0x8000u) ? 0x1021u : 0u));
    }
    return crc;
}
static void seal(uint8_t *frame) {
    uint16_t crc = ww_crc(frame, 18);
    frame[18] = (uint8_t)crc;
    frame[19] = (uint8_t)(crc >> 8);
}
static bool frame_valid(const uint8_t *p, uint32_t length, uint8_t kind) {
    if (!p || length != WW_FRAME_BYTES || p[0] != 0x57u ||
            p[1] != 1u || p[2] != kind) return false;
    return ww_crc(p, 18) == (uint16_t)((uint16_t)p[18] | ((uint16_t)p[19] << 8));
}
bool ww_body_valid(uint8_t kind, const uint8_t *p, uint32_t length,
                   uint32_t boot_lo, uint32_t boot_hi) {
    if (!p || length != WW_BODY_BYTES || !(boot_lo | boot_hi) ||
            p[0] < WW_STATUS || p[0] > WW_RENEW) return false;
    if (kind == WW_REQUEST) {
        if (p[1] || p[18] || p[19] || ww_get32(p + 2) != boot_lo ||
                ww_get32(p + 6) != boot_hi) return false;
        uint32_t session = ww_get32(p + 10), sequence = ww_get32(p + 14);
        return p[0] == WW_RENEW ? session != 0 && sequence != 0 : session == 0 && sequence == 0;
    }
    if (kind != WW_REPLY || p[1] > 4u || p[2] > 4u || p[3] > 1u ||
            ww_get32(p + 4) != boot_lo || ww_get32(p + 8) != boot_hi || ww_get32(p + 16)) return false;
    uint32_t session = ww_get32(p + 12);
    /* State codes match wm_state. Health retains its latest session counter. */
    if ((p[2] == 1u || p[2] == 2u) && session == 0) return false;
    if (p[2] == 2u && p[3]) return false;
    if (p[1] != 0u || p[0] == WW_STATUS) return true;
    if (p[0] == WW_HEALTH) return p[2] == 0u;
    return p[2] == 2u; /* success is committed Gesture, never queued intent */
}
bool ww_pack_control(uint8_t kind, uint32_t id, const uint8_t *body,
                     uint32_t length, uint8_t part, uint8_t *frame) {
    if (!frame || !body || length != WW_BODY_BYTES || id == 0 || part > 1u ||
            (kind != WW_REQUEST && kind != WW_REPLY)) return false;
    unsigned boot = kind == WW_REQUEST ? 2u : 4u;
    if (!ww_body_valid(kind, body, length, ww_get32(body + boot), ww_get32(body + boot + 4))) return false;
    frame[0] = 0x57; frame[1] = 1; frame[2] = kind; frame[3] = part;
    ww_put32(frame + 4, id);
    for (unsigned i = 0; i < 10; ++i) frame[8 + i] = body[10u * part + i];
    seal(frame);
    return true;
}
static uint8_t reject(ww_rx *r) {
    r->state = WW_REJECT;
    for (unsigned i = 0; i < WW_BODY_BYTES; ++i) r->body[i] = 0;
    return WW_REJECT;
}
void ww_rx_begin(ww_rx *r, uint8_t kind, uint32_t id, uint32_t connection,
                 uint32_t boot_lo, uint32_t boot_hi, uint8_t operation, uint32_t now) {
    *r = (ww_rx){ .id = id, .connection = connection, .boot_lo = boot_lo,
                 .boot_hi = boot_hi, .started = now, .kind = kind, .operation = operation };
    if (!id || !connection || !(boot_lo | boot_hi) || operation < WW_STATUS || operation > WW_RENEW ||
            (kind != WW_REQUEST && kind != WW_REPLY))
        (void)reject(r);
}
uint8_t ww_rx_feed(ww_rx *r, const uint8_t *p, uint32_t length,
                   uint32_t connection, uint32_t now) {
    if (r->state != WW_MORE || connection != r->connection ||
            (uint32_t)(now - r->started) > WW_TIMEOUT_MS ||
            !frame_valid(p, length, r->kind) || p[3] != r->next || ww_get32(p + 4) != r->id)
        return reject(r);
    for (unsigned i = 0; i < 10; ++i) r->body[r->next * 10u + i] = p[8 + i];
    if (++r->next != 2u) return WW_MORE;
    if (r->body[0] != r->operation ||
            !ww_body_valid(r->kind, r->body, WW_BODY_BYTES, r->boot_lo, r->boot_hi)) return reject(r);
    r->state = WW_DONE;
    return WW_DONE;
}
bool ww_pack_motion(uint32_t session, uint32_t sequence,
                    const int16_t *xyz, uint8_t *p) {
    if (!p || !xyz || !session || !sequence) return false;
    p[0] = 0x57; p[1] = 1; p[2] = WW_MOTION; p[3] = 0;
    ww_put32(p + 4, session); ww_put32(p + 8, sequence);
    for (unsigned i = 0; i < 3; ++i) {
        uint16_t v = (uint16_t)xyz[i];
        p[12 + 2 * i] = (uint8_t)v; p[13 + 2 * i] = (uint8_t)(v >> 8);
    }
    seal(p);
    return true;
}
