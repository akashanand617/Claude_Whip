#include "fresh_source.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

int main(void) {
    ws_source source;
    ws_init(&source);
    ws_profile p = {.config_epoch = 1, .binding_id = 2,
        .observed_frames = 101, .observed_span_ms = 1300,
        .minimum_period_ms = 13, .maximum_period_ms = 13,
        .chip_id = 0x23, .range = 5, .bandwidth = 15, .power = 0x74, .fifo_config = 0xc8};
    p.evidence_sha256[0] = 0xee; /* Synthetic, not a qualified physical profile. */
    uint32_t delivered = 0;
    for (uint32_t session = 1; session <= 10000; session++) {
        uint32_t start = UINT32_MAX - session * 43u;
        assert(ws_start(&source, session, &p, start));
        uint32_t transaction = 0, expected_bucket = 0;
        for (uint32_t t = 0; t < 1000; t += 13) {
            ws_receipt r = {.session = session, .config_epoch = 1, .binding_id = 2,
                .transaction = ++transaction, .status_at = start + t,
                .completed_at = start + t, .requested_bytes = 6, .completed_bytes = 6,
                .fifo_status = 1, .count = 1};
            assert(ws_set_bounds(&r, 0, start + t, start + t));
            r.bytes[0] = (uint8_t)t;
            r.bytes[1] = (uint8_t)(t >> 8);
            r.bytes[3] = 0x80;
            r.bytes[4] = r.bytes[5] = 0xff;
            ws_receipt untouched = r;
            ws_delivery d;
            ws_result result = ws_observe(&source, &r, &d, start + t);
            assert(memcmp(&r, &untouched, sizeof(r)) == 0);
            assert(result == WS_ACCEPTED || result == WS_DELIVER);
            if (result == WS_DELIVER) {
                assert(d.count == 1 && d.values[0].axis[0] == (int16_t)t);
                assert(d.values[0].axis[1] == -32768 && d.values[0].axis[2] == -1);
                assert((uint32_t)(d.oldest_at - start) / 40 == expected_bucket++);
                delivered++;
            }
        }
        assert(expected_bucket == 25);
        ws_stop(&source, session - 1);
        assert(source.progress.active);
        ws_stop(&source, session);
        assert(!source.progress.active && !ws_start(&source, session, &p, start));
    }
    printf("{\"sessions\":10000,\"delivered\":%u,\"source_bytes\":%zu}\n",
           delivered, sizeof(source));
    return 0;
}
