#include "control_mailbox.h"

enum { OPEN = 1u, REPORTED = 32u, COUNT = 192u, HEAD = 256u,
       REASONS = WIM_LINK_LOST | WIM_CHARGING | WIM_FAULT };
_Static_assert(sizeof(wim_mailbox) == 56, "review mailbox ownership budget");
_Static_assert(sizeof(wim_event) == 32, "review consumer scratch budget");

static uint32_t lock(void) {
    uint32_t prior;
    __asm volatile ("mrs %0, primask\n\tcpsid i" : "=r"(prior) :: "memory");
    return prior;
}
static void unlock(uint32_t prior) {
    __asm volatile ("msr primask, %0" :: "r"(prior) : "memory");
}
static bool current(const wim_mailbox *m, uint32_t generation) {
    return (m->flags & OPEN) && generation && m->generation == generation;
}
static void close_locked(wim_mailbox *m, uint32_t reasons) {
    if ((m->flags & reasons) != reasons) m->flags &= ~REPORTED;
    m->flags = (m->flags & ~COUNT) | reasons;
}
void wim_init(wim_mailbox *m) {
    if (m) *m = (wim_mailbox){0};
}
bool wim_open(wim_mailbox *m, uint32_t generation) {
    if (!m) return false;
    uint32_t prior = lock();
    bool ok = !m->flags && generation && generation > m->generation;
    if (ok) {
        m->generation = generation;
        m->flags = OPEN;
    }
    unlock(prior);
    return ok;
}
bool wim_post(wim_mailbox *m, uint32_t generation, const uint8_t *frame,
              uint32_t length, uint32_t received) {
    if (!m) return false;
    uint32_t prior = lock();
    bool ok = false;
    if (current(m, generation) && !(m->flags & REASONS)) {
        unsigned count = (m->flags & COUNT) >> 6;
        if (!frame || length != WW_FRAME_BYTES || count == 2u) {
            close_locked(m, WIM_FAULT);
        } else {
            unsigned index = (((m->flags & HEAD) >> 8) + count) & 1u;
            for (unsigned i = 0; i < WW_FRAME_BYTES; ++i) m->slots[index].frame[i] = frame[i];
            m->slots[index].received = received;
            m->flags += 64u;
            ok = true;
        }
    }
    unlock(prior);
    return ok;
}
bool wim_close(wim_mailbox *m, uint32_t generation, uint32_t reasons) {
    if (!m || !reasons || (reasons & ~REASONS)) return false;
    uint32_t prior = lock();
    bool ok = current(m, generation);
    if (ok) close_locked(m, reasons);
    unlock(prior);
    return ok;
}
bool wim_admitted(const wim_mailbox *m, uint32_t generation) {
    if (!m) return false;
    uint32_t prior = lock();
    bool ok = current(m, generation) && !(m->flags & REASONS);
    unlock(prior);
    return ok;
}
uint32_t wim_take(wim_mailbox *m, uint32_t now, wim_event *out) {
    if (!m || !out) return WIM_NONE;
    uint32_t prior = lock();
    uint32_t kind = WIM_NONE;
    unsigned head = (m->flags & HEAD) >> 8;
    if ((m->flags & COUNT) && (uint32_t)(now - m->slots[head].received) > WW_TIMEOUT_MS)
        close_locked(m, WIM_FAULT);
    if ((m->flags & REASONS) && !(m->flags & REPORTED)) {
        *out = (wim_event){ .generation = m->generation, .reasons = m->flags & REASONS };
        m->flags |= REPORTED;
        kind = WIM_CLOSED;
    } else if (m->flags & COUNT) {
        out->generation = m->generation;
        out->received = m->slots[head].received;
        for (unsigned i = 0; i < WW_FRAME_BYTES; ++i) out->frame[i] = m->slots[head].frame[i];
        out->reasons = 0u;
        m->flags = (m->flags - 64u) ^ HEAD;
        kind = WIM_FRAME;
    }
    unlock(prior);
    return kind;
}
bool wim_retire(wim_mailbox *m, uint32_t generation) {
    if (!m) return false;
    uint32_t prior = lock();
    bool ok = current(m, generation) && (m->flags & REASONS) && (m->flags & REPORTED);
    if (ok) m->flags = 0u;
    unlock(prior);
    return ok;
}
