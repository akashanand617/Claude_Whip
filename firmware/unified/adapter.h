#ifndef WHIP_UNIFIED_ADAPTER_H
#define WHIP_UNIFIED_ADAPTER_H
#include "runtime.h"
#include "health_adapter.h"
#include "fresh_source.h"

/* OFFLINE component integration, NOT installed stock/RTOS/transport hooks.
 * All operations, hardware commits, receipt creation and settings revalidation
 * belong to ONE proven serialization domain. No default source profile exists.
 * Missing inventory/profile disables Gesture, never stock's boot Health path.
 * Do not call lower-level completion/offer APIs to bypass these checks.
 */
typedef struct {
    wr_runtime runtime;
    wh_adapter health;
    ws_source source;
    /* One owned profile in source.profile, including while Health is active.
     * It may change only in Health with the source stopped. No caller pointer
     * is retained; Gesture's validation and selection use the same snapshot.
     */
    bool profile_ready;
} wa_adapter;

enum {
    WA_ACCEL_HELD = 1u << 0,
    WA_HEALTH_PRESERVED = 1u << 1,
    WA_CONFIG_CHECKED = 1u << 2,
    WA_SOURCE_SERIALIZED = 1u << 3,
    WA_SOURCE_STOPPED = 1u << 4,
    WA_CALLBACKS_FENCED = 1u << 5,
    WA_TRANSPORT_DRAINED = 1u << 6,
    WA_ACCEL_RELEASED = 1u << 7
};
typedef struct {
    uint32_t token, session;
    wm_action action;
    uint32_t postconditions, config_epoch, binding_id;
} wa_physical_receipt;

/* Once after stock Health initialized. An unavailable/unproven inventory is
 * represented internally by WH_FAULT but is NOT a request to shut stock Health
 * down or install incomplete gates. See wa_health_passthrough/allowed.
 */
void wa_init(wa_adapter *a, uint32_t required_jobs, bool inventory_proven);
/* Health-only copy of a profile ALREADY pinned/reviewed by the eventual binding.
 * Numerical/digest consistency is not attestation. Invalid/null clears readiness.
 */
bool wa_prepare(wa_adapter *a, const ws_profile *profile);
bool wa_health_passthrough(const wa_adapter *a);
bool wa_health_allowed(const wa_adapter *a, wm_optical_purpose purpose);
void wa_tick(wa_adapter *a, uint32_t now);
void wa_link(wa_adapter *a, bool connected, bool charging, uint32_t now);
bool wa_request(wa_adapter *a, bool gesture, uint32_t now);

/* Actual job cancellation/drain, start/publication fence and verified physical
 * optical STOP, not enqueue acceptance. Valid only for current QUIESCE or RESUME.
 * The final successful QUIESCE STOP advances runtime to HOLD automatically.
 */
bool wa_cancelled(wa_adapter *a, uint32_t token, uint32_t generation,
                  uint32_t jobs, uint32_t now);
bool wa_fenced(wa_adapter *a, uint32_t token, uint32_t generation, uint32_t now);
bool wa_optics_stopped(wa_adapter *a, uint32_t token, uint32_t generation,
                       bool physically_stopped, uint32_t now);
/* Only HOLD, STOP_STREAM and RELEASE. No generic START or RESUME success path.
 * HOLD requires HELD|HEALTH_PRESERVED|CONFIG_CHECKED|SOURCE_SERIALIZED plus exact
 * config/binding identity. It starts observation but leaves START pending.
 * STOP requires STOPPED|CALLBACKS_FENCED|TRANSPORT_DRAINED, including every old
 * entry/hold/start operation, outstanding callback and pending physical send.
 * RELEASE requires RELEASED|HEALTH_PRESERVED even after partial/failed entry.
 */
bool wa_physical_done(wa_adapter *a, const wa_physical_receipt *receipt, uint32_t now);
bool wa_action_failed(wa_adapter *a, uint32_t token, uint32_t session,
                      wm_action action, uint32_t now);
/* First WS_DELIVER atomically completes START and offers the physical sample.
 * Valid receipts with no selection leave START pending. Fault initiates cleanup.
 */
ws_result wa_observe(wa_adapter *a, const ws_receipt *receipt, uint32_t now);

/* Begin captures CURRENT settings at RESUME. Partial entry must supply a fresh
 * cancel/fence/STOP proof under this token/generation; PAUSED proof may carry.
 * READY leaves both publication/RUN gates closed. Commit must reread settings
 * in the same serialized operation and atomically commit runtime and WH gates.
 */
bool wa_begin_resume(wa_adapter *a, uint32_t token, uint32_t current_revision, uint32_t now);
bool wa_resume_ready(wa_adapter *a, uint32_t token, uint32_t generation,
                     uint32_t current_revision, bool health_preserved,
                     bool scheduler_rebound, uint32_t now);
bool wa_commit_health(wa_adapter *a, uint32_t token, uint32_t current_revision, uint32_t now);

/* Enqueue acceptance is a separate physical receipt, never stock void enqueue.
 * Binding revalidates session immediately at enqueue; STOP fences queued work.
 */
bool wa_next(wa_adapter *a, uint32_t session, wt_sample *sample, uint32_t now);
bool wa_sent(wa_adapter *a, uint32_t session, uint32_t sequence, bool accepted, uint32_t now);
bool wa_renew(wa_adapter *a, uint32_t session, uint32_t processed_sequence, uint32_t now);
#endif
