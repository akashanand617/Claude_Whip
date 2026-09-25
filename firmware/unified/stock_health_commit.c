#include "stock_health_commit.h"
#include "stock_schedule_settings.h"

bool wsc_commit_health(wa_adapter *a, const wsc_prepared *p,
                       const volatile uint32_t *current_revision, uint32_t now) {
    uint32_t exception, prior;
    __asm volatile ("mrs %0, ipsr" : "=r"(exception));
    if (exception || !a || !p || !current_revision ||
        (((uintptr_t)a | (uintptr_t)p | (uintptr_t)current_revision) & 3u))
        return false;
    __asm volatile ("mrs %0, primask\n\tcpsid i" : "=r"(prior) :: "memory");
    bool committed = false;
    if (a->runtime.mode.state != WM_RETURNING ||
        a->runtime.mode.action != WM_RESUME_HEALTH ||
        a->health.state != WH_READY || p->token == 0u || p->generation == 0u ||
        p->token != a->runtime.mode.token || p->token != a->health.token ||
        p->generation != a->health.generation ||
        p->revision != a->health.settings_revision)
        goto out;
    uint32_t revision = *current_revision;
    if (revision != p->revision) {
        /* Existing path invalidates READY without publishing Health. */
        (void)wa_commit_health(a, p->token, revision, now);
        goto out;
    }
    if (wss_read_controls() != p->controls) {
        /* A visible writer bypassed its required revision contract. Do not
         * guess a revision, silently retain READY, or restart an old job. */
        wh_fail(&a->health);
        wa_tick(a, now);
        goto out;
    }
    committed = wa_commit_health(a, p->token, revision, now);
out:
    __asm volatile ("msr primask, %0" :: "r"(prior) : "memory");
    return committed;
}
