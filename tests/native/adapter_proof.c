/* TEST-ONLY fixtures for both native and actual-Thumb execution. No hardware,
 * qualified profile, writable global state, transport mock acceptance or I/O.
 * Every operation's arguments are explicit u32 words, as documented below.
 */
#include "adapter.h"
#include <stddef.h>

unsigned proof_adapter_size(void) { return sizeof(wa_adapter); }

/* Test-only ABI witnesses for the single-address-space stock switch runner. */
unsigned proof_switch_layout(unsigned field) {
    switch (field) {
    case 0: return offsetof(wa_adapter, health);
    case 1: return sizeof(ws_profile);
    case 2: return sizeof(ws_receipt);
    case 3: return offsetof(ws_receipt, bytes);
    case 4: return offsetof(ws_receipt, acquired);
    case 5: return sizeof(wa_physical_receipt);
    case 6: return sizeof(ws_delivery);
    default: return UINT32_MAX;
    }
}

static ws_profile fixture_profile(void) {
    ws_profile p = {.config_epoch = 1, .binding_id = 2,
        .observed_frames = 101, .observed_span_ms = 2000,
        .minimum_period_ms = 20, .maximum_period_ms = 20,
        .chip_id = 0x23, .range = 5, .bandwidth = 15, .power = 0x74, .fifo_config = 0xc8};
    p.evidence_sha256[0] = 0xee; /* Made up, NEVER a qualified physical profile. */
    return p;
}

/* key: 0 state, 1 action, 2 token, 3 session, 4 WH state, 5 WH generation,
 * 6 WS active, 7 tap count, 8 pending, 9 Health allowed, 10 passthrough,
 * 11 WS transaction, 12 WS acquisition, 13 WH cancelled, 14 WH inflight,
 * 15 WH fenced, 16 WH stopped, 17 settings revision, 18 sent sequence,
 * 19 source oldest, 20 reason, 21 WH token, 22 profile readiness,
 * 23 tap sequence, 24 first queued native axis0, 25 pending sequence,
 * 26 WH job_generation, 27 job0 serial, 28 WH nextserial, 29 lease deadline.
 */
uint32_t proof_adapter_get(const wa_adapter *a, uint32_t key) {
    switch (key) {
    case 0: return a->runtime.mode.state;
    case 1: return a->runtime.mode.action;
    case 2: return a->runtime.mode.token;
    case 3: return a->runtime.mode.session;
    case 4: return a->health.state;
    case 5: return a->health.generation;
    case 6: return a->source.progress.active;
    case 7: return a->runtime.tap.count;
    case 8: return a->runtime.awaiting_send;
    case 9: return wa_health_allowed(a, WM_HEALTH_MEASUREMENT);
    case 10: return wa_health_passthrough(a);
    case 11: return a->source.transaction;
    case 12: return a->source.acquisition;
    case 13: return a->health.cancelled_jobs;
    case 14: return a->health.in_flight;
    case 15: return a->health.fenced;
    case 16: return a->health.stopped;
    case 17: return a->health.settings_revision;
    case 18: return a->runtime.last_sent;
    case 19: return a->runtime.last_source_at;
    case 20: return a->runtime.mode.reason;
    case 21: return a->health.token;
    case 22: return a->profile_ready;
    case 23: return a->runtime.tap.sequence;
    case 24: return (uint32_t)(int32_t)a->runtime.tap.queue[a->runtime.tap.head].axis[0];
    case 25: return a->runtime.pending.sequence;
    case 26: return a->health.job_generation;
    case 27: return a->health.jobs[0];
    case 28: return a->health.next_serial;
    case 29: return a->runtime.mode.lease_ms;
    case 30: return a->source.profile.config_epoch;
    case 31: return a->source.profile.binding_id;
    default: return UINT32_MAX;
    }
}

/* All argument reads are within 12 words (caller supplies initialized words).
 *  0 init: jobs, inventory, profile_present
 *  1 prepare: profile_present (0 means NULL)
 *  2 link: connected, charging, now
 *  3 request: gesture, now
 *  4 tick: now
 *  5 cancelled: token, generation, jobs, now
 *  6 fenced: token, generation, now
 *  7 optics_stopped: token, generation, physically_stopped, now
 *  8 physical_done: token, session, action, postconditions, epoch, binding, now
 *  9 action_failed: token, session, action, now
 * 10 observe: session, transaction, first_time, count, status_time,
 *             completed_time, now, fault_mask
 *    synthetic frames every20ms; native axis0 = transaction*32+frame index;
 *    fault bits 1=I2C failure,2=overflow,4=partial,8=wrongconfig,16=wrongbinding,
 *               32=future/ambiguous firstframe,64=countstatus mismatch.
 * 11 begin_resume: token, current_revision, now
 * 12 resume_ready: token, generation, current_revision, preserved, rebound, now
 * 13 commit_health: token, current_revision, now
 * 14 next: session, now (return sequence, 0 if refused)
 * 15 sent: session, sequence, accepted, now
 * 16 renew: session, processed_sequence, now
 * 17 job_begin: job (return boot serial, 0 if refused)
 * 18 run_begin: generation, serial, job
 * 19 run_end: generation, serial, job, physical_success, now
 * 20 result_allowed: generation, serial, job, measured
 * 21 job_end: generation, serial, job
 * 22 purpose_allowed: purpose
 * 23 exhaust_job_serial: now (test-only boundary, then actual job_begin/tick)
 */
uint32_t proof_adapter_call(wa_adapter *a, uint32_t op, const uint32_t *v) {
    switch (op) {
    case 0: {
        wa_init(a, v[0], v[1] != 0u);
        ws_profile p = fixture_profile();
        if (v[2]) return wa_prepare(a, &p);
        return 1;
    }
    case 1: {
        ws_profile p = fixture_profile();
        return wa_prepare(a, v[0] ? &p : 0);
    }
    case 24: {
        ws_profile p = fixture_profile();
        p.config_epoch = v[0];
        p.binding_id = v[1];
        bool accepted = wa_prepare(a, &p);
        p = (ws_profile){0}; /* Later mutation must not change the owned copy. */
        return accepted;
    }
    case 2: wa_link(a, v[0] != 0u, v[1] != 0u, v[2]); return 1;
    case 3: return wa_request(a, v[0] != 0u, v[1]);
    case 4: wa_tick(a, v[0]); return 1;
    case 5: return wa_cancelled(a, v[0], v[1], v[2], v[3]);
    case 6: return wa_fenced(a, v[0], v[1], v[2]);
    case 7: return wa_optics_stopped(a, v[0], v[1], v[2] != 0u, v[3]);
    case 8: {
        wa_physical_receipt r = {.token = v[0], .session = v[1], .action = (wm_action)v[2],
            .postconditions = v[3], .config_epoch = v[4], .binding_id = v[5]};
        return wa_physical_done(a, &r, v[6]);
    }
    case 9: return wa_action_failed(a, v[0], v[1], (wm_action)v[2], v[3]);
    case 10: {
        ws_receipt r = {.session = v[0], .transaction = v[1],
            .config_epoch = 1, .binding_id = 2, .count = (uint8_t)v[3],
            .fifo_status = (uint8_t)v[3], .status_at = v[4], .completed_at = v[5],
            .requested_bytes = (uint16_t)(v[3] * 6u), .completed_bytes = (uint16_t)(v[3] * 6u)};
        for (uint32_t i = 0; i < v[3] && i < WS_FIFO_FRAMES; i++) {
            (void)ws_set_bounds(&r, i, v[2] + i * 20u, v[2] + i * 20u);
            uint16_t value = (uint16_t)(v[1] * 32u + i);
            r.bytes[i * 6u] = (uint8_t)value;
            r.bytes[i * 6u + 1u] = (uint8_t)(value >> 8u);
            r.bytes[i * 6u + 3u] = 0x80;
            r.bytes[i * 6u + 4u] = r.bytes[i * 6u + 5u] = 0xff;
        }
        if (v[7] & 1u) r.transport_result = 1;
        if (v[7] & 2u) r.fifo_status |= 0x80;
        if (v[7] & 4u) r.completed_bytes = 0;
        if (v[7] & 8u) r.config_epoch++;
        if (v[7] & 16u) r.binding_id++;
        if (v[7] & 32u) (void)ws_set_bounds(&r, 0, v[2], v[2] + 40u);
        if (v[7] & 64u) r.fifo_status = 0;
        if ((v[7] & 128u) && v[8] < r.count && v[8] < WS_FIFO_FRAMES)
            (void)ws_set_bounds(&r, v[8], v[2] + v[8] * 20u,
                                v[2] + v[8] * 20u + 3u);
        return wa_observe(a, &r, v[6]);
    }
    case 11: return wa_begin_resume(a, v[0], v[1], v[2]);
    case 12: return wa_resume_ready(a, v[0], v[1], v[2], v[3] != 0u, v[4] != 0u, v[5]);
    case 13: return wa_commit_health(a, v[0], v[1], v[2]);
    case 14: {
        wt_sample sample;
        return wa_next(a, v[0], &sample, v[1]) ? sample.sequence : 0;
    }
    case 15: return wa_sent(a, v[0], v[1], v[2] != 0u, v[3]);
    case 16: return wa_renew(a, v[0], v[1], v[2]);
    case 17: {
        wh_ticket t;
        return wh_job_begin(&a->health, (uint8_t)v[0], &t) ? t.serial : 0;
    }
    case 18: return wh_run_begin(&a->health, (wh_ticket){v[0], v[1], (uint8_t)v[2]});
    case 19: {
        bool result = wh_run_end(&a->health, (wh_ticket){v[0], v[1], (uint8_t)v[2]}, v[3] != 0u);
        wa_tick(a, v[4]);
        return result;
    }
    case 20: return wh_result_allowed(&a->health, (wh_ticket){v[0], v[1], (uint8_t)v[2]}, v[3] != 0u);
    case 21: return wh_job_end(&a->health, (wh_ticket){v[0], v[1], (uint8_t)v[2]});
    case 22: return wa_health_allowed(a, (wm_optical_purpose)v[0]);
    case 23: {
        wh_ticket t;
        a->health.next_serial = UINT32_MAX;
        bool result = wh_job_begin(&a->health, 0, &t);
        wa_tick(a, v[0]);
        return result;
    }
    default: return 0;
    }
}
