/* Offline policy stress only: no sensor adapter, ROM, BLE, or image execution. */
#include "mode_controller.h"
#include <assert.h>
#include <stdio.h>

static uint32_t random_word(uint32_t *s) {
    *s ^= *s << 13; *s ^= *s >> 17; *s ^= *s << 5;
    return *s;
}

static void invariant(const wm_controller *c) {
    assert(c->state >= WM_HEALTH && c->state <= WM_FAULT);
    assert(c->action >= WM_NONE && c->action <= WM_RESUME_HEALTH);
    assert(wm_optics_allowed(c) == (c->state == WM_HEALTH));
    assert(wm_optical_start_allowed(c, WM_HEALTH_MEASUREMENT) == (c->state == WM_HEALTH));
    assert(!wm_optical_start_allowed(c, WM_DECORATIVE_INDICATOR));
    assert(!wm_optical_start_allowed(c, WM_RAW_OPTICAL_DEBUG));
    assert(!wm_optical_start_allowed(c, (wm_optical_purpose)99));
    if (c->state == WM_ENTERING)
        assert(c->action >= WM_QUIESCE_OPTICS && c->action <= WM_START_25HZ);
    else if (c->state == WM_RETURNING)
        assert(c->action >= WM_STOP_STREAM && c->action <= WM_RESUME_HEALTH);
    else assert(c->action == WM_NONE);
    if (c->state == WM_GESTURE) assert(c->connected && !c->charging);
}

static void complete(wm_controller *c, wm_action action, uint32_t now) {
    assert(c->action == action);
    assert(wm_complete(c, c->token, true, now));
    invariant(c);
}

static void repeated_sessions(void) {
    wm_controller c;
    wm_init(&c);
    uint32_t now = UINT32_MAX - 1000u;
    uint32_t previous_session = 0;
    for (unsigned i = 0; i < 20000; ++i) {
        wm_link(&c, true, false, now);
        assert(wm_request(&c, true, now));
        assert(c.session > previous_session);
        previous_session = c.session;
        complete(&c, WM_QUIESCE_OPTICS, now);
        complete(&c, WM_HOLD_ACCEL, now);
        complete(&c, WM_START_25HZ, now);
        uint32_t lease = c.lease_ms;
        assert(wm_request(&c, true, now + 1));
        assert(c.lease_ms == lease); /* duplicate entry never prolongs Gesture */
        assert(wm_renew(&c, c.session, UINT32_MAX - 1u, now + 2));
        assert(!wm_renew(&c, c.session, UINT32_MAX - 1u, now + 3));
        assert(wm_renew(&c, c.session, 1, now + 4));
        assert(!wm_renew(&c, c.session, 0x80000001u, now + 5));
        assert(!wm_renew(&c, c.session - 1u, 2, now + 6));
        switch (i % 4) {
        case 0: assert(wm_request(&c, false, now + 7)); break;
        case 1: wm_link(&c, false, false, now + 7); break;
        case 2: wm_link(&c, true, true, now + 7); break;
        default:
            now += 4u + WM_LEASE_MS;
            wm_tick(&c, now);
            break;
        }
        now += 8;
        complete(&c, WM_STOP_STREAM, now);
        complete(&c, WM_RELEASE_ACCEL, now);
        complete(&c, WM_RESUME_HEALTH, now);
        assert(c.state == WM_HEALTH);
        now += 1000;
    }
}

static void token_exhaustion(void) {
    for (unsigned remaining = 0; remaining < 7; ++remaining) {
        wm_controller c;
        wm_init(&c);
        wm_link(&c, true, false, 0);
        c.token = UINT32_MAX - remaining;
        (void)wm_request(&c, true, 0);
        for (unsigned n = 0; n < 10 && c.state != WM_FAULT; ++n) {
            if (c.state == WM_GESTURE || c.state == WM_HEALTH)
                (void)wm_request(&c, c.state == WM_HEALTH, 0);
            else (void)wm_complete(&c, c.token, true, 0);
            invariant(&c);
        }
        assert(c.state == WM_FAULT && c.token == UINT32_MAX);
        assert(!wm_request(&c, true, 0));
        (void)wm_request(&c, false, 0);
        assert(c.state == WM_FAULT); /* no wrap/reuse, even on cleanup retry */
        invariant(&c);
    }
}

int main(void) {
    unsigned visits[5] = {0};
    repeated_sessions();
    token_exhaustion();
    for (uint32_t seed = 1; seed <= 256; ++seed) {
        struct { uint32_t before; wm_controller c; uint32_t after; } guarded;
        guarded.before = 0xabcddcbau; guarded.after = 0x12344321u;
        wm_controller *c = &guarded.c;
        wm_init(c);
        uint32_t rng = seed, now = UINT32_MAX - seed * 37u;
        /* Start each fault campaign from an established session. Unconstrained
         * noise alone mostly stays in Fault and undersamples active Gesture. */
        wm_link(c, true, false, now);
        assert(wm_request(c, true, now));
        complete(c, WM_QUIESCE_OPTICS, now);
        complete(c, WM_HOLD_ACCEL, now);
        complete(c, WM_START_25HZ, now);
        for (unsigned i = 0; i < 5000; ++i) {
            uint32_t old_token = c->token;
            now += random_word(&rng) % 1001u;
            switch (random_word(&rng) % 10u) {
            case 0: (void)wm_request(c, true, now); break;
            case 1: (void)wm_request(c, false, now); break;
            case 2: {
                uint32_t link = random_word(&rng);
                wm_link(c, (link & 1) != 0, (link & 2) != 0, now);
                break;
            }
            case 3: (void)wm_complete(c, c->token, true, now); break;
            case 4: (void)wm_complete(c, c->token, false, now); break;
            case 5: (void)wm_complete(c, c->token - 1u, true, now); break;
            case 6: (void)wm_renew(c, c->session, random_word(&rng), now); break;
            case 7: (void)wm_renew(c, c->session - 1u, rng, now); break;
            case 8: now += WM_LEASE_MS; wm_tick(c, now); break;
            default: wm_tick(c, now); break;
            }
            assert(c->token >= old_token);
            invariant(c);
            visits[c->state]++;
            assert(guarded.before == 0xabcddcbau && guarded.after == 0x12344321u);
        }
    }
    printf("{\"random_events\":1280000,\"complete_sessions\":20000,"
           "\"token_exhaustion_cases\":7,\"state_visits\":[%u,%u,%u,%u,%u]}\n",
           visits[0], visits[1], visits[2], visits[3], visits[4]);
    for (unsigned i = 0; i < 5; ++i) assert(visits[i] > 0);
    return 0;
}
