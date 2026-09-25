# Extended offline safety tests — 2026-09-22

**Release verdict: still NO-GO for unified firmware.** The two reproduced app
failures were subsequently fixed offline at the user's request: **53/53 iOS
simulator tests pass**. The full Python suite is **631 passed / 1 pre-existing,
unrelated script-cut failure**. The unified firmware still has no stock-linked
candidate or hardware adapter. The fixed app has not been installed on the phone.
See the software-fix follow-up at the end; the initial failing results below
are retained as history, not the current verdict on those two regressions.

**Later firmware implementation/proof pass:** 95 offline tests pass (0 skipped),
including actual selected stock Thumb execution, a separate C Gesture sample
queue and reproducible Cortex-M0+ object builds. The shared Health cursor is
preserved in tested active serialized paths; wake/backlog loss, cached reads,
full-buffer aliasing and ignored I2C failure are reproduced negative witnesses.
See [UNIFIED_STOCK_MOTION.md](UNIFIED_STOCK_MOTION.md). This is not a stock-linked
unified image, a step/sleep accuracy test or permission to flash.

## Initial test-only results (before fixes)

No BLE connection, phone deployment, firmware flash, model retraining or
production-code fix was made during this initial test-only pass.

| Check | Result and scope |
|---|---|
| Full Python suite | 616 passed, 1 existing failure (`test_the_cut_follows_the_gestures_not_the_widest_gaps`: margin 0.00909 vs >1.0). |
| Stock/controller suite | 52 passed. Includes 12 single-byte stock mutations and 9 truncation/extension cases; all refuse construction and cannot certify a stock layout. |
| Native C AddressSanitizer + UndefinedBehaviorSanitizer | 1,280,000 randomized events, 20,000 complete entry/return cycles, 7 token-exhaustion cases. No sanitizer finding or policy assertion failure. This is a serialized portable controller, not hardware/RTOS execution. |
| Native controller coverage | 11/11 functions, 99/100 lines, 71/74 branches. Unvisited branches are the invalid-action switch default and the disconnected/charging checks while already in Gesture (normal link handling exits that state first). Not 100% coverage or proof of hardware safety. |
| iOS simulator | 48 passed, 2 failed, 0 skipped. iPhone 18 Pro / iOS 27 simulator, deployment target remains iOS 17. Failures below are ordinary blocking assertions, not suppressed/expected failures. |
| Core ML vs PyTorch, saved test split | 7,627 windows spanning every one of the 12 labels (11 gestures plus none). Maximum absolute probability difference 2.294778823852539e-6, below 1e-5. No retraining, threshold adjustment, or new accuracy claim. |
| Swift numerical fixtures | 108 windows: 3 per label under identity, reversed frame and quarter-spin variants. Preprocessing tolerance 1e-6; model probability tolerance 1e-5. All passed. |
| Decoder fixtures | 17 synthetic traces, including all labels, a sub-floor one-sample blip, a double's internal gap, consecutive gestures, reset dropping pending events, and a tied direction vote. Only the tied-direction case fails. |
| Additional recorded replays | 4,650 samples / 47 Python events from the four-posture recording, plus the last 1,750 samples / 1 event from the sustained-wave recording. Full model/decoder event parity passed. Fixed identity frame, not an accuracy or automatic-frame-change validation. |
| Health import | 100 randomized orders with duplicate packets; every omitted HR/step packet; conflicting duplicates; checksum corruption; invalid sleep stages/lengths; duplicate sleep days; 10,000 bounded malformed inputs; storage failure and persisted retry depth. Passed. Does not validate acquisition on the ring. |
| Phone processing/control | Unsupported capabilities, charging refusal, disconnect during reply, wrong boot/session/mode in renewal, sequence rollover/replay, stale/future timestamps, packet gaps/checksums/freeze, queue overflow and in-flight cancellation. Passed except premature publication from an invalid renewal. |
| Whole-image DFU byte parity | Swift and Python agree on all 139 frames for both pinned stock and V2 (START, INIT, 135 DATA, CHECK, END); exact payload reconstruction. Also all 255 error statuses per command, truncations and single-bit ACK corruption are rejected. **No transfer performed; no unified image tested.** |
| Historical ambient freshness | The two old ambient hours contain 1,024.1 s (28.4%) and 1,394.6 s (39.3%) of frozen data. They do not close the fresh 190-minute ambient requirement. |

## Originally failing app gates (fixed in the follow-up below)

### 1. Direction-vote ties disagree between Python and Swift

`GestureSafetyReplayTests.testDirectionVoteTieMatchesPinnedPythonOracle`
reproduces **Swift up vs Python down** for the same tied votes. Python's
`whip.events.BurstTracker._judge` chooses through `max(set(dirs), key=dirs.count)`;
Swift's `GestureBurstTracker.dominant` chooses the first tied vote. Python set
order is not a stable semantic tie-break. The oracle pins `PYTHONHASHSEED=0`
to make this failing case repeatable, **not** to solve the discrepancy.

Required change identified by this test: define one deterministic tie policy in the reference and
port, regenerate the oracle, and rerun numerical/full-stream/ambient regressions.
Do not loosen the assertion, choose a conveniently passing hash seed, retrain,
or reinterpret this as a Core ML numerical error.

### 2. An invalid renewal publishes Health before rejection

`UnifiedModeTests.testInvalidRenewalMustNotPublishHealthBeforeItIsRejected`
returns a correlated request ID but a different boot ID and Health status from
a Gesture renewal. `UnifiedModeCoordinator.heartbeat` calls `accept` **before**
checking the boot/session/mode/charging renewal postconditions. `accept`
updates observable status and invokes `onModeChange`. The request later throws
and clears control, but the invalid Health notification already escaped.

This is consequential: `AppModel.runtimeModeChanged` immediately passes a
non-nil status to `HealthCoverageStore.observe`; Health closes open uncertainty
intervals. The regression proves premature publication; the persistence impact
is established by that call path, not by a live-ring observation.

Required change identified by this test: validate the entire reply against the outstanding operation
before publishing it or calling observers. Preserve the uncertainty interval on
an untrusted reply, and test observer/persistence side effects as well as the
coordinator's eventual nil status. No production fix is included in this pass.

## Provenance and reproduction

- Model SHA-256: `77ed774f03ce3eaddbb8ac29ac8dfc1be32fdd7bef997b56c54157891aff26d5`.
- Test-split SHA-256: `4474896c104c5e0db4ac5e39dd7762d72ad83c157545eefddbb4a5d96e52e088`.
- Fixture: `ios/R02RingTests/Fixtures/gesture-safety-replay.json`; contains the
  manifest, source recording hashes, 108 numerical windows, traces and events.
  Initial SHA-256: `29042604b99ea7a4a610b6487c57abf4085c5ef28ff7465b7a1edbe3694cb9ec`.
  The replacement fixture and its reviewed differences are documented below.
- Generator: `probe/ios_safety_replay.py`; requires a new output path and a pinned
  model. Reads the existing bundled model; does not regenerate or replace it.
- C stress harness: `tests/native/mode_controller_stress.c`, invoked with both
  sanitizers by `tests/test_fwunified.py`.
- Local raw reports: `/tmp/whip-extended-safety.If2CY5/` (temporary, not committed):
  `full-python.xml`, `controller-tests.xml`, `controller.profraw`,
  `controller.profdata`, `model-parity-final.json`, simulator `.xcresult` bundles.

```sh
.venv/bin/pytest -q tests/test_fwunified.py
.venv/bin/pytest -q
python -m probe.ios_safety_replay \
  --fixtures /tmp/new-gesture-safety-replay.json --report /tmp/new-model-parity.json
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcodebuild test \
  -project ios/R02Ring.xcodeproj -scheme R02Ring \
  -destination 'platform=iOS Simulator,name=iPhone 18 Pro' CODE_SIGNING_ALLOWED=NO
```

The parity generator uses the Core ML export environment documented in
[UNIFIED_FIRMWARE.md](UNIFIED_FIRMWARE.md). Coremltools still warns about Torch
2.11 being outside its tested range and optional global NumPy-ABI dependencies.
Actual CPU float32 predictions passed; supported clean-toolchain validation is
not claimed. Xcode also warned about old headermaps and failure to locate
`simctl` for diagnostic collection after assertion failures; completed test
bundles identify the two real failures above.

## Tests still blocked by missing prerequisites

Portable simulations do not substitute for any of these:

1. Exact stock code/RAM allocation, stack/heap/RTOS ownership, protected
   boot/DFU/storage/calibration map, branch reach and allowed-diff validation.
2. A real stock health/optical/accelerometer adapter, collision-free wire
   protocol and candidate identity. No adapter or linked unified image exists.
3. Independent linked Thumb execution with ROM/RTOS/sensor mocks and injected
   queue, callback, reset, rollover and sensor failures. A native policy test
   does not exercise stock startup or asynchronous hardware postconditions.
4. Physical iPhone lock/background/suspension/BLE/throughput testing against the
   approved protocol, plus automatic-frame-change parity beyond fixed frames.
5. Matching-spare stock baselines/recovery, actual HR/step/sleep acquisition,
   schedule-boundary/charging/disconnect behavior, 100 physical toggles,
   verified-dark fresh 25 Hz sessions, >=190 fresh ambient minutes, multiple
   sleep nights and matched battery tests beyond the 100% gauge plateau.

Keep the construction refusal and app capability lock in place. Neither these
tests nor successful DFU framing authorizes flashing the daily ring.

## Physical-iPhone follow-up — 2026-09-22

After the user authorized phone-only testing and confirmed other ring clients
were disconnected, the signed test build was installed and exercised on the
paired **iPhone 14, iOS 26.6.1 (23G83), arm64e**. The production firmware and
model were not changed. The unified mode transport remains unattached/locked.

- Physical XCTest result: **48 passed, 2 failed, 0 skipped**, the same
  direction-tie and premature-Health-publication assertions as the simulator.
  The numerical/Core ML, recorded replay, health import/storage, worker fault
  and pure DFU-byte tests therefore also ran on the physical phone. This is
  not a successful release gate or a BLE/background acquisition test.
- Local result bundle:
  `/tmp/whip-phone-safety.jevTCg/physical-phone-tests.xcresult`.
  Signed build and `.xctestrun` are under that directory's `DerivedData`.
- The app's existing data container was backed up before installation to
  `data/phone-backup-20260922.yVIY9F/` (local, git-ignored, owner-only directory).
  Do not commit or upload this private backup. A temporary copy also exists
  under `/tmp/whip-phone-safety.jevTCg/pretest-app-data`.
- Pre/post database integrity checks returned `ok`. Comparing every original
  health row's non-Core-Data-bookkeeping columns found none missing or changed:
  4 step records, 1 sleep session and 5 sleep stages were preserved; both
  snapshots contained zero heart-rate records. This verifies preservation, not
  whether the ring is currently acquiring any of those measurements.
- A broad post-test Library copy hit an unrelated protected SplashBoard
  snapshot. A separate copy of `Library/Application Support` succeeded and
  supplied the actual post-test database used for comparison.
- Signature verification initially failed inside the sandbox; the same strict
  verification using normal macOS signing services passed. No certificate trust
  settings or signature checks were weakened. The initial phone transport reset
  cleared on the subsequent read-only connection; no Bluetooth bond was removed.
- The app was then launched normally with `devicectl`. The user reported
  **"Connected / synced health history"**. A subsequent read-only copy of app
  preferences and Application Support is at `/tmp/whip-phone-sync.ScLI2f/`.
  The copied database passes integrity checking, and all existing health rows
  remain unchanged: zero added, removed or updated in the four health tables.
  The saved successful-sync timestamp is unchanged from before installation
  (`2026-09-23T00:02:16Z`), with no per-metric import cursor present. Thus the
  user-observed connection is confirmed, but a new completed history import
  or fresh health acquisition is **not** established by this snapshot.
- A new open coverage record at `2026-09-23T05:11:40Z` records firmware version
  `RT02CR_3.12.07_260514`, reason `unverifiedFirmware`. This supports a live
  connection/identity read of the 25 Hz firmware family, not stock Health.
  It does not distinguish the original 25 Hz image from V2 or prove a full
  image hash. The persisted mode remains `gesture`, as it was in the backup;
  that cached preference alone is not a fresh fingerprint result. The app
  deliberately records legacy non-Health firmware as unknown coverage.
- The user subsequently clarified that the app says **health sync is paused**,
  consistent with the unchanged import data. Connection passed, not health
  acquisition or a completed fresh import.
- Startup can reconnect to the saved ring and read identity/history; stock
  history sync is read-only with respect to ring settings. No desktop BLE
  client, raw-stream start, setting change or firmware flash was initiated here.

Physical lock/background behavior, live gesture inference through a reviewed
unified transport, exact current image identity, actual health acquisition and
spare-ring firmware tests remain open. The installed phone build still contains
the two failures; the later offline fixes below have not been deployed to it.

## Software-fix follow-up — 2026-09-22

The user explicitly requested fixes for both reproduced failures. Work remained
offline: no phone deployment, BLE connection, ring command, settings change,
firmware modification or flash. The app capability lock and unconditional
unified-image construction refusal remain in place.

### Changes

- `whip.events.dominant_direction` now counts non-`none` directions and resolves
  equal counts by the **earliest contributing vote**, matching the existing
  Swift decoder. Both Python burst judgement and sustained-event enrichment use
  it. Direction ties do not use confidence; gesture-label tie rules are unchanged.
  Tests cover reversed vertical/horizontal ties, multi-vote/four-way ties,
  majority overriding the first vote, `none`, and Python hash seeds 0, 1, 42,
  123 and random. No retraining, thresholds or model weights changed.
- `UnifiedModeCoordinator.heartbeat` now checks boot, session, Gesture mode and
  charging **before** `accept` can publish. `accept` still checks request ID and
  connection generation before changing state. Rejected renewals cannot reach
  either Combine status subscribers or `onModeChange`; disconnect publishes
  unknown/nil, not an invented Health confirmation.
- The original invalid-Health regression now exercises the real
  `HealthCoverageStore` as an observer and reads it back through a new SwiftData
  context: the interval stays open and its unverified flags stay false. A
  positive control proves a valid renewal keeps the gap open and a subsequent
  confirmed Health return closes it. Separate tests cover wrong request IDs and
  disconnect during renewal as well as invalid boot/session/mode/charging.

### Verification

- Re-ran the two original iOS regressions **before** the fixes: both failed.
- Full simulator suite **53 passed, 0 failed, 0 skipped, 0 expected failures**
  on iPhone 18 Pro / iOS 27. Includes numerical and recorded stream parity,
  observer/storage regression checks, health import, processing and DFU bytes.
- Targeted Python event/realtime suite: **57 passed**. Full Python suite:
  **631 passed, 1 failed**, still only
  `test_the_cut_follows_the_gestures_not_the_widest_gaps` (0.00909 vs >1.0).
  This separate script-label alignment issue was not modified or suppressed.
- Rechecked all **7,627** Core ML/PyTorch windows: zero failures, maximum absolute
  probability difference **2.294778823852539e-6**, still below 1e-5.
- Regenerated the safety fixture from the Python reference under hash seed 42,
  with no seed requirement in the generator. All **108 numerical vectors** and
  both recorded replays are exactly unchanged. Among the original synthetic
  traces, only `direction_vote_tie` changes: direction down → up; every other
  field is identical. Three reversed/horizontal tie cases bring the total to
  **20 traces**. Swift checks the explicit expected directions as well as parity.
- Current fixture SHA-256:
  `13b67e597058cfbdc463c8fb66112391c0de9f6a004e1ec1d020287077dae55a`.
  A copy of the original fixture is retained with the local run artifacts.
- Archived ambient before/after replay using the recorded frame corrections:
  `negative_20260915_021616` (90,001 samples, flip_axis0) yields 4 events under
  both policies; `negative_20260915_224235` (88,690 samples, flip_axis1) yields
  zero under both. All event fields are identical, not just counts. The old
  set-order policy was pinned to hash seed 0 for this comparison. The known
  frozen stretches remain in those captures: this is regression evidence, not
  new ambient freshness/accuracy validation.
- Sandbox restrictions initially blocked Core ML compilation-cache access and
  localhost Python test servers. Scoped approved reruns completed; these were
  environment failures, not relaxed assertions. Existing Core ML toolchain and
  Xcode headermap warnings remain as described above.

Local raw evidence: `/tmp/whip-failure-fixes.o5L3Cg/`, including
`before-fixes.xcresult`, `after-fixes.xcresult`,
`full-python-unsandboxed.xml`, `model-parity-fixture.json`, `ambient-replay.json`,
its read-only replay script, and the old fixture.
Physical-device retesting of the corrected app remains pending. Passing these
software regressions does not validate new health acquisition or make unified
firmware flash-ready.

## Parallel firmware workflow follow-up — 2026-09-22

All work remained off-ring. No BLE, phone installation, firmware flash,
production transport attachment or change to the construction/allowlist gates.
See [UNIFIED_WORKFLOW.md](UNIFIED_WORKFLOW.md) for implementation and remaining
completion gates; the earlier software and phone results above are unchanged.

### Final reproducible build

Local output:
`firmware/unified/build-20260922-workflow-handoff/` (git-ignored).
`manifest.json` binds the stock/source/test/tool hashes, compiled objects,
artificial-address ELF, JUnit and ordered collection/execution reports.
**234 passed, 0 failed, 0 skipped**, 36.75 seconds for test execution:

| Required suite | Tests |
|---|---:|
| Stock FIFO/motion and compiled tap observer | 40 |
| Native tap sanitizer + three ARM object builds | 4 |
| Controller/identity/construction gate | 52 |
| Actual linked ARM runtime | 38 |
| Stock command routing/prelude | 11 |
| Stock health/optical lifecycle | 45 |
| Stock memory/overlay/ABI | 25 |
| Proof integrity, selection and outcome rejection | 19 |

All three C components and test-support object rebuild identically; the ELF
relinks identically. The final invocation intentionally supplied
`PYTEST_ADDOPTS='-k nonexistent_safety_test'` and
`PYTEST_PLUGINS=missing_inherited_plugin`. The sanitized workflow still collected
and executed every required identity. Inner negative guard fixtures deliberately
exercise failure/skip/xfail cases; those cannot count as successful proof runs.

ELF SHA-256:
`3a4f283c08e0f8809555e4dc9af1ed310f4c4d556e7fe2d30b3dd1ba9822e39e`.
Collected identity report SHA-256:
`d4f0f7cc3b336c887e57123b54205226d708f1b6e84d00bb1f403becbfafc0bd`.
Execution identity report SHA-256:
`79aa027292b70b25db7d89a5fba17f8e36f37577664de370c56661e278b6c889`.

The ELF runs at synthetic `0x01000000`, not the stock flash/RAM map. It has no
ROM, sensor or RTOS adapter. The stock harnesses execute only whitelisted
instruction slices with explicitly documented mocks. Proof reports are not a
full-chip emulator, health-accuracy result, safe-placement certificate or flash
approval. Per-function stack reports are not worst-case task/interrupt stacks.

### Additional regression and independent review

Existing `test_fwimage`, `test_fwbuild`, `test_fwidentity`, `test_fwoptical`,
`test_dfu`, `test_flash`, `test_protocol`, `test_accel`, `test_accelrange` and
`test_capture_cleanup`: **206 passed**, 6.04 seconds. Local JUnit:
`/tmp/whip-unified-build.m1E9lk/firmware-regression-final.xml`.
This is targeted regression, not a new full-Python or iOS run.

Independent review reproduced a runtime stale-backlog lease bug and found
vacuous randomized coverage. Both are fixed: acquisition and queue age are
checked; randomized tests explicitly exercise repeated active Gesture sessions.
Review also hardened emulator read boundaries and proof snapshot ordering.
The first 126-test ELF run predates these fixes and is historical only; the
134-test intermediate run predates integration of the three stock audits and
proof guard. The final 234-test manifest identifies the current tested sources.
The handoff run also includes the completed memory-audit configuration-read
metadata; its source hash is pinned anew instead of reusing an older manifest.

Memory auditing used the PDF-reading skill for the vendor guide and a
UUID/symbol-matched SDK-derived source mirror to interpret stock ABI arguments.
It did not borrow another device's memory allocation or flash map. All 200
apparent tail bytes are occupied boot code/literals. Live configuration and
indirect ownership remain unresolved, so no allocation or OTA construction was
approved. Optical auditing also demonstrated a timeout fallback can reach an
aggregation boundary without a sensor result; disabling RUN alone is inadequate.
