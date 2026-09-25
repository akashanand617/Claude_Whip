# Checked optical-timer cancellation — not final firmware

2026-09-23. Off-ring implementation following the request to finish safe health
pause/resume, memory/recovery verification and physical continuity. Installed
V2 is unchanged. No BLE connection, sensor command, firmware transfer or phone
deployment occurred. Health remains the required unified boot/default.

Later [queue-storage compaction](UNIFIED_RESOURCE_BUDGET.md) preserves the full
32-sample queue and behavior while saving 192 RAM bytes and 40 linked flash
bytes. Current build: **2734 tests, zero skips; 239 hashes checked**, in
`build-20260924-optical-acquisition-v1/`. The latest
[optical read audit](UNIFIED_OPTICAL_ACQUISITION.md) shows that failed/cached-only
reads can still yield top-level zero and parsed/read flags. They cannot prove
measured provenance. That continuation changes neither ELF. The preceding unattached
[HR commit guard](UNIFIED_HR_RESULT_COMMIT.md) adds 80 bytes and 60 actual-ARM
cases for four positive-HR stores. Both ELFs change; no stock hooks, source
provenance, production inventory or physical gates are established. The
[optical event audit](UNIFIED_OPTICAL_DISPATCH.md)
adds concrete late cache/publication paths; the timer barrier does not cover
untagged GPIO/software hub events or make entry-only checks atomic. No physical
resume or inventory closure follows. The [status audit](UNIFIED_STATUS_NOTIFICATIONS.md)
adds redacted logging but leaves every foreign packet terminal and physical
cause unknown. A new separately requested [create-hook diagnostic](UNIFIED_CREATE_HOOK_READ.md)
completed all 359 transactions, repeated header/code equality, postchecks and
verified disconnect. The earlier `0x73` abort remains historical. The new code
now executes off-ring through hook success and header equality, while creation
failure reaches unread `0x111a6`; no physical resume proof follows.
Further access needs fresh coordination. The separate [support-code/state diagnostic](UNIFIED_SUPPORT_READ.md)
completed on a separately requested retry: 284 matching transactions and verified
disconnect. New captured helper/context tests pass; the nonzero live create
hook was subsequently captured and selected paths executed off-ring. No serialized
creation/resume proof follows. The earlier
discovery failure is retained separately. The [timer-code read](UNIFIED_TIMER_RESUME_READ.md)
subsequently completed after fresh coordination: 180 matching transactions,
452 new bytes read twice, passing postchecks and verified disconnect. Separate
archive replay and captured creation/default execution are included in the
current build; that diagnostic continuation changed neither ARM ELF.
Native zero-period creation consumes
allocation state before asserting. Conditional conversion hazards are not a
verified hardware tick rate or a completed safe-resume binding.
The [current-controls primitive](UNIFIED_STOCK_SETTINGS.md)
adds a read-only exact-stock snapshot, not a complete resume binding. The
[indicator experiment](UNIFIED_INDICATOR_RETIREMENT.md) remains emulator-only,
not real shutdown or inventory closure. Dispatcher/frame/fence totals 796 bytes;
components occupy 9352 configured flash bytes. This supersedes counts/sizes
below, not cancellation semantics or any physical/memory-ownership gate.

## Latest extension: twelve reviewed timer slots

`wht_stop_reviewed` now exposes the same checked, nonblocking STOP primitive
for all twelve timer slots mapped so far. `wht_stop_scheduled` retains its
original five-job bounds and rejects the additional indices. The original
five slots below keep their indices; the seven additions are:

| Index | Timer slot | Reviewed producer |
|---|---|---|
| 5 | `0x209d40` | Shared realtime 69/6a callback |
| 6 | `0x209d44` | On-demand opcode 0x1e |
| 7 | `0x20c018` | Wear/probe, including deferred result-pointer writes |
| 8 | `0x20bc54` | Activity/exercise |
| 9 | `0x209cc0` | Raw A1 |
| 10 | `0x209d14` | Indicator brightness callback `0x3ac4` |
| 11 | `0x209d10` | Indicator pattern |

These are **reviewed timer slots, not a complete optical producer inventory**.
The main motion-driver timer is not included. Activity and wear timers also
have non-optical obligations; exposing a checked STOP is not authorization or
proof that pausing those entire timers preserves their behavior. Their actual
pause policy and current-settings/fresh-job resume still need integration.
No cancel-all routine or real health receipt was added.

The helper retains all pool/bitmap/queue bounds checks, ISR/masked-context
refusals, PRIMASK restoration and exact-result handling. It writes no stock
health state, deletes no handle, and performs no retry, settings/clock/history
write, resume or device access. The caller-owned serialization/lifetime
obligations described below remain essential. An allocated pool entry does not
by itself prove the timer's job identity or that its slot cannot change.

### New executed evidence

All twelve slots are exercised with distinct synthetic handles, all four
reviewed queue results, empty entries and unallocated entries. Original
scheduled-only and expanded index bounds are checked separately. Twelve
accepted STOP messages execute through captured ROM one at a time, followed
by the compiled timer barrier. Each timer becomes inactive before the barrier
acknowledgment; handles and the other synthetic timer objects are preserved.

Twelve negative witnesses deliberately fail one STOP submission each. The
later barrier can still complete while that specific timer remains active.
**A successful barrier must never erase or substitute for individual STOP
failure handling.** This is a demonstrated integration requirement, not a
claim that the production pause coordinator has already implemented it.

Additional unchanged-stock execution independently verifies raw A1 04/05's
timer arguments and the brightness entry's slot/callback. Raw acquisition is
an explicit intercepted boundary, not executed sensor work. The wider raw
region, neighboring boot/OTA routines and other A1 commands are not admitted.
Other auxiliary mappings retain their existing stock entry/cancel witnesses.
Queue/list/timing/RTOS boundaries remain synthetic as described below.

### Size investigation and unchanged construction limits

No compiler optimization was adopted. The experiments retained the same
`0x847ad0..0x84a000` append bounds and did not reclaim stock bytes:

- Per-function sections exceeded the bound; the pinned Zig driver rejected
  the requested safe identical-code-folding option. Forced outlining gave
  the unchanged 9220-byte baseline.
- Apple-Clang LTO bitcode failed the pinned linker's record parser. Using
  Zig for both compile and link, with every public function retained, still
  exceeded the bound, with and without LTO.
- Disabling inlining yielded 9204 bytes; a zero inline threshold yielded
  9116 bytes. Neither was adopted: the small gain does not establish room for
  the remaining integration, and changed call chains need their own review.
- Single-translation-unit experiments, with colliding private names isolated,
  also exceeded the unchanged bound. `-Os` did not improve the fit.

All experiments were off-ring temporary compiler outputs, not release builds.
No public API, safety check, linker assertion or existing test was removed to
obtain a fit. The twelve-slot extension under the unchanged build flags occupies
**9264/9520 configured bytes**, leaving **256**, with no static writable RAM.
The new primitive's local ARM stack frame is 48 bytes; the compatibility wrapper
adds an 8-byte frame when called, excluding further callees and interrupts.
Dispatcher/frame/fence state remains 988 bytes, still not approved RAM.

The final firmware is **not ready**: real admissions/serialization, hub/IRQ/RUN/
publication fences, physical STOP, current-settings resume, complete integration
fit and RAM ownership/recovery, and physical model/steps/sleep continuity remain
open. Nothing here restores optical Health on the installed V2 image or permits
an installable unified container. A new device session still needs a bounded
plan and fresh client coordination.

### Latest guarded build record

`firmware/unified/build-20260923-reviewed-timers-v1/`: **1733 tests passed in
120.05 seconds**, zero skips/failures/errors/xfails. This includes all 85 added
cases; the separate focused run passed 322 tests and overlaps the full suite.
Both compile/link layouts reproduced identical bytes. All **192 hashes** were
independently checked: 128 inputs, 61 artifacts and three proof reports.

- Manifest SHA-256:
  `7262ee0c46bf7785f654adba440ddc611312d0f78a1ce93e00e85b152602906b`.
- Artificial-address test ELF SHA-256:
  `9c5598e7ef242176bbb20dbd5d645459e54fe6a9f0e52cc80f19b37c65eeb5da`.
- Actual-address component ELF SHA-256:
  `411cc06b6f5f9d4f3ba382f0ea0e0e1d717cf3ae046c7e122491d9700dafa47c`.
- Linked extent ends at `0x849f00`: 9176 text/constant bytes plus 88 unwind
  bytes, 44 bytes more than the preceding five-job build.

`flashable`, `stock_linked`, `hardware_access` and `ram_ownership_verified`
remain false. No Swift changed; no new simulator run, phone deployment,
separate legacy-regression run, commit or push occurred. The full gate includes
compiled Swift checks, not a phone or physical-ring test.

## Earlier implementation: five scheduled jobs

`firmware/unified/stock_health_timers.{c,h}` adds `wht_stop_scheduled`. Unlike
the legacy app's stop/delete wrapper, it does not ignore STOP failure, delete
the timer, clear its handle or reset the job's health state. It binds to the
reviewed stock image and captured ROM only; never use these stock RAM slots on
the installed V2 image.

| Job index | Stock timer slot | Meaning |
|---|---|---|
| 0 | `0x20c0c4` | Scheduled HR |
| 1 | `0x20c0ac` | Scheduled SpO2 |
| 2 | `0x20c0e8` | Reviewed owner `0x200` |
| 3 | `0x20c0f0` | Reviewed owner `0x100` |
| 4 | `0x20c104` | Reviewed owner `0x1000` |

The primitive rejects unknown indices, interrupt context and callers with
interrupts already disabled. In a bounded, PRIMASK-preserving critical section,
it reads the exact slot and checks the stock timer queue, timer pool, count,
allocation bitmap and timer index. Pool and bitmap spans must be aligned and
fit the fixed SRAM address bounds. Subtractions and index calculations are
bounded before dereferencing a timer. An empty slot is reported separately.

Only then, with interrupts restored, it calls captured `xTimerGenericCommand`
at `0x108e1` with `(handle, STOP=3, value=0, wake=NULL, wait=0)`. Only return
value **1** is accepted. Other results report queue failure. It does not retry.
The SRAM bounds reject implausible addresses; they do **not** prove actual
allocation ownership or the queue's lifetime/type.

The legacy ROM STOP path checks range/alignment but not the allocation bit;
this primitive checks the bit as well. The captured ROM's invalid-handle path
deliberately writes through a null pointer. Refusing invalid/free entries before
that API is a concrete safety improvement, not a complete cancellation proof.

## Required serialization is still a binding obligation

All timer creation/restart/deletion admissions must already be closed, and the
caller must own a domain that prevents timer-pool reuse through the ROM call.
This includes already queued deletes and higher-priority callbacks. A critical
section around the initial reads alone cannot protect the later enqueue call.
The primitive deliberately does not invoke an RTOS API with interrupts masked.
It remains **unattached**, because that production domain is not implemented.

Empty/accepted are not `wh_cancelled`, `wh_fenced` or `wh_stopped` receipts.
Already dispatched callbacks, queued optical hub work, IRQs, in-flight RUN and
result publications need their own generation/lifetime barriers. This five-job
table also does not cover realtime, wear, activity, raw/debug or indicators.
Do not promote it to the complete health producer inventory.

There is intentionally no blind “resume all old timers” function. Old job
handles/state cannot be replayed as new health work: settings may have changed,
callbacks may contain stale results, and stock activity/reset paths can discard
state. The existing portable current-revision resume/commit code is retained;
actual current-settings scheduler and fresh-job bindings are still required.

## Executed tests and explicit substitutes

`tests/test_stock_health_timers.py` executes the real-address compiled C and
captured generic-command/daemon instructions together. It tests all five slots,
empty entries, queue failures and unusual returns, null/misaligned/out-of-range
metadata, pool bounds, mismatched timer numbers, free allocation bits, bitmap
word boundaries, interrupt/masked entry and non-stack health-RAM preservation.

One combined chain queues all five actual STOP commands, then queues the
compiled timer barrier. The captured daemon clears each active bit while the
barrier remains incomplete; only the later captured callback dispatch reaches
the compiled acknowledgment. Handles remain unchanged. The test does not write
a fabricated acknowledgment into the fence to obtain completion.

Queue send/receive, division, scheduler-state query, tick count, list removal
and compiler switch-helper boundaries are explicitly substituted. The switch
substitute reads the real captured table. SRAM and timer metadata are fixtures;
FIFO ordering is an assumption of the synthetic queue, not measured kernel or
hardware behavior. The test does not establish sensor shutdown, thread safety,
interrupt latency, step counts or sleep accuracy.

## Capacity and raw/debug reuse investigation

The new object has a 48-byte ARM local stack frame, excluding callees and
interrupts, and no static writable RAM. The complete component link now uses
**9220 of 9520 configured bytes**, leaving **300**. Existing dispatcher/frame/
fence state remains 988 bytes; ownership of the nominal RAM gap is unapproved.
This is not a fit claim for the remaining hardware hooks or a complete image.

An exploratory scan of the pinned stock raw/debug area found shared structure,
not a disposable contiguous code cave:

- Raw handler `0x2104` has an external queued-dispatch call at `0x6688` and
  shares an epilogue at `0x202a` with the raw report routine.
- Callback `0x1e4a` is referenced through the literal at `0x239c` and by raw
  entry paths. Earlier non-raw getter/A0 code references constants within the
  wider apparent raw region, so erasing that region wholesale would be unsafe.
- Startup calls adjacent `0x2360` at `0x12f8`; OTA completion calls adjacent
  `0x2384` at `0x864a`. These must not be swept into a debug-code replacement.
- Getter `0x1e42` has callers at `0x2bf8` and `0xa764` outside the raw handler.

The exploratory scan is not an exhaustive indirect-call/reference closure.
No byte was reclaimed, no linker bound was enlarged, and the boot overlay and
DFU code remain intact. Explicit retirement/hooks and all shared data/control
references must be resolved before considering any such reuse.

## What prevents a final release

| Requested outcome | Still needed |
|---|---|
| Safe health pause/resume | Complete producer/result inventory; real serialization and cancellation/drain; verified physical STOP; fresh jobs resumed from current settings |
| Verified memory/recovery | Fit of the entire integration; approved RAM/stack ownership; physical flash geometry; reviewed boot/copy/recovery and an actual usable recovery route |
| Physical motion/steps/sleep continuity | Reviewed acquisition observer; physical FIFO timing/completion/overflow trace; finalized-model replay; controlled step and overnight sleep comparisons across transitions |

The stock binary/captured ROM are useful references but cannot manufacture an
overnight trial, an electrical shutdown observation or recovery access. The
installed V2 image's globally disabled optics cannot validate unified optical
Health. No production source profile, installable unified container, flash
approval or automatic on-ring test follows from this component.

Before another device session, define its exact commands/read bounds and
coordinate exclusive access again. The preceding ROM retry is complete, not
standing authorization. Do not flash this component ELF or bypass the locked
unified builder through the generic byte patcher.

## Guarded build record

`firmware/unified/build-20260923-health-cancel-v1/` passed **1648 tests in
113.77 seconds**, zero skips/failures/errors/xfails. The 60 new cancellation
cases are included, not a separate addition to that count. Compilation and
both link layouts rebuild identically. All **192 hashes** were independently
checked: 128 inputs, 61 artifacts and three reports. Test collection and each
test's setup/call/teardown identities agree.

- Manifest SHA-256:
  `9b3f7c3df3947c6362f083807845ba5233be7254819bfd1fbb8b634882610313`.
- Artificial-address test ELF SHA-256:
  `d546d66bba8d0de3a57eb494fc46b35538f08ca0e32c1fee543783e6eb724741`.
- Actual-address component ELF SHA-256:
  `4b20d6adba8a8bebff268a0aedb753dde1bb58d13ec9855a8192634a00db7cd1`.
- Append ends at `0x849ed4`: 9132 text/constant bytes plus 88 unwind bytes.
  This adds 328 linked bytes and zero static RAM to the preceding build.

`flashable`, `stock_linked`, `hardware_access` and `ram_ownership_verified`
remain false. No simulator or separate legacy-regression rerun, app deployment,
commit or push. The suite includes compiled Swift checks, not a phone test.
The exploratory `stock-health-timers-20260923-v1/` link predates the final queue-
pointer validation; it is not the current guarded result and is not installable.
