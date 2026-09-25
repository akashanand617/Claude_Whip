#ifndef WHIP_MODE_CONTROLLER_H
#define WHIP_MODE_CONTROLLER_H
#include <stdbool.h>
#include <stdint.h>

/* Portable policy only. No stock adapter, addresses, RTOS calls or flash writes.
 * Call from ONE serialized firmware task, never directly from interrupt context.
 * Completion means the physical postcondition was verified, not merely queued.
 */
typedef enum { WM_HEALTH, WM_ENTERING, WM_GESTURE, WM_RETURNING, WM_FAULT } wm_state;
typedef enum {
    WM_NONE, WM_QUIESCE_OPTICS, WM_HOLD_ACCEL, WM_START_25HZ,
    WM_STOP_STREAM, WM_RELEASE_ACCEL, WM_RESUME_HEALTH
} wm_action;
typedef enum {
    WM_USER, WM_DISCONNECT, WM_LEASE, WM_CHARGING, WM_ACTION_FAILED, WM_ACTION_TIMEOUT,
    WM_STREAM_FAILED
} wm_reason;
typedef enum { WM_HEALTH_MEASUREMENT, WM_DECORATIVE_INDICATOR, WM_RAW_OPTICAL_DEBUG } wm_optical_purpose;

typedef struct {
    wm_state state;
    wm_action action;
    wm_reason reason;
    uint32_t token, session, deadline_ms, lease_ms, last_sequence;
    bool connected, charging, have_sequence;
} wm_controller;

#define WM_LEASE_MS 30000u
#define WM_ACTION_TIMEOUT_MS 3000u

/* Called only AFTER the stock boot path successfully initialized Health. */
void wm_init(wm_controller *c);
void wm_link(wm_controller *c, bool connected, bool charging, uint32_t now);
bool wm_request(wm_controller *c, bool gesture, uint32_t now);
bool wm_complete(wm_controller *c, uint32_t token, bool success, uint32_t now);
bool wm_renew(wm_controller *c, uint32_t session, uint32_t processed_sequence, uint32_t now);
void wm_tick(wm_controller *c, uint32_t now);
void wm_stream_failed(wm_controller *c, uint32_t now);
bool wm_optics_allowed(const wm_controller *c);
bool wm_optical_start_allowed(const wm_controller *c, wm_optical_purpose purpose);
#endif
