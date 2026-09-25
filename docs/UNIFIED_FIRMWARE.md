# Health-default unified firmware — offline implementation

Status: 2026-09-23. **Partial implementation; not flash-ready, not deployed.**
The installed ring remains V2 optical-off, not unified; optical health is globally
disabled on that installed image. Workflow 3's bounded descriptor read matched
sampled V2 code, not the entire live image. See
[the completed workflow](UNIFIED_WORKFLOW_3.md) for scope and hardware evidence.

**Current handoff:** [UNIFIED_RESOURCE_BUDGET.md](UNIFIED_RESOURCE_BUDGET.md)
and [timer creation/resume evidence](UNIFIED_TIMER_RESUME_READ.md) supersede the
historical counts and unread-code claims below. The fixed 452-byte timer-code
read completed and disconnected; its code is now exercised off-ring with
explicit missing-helper/configuration substitutes. Native zero-period creation
mutates allocation state before asserting. No complete health binding, memory/
recovery approval, physical continuity evidence or final OTA image exists.

**Earlier actual-address implementation:** [UNIFIED_STOCK_INTEGRATION.md](UNIFIED_STOCK_INTEGRATION.md)
adds an actual-address component link, shared compiler primitives, a 60-byte RAM
reduction and an unattached timer-daemon barrier with cancellation-race tests.
**1495 guarded tests pass, zero skips; all 179 hashes match** in
`firmware/unified/build-20260923-stock-address-v1/`. The components occupy
8868 configured flash bytes, leaving 652; state/frame/fence needs 988 nominal
RAM bytes, whose ownership remains unproved. No installable stock-hooked image
exists. The preceding boot comparison matched 528 code bytes; a later consolidated
ROM read aborted on unrelated traffic without retry, so its new windows remain
unqualified. A separately coordinated passive check then completed 60 seconds
with zero notifications/zero UART commands and verified disconnect; the original
interruption's cause remains unknown. The user subsequently requested one retry,
with fresh readiness: all 6076 ROM bytes matched across both reads, 974 CD01
transactions completed and disconnect was verified. Code is now captured for
offline review, not proof of full RTOS/hardware integration or recovery.
No flash, sensor command, app deployment or production unlock occurred.

**Earlier diagnostic continuation:** [UNIFIED_ROM_DIAGNOSTIC.md](UNIFIED_ROM_DIAGNOSTIC.md)
records fixed ROM-code and hook-state reads: 114, 142 and 144 matching
transactions with verified disconnect, no sensor command or flash. Captured
hook slots were zero twice, selecting defaults in that idle snapshot. Defaults
delegate to the unread timer-command API; callback drain remains unproved.
**1276 guarded tests pass, zero skips; all 132 hashes match**
in `firmware/unified/build-20260923-rom-internals-v1/`, not OTA. No C component or
Swift changed, no simulator was rerun, and no production gate was opened.
Only a specifically reviewed daily-ring test may be considered; a spare is
preferred, not an absolute requirement. This session does not authorize a flash.

**Previous memory continuation:** [UNIFIED_RESOURCE_BUDGET.md](UNIFIED_RESOURCE_BUDGET.md)
records the daily-ring-only constraint and reduces one ARM local stack frame
from 344 to 184 bytes while preserving all-or-nothing sample validation.
**986 guarded tests pass, zero skips; all 120 hashes match.** Output:
`firmware/unified/build-20260923-memory-v1/`, not OTA. The 1016-byte dispatcher
nearly consumes the entire 1024-byte nominal aligned RAM gap, whose ownership
remains unproved; current component `.text` is 8252 bytes before real linking.
No ring/phone access, simulator run, new allocation or production unlock occurred.

**Previous transport continuation:** [UNIFIED_STOCK_TRANSPORT.md](UNIFIED_STOCK_TRANSPORT.md)
adds a tested, unattached exact-stock registration/send shim and actual-code queue
failure witnesses. **936 guarded tests pass, zero skips; all 120 hashes match**.
Output is `firmware/unified/build-20260923-transport-v1/`, not OTA. There is no
registered unified service or approved extra service/RAM capacity. Callback
layout, queue ownership, stack lifetime and disconnect fences cannot be assumed.
No ring or phone was accessed, and no Swift or simulator changed in this run.

**Previous dispatcher continuation:** [UNIFIED_DISPATCH.md](UNIFIED_DISPATCH.md)
joins the [C/Swift codec](UNIFIED_WIRE_CODEC.md) to the guarded mode adapter.
Command success waits for committed transitions; replay, timeout and send failure
close the control owner and initiate cleanup. **874 guarded tests pass, zero
skips**, including 20,000 native sanitizer-stressed connections; all 114 recorded
hashes match. Output: `firmware/unified/build-20260923-dispatch-v1/`, not OTA.
No service or live transport is attached, and no hardware was accessed. The prior
58-test simulator run remains the latest; no Swift changed or simulator was rerun
in this continuation. Physical source, health continuity, placement and recovery
gates remain open. Earlier results below are historical, not extra current runs.

**First parallel workflow:** [UNIFIED_WORKFLOW.md](UNIFIED_WORKFLOW.md) records
the integrated runtime, actual linked ARM execution at artificial test addresses,
stock memory/optical/command audits and guarded reproducible builds: **234 passed,
none skipped**, plus **206** existing firmware/protocol regressions. This
supersedes the older 95-test component result below. No stock-linked adapter,
approved code/RAM placement or installable unified image exists yet.

**Extended safety run:** [UNIFIED_SAFETY_TESTS.md](UNIFIED_SAFETY_TESTS.md)
supersedes the initial test counts below. The direction-tie and premature Health
publication failures have now been fixed offline: **53/53 simulator tests pass**;
Python **631 passed / 1 existing unrelated script-cut failure**. All 7,627 Core ML
parity windows still pass; no model or firmware change. The corrected app has
not been installed on the physical phone. Native sanitizer stress previously
passed; the unified image remains blocked by the missing stock adapter/layout.

**Stock continuity implementation follow-up:** a copy-only Gesture sample queue
and reproducible Cortex-M0+ object build now exist. Selected **actual stock Thumb
instructions** have been executed with explicit I2C/ROM/algorithm-boundary mocks;
the combined offline suite passes **95 tests, none skipped**. Stock data sharing
works in the tested serialized paths, but wake/backlog loss, cached raw output,
buffer wrap and ignored I2C failure are real hazards. See
[UNIFIED_STOCK_MOTION.md](UNIFIED_STOCK_MOTION.md) for exact anchors, tests and
limits. This does not clear the linked-image or health-acquisition gates.

Physical-phone follow-up (before the fixes): the test build was installed/run on an
iPhone 14 (iOS 26.6.1): 48 passed / the same 2 failures. Existing health rows
were backed up and verified preserved. The user confirmed connection/synced
history; a read-only app snapshot records the 25 Hz version string, but no
new health rows or advanced sync timestamp. Connection is supported; a fresh
history import, exact image fingerprint and current health acquisition remain
unverified. The user clarified that health sync is paused. No unified firmware
exists or was flashed. See the follow-up section in the safety record for scope
and evidence.

## Product contract

Health is the boot/default mode. Gestures are explicitly requested, temporary
sessions. Disconnect, charging, or loss of fresh phone processing returns the
ring to Health, not to an indefinitely dark raw mode. Normal transitions will
not reflash or reboot. Real health measurements may illuminate the optics;
decorative/status/charging/find-ring animations and raw-mode optical flashing
are to be suppressed. Strict darkness applies to Gesture sessions. Do not
promise uninterrupted HR, steps or sleep during those sessions.

A matching spare/recoverable test device is preferred. The user now permits
considering their daily RT02CR_V3.1 for a specifically reviewed lower-risk test;
diagnostics are authorized first, not an automatic flash. Health remains the
first post-flash check. Automatic rollback and zero-brick safety are not proved.
DFU CHECK confirms credited receipt, not a healthy boot; the stock OTA archive
is not full factory recovery. A spare alone would not prove recovery either.
The first [fixed ROM diagnostic](UNIFIED_ROM_DIAGNOSTIC.md) has now completed;
its optional-hook finding does not close cancellation or recovery gates.

## Implemented

- `firmware/unified/mode_controller.{c,h}`: allocation-free C11 policy with
  Health/Entering/Gesture/Returning/Fault, explicit ordered asynchronous actions,
  unique callback tokens, 3-second action deadlines, 30-second Gesture lease,
  advancing-sequence renewal, charging/disconnect exit, and bounded cleanup.
  Repeated Gesture requests do not extend the lease. Cleanup failure cannot
  report Health. Optical-purpose policy allows real measurements in Health,
  never decorative or raw-debug flashing. No hardware/RTOS adapter exists yet.
- `firmware/unified/sample_tap.{c,h}`: independent bounded Gesture copy queue,
  strict fresh-acquisition/session checks and fail-closed overflow handling;
  cannot write the stock Health cursor. Not yet installed on any stock hook.
- `firmware/unified/runtime.{c,h}`: integrated mode/tap/transport policy, source
  and queued-sample acquisition-age checks, one pending send, and replay-safe
  lease renewal. A stale backlog cannot keep Gesture active. Actual ARM execution
  validates the compiled integration in an artificial test layout, not in stock.
- `whip/fwcontinuity.py`: fingerprint-locked execution of selected stock Thumb
  data-path routines with explicit mocks, negative witnesses and a C observer.
  `probe.unified_build` builds repeatable non-installable ARM objects plus a
  proof manifest; skipped tests cannot qualify that build as passing.
- `whip/fwunified.py`, `probe/unified.py`: exact stock identity/container audit
  and unconditional construction refusal with concrete blockers. No unified
  OTA binary or new selectable DFU target is produced.
- iOS `UnifiedMode.swift`: capabilities/status/request-ID/session/boot-ID semantic
  contract and coordinator. New connections do not adopt a prior Gesture session.
  A 5-second heartbeat requires recent successfully processed advancing samples,
  not merely a BLE connection. Mismatched replies invalidate control. There is
  deliberately **no BLE wire encoding or production transport attachment** yet:
  unknown A1 subcommands can clear raw state on legacy images.
- iOS `RingOperationGate`: one logical owner across health sync, settings, live
  HR, future mode control and existing firmware maintenance. UART requests
  recheck exclusivity after their spacing await. Notifications must be enabled
  before readiness; stale DIS identity is cleared on disconnect. A UART timeout
  blocks further UART requests until reconnect because legacy replies lack IDs.
- Health import now depends on a read-only reader interface. Full sync only
  increases history depth; it never resets the clock or changes HR settings.
  Existing settings are read separately and displayed without forcing HR on
  or changing its interval. Settings writes remain explicit user actions.
- Per-metric persisted import cursors, two-day overlap, seven-day fetch cap,
  retry depth retained for incomplete metrics, and independent-day failure
  handling. No-data is not converted to fabricated measurements. The seven-day
  cap is not proof that older data are complete or recoverable.
- HR/steps require complete indexed responses; duplicates are idempotent,
  conflicting duplicates fail. A terminal index alone is insufficient. Sleep
  rejects truncation, unknown stages, duplicate nights and inconsistent lengths
  before persistence. Sleep's relative days are anchored at request time; a UTC
  midnight crossing rejects that response for retry. No speculative CRC scheme
  was added to the legacy big-data protocol.
- Store updates preserve stable keys and use rollback on failure. Sleep stages
  are not replaced from incomplete responses. Coverage uncertainty persists
  independently of import cursors and survives reconnect/relaunch until Health
  is observed. Dashboard warning and `health_coverage.csv` expose these intervals;
  missing top-level sleep/step values display a dash, not zero. Metric algorithms
  are not repaired/interpolated to hide gaps.
- Pinned float32 Core ML export, Swift preprocessing and burst/sustained decoding,
  calibration, bounded off-main worker, stale/gap/duplicate/frozen/overflow
  rejection, generation-invalidated callbacks, and teardown that drops pending
  events. No retraining, quantization or changes to the deployed Python model.
- App Gesture tab/session control is present but locked without approved unified
  capabilities. Detection/event display and heartbeat integration are prepared;
  a reviewed transport must supply actual ring session/sequence values. Legacy
  A1 packets must not be given invented sequences. Firmware replacement remains
  a separately labeled maintenance operation. Placeholder system actions remain
  disabled. iPhone is the intended primary inference host, desktop deferred.

## Exact identities and numerical evidence

Vendor stock: `firmware/rt02cr-stock-3.12.02.bin`, 138016 bytes,
SHA-256 `b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0`.
Its `not_ready` flag and stale payload SHA are expected vendor-container fields,
not an excuse to refresh/flash it during a read-only audit. V2/base offsets
cannot be transplanted into this stock image.

Stock startup has now been inspected directly: entry file `0x450` loads Thumb
pointer `0x826665` (file `0x6b4`), whose call at `0x758` reaches `0x4a0`.
Under runtime = file + `0x825fb0`, the heuristic disassembly's 916 ROM BL sites
reach 79 distinct ROM targets, all matching the archived ROM symbol table.
Startup `0x4a0` loads its literal pool at `0x768` and calls ROM memcpy twice,
then `__rt_memclr`. These copy/clear boundaries are recorded in the audit:

| Stock startup region | File range (end exclusive) | RAM range (end exclusive) |
|---|---|---|
| First copy / RAM code | `0x20cc8–0x21578` | `0x207c00–0x2084b0` |
| Initialized data | `0x21578–0x21a58` | `0x2084b0–0x208990` |
| BSS clear | none | `0x208990–0x20e734` |
| Boot/vector overlay | `0x21a58–0x21b20` | `0x20e734–0x20e7fc` |

Initialized data and BSS are adjacent. The final `0xc8` file bytes are now
identified as a relocated boot/vector overlay, **not free code space**.
See [UNIFIED_MEMORY_AUDIT.md](UNIFIED_MEMORY_AUDIT.md) for actual loader execution
and the SDK/ROM-supported memory-layout ABI. Startup `0x4c0` has zero-sized copy/clear
regions targeting `0x216000`; this is not proof that this RAM is available.
The boot path calls `update_ram_layout(0x7000, 0x7400, 0)`. The 1028 nominal bytes
after the overlay are not an approved allocation. Heap/stack/ROM ownership and
indirect references still need closure; no safe controller allocation is certified.

Model: `data/model.pt`, SHA-256
`77ed774f03ce3eaddbb8ac29ac8dfc1be32fdd7bef997b56c54157891aff26d5`.
Eight channels: shape(3), scale(1), saturation(1), room(3); 50 samples, stride 6,
threshold 0.5; twelve labels including none. Counts/g 8005; signed16 BE axes
X=6:8, Y=2:4, Z=4:6. Despike off. Calibration 50-sample rolling pose plus the
reference three-second accepted hold; reversed wear flips axes 1 and 2.

The exporter checked **1,048 windows** from
`data/live/console_20260922_012043.jsonl` against PyTorch on macOS CPU.
Maximum absolute probability difference: **2.384185791015625e-6**, below 1e-5.
Replay SHA `c4b6454c9816c74925f1c9973e015e8b7b8861a25c3742a217178edf89cb8c11`.
The checked-in oracle contains 6332 decoded samples, 21 preprocessing/probability
vectors and 19 reference events, using a deliberately fixed identity frame.
The Swift full-stream replay checks labels, direction, vote counts, confidence,
onset, end and decision latency; this is numerical parity, **not a new gesture
accuracy result**, and does not validate all postures/classes/background use.
The original reference used Python set ordering for direction ties. The later
software fix replaces that with the earliest contributing tied vote in both
implementations, adds tie traces and hash-seed tests, and passes the expanded
parity suite. See the software-fix follow-up in the safety record; the earlier
1,048-window result above remains historical evidence, not the latest total.

Export environment: coremltools 9.0, Torch 2.11.0, NumPy 2.3.4. Coremltools warns
that Torch 2.11 is outside its tested range. Conversion is gated on actual
predictions, never just conversion success. CPU-only float32 is the validated
path; Neural Engine/GPU/float16 parity is not claimed. Use an isolated environment
with `requirements-ios-export.txt`; optional global scientific packages can emit
unrelated NumPy ABI warnings when a system-site-packages environment is reused.

```sh
python -m probe.export_ios \
  --output ios/R02Ring/Gesture/GestureClassifier.mlpackage \
  --fixtures ios/R02RingTests/Fixtures/gesture-replay.json
```

## Verification and limits

- Native C controller: 30 tests, including 40 seeds × 1000 randomized events;
  quiesce/hold/start and stop/release/resume interruption, queue failure,
  timeouts, replayed callbacks, charging, disconnect and timer/sequence wrap.
- Cortex-M0+ freestanding Thumb object compiles with warnings treated as errors.
  This is **not** linked stock-image execution or hardware/ROM emulation.
- Targeted Python firmware/build/identity/realtime regression: 174 passed.
- Full Python regression: 594 passed,
  one existing unrelated failure in
  `tests/test_script.py::test_the_cut_follows_the_gestures_not_the_widest_gaps`
  (`margin=0.00909`, expected >1.0). Initial sandbox-only socket failures disappear
  when the local mock-server suite has localhost permission. No fixes were made
  to unrelated script-cut behavior.
- iOS simulator regression: **28 passed, 0 failed, 0 skipped** on iPhone 18 Pro,
  iOS 27.0 simulator (deployment target remains iOS 17). Covers wire parsing, history depth/retries/midnight,
  persistent dedup/coverage, mode reply correlation/leases, calibration, full
  recorded-stream parity and worker freshness/overflow. Physical iPhone
  lock/background/BLE performance is untested.

## Hard construction blockers / next work

1. Map the pinned **stock** boot/scatter layout, all live code/data, BSS, stack,
   heap/RTOS allocations and relocation/call/literal reach. Prove reserved code
   and RAM space. No speculative cave, blind patch bisection or copied V2 offsets.
2. Trace stock HR/wear/steps/sleep **acquisition**, not only history retrieval:
   accelerometer FIFO consumers, clocks/day rollover, NVM writes, scheduler
   ownership, all optical RUN/indicator paths, charging and disconnect cleanup.
   Preserve algorithm calibration/current/duration and persistent settings.
3. Implement the reviewed stock adapter and collision-free command namespace,
   packet identity/sequence/status correlation, and approved image allowlist.
   Review every async queue/callback race; tokens alone do not stop stale hardware
   work already enqueued. No production transport until this contract is proven.
4. Build a linker-checked candidate with exact original-byte assertions, protected
   boot/vector/DFU/storage/calibration ranges, allowed-diff manifest, deterministic
   rebuild, container checksums and offline DFU framing. The stock equivalent of
   the protected old `0x7ed4` DFU reassembly timer is now mapped at **`0x80f8`**,
   bytes `7d21c900`; preserve it. The remaining protected-range map is incomplete.
5. Independently execute the linked Thumb candidate against explicit ROM/RTOS/
   sensor mocks; inject dropped/full queues, late callbacks, disconnect, reset,
   charging, clock rollover and sensor failures. Re-run every stock lifecycle
   regression. The native policy simulation cannot substitute for this gate.
6. Expand frozen phone/Python parity to all classes, frame changes, direction
   ties, consecutive gestures and ambient corpora. The mobile wrapper currently
   fixes the frame after explicit calibration; Python live auto-frame updates
   are not enabled mid-session. Safe re-calibration/reset behavior must be
   reviewed before changing that. Validate locked/background iPhone processing,
   suspension, backpressure and lease exit on real hardware.
7. On the matching spare only, record stock HR/steps and two baseline sleep
   nights. Review candidate + stock restore path before explicit flash approval.
   Then Health-first smoke tests, 100 toggles, 24–26 Hz/fresh-data/LED checks,
   schedule-boundary tests, ≥190 minutes ambient replay/live use, two unified
   Health nights + two mixed-mode nights and matched battery tests beyond the
   100% gauge plateau. Health acquisition must resume, not merely old history
   remain readable. Transfer receipt alone never closes this gate.

Mode command latency (<1 second target) and model readiness (calibration plus a
2-second window) are separate. No real switching latency has been measured for
unified firmware because no unified image has been built or flashed.
