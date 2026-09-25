#include "adapter.h"

/* Keep one copy of the complete inventory predicate across adapter gates. */
static __attribute__((noinline)) bool inventory(const wa_adapter *a) {
    return a->health.inventory_proven && a->health.required_jobs != 0u;
}

static void stop_unless_observing(wa_adapter *a) {
    const wm_controller *m = &a->runtime.mode;
    if (m->state != WM_GESTURE &&
        !(m->state == WM_ENTERING && m->action == WM_START_25HZ))
        ws_stop(&a->source, a->source.session);
}

static void source_failed(wa_adapter *a, uint32_t now) {
    wm_stream_failed(&a->runtime.mode, now);
    wr_tick(&a->runtime, now); /* Discard tap/pending output immediately. */
    stop_unless_observing(a);
}

void wa_init(wa_adapter *a, uint32_t jobs, bool proven) {
    *a = (wa_adapter){0};
    wr_init(&a->runtime);
    wh_init(&a->health, jobs, proven);
    ws_init(&a->source);
}

bool wa_prepare(wa_adapter *a, const ws_profile *p) {
    if (a->runtime.mode.state != WM_HEALTH || a->source.progress.active) return false;
    bool valid = ws_profile_valid(p);
    if (valid) a->source.profile = *p;
    else a->source.profile = (ws_profile){0};
    a->profile_ready = valid;
    return valid;
}

bool wa_health_passthrough(const wa_adapter *a) {
    return a->runtime.mode.state == WM_HEALTH && !inventory(a);
}

bool wa_health_allowed(const wa_adapter *a, wm_optical_purpose purpose) {
    return wm_optical_start_allowed(&a->runtime.mode, purpose) &&
        (wa_health_passthrough(a) || a->health.state == WH_HEALTH);
}

void wa_tick(wa_adapter *a, uint32_t now) {
    wr_tick(&a->runtime, now);
    wm_controller *m = &a->runtime.mode;
    if (inventory(a) && a->health.state == WH_FAULT &&
        (m->state == WM_HEALTH ||
         (m->state == WM_RETURNING && m->action == WM_RESUME_HEALTH &&
          a->health.token == m->token))) {
        /* A known Health operation failed: never advertise Health while its
         * RUN/publication gates are closed. Recovery still needs an explicit
         * Health request and the complete physical stop/release/resume chain.
         * An unavailable boot inventory deliberately does NOT take this path.
         */
        m->state = WM_FAULT;
        m->action = WM_NONE;
        m->reason = WM_ACTION_FAILED;
        wr_tick(&a->runtime, now);
    }
    bool observing = m->state == WM_GESTURE ||
        (m->state == WM_ENTERING && m->action == WM_START_25HZ);
    if (observing && (!ws_tick(&a->source, now) || a->health.state == WH_FAULT))
        source_failed(a, now);
    else if (m->state == WM_ENTERING && a->health.state == WH_FAULT)
        source_failed(a, now);
    stop_unless_observing(a);
}

void wa_link(wa_adapter *a, bool connected, bool charging, uint32_t now) {
    wr_link(&a->runtime, connected, charging, now);
    wa_tick(a, now);
}

bool wa_request(wa_adapter *a, bool gesture, uint32_t now) {
    /* Refusal must not start quiescence or reinterpret an unavailable inventory
     * as a command to disable stock Health. No physical capability by default.
     */
    if (gesture && a->runtime.mode.state == WM_HEALTH &&
        (!inventory(a) || a->health.state != WH_HEALTH || !a->profile_ready ||
         !ws_profile_valid(&a->source.profile))) return false;
    uint32_t previous = a->runtime.mode.token;
    bool accepted = wr_request(&a->runtime, gesture, now);
    if (accepted && gesture && a->runtime.mode.state == WM_ENTERING &&
        a->runtime.mode.action == WM_QUIESCE_OPTICS &&
        a->runtime.mode.token != previous) {
        if (!wh_begin_quiesce(&a->health, a->runtime.mode.token)) {
            wr_complete(&a->runtime, a->runtime.mode.token, false, 0u, now);
            accepted = false;
        }
    }
    wa_tick(a, now);
    return accepted;
}

static bool action_matches(const wa_adapter *a, uint32_t token, uint32_t session,
                           wm_action action) {
    return action != WM_NONE && a->runtime.mode.token == token && token != 0u &&
        a->runtime.mode.session == session && a->runtime.mode.action == action;
}

static bool health_receipt(wa_adapter *a, uint32_t token, uint32_t generation, uint32_t now) {
    wm_action action = a->runtime.mode.action;
    if ((action != WM_QUIESCE_OPTICS && action != WM_RESUME_HEALTH) ||
        token != a->runtime.mode.token || token != a->health.token ||
        generation != a->health.generation) return false;
    wa_tick(a, now);
    return token == a->runtime.mode.token && action == a->runtime.mode.action;
}

bool wa_cancelled(wa_adapter *a, uint32_t token, uint32_t generation,
                  uint32_t jobs, uint32_t now) {
    return health_receipt(a, token, generation, now) &&
        wh_cancelled(&a->health, token, generation, jobs);
}

bool wa_fenced(wa_adapter *a, uint32_t token, uint32_t generation, uint32_t now) {
    return health_receipt(a, token, generation, now) &&
        wh_fenced(&a->health, token, generation);
}

bool wa_optics_stopped(wa_adapter *a, uint32_t token, uint32_t generation,
                       bool stopped, uint32_t now) {
    if (!health_receipt(a, token, generation, now)) return false;
    bool accepted = wh_stopped(&a->health, token, generation, stopped);
    if (!accepted) {
        if (a->health.state == WH_FAULT) wa_tick(a, now);
        return false;
    }
    if (a->runtime.mode.action == WM_QUIESCE_OPTICS) {
        if (!wh_quiesced(&a->health, token)) return false;
        accepted = wr_complete(&a->runtime, token, true, 0u, now);
    }
    wa_tick(a, now);
    return accepted;
}

bool wa_physical_done(wa_adapter *a, const wa_physical_receipt *r, uint32_t now) {
    if (!r || !action_matches(a, r->token, r->session, r->action)) return false;
    wa_tick(a, now);
    if (!action_matches(a, r->token, r->session, r->action)) return false;
    uint32_t need;
    switch (r->action) {
    case WM_HOLD_ACCEL:
        need = WA_ACCEL_HELD | WA_HEALTH_PRESERVED | WA_CONFIG_CHECKED | WA_SOURCE_SERIALIZED;
        if (a->health.state != WH_PAUSED || r->config_epoch != a->source.profile.config_epoch ||
            r->binding_id != a->source.profile.binding_id) return false;
        break;
    case WM_STOP_STREAM:
        need = WA_SOURCE_STOPPED | WA_CALLBACKS_FENCED | WA_TRANSPORT_DRAINED;
        break;
    case WM_RELEASE_ACCEL:
        need = WA_ACCEL_RELEASED | WA_HEALTH_PRESERVED;
        break;
    default: return false;
    }
    if ((r->postconditions & need) != need) return false;
    bool accepted = wr_complete(&a->runtime, r->token, true, 0u, now);
    if (accepted && r->action == WM_HOLD_ACCEL &&
        a->runtime.mode.action == WM_START_25HZ) {
        if (!ws_start(&a->source, a->runtime.mode.session, &a->source.profile, now))
            source_failed(a, now);
    }
    wa_tick(a, now);
    return accepted;
}

bool wa_action_failed(wa_adapter *a, uint32_t token, uint32_t session,
                      wm_action action, uint32_t now) {
    if (!action_matches(a, token, session, action)) return false;
    bool accepted = wr_complete(&a->runtime, token, false, 0u, now);
    wa_tick(a, now);
    return accepted;
}

ws_result wa_observe(wa_adapter *a, const ws_receipt *r, uint32_t now) {
    if (r && r->session != a->runtime.mode.session) return WS_IGNORED;
    wa_tick(a, now);
    wm_controller *m = &a->runtime.mode;
    if (m->state != WM_GESTURE &&
        !(m->state == WM_ENTERING && m->action == WM_START_25HZ)) return WS_IGNORED;
    ws_delivery d;
    ws_result result = ws_observe(&a->source, r, &d, now);
    if (result == WS_FAULT || result == WS_IGNORED) {
        source_failed(a, now);
        return WS_FAULT;
    }
    if (result == WS_DELIVER) {
        if (m->state == WM_ENTERING &&
            !wr_complete(&a->runtime, m->token, true, 0u, now)) {
            source_failed(a, now);
            return WS_FAULT;
        }
        if (wr_offer(&a->runtime, d.session, d.acquisition, d.values, d.count, true,
                      d.oldest_at, now) != WT_OK) {
            source_failed(a, now);
            return WS_FAULT;
        }
    }
    wa_tick(a, now);
    return result;
}

bool wa_begin_resume(wa_adapter *a, uint32_t token, uint32_t revision, uint32_t now) {
    if (!action_matches(a, token, a->runtime.mode.session, WM_RESUME_HEALTH)) return false;
    wa_tick(a, now);
    if (a->runtime.mode.token != token || a->runtime.mode.action != WM_RESUME_HEALTH)
        return false;
    return wh_begin_resume(&a->health, token, revision);
}

bool wa_resume_ready(wa_adapter *a, uint32_t token, uint32_t generation,
                     uint32_t revision, bool preserved, bool rebound, uint32_t now) {
    if (!health_receipt(a, token, generation, now) ||
        a->runtime.mode.action != WM_RESUME_HEALTH) return false;
    bool accepted = wh_resume_ready(&a->health, token, generation, revision, preserved, rebound);
    wa_tick(a, now);
    return accepted;
}

bool wa_commit_health(wa_adapter *a, uint32_t token, uint32_t revision, uint32_t now) {
    if (!action_matches(a, token, a->runtime.mode.session, WM_RESUME_HEALTH)) return false;
    wa_tick(a, now);
    if (a->runtime.mode.token != token || a->runtime.mode.action != WM_RESUME_HEALTH)
        return false;
    if (a->health.state == WH_READY && a->health.token == token &&
        a->health.settings_revision != revision) {
        /* A changed current setting invalidates the old scheduler receipt.
         * No physical operation or runtime publication has happened yet.
         */
        a->health.settings_revision = revision;
        a->health.state = WH_RESUMING;
        return false;
    }
    if (!wh_can_commit(&a->health, token, revision)) return false;
    if (!wr_complete(&a->runtime, token, true, 0u, now)) return false;
    /* The same serialized critical section and immutable arguments make this
     * infallible after can_commit; fail shut if that invariant ever changes.
     */
    if (!wh_commit_health(&a->health, token, revision)) {
        wh_fail(&a->health);
        a->runtime.mode.state = WM_FAULT;
        a->runtime.mode.action = WM_NONE;
        a->runtime.mode.reason = WM_ACTION_FAILED;
        return false;
    }
    stop_unless_observing(a);
    return true;
}

bool wa_next(wa_adapter *a, uint32_t session, wt_sample *sample, uint32_t now) {
    if (session != a->runtime.mode.session) return false;
    wa_tick(a, now);
    bool result = wr_next(&a->runtime, session, sample, now);
    stop_unless_observing(a);
    return result;
}

bool wa_sent(wa_adapter *a, uint32_t session, uint32_t sequence, bool accepted, uint32_t now) {
    if (session != a->runtime.mode.session) return false;
    wa_tick(a, now);
    bool result = wr_sent(&a->runtime, session, sequence, accepted, now);
    stop_unless_observing(a);
    return result;
}

bool wa_renew(wa_adapter *a, uint32_t session, uint32_t sequence, uint32_t now) {
    if (session != a->runtime.mode.session) return false;
    wa_tick(a, now);
    bool result = wr_renew(&a->runtime, session, sequence, now);
    stop_unless_observing(a);
    return result;
}
