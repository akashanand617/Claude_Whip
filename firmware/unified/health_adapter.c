#include "health_adapter.h"

static bool inventory(const wh_adapter *h) {
    return h->inventory_proven && h->required_jobs != 0u;
}
static bool matching(const wh_adapter *h, uint32_t token, uint32_t generation) {
    return token != 0u && token == h->token && generation == h->generation;
}
static bool closing(const wh_adapter *h) {
    return h->state == WH_QUIESCING || h->state == WH_RESUMING;
}
static bool drained(const wh_adapter *h) {
    return inventory(h) && h->cancelled_jobs == h->required_jobs && h->in_flight == 0u;
}
static bool quiet(const wh_adapter *h) {
    return drained(h) && h->fenced && h->stopped;
}
static bool ticket_matches(const wh_adapter *h, wh_ticket t) {
    return t.job < WH_JOB_LIMIT && t.generation == h->job_generation &&
           t.serial != 0u && h->jobs[t.job] == t.serial;
}
/* Tiny two-caller increment; inline it while sharing the larger fault body. */
static __attribute__((always_inline)) inline bool advance(wh_adapter *h) {
    if (h->generation == UINT32_MAX) {
        wh_fail(h);
        return false;
    }
    h->generation++;
    return true;
}
/* All failure paths share the same receipt invalidation; keep one code copy. */
__attribute__((noinline)) void wh_fail(wh_adapter *h) {
    h->state = WH_FAULT;
    h->fenced = false;
    h->stopped = false;
}
void wh_init(wh_adapter *h, uint32_t required_jobs, bool inventory_proven) {
    *h = (wh_adapter){0};
    h->required_jobs = required_jobs;
    h->inventory_proven = inventory_proven;
    h->generation = 1u;
    h->job_generation = 1u;
    h->state = inventory(h) ? WH_HEALTH : WH_FAULT;
}
bool wh_begin_quiesce(wh_adapter *h, uint32_t token) {
    if (!inventory(h) || token == 0u || token <= h->token || !advance(h)) return false;
    h->token = token;
    h->state = WH_QUIESCING;
    h->cancelled_jobs = 0u;
    h->fenced = false;
    h->stopped = false;
    return true;
}
bool wh_cancelled(wh_adapter *h, uint32_t token, uint32_t generation, uint32_t jobs) {
    if (!closing(h) || !matching(h, token, generation) || jobs == 0u ||
        (jobs & ~h->required_jobs) != 0u || (jobs & h->in_flight) != 0u) return false;
    h->cancelled_jobs |= jobs;
    return true;
}
bool wh_fenced(wh_adapter *h, uint32_t token, uint32_t generation) {
    if (!closing(h) || !matching(h, token, generation) || !drained(h)) return false;
    h->fenced = true;
    return true;
}
bool wh_stopped(wh_adapter *h, uint32_t token, uint32_t generation, bool verified) {
    if (!closing(h) || !matching(h, token, generation) || !drained(h) || !h->fenced)
        return false;
    if (!verified) {
        wh_fail(h);
        return false;
    }
    h->stopped = true;
    if (h->state == WH_QUIESCING) h->state = WH_PAUSED;
    return true;
}
bool wh_quiesced(const wh_adapter *h, uint32_t token) {
    return token == h->token && h->state == WH_PAUSED && quiet(h);
}
bool wh_retirement_allowed(const wh_adapter *h, uint32_t token) {
    return token != 0u && token == h->token &&
           (h->state == WH_PAUSED || h->state == WH_RESUMING) && quiet(h);
}
bool wh_begin_resume(wh_adapter *h, uint32_t token, uint32_t revision) {
    if (!inventory(h) || token == 0u || token <= h->token || h->state == WH_HEALTH)
        return false;
    bool had_quiet = h->state == WH_PAUSED && quiet(h);
    if (!advance(h)) return false;
    h->token = token;
    h->settings_revision = revision;
    h->state = WH_RESUMING;
    if (!had_quiet) {
        h->cancelled_jobs = 0u;
        h->fenced = false;
        h->stopped = false;
    }
    return true;
}
bool wh_resume_ready(wh_adapter *h, uint32_t token, uint32_t generation,
                     uint32_t revision, bool preserved, bool rebound) {
    if (h->state != WH_RESUMING || !matching(h, token, generation) || !quiet(h)) return false;
    if (revision != h->settings_revision) {
        h->settings_revision = revision;
        return false;
    }
    if (!preserved || !rebound) {
        wh_fail(h);
        return false;
    }
    h->state = WH_READY;
    return true;
}
bool wh_can_commit(const wh_adapter *h, uint32_t token, uint32_t revision) {
    return token != 0u && token == h->token && h->state == WH_READY && quiet(h) &&
           revision == h->settings_revision;
}
bool wh_commit_health(wh_adapter *h, uint32_t token, uint32_t revision) {
    if (token == h->token && h->state == WH_READY && revision != h->settings_revision) {
        h->settings_revision = revision;
        h->state = WH_RESUMING;
    }
    if (!wh_can_commit(h, token, revision)) return false;
    for (uint8_t i = 0; i < WH_JOB_LIMIT; i++) h->jobs[i] = 0u;
    h->job_generation = h->generation;
    h->cancelled_jobs = 0u;
    h->fenced = false;
    h->stopped = false;
    h->state = WH_HEALTH;
    return true;
}
bool wh_job_begin(wh_adapter *h, uint8_t job, wh_ticket *t) {
    if (h->state != WH_HEALTH || !inventory(h) || t == 0 || job >= WH_JOB_LIMIT ||
        (h->required_jobs & (UINT32_C(1) << job)) == 0u || h->jobs[job] != 0u) return false;
    if (h->next_serial == UINT32_MAX) {
        wh_fail(h);
        return false;
    }
    h->jobs[job] = ++h->next_serial;
    *t = (wh_ticket){ h->job_generation, h->next_serial, job };
    return true;
}
bool wh_run_begin(wh_adapter *h, wh_ticket t) {
    if (h->state != WH_HEALTH || !ticket_matches(h, t)) return false;
    uint32_t bit = UINT32_C(1) << t.job;
    if ((h->in_flight & bit) != 0u) return false;
    h->in_flight |= bit;
    return true;
}
bool wh_run_end(wh_adapter *h, wh_ticket t, bool success) {
    if (!ticket_matches(h, t)) return false;
    uint32_t bit = UINT32_C(1) << t.job;
    if ((h->in_flight & bit) == 0u) return false;
    h->in_flight &= ~bit;
    if (!success) wh_fail(h);
    return success;
}
bool wh_result_allowed(const wh_adapter *h, wh_ticket t, bool measured) {
    return h->state == WH_HEALTH && measured && ticket_matches(h, t);
}
bool wh_job_end(wh_adapter *h, wh_ticket t) {
    if (!ticket_matches(h, t) || (h->in_flight & (UINT32_C(1) << t.job)) != 0u) return false;
    h->jobs[t.job] = 0u;
    return true;
}
