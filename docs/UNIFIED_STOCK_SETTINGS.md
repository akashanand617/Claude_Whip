# Current stock settings and resume boundaries

2026-09-23. Off-ring implementation. Health remains the unified boot/default;
Gesture is opt-in. Installed V2 optical-off is unchanged. No ring access, sensor
start, deployment, firmware-file patch or flash. This is a read primitive and
selected original-code execution, **not a completed physical resume binding**.

## Implemented: exact-stock current-controls read

`firmware/unified/stock_schedule_settings.{c,h}` adds `wss_read_controls`.
It reads four volatile SRAM bytes in a bounded interrupt-masked section and
restores the caller's original PRIMASK. The return value packs them in the order
below, least-significant byte first. There is no caller-owned output buffer,
static state, allocator, ROM/RTOS call, settings/clock/history write or retry.

| Packed byte | Pinned stock RAM | Meaning witnessed in stock instructions |
|---|---|---|
| 0 | `0x208aac` | HR interval used by minute-dispatch eligibility |
| 1 | `0x208aad` | All eight control bits; bits 0–4 enable the five reviewed jobs |
| 2 | `0x208c44` | Operating mode; normal minute-dispatch branch requires 3 |
| 3 | `0x208c46` | Time-set gate; minute-dispatch branch requires exactly 1 |

The source image is stock SHA-256
`b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0`.
**Do not use the installed 25 Hz/V2 family's `0x208ab1` or `0x208c4a` fields
in this stock binding.** Protocol commands are unchanged; the internal map is
image-specific. `whip/protocol.py` now qualifies its older address comments.

The primitive preserves unknown high bits instead of masking their changes out
of a future comparison. Invalid/unusual raw bytes, including interval zero, are
reported as stored, not replaced by defaults. It does not claim that settings
are valid, a job is due, or Health can resume. Nor is this packed value a
monotonic revision or ABA detector: changing settings and changing them back
returns the original value.

The interrupt mask makes these four loads indivisible relative to normal
maskable writers, not to NMI/debug/DMA/reset writers. Exact image/map and
initialization are caller obligations. Final check and commit still need a
proven shared serialization domain. Wear, charging, current time, other Health
settings, active jobs and sensor state are not contained in these four bytes.
No `wh_resume_ready` or physical shutdown receipt is manufactured from the read.

The real-address component link adds **48 bytes**, taking components from 9224
to **9272/9520 configured bytes**, with **248 remaining**. The function's local
ARM frame is eight bytes. Dispatcher/frame/fence remains 796 bytes. No writable
static section or allocation was added; none of this approves RAM/stack
ownership, complete integration fit or reuse of the indicator body.

## Unchanged stock execution replaces prior boolean settings fixtures

`whip/fwhealth_schedule.py` extends only the offline harness. It executes the
five real bit getters/setters, their original job start paths, and minute
dispatcher `0x1202`. It does not modify stock code or permit arbitrary firmware.

| Job | Bit | Getter | Setter | Original start |
|---|---:|---:|---:|---:|
| HR | 0 | `0x1726` | `0x1732` | `0xe420` |
| SpO2 | 1 | `0x176a` | `0x174e` | `0xe168` |
| owner `0x200` | 2 | `0x1776` | `0x1782` | `0xe8c2` |
| owner `0x100` | 3 | `0x1880` | `0x188c` | `0xea58` |
| owner `0x1000` | 4 | `0x189e` | `0x18aa` | `0xecbe` |

Compiled ARM reads are checked against actual stock getters for all 256 control
bytes. Each real setter is exercised with all 256 prior bytes and both valid
boolean inputs: only its own bit changes, and the other firmware's address
remains untouched. The reader's exact four data accesses must occur while
PRIMASK is set; caller mask, registers, stack and the whole fixture page are
preserved. Every one of the four fields is re-read after mutation; no caching.

Minute-dispatch tests execute all 32 enable combinations across 60 minute slots
for intervals 0, 1, 5, 60 and 255. At the tested nonzero scheduler-second values:
HR follows the configured interval; SpO2 is selected at minute 32, owner `0x100`
at minute 0, and owners `0x200/0x1000` at minutes 0 and 30. The exact byte gates,
wear and charging guards remain effective. Disabled old HR does not reappear
at its next boundary; newly enabled SpO2 is selected at its own boundary.
The real division-zero helper returns quotient zero and the input remainder;
the tests do not invent a default interval or call zero a valid configuration.

Clock reconciliation, timestamp/calendar conversion, wear/charge predicates,
queue/timer actions and non-optical minute/hour/day work are **explicit
substitutes**. Actual elapsed/pending counter loads/stores execute, but wall-clock
timing, RTOS ordering, physical starts, history and step/sleep algorithms do not.

## Resume must preserve the rest of the scheduler

The unchanged dispatcher consumes pending seconds at `0x209cac` and advances
the scheduler counter at `0x208be4`. Calling it again without pending time does
not rearm measurements. On a large delayed increment ending off a minute
boundary, it consumes the increment without replaying every crossed due minute.
Tests exercise those counter changes directly.

It also invokes hourly/minute bookkeeping, including `0xe4de`, `0x373e`,
`0xb53e` and `0x11c0`. Their effects are deliberately not modeled or erased.
**Do not pause the whole minute handler or invoke it as a resume/capability
probe.** Preserve its clock/non-optical work and bind optical admissions
separately. This is not proof that the future hooks already preserve steps/sleep.
The handling of optical work missed during Gesture still needs an explicit
fresh-job policy and coverage records; do not replay time to synthesize catch-up.

## Fresh start is not old-job continuation

Original job-start instructions directly change working state before/after
posting their optical request. The following are CPU stores witnessed with
mocked clock/queue/timer boundaries, not claims about downstream hardware/NVM:

| Job | Direct working-state writes |
|---|---|
| HR | Clears words `0x20c0cc/0x20c0d0`, then writes current fixture time to `0x20c0cc`; active byte `0x20c0c0=1`, counter `0x20c0c1=0` |
| SpO2 | Clears bytes `0x20c0a8/0x20c0a9`; writes time at `0x20c0b0` |
| owner `0x200` | Clears bytes `0x20c0e4/0x20c0e6`; sets `0x20c0fa=30` |
| owner `0x100` | Clears bytes `0x20c0fb/0x20c0f9`; sets `0x20c0fa=30` |
| owner `0x1000` | Clears bytes `0x20c100/0x20c102` |

The shared `0x20c0fa` parameter rules out assuming those two jobs have fully
independent private state. These routines are not preservation-safe generic
timer rearm functions. Old jobs/results must already be cancelled/fenced, and
any resumed work must be a fresh job selected using current settings and all
eligibility guards. No blind old-owner-mask or old-timer replay was implemented.

## Remaining release gates

Later [timer-rearm evidence and fixed code read](UNIFIED_TIMER_RESUME_READ.md)
and [support capture](UNIFIED_SUPPORT_READ.md), followed by the preflighted
[create-hook plan](UNIFIED_CREATE_HOOK_READ.md) and off-ring
[status audit](UNIFIED_STATUS_NOTIFICATIONS.md), bring the guarded suite to
2734 passing tests, 239 checked hashes, including the later successful create-hook
capture replay, 121 captured-hook/comparator execution cases and 32
[optical-event/commit cases](UNIFIED_OPTICAL_DISPATCH.md). The subsequent
[HR commit implementation](UNIFIED_HR_RESULT_COMMIT.md) adds 60 actual-ARM
cases and 80 linked bytes: 9352/9520 configured bytes, 168 remaining. It changes
both ELFs, not the settings primitive or stock bytes, and remains unattached.
Original producer identity/provenance and complete resume remain unproved.
The later [optical read audit](UNIFIED_OPTICAL_ACQUISITION.md) adds 29 cases
without changing C or either ELF. It rules out top-level zero and parsed/read
flags as measured-source receipts after failed or cached-only reads.
The subsequently coordinated
180-transaction read, archive replay and captured creation/default execution
passed; the current execution-build manifest includes the new artifacts.
The settings-build record below remains
its own historical snapshot. Physical resume remains unverified. The later
requested create-hook attempt connected but aborted during prerequisites on
`0x73` traffic, before any new window. Disconnect was verified; no retry or
success capture occurred in that first attempt. A separate newly requested retry
then completed 359 transactions, repeated equality/postchecks and verified
disconnect. Selected hook/comparator paths now execute off-ring; empty-handle
creation failure reaches unread `0x111a6`. Neither those synthetic-state tests
nor capture/replay establish physical creation/resume or ownership.

Full guarded build: `firmware/unified/build-20260923-stock-settings-v1/`,
**1949 tests passed in 157.48 seconds**, zero skips/failures/errors/xfails.
All **206 hashes** verified: 136 inputs, 67 artifacts and three reports. The
42 new settings/scheduler cases are included in that total. Both compilation/
link layouts reproduce identically. Manifest SHA-256:
`fd45710dc6dfff56dbb87e38e1fc7e92a8da925a987db8f1b357619437687c34`.
Test ELF SHA-256:
`2e66a8133a753103ff412dd959d42d7e39bb177fc2c2120aaa344b9426a67b7e`.
Actual-address ELF SHA-256:
`2c75d78867394ac4c9beb9ca18b3e4f5dca58c701884b64b92a65ac5720013e6`.
No Swift source changes, new simulator or separate legacy-regression run,
commit or push. The protocol source change only qualifies address comments.

The primitive is unattached. Actual producer/result inventory, admissions and
hub/IRQ/RUN/publication serialization, completed cancellation and physical
STOP, and a current-settings/fresh-job resume transaction remain required.
Memory/stack ownership, complete linked placement and usable recovery are not
verified. Physical FIFO timing/completion/overflow, finalized-model replay,
controlled steps and overnight sleep continuity still require measurements.
All production/construction gates stay closed; fresh coordination and a bounded
plan precede any further ring access.
