#ifndef WHIP_STOCK_EVENT_GATE_H
#define WHIP_STOCK_EVENT_GATE_H
#include <stdint.h>

/* UNATTACHED exact-stock common-event gate. A published, non-0xff unified
 * service ID is suppressed before event is dereferenced. Every other ID,
 * including the general-event sentinel 0xff, reaches original file0x6f28
 * unchanged. Event remains opaque: service-local and general layouts differ.
 * Return0 on suppression is NOT a completed action, send receipt or admission.
 *
 * wgs_service_id must be qualified, unique, and stable once per boot; no ID
 * reuse or re-registration with old events is supported. Before publication,
 * dedicated read/write/CCCD callbacks must fail closed and NEVER fall through
 * to the old common callback. This gate does not establish that prerequisite.
 * Both setup literal roots0x7788/0x77ac require separate reviewed attachment;
 * retained/computed pointers and direct old-entry calls are not fenced here.
 * No stock patch, event parser, handler, ownership or physical fence is added.
 */
uint32_t wge_common(uint8_t service, void *event);
#endif
