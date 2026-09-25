#include "runtime.h"

static void discard_if_not_gesture(wr_runtime *r) {
    if (r->mode.state == WM_GESTURE) return;
    wt_stop(&r->tap, r->tap.session);
    r->awaiting_send = false;
    r->have_sent = false;
}

void wr_init(wr_runtime *r) {
    *r = (wr_runtime){0};
    wm_init(&r->mode);
    wt_init(&r->tap);
}

void wr_tick(wr_runtime *r, uint32_t now) {
    wm_tick(&r->mode, now);
    if (r->mode.state == WM_GESTURE &&
            (uint32_t)(now - r->last_source_at) >= WR_MAX_SAMPLE_AGE_MS)
        wm_stream_failed(&r->mode, now);
    discard_if_not_gesture(r);
}

void wr_link(wr_runtime *r, bool connected, bool charging, uint32_t now) {
    wm_link(&r->mode, connected, charging, now);
    wr_tick(r, now);
}

bool wr_request(wr_runtime *r, bool gesture, uint32_t now) {
    bool accepted = wm_request(&r->mode, gesture, now);
    discard_if_not_gesture(r);
    return accepted;
}

bool wr_complete(wr_runtime *r, uint32_t token, bool success,
                 uint32_t source_baseline, uint32_t now) {
    wr_tick(r, now);
    if (token != r->mode.token || r->mode.action == WM_NONE) return false;
    if (success && r->mode.action == WM_START_25HZ) {
        success = wt_start(&r->tap, r->mode.session, source_baseline);
        r->have_sent = r->awaiting_send = false;
        r->last_sent = 0;
        r->last_source_at = now;
        r->have_source = false;
    }
    bool accepted = wm_complete(&r->mode, token, success, now);
    discard_if_not_gesture(r);
    return accepted;
}

wt_result wr_offer(wr_runtime *r, uint32_t session, uint32_t acquisition,
                   const wt_axes *batch, uint8_t count, bool verified,
                   uint32_t oldest_at, uint32_t now) {
    wr_tick(r, now);
    if (r->mode.state != WM_GESTURE || session != r->mode.session)
        return WT_STALE_SESSION;
    uint32_t advance = oldest_at - r->last_source_at;
    verified = verified && (uint32_t)(now - oldest_at) < WR_MAX_SAMPLE_AGE_MS &&
        (!r->have_source || (advance > 0 && advance < 0x80000000u));
    uint8_t slot = (uint8_t)((r->tap.head + r->tap.count) % WT_CAPACITY);
    wt_result result = wt_offer(&r->tap, session, acquisition, batch, count, verified);
    if (result != WT_OK) {
        wm_stream_failed(&r->mode, now);
        discard_if_not_gesture(r);
    } else {
        for (uint8_t i = 0; i < count; i++)
            r->queued_at[(slot + i) % WT_CAPACITY] = (uint8_t)oldest_at;
        r->last_source_at = oldest_at;
        r->have_source = true;
    }
    return result;
}

bool wr_next(wr_runtime *r, uint32_t session, wt_sample *sample, uint32_t now) {
    wr_tick(r, now);
    if (r->mode.state != WM_GESTURE || session != r->mode.session ||
            r->awaiting_send || !sample) return false;
    if (r->tap.count && (uint8_t)(now - r->queued_at[r->tap.head]) >= WR_MAX_SAMPLE_AGE_MS) {
        wm_stream_failed(&r->mode, now);
        discard_if_not_gesture(r);
        return false;
    }
    r->pending_at = now - (uint8_t)(now - r->queued_at[r->tap.head]);
    if (!wt_take(&r->tap, session, &r->pending)) return false;
    *sample = r->pending;
    r->awaiting_send = true;
    return true;
}

bool wr_sent(wr_runtime *r, uint32_t session, uint32_t sequence, bool success, uint32_t now) {
    wr_tick(r, now);
    if (r->mode.state != WM_GESTURE || session != r->mode.session ||
            !r->awaiting_send || sequence != r->pending.sequence) return false;
    if ((uint32_t)(now - r->pending_at) >= WR_MAX_SAMPLE_AGE_MS) {
        wm_stream_failed(&r->mode, now);
        discard_if_not_gesture(r);
        return false;
    }
    r->awaiting_send = false;
    if (!success) {
        wm_stream_failed(&r->mode, now);
        discard_if_not_gesture(r);
        return true;
    }
    r->last_sent = sequence;
    r->have_sent = true;
    return true;
}

bool wr_renew(wr_runtime *r, uint32_t session, uint32_t processed_sequence, uint32_t now) {
    wr_tick(r, now);
    if (!r->have_sent || processed_sequence == 0 || processed_sequence > r->last_sent)
        return false;
    return wm_renew(&r->mode, session, processed_sequence, now);
}
