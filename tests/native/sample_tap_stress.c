#include "sample_tap.h"
#include "mode_controller.h"
#include <assert.h>
#include <stddef.h>
#include <stdio.h>

int main(void) {
    wt_tap t;
    wt_init(&t);
    wt_axes source[32];
    wt_sample out;
    for (unsigned i = 0; i < 32; i++) {
        source[i] = (wt_axes){{(int16_t)i, (int16_t)(-8005), (int16_t)32767}};
    }
    assert(!wt_start(&t, 0, 0));
    unsigned delivered = 0;
    for (uint32_t session = 1; session <= 10000; session++) {
        assert(wt_start(&t, session, UINT32_MAX - 2));
        assert(!wt_start(&t, session, 0));
        uint32_t acquisition = UINT32_MAX - 2;
        uint32_t sequence = 0;
        for (unsigned batch = 0; batch < 20; batch++) {
            uint8_t count = (uint8_t)(1 + (batch * 7 + session) % 32);
            assert(wt_offer(&t, session, ++acquisition, source, count, true) == WT_OK);
            for (unsigned i = 0; i < count; i++) {
                assert(wt_take(&t, session, &out));
                assert(out.sequence == ++sequence);
                for (unsigned j = 0; j < 3; j++) assert(out.value.axis[j] == source[i].axis[j]);
                delivered++;
            }
            assert(!wt_take(&t, session, &out));
        }
        wt_stop(&t, session - 1); /* stale stop cannot cancel new session */
        assert(t.active);
        assert(wt_offer(&t, session - 1, acquisition, source, 1, false) == WT_STALE_SESSION);
        assert(t.active);
        wt_stop(&t, session);
        assert(!wt_start(&t, session, 0));
        assert(!wt_take(&t, session, &out));
    }
    assert(wt_start(&t, 10001, 0));
    assert(wt_offer(&t, 10001, 1, source, 32, true) == WT_OK);
    assert(wt_offer(&t, 10001, 2, source, 1, true) == WT_OVERFLOW);
    assert(!wt_take(&t, 10001, &out) && !t.active);
    assert(!wt_start(&t, 10001, 0));
    for (unsigned failure = 0; failure < 6; failure++) {
        uint32_t session = 10002 + failure;
        assert(wt_start(&t, session, 0));
        wt_result r = wt_offer(&t, session, failure == 0 ? 0 : failure == 1 ? 2 : 1,
                              failure == 2 ? NULL : source,
                              failure == 3 ? 0 : failure == 4 ? 33 : 1,
                              failure != 5);
        assert(r == WT_BAD_ACQUISITION && !t.active && t.count == 0);
    }
    assert(wt_start(&t, 10008, 0));
    t.sequence = UINT32_MAX - 1;
    assert(wt_offer(&t, 10008, 1, source, 2, true) == WT_SEQUENCE_EXHAUSTED);

    /* Integration contract: overflow requests cleanup; never instantly Health. */
    wm_controller c;
    wm_init(&c);
    wm_link(&c, true, false, 0);
    assert(wm_request(&c, true, 0));
    for (unsigned i = 0; i < 3; i++) assert(wm_complete(&c, c.token, true, 0));
    assert(c.state == WM_GESTURE);
    wt_init(&t);
    assert(wt_start(&t, c.session, 0));
    assert(wt_offer(&t, c.session, 1, source, 32, true) == WT_OK);
    assert(wt_offer(&t, c.session, 2, source, 1, true) == WT_OVERFLOW);
    assert(wm_request(&c, false, 1));
    assert(c.state == WM_RETURNING && c.action == WM_STOP_STREAM);
    assert(!wm_optics_allowed(&c));
    for (unsigned i = 0; i < 3; i++) assert(wm_complete(&c, c.token, true, 1));
    assert(c.state == WM_HEALTH);

    /* Preserve an independent, shifting FIFO while the physical ring index
     * repeatedly wraps with a nonempty backlog. Unlike the first stress loop,
     * these batches are not fully drained before a new append.
     */
    wt_sample expected[WT_CAPACITY];
    unsigned pending = 0;
    uint32_t next_sequence = 0, acquisition = UINT32_MAX - 2, random = 0x621e;
    wt_init(&t);
    assert(wt_start(&t, 1, acquisition));
    for (unsigned iteration = 0; iteration < 100000; ++iteration) {
        random = random * 1664525u + 1013904223u;
        if (pending < WT_CAPACITY && (pending == 0 || (random & 3u) == 0)) {
            uint8_t count = (uint8_t)(1u + (random >> 8) % (WT_CAPACITY - pending));
            assert(wt_offer(&t, 1, ++acquisition, source, count, true) == WT_OK);
            for (unsigned i = 0; i < count; ++i)
                expected[pending++] = (wt_sample){++next_sequence, source[i]};
        } else {
            assert(wt_take(&t, 1, &out));
            assert(out.sequence == expected[0].sequence);
            for (unsigned j = 0; j < 3; ++j) assert(out.value.axis[j] == expected[0].value.axis[j]);
            for (unsigned i = 1; i < pending; ++i) expected[i - 1] = expected[i];
            pending--;
        }
        assert(t.count == pending && t.sequence == next_sequence);
    }
    printf("{\"sessions\":10000,\"delivered\":%u,\"interleaved\":100000,\"tap_bytes\":%zu}\n",
           delivered, sizeof(t));
    return 0;
}
