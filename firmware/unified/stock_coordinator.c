#include "stock_coordinator.h"
#include "stock_optical_work.h"

_Static_assert(sizeof(wc_owner) == 28, "review coordinator ARM32 owner budget");
_Static_assert(sizeof(wc_stop_receipt) == 28, "review STOP receipt budget");
_Static_assert(sizeof(wc_resume_receipt) == 20, "review resume receipt budget");

enum { C_IDLE, C_DRAIN, C_SUBMITTING, C_STOP, C_RETIRED, C_RESUME, C_FAILED };

static bool context(const wc_owner *c) {
    uint32_t exception, mask;
    __asm volatile ("mrs %0, ipsr\n\tmrs %1, primask" : "=r"(exception), "=r"(mask));
    return !exception && !mask && c && c->adapter;
}
static bool closing(const wc_owner *c) {
    const wa_adapter *a = c->adapter;
    return c->token && c->token == a->runtime.mode.token &&
        c->session == a->runtime.mode.session && c->token == a->health.token &&
        c->generation == a->health.generation &&
        (a->runtime.mode.action == WM_QUIESCE_OPTICS ||
         a->runtime.mode.action == WM_RESUME_HEALTH);
}
static bool retired_pause(const wc_owner *c) {
    const wa_adapter *a = c->adapter;
    return c->retired && c->session == a->runtime.mode.session &&
        c->generation == a->health.generation && wh_quiesced(&a->health, c->token);
}
static void failed(wc_owner *c, uint32_t now) {
    wm_controller *m = &c->adapter->runtime.mode;
    c->phase = C_FAILED;
    c->retired = false;
    (void)wa_action_failed(c->adapter, m->token, m->session, m->action, now);
}

void wc_init(wc_owner *c, wa_adapter *a) {
    if (!c) return;
    uint32_t exception, mask;
    __asm volatile ("mrs %0, ipsr\n\tmrs %1, primask" : "=r"(exception), "=r"(mask));
    if (!exception && !mask) *c = (wc_owner){.adapter = a};
}

wc_result wc_pump(wc_owner *c, const volatile uint32_t *revision,
                  uint8_t *buffer, uint8_t *status, uint32_t now,
                  wc_stop_receipt *out) {
    if (!context(c)) return WC_REJECTED;
    wa_adapter *a = c->adapter;
    wa_tick(a, now);
    wm_controller *m = &a->runtime.mode;
    if (m->action != WM_QUIESCE_OPTICS && m->action != WM_RESUME_HEALTH) {
        if (c->phase == C_DRAIN || c->phase == C_SUBMITTING || c->phase == C_STOP)
            c->phase = C_IDLE; /* a late STOP observer cannot revive this work */
        if (m->state == WM_HEALTH) c->retired = false;
        return m->action == WM_HOLD_ACCEL && retired_pause(c) ? WC_HOLD_READY : WC_IDLE;
    }
    if (!buffer || !status) return WC_REJECTED;
    if (!closing(c)) {
        bool carry = retired_pause(c);
        if (carry && (buffer != c->buffer || status != c->status)) {
            failed(c, now);
            return WC_FAILED;
        }
        if (m->action == WM_RESUME_HEALTH) {
            if (!revision || !wa_begin_resume(a, m->token, *revision, now)) return WC_REJECTED;
        } else if (a->health.state != WH_QUIESCING || a->health.token != m->token) {
            return WC_REJECTED;
        }
        c->token = m->token;
        c->session = m->session;
        c->generation = a->health.generation;
        c->buffer = buffer;
        c->status = status;
        c->retired = carry;
        c->phase = carry ? C_RESUME : C_DRAIN;
    }
    if (buffer != c->buffer || status != c->status) return WC_REJECTED;
    if (c->phase == C_RESUME) return WC_WAIT_RESUME;
    if (c->phase == C_STOP) return WC_WAIT_STOP;
    if (c->phase != C_DRAIN) return WC_REJECTED;
    const wh_adapter *h = &a->health;
    if (!h->inventory_proven || !h->required_jobs || h->cancelled_jobs != h->required_jobs ||
        h->in_flight || !h->fenced ||
        (h->state != WH_QUIESCING && h->state != WH_RESUMING)) return WC_WAIT_DRAIN;
    if (!out) return WC_REJECTED;
    wc_stop_receipt receipt = {.token = c->token, .session = c->session,
                              .generation = c->generation};
    c->phase = C_SUBMITTING; /* no duplicate submission, including reentry */
    bool written = wb_stock_stop_writes(&receipt.writes);
    uint32_t returned_mask;
    __asm volatile ("mrs %0, primask" : "=r"(returned_mask) :: "memory");
    *out = receipt;
    if (returned_mask) {
        /* A blocking callee broke the entry contract. Do not enable interrupts
         * over its unknown critical section or claim a successful submission. */
        wh_fail(&a->health);
        failed(c, now);
        wa_tick(a, now);
        return WC_FAILED;
    }
    if (!closing(c) || c->token != receipt.token || c->session != receipt.session ||
        c->generation != receipt.generation || c->phase != C_SUBMITTING)
        return WC_REJECTED;
    if (!written) {
        failed(c, now);
        return WC_FAILED;
    }
    c->phase = C_STOP; /* actual successful writes retained, not caller claims */
    return WC_STOP_SUBMITTED;
}

bool wc_optics_stopped(wc_owner *c, const wc_stop_receipt *r, bool physical,
                       uint8_t *buffer, uint8_t *status, uint32_t now) {
    if (!context(c) || !r || c->phase != C_STOP || !closing(c) ||
        r->token != c->token || r->session != c->session || r->generation != c->generation ||
        buffer != c->buffer || status != c->status) return false;
    wa_tick(c->adapter, now);
    if (!closing(c)) return false;
    c->phase = C_IDLE; /* consume before an adapter call can advance the token */
    if (!wa_optics_stopped(c->adapter, r->token, r->generation, physical, now)) {
        if (closing(c)) failed(c, now);
        return false;
    }
    /* wa_optics_stopped may have issued HOLD with a NEW controller token.
     * The old Health pause identity remains the only retirement authority. */
    if (!wop_retire(&c->adapter->health, r->token, buffer, status)) {
        failed(c, now);
        return false;
    }
    c->retired = true;
    c->phase = c->adapter->runtime.mode.action == WM_RESUME_HEALTH ? C_RESUME : C_RETIRED;
    return true;
}

bool wc_resume_prepared(wc_owner *c, const wc_resume_receipt *r,
                        const volatile uint32_t *revision, uint32_t now) {
    if (!context(c) || !r || !revision || c->phase != C_RESUME || !c->retired || !closing(c) ||
        c->adapter->runtime.mode.action != WM_RESUME_HEALTH ||
        r->prepared.token != c->token || r->prepared.generation != c->generation)
        return false;
    if (!wa_resume_ready(c->adapter, r->prepared.token, r->prepared.generation,
                         r->prepared.revision, r->health_preserved, r->scheduler_rebound, now))
        return false;
    bool committed = wsc_commit_health(c->adapter, &r->prepared, revision, now);
    if (committed) {
        c->phase = C_IDLE;
        c->retired = false;
    }
    return committed;
}

bool wc_physical_done(wc_owner *c, const wa_physical_receipt *r, uint32_t now) {
    if (!context(c) || !r) return false;
    if (r->action == WM_HOLD_ACCEL &&
        (c->phase != C_RETIRED || !retired_pause(c))) return false;
    return wa_physical_done(c->adapter, r, now);
}
