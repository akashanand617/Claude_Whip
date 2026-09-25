#ifndef WHIP_UNIFIED_DISPATCH_H
#define WHIP_UNIFIED_DISPATCH_H
#include "adapter.h"
#include "wire.h"

/* OFFLINE serialized command owner. Not registered GATT, a stock hook, a
 * capability authorization or permission to invent physical receipts.
 * Initialize ONCE per boot AFTER stock Health. Prepare only a reviewed source
 * profile through adapter; complete physical work through wa_* receipt APIs.
 * All calls (including wa_* completions) need the SAME serialization domain.
 */
#define WD_OPERATION_MS 10000u
enum { WD_CLOSED, WD_IDLE, WD_RECEIVING, WD_WAITING, WD_REPLY };
enum { WD_OK, WD_UNAVAILABLE, WD_BUSY, WD_INVALID, WD_FAULT };
typedef struct {
    wa_adapter adapter;
    ww_rx rx;
    uint32_t boot_lo, boot_hi, connection, last_id, started, session;
    uint8_t state, operation, part;
    bool offered;
    uint8_t reply[WW_BODY_BYTES];
} wd_dispatch;

void wd_init(wd_dispatch *d, uint32_t jobs, bool inventory_proven,
             uint32_t boot_lo, uint32_t boot_hi);
/* Connection generations strictly increase during this boot; zero/wrap/reuse
 * rejected. Open only after reviewed identity/capability/service admission.
 * No active connection replacement: close/drain old callbacks first.
 */
bool wd_open(wd_dispatch *d, uint32_t connection, bool charging, uint32_t now);
bool wd_close(wd_dispatch *d, uint32_t connection, uint32_t now);
bool wd_charging(wd_dispatch *d, uint32_t connection, bool charging, uint32_t now);
void wd_tick(wd_dispatch *d, uint32_t now);
/* A current-connection framing/order/replay/concurrency violation closes this
 * control owner and initiates Health cleanup. Binding must then physically
 * disconnect/fence pending sends; no software flag undoes a late hardware send.
 * Old-connection callbacks are ignored without touching the new exchange.
 * IDs strictly increase per connection. No retry/re-execution or reply cache.
 */
bool wd_receive(wd_dispatch *d, const uint8_t *frame, uint32_t length,
                uint32_t connection, uint32_t now);
/* Copies one frame into caller-owned 20 bytes; at most one offer outstanding.
 * Capture connection, rx.id and part AT OFFER for the eventual send receipt.
 * Actual enqueue must be in the serialized domain and recheck this ownership.
 * An accepted receipt is enqueue acceptance, NOT remote delivery/processing.
 */
bool wd_reply_next(wd_dispatch *d, uint32_t connection, uint8_t *frame, uint32_t now);
bool wd_reply_sent(wd_dispatch *d, uint32_t connection, uint32_t request,
                   uint8_t part, bool accepted, uint32_t now);
#endif
