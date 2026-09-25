#include <assert.h>
#include <stdio.h>
#include "health_adapter.h"

int main(void) {
    wh_adapter h;
    wh_ticket tickets[16];
    unsigned measured = 0, stale = 0;
    uint32_t token = 0;
    wh_init(&h, UINT32_C(0xffff), true);
    for (unsigned cycle = 0; cycle < 20000; cycle++) {
        assert(h.state == WH_HEALTH);
        for (uint8_t job = 0; job < 16; job++) {
            assert(wh_job_begin(&h, job, &tickets[job]));
            assert(wh_run_begin(&h, tickets[job]));
            if ((job & 1u) == 0u) assert(wh_run_end(&h, tickets[job], true));
            assert(!wh_result_allowed(&h, tickets[job], false));
            assert(wh_result_allowed(&h, tickets[job], true));
            measured++;
        }
        assert(wh_begin_quiesce(&h, ++token));
        uint32_t old_generation = h.generation;
        for (uint8_t job = 0; job < 16; job++) {
            assert(!wh_run_begin(&h, tickets[job]));
            assert(!wh_result_allowed(&h, tickets[job], true));
            stale++;
            if ((job & 1u) != 0u) {
                assert(!wh_cancelled(&h, token, h.generation, UINT32_C(1) << job));
                assert(wh_run_end(&h, tickets[job], true));
            }
            assert(wh_cancelled(&h, token, h.generation, UINT32_C(1) << job));
        }
        if (cycle & 1u) {
            assert(wh_fenced(&h, token, h.generation));
            assert(wh_stopped(&h, token, h.generation, true));
            assert(wh_quiesced(&h, token));
        }
        assert(wh_begin_resume(&h, ++token, cycle));
        assert(!wh_stopped(&h, token - 1, old_generation, false));
        if ((cycle & 1u) == 0u) {
            assert(!wh_resume_ready(&h, token, h.generation, cycle, true, true));
            assert(wh_cancelled(&h, token, h.generation, h.required_jobs));
            assert(wh_fenced(&h, token, h.generation));
            assert(wh_stopped(&h, token, h.generation, true));
        }
        assert(wh_resume_ready(&h, token, h.generation, cycle, true, true));
        assert(!wh_job_begin(&h, 0, &tickets[0]));
        assert(!wh_commit_health(&h, token, cycle + 1));
        assert(h.state == WH_RESUMING);
        assert(wh_resume_ready(&h, token, h.generation, cycle + 1, true, true));
        assert(wh_commit_health(&h, token, cycle + 1));
        for (uint8_t job = 0; job < 16; job++) {
            assert(!wh_result_allowed(&h, tickets[job], true));
            assert(!wh_run_end(&h, tickets[job], false));
        }
    }
    printf("{\"cycles\":20000,\"measured\":%u,\"stale_rejected\":%u,\"context_bytes\":%zu}\n",
           measured, stale, sizeof(h));
    return 0;
}
