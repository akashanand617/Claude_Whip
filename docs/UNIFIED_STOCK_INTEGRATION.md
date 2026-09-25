# Stock-address integration work — 2026-09-23

Active implementation, not an installable firmware. Health remains the required
boot/default; Gesture is temporary. Installed firmware is unchanged V2 optical-
off. The user explicitly asked to keep implementing, not stop at diagnostics.

Current milestone and finite release gates:
[integrated switching and whole-image budget](UNIFIED_READINESS.md).
That runner joins actual-address C and selected stock paths in one ARM state;
its remaining physical/coordinator fixtures are explicitly listed.

Earlier consolidated device evidence: an explicitly requested, newly coordinated retry of the
fixed ROM plan **completed all 974 CD01 transactions**, reading all **6076 bytes
twice with equal results**, matching postchecks and verified disconnect. No
sensor or flash command. Evidence is archived under
`firmware/research/2026-09-23/rom-integration/`; see the successful-retry section
below. The preceding abort and passive session remain historical records.

The newer [checked-health cancellation](UNIFIED_HEALTH_CANCELLATION.md) and
[lossless queue compaction](UNIFIED_RESOURCE_BUDGET.md) provide an unattached
twelve-slot STOP binding and smaller state with unchanged 32-sample capacity:
**3004 passing guarded tests**, 265 checked source/artifact/report hashes, 9468
component bytes with 52 configured bytes remaining. Source storage keeps all
32 input frames and exact timestamps: receipt 288, temporary delivery 64,
observed observation nested stack 244 bytes. The separate
[Health commit candidate](UNIFIED_HEALTH_COMMIT.md) remains excluded from both
main ELFs because the full addition fails the unchanged capacity limit.
Dispatcher/frame/fence totals 796 RAM bytes,
still unallocated and unapproved. That result
supersedes the counts/sizes below, not the remaining safety gates.
The latest [heap-free I/O integration](UNIFIED_OPTICAL_IO.md) executes two
fixed sample-reader BL edits only in emulator memory, with checked bus/release
results and no allocation. It does not establish complete integration fit or
physical/source/lifetime receipts. The preceding
[optical work implementation](UNIFIED_OPTICAL_WORK.md) adds C for
original-ticket read lifetime and verified-pause software-buffer retirement.
Both ARM ELFs change reproducibly, with unchanged compiler flags and no new
static RAM. Sharing repeated checked code makes the components fit; it does not
prove complete integration fit, stock ownership/recovery or physical continuity.
The retained optical-work-fit-v1 APP-bound failure is not a passing build.
Individual STOP failures cannot be replaced by a later barrier acknowledgment;
the new negative witnesses demonstrate that an affected timer stays active.
No compiler flags changed and no complete hardware binding was enabled.
The [optical-dispatch continuation](UNIFIED_OPTICAL_DISPATCH.md) adds actual
GPIO/software-event routing and HR/SpO₂ result stores. Synthetic late-work
witnesses restore result state after STOP without enable; original identity,
commit serialization and IRQ/hub/notification retirement remain unbound.
The subsequent [HR commit guard](UNIFIED_HR_RESULT_COMMIT.md) implements a
bounded critical section for four HR-result stores, adding 80 bytes and 60 ARM
cases. Both ELFs change; no stock hooks or production inventory were attached.
Original source identity/provenance, other commits and physical fences remain
unproved, so this does not complete the binding.
The later [optical read continuation](UNIFIED_OPTICAL_ACQUISITION.md) replaces
selected status/parser/classification mocks with actual instructions. It rules
out top-level zero and parsed/read flags as measured provenance, with no C or
ELF change. Real source identity and buffer retirement still need binding.
The [status-notification audit](UNIFIED_STATUS_NOTIFICATIONS.md) adds off-ring
constructor evidence and redacted diagnostic metadata, not a relaxed filter,
physical cause, publication fence or new device session. That audit changed
neither ELF.
The newest [indicator retirement experiment](UNIFIED_INDICATOR_RETIREMENT.md)
changes entries only in emulator memory. It prevents tested indicator restarts
while preserving selected Health starts/replies; no stock body space is reclaimed.
The newer [current-controls primitive](UNIFIED_STOCK_SETTINGS.md) adds 48 linked
bytes and an eight-byte local frame, no static state or stock writes. It executes
alongside original stock settings/scheduler witnesses, not a full resume binding.
The [timer-rearm continuation](UNIFIED_TIMER_RESUME_READ.md) executes captured
kernel hazards. Its freshly coordinated 452-byte code read subsequently passed
all 180 transactions, repeat/postchecks and verified disconnect. Standalone
archive replay and 79 captured creation/default execution cases now belong to
the current guarded build. That rearm continuation changed neither ARM ELF. Native zero-period
creation mutates allocation before asserting; conversion assumptions remain
explicit. No physical pause/resume proof or continuing device authorization follows.

The new [support-code/state diagnostic](UNIFIED_SUPPORT_READ.md) completed on
a separately requested retry: 284 matching transactions, all repeated values/
postchecks passed and disconnect verified. The earlier discovery failure is
retained separately. Actual helper/context/literals are now captured alongside
17 fixed state bytes. Rate configuration is 100; create/start/restart hooks are
`(0x205c01, 0, 0)`. The create target was NOT followed in that earlier session.
New offline tests replace arithmetic/context assumptions, not real hardware
serialization or hooked creation. Further device work needs new coordination.

The [fixed create-hook diagnostic](UNIFIED_CREATE_HOOK_READ.md) completed on a
separately requested retry: 359 matching transactions, repeated equality and
postchecks, verified disconnect. Exact archive replay is included in the current
build. The earlier `0x73` abort is retained separately. The captured hook and
comparator now execute off-ring: success creates an inactive timer, while
empty-handle failure reaches unread `0x111a6`. Null output and wrapped-period
negative witnesses also forbid naive API use. Pool/list/critical boundaries
remain synthetic; no physical resume/ownership/recovery proof. An SDK initializer witness sets
a different create-hook value, so it cannot replace actual ring code. The plan
gates 52 non-secret header bytes and two fixed code caps behind prior checks,
with 359 total transactions and no pointer following or hardware execution.

Preceding off-ring build: `firmware/unified/build-20260923-captured-rom-v1/`,
**1588 tests passed**, zero skips/failures/errors, all **185 hashes checked**.
This supersedes the older build and component sizes recorded further below.

## Captured-ROM execution and null-queue guard

The successful repeated capture is now an input to `whip/fwrom_execution.py`,
`tests/test_fwrom_execution.py` and `tests/test_fwrom_fence.py`. This continuation
is entirely off-ring. Captured bytes are pinned by the full archive hash and
each window's address/length/hash; missing code or literals are **not** silently
filled with zero or invented SDK data. Only selected instruction spans execute.
SRAM, timer objects, queue messages, headers and timing are explicit fixtures;
unread callees are named substitutions. Stack/register preservation and access
bounds are checked. This is not a complete ROM/boot/RTOS emulator.

### Actual code findings and implementation consequences

| Captured entry | Executed behavior | Consequence |
|---|---|---|
| `update_ram_layout`, `0x4a78` | Writes app size at `0x200384`, data-heap size at `0x200388`, cache selector at `0x2003cc`; leaves base pointers alone | Confirms the three-argument ABI, **not** allocator initialization, capacity or ownership |
| Error helper, `0x4c7a` | Image IDs `0x278d..0x279a` store the low error byte at `0x20005d..0x20006a`; out-of-range IDs do nothing | The earlier unknown helper is a bounded status store on this selected path, not itself a reset/copy/recovery operation |
| Task timer pend, `0x10d5e` | Asserts if queue slot `0x201478` is null; otherwise marshals `[-1, callback, context, ticket]`, calls `0xeab2`, returns its raw result | Added a null-slot check **before** our binding calls ROM; absence permanently faults the fence without enqueue |
| Generic timer command, `0x108e0` | Checks pool range/48-byte alignment; bad handles take `movs r0,#0; str r0,[r0]` at `0x10954..0x10956` | Cancellation requires owned, live timer handles under serialization; invalid handles are not harmless false returns |
| Same command, DELETE versus STOP | DELETE checks the allocation bitmap and takes the same bad-handle path if clear; STOP can still enqueue a pool-aligned unallocated entry | STOP acceptance is not evidence that the timer is live, owned or cancelled |
| Timer command processor, `0x1099e` | Negative messages call the stored callback with stored context/ticket; STOP clears the timer active bit; static DELETE also clears that bit | Dispatch ordering can support a timer barrier, but queue acceptance alone cannot acknowledge completion |
| Header check, `0x8a82` | Rejects null headers, wrong IC byte, `not_ready` and mismatched image ID | Early rejection paths are executable evidence; valid-looking input reaches **uncaptured** literal `0x8cbc` and stops the proof |

The new guard is a bounded load under the existing PRIMASK-preserving critical
section; no RTOS call occurs while masked. It assumes the initialized stock
queue survives for the boot. It does not prove queue lifetime, scheduler state
or correct firmware identity, and the binding remains unattached. The captured
generic-command queue-null behavior is different: it returns zero; the timer-
pend wrapper asserts. Treating all timer APIs as identical would miss this bug.

`ROMFenceHarness` executes the **actual-address compiled C fence**, the captured
ROM pend marshalling, captured negative-message dispatch and compiled C callback
as one chain. Only `xQueueGenericSend` (`0xeab2`) and `xQueueReceive` (`0xefae`)
are replaced by the explicitly synthetic kernel queue. Tests cover early
dispatch before enqueue returns, exact acceptance value 1, failed/unusual
returns, one-shot completion, abandoned and stale callbacks, null-queue refusal,
and rejection of unreviewed commands/callbacks/context pointers. No test writes
a fabricated acknowledgment into the C object to obtain completion.

Additional captured-command tests cover task/ISR STOP and task DELETE, raw
queue-return propagation, scheduler-dependent wait arguments, null queues and
invalid/unallocated handles. Selected STOP/static-DELETE daemon tests execute
the active-bit update and captured non-wrap time helper. They explicitly mock
queue receive, list removal, tick count and the unread compiler switch helper;
the latter uses the actual captured table. They do not execute the dynamic-
delete allocator or prove physical cancellation/freshness. The invalid-handle
witness faults at the captured null write in protected emulator memory; no
such operation was performed on the ring.

The guard adds **24 linked bytes**: current components occupy **8892 of 9520
configured bytes**, leaving **628**. The 12-byte fence and 988-byte combined
state/frame budget are unchanged. This is still a component link, not a complete
hooked image; neither the remaining flash bytes nor nominal 36 RAM bytes are
approved spare space. No construction or production gate is opened.

### Next implementation boundary

The timer ABI is no longer supported only by a symbol-map/mock. What remains
is proving the underlying queue ordering/lifetime and joining that barrier to
the real producer inventory, hub/IRQ/RUN and result guards. Timer handles must
not be deleted/reused while cancellation examines them. A timer receipt alone
must never call `wh_fenced` or `wh_stopped`. Physical STOP, current-settings
resume, acquisition/model qualification, steps/sleep continuity, complete
placement/RAM ownership and recovery are still separate required gates. The
missing header literals/callees were **not** read by this off-ring continuation.

### Guarded result for this continuation

`firmware/unified/build-20260923-captured-rom-v1/`:

- **1588 passed in 113.18 seconds**, zero skips/failures/errors/xfails. Ordered
  collection and setup/call/teardown identities agree. This adds 93 tests to
  the prior 1495-test gate, including the successful diagnostic-archive replay.
- All **185 hashes** independently rechecked: 125 inputs, 57 artifacts and
  three reports. Component objects and both link layouts rebuild identically.
- Actual-address append occupies 8892 bytes (8804 text/constants, 88 unwind),
  ending at `0x849d8c`, with 628 configured bytes remaining. No writable ELF
  sections, stock-byte changes, installed hooks or OTA container.
- Manifest SHA-256:
  `6104d022450485e5c83a819d32055c50d0400aae89ff8a82f58c56b2d5c2385d`.
- Artificial-address test ELF SHA-256:
  `60e1bbccc53e8dc4373b27ff028d0cf3c993e670c38edfd474ff049525540980`.
- Actual-address component ELF SHA-256:
  `665177d42df27d27c519ab3e667bc183269c98b8acb4d0c1aa7072f6c1d03161`.

No ring access, app deployment, simulator rerun, separate legacy-regression run,
commit or push. Compiled Swift checks are part of this guarded suite, not a
phone test. The installed image remains V2 optical-off. `flashable`,
`stock_linked`, `hardware_access` and `ram_ownership_verified` remain false.

## Real-address link and RAM reduction

`probe.stock_link` now compiles eleven components plus shared freestanding
compiler primitives and links them at **`0x847ad0`**, immediately after the
complete pinned stock image. The actual captured descriptor supplies the end
`0x84a000`; original code/data and the last 200-byte boot overlay remain intact.
There are no new writable sections or installed hooks and no OTA/container
output. The verifier rejects unresolved symbols/relocations, misplaced/writable
segments, wrong entry, missing components and test-support symbols.

The first attempt `stock-link-20260923-v1` failed entry validation because Zig
supplied its default `_start`, overriding the script entry. It has no success
report. Explicitly specifying `wd_init` fixes that without relaxing validation.
The pre-RAM-reduction link `stock-link-20260923-v2` is reproducible and occupies
8500 bytes: 8412 text/constant bytes and 88 unwind bytes, with **1020 configured
bytes remaining**. This is a real-address *component* link, not a stock-linked
candidate with boot/service/hardware hooks or a physical placement approval.

The adapter now retains one copied source profile in `source.profile`, rather
than two copies. Preparation is allowed only in Health with the source stopped;
no external pointer survives. START explicitly permits copying its own retained
profile before replacing source state. Queue sizes and all freshness/health
checks are unchanged. Native/ARM tests cover busy refusal, hold identity,
profile retention and a new Gesture after returning to Health. Early new tests
incorrectly assumed consecutive session IDs; sessions actually use operation
tokens, so the corrected assertions check the next operation token.

The preceding guarded build includes this real-address link and executes it in
addition to the artificial-address proof ELF. Final component extent is
**8868 bytes** (8780 text/constants plus 88 unwind), leaving **652 configured
bytes**. Actual ARM `sizeof` witnesses measure adapter 864, dispatcher 956,
dispatcher plus caller-owned frame 976, and timer fence 12 bytes. The adapter
and dispatcher each save exactly one 60-byte profile. Combined state/frame/
fence totals 988 bytes, leaving only 36 of the nominal 1024 aligned bytes.
Neither RAM ownership nor space for all remaining hooks is proved by that sum.

ELF inspection now verifies exact section/load file-offset correspondence and
execute permissions, unique bounded sections, nonoverlapping segments, function
membership in `.text`, and all required entry/component symbols. The builder
removes inherited fixture-ELF overrides and supplies its own hashed outputs to
the tests; stale external ELF files cannot silently satisfy the guarded run.

## Timer-daemon barrier binding candidate

`stock_timer_fence.{c,h}` is actual-address Cortex-M0+ code using the symbol-map
address `0x10d5f` for the SDK's `xTimerPendFunctionCall`, with a zero wait. Signed
return value **exactly 1** means enqueue acceptance. Only the retained compiled
callback can acknowledge a strictly increasing ticket; completion is consumed
once, and stale callbacks, zero/wrapped tickets and interrupt/masked enqueue
contexts are refused. Prior PRIMASK is always restored. Critical sections contain
bounded state operations, never an RTOS call. Storage is 12 bytes and must remain
alive for the entire boot, even after timeout/abandon.

A review found and fixed an enqueue/cancel race: abandon could otherwise clear
`pending` while the first ROM call was still in flight, allowing a second request
whose state the first return could corrupt. A separate `enqueuing` byte occupies
existing struct padding and refuses that overlap. ARM tests execute abandon and
new request from a second synthetic task at the exact ROM boundary, with both
enqueue outcomes and early callbacks. They also cover stale callbacks, masked
interrupts, one-shot completion and permanent refusal after enqueue failure.

This is **not** a completed health fence. The original aborted diagnostic did
not capture the ROM timer body; the later successful retry below did. The newer
execution section above replaces the pend/dispatch API mocks with captured
instructions, but still substitutes the actual queue kernel/FIFO semantics.
Even proven timer-queue passage would still require accepted producer cancellation,
closed restart admissions, hub/IRQ/RUN/publication fencing, and physical STOP.
Do not synthesize `wh_fenced` or `wh_stopped` from this component alone. It is
unattached and must not be called on the installed V2 image.

## Consolidated ROM-code diagnostic plan

The user freshly confirmed all clients closed, no stream/DFU, for this specific
code-only plan. It supports the real allocation, cancellation/barrier and OTA
binding work, instead of treating unread APIs as completed physical evidence.

`probe.rom_read --integration-code` admits only these fixed symbol-bounded
intervals, in addition to repeated pinned prerequisites:

| Name | Start | End exclusive | Bytes |
|---|---:|---:|---:|
| RAM layout and intervening boot helpers | `0x4a78` | `0x53a4` | 2348 |
| Flash-info/layout getters | `0x805e` | `0x81a0` | 322 |
| OTA checksum/header/routing getters | `0x8a5c` | `0x8c72` | 534 |
| Timer task/queue/API implementation | `0x105c8` | `0x10fb8` | 2544 |
| Critical-section implementations | `0x1105e` | `0x111a6` | 328 |

The full symbol-map hash and both boundary symbols for every interval are
checked before connecting. The reader first repeats the 91-transaction V2/CD/
idle/configuration/bank0 descriptor plan and requires the exact known descriptor.
It then reads the 16-byte app ROM identifier twice and requires the known UUID.
All **6076 new code bytes** are read twice and compared, followed by exact config/
idle postchecks, unsubscribe and verified disconnect. Success requires exactly
**974 CD01 transactions**. Collection has a 180-second deadline and the whole
workflow 240 seconds. Each transaction has the existing three-second timeout,
one outstanding request, 100 ms pacing and poison-on-ambiguity behavior.

No request address comes from captured pointers. No key/authentication/OTP field,
hardware/FIFO register, sensor command, flash, reset or code execution is allowed.
The code spans may reference data; those data are not read by this plan. CD01
still has the reviewed bookkeeping side effects. A mismatch/fault stops with
no retry or reconnect; no success is declared unless disconnect is verified.
No new flash authority follows from this session or its eventual code matches.

### Actual outcome: aborted, no retry

The coordinated attempt sent **189 requests**, received **188 matching replies**
and aborted when unrelated UART traffic arrived during the request at `0x4f8e`.
Only 1302 bytes of the first new window were returned once. None of the five new
windows passed repeat/postchecks, and no successful capture exists. Original
notification type/payload and backend-disconnect status were not logged. Existing
unsubscribe/disconnect cleanup ran and the process exited, but verified disconnect
must not be claimed retrospectively. The exact transcript and its limitations
are archived under `firmware/research/2026-09-23/rom-integration-aborted/`.

New logging records only foreign packet type/length, never health payload, and
records the backend's disconnect state on failure. The strict abort policy is
unchanged. The archive test replays the exact prefix to its recorded exception
and proves that it cannot complete or retry; it does not invent the packet type.

Single-pass partial bytes provide two **unqualified leads**, not completed ROM
evidence: `update_ram_layout` appears to write only app size, data-heap size and
cache-sharing configuration, rather than initializing the heap; `0x4c7a` appears
to store an image-indexed error byte (`0x278d..0x279a` map to `0x20005d..0x20006a`).
These paths and literals lie in the partial transcript but were not repeated.
The RAM write does not prove later allocator boundaries, retention or ownership;
the error-byte helper does not prove the caller's recovery behavior.

### Passive notification follow-up completed

`probe.idle_notifications` reads DIS identity, listens on UART notifications for
60 seconds, unsubscribes and verifies disconnect. It sends **zero UART commands**;
there are no code reads, sensor/flash/clock/settings commands or retries. Only
command byte, length and checksum validity are retained, never health payload.
Raw A1, diagnostic CD, malformed traffic or 120 packets abort the observation.
Eleven fake-radio tests passed before connection. After fresh closed-client
confirmation, `data/idle-notifications-20260923-01/` completed the full **60-second
interval with zero notifications and zero UART commands** and verified disconnect.
DIS identity matched the expected strings, not a full image fingerprint. The
reader/tests/packet implementation matched their preceding guarded-build hashes.
The exact transcript is archived under
`firmware/research/2026-09-23/idle-notifications/`, SHA-256
`e459b22c6edc55800c03d2401f0190d300de8ad37f2eaab2760a9d89cf0f2cf6`.

The interruption did not recur passively; its original type and cause remain
unknown. This does not prove behavior during CD01 bookkeeping, permit foreign
packet filtering or qualify any new ROM window. No code-read retry, sensor
command or flash occurred during that passive session. It ended before the
separately requested retry below. Firmware code and the 1495-test build are unchanged.

### Separately requested retry: all five code windows captured

The user explicitly requested one retry and freshly confirmed all other clients
closed, ring idle, with no stream/firmware transfer. The reader/protocol/reference
hashes matched the passing build; **378 preflight tests passed**. No read bounds,
timeouts or unexpected-traffic guards were relaxed.

`data/rom-integration-20260923-02/` completed **974 matching CD01 transactions**
in 134.840 seconds of request/reply time. All 6076 bytes across the five fixed
windows matched their repetitions; configuration/idle postchecks passed and
disconnect was verified. No sensor, flash, key-field, MMIO/FIFO, returned-pointer
or on-device target-execution operation occurred. CD01 bookkeeping remains an
explicit side effect, and sampled identity is not full live-image attestation.

Byte-identical archive: `firmware/research/2026-09-23/rom-integration/`:

- Capture SHA-256: `d02cc3582a789d933e1be09fa1bbec05ade7a193508418149f145dc12df3b05b`.
- Transcript SHA-256: `22d85dc403dda89e6bc6cfea605200d05d8201521d58b0ae83ee597235e39f8f`.

The new standalone archive test validates all checksums, exact outgoing requests,
window hashes and evidence flags, replays all 974 replies through the fixed
reader, and reproduces the saved capture. Its RAM/boot prefix also matches all
1302 bytes from the older aborted attempt. This test and the existing abort
archive test passed together (**2 tests**). The new archive/test are not included
in the older 1495-test manifest; firmware and those 179 recorded hashes are
unchanged. The original unexpected packet's type/cause remain unknown.

Initial off-ring disassembly confirms the task-context timer-pend wrapper builds
a 16-byte message with command `-1`, callback, context and ticket; forwards the
caller's wait and send-position 0 to `xQueueGenericSend` at `0xeab2`; and propagates
its return. The queue handle must already exist or it enters an assertion path.
That supports the binding ABI but does not yet execute/prove the queue kernel
or full timer/hub/IRQ shutdown fence. Header-check code is now captured, but its
shared literals around `0x8cbc..0x8cd4` and some callees remain outside this fixed
read; do not silently follow them or present mocked values as physical evidence.

The completed read supplies previously missing code for further off-ring work.
It does not by itself approve RAM placement, physical geometry/recovery, FIFO
timing/model replay, or health STOP/resume/steps/sleep continuity. No firmware
was changed and construction gates remain closed. This session ended; further
device access requires a new bounded plan and coordination.

## Earlier guarded build result

`firmware/unified/build-20260923-stock-address-v1/`:

- **1495 passed in 129.62 seconds; zero failures, errors, skips or xfails.**
- All **179 hashes** independently rechecked: 119 inputs, 57 artifacts and three
  proof reports. Ordered collection/execution identities match, with passing
  setup/call/teardown for every test.
- Component objects and both link layouts are rebuilt identically. Both use
  the same checked-in freestanding compiler primitives. The actual-address STOP
  shim executes against unchanged stock bus instructions with explicit peripheral
  mocks, retaining errors and preserving all original stock bytes in the fixture.
- Artificial-address ELF SHA-256:
  `1f5282966060e2bff4e00f4a9d2c403e07fc7a1deb5f910c514cc19a49afc513`.
- Real-address component ELF SHA-256:
  `6b21fcbb5f7a66d79820175fe907f7b50e0534c57b4746e8b9dc6bc8c37458ea`.
- Manifest SHA-256:
  `e02b7d505e3cf451077b7289dc5fca894a49b6242ceb1ae7046a146a46104f8b`.

A separate exploratory Zig LTO build in `/tmp/whip-stock-lto.ozWKIz/` was **not
adopted**. The initial command collapsed the root list into one argument and
produced an invalid, stripped/incomplete ELF; structural/execution tests rejected
it (27 failed, 10 passed). Correctly retaining all 91 public API roots then failed
the unchanged APP-bound assertion. No bounds, required symbols or safety checks
were weakened, and no LTO result is included in the passing build above.

No firmware container, boot/service/hardware hook installation, RAM reservation,
physical FIFO/STOP/resume/steps/sleep proof, app deployment, commit or push was
performed. Health is still the intended unified default, while installed V2 still
globally disables optical health. The latest iOS simulator/legacy-regression
results remain historical; neither was rerun in this continuation.
