# Unified health lifecycle adapter — offline component

Date: 2026-09-23. **Not installed, not an OTA image, not a completed hardware
binding.** No ring, BLE or phone was used for this work. Health remains the
default. Unresolved lifecycle evidence keeps unified Gesture unavailable; it
must not install a permanently closed guard over ordinary stock Health.

Read [UNIFIED_HEALTH_LIFECYCLE.md](UNIFIED_HEALTH_LIFECYCLE.md) for the stock
optical STOP failures, STK ownership and acquisition-cadence limitations, and
[UNIFIED_WORKFLOW.md](UNIFIED_WORKFLOW.md) for the whole candidate's gates.
This component does not establish steps, sleep, clinical measurement accuracy,
battery benefit, safe RAM placement or firmware recovery.

The [integrated switch runner](UNIFIED_READINESS.md#integrated-sequence-implemented)
now exercises this C with original optical read/clear/TX and motion-consumer
paths in one persistent ARM state. Cancellation/physical STOP/fresh-job resume
remain named fixtures; the runner does not attach this component to hardware.
The later [source-storage reduction](UNIFIED_RESOURCE_BUDGET.md) retains that
integrated runner and exact timestamp behavior with smaller receipt/scratch.
It does not complete the Health hardware binding or steps/sleep continuity.

Later [checked cancellation](UNIFIED_HEALTH_CANCELLATION.md) implements validated
nonblocking STOP submissions for these five scheduled jobs and executes them
with the captured ROM and timer fence. It remains unattached, requires proven
serialization and does not close the broader inventory, physical STOP or resume.

The newer [current-settings binding](UNIFIED_STOCK_SETTINGS.md) implements an
unattached exact-stock four-byte read primitive and executes the real settings
getters/setters/minute selection. It does not turn a snapshot into a resume
receipt. Whole-tick replay and independent job-state assumptions are unsafe
shortcuts: pending time is consumed, due minutes can be skipped, and two starts
share a working parameter. Use the [resource handoff](UNIFIED_RESOURCE_BUDGET.md)
for current build counts and sizes; the earlier suite counts below are historical.

The [captured timer creation/resume execution](UNIFIED_TIMER_RESUME_READ.md)
adds a concrete binding requirement: validate the native period before
allocation/queue submission. Native create consumes an allocation before a
zero-period assertion; creating a new callback/ID does not itself start work.
Later [actual hook execution](UNIFIED_CREATE_HOOK_READ.md) now covers conversion
and the selected wrapper/hook success path, but empty-handle failure reaches
unread `0x111a6`. A nonzero requested period or a truthy hook-handled return is
not a safe-resume receipt.

The newer [optical event/commit audit](UNIFIED_OPTICAL_DISPATCH.md) traces a
separate GPIO/software event through hub subtype zero and actual HR/SpO₂ result
stores. With synthetic cached-ready/algorithm state, late processing after STOP
can restore result state and reach scheduled aggregation without a new enable.
Entry-only admission and current-ticket relabeling both have explicit negative
witnesses. This adds a concrete missing producer/commit path, not a complete
inventory, installed guard or physical observation.

The subsequent [HR result-commit primitive](UNIFIED_HR_RESULT_COMMIT.md) now
implements the original-ticket check and four exact-stock positive-result
stores in one bounded PRIMASK section. It executes compiled ARM and matches
the unchanged stock block; it is **unattached** and supplies no measured
provenance, real inventory assignment, other-result guard or physical receipt.
Caller-owned context/source identity and NMI/DMA exclusion remain obligations.

The [optical acquisition audit](UNIFIED_OPTICAL_ACQUISITION.md) replaces former
status/parser/classification mocks with selected actual read-chain instructions.
Stock can return zero and mark flags complete after receive failure, or without
reading at all when cached. Those flags/returns cannot supply the commit guard's
`measured` argument. Source/algorithm/job association and sample-buffer retirement
still require actual attachment; no production provenance flag was added.

The [optical work implementation](UNIFIED_OPTICAL_WORK.md) now adds unattached
`wop_read` and `wop_retire` C bindings. RUN's in-flight bit also covers a shared-
sensor read, so no cancellation/fence/STOP receipt can complete during it.
Retirement executes the stock software clear even when old ready is zero, and
clears acquisition flags only after fully evidenced PAUSED. It neither flushes
hardware FIFO nor supplies measured provenance/current-settings resume. Stock
allocation/release-result limitations, original producer identity and physical
fences remain obligations, not hidden successes.

The subsequent [heap-free I/O integration](UNIFIED_OPTICAL_IO.md) replaces
exactly two sample-reader BLs in emulator memory with checked caller-buffer
operations. This fixes the selected allocation/release-result defects, not
all stock I/O. FE/FF remain separate mutex scopes; no physical receipt or
producer identity follows. The original wrapper alone does not install edits.

## Executable component and evidence boundaries

`firmware/unified/health_adapter.{c,h}` contains a freestanding C lifecycle
component with no stock addresses, register accesses, BLE, allocator or NVM.
It accepts explicit receipts from a future audited binding. A receipt is never
inferred from a queued command, elapsed timeout, cleared byte or wrapper return.

`tests/test_health_adapter.py` compiles that C for native execution and ARMv6-M.
The native stress program runs 20,000 pause/resume cycles with 16 jobs per cycle:
320,000 synthetic measured-result admissions and 320,000 stale-ticket rejections,
including overlapping RUN, partial-entry cancellation, and changed settings.
ASan/UBSan check memory and undefined behavior. Its 168-byte host context is a
local size measurement, **not permission to use 168 bytes anywhere on the ring**.
The complete component suite passed **65 tests, zero skips** in the proof
environment, including native sanitizers, ARM compilation and stock witnesses.

`whip/fwhealth_adapter.py` executes additional unchanged stock Thumb ranges in
the strict existing Unicorn harness. The full input hash is pinned to:

```
firmware/rt02cr-stock-3.12.02.bin
b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0
runtime address = file offset + 0x825fb0
```

Peripheral access remains mocked. Timer create/delete calls are recorded, not
executed by a real RTOS. Settings, wear/activity predicates and timestamps are
explicit fixture inputs. Aggregation is intercepted and never reaches flash or
NVM. The publication observer calls compiled `wh_result_allowed` with the
**original captured job ticket**. This is a real-C/unchanged-stock boundary test,
not a trampoline, installed gateway or real measurement provenance implementation.

## State and receipt contract

```
HEALTH -> QUIESCING -> PAUSED -> RESUMING -> READY -> HEALTH
                    failure -> FAULT -> RESUMING (new proof required)
```

Only HEALTH admits new measurement jobs, physical RUN entry and measured result
publication. READY is deliberately still closed. The final commit must share a
proven serialization region with the runtime's accepted `WM_RESUME_HEALTH` and
the current-settings revision check; the runtime must already be HEALTH before
`wh_commit_health` opens the gates. A queued resume or scheduler-rebind request
does not satisfy this ordering.

1. `wh_init`: after stock Health initialization, once per boot. A complete,
   nonzero, reviewed producer inventory is required. The job mask is a binding's
   own inventory, **not the stock optical owner mask**. Disabled schedules still
   belong to the inventory. Zero or unreviewed inventory closes the component.
2. `wh_job_begin`: assigns a boot-unique serial plus generation to one logical
   job. Every deferred timer, RUN request, callback and result retains that
   ticket. Looking up the newest ticket when old work fires is forbidden.
   Reusing a job slot requires ending its old ticket; serials never repeat.
3. `wh_run_begin`: immediately before real RUN under the shared serialization
   contract. It records an in-flight operation. `wh_run_end` completes that
   captured operation even if quiescence began meanwhile. A hardware write
   failure faults the component. These APIs do not perform the write themselves.
4. `wh_begin_quiesce(token)`: advances generation, closes starts/results at once,
   and clears old cancellation/fence/STOP evidence. Controller tokens must
   increase, are nonzero and never wrap. Generation/serial exhaustion faults.
5. `wh_cancelled`: receipt for actual cancellation/draining of selected known
   producers. A job with RUN still in flight cannot be marked cancelled. The
   binding additionally must account for deferred callbacks and queued hub work;
   the component cannot inspect the RTOS itself.
6. `wh_fenced`: only after all inventoried jobs are cancelled and RUN flights
   have ended. This receipt means old queued work can no longer produce an
   unguarded RUN or result. It is not merely a queue-empty snapshot.
7. `wh_stopped`: only after the fence and drain. A false physical-stop receipt
   faults the component; a true receipt is a binding obligation requiring
   independently established postconditions. Only then is `wh_quiesced` true.
8. `wh_begin_resume(token, current_revision)`: does not replay saved optical
   masks or settings. A fully PAUSED proof carries forward while gates stay
   closed. If entry was interrupted in QUIESCING, or the component is FAULT,
   cancellation/fence/STOP must be proved anew under the new token/generation.
9. `wh_resume_ready`: requires quiet, preserved stock health state, current
   settings and scheduler rebind. A revision mismatch remains closed and
   requires a new rebind receipt. False preservation/rebind faults. Neither
   READY nor any earlier state may reopen optics while runtime is RETURNING.
10. `wh_can_commit` / `wh_commit_health`: revalidate current revision at the
    final commit. Changed settings invalidate readiness. Successful commit
    retires old job slots and admits new jobs under the new generation.

All calls require caller-owned serialization. In particular, checking
`wh_result_allowed` and then later publishing without a shared critical section
would permit pause to interleave. Checking RUN admission outside the actual
hardware-commit domain has the same race. There is no invented lock or ROM ABI
inside this module. Runtime deadlines are separate from these receipts.

## Exact-stock scheduled jobs

Offsets below are file offsets; timer slots are absolute RAM addresses. Metric
names not independently confirmed remain owner-mask labels.

| Job | Start | Callback | Timer slot | Owner mask | Aggregation boundary |
|---|---:|---:|---:|---:|---:|
| Scheduled HR | `0xe420` | `0xe384` | `0x20c0c4` | `0x10` | `0xe2e4`, value in r1 |
| Scheduled SpO2 | `0xe168` | `0xe104` | `0x20c0ac` | `0x80` | `0xe0c6`, value in r0 |
| owner 0x200 | `0xe8c2` | `0xe856` | `0x20c0e8` | `0x200` | `0xe7bc`, value in r0 |
| owner 0x100 | `0xea58` | `0xe9e0` | `0x20c0f0` | `0x100` | `0xe948`, value in r0 |
| owner 0x1000 | `0xecbe` | `0xec54` | `0x20c104` | `0x1000` | `0xeb7c`, value in r0 |

The stock start paths post `(type=3, subtype=1, mask)` through `0xdd04`, then
request timer creation through `0x3e04` with r0=slot, r1=Thumb callback pointer,
r2=1000, r3=1. Tests execute enabled and disabled settings branches and verify
these exact arguments. Timer wall-clock behavior is not inferred from `1000`.
Stock cancellation posts `(3,2,mask)` through `0xdcea`, separately requesting
timer deletion through `0x3e30`.

Alternative HR entry `0xe51c` uses the same mask/timer/callback, checks the timer
slot and runtime guards, and can start outside the normal scheduled settings
entry. Therefore guarding only `0xe420` is insufficient. The helper `0xe56c`
clears the HR job's timestamp/counter area; this is not permission to call it
as a general preservation-safe resume routine.

## Generated results and publication proof

All five callbacks have generated-value branches. This is not merely a concern
that could theoretically occur: unchanged Thumb executes those branches under
explicit timeout fixtures and reaches the observed aggregation boundary.

| Callback | Generated branch demonstrated | Observed fixture result |
|---|---|---:|
| HR `0xe384` | getter below 40, PRNG modulo 10 plus 40 | 46 |
| SpO2 `0xe104` | zero result after count 65; PRNG modulo 7 plus 93, then setter | 99 |
| owner 0x200 `0xe856` | zero result after count 50; PRNG modulo 20 plus 30 | 36 |
| owner 0x100 `0xe9e0` | zero result at count 60; PRNG modulo 20 plus 30 | 36 |
| owner 0x1000 `0xec54` | zero result at count 50; PRNG parity plus 360, setter subtracts 200 | 160 |

The fixture PRNG result is 6. HR publishes within the same callback; the other
four first store a generated value and publish on a subsequent callback.
Additional branches clamp or replace out-of-range existing values, including
HR above 120 under specific wear/activity state, and SpO2 at or below 93.
This table does not enumerate every numerical output of every algorithm path.

The observer marks a job unmeasured as soon as its PRNG boundary executes and
retains that mark across callbacks. Even an optimistic synthetic source flag
cannot promote that generated path. C rejects these outputs both in Health and
after pause. Positive-control values admitted as explicitly synthetic measured
fixtures pass only in Health with the matching original ticket; pause and a
completed resume/new ticket both reject the old callback. A plausible value
without verified provenance remains unmeasured and is rejected.

There is **no production provenance flag yet**. The real binding must prove
which acquisition/algorithm result belongs to which job and reject fallback or
old cache before aggregator entry. Stock `0xf74c` returns `OPTICAL+2` only in
state 2, otherwise `OPTICAL+0xc`; neither a plausible byte nor state 2 by itself
establishes acquisition freshness or clinical correctness.

## Additional producers: the real inventory is not closed

The pinned image's 21 reviewed direct BL sites to enable-post `0xdd04` are
recorded in `ENABLE_POST_CALLERS`. This covers the direct call scan, not indirect
calls, ROM producers, indicator-specific configuration or every VC register
write. It must not be substituted for `inventory_proven=true`.

| Producer | Exact evidence | Additional binding requirement |
|---|---|---|
| Raw A1 | `0x21c4,0x222a,0x2290,0x22b2` post enable | Reject raw entry/retained raw timer while unified gestures use their separate source; no reuse of destructive raw reader |
| Realtime 69/6a | handler `0x52a0`; starts at `0x5368,0x53ca,0x53d8,0x53ec,0x540a,0x5446,0x5486` | Shared timer `0x209d40` callback is **0x4722**, dispatching `0x4518` for mode 6 and `0x40d6` otherwise |
| Delayed realtime restart | `0x45d6` can re-enable mask 1 | Retain ticket through timer dispatch; gate actual RUN as well as initial UART handler |
| Realtime result | `0x4518` family calls PRNG, perturbs getter and reaches notify `0x7e30` | Scheduled-aggregator guards alone do not suppress realtime publications |
| Opcode 0x1e | handler `0x4e4a`, enable at `0x4e72`, mask `0x4000` | Separate timer `0x209d44`, callback `0x4e0c`, 60-count lifetime, explicit stop at `0x4e8e` |
| Activity/exercise | entry `0xa88a`, enable mask 1 at `0xa922`; stop `0xaa00` posts disable at `0xaa0e` | Timer slot `0x20bc54`; activity lifecycle and shared algorithm parameters must not be reset casually |
| Wear/probe | entry `0xde38`, enable mask 2 at `0xde96` | Timer `0x20c018`, callback `0xde04`, period argument 2500; results written through up to two caller pointers |
| Indicator | `0x3af4,0x3b06,0x3b44` call `0xf812` outside ordinary measurement owners | Cancel pattern and brightness producers and guard lower RUN; mask-only filtering is incomplete |
| Optical GPIO/software event | `0xd8f0` / `0xd9f8` post `(3,0,0)`; `0xdd6e` → `0xf7a8` → `0xf774` → `0xf308` | Untagged deferred processing can write result caches without new enable; retain origin identity or prove retirement and fence actual commits, not just entry |

Tests execute opcode 0x1e start, reporting, timeout and explicit stop: its STOP
is still only a hub post, with no observed hardware writes in that call. Tests
also execute two wear/probe requests and the deferred callback, observing both
caller bytes written before pointer/state clearing and timer cancellation.
Those pointer writes are a second reason an aggregator-only guard is incomplete.

The realtime mapping includes owner masks 1, 0x20, 0x400, 0x100, 0x200, 0x1000,
and composite modes; cancellation can use 0x1301 or 0x1701. Do not confuse
`69 06 02` (timer stop only) with `69 06 04` (mask-1 disable plus timer stop).
These offsets describe stock 3.12.02; no V2 offsets were ported.

## Remaining binding gates

The off-ring [status-notification audit](UNIFIED_STATUS_NOTIFICATIONS.md)
additionally executes three `0x73` packet constructors and their checksum
helpers in stock/original25Hz/V2. Selected callers include motion consumption,
SpO2 aggregation and device state; the family is not uniformly Health or
uniformly harmless. These publication paths and already queued packets belong
in the inventory review. No new production result guard, physical cause or
complete caller/queue-lifetime proof follows from the constructor tests.

- Close the complete producer and result-sink inventory, including indirect
  callbacks, wear pointer writes, activity and indicator work. Decide the
  approved logical job identities; no real adapter mask is assigned here.
- Establish RTOS context, cancellation acknowledgement, callback drain,
  hub-message generation binding and a common serialization domain. A cancel
  API return is not automatically a callback fence.
- Carry tickets through actual deferred work and actual RUN/result commits.
  Do not stamp an old message with the current generation at dequeue time.
- Prove physical STOP through verified sensor postconditions and write-error
  handling. Stock `0x10eaa` returning zero is not that proof; previous tests
  demonstrate ignored RESET/STOP write failures and cleared ownership anyway.
- Resume from **current** settings without restoring stale masks, enabling
  disabled schedules, resetting steps/sleep cursors, clearing history, changing
  the clock, or duplicating an interrupted optical result. Revalidate settings
  at commit. A settings-version counter itself needs a wrap-safe binding.
- Preserve the stock motion reader/cursor and native ODR/FIFO contract.
  Steps/sleep acquisition continuity and cadence are separate gates from this
  optical pause component; they remain unproved on hardware.
- Review memory ownership, executable placement, ABI, recovery and complete
  integration before any image/flash path can become eligible.

Successful host or emulator tests satisfy only their named boundaries. Until
these gates have evidence, the correct production capability is unavailable,
with ordinary stock Health left alone.
