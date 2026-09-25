/* Host sanitizers, no hardware. Unknown inventory deliberately leaves Health. */
#include <assert.h>
#include <stdio.h>
#include "dispatch.h"

int main(void) {
    wd_dispatch d;
    wd_init(&d, 0, false, 1, 0);
    uint8_t body[20] = {WW_STATUS, 0, 1};
    unsigned corrupted = 0, completed = 0;
    for (uint32_t connection = 1; connection <= 20000; ++connection) {
        uint8_t frames[40], out[20];
        uint32_t now = connection * 1100u;
        assert(wd_open(&d, connection, false, now));
        assert(ww_pack_control(WW_REQUEST, 1, body, sizeof(body), 0, frames));
        assert(ww_pack_control(WW_REQUEST, 1, body, sizeof(body), 1, frames + WW_FRAME_BYTES));
        if (connection % 3u) {
            unsigned bit = connection % 320u;
            frames[bit / 8u] ^= (uint8_t)(1u << (bit % 8u));
            (void)wd_receive(&d, frames, 20, connection, now);
            assert(!wd_receive(&d, frames + 20, 20, connection, now));
            assert(d.state == WD_CLOSED);
            ++corrupted;
        } else {
            assert(wd_receive(&d, frames, 20, connection, now));
            assert(wd_receive(&d, frames + 20, 20, connection, now));
            for (uint8_t part = 0; part < 2; ++part) {
                assert(wd_reply_next(&d, connection, out, now));
                assert(!wd_reply_next(&d, connection, out, now));
                assert(!wd_reply_sent(&d, connection, 2, part, true, now));
                assert(wd_reply_sent(&d, connection, 1, part, true, now));
            }
            assert(d.state == WD_IDLE);
            assert(wd_close(&d, connection, now));
            ++completed;
        }
        assert(d.adapter.runtime.mode.state == WM_HEALTH);
        assert(d.adapter.runtime.mode.token == 0);
        assert(wa_health_allowed(&d.adapter, WM_HEALTH_MEASUREMENT));
        assert(!wd_open(&d, connection, false, now));
    }
    printf("{\"connections\":20000,\"corrupted_rejected\":%u,\"completed\":%u,\"context_bytes\":%zu}\n",
           corrupted, completed, sizeof(d));
    return 0;
}
