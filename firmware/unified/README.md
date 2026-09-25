# Unified firmware: offline runtime, NOT an installable image

Current decisions and measurements live in the
[finite readiness checklist](../../docs/UNIFIED_READINESS.md) and
[resource handoff](../../docs/UNIFIED_RESOURCE_BUDGET.md); they supersede the
historical checkpoint counts and sizes below. The integrated runner includes
the original stock notification wrapper, but ROM transport and physical
pause/resume/source evidence remain explicit fixtures. Health is boot/default;
the installed ring is still V2 optical-off, not unified.

Latest [integrated retirement](../../docs/UNIFIED_RETIRED_SWITCH.md) runs the
C coordinator and original stock Health sample path together in one persistent
21-object ARM context, with known legacy roots suppressed through nine phases.
The separate [discovery candidate](../../docs/UNIFIED_DISCOVERY.md) adds a pure
C/Swift identity format, no callback/owner/admission. Its full **22-object,
132-function** conditional link uses **9256 append bytes / 264 remaining**, plus
unchanged **1894 unowned moved bytes**. Archive:
`research-20260924-discovery-budget-v1/`. **63 supplemental tests pass** with
253 content hashes independently checked; full simulator app build passes.
Switch and discovery tests use distinct pinned layouts. The new ELF has no
retirement stubs and production rejects it. **Never install it.** All gates stay
closed; 20 identity-storage bytes are additional unallocated state, not a RAM owner.

The preceding [whole-code research trial](../../docs/UNIFIED_RAW_RELOCATION_TRIAL.md)
links its 21 objects/130 functions using **1894 bytes of unowned**
legacy regions plus 9132 append bytes (388 configured bytes remain). The
standalone ELF has no entry stubs; a separate exact-ELF-pinned
[16-edit plan](../../docs/UNIFIED_STOCK_RETIREMENT.md) tests known-root retirement
and selected Health paths together only in emulator memory. Missing hooks are
additional; production rejects the ELF. **Never install this layout.** Current
archive: `research-20260924-raw-retirement-v1/`; its 55 guarded supplemental tests
pass, with 277 content hashes checked. Neither main ELF changes. No RAM/stock
space is approved. The full **3251-test** raw-ingress checkpoint is separate.

`stock_health_commit.{c,h}` is an **unlinked candidate**, not a member of either
main ELF. The guarded build archives its reproducible object/stack report and
runs its separate focused tests; the full component addition fails the fixed
APP bound. See [the commit contract](../../docs/UNIFIED_HEALTH_COMMIT.md).
An object archive or focused subset link must not be described as complete
firmware fit. No stock hook, RAM owner or OTA container is enabled.

`stock_coordinator.{c,h}` is also an **unlinked candidate**. It joins checked
one-shot STOP, original-identity optical retirement and atomic current-settings
resume, with physical/producer/scheduler boundaries still explicit fixtures.
The guarded raw-ingress checkpoint passes 3251 tests with all 371 recorded
hashes checked. The main builder attempts its four candidates plus all main
components together: **11108 bytes, 1588 over** the unchanged configured APP
limit, with no full-candidate ELF. The component-only main ELF uses 9500 bytes.
See [coordinator contract](../../docs/UNIFIED_COORDINATOR.md).

`stock_legacy_gate.{c,h}` is the fourth **unlinked candidate**, 64 text bytes.
Its exact-stock callback tests reject A1/BF/CE/CD before the stateful prelude and
preserve separate DFU routing. There is no A1 fallback. Unified app identity/discovery
must replace CD01 fingerprinting before attachment, or it would break existing
app identity and return-to-stock preflight. See
[filter contract](../../docs/UNIFIED_LEGACY_GATE.md). The measured V2 heap has
only 264 free bytes (104 minimum), not room for the 1164-byte selected state.
No gap ownership follows from its unchanged one-minute observation.

`stock_service.{c,h}` is likewise an **unlinked development candidate**: 240
read-only bytes for primary/RX/TX+CCCD/discovery attributes and UUIDs, no callbacks
or service admission. The guarded output also retains explicitly **unowned,
production-rejected relocation diagnostics**. Only their baseline emits an ELF;
adding the service preserves a reproducible APP-bound refusal, with no ELF.
Neither diagnostic changes the main component link or approves stock/RAM space.
See [service layout](../../docs/UNIFIED_SERVICE_TABLE.md) and
[relocation outcome](../../docs/UNIFIED_RELOCATION_TRIAL.md).

`mode_controller.c` is portable C11 for a single serialized firmware task. It
does not contain stock addresses, a linker script, a wire-command allocation,
or a hardware adapter. Native tests and a Cortex-M0+ object build are not proof
of ring safety. **Do not inject this object into an apparent code cave.**

See `docs/UNIFIED_FIRMWARE.md` for implementation status and remaining gates.
The current [stock-address continuation](../../docs/UNIFIED_STOCK_INTEGRATION.md)
and [checked-health cancellation](../../docs/UNIFIED_HEALTH_CANCELLATION.md), with
[lossless queue compaction](../../docs/UNIFIED_RESOURCE_BUDGET.md),
pass **1790 guarded tests, zero skips**, all **196 hashes checked**, in
`build-20260923-queue-compact-v1/`. It includes an actual-address component ELF
at `0x847ad0`, shared compiler primitives, profile RAM deduplication and a tested
but unattached ROM timer-barrier and checked twelve-slot STOP binding. Components
occupy 9224 bytes, leaving 296 configured bytes. Dispatcher/frame/fence totals
796 bytes, not approved RAM. Caller serialization and full health bindings remain
required; checked STOP acceptance is not physical shutdown or safe resume.
A barrier can complete despite a prior STOP failure, leaving that timer active.
Activity/wear timer duties also prevent treating the reviewed table as an
approved blanket pause policy. No compiler-size optimization was adopted.
There is no stock-hooked OTA image, RAM allocation or physical health/source proof.
The later consolidated ROM diagnostic aborted without retry; its partial bytes
do not qualify new windows. A separately coordinated passive check then completed
60 seconds with zero notifications/zero UART commands and verified disconnect;
the earlier interruption remains unexplained. A later explicitly requested,
newly coordinated retry completed 974 CD01 transactions and captured all 6076
ROM bytes twice with matching results, passing postchecks and verified disconnect.
This supplies code for offline review; it does not close physical gates. The
subsequent off-ring continuation executes captured ROM with the compiled fence
and fixes the ROM null-queue assertion hazard. Kernel/scheduling remain mocked,
and invalid timer handles require ownership checks before cancellation. No
ring connection or firmware change occurred during that implementation. Earlier
build counts below are historical.
The latest coordinated workflow is recorded in
[`docs/UNIFIED_WORKFLOW_3.md`](../../docs/UNIFIED_WORKFLOW_3.md).
The latest [ROM diagnostic](../../docs/UNIFIED_ROM_DIAGNOSTIC.md) completed a
separately coordinated fixed reads with 114/142/144 matching transactions and
verified disconnect, no sensor command or flash. Its guarded offline build passes
1276 tests, zero skips, with all 132 hashes checked in
`build-20260923-rom-internals-v1/`; it is an artificial-address test build, not OTA.
Captured hook slots were zero twice, selecting captured defaults in that idle
snapshot. Their timer-command API and callback-drain behavior remain unproved.
The preceding
[codec continuation](../../docs/UNIFIED_WIRE_CODEC.md) passed 58 iOS simulator
tests; no Swift changed or simulator was rerun in subsequent continuations.
The source selector now uses caller-owned scratch to reduce its ARM local stack
frame from 344 to 184 bytes, with late-rejection clearing tests. No RAM allocation
or complete task-stack budget is thereby approved. Only the daily-use ring is
available; the user permits considering a specifically reviewed test if risk is
reduced. A spare is preferred, not required categorically. Technical gates remain
unchanged; this diagnostic session does not authorize a flash or further reads.

`sample_tap.c` now implements a separate 32-sample Gesture queue. It copies
verified acquisitions without receiving stock pointers or mutating Health's
cursor. Lost/replayed batches, I2C failure, queue overflow and sequence exhaustion
invalidate the session; stale-session callbacks cannot affect its successor.
Its compact storage saves 192 bytes by deriving the oldest sequence from FIFO
counters instead of storing a redundant sequence/padding with every entry.
Capacity, public output, freshness and failure semantics remain unchanged;
native and actual-ARM comparisons include the archived pre-change binary.
It is NOT a 25 Hz resampler, a physical sensor hook, or a safe RAM allocation.
The adapter must request mode cleanup on a current-session tap fault and fence
in-flight notifications. Stopping this queue alone cannot stop hardware work.

`runtime.c` connects the controller and tap: one pending send, source and queued
sample age checks, cleanup on sampling/transport failure, and lease renewal only
for sequences actually accepted by a reviewed transport. An old backlog cannot
keep Gesture alive. `wr_offer` requires the oldest physical acquisition time,
not callback arrival time; source and queued age must remain under 250 ms.
This is a software requirement, not measured stock FIFO timing. Only one
serialized task may call this API. The legacy stock TX queue cannot establish
the required successful-send/backpressure contract.

Actual pinned-stock Thumb execution now verifies selected FIFO/consumer paths:
[stock motion proof](../../docs/UNIFIED_STOCK_MOTION.md). This is not execution of
a linked unified candidate, and the step/sleep algorithm boundary is mocked.

## Offline evidence components (not installed stock bindings)

`stock_transport.c` contains two unattached exact-stock calls: service registration
with the actual by-value callback ABI and fixed 20-byte notification submission.
It preserves stack result bytes and does not use the unsafe legacy UART queue.
No service/table/UUID is installed, no stack capacity is expanded, and buffer/
callback lifetime, credits, serialization and disconnect fencing remain unproved.
Never call these stock addresses on V2/25 Hz. See the stock transport proof.

`dispatch.c` joins validated wire requests to the guarded adapter, owns one
exchange, waits for committed transitions, and permits one reply fragment in
flight. It rejects replay/old ownership and continues cleanup deadlines while
closed. It does not install a service, create boot identity or supply physical
receipts. Real enqueue/disconnect fencing remains a binding obligation. See the
dispatcher integration for tested failure paths and explicit limits.

`wire.c` and the matching Swift `UnifiedWire.swift` define bounded 20-byte control
and motion frames for a distinct future GATT service. Control reassembly is bound
to request, operation, boot and connection identities; malformed, stale or
reordered fragments poison the exchange. This is not a legacy UART opcode,
dispatcher, service registration, queue or hardware-completion proof. Do not send
these frames to the installed ring. See the codec continuation for the exact
format, ARM/Swift parity tests and remaining binding obligations.

`health_adapter.c` tracks cancellation, in-flight RUN work, physical STOP
receipts, publication tickets and current-settings resume. Its receipts are
obligations for a future stock binding, not proof that a queued operation ran.
An incomplete producer inventory cannot enable the unified capability.

`fresh_source.c` validates copied FIFO transaction evidence and selects one
original sample per 40 ms acquisition-time bucket. It neither changes nor
drains Health's sensor source. There is no qualified physical profile in this
repository. The existing stock path does not preserve all the required timing,
overflow and byte-completion evidence; a 25 Hz notification cadence alone
cannot satisfy this contract. Selection may have within-bucket timing jitter;
model compatibility still needs a measured replay, not just this selector.

See [fresh-source audit](../../docs/UNIFIED_FRESH_SOURCE.md) and
[capacity diagnostic review](../../docs/UNIFIED_CAPACITY_GATE.md). A passing
component test does not close its hardware gate.

`adapter.c` joins these components to `runtime.c`. It refuses Gesture before
quiescence when capability evidence is unavailable, completes START only on a
validated acquisition, requires typed physical receipts for motion ownership
and cleanup, and commits Health only after current-settings revalidation. A
genuine Health-component failure reports Fault; an unproven inventory at boot
instead leaves ordinary Health untouched. Physical Health job hooks must call
`wa_tick` after outcomes, and every operation needs the same proven serialization
domain. These are not installed stock hooks. See the
[Health adapter audit](../../docs/UNIFIED_HEALTH_ADAPTER.md).

`stock_binding.c` is an **unattached, exact-stock-only** heap-free RESET/STOP
write shim. Unlike the portable controller, it contains reviewed stock/ROM
addresses. It preserves bus failures and mutex-release status but does not
fence callbacks, establish physical emitter shutdown or produce a successful
Health STOP receipt. It is included only in the offline objects/test ELF, not
an installed hook. See [stock binding evidence](../../docs/UNIFIED_STOCK_BINDING.md).

## Required physical adapter contract (stock binding not implemented)

Each action has a unique token. Call `wm_complete` only after verifying its
physical postcondition, not after merely queuing work. A failed/nonblocking RTOS
enqueue must complete with `success=false`. Async callbacks must retain their
original token; never stamp an old callback with the controller's current token.
The adapter must also fence the underlying hardware work: discarding an old
callback does not undo a late optical RUN or timer restart.

| Action | Required postcondition |
|---|---|
| QUIESCE_OPTICS | All measurement/indicator starts fenced; active optical owners and timeout/result-publication callbacks cancelled/drained through stock lifecycle; actual RUN state stopped. Saved health settings unmodified. |
| HOLD_ACCEL | Normal accel wake/ownership acquired; sleep/idle veto established without replacing another owner's state. |
| START_25HZ | One producer active, delivering fresh FIFO samples at verified 25 Hz. Not repeated cached register values. |
| STOP_STREAM | Producer stopped/deleted; prior entry generation cannot run later; raw flags and callbacks cleared; no further stream notifications. Must work after partial entry. |
| RELEASE_ACCEL | Only this session's hold/idle veto released; normal health ownership preserved. Idempotent if never acquired. |
| RESUME_HEALTH | Health scheduler restored from current settings, not a saved/stale ownership mask. Health algorithms/storage unchanged. Scheduler can request genuine measurements after Health is committed. |

Call `wm_init` after successful stock Health initialization. State is volatile;
do not persist Gesture mode or write NVM per transition. Call `wm_tick` from a
reviewed timer/task context frequently enough for lease/transition deadlines;
the native policy does not supply a timer. Time is monotonic uint32 milliseconds
with serial wrap semantics (no gaps of half the counter range).

Entry/cleanup action deadlines are 3 seconds each. Gesture lease is 30 seconds,
renewed with the current session and a strictly advancing processed sample
sequence. The phone attempts renewal every 5 seconds while processing is fresh.
Disconnect/charging cancels entry or exits Gesture. A failed/timed-out cleanup
enters Fault with the optical gate closed; **this does not prove a stuck physical
sensor stopped**. Only an explicit Health request retries cleanup from Fault.

All optical RUN paths must call `wm_optical_start_allowed` with a reviewed
purpose. Genuine health acquisition is permitted only in Health; decorative
charging/status/find-ring animation and raw optical debug flashing are denied
in every mode. Do not reclassify a measurement as decorative to make it dark.
Do not reduce measurement current/duration without separate accuracy evidence.

## Local checks

```sh
.venv/bin/pytest -q tests/test_fwunified.py
.venv/bin/python -m probe.unified
clang --target=armv6m-none-eabi -mcpu=cortex-m0plus -mthumb \
  -ffreestanding -fno-builtin -Oz -Wall -Wextra -Werror \
  -c firmware/unified/mode_controller.c -o /tmp/whip-mode-controller.o
```

The audit is read-only. `whip.fwunified.build` refuses construction even when
the pinned stock container passes. No command-line override or speculative
flash target is provided. Do not bypass it using the generic byte patcher.

To produce reproducible **non-installable ARM objects and an artificial-address
test ELF**, install `requirements-firmware-proof.txt` in an isolated environment
and supply the official Zig 0.15.2 toolchain and a Swift compiler, then:

```sh
python -m probe.unified_build --zig /path/to/zig \
  --output /tmp/whip-unified-offline-new-directory
```

The output must be a new directory. The command compiles and links twice, checks
byte identity, reports ELF sections/unresolved symbols/per-function stack usage,
and executes the linked Cortex-M0 runtime at synthetic address `0x01000000`.
Its explicit suites also cover stock motion, memory overlays, health/optical
lifecycle, command routing, native sanitizer stress and proof-integrity guards.
They also replay the archived descriptor session, check OEM OTA bounds and
failure paths, execute stock FIFO/I2C and optical bus code, and compile the
checked-in Swift decoder for host-only representation/scale comparison. This
does not validate physical sampling cadence or classifier accuracy on a new source.
It snapshots inputs/artifacts and requires identical collected/executed test
identities; deselection, skip, xfail or failed phases invalidate the proof.
This is not a filesystem lock or hermetic compiler/ROM/hardware proof.
It never emits `.bin`, touches BLE, changes a flash allowlist
or clears `whip.fwunified.build`'s gate. On this Mac the emulator's JIT required
execution outside the sandbox; ordinary C compilation did not.
