# RT02CR firmware research and handoff

Saved 2026-09-22 at the user's request, after the completed Fable workflow and
the LED-off experiments. This is the consolidated technical record for the
ring. It now also records the first controlled V2 deployment and native-stream
validation; that is evidence for this exact ring/image, not a general safety claim.

Later unified-build work: [UNIFIED_STOCK_MOTION.md](UNIFIED_STOCK_MOTION.md)
records stock-only FIFO/Health mappings, selected ARM execution proofs and a
separate Gesture sample-copy component. No unified OTA image exists yet; the
construction gate remains closed. Do not transplant the V2 offsets below into
the stock-based unified effort.

Latest off-ring [integrated retirement](UNIFIED_RETIRED_SWITCH.md) exercises the
compiled coordinator and original Health sample path together with known-root
retirement across nine phases, in the pinned 21-object layout. Physical/RTOS/
steps/sleep remain fixtures. [Discovery](UNIFIED_DISCOVERY.md) adds an unattached
20-byte C/Swift identity format and a separate **22-object/132-function** link:
**9256/9520 append bytes, 264 left**, plus **1894 unowned moved bytes**.
**63 guarded supplemental tests pass**, **253 content hashes** independently
checked; simulator app build passes. Neither conditional ELF is installable.
The [stack archive review](UNIFIED_STACK_EVIDENCE.md) verifies three later
captures but does not establish SP-depth history, headroom or memory ownership.
No Codex ring access or construction/admission gate change.

Preceding [combined retirement](UNIFIED_STOCK_RETIREMENT.md): its 21
objects/130 functions link conditionally, moving **1894 bytes into
unowned regions**, with **9132/9520 append bytes** and 388 left before missing
hooks. An exact-ELF-pinned 16-edit plan tests known-root retirement and selected
stock Health/DFU paths together in emulator memory; no installable image exists.
The standalone ELF has no stubs and production rejects it. **55 guarded
supplemental tests pass**, with **277 content hashes** independently checked.

Latest [raw-ingress checkpoint](UNIFIED_LEGACY_GATE.md): **3251 guarded tests,
zero skips**, all **371 hashes checked**, both main ELFs unchanged. Four unlinked
candidates plus all components attempt **11108/9520 bytes**, 1588 over, no full
ELF. **A1/BF/CE/CD** retirement needs app identity/discovery migration before attachment.
The [raw retirement audit](UNIFIED_RAW_RETIREMENT.md) preserves shared Health
readers and identifies only conditional code space. Claude separately completed
268 RAM diagnostic reads with disconnect; its archive and 39 RAM tests were
rechecked off-ring. Installed V2 has **264 free data-heap bytes, 104 minimum**;
the unchanged gap is not owned storage. No Codex device access or release gate
change. See [resource handoff](UNIFIED_RESOURCE_BUDGET.md).
The later [ROM resume review](UNIFIED_ROM_RESUME_EVIDENCE.md) replays three
additional archives but leaves context-restoration, boot-once and RAM ownership
unproved; equal gap digests across separated observations do not prove DLPS
retention or absence of writers. Codex stayed entirely off-ring.

Preceding [coordinator checkpoint](UNIFIED_COORDINATOR.md): **3143 guarded tests,
zero skips**, all **365 source/artifact/report hashes checked** in
`firmware/unified/build-20260924-coordinator-v1/`. Actual C now joins checked
STOP, original-token retirement and atomic current-settings Health commit;
physical and scheduler receipts remain fixtures. Coordinator/commit/service are
unlinked candidates: all current real code together exceeds the fixed region by
**1524 bytes**, no complete ELF. Existing components occupy 9500/9520 bytes;
final linker/ELF bounds are qualified without more capacity. RAM ownership,
hardware attachment, physical continuity and recovery remain unresolved. Codex
performed no device access; Claude Code separately owns user-requested live tests.

Preceding [parallel layout-candidate checkpoint](UNIFIED_RESOURCE_BUDGET.md):
**3060 guarded tests, zero skips**, all **357 source/artifact/report hashes
checked** in `firmware/unified/build-20260924-layout-candidates-v1/`. Both main
ELFs remain unchanged. The new 240-byte service database and Health commit are
separate unlinked candidates. An explicitly unowned scattered-placement trial
includes Health commit but is production-rejected; adding the service fails
the unchanged bound with no ELF. Claude's separate RAM audit passes 15 tests,
not an ownership/retention proof. No stock file, ring or production gate changed.

Preceding implementation: [lossless queue compaction](UNIFIED_RESOURCE_BUDGET.md)
and [checked-health cancellation](UNIFIED_HEALTH_CANCELLATION.md) pass
**3004 guarded tests, zero skips**, all **265 source/artifact/report hashes checked**
in `firmware/unified/build-20260924-parallel-integration-v1/`. Exact source ages
keep the receipt at 288 bytes; the proven eight-bucket bound reduces temporary
delivery 208→64 and observed nested stack 388→244. Prior/new ARM behavior agrees
in synthetic tests; both main ELFs reproduce, with no physical gate opened.
The separately archived [Health commit guard](UNIFIED_HEALTH_COMMIT.md) closes
the software settings check-to-commit gap; its 196 text bytes do not fit with
all existing components, so neither main ELF includes it. Revision ownership
and physical resume remain unproved. The
[integrated switch/readiness checkpoint](UNIFIED_READINESS.md) joins actual C
and stock paths in one ARM state, with physical boundaries explicitly simulated.
It now includes the original stock notification wrapper, but not ROM radio/
buffer-lifetime proof. Complete code/RAM budgeting, rather than the 52-byte component margin, leads
the next implementation batch. The preceding
[heap-free sample I/O](UNIFIED_OPTICAL_IO.md) executes two fixed sample-reader
call replacements in emulator memory, without allocating and with checked
bus/release results. The old wrapper alone does not install these edits; other
stock I/O defects remain. No stock file or physical gate changed. The preceding
[optical work implementation](UNIFIED_OPTICAL_WORK.md) adds actual C for original-
ticket in-flight reads and software-buffer retirement only after fully evidenced
pause. It executes the original stock reader/clear, changes both ARM ELFs and
shares repeated checked code without removing safety checks or capacity. No
stock hooks or physical gate were enabled. Measurement provenance, current-
settings fresh-job resume and physical continuity remain unproved. The preceding
[optical read evidence](UNIFIED_OPTICAL_ACQUISITION.md) rules out top-level zero
and parsed/read flags as measured provenance: failed or cached-only reads can
produce them. This continuation changes neither ARM ELF. The preceding unattached
[HR commit guard](UNIFIED_HR_RESULT_COMMIT.md) adds 80 bytes and protects exactly
four positive-HR-result stores against an ordinary-interrupt pause race. Its
original-ticket/provenance inputs remain caller obligations; no stock hook or
production inventory was enabled. That guard implementation changed both ARM ELFs.
Earlier
[optical-event/commit witnesses](UNIFIED_OPTICAL_DISPATCH.md) trace a separate
untagged hub path that can restore result state after STOP under synthetic
cached-ready/algorithm fixtures. Original work identity and actual commit
serialization remain required; no installed guard or physical observation.
The off-ring
[status audit](UNIFIED_STATUS_NOTIFICATIONS.md) proves `0x73` is shared by
multiple event subtypes and adds redacted subtype/checksum logging; every
foreign packet remains terminal. The failed packet's cause remains unknown.
The separately requested [create-hook code retry](UNIFIED_CREATE_HOOK_READ.md)
completed all 359 transactions, repeated code/header equality, final checks
and verified disconnect. Exact archive replay passes; no sensor/flash command.
The earlier `0x73` abort remains separately archived. Further access needs fresh
exclusive-idle coordination. Captured hook/comparator paths now execute off-ring,
with empty-handle creation failure reaching unread `0x111a6`; this is not a
safe-return or physical resume proof. The reference SDK initializer
writes a different create hook; its body must not substitute for the ring's.
Those diagnostic-only continuations changed neither ARM ELF; all construction
gates remain closed. The separate
[support-code/state diagnostic](UNIFIED_SUPPORT_READ.md) completed on a separate
retry: 284 matching transactions, repeated values/postchecks and verified
disconnect. The earlier discovery failure is retained separately. The observed
create hook is nonzero (`0x205c01`); its target was later captured and selected
paths executed under synthetic pool/list/critical boundaries. Arithmetic and
context helpers now execute off-ring without those former mocks, not a complete
live creation/resume proof. Actual-address components
occupy 9468 bytes, leaving 52 configured bytes; the dispatcher, frame and timer
barrier total 796 bytes, not approved RAM. Queue compaction saves 192 bytes
without reducing its 32-sample capacity, output semantics or protections.
The [current-controls read](UNIFIED_STOCK_SETTINGS.md) adds 48 linked bytes and
reads exact stock settings without changing them. Real stock scheduling and
shared working-state writes are now witnessed; complete serialized fresh-job
resume is still unimplemented. Indicator retirement remains emulator-only.
The [timer-resume code read](UNIFIED_TIMER_RESUME_READ.md) subsequently completed
after fresh coordination: 180 matching transactions, 452 new bytes read twice,
passing postchecks and verified disconnect. Standalone archive replay passes;
the new execution build includes that evidence and 79 captured-code cases.
Native create consumes an allocation before a zero-period assertion; conditional
conversion tests do not prove the ring's tick rate. Captured native kernel tests show
old callbacks/IDs survive rearm and can run immediately on stale commands. That
rearm continuation left both ARM ELFs unchanged; no rearm API was added.
Captured ROM execution
exposed a null-queue assertion, now guarded in the unattached C fence. Compiled
C/captured-ROM/callback integration passes, with queue kernel/scheduling still
explicit substitutes. Invalid timer handles can reach a deliberate null write;
STOP acceptance does not prove ownership or shutdown. Full health fences remain
unestablished. RAM-layout and boot-error helpers are now executed, not complete
allocation/recovery proof. No ring access occurred in this implementation turn.
The extended cancellation primitive validates twelve mapped timer slots before
actual ROM STOP, preserves handles/state and propagates each failure. A later
timer barrier can still finish after a failed STOP; it is not a blanket success
receipt. Caller serialization, complete producer coverage and actual current-
settings resume remain unproved. Activity/wear have non-optical obligations;
the expanded slot table does not approve pausing all twelve in production.
The [boot comparison](UNIFIED_BOOT_REFERENCE.md) completed 182 transactions,
matching a non-secret 52-byte prefix and 528-byte checker. A subsequent 6076-byte
ROM plan aborted on unrelated UART traffic after 188 replies, with no repeated
new window or successful capture. No automatic retry, sensor command or flash.
A separate freshly coordinated passive check completed 60 seconds with zero
notifications/zero UART commands and verified disconnect. The interruption's
cause remains unknown. A later explicitly requested/freshly coordinated retry
completed 974 CD01 transactions, all 6076 fixed ROM bytes matching twice, passing
postchecks and verified disconnect. Archive: `firmware/research/2026-09-23/rom-integration/`.
This supplies code for offline review, not physical integration/recovery proof.
Installed V2 and all production gates are unchanged. Older counts are historical.

Earlier diagnostics: the [fixed ROM reads](UNIFIED_ROM_DIAGNOSTIC.md) completed
114/142/144 matching transactions with prerequisites and verified disconnect.
No sensor or flash command was sent. Captured hook slots were zero twice,
selecting the captured default routines in that idle snapshot. Those call the
then-unread timer-command API; callback drain remains unproved. That older offline
build passes **1276 tests, zero skips**, with all 132 hashes checked in
`firmware/unified/build-20260923-rom-internals-v1/`. No unified
image exists. A specifically reviewed daily-ring test may be considered, but
diagnostics do not automatically authorize flashing or waive physical gates.

Previous offline result: the [memory continuation](UNIFIED_RESOURCE_BUDGET.md)
passes **986 guarded tests, zero skips**, with all 120 hashes checked in
`firmware/unified/build-20260923-memory-v1/`. Duplicate sample-delivery scratch
was removed; its two nested ARM local frames total 440 rather than 600 bytes.
The dispatcher still needs 1016 bytes versus 1024 nominal aligned RAM bytes,
not approved space. Only the daily-use ring is available. No ring/phone access,
unified image, new allocation or flash authorization resulted from this work.
Earlier continuation results below describe their historical input snapshots.

First coordinated follow-up: [UNIFIED_WORKFLOW.md](UNIFIED_WORKFLOW.md) records
the integrated Health-default runtime, artificial-address linked ARM tests,
stock boot-overlay/health/command audits and guarded build workflow. **234
offline tests and 206 existing firmware/protocol regressions pass.** This is not
an installable image or evidence of new physical health acquisition; no ring
access or flash occurred in that workflow.

The [second follow-up](UNIFIED_WORKFLOW_2.md) adds source/lifecycle integration
and 512 guarded tests. Its separately coordinated idle read matched V2's sampled
code and collected repeated bank/RAM configuration. Bank0 is configured as
288 KiB and OTA temporary space as 144 KiB; bank1 is absent. These declarations
do not prove physical capacity, free placement or recovery. No flash or sensor
command was sent. Actual acquisition and installed-stock bindings remain open.

The [third follow-up](UNIFIED_WORKFLOW_3.md) completed the separately coordinated
80-byte bank0 descriptor read twice and archived the exact 91-transaction session.
APP and OTA staging each declare 144 KiB, agreeing with the OEM upload limit;
9520 bytes beyond stock are configured margin, not approved expansion. The
then-current guarded build passed **748 tests with zero skips**, plus 194 separate
existing regressions. New actual-code witnesses cover OEM bounds/failures,
FIFO completion/overflow, app decoder parity and optical lifecycle hazards.
A heap-free STOP-write helper is implemented but unattached. Physical geometry,
recovery/RAM ownership, acquisition timing, complete callback fencing and real
health continuity remain unproved. No unified image was built or flashed.

The later [offline codec continuation](UNIFIED_WIRE_CODEC.md) implements matching
C/Swift control and motion frames for a distinct future GATT service. The latest
guarded build passes **793 tests**, and the full iOS simulator suite passes
**58 tests**, both with zero skips. All 105 source/artifact/report hashes were
rechecked. No service/dispatcher/live transport is attached, and no ring or
physical phone was accessed in this continuation. Physical gates remain open;
the output is not an installable unified image.

The [dispatcher integration](UNIFIED_DISPATCH.md) then connected commands to the
portable guarded adapter, with completion-aware replies and strict ownership,
replay, timeout and send-failure handling. Latest guarded build: **874 passed,
zero skips**, all 114 hashes checked. Nine component objects total 8066 `.text`
bytes before actual hooks and support code; this is not a fit/placement proof.
No hardware or simulator was accessed in this continuation, and no service or
actual stock-linked dispatcher is installed. Physical gates remain unchanged.

The [stock transport continuation](UNIFIED_STOCK_TRANSPORT.md) adds an unattached
ARM registration/send shim tested through the original wrappers. Executed
witnesses demonstrate unsafe legacy queue wrap, latched wake failures and missing
connection-generation binding; default-size SDK callback enums also misinterpret
the stock cause field. All five declared service slots are used. Latest build:
**936 tests, zero skips**, all 120 hashes checked; ten components total 8242
`.text` bytes, not final fit approval. No service, image or hardware change.

## 1. Current state and the user's intended direction

- The ring now runs the **V2 optical-off 25 Hz** image,
  `firmware/rt02cr-25hz-optical-off-v2-experimental.bin` (SHA-256
  `0d18a0fa…e14c`). It was flashed on 2026-09-22 after a pinned-hash dry run;
  all 135 DATA acknowledgements and CHECK passed.
- On that unchanged firmware, a temporary command sequence produced fresh,
  motion-responsive 25 Hz acceleration while the user saw the LEDs stay dark.
  This passed a one-minute trial and a separate two-minute repeat. It is not a
  long-duration battery result or a test of the new firmware.
- A subsequent ten-minute host-workaround battery run completed at fresh ~25 Hz:
  92% to 90%, approximately 0.20 percentage points/minute, with successful cleanup.
  The user observed flashing then stopping. This short, unmatched run does not
  establish LED savings or full-charge runtime. See [BATTERY_TESTS.md](BATTERY_TESTS.md)
  and the two separately archived battery logs (first interrupted, repeat complete).
- Post-flash fixed-site reads classified the installed code as
  `optical_off_candidate`. A native `A1 04` run (no temporary CE/3B workaround)
  delivered 699 distinct samples in 28.0 s at 24.997 Hz with fresh motion, then
  stopped cleanly and returned to idle. Visual LED darkness is still awaiting
  the wearer's explicit confirmation; charging and full battery runtime remain untested.
- That candidate intentionally disables optical health measurements **even
  outside gesture tracking**, and disables optical indicators too. Stopping
  gesture tracking would not restore those functions on this image.
- After this trade-off was clarified, the user asked to preserve the complete
  research and then explore **stock firmware for health tracking, switching
  back to a dedicated gesture image for gestures**. This is the likely direction,
  and the iOS app now contains an explicit, confirmation-gated mode switch.
- A single image with a reversible health/gesture mode has **not** been built.
  It would require a different optical-ownership design and its own validation.
- Do not let hardware work block the preference-research milestones, which can
  use keypress labels without the ring.

The detailed experiment chronology remains in [LED_FIX.md](LED_FIX.md).
Original review outputs, mapping tools, all six captures and the byte-level v2
manifest are preserved in the [research archive](../firmware/research/2026-09-22/README.md).
Older contradictory entries in `AGENTS.md`, `CLAUDE.md` and `HARDWARE.md` are
historical, not current LED/firmware guidance.

## 2. What the evidence can establish

Use these categories when extending the work:

| Evidence | What it establishes | What it does not establish |
|---|---|---|
| Saved BLE packets and diagnostics | Delivery, changing samples, sampled registers/state | Visible darkness or complete absence of replay |
| User's visual observation | LEDs appeared dark during the observed interval | Electrical power consumption or invisible emission |
| Disassembly of a pinned image | Control flow and bytes for that exact image | Behavior of another vendor version or physical chip revision |
| Instruction-execution/unit tests | Specified branches, flags, registers and host failure handling | RTOS scheduling, actual BLE timing, physical sensor behavior |
| Checksums and offline DFU dry run | Container consistency, pinned identity, transfer framing/reassembly | Successful boot, recoverability or battery life |
| Short successful host workaround | Optical shutdown and fresh acceleration can coexist | That the firmware candidate works, stays dark for hours or saves energy |

Packet rate and sample freshness are separate requirements. A stream that repeats
one cached XYZ value 25 times a second is a failed motion stream, even if its
packet-loss score is perfect. Similarly, stopping all acceleration is not an
LED-off gesture solution.

## 3. Device identity and platform correction

| Field | Value / qualification |
|---|---|
| Product / hardware | Colmi R02 / `RT02CR_V3.1` |
| Advertised name | `R02_CC07`; stock previously `COLMI R02_CC07` |
| Recorded MAC | `30:32:41:33:CC:07`; radio addresses can rotate |
| macOS CoreBluetooth identifier | `3C2FA77E-1BE3-A0C5-0DD5-DB6A3AD452B2` |
| Current DIS firmware string | `RT02CR_3.12.07_260514` |
| Base/candidate container version | `RT02CR_3.12.00_251205` |
| Stock image version | `RT02CR_3.12.02_260824` |
| Accelerometer | STK8321, 7-bit I2C address `0x1F`, observed ID `0x23` |
| Optical front end | VC30F-family, I2C address `0x33`; driver accepts IDs `0x25` / `0x27` |
| Battery | Project's recorded nominal capacity: 17 mAh |
| Platform | Strong binary evidence for Realtek RTL8762E family, not the older BlueX RF03 attribution |

The platform correction is based on **79 distinct ROM BL targets matching all
79 entries in the RTL8762E ROM symbol table**, with the Thumb bit applied during
symbol lookup. This was reproduced while saving this handoff. It establishes
the compatible platform family; it is not a physical reading of the package
marking or proof of an exact SKU. The disassembly is ARM Thumb, consistent with
the Cortex-M0+ platform identification in Fable's findings.

The optical library identifies itself as `core30fx_v0.23` at file `0x1F65C`.
The pin survey found I2C0 at `0x40015000`, P2_4/P2_5; optical INT at P4_1
(pad 33); accelerometer INT at P2_6 (pad 22). No independently identified
sensor-power GPIO was found. That negative survey is not proof that no hardware
power-control mechanism exists.

### BLE connection traps retained from the project

- Match `advertisement.local_name or device.name`, not only `device.name`.
  `COLMI R02...` also defeats a simple `startswith("R02")` check.
- A stale macOS bond can leave the ring advertising strongly while connections
  time out in both Python and Chrome. Forgetting the device was the effective
  remedy in earlier tests; toggling Bluetooth or restarting did not remove it.
- Rotating radio addresses may appear as duplicate paired entries. CoreBluetooth
  can collapse them behind one identifier and select stale state.
- Healthy discovery can take tens of seconds; the project uses a 90-second
  connection timeout. Short timeouts alone do not establish a broken ring.
- QRing binding can complicate Mac reconnection. If using QRing for stock health
  mode, explicitly test the unbind/forget/reconnect transition back to gestures.
- Use one owner of the BLE connection at a time. Do not compete with the live
  console, another probe, the phone app or another assistant.

## 4. Address mapping, layout and disassembly pitfalls

Unless marked **RAM** or **runtime**, addresses in the remaining analysis are
**file offsets** in the pinned 25 Hz image.

```text
file 0x450 <-> runtime 0x00826400
runtime = file + 0x00825FB0
file    = runtime - 0x00825FB0
```

Three anchors established the mapping: the entry at `0x450` loads a Thumb
pointer `0x00826665`; header words at `0x6C/0x70` contain `0x00826400`; and
56 of 80 odd flash literals landed on push/LR prologues at this base, versus
13 at the next best candidate in Fable's scan. The ROM-call matches provide a
further independent check. The old conclusion that the load base was unsolved
is superseded.

Thumb branch pointers have bit zero set. **Memory-read addresses do not**:
read the even code byte address, not the odd function pointer.

Reset-copy layout from the table near `0x768`:

| Flash source / file region | RAM destination | Length | Interpretation |
|---|---|---|---|
| `0x846A98` / `0x20AE8..0x21397` | `0x207C00` | `0x8B0` | Includes RAM-resident code, including deep-sleep store/restore |
| `0x847348` / `0x21398..0x2187B` | `0x2084B0` | `0x4E4` | Initialized data, **not** a second RAM-code block |
| BSS | `0x208994` | `0x5D80` | Zero-initialized state |

Fable's battery review corrected the second block's earlier misclassification.
Deep-sleep store/restore routines at file `0x20D70` and `0x20E30` map into
the first block, at RAM `0x207E88` and `0x207F48`.

Disassembly precautions:

- Start at the payload, not byte zero of the vendor container. Resynchronize
  across data islands instead of letting the first undecodable value terminate
  the analysis.
- A linear-sweep function map is a navigation aid, not proof that every decoded
  instruction or inferred function is real. Confirm decisive paths from callers,
  branches, data references and actual bytes.
- CRC lookup data around `0x1F380` produced false function/pointer references.
  A pool reference attributed to an enormous neighboring “function” can also be
  an artifact. Do not patch based on those names alone.
- In synthetic BL fixtures, a constant relative delta at different call sites
  produces different absolute targets. Construct fixtures with actual targets.
- The legacy `abs-original.py` looked up even branch targets directly in a table
  of odd Thumb symbols. Use `target | 1`; otherwise valid matches disappear.
- Never infer encryption from entropy or a checksum algorithm that fails to
  verify. This payload is plaintext Thumb code.

## 5. Container, image identity and protected bytes

| File offset | Field |
|---|---|
| `0x0000` | Magic bytes `E5 C3 BD 81` |
| `0x000C` | u32 LE sum of every byte from `0x50` to EOF |
| `0x0010` | Container firmware version string |
| `0x0030` | Hardware version string |
| `0x0050` | Nested Realtek header |
| `0x0052` | u16 LE flags; bit 7 is `not_ready` |
| `0x0058` | u32 payload length, file size minus `0x450` |
| `0x01C4` | 32-byte SHA-256 of payload `0x450..EOF` |
| `0x0450` | Application payload |

Build order: patch payload; update SHA-256; clear `not_ready`; compute the outer
body sum **last**, because it covers the digest and flags. `whip/fwbuild.py`
implements this. Valid checksums do not certify a semantically safe patch.

Keep these unchanged in the optical-off work:

- Raw timer immediate at `0x2248`: `#4`, measured 25 Hz.
- STK range setting at `0xBF0A`: `0x05`, ±4 g.
- **DFU reassembly timer at `0x7ED4`**. It resembles the raw timer idiom but
  changing it can destroy the recovery path. It is in `fwimage.DO_NOT_PATCH`.
- The reviewed DFU region `0x7E00..0x81FF` is byte-identical to the base in the
  optical-off candidates.

### Full-file hash ledger

| Artifact | SHA-256 | Status |
|---|---|---|
| `rt02cr-stock-3.12.02.bin` | `b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0` | Vendor health/recovery image, 138,016 bytes |
| `rt02cr-low-latency.bin` | `2ea1bb08826891604fb714a3820c859d77f52f8d22f1d9a870db10cd5fbffe34` | Upstream 50 Hz image |
| `rt02cr-33hz.bin` | `a3b160f8fc366fa1cb3b6d0048559c0ab2a4c1ecbcd5397e2bb08fdd8290b67a` | Earlier rate experiment |
| `rt02cr-25hz.bin` | `f13e63d3fdef3b10aa20fd4e0672077b66f60bb19c689ef64053840e4d35d3d9` | Strict V2 patch base, 137,540 bytes; no longer installed |
| Fable's `rt02cr-25hz-noled.bin` | `3c57b73e11357a9be1b2b7051ff78d99381b4aaec5cff0ed38568d78d7801e9f` | Superseded one-halfword experiment; not flashed |
| `rt02cr-25hz-optical-off-experimental.bin` | `f862e5bb1b65ff43d6133524d20fd82bcbc072bd8a1245a9927367993a213f27` | Preserved v1; superseded; not flashed |
| `rt02cr-25hz-optical-off-v2-experimental.bin` | `0d18a0fa860d58ab8f984b5f542f45dac105241f47bf1c2af41321eb0431e14c` | Installed 2026-09-22; identity and native 25 Hz stream/stop/idle checks passed; visual darkness pending |

The current top-level `firmware/SHA256SUMS` pins v2, not v1. The old v1 binary
is retained as history; the current builder does not reproduce it. Fable's
older `E2 E7` experiment is identified in its record only by hash prefix
`2e2045c1…`; do not invent the missing full hash or treat it as the `E5 E7` image.

DIS/version strings are shared by the 25 Hz base and optical-off candidates.
`flashing.detect_mode()` can identify the broad gesture family, **not** which
optical patch is installed. Keep a transfer hash and use code-site checks.

## 6. UART protocol and corrected commands

The UART command is 16 bytes: command, up to 14 data bytes, then the sum of
the previous 15 bytes modulo 256. Notifications use the same checksum framing.

| Characteristic | UUID |
|---|---|
| UART service | `6e40fff0-b5a3-f393-e0a9-e50e24dcca9e` |
| Host write | `6e400002-b5a3-f393-e0a9-e50e24dcca9e` |
| Notifications | `6e400003-b5a3-f393-e0a9-e50e24dcca9e` |
| DFU service | `de5bf728-d711-4e47-af26-65e3012a5dc7` |
| DFU notify / write | `de5bf729-d711-4e47-af26-65e3012a5dc7` / `de5bf72a-d711-4e47-af26-65e3012a5dc7` |

Full packets worth preserving (these are a record, not a request to transmit):

| Purpose | Packet hex | Important scope |
|---|---|---|
| Raw motion start | `a10400000000000000000000000000a5` | Sets raw mode 4, enables optical bit `0x800` on the base |
| Matching raw stop | `a10500000000000000000000000000a6` | Clears `0x800`, raw mode and producer timer |
| Other raw stop | `a10200000000000000000000000000a3` | Clears `0x40`, **not** `0x800`; also stops the producer |
| Optical-only diagnostic STOP | `ce02337b01000000000000000000007f` | Writes VC30F `0x7B = 0`, does not stop A1 |
| Temporary motion hold | `3b020103000000000000000000000041` | Volatile action mode 3; wakes STK and inhibits connected inactivity |
| Restore motion mode disabled | `3b02010000000000000000000000003e` | Restores tested original motion-control state |
| Corrected realtime HR stop | `690604000000000000000000000073` | Disables optical bit 1 and stops HR report timer |

**The host stop sequence is `A1 05`, then `A1 02`.** Both writes are attempted
even if one fails. This covers the raw-motion and other raw modes; it is not a
guarantee of darkness if another optical feature still owns a sensor bit.

**`69 01 04` is a START, not a stop.** At `0x50DC`, subcommand 1 reaches
`enable(1)` at `0x517E..0x5180` after restarting the HR reporting timer.
`69 06 04` reaches `disable(1)` at `0x5292..0x5294`, then stops the timer via
`0x525C`. `69 06 02` stops reporting only. The host quiet tuple and LED probe
have been corrected with regression tests. The two successful LED-off trials
did not use the mislabeled health command.

Legacy `6A 01 00 00` and `6A 03 00 00` probes were not established as effective
raw-optics controls. Do not infer that an absence of LED response proves the
health command path cannot drive optics: code shows that it can, and health
start paths have prerequisites and guards.

## 7. A1 dispatch, timer ownership and optical message flow

The verified path is:

```text
BLE dispatcher 0x564A -> 0x4B9C -> packet queue at RAM 0x209D48
    -> semaphore wake -> task 0x1316 -> packet dispatcher 0x6334
    -> A1 handler 0x20BC

disable(bits) 0xDC82 / enable(bits) 0xDC9C
    -> 8-byte hub message {u16 type=3, u16 subtype=2/1, u32 bits}
    -> queue at [RAM 0x208C9C + 8]
    -> task loop 0x1446 -> message switch 0x1400 -> 0xDCD0
    -> sensor_disable 0xF740 / sensor_enable 0xF68C
```

The A1 packet queue holds ten 16-byte entries, with u16 read/write indices.
The wake helper `0x1178` gives a semaphore at `[0x208C84 + 8]`; constant
`0x332` is not a message ID. Similarly, constants `0x18D` and `0x195` at the
optical-post callers are discarded by `0x149C` (`mov r1,r0`). The payload's
type/subtype, not those constants, routes the optical message.

The optical hub queue has 32 entries. Posts use zero wait and their return
values are ignored; a full queue can theoretically drop an enable/disable.
The normal disable-all then enable ordering is FIFO/asynchronous, not immediate
sensor work inside the BLE write. Diagnose after allowing the task to run.

Selected `0x20BC` cases:

| Parameter | Effect in the pinned base |
|---|---|
| `01` | Save stats, disable all, enable `0x40`, mode 1, producer start |
| `02` | Restore stats, disable `0x40`, mode 0, stop/delete producer |
| `03` | One synchronous producer report |
| `04` | Disable `0xFFFF`, enable `0x800`, mode 4, producer start |
| `05` | Disable `0x800`, mode 0, stop/delete producer |
| `06` | Other raw mode using `0x40`, mode 6, producer start |
| `07` | Conditional `0x40` raw mode/countdown; separate nominal 1000 ms timer setting |
| `08` | Disable `0x40`, stop timer and return counters |

The handler first checks charging. While charging, it replies `A1 FF`, clears
the mode bytes, and skips the cases; that branch does **not** stop the timer.
Do not send A1 while charging and assume its usual effect occurred.

Raw producer timer handle slot: **RAM `0x209CBC`**. Mode byte: **RAM
`0x209CAC`**, auxiliary mode byte at `0x209CAD`. `0x3D0C` creates/starts or
restarts the timer; `0x3D38` null-checks then stops/deletes it. The raw start
tail also performs one immediate report, not only subsequent timed reports.

The callback `0x1DFE` builds optical, acceleration and subtype-5 reports. The
upstream image NOPs optical/subtype-5 notification calls at `0x1E58`, `0x1EB2`
and `0x1F74`; it does not turn off the corresponding sensor. Acceleration is
obtained via `0xCBDA` and sent at `0x1F32` through the notify path `0x7C0C`.
Subtypes: `01` SpO2, `02` PPG, `03` acceleration, `05` a near-static value
whose full application meaning is not established here.

Several tempting “power” calls are **stubs**: `0x1475C`, `0x14754`, `0xD744`
and `0xD746` are `bx lr`. Do not attribute energy behavior to their arguments.

## 8. Optical ownership, start paths and health schedules

### State and ownership

| RAM location | Meaning established by the analysis |
|---|---|
| `0x20C018` | u16 sensor ownership mask |
| `0x20C01A` | Last HR/result byte in the state structure |
| `0x20C01B` | Probe/failure flag |
| `0x20C01C` | Optical state: 0 idle, 1 running, 2 valid, 3 failed |
| `0x20C01E` | u16 auxiliary state |
| `0x20C024` | Fallback result value |
| `0x20C008` | VC30F-absent flag from chip-ID probing |
| `0x208548` | Optical config: u16 rate at +0, mode at +2 |

Bits `0x40` and `0x800` are exclusive to the A1 raw handler. Other optical
features use bits including `1`, `2`, `0x10`, `0x20`, `0x80`, `0x100`,
`0x200`, `0x400`, `0x1000` and combined `0x1301`. Fable's early lists
misread `0x100` as `0xFF` and `sub_0441C`'s bit 1 as `0x38`.

In `sensor_enable` (`0xF68C`):

- From mask zero, probe the chip. Failure leaves the mask zero and marks
  failure; success clears the probe-failure flag.
- Requests involving `0xA0` select optical mode 1. Exact argument `0x40` or
  `0x800` selects mode 7. Other requests take other/default configuration.
- If an existing mask already contains `0x40`, a new enable returns directly:
  **it does not OR the new bits into the mask**.
- With mask `0x800`, later `0xA0`-class requests can reconfigure/start mode 1.
  This is why patching only the initial raw-mode start does not ensure darkness.
- The entry also cancels an active indicator pattern in the original code.

In `sensor_disable` (`0xF740`): clear the requested mask bits; if zero remains,
stop the VC30F and clear running state. If another owner remains, optical work
can continue. When an `0xA0` measurement ends while another non-`0xA0` bit
remains, the routine can STOP and then **restart mode 0**. The restart is not
conditional on the state being 2; only a state-byte update is conditional.

Thus `A1 02` after `A1 04` stopped reports while leaving optical owner `0x800`.
`A1 05` fixes that specific mismatch. It does not clear an unrelated bit 1
accidentally enabled by the old supposed HR-stop command or a scheduled feature.

### Driver start/stop and bypass paths

Normal start: `0xEFF8 -> 0x10C86 -> 0x10016 -> mode fn_a -> 0x122FE(1)`.
Chip ID and revision-byte checks apply (`0x25/0x27`, revision `0x10/0x30`).
`0x10C86` clears a `0x540`-byte state structure and selects a ten-entry mode
table at `0x1F5E4`. `0xEFF8` itself creates no timers.

`0x122FE` writes VC30F register `0x7B`:

| Operation | Written value |
|---|---|
| STOP | `0x00` |
| RUN | `0x5A` |
| RESET/configuration prelude | `0xA5` |

The normal full stop `0x10D12` writes `0xA5`, then `0x00`. Stopping an
already-stopped chip occurs in ordinary firmware paths, including boot. The
diagnostic experiment writes only `0x00`. This is the driver's idle command,
not a datasheet-backed claim that all optical circuitry is electrically off.
Reading `0x7B` returned zero even before optical STOP in a test, so it is not
a trustworthy running/status register.

Indicator path: `0x3B8C` / `0x3C16 -> 0x3A8E -> 0xF67A -> 0x110AE`.
It bypasses `sensor_enable` and normal mode selection, but uses the same RUN
helper. Boot, charger, find-ring (`BLE 0x50`) and low-battery behavior reach
indicator logic. Patterns can configure the chip at 100 ms steps. A mode-7-only
patch does not cover them. The indicator entry normally checks mask==0 via
`0xF792`; leaving the mask clear permits them to run.

The global v2 patch blocks both ordinary optical enable and RUN. It still
allows indicator configuration traffic, RESET writes and bounded health timers
that receive no optical data. No null-pointer crash path was found: relevant
driver calls check the object, mode entry and function pointers before use.
Not every BLE measurement timer was traced line by line; this is not a proof
of absence of all firmware failures.

### The five schedules, not one master health switch

For the **stock-based unified build**, use the separately executed
[current-settings map](UNIFIED_STOCK_SETTINGS.md): enable byte `0x208aad`, HR
interval `0x208aac`, operating mode `0x208c44`, time-set gate `0x208c46`.
Do not transplant the 25 Hz/V2-family RAM constants from the historical research
below into the pinned stock application. The settings reader is unattached and
does not establish physical resume or steps/sleep continuity.

The minute tick `0x1202`, called from `0x1316`, is gated by the time-set flag
at RAM `0x208C4A`. Schedule enables are bits 0–4 at RAM `0x208AB1`:

| Setting command | Bit | Scheduled path / optical mask |
|---|---|---|
| `0x16` (HR) | 0 | `0xE35C`, `0x10` |
| `0x2C` (SpO2) | 1 | `0xE0A4`, `0x80` |
| `0x36` | 2 | `0xE7F2`, `0x200` |
| `0x38` | 3 | `0xE988`, `0x100` |
| `0x3A` | 4 | `0xEBEE`, `0x1000` |

Different measurements are scheduled at interval/minute boundaries, including
minute 0, 30 and 32, with wear/charging/other guards. Exact wall-clock timing
depends on firmware state. `16 02 02 3C` clears **bit 0 only** and sets its
interval field; it is not a master optical disable. Earlier reads found
`0x16/0x2C/0x36/0x38` disabled; **`0x3A` was not read**. Unsupported
`0x37/0x39` replies do not settle `0x3A`.

The current `DISABLE_LOGGING_PACKETS` touches only HR and SpO2. It does not
disable all five schedules. Persistent settings were not changed during the
successful workaround or latest archive/refresh. For health-mode preservation,
do not casually issue blanket settings changes and assume a later flash will
restore their defaults.

### LED-current alternative: what was actually rejected

Mode 7 uses `fn_a = 0xFEC4`; slot 0/1 current literals are `0x7F` at
`0xFEE0` and `0xFF04`. Slot 2 current `0x0B` is stored at `0xFF26`; the
earlier `0xFEE6` citation was a reused literal load, also used for gain indices.
Current-register family includes `0x42/0x46/0x4A`; slot enables remain separate.

The earlier reason “AGC will turn the currents up again” was not supported for
mode 7. Its reachable slot-current adjustment decreases current, and the
bidirectional AGC path belongs to other modes. `0x11240` writes a per-variant
servo/config value at `0x53/0x56`, not the slot current previously claimed.

Zeroing two current literals was still incomplete: slot 2, optical sampling,
interrupts, shared-I2C traffic and indicator starts remain. The color of each
slot and whether slot 2 necessarily emits light are not established from code
alone. Mode 7 takes a default optical sample rate of 25 Hz despite the stored
config-rate value `0xC8`; do not read that field as a measured physical rate.

## 9. Accelerometer freshness, power state and calibration

Acceleration decode remains:

```python
x = int.from_bytes(payload[6:8], "big", signed=True)
y = int.from_bytes(payload[2:4], "big", signed=True)
z = int.from_bytes(payload[4:6], "big", signed=True)
# divide each by measured 8005 counts/g
```

Physical axes are project-labeled Y/Z/X in packet order. The STK's left-justified
internal format does not justify replacing the working signed-16-bit decode
with the faulty public 12-bit/sign-check implementation. Nominal ±4 g scaling
and measured ~8005 counts/g are compatible with the observed rail; the firmware
work does not change calibration or range. Vector magnitude may exceed 4 g
while individual axes clip near ±4.09 g.

| RAM / register | Active observation | Idle observation |
|---|---|---|
| `0x20BDC5`, FIFO-consumer-active byte | 1 | 0 |
| STK `0x0F` range | `05` | `05` |
| STK `0x10` bandwidth/config | `0F` | `0A` |
| STK `0x11` power/config | `74` | `7C` |
| STK `0x1A` interrupt mapping | `02` | `00` |
| RAM `0x20CC4E` inactivity counter | Can reach 125 under a hold | Reached 125 before idle |

Sample-state base `0x20BDC4`: +1 active/FIFO flag, +6 pending idle,
+8 u16 ring-buffer index and +0xC sample storage. IRQ/task state has another
base at `0x20BD94`. The driver timer handle is at **`0x20BDA4`**, i.e.
`0x20BD94 + 0x10` (or `0x20BDC4 - 0x20`), not sample-state +0x10.
`0xCB06` restarts it with argument 800; `0xCF6E` originally creates it with
argument 2000. These are timer arguments, not measured raw notification periods.
Do not write these addresses directly.

`0xCBDA` drains the FIFO through `0xC228` only while the active flag is set.
When it is clear, the routine repeats the cached newest sample, including
repeating it `n` times for requests of several samples. An optical-processing
reader is another consumer of acceleration, not its source. **Fresh acceleration
does not inherently require the optical front end.**

Inactivity processing `0xCD08` uses predicate `0x1D91C` and the count threshold
125 to request idle. Task `0xCA60` consumes the request via `0xC888`, which
configures low-power/motion-detect behavior. Startup itself sets an idle request
at `0xCA7C`. Therefore blocking only the quiet-counter predicate misses an
already-pending or startup-generated idle request.

Wake/request path `0xCB06` sets driver request/state flags and restarts the
driver timer; the driver wakes/reinitializes asynchronously. It should not be
described as an independently verified queue post. Any-motion interrupt paths
can also reinitialize the chip, with
reset/delay work. The first raw packets after a wake request can still be cached;
do not assume the BLE write synchronously woke the sensor.

The driver has a watchdog path after ten empty drains that can reset/reinitialize
the sensor. Shared-I2C mutex timeout (100 ms in the reviewed helper) is another
possible source of missed drains. These are code-level candidates for timing
artifacts, not proven explanations of every historical spike or packet gap.

Changing the range to ±8 g would alter counts/g, thresholds and recorded-data
comparability. It has not been done and is independent of the LED fix.

### Frozen stretches in the archived captures (audit 2026-09-22)

`python -m probe.freshness` scans every archived raw capture for runs of
byte-identical consecutive `A1 03` frames; `analyze.StreamStats` carries the
same numbers (`frozen_runs`, `frozen_s`, `longest_frozen_s`,
`distinct_fraction`) and `probe.report` prints them next to rate and loss. A
run at least `analyze.FROZEN_RUN_S` (1 s) long is the cached sample, not
stillness: a worn ring's noise toggles the low bits every few frames.

| Capture | Frames | Length | Frozen | Longest run | Runs >= 1 s |
|---|---|---|---|---|---|
| `negative_20260915_224235` (ambient hour) | 88,690 | 59 min | **39.3%** | 84 s | 114 |
| `negative_20260915_021616` (ambient hour) | 90,001 | 60 min | **28.4%** | 59 s | 149 |
| `gate_imm4_20260906_210533` (10 min gate) | 15,000 | 10 min | 1.1% | 6.9 s | 1 |
| `prompted_*` gesture sessions | -- | -- | 0-2.2% (one 8.5 s clip at 52%) | <= 4.5 s | 0-2 |
| `console_*` live sessions | -- | -- | 0-8.4% | <= 13 s | 0-4 |
| desk captures from the flashing days (`postflash_*`, `restore_check`, `nolog_after`) | -- | 30-120 s | 75-100% | whole capture | 1 |
| `battery_1790075332801725000` (10 min, wake/hold + optical STOP) | 15,130 | 10 min | 0.0% | 0.05 s | 0 |

Consequence: a frozen stretch cannot hold a gesture or produce a false
positive, so the ambient false-positive rates recorded in `CLAUDE.md` for
those two hours are bounded on 61-72% of the wear time they claim, and the
learning-curve and ambient-threshold numbers derived from them inherit that.
Prompted and live sessions are essentially clean, because the wearer moved.
Re-measure the ambient rate on captures that pass the freshness check (or on
captures taken under the wake/hold sequence, which held 0.0% over 10 minutes).

## 10. Temporary host workaround that passed on hardware

The successful sequence is **raw start -> explicit wake/hold -> optical-only
STOP -> observe -> raw stop -> restore hold state**. It is not `A1 04` followed
immediately by `A1 05` to produce the dark measurement interval.

`3B 02 01 03` routes through `0x5C44 -> 0xD3BC`; RAM `0x20BFC0` selects
motion action mode 3. It wakes via `0xC4FC` and, while connected, inhibits
inactivity through `0xD43E`. Its selected action target `0x3E7A` is a no-op in
this exact firmware. **Mode 1 is not interchangeable: it can emit host input.**
This command is volatile, not a recorded NVM-setting write. It also affects
motion-interrupt behavior, so it remains an experiment, not the capture default.

The setter forces sensitivity to 1. Before using it, `probe.ledcheck` requires
RAM `0x20BFC0..2` to be exactly `00 01 00`, because disabling the feature then
restores that exact state. The ordinary protocol read does not expose the third
byte; a fixed read-only RAM snapshot does. Cleanup observed that same three-byte
state after both successful tests.

The unchanged firmware can still restart optics through background health or
indicator paths. No hours-long or unexpected-disconnect acceptance test of this
workaround has passed. Its success motivates the firmware design but does not
validate it.

## 11. Six hardware experiments and their saved evidence

All six ran on the unchanged 25 Hz base. Complete JSONL copies are now in
`firmware/research/2026-09-22/captures/`, outside the git-ignored `data/` tree.
They are byte-identical to the original files listed in the archive manifest.
Visual statements below come from the user, not an LED detector in the log.

| Capture suffix | Experiment | Result |
|---|---|---|
| `1790069430476372000` | A1 start 12 s, matching stop 10 s | 300 motion packets, 159 distinct XYZ before stop; zero after. User saw flashing then darkness. |
| `1790069554509973000` | Stop only | No start sent, zero motion packets. Darkness alone is not tracking. |
| `1790069719668453000` | Optical STOP alone, 60 s | 1,501 packets near 25 Hz, only 63 distinct XYZ. Last change 2.479 s after STOP; ~57.5 s frozen. |
| `1790070844062449000` | Optical STOP with sensor/RAM snapshots | 500 packets in 20 s, final ~18.27 s frozen; STK changed from active to idle configuration. A 3.55 s frozen baseline run occurred before STOP too. |
| `1790071705479474000` | Wake/hold + optical STOP, ~60.3 s | 1,509 packets, 24.996 Hz, 1,483 distinct XYZ, no consecutive identical samples. User confirmed LEDs stayed dark while moving. |
| `1790072161023025000` | New connection, same sequence, ~120.3 s | 3,008 packets, 25.0018 Hz, 3,007 distinct XYZ, max identical run 30.2 ms, max gap 76.4 ms. User again confirmed darkness during movement. |

Additional details that prevent misleading interpretations:

- Trial 3's baseline had 199 packets/8 s and 197 distinct XYZ; its repeated
  frozen XYZ bytes were `e0 4c fe ec f9 f1`. “Always dark” did not establish an
  exact visual transition time.
- Trial 4 proved active-to-idle state change, **not that optical STOP caused it**.
  The unchanged baseline also froze before fresh values resumed.
- Trial 5 began with 208 identical raw packets and active flag 0 before the
  explicit hold. After it, active registers/flag persisted even at counter 125.
- Trial 6 included substantial motion after the initial transient. The middle
  two 30-second blocks reached vector magnitudes 6.88 g and 6.05 g; some axes
  clipped. The final quieter block still had 750 distinct values/750 samples.
- In trials 5 and 6, `A1 05` was sent **after** the dark tracking interval.
  Cleanup then sent `A1 02` and disabled motion mode; state read back `00 01 00`.
- Trial 6 saw no acceleration more than two seconds after stop. Normal idle
  completion after disconnect was not directly established by those trials.
- Battery readings across the work moved from 99% to 96%; the brief, unequal
  workloads do not establish an optical-off drain slope or runtime benefit.
- No live gesture-classifier acceptance test was run on the firmware candidate.
  Motion-responsive raw packets are necessary, not sufficient, for that claim.

## 12. Power, disconnect and charging

Historical estimates: 50 Hz ~1.0%/min (~1.7 h), 33 Hz ~0.27%/min (~6.3 h),
25 Hz ~0.30%/min (~5.5 h). Those are earlier project observations, not a
matched fresh-data comparison with optical-off operation. Old sessions may
have included cached/idle acceleration. “LEDs dominate the remaining drain”
and “six hours is the ceiling” are hypotheses, not settled power measurements.

The completed 2026-09-22 host-workaround battery repeat measured 92% to 90% over
600.0065 seconds between battery replies (~0.20 percentage points/minute), with
freshness gates passing and the accelerometer remaining active. This was on the
original image, not v2. The difference from historical 0.30/min is suggestive but
not a matched optical-on/off experiment; the one-point gauge resolution and short
window prevent a reliable runtime claim. Details and archived logs are in
[BATTERY_TESTS.md](BATTERY_TESTS.md).

The instruction passes `immediate * 8` ms to a timer helper; observed notification
periods follow `immediate * 10` ms. Keep the empirically established rate, and
do not claim to have explained the 25% difference. Lower loss at 25 Hz than
33/50 Hz is measured; notification pressure and motion-sensitive work are
possible contributors, not separately measured current consumers.

**Raw mode 4 vetoes deep low-power sleep (DLPS)** at `0xA54E -> 0x1DF6`.
The base's disconnect path clears connected state RAM `0x209E09` but can leave
raw mode 4 and its timer alive. Callback work continues; `0x7C0C` drops the
notify while disconnected. Releasing the STK idle hold alone does not remove
this MCU sleep veto. V2 explicitly clears mode 4 and stops its producer on
disconnect. This removes a known code-level obstacle; actual deep-sleep entry
and resulting current still need measurement.

Connected raw tracking still costs MCU, BLE, accelerometer and I2C work even with
optics stopped. The reviewed connection-parameter request path is stubbed, so
do not assume a patched raw rate or an old call adjusts the link as desired.

Charging has separate paths:

- A1 handler refuses commands and clears its mode bytes, without deleting the
  timer in that early branch.
- The producer's charging branch clears optical bit `0x40` and stops its timer;
  by itself it does not clear `0x800`.
- Main-loop charger handler `0x33AC -> 0xE3B6 -> 0xDC82(0xFFFF)` is the
  disable-all path explaining why charger taps clear stuck optics. It also
  updates failure/state bytes and may run charger indicators.

This reconciles the observed charger remedy without pretending A1 works while
charging. With v2 the ordinary charging **light** is intentionally suppressed;
charging operation itself has not been hardware-validated on that image.

## 13. Patch history and exact current design

### Rejected / superseded candidates

1. Fable's `0xF710: 51 48 -> E2 E7`, branch to `0xF6D8`: skipped the initial
   raw optical start but still ORed the raw bit into the ownership mask. Other
   health requests could reconfigure/start optics and leave them running.
2. Revised `E5 E7`, branch to `0xF6DE`: returns without recording that raw
   owner. This fixes the above mask problem but permits ordinary background
   health and indicator starts, and does not stop the accelerometer idling.
3. First multi-site image, v1 (`f862…`): global optical disable, explicit STK
   wake and connected/raw-only idle guard. It released STK idle on disconnect
   but left the producer timer/raw-mode sleep veto; v2 supersedes it.

### V2: seven edit ranges, 81 changed payload bytes

The original and replacement bytes for every range, their runtime addresses
and all fingerprint reads are in
[v2-patch-manifest.json](../firmware/research/2026-09-22/v2-patch-manifest.json).

| File offset | Replacement / intent |
|---|---|
| `0xF68C` | `70 47` (`bx lr`) before the sensor-enable prologue; reject optical enables globally |
| `0xF690` | 36-byte helper/literals in the now-unreachable original body; connected raw-mode idle guard |
| `0xCAD2` | `02 f0 dd fd` (`bl 0xF690`) instead of original load/compare of pending idle |
| `0x21DC` | `04 20 38 70 0a f0 91 fc`: store raw mode 4 before requesting wake via `0xCB06` |
| `0x1231A` | `00 20` instead of `5a 20`: ordinary VC30F RUN becomes STOP |
| `0x691E` | `08 f0 c9 fe`: route original disconnect cleanup call through `0xF6B4` |
| `0xF6B4` | 32-byte disconnect wrapper and literal, retaining original cleanup and clearing/stopping raw mode 4 |

Idle guard bytes:

```text
0648 0078 0428 05d1 0548 0078 0228 01d1
0020 7047 a079 0028 7047 00bf ac9c2000 099e2000
```

Meaning: if RAM raw mode is 4 **and** BLE state is 2, return zero with Z set,
so the caller takes its ordinary FIFO-drain path instead of idling. Otherwise
execute the original `ldrb r0,[r4,#6]; cmp r0,#0` and return with those flags.
The pending request is retained, so stop/disconnect restores normal handling.
The caller saved LR, r4 is the driver's state pointer, and only r0/flags change.

Disconnect wrapper bytes:

```text
10b5 f7f7c4fc 054c 2078 0428 05d1 0020 2070
2046 1030 f4f735fb 10bd ac9c2000
```

Meaning: push r4/LR (8 bytes); call the original `0x7042` cleanup exactly once;
load mode pointer `0x209CAC`; for mode 4 only clear it, form timer slot
`0x209CBC`, call the existing null-safe stop/delete helper `0x3D38`; restore
r4/PC. The caller overwrites r0/flags afterward. Non-mode-4 behavior remains
the original disconnect behavior. A new connection requires `A1 04` to start
tracking again. Tests cover all 256 mode-byte values and null/live timers.

The reclaimed region was checked for incoming branches and absolute pointers;
the normal external optical-enable caller enters at `0xF68C`, which now returns.
Do not assume unused-looking bytes are free space in another image. The builder
pins the entire base hash, checks surrounding instruction signatures, applies a
byte-change allowlist, regenerates container fields and rejects unknown inputs.

V2 side effects and boundaries:

- Heart rate, blood oxygen and optical-derived health functionality cannot be
  promised; the ordinary optical measurement path is deliberately disabled.
- Boot, charging, find-ring and low-battery optical indications are disabled.
- Steps, temperature, sleep and every other non-identical health feature have
  **not** been validated on this build; do not call it a normal health image.
- Diagnostic `CE 02` can bypass the RUN helper and write the I2C register directly.
  This is suppression of ordinary firmware paths, not a hardware interlock.
- Indicator I2C reconfiguration, RESET transients and health timeout behavior
  remain runtime questions.
- Range, rate and DFU remain unchanged. This does not make failed boot or loss
  of radio recovery impossible.

## 14. Diagnostics and post-flash identity safeguards

`CD 01` reads memory; the fixed request layout is command, operation `01`,
length, four-byte big-endian address, padding, checksum. Data begins at reply
byte 1. **There is no address, length or request ID echoed in the reply.**
`CE 01`/`CE 02` sensor diagnostics likewise lack sufficient request identity.

Therefore send one request at a time, reject an already queued/unexpected reply,
validate framing/checksum, and abort the entire diagnostic sequence on timeout
or invalid response. Do not retry on the same connection: a late reply can be
mistaken for another address and create false evidence. The identity probe marks
the session poisoned on such failure.

Fixed sensor reads include STK ID `0x00`, output `0x02..0x07`, range/bandwidth/
power `0x0F..0x11`, FIFO status `0x0C`, mapping `0x1A`, and VC30F `0x7B`.
**Do not read STK FIFO data register `0x3F` for a diagnostic snapshot**: consuming
the FIFO changes the stream being measured. Avoid generic CE/C7/CD writes in
normal tracking; the permanent candidate needs none of the workaround writes.

The identity fingerprint uses **22 serial reads / 244 bytes**, max 14 bytes per
read, covering these file ranges (start + length):

```text
raw start           0x21D6 + 20
raw period          0x2244 + 16
disconnect hook     0x6918 + 24
protected DFU       0x7ED0 + 20
accel range         0xBF04 + 16
idle request        0xCAD0 + 20
optical/guard/body  0xF68A + 80
optical control     0x122FE + 48
```

Classification is `original25Hz`, `optical_off_candidate`, or `mixed_or_unknown`.
V1 is deliberately unknown/rejected. This samples all reviewed changes and
neighbors; it is **not a full-image hash readback**. Flash-address readability
passed on the original 25 Hz ring during the 2026-09-22 battery-test preflight:
all 22 reads / 244 bytes matched `original25Hz` in
`data/batterycheck/battery_1790075215600058000.jsonl`. After the flash, all 22
reads matched V2 in `data/ledcheck/firmware_validation_1790114476907550000.jsonl`.
A failed diagnostic is a
blocker to trusting this identification method, not permission to guess from
the version string or LED behavior alone.

`probe.validate_optical_off --check-only` only performs identity-related reads
and device/battery checks; no A1 start/stop, CE STOP, 3B hold or firmware write.
The active test refuses the base/unknown firmware before starting a stream.
It requires the candidate, uses `A1 04` alone, then `A1 05`/`A1 02`, and
opens a new connection for each cycle. Preflight also requires the expected
hardware/DIS/name, adequate battery and no charger connection.

The active sample gate excludes two seconds of asynchronous wake time, requires
24–26 Hz, no gap above 250 ms, no identical run above 500 ms, valid packets,
at least half distinct XYZ (minimum ten), and at least 0.25 g span on an axis.
Those are probe acceptance thresholds, not measured firmware guarantees. They
reject obvious stale/two-value streams, not every possible replay. Independent
state requires raw mode 4, connected state 2 and active FIFO consumer. After
stop it checks no late A1 acceleration beyond two seconds, raw mode 0 and an
observed idle flag. Continued user motion can defer idle; that outcome needs
interpretation, not an automatic diagnosis of a firmware defect.

## 15. Host-side changes and limits of existing tooling

- `whip/protocol.py`: correct matching raw stop (`05`), retain `02` as second
  cleanup, correct HR stop to `69 06 04`, qualify logging-disable scope.
- `whip/capture.py`: cleanup covers setup failure and cancellation; both stop
  writes are attempted independently; the flusher is cancelled/awaited and
  capture files are closed. A disconnected radio still cannot receive cleanup.
- `probe.ledcheck`: experimental optical STOP, fixed non-consuming diagnostics,
  optional exact-state-preflighted motion hold, durable phases and cleanup.
- `whip/fwoptical.py` / `probe.build_optical_off`: strict offline builder; no
  BLE connection or flashing; existing output files are refused.
- `whip/fwidentity.py` / `probe.validate_optical_off`: exact candidate pin,
  fixed code-site reads and freshness/state tests without the host workaround.
- `firmware/fetch.sh`: rebuilds current pinned images, including v2, without
  silently overwriting an existing candidate. It is **not** a read-only command;
  do not run it merely to inspect provenance.
- `FLASH_TARGETS` still maps the console's **gesture** choice to the original
  `rt02cr-25hz.bin`, and **stock** to the vendor image. The LED-off candidate
  has not been promoted to a normal UI target.
- The standard capture path does not automatically apply the temporary 3B/CE
  workaround. Legacy `quiet_optical` is not an equivalent LED-off mode.

## 16. Review and test record: keep it tied to exact artifacts

Fable session: `fce5503d-9fbc-4aa8-93c0-bd04600def2d`; workflow:
`wf_e507bed5-541`. Nine verifier results plus critic `a5017e9fe202cd0b7` were
available. Eleven agents were started (duplicate work included); only ten
result records exist. Its last visible main-session message was the usage-limit
notice at `2026-09-22T10:24:33.798Z`, not a final synthesis after the critic.
This was read from saved outputs, not a native UI `/import`, hidden reasoning
or a background memory synchronization.

Critic verdict: **proceed_with_changes**, not “approved to flash.” The verifiers
primarily reviewed the one-halfword experiment. The critic separately decoded
v1 and found its patch mechanics sound, while flagging remaining gaps. V2's
disconnect wrapper was reviewed separately in this work; do not count the nine
older verifiers as nine reviews of v2.

The archived structured results retain each claim, evidence, correction, risk
and verdict. Some individual reviewers repeated earlier mistakes; the corrected
synthesis in this document and final critic must accompany the raw records.

Latest focused test result before this documentation save: **179 passed**:

```sh
.venv/bin/python -m pytest -q tests/test_protocol.py tests/test_capture_cleanup.py \
  tests/test_ledcheck.py tests/test_fwoptical.py tests/test_fwidentity.py \
  tests/test_validate_optical_off.py tests/test_fwbuild.py tests/test_fwimage.py
```

These include instruction semantics, builder guards, identity corruption/old-image
rejection, diagnostic timeout correlation, failed-start cleanup, fresh/frozen
sample checks, and candidate tests that reject CE/3B workaround use. A prior
full-suite run had 464 passing and one unrelated existing cut-margin failure
in `tests/test_script.py`. Sandbox socket denials were separately resolved for
server tests outside the sandbox; do not reclassify them as firmware failures.
The 179-test run is not a new full-suite pass.

Pre-push checkpoint, 2026-09-22: the full `.venv/bin/python -m pytest -q`
run outside the socket-restricted sandbox produced **560 passed, 1 failed**.
The remaining failure is the previously observed
`tests/test_script.py::test_the_cut_follows_the_gestures_not_the_widest_gaps`:
the selected cut matches the fixture but its margin is ~0.00909, below the
asserted `MARGIN_OK` of 1.0. Its existing algorithm and assertion were preserved;
this checkpoint is not an all-green full-suite result. All firmware/battery
tests passed. The merged iOS app and its protocol test target compiled for the
simulator, without launching the app or running its XCTest suite. All 20 research
archive checksums passed, including the two added battery captures.

V2's offline DFU dry run passed: 137,540 bytes, 135 chunks and 672 BLE writes,
exact reassembly, current catalogue hash recognized, no connection. All five
current archive hashes, shell syntax and diff whitespace checks passed.

## 17. DFU safety and the proposed stock/gesture balance

DFU frames: `BC | cmd | len_lo | len_hi | crc16_lo | crc16_hi | payload`.
CRC-16/Modbus covers payload. Commands: START `01`, INIT `02`, DATA `03`,
CHECK `04`, END `05`; chunks 1024 bytes, BLE segments 240 bytes. The existing
gesture/custom activation path uses init type **4**; the existing stock-restore
target uses init type **1**. Do not casually substitute one for the other.

The library validates pinned hashes and exact hardware identity, applies
catalogue compatibility constraints where present, and reads battery before
transfer (current library floor 40%, above the protocol's recorded 20%). It
uses write-with-response, one DFU notification subscription and acknowledgments
between frames. The server also blocks flashing while streaming and requires
a per-connection dry run and typed confirmation. Keep all those gates.

CHECK confirms receipt/validation of the transfer. END commonly has no reply
because the ring reboots. Lack of END acknowledgment alone is not failed flashing,
but neither is CHECK proof that the application booted. The current library
treats `FlashAborted` at END as expected silence; inspect the actual log and
perform post-flash identification instead of inferring successful runtime.

Stock/gesture separation is plausible because both images and a gated switching
path already exist. It is not a free software toggle:

| Mode candidate | Intended benefit | Cost / unsettled issue |
|---|---|---|
| Stock vendor image | Normal vendor optical health behavior and app integration | Raw motion is about 1 Hz; not the trained 25 Hz gesture stream; health restoration after a new round trip must be checked |
| Original 25 Hz image | Already used for gesture captures; rollback baseline | Raw optical activity and cached-sample idle behavior remain |
| Optical-off v2 gesture image | Dedicated dark, fresh-acceleration tracking design | Hardware unvalidated; global optical health and indicators unavailable |
| Future single dual-mode image | Could avoid reflashing for every transition | Not built; needs safe optical ownership, schedules, data/timer cleanup and full validation |

For the likely two-image direction, the next research questions are:

1. Does stock restoration recover actual health measurements and app syncing,
   not merely a stock-looking version string?
2. Which settings, timestamps, health history and bonds survive each direction
   of flashing? Which must be synced/exported or restored first? **Unknown.**
3. Does a stock -> gesture -> stock round trip work repeatedly without stale
   bonds, leftover settings, failed activation or unexpected charging behavior?
4. Is switching occasional or frequent enough that transfer time, user friction,
   interruption risk and flash endurance matter? We have no measured safe cycle
   count or chip-specific endurance limit; do not invent one.
5. Which image/identity checks should the UI show? A generic “gesture” DIS match
   must not imply that the optical-off candidate is installed or validated.
6. What health features matter to the user (HR, SpO2, sleep, steps, etc.)? Test
   those explicitly; neither dark LEDs nor plausible app numbers validate them.

Keep the pinned stock image and original 25 Hz image ready. An archived rollback
image only helps if the ring still boots into or accepts DFU. **Recovery is not
guaranteed if the radio/DFU path becomes inaccessible.** No automated flash loop,
default-target promotion or new health-setting changes are authorized by this
documentation request.

## 18. Resume checklist and unresolved questions

Before any newly approved flash:

1. Read this handoff and the exact pinned manifest, not only old LED notes.
2. Check the worktree for overlapping work; preserve unrelated corpus/model/iOS
   changes. Rebuild only to a new output and require exact expected bytes.
3. Re-run focused tests, container verification and offline DFU framing for the
   exact proposed artifact. Keep the known-good images available.
4. Establish reliable connection/adequate charge and verify read-only code
   fingerprinting against the current base. This remains the next hardware
   check; it has not happened yet.
5. Agree on the health/gesture policy and obtain explicit flash approval for the
   chosen image. Prior “yes, stayed dark” observations were **not** flash approval.

After an approved candidate installation, only then can it be validated:

- Verify the installed code sites and record the transfer hash/version/hardware.
- Confirm dark LEDs with human observation while A1-only motion/rest data stays
  fresh; extend beyond the previous two-minute workaround trial (at least a
  several-minute alternating test, then background schedule boundaries).
- Repeat start/stop with actual idle observations, and test abrupt disconnect
  while streaming—not just orderly stop then reconnect. Check raw mode/timer
  cleanup and reconnect behavior without silently masking them with host stops.
- Exercise actual gestures with the deployed classifier, not only changing XYZ.
- Test boot, charging insertion/removal and health/indicator side effects. Do not
  mistake intentionally absent charging lights for proof of failed charging.
- Measure battery against a matched fresh-data workload, over long enough
  intervals to overcome percent quantization; include nontracking/disconnected
  behavior. The review suggested a multi-hour comparison. No savings number is
  established yet.
- If pursuing two images, perform a separately approved round trip to stock and
  verify the requested health functions, retained settings/data and pairing.

Still unknown: actual v2 boot and radio stability, long-term darkness, RESET
transients, remaining optical configuration power, actual DLPS entry, battery
gain, health/data retention across switching, safe switching frequency and
complete behavior of every BLE health timer. None is settled by a checksum,
a passing unit test, or Fable's willingness to proceed with changes.

## 19. Where to continue

- [LED_FIX.md](LED_FIX.md): chronological hardware observations and immediate
  patch history.
- [Research archive README](../firmware/research/2026-09-22/README.md): original
  outputs, code-map tooling, capture copies, provenance and integrity checks.
- [Firmware provenance](../firmware/PROVENANCE.md): vendor/upstream origins and
  current/superseded binaries.
- [Builder](../whip/fwoptical.py), [identity module](../whip/fwidentity.py),
  [hardware probe](../probe/validate_optical_off.py),
  [host experiment](../probe/ledcheck.py), [flashing gates](../whip/flashing.py).

All work saved here is local repository content. This task did not flash the
ring, transmit BLE commands, change health settings, commit, push or create an
off-machine backup.

Saving-time checks: all six capture copies compare byte-for-byte to their
originals; the ten exported workflow result objects compare exactly to the
source journal; all 18 archive-manifest entries verify; the 14 local links in
this document and archive README resolve; and the same 179 focused tests pass
again. The preserved mapping tool reproduces 79/79 ROM-symbol matches. These
checks protect the handoff's integrity, not the untested firmware's behavior.
