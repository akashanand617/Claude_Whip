#ifndef WHIP_HEALTH_ADAPTER_H
#define WHIP_HEALTH_ADAPTER_H
#include <stdbool.h>
#include <stdint.h>

/* OFFLINE lifecycle adapter component, not installed stock hooks.
 * All calls and the final hardware RUN/publication commits must share a proven
 * serialization domain. No addresses, timers, I2C, sensor cursors or NVM here.
 * Receipts below are evidence supplied by the real binding, NEVER queued intent.
 * An unresolved physical STOP/inventory/drain obligation must remain false.
 */
#define WH_JOB_LIMIT 32u
typedef enum {
    WH_HEALTH, WH_QUIESCING, WH_PAUSED, WH_RESUMING, WH_READY, WH_FAULT
} wh_state;
typedef struct {
    uint32_t generation, serial;
    uint8_t job;
} wh_ticket;
typedef struct {
    wh_state state;
    uint32_t generation, job_generation, token, next_serial;
    uint32_t required_jobs, cancelled_jobs, in_flight;
    uint32_t settings_revision;
    uint32_t jobs[WH_JOB_LIMIT];
    bool inventory_proven, fenced, stopped;
} wh_adapter;

/* Once per boot AFTER stock Health initialized. A zero/unproven inventory
 * starts faulted/closed. Inventory means ALL timer/start/result producers, not
 * just enabled schedules. Health measurements only; indicators/raw never start.
 * An unproven binding must disable unified Gesture capability, leaving stock
 * Health untouched; do NOT install these closed guards over stock Health.
 */
void wh_init(wh_adapter *h, uint32_t required_jobs, bool inventory_proven);
bool wh_begin_quiesce(wh_adapter *h, uint32_t controller_token);
bool wh_cancelled(wh_adapter *h, uint32_t token, uint32_t generation, uint32_t jobs);
bool wh_fenced(wh_adapter *h, uint32_t token, uint32_t generation);
bool wh_stopped(wh_adapter *h, uint32_t token, uint32_t generation, bool verified);
bool wh_quiesced(const wh_adapter *h, uint32_t token);
/* Pure permission for bounded software-buffer retirement. A partial-entry
 * recovery may establish fresh quiet proof while RESUMING without ever having
 * reached PAUSED. READY is excluded: retirement must precede fresh scheduler
 * preparation, not erase work after it. Does not create any physical receipt.
 */
bool wh_retirement_allowed(const wh_adapter *h, uint32_t token);

/* Partial entry may be cancelled: resume may begin before quiescence completed.
 * In that case cancel/fence/STOP evidence is required anew under the new token
 * and generation. A fully closed/drained PAUSED proof can carry across resume.
 * No call here replays an old optical owner mask or writes Health settings.
 */
bool wh_begin_resume(wh_adapter *h, uint32_t controller_token, uint32_t settings_revision);
bool wh_resume_ready(wh_adapter *h, uint32_t token, uint32_t generation,
                     uint32_t current_revision, bool health_preserved,
                     bool scheduler_rebound);
bool wh_can_commit(const wh_adapter *h, uint32_t token, uint32_t current_revision);
/* Call only AFTER runtime accepted WM_RESUME_HEALTH, in the same critical
 * section as current-settings revalidation. READY itself keeps all gates shut.
 */
bool wh_commit_health(wh_adapter *h, uint32_t token, uint32_t current_revision);

/* Every actual measurement job (including delayed timer/result work) gets a
 * boot-unique serial. The real adapter carries this ticket through deferred
 * work; looking up the newest ticket when an OLD callback fires is forbidden.
 * begin_run is immediately before actual RUN or a shared-sensor acquisition
 * under the binding's serialization; end_run marks that operation completed,
 * even if pause intervened. One in-flight operation per job, never overlapping
 * RUN/read calls. All work retains the original ticket until completion.
 */
bool wh_job_begin(wh_adapter *h, uint8_t job, wh_ticket *ticket);
bool wh_run_begin(wh_adapter *h, wh_ticket ticket);
bool wh_run_end(wh_adapter *h, wh_ticket ticket, bool write_succeeded);
bool wh_result_allowed(const wh_adapter *h, wh_ticket ticket, bool measured);
bool wh_job_end(wh_adapter *h, wh_ticket ticket);
void wh_fail(wh_adapter *h);
#endif
