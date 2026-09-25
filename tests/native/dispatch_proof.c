/* Test scaffolding only: never a real profile, transport or physical receipt. */
#include "dispatch.h"
#include <stddef.h>
typedef struct { wd_dispatch d; uint8_t frame[WW_FRAME_BYTES]; } fixture;
uint32_t proof_adapter_call(wa_adapter *, uint32_t, const uint32_t *);
unsigned proof_dispatch_size(void) { return sizeof(fixture); }
unsigned proof_dispatch_output_offset(void) { return offsetof(fixture, frame); }
unsigned proof_dispatch_adapter_offset(void) { return offsetof(wd_dispatch, adapter); }
uint32_t proof_dispatch_get(const fixture *f, uint32_t key) {
    const wd_dispatch *d = &f->d;
    switch (key) {
    case 0: return d->state;
    case 1: return d->connection;
    case 2: return d->last_id;
    case 3: return d->rx.id;
    case 4: return d->part;
    case 5: return d->offered;
    case 6: return d->operation;
    default: return UINT32_MAX;
    }
}
uint32_t proof_dispatch_call(fixture *f, uint32_t op, const uint32_t *v) {
    wd_dispatch *d = &f->d;
    switch (op) {
    case 0:
        wd_init(d, v[0], v[1] != 0, v[3], v[4]);
        return proof_adapter_call(&d->adapter, 0, v); /* synthetic profile */
    case 1: return wd_open(d, v[0], v[1] != 0, v[2]);
    case 2: return wd_close(d, v[0], v[1]);
    case 3: wd_tick(d, v[0]); return 1;
    case 4: return wd_charging(d, v[0], v[1] != 0, v[2]);
    case 5: return wd_reply_next(d, v[0], f->frame, v[1]);
    case 6: return wd_reply_sent(d, v[0], v[1], (uint8_t)v[2], v[3] != 0, v[4]);
    default: return 0;
    }
}
