# Unified firmware: integration milestone and finite readiness gates

2026-09-24/25. **Not flash-ready.** Health is the boot/default; Gesture is opt-in
and temporary. The daily ring is still V2 optical-off. One fixed read-only
gateway diagnostic has since completed; it neither restores optical Health nor
changes the ring.

This is the current decision checklist, not another chronological audit.
Historical evidence remains linked below. Passing more isolated tests does not
change a gate without the missing evidence named here.

The latest [whole-28 compiler assessment](UNIFIED_RESOURCE_BUDGET.md) rejects
two fit shortcuts. Exact sources reproduce all28 current objects. Short enums
save only72 input-text bytes and violate the 880-byte owner ABI. Append-unit LTO
with all38 no-in-set-caller public roots saves112 text bytes but adds456 linked
unwind bytes, making measured append occupancy344 bytes worse. The artificial
baseline is1324 over; even all790 gross FEE7 bytes would leave at least534 bytes
over before real write/CCCD and physical bindings. Nothing is adopted; no gate
closes.

The newer [UART-multiplexing size lead](UNIFIED_RESOURCE_BUDGET.md) removes the
need for a separate replacement service by reserving length20/versioned traffic
on the already-required UART path. Its reproducible artificial link occupies
**9484/9520 bytes**, leaving only **36 bytes** after selected functions are
placed across all gross FEE7 spans. The ingress and clock implementations are
fake six-byte fixtures, complete FEE7 retirement/ownership is unproved, and no
status-handshake/app/callback-drain behavior is implemented. It is a promising
architecture decision point, not a production ELF, fit proof or gate closure.

The [fixed gateway diagnostic](UNIFIED_STACK_GATEWAY_READ.md) passed 444 guarded
preflight tests, then completed 122/122 physical requests with repeated equality
and confirmed disconnect. ROM `0x4926` performs the guarded indirect call; the
live slot points to the installed Upper Stack execution address `0x80e400`.
The reader did not follow the pointer, start a sensor or flash. Target dispatch,
callback provenance and disconnect drain remain unproved, so no gate closes.
Setup/cancellation cleanup is explicitly owned by the separate CLI; the initial
413-case preflight predates that correction and is historical.

New [control-ingress counterexamples](UNIFIED_CONTROL_INGRESS.md):107 guarded
tests pass (13 new). A hypothetical current-generation lookup can mislabel old
write callbacks after short connection-ID reuse and trigger software Gesture
entry; preserving original generation rejects them. This is not an observed
ring-stack bug. Write/CCCD attachment needs original event identity or a proven
upstream disconnect/drain barrier. The compatible seventh write argument is not
independently verified by stock's first-six-argument use; do not dereference it
on that evidence alone. No production callback or format change was made.

Newest [discovery callback and combined startup](UNIFIED_WECHAT_RETIREMENT.md):
**178 guarded tests pass**. Selected service registration, dual-root gate and
advertising paths now run in one persistent ARM context; the separate actual
six-argument discovery callback returns only an initialized identity view and
does not admit Gesture. Real publication/lifetime, write/CCCD, hardware and full
startup remain unqualified. Whole **28-object lower bound is 10798/9520,
1278 over**, with **six strong bindings** missing, including identity storage.
The existing identity20 is not additional RAM. No production ELF or gate change.
Earlier 27/26-object numbers below are historical subtotals.

Latest [direct WeChat audit and routing guards](UNIFIED_WECHAT_RETIREMENT.md):
144 guarded tests pass. The slot adapter preserves four retained services and
five registrations. A new opaque gate covers both known callback pointer roots;
separate exact-stock edits remove the FEE7 service-list advertisement while
preserving manufacturer data. These are unattached, emulator-only witnesses,
not full startup or physical discovery. All **27 objects require at least
10706/9520**, still **1186 over**, before the 12-byte callback constant and
remaining bindings. Five strong bindings remain missing; no production ELF.
Retained/computed roots, prepublication callbacks and ownership remain open.
Surveyed 790 gross bytes are not approved reclamation. No ring access or
release gate changes.

Claude's subsequent [GATT resource read](UNIFIED_GATT_RESOURCES.md) is now
independently verified: 172/172 matching transactions, seven twice-equal windows
and confirmed disconnect. The ring Upper Stack is not the reference build;
one reference address actually falls in the ring APP. No reference allocator
or RAM address may be copied into a hardware binding. The user's verified
WeChat-only retirement decision permits designing a replacement for its FEE7
registration slot while preserving UART, DFU, DIS and HID. It does not approve
reclaimed memory, physical registration or a flash. This avoids designing for
a sixth service, but still requires complete old-callback/ID retirement and
owned new callbacks/state. No gate closes.

The [final-binding inventory](UNIFIED_FINAL_BINDINGS.md) records the exact
remaining owner, stock-pointer/revision and clock work. In particular, the
existing stock clock leaf cannot simply supply the monotonic-ms symbol: its
32-bit multiplication admits a premature wrap. No placeholder definitions
are permitted to turn the current strict link refusal into a release build.

The latest [storage experiment](UNIFIED_TIMESTAMP_STORAGE.md) passes44 guarded
tests and would save64 persistent RAM bytes without shrinking the queue.
It is not adopted core: full downstream low16 integration and stack review are
still required. Its whole25 lower bound remains1088 bytes over capacity and
does not close any gate below. Accepted source and preceding proofs are intact.

Newest [control-owner checkpoint](UNIFIED_CONTROL_OWNER.md): real C supervisor,
dispatcher and coordinator compose with a two-fragment mailbox and original
arrival deadline. The stock wait-loop path and selected original Health paths
execute in one persistent artificial ARM context; physical/clock/storage/ROM
bindings remain explicit fixtures. The **25-object production link refuses
three strong physical bindings**. Input-only append lower bound is
**10610/9520 bytes, at least 1090 over**, with the same 1894 unowned moved bytes.
Persistent planning is **1244 bytes**, without double counting the 880-byte
embedded owner; no owned allocation or bounded cadence is proved. Main 3251
regression passes again, separately from **258 guarded integration cases** and
767 content hashes in `research-20260925-control-owner-v2/`. All six gates
remain open; earlier 22/24-object margins below are historical subtotals.

Latest [integrated switching](UNIFIED_RETIRED_SWITCH.md) runs the actual C
coordinator and original Health sample paths in one persistent ARM context with
the pinned 21-object layout and 18 emulator-only instruction edits. Known
queued/stored legacy roots stay suppressed throughout nine phases. Physical,
RTOS and downstream step/sleep boundaries remain fixtures, not closed gates.

The separate [discovery candidate](UNIFIED_DISCOVERY.md) supplies the C/Swift
read-only identity format, without callbacks, ownership or app admission. All
**22 objects/132 functions** link conditionally: **9256 append bytes, 264 left**,
plus the same **1894 unowned moved-text bytes**. Discovery executes separately
at actual linked addresses; the full switch was not rerun in that new layout.
The final **63-test guarded supplement** passed with **253 content hashes**
independently verified; the simulator app build also passes. No device access.

Subsequent [task-context mapping](UNIFIED_TASK_BINDINGS.md) establishes selected
Health scheduling/consumption in **qc_app**, acquisition/optical work in **hub**,
and callback execution in **Tmr Svc**. None is already a single unified owner.
qc_app waits indefinitely on a semaphore and has blocking/unbounded service
paths: simply inserting `wd_tick` there does **not** guarantee the 1 s/3 s/10 s
protocol/action/operation deadlines. An independent bounded supervisor wake and
bounded cross-context handoff must be implemented and included in the budget.

The [read-callback audit](UNIFIED_GATT_READ_BINDING.md) confirms six arguments,
no context pointer, and an outstanding owned-lookup/lifetime requirement.
The [boot-ID source audit](UNIFIED_BOOT_ID_SOURCE.md) finds stock's actual
`platform_random` startup call, but no qualified entropy/failure/reset contract.
The shared software PRNG is not a fresh 64-bit boot-ID source. These findings
narrow the binding work; no new callback, owner, supervisor or generator is
installed. The separate GATT resource audit was pending at that historical
checkpoint; its subsequently verified result is linked above. Those three
earlier audits use stock/public source only.

Preceding [combined retirement supplement](UNIFIED_STOCK_RETIREMENT.md): its
21 objects/130 functions link with **9132 append bytes, 388 left**,
using **1894 bytes of unowned** legacy regions. An exact-ELF-pinned 16-edit
plan retires known entries only in the emulator; the ELF alone has no stubs
and is production-rejected. The separate **55-test guarded supplement** passes
(42 placement, 13 combined); selected queued/direct/stored roots and original
Health/DFU paths execute together, with explicit hardware/algorithm fixtures.
That earlier suite is not full switching or closure of all indirect/retained
roots. Its planner remains pinned to the 21-object ELF. No gate closes.

Latest coordinated checkpoint: **3251 guarded tests passed**, zero skips,
**371 source/artifact/report hashes independently checked** in
`firmware/unified/build-20260924-raw-ingress-v1/`. Both main ELFs remain identical
to the coordinator checkpoint. Coordinator, Health commit, service and the
early **A1/BF/CE/CD** filter are separately tested unlinked candidates; all current
code at that checkpoint together exceeds the fixed final region by **1588 bytes**,
with no ELF; the newer discovery unit is additional to that append-only refusal.
Claude's separate device read measured only **264 free data-heap bytes, 104
minimum-ever**, ruling out a heap fallback for the 1164-byte selected state on
measured V2. Its unchanged gap observation does not establish ownership. See the
[resource handoff](UNIFIED_RESOURCE_BUDGET.md) for exact sizes/hashes and the
qualified linker-boundary correction. No gate closes from these software results.
The [ROM resume review](UNIFIED_ROM_RESUME_EVIDENCE.md) also finds an explicit
normal-return continuation toward first boot; unread context-restore behavior
must exclude it before claiming boot-only RAM is reusable. Equal gap digests
across ~4.61 hours are no observed net change, not proven DLPS retention.
The [independent stack review](UNIFIED_STACK_EVIDENCE.md) verifies three more
archives and six task observations, but sampled paint is not a stack-pointer
depth bound, proven future reserve or stock-Health workload qualification.

## Six release gates

| Gate | Current evidence | Required to close |
|---|---|---|
| Integrated switching and image fit | Persistent 21-object retired-layout switch remains separate. Actual C wait/mailbox/dispatcher/coordinator compose in an artificial owner ELF with selected original Health paths. Slot/gate/advertising paths compose separately; real discovery-read callback is separately exercised. Current-generation ingress relabeling fails the new replay witness. Whole 28-object input lower bound 10798/9520; six bindings missing; cadence unproved. | Close old roots and preserve Health; establish original callback ownership or real upstream disconnect/drain before ID reuse; bind one serialized owner with bounded handoff/deadline wake; attach coordinator/hooks/service; qualify physical bindings and boot identity; all remaining code fits reviewed storage reproducibly. |
| Memory ownership | Actual component sizes/selected stack paths; no writable static section. V2 heap 264 free/104 minimum; gap/paint do not prove ownership/headroom. Persistent planning: 1164 + identity 20 + mailbox 56 + arrival 4 = 1244, plus new service ID 1; event 32 is stack scratch. | Owned boot/retention state, scratch and task/interrupt stack; heap reserve/failure handling; flash/erase geometry and final placement. |
| Optical pause and current-settings resume | Checked STOP writes, selected read/commit guards, timer primitives and software retirement execute. | Closed producer/result inventory; original job identities; serialized timer/IRQ/hub/RUN/publication drain; physical STOP; fresh jobs from current settings. |
| Fresh motion and final model | Stock axes/scale and source-validator code agree; old captures lack complete physical receipts. | Non-destructive physical completion/overflow/acquisition timing evidence, selected 25 Hz compatibility and measured final-model replay. |
| Steps, sleep and health history | Original motion consumer receives the same samples before/during/after the simulated switch; actual settings remain unchanged except explicit test edits. | Actual algorithms and records across gesture gaps, day boundaries, controlled steps and overnight sleep; report optical gaps honestly, no invented backfill. |
| Viable recovery | Stock descriptor/OTA route and selected boot checks are understood; some failure paths ignore errors. | Exact boot/update/power-loss behavior and a usable recovery route on this hardware; matching SDK symbols alone do not qualify it. |

No gate in this table is fully closed. A test fixture can demonstrate the
required software sequence without supplying its physical evidence.

## Integrated sequence implemented

The newest [retired-layout runner](UNIFIED_RETIRED_SWITCH.md) now brings the
coordinator, conditional layout, known-root retirement, sample-reader hooks and
original Health consumer together. Its precise fixture boundaries and nine-phase
sequence supersede treating those tests as wholly separate evidence. The older
append-only runner described below remains a distinct baseline, not an additional
physical validation or a proof that every root is retired.

The new [C coordinator](UNIFIED_COORDINATOR.md) now implements the orchestration
formerly supplied entirely by the runner: original pause identity, checked
one-shot STOP, separate physical receipt, retirement before HOLD and atomic
current-settings Health commit. It handles partial-entry resume without
inventing cancellation/fence/physical evidence. Its 32 focused ARM cases also
exercise failures and stale identities. The coordinator, Health commit and
service database remain separate **unlinked candidates**, not production hooks.
Its positive source/scheduler receipts remain fixtures; the older exact-motion
consumer sequence below is separate evidence, not physical continuity.

`tests/test_stock_switch.py` runs the actual-address component ELF and exact
stock image in **one persistent ARM address space**. Source-defined C interfaces
and compiled ABI size witnesses drive the runner. It is not multiple isolated
successful tests being counted as a transition.

The complete positive sequence does the following:

1. Initializes Health and the command dispatcher. Creates an original job,
   runs the checked original sample reader and guarded positive-HR stores.
2. Feeds both wire fragments for Gesture through `wd_receive`. No reply can
   claim success while quiescence or fresh-source startup is pending.
3. Uses explicitly simulated cancellation/IRQ/hub/publication receipts, then
   executes `wb_stock_stop_writes` through original stock TX. Successful writes
   alone leave the switch pending. Physical STOP remains a separate fixture.
4. Retires software optical buffers via real `wop_retire` and stock clear.
   The controller has advanced to HOLD's new token, while retirement must name
   **the original Health pause token**. The new test rejects substituting the
   current controller token. The new coordinator retains this identity too.
5. Runs original stock motion drain/Health consumer and supplies the same
   selected frame to `wa_observe`, with invented timing/completion metadata.
   Only then can a Gesture success reply be assembled. Reply fragments and
   packed motion run through actual `wg_stock_notify20` and the original stock
   notification wrapper, including its shared return tail. ROM submission
   status remains a fixture; no radio delivery or buffer-copy lifetime is proved.
6. Feeds a Health command, drains/releases through named fixtures, reads changed
   current stock controls and prepares resume. READY still cannot reply Health
   success. A monotonic settings revision is simulated, **not derived from raw
   settings bits**, which cannot detect change-and-change-back.
7. Commits Health, rejects old source receipts and old optical tickets, creates
   a new ticket and runs a new original sample read. Fresh acquisition setup
   and scheduler rebinding remain fixtures; no real RUN/resume implementation
   is smuggled in by the test helper.

Other cases exercise missing inventory, STOP/reset/release failures, partial
motion transfer, overflow, transport error, optical read failure, changed
settings revision, disconnect, charging and stale source. A separate sequence
feeds the **actual stock motion consumer in eight transition phases**, matching
an unchanged-stock baseline. The step/sleep algorithm boundary is still mocked:
same input delivery is not measured step/sleep continuity.

Notification refusal on either reply fragment returns Gesture toward cleanup;
refusal after committed Health does not undo default Health. A refused motion
send cannot renew the lease. A stale successful-send receipt after reconnect
cannot mutate the new connection. Previously submitted packets are not recalled
by this test: callback/transport draining and dedicated service admission remain
explicit fixtures. The unsafe legacy UART queue is not used.

Separately, [the final Health commit candidate](UNIFIED_HEALTH_COMMIT.md) joins
the current-controls/revision check and existing software commit under one
PRIMASK-preserving critical section. It does not create a revision owner or
fresh scheduler/physical resume receipts. Its focused incomplete ELF is rejected
by the production verifier; adding the helper to all current components exceeds
the unchanged APP bound. It is not hidden inside the fitting subtotal below.

In that older runner, only the two reviewed sample-reader BLs change in emulator memory.
No coordinator is attached to production, and no timer policy, GATT registration,
sensor configuration, stock file or construction gate is changed by these runners.

## Whole-integration budget: current append-only approach is insufficient

The preceding 22-object scattered trial provides conditional placement only
for its historical subset, not all currently implemented code or approved
reclamation. The current 25-object input-only lower bound is 10610/9520 and
refuses three physical bindings. The following append-only numbers describe
the unchanged main checkpoint, not the whole current integration. No remaining
hook costs are absorbed into the historical 264-byte conditional margin.

The current component link is not a whole-image budget. All figures below use
the same unchanged compiler flags, retained unwind data and 32-sample queue.

| Existing category | Text/constants bytes |
|---|---:|
| Mode/runtime/adapter/Health lifecycle | 4114 |
| Motion tap and source validator | 1320 |
| Wire/dispatcher/transport helpers | 2350 |
| Stock-facing timer/STOP/settings/result/read/I/O bindings | 1458 |
| Compiler support and remaining alignment | 162 |
| Total text/constants | 9404 |
| Linked unwind | 96 |
| Occupied append extent | **9500** |
| Configured remaining extent | **20** |

That subtotal excludes four candidates from the main checkpoint, plus the later
discovery unit. The guarded main build attempts its components plus Health commit, service,
coordinator and legacy filter together. Its final-region refusal/map records
**11108 bytes, 1588 over** the unchanged configured limit; no ELF is produced. This supersedes
the earlier arithmetic that counted only commit and service. The remaining
hardware/communication hooks below are still additional unknown costs.

Still required beyond the main checkpoint, all to be budgeted **together**:

- Boot/retention initialization and a proven persistent owner pointer.
- Service registration-capacity change, callbacks, discovery ownership/admission
  (its 122-byte encoder/view now appears in the separate 22-object budget),
  subscription/connection generation and serialized command ownership.
- Complete producer/start/result hooks, ticket propagation and queue fences.
- Fresh-job settings-aware resume and truthful completion/failure handling.
- Motion completion/overflow/time observer, stock data-path hooks and source
  configuration checks without changing Health's sensor behavior.
- Relocation trampolines/literal pools/alignment and final container placement.

Unknown implementation sizes are **unknown**, not zero. As a concrete planning
case, mirroring stock's six-attribute RX/TX service shape needs **168 database
bytes alone** (six reviewed 28-byte entries). Appending just that table would
make 9668 bytes: **148 beyond** the configured margin, before its UUID storage,
callbacks or the other missing integration code. This is an exact arithmetic
failure for that append-only design, not a measured final service implementation.
The five existing service slots are already used; changing capacity also needs
stack-memory evidence. See [the stock transport audit](UNIFIED_STOCK_TRANSPORT.md).

The subsequent [compiled service candidate](UNIFIED_SERVICE_TABLE.md) replaces
that lower-bound planning case with **240 measured read-only bytes**: eight rows
plus the external primary UUID. It chooses a separate read-only slot to discover
boot identity before the existing boot-bound first request; adding read semantics
to RX could instead save 56 bytes and remains an unimplemented alternative. The table remains
unlinked in the main checkpoint; the newer discovery format exists, but its
callbacks, storage/identity owners and sixth-slot admission are not supplied.
At the preceding checkpoint, components + Health commit + that table totaled
**9904 bytes**, **384 over the configured margin**. That historical subtotal
omitted the now-implemented coordinator and is not the current whole-code budget.

Small factoring experiments were discarded rather than accepted as a whole-fit
solution: a shared Health receipt predicate saved 12 linked bytes; shared
controller transitions saved 8 object-text bytes; runtime/adapter sharing added
unwind entries with negligible/no text savings. All exploratory source edits
were restored to the pinned checkpoint. Test-only code is already excluded from
the actual-address component ELF; there is no hidden test harness to remove.
Even the impossible upper bound of deleting every nested initializer, fence
initializer and three small potentially redundant exports saves only 306 bytes,
less than even the preceding 384-byte known deficit. Most currently callerless
exports are still-required production hooks, not dead code.

### RAM and stack cannot be reduced to the old 796-byte subtotal

- Dispatcher plus one output frame plus timer fence: **796 bytes** of persistent
  candidate state, still unallocated. Profile/Health/tap are already inside it;
  do not count those again.
- Current full source-receipt C object: **288 bytes**, recorded by the build's
  actual ARM size witness (previously 480). It retains all 32 raw frames and
  both exact acquisition endpoints as checked ages relative to status time.
- Observation's output scratch is now 64 bytes, previously 208, **inside** its
  measured nested stack, not another independent persistent allocation. The
  unchanged <250 ms validity window spans at most eight 40 ms buckets; this
  reduces temporary scratch, not the 32-frame input or persistent queue.
- Integrated successful `wa_observe` reaches **244 observed nested stack bytes**,
  down from 388 at the source-storage checkpoint. This still excludes
  the caller's receipt, outer stock caller, interrupts and unexecuted paths.

If the receipt gets a separate persistent scratch allocation, 796 + 288 =
**1084 bytes**, still 60 beyond the unapproved 1024-byte aligned-gap idea,
with another measured 244 stack bytes elsewhere. If the receipt is on the task
stack instead, 288 + 244 = **532 bytes** before outer caller/interrupt overhead;
that cannot be approved just because one known task was created with 1024 bytes.
Other stock task stacks are 3584/2560 bytes, but their free headroom is unproved.
Neither arithmetic choice establishes ownership. The latest change removes
another 144 bytes from this planning case, not from proven ring RAM use.
Those are motion-only planning subtotals. Including coordinator owner (28),
original STOP receipt (28), resume receipt (20, already containing preparation)
and revision word (4) makes that all-persistent candidate **1164 bytes**.
The later immutable discovery value adds 20, giving **1184 planned bytes**,
still unallocated and not a whole-image RAM budget.
Claude's unapproved overlay-plus-gap prototype packs these objects with 60 bytes
remaining; its boot/retention/other-writer lifetime is not established. Local
coordinator stack reports do not establish full nested/interrupt headroom.
Scratch lifetime/reuse must
be proved against concurrency; the input receipt and output scratch cannot alias.
The representation and prior-ARM equivalence evidence are recorded in
[the source-storage handoff](UNIFIED_RESOURCE_BUDGET.md).

### Reclamation decision

Approved reclaimed stock space: **zero**. The indicator experiment identifies
764 potentially reusable body bytes but does not close indirect/retained
references or boot/retention behavior. Raw/debug code shares live literals,
epilogues and startup/OTA dependencies. The final 200 bytes are boot overlay.
None may silently become a linker hole. See
[indicator retirement](UNIFIED_INDICATOR_RETIREMENT.md) and
[memory ownership](UNIFIED_MEMORY_AUDIT.md).

The separate [scattered-link experiment](UNIFIED_RELOCATION_TRIAL.md) now executes
four whole objects at hypothetical indicator-body addresses: 408 bytes outside
the append region, preserving entry stubs/shared tails/literal pools. At the
previous checkpoint, baseline plus Health commit used 9176 append bytes (344
remained), with all 118 baseline function names retained. The current predicate
is also retained in the new diagnostic; neither includes the coordinator.
The 240-byte service-inclusive attempt is an archived
**failed link**, not an approved fit: the linker's initial unwind estimate crosses
the bound even though its later merged map appears below it. No region or
capacity is expanded. The main component linker separately removes only the
premature pre-coalescing assertion, with exact final-region/ELF checks strengthened
and boundary-tested; this older diagnostic retains its strict script. The
global stock unwind behavior is also unproved.

Claude's separate [RAM candidate audit](UNIFIED_RAM_OWNERSHIP.md) identifies a
conditional 1224-byte post-boot overlay plus gap layout. Its newer vendor-guide
evidence supports the documented APP-versus-heap boundary, not exact-ring
lifetime. It is not owned storage: ROM/DLPS re-entry, heap/patch writers,
retention, indexed accesses and the final owner/serialization remain unresolved.
No `NOLOAD` section or production verifier exception has been added.

The next implementation batch must choose and measure a complete architecture:
prove a sufficient reclaimable region, reduce/reshape the integrated code and
scratch representation with behavior-preserving tests, or establish other
owned storage. The source-storage reduction is implemented, but complete fit
is still unresolved. Repeatedly fitting one helper into a component margin does not
resolve this gate. No queue/validation/unwind removal is approved as a shortcut.

## Source/reference search

The source search on 2026-09-24 found no exact vendor application SDK/symbols
or daily-ring hard-recovery procedure. It did find useful additional code:

- [lachlanmcalpine/colmi-ring builder](https://github.com/lachlanmcalpine/colmi-ring/blob/4a0aa9debd6a8117203f5e3ed393a1d994f78e29/firmware/build.py)
  was read, not executed. Its 137540-byte base exactly matches our upstream
  low-latency file, SHA-256
  `2ea1bb08826891604fb714a3820c859d77f52f8d22f1d9a870db10cd5fbffe34`.
  Builder source SHA-256 is
  `3e4062ad08478525cac2399ec931a3641640cf00ea884b3b2be784663e6e3409`.
  It alters sensor configuration, repurposes raw callback bodies and reshapes
  the UART queue. Its polling loop checks a data bit but not the I/O return.
  Those choices are reference ideas, not verified Health-preserving donors.
  No source or binary from it was installed or run.
- Its [firmware notes](https://github.com/lachlanmcalpine/colmi-ring/blob/4a0aa9debd6a8117203f5e3ed393a1d994f78e29/firmware/README.md)
  describe experimental motion results and advise against experimental flashes
  on the only ring. Reported timing/recovery claims are not measurements of
  this ring. In particular its rate label for the identical base differs from
  our measurement; binary identity does not make external rate labels authoritative.
- [aimindseye's research](https://github.com/aimindseye/colmi-r02-firmware)
  targets RY02_V3.0, not RT02CR_V3.1, and explicitly lacks validated SWD
  recovery. It is not an exact source or recovery substitute.
- [Nosh118](https://github.com/Nosh118/colmi-ring-tools) remains an exact binary/
  patch/protocol reference, not a complete ring SDK. The SDK-origin e-paper
  source mirror has already exposed a different live timer-create hook;
  [the boot-reference audit](UNIFIED_BOOT_REFERENCE.md) records that limitation.

The follow-up [vendor/recovery search](UNIFIED_VENDOR_RECOVERY_LEADS.md) found
official family ROM-bypass documentation and an RTL8762ESF ring-SDK supplier
lead, not RT02CR-specific source or proven recovery. The current official SDK
download requires authentication. No vendor contact or hardware access occurred.

## Validation cadence

Focused tests during edits; the coordinator full/reproducible checkpoint passed
**3143 tests in 454.34 seconds**, zero skips or failures; all **365
source/artifact/report hashes** were independently checked. Both main ELFs change
reproducibly; all prior integrated-switch cases remain included. Coordinator,
Health commit and service candidates are explicitly excluded from both main
ELFs; their combined fixed-bound link has a recorded real-capacity refusal.
Exact hashes belong in
[the resource handoff](UNIFIED_RESOURCE_BUDGET.md), not in every gate cell.
No live test until its precise purpose can close a named gate and its
prerequisites/authorization are satisfied. No flash approval follows from this
off-ring runner or from the number of passing tests.
