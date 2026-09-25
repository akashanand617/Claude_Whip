/* OFF-RING EXPERIMENT, NOT ADOPTED. Same ABI and policy as fresh_source.c.
 * Replace the second per-frame bucket division with an exact remainder bound.
 * Do not link into a firmware image without differential and full integration
 * validation. No physical sensor, stack or allocation is qualified here.
 */
#include "fresh_source.h"

bool ws_set_bounds(ws_receipt *r, uint32_t index, uint32_t earliest, uint32_t latest) {
    if (!r) return false;
    uint32_t first_age = r->status_at - earliest, last_age = r->status_at - latest;
    if (index >= WS_FIFO_FRAMES || first_age >= WS_MAX_AGE_MS || last_age > first_age) {
        r->transport_result = 1u;
        return false;
    }
    r->acquired[index] = (ws_age_bound){(uint8_t)first_age, (uint8_t)last_age};
    return true;
}

bool ws_profile_valid(const ws_profile *p) {
    if (!p || !p->config_epoch || !p->binding_id || p->observed_frames < 2u ||
        p->observed_frames > UINT32_MAX / WS_PERIOD_MS ||
        !p->minimum_period_ms || p->minimum_period_ms > p->maximum_period_ms ||
        p->maximum_period_ms > WS_PERIOD_MS ||
        p->timestamp_uncertainty_ms >= WS_PERIOD_MS ||
        p->chip_id != 0x23u || p->range != 0x05u || p->bandwidth != 0x0fu ||
        p->power != 0x74u || p->fifo_config != 0xc8u) return false;
    uint8_t evidence = 0;
    for (unsigned i = 0; i < sizeof(p->evidence_sha256); i++)
        evidence |= p->evidence_sha256[i];
    uint32_t intervals = p->observed_frames - 1u;
    return evidence && p->observed_span_ms >= intervals * p->minimum_period_ms &&
        p->observed_span_ms <= intervals * p->maximum_period_ms;
}

void ws_init(ws_source *s) { *s = (ws_source){0}; }

bool ws_start(ws_source *s, uint32_t session, const ws_profile *p, uint32_t now) {
    if (!s || s->progress.active || !session || session <= s->session || !ws_profile_valid(p))
        return false;
    *s = (ws_source){.profile = *p, .session = session, .started_at = now,
                     .progress = {.active = true}};
    return true;
}

void ws_stop(ws_source *s, uint32_t session) {
    if (s && s->session == session) s->progress.active = false;
}

bool ws_tick(ws_source *s, uint32_t now) {
    if (!s || !s->progress.active) return false;
    uint32_t anchor = s->progress.have_frame ? s->progress.last_earliest : s->started_at;
    if ((uint32_t)(now - anchor) >= WS_MAX_AGE_MS ||
        (uint32_t)(now - s->started_at) >= 0x80000000u) s->progress.active = false;
    return s->progress.active;
}

static ws_result fail(ws_source *s, ws_delivery *d) {
    s->progress.active = false;
    if (d) *d = (ws_delivery){0};
    return WS_FAULT;
}

ws_result ws_observe(ws_source *s, const ws_receipt *r,
                     ws_delivery *d, uint32_t now) {
    if (d) *d = (ws_delivery){0};
    if (!s || !s->progress.active) return WS_IGNORED;
    if (r && r->session != s->session) return WS_IGNORED;
    if (!r || !d || !ws_tick(s, now)) return fail(s, d);
    uint32_t span = r->completed_at - r->status_at;
    if (r->config_epoch != s->profile.config_epoch ||
        r->binding_id != s->profile.binding_id ||
        s->transaction == UINT32_MAX || r->transaction != s->transaction + 1u ||
        r->transport_result || r->count > WS_FIFO_FRAMES || r->fifo_status != r->count ||
        r->requested_bytes != (uint16_t)(r->count * 6u) ||
        r->completed_bytes != r->requested_bytes ||
        (uint32_t)(now - r->status_at) >= WS_MAX_AGE_MS ||
        (uint32_t)(now - r->completed_at) >= WS_MAX_AGE_MS ||
        (uint32_t)(r->status_at - s->started_at) >= 0x80000000u ||
        span >= WS_MAX_AGE_MS) return fail(s, d);
    uint32_t arrivals = span / s->profile.minimum_period_ms + 1u;
    if ((uint32_t)r->count + arrivals > WS_FIFO_FRAMES) return fail(s, d);

    ws_progress next = s->progress;
    d->session = s->session;
    for (uint8_t i = 0; i < r->count; i++) {
        ws_age_bound age = r->acquired[i];
        if (age.earliest_age >= WS_MAX_AGE_MS || age.latest_age > age.earliest_age)
            return fail(s, d);
        ws_time_bound t = {r->status_at - age.earliest_age, r->status_at - age.latest_age};
        uint32_t first = t.earliest - s->started_at;
        uint32_t width = t.latest - t.earliest;
        if (width > s->profile.timestamp_uncertainty_ms ||
            (uint32_t)(now - t.earliest) >= WS_MAX_AGE_MS ||
            first >= 0x80000000u) return fail(s, d);
        uint32_t bucket = first / WS_PERIOD_MS;
        /* Checked ages/status/first imply first <= last < 2^31. Therefore
         * last/40 == first/40 iff (first - floor(first/40)*40) + width < 40.
         * Remainder <=39 and width <=249 even with a malformed profile; this
         * addition cannot overflow. Preserve exact millisecond boundaries.
         */
        if (first - bucket * WS_PERIOD_MS + width >= WS_PERIOD_MS) return fail(s, d);
        if (next.have_frame &&
            ((uint32_t)(t.earliest - next.last_latest) < s->profile.minimum_period_ms ||
             (uint32_t)(t.earliest - next.last_latest) > s->profile.maximum_period_ms ||
             (uint32_t)(t.latest - next.last_earliest) > s->profile.maximum_period_ms))
            return fail(s, d);
        if ((!next.have_bucket && bucket != 0u) ||
            (next.have_bucket && bucket != next.last_bucket &&
             bucket != next.last_bucket + 1u)) return fail(s, d);
        if (!next.have_bucket || bucket != next.last_bucket) {
            if (d->count >= WS_DELIVERY_FRAMES) return fail(s, d);
            if (!d->count) d->oldest_at = t.earliest;
            for (unsigned axis = 0; axis < 3; axis++) {
                unsigned pos = (unsigned)i * 6u + axis * 2u;
                uint16_t word = (uint16_t)r->bytes[pos] |
                    (uint16_t)((uint16_t)r->bytes[pos + 1u] << 8u);
                int32_t signed_word = word < 0x8000u ? (int32_t)word : (int32_t)word - 65536;
                d->values[d->count].axis[axis] = (int16_t)signed_word;
            }
            d->count++;
            next.last_bucket = bucket;
            next.have_bucket = true;
        }
        next.last_earliest = t.earliest;
        next.last_latest = t.latest;
        next.have_frame = true;
    }
    uint32_t acquisition = s->acquisition;
    if (d->count) {
        if (acquisition == UINT32_MAX) return fail(s, d);
        d->acquisition = ++acquisition;
    }
    s->transaction = r->transaction;
    s->acquisition = acquisition;
    s->progress = next;
    return d->count ? WS_DELIVER : WS_ACCEPTED;
}
