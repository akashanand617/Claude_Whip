# Timer-create-hook diagnostic: separate requested retry completed

Latest session, 2026-09-23: after a new explicit connection request, the fixed
retry completed **359 matching CD01 transactions**, repeated header/code equality,
final state/header/config/idle checks and verified disconnect. All 279 known
prerequisites passed before the fixed 52-byte prefix and 384 code bytes were read.
No unexpected notification, filter bypass, sensor/flash command or automatic
retry. Exact archive replay passes; see
[the success archive](../firmware/research/2026-09-23/rom-create-hook/README.md).
Before connection all 224 status-build hashes matched and 226 selected tests
passed in 3.22 seconds. This session ended and grants no continuing device access.

Earlier attempt, retained separately: **one requested reconnect aborted before
any new window.**
The ring connected and DIS matched. After 170 requests / 169 accepted replies,
an unexpected 16-byte notification of type `0x73` interrupted prerequisites at
`0x1409a`. Its payload was not saved and its cause is unknown. The reader stopped,
verified disconnect, and did not retry. No new header/hook/comparator address was
requested, no final postchecks ran, and no success capture exists. See the
[byte-identical failure archive](../firmware/research/2026-09-23/rom-create-hook-aborted/README.md).
All 222 preflight hashes and 132 selected tests (2.79 seconds) passed beforehand.
Further device access requires a newly coordinated exclusive-idle session;
neither the completed support session nor this terminal attempt grants one.
No firmware C, image, hardware binding, memory reservation or flash gate changed.
Health remains unified boot/default; installed V2 optical-off is unchanged.

Later off-ring [status-constructor tests](UNIFIED_STATUS_NOTIFICATIONS.md)
establish a shared `0x73` event family, not this packet's cause. The code reader
now records checksum validity, valid `0x73` subtype and host time without health
values. All foreign packets still abort; bounds and 359-request budget are
unchanged. The preflight build used for the retry was `build-20260923-status-metadata-v1/`:
2491 passing tests, all 224 hashes checked, both ARM ELFs unchanged. The updated
code reader was used for the successful separate retry above. The passive
observer v2 has not run; the failed first event's cause is still unknown.

## Captured declarations and initial off-ring reading

The ring's non-secret ROM-patch prefix declares payload `0x9528`, RAM start
`0x203800`, load source `0x1809404`, load length `0x3510` and image base
`0x1803000` (IC 12, image ID `0x2792`, flags `0x916`). Declared RAM end is
`0x206d10`; this fits the conservative cap gate but does not prove ownership,
runtime copying, authentication, chip geometry or boot/recovery. No key field
or declared load-source address was read. These fields differ from the external
SDK reference; its initializer/body cannot replace captured ring instructions.

Initial disassembly identifies create-hook body `0x205c00..0x205c30` and a
literal at `0x205c30` containing `0x200364`. The hook calls captured ROM default
`0x13f9e`, stores a result byte, and has a conditional failure/empty-handle call
to unread `0x111a6`. The pinned symbol text calls that target
`vTimerCreateFailedHook`; a symbol name is not its implementation or a safe
failure-recovery proof. Comparator body `0x8e24..0x8e46` checks byte equality.
Other routines/literals inside the acquisition caps are not approved execution.
The subsequent off-ring execution below tests these bodies; it is not another
automatic device read or a completed physical resume proof.

## Captured-body execution — 2026-09-24

`tests/test_fwrom_hook_execution.py` adds **121 offline cases**. The focused
hook/support/resume/archive run passes **260 tests in 0.46 seconds**; the 121
are included, not additional to that count. The input is the exact successful
capture, checked by archive and window hashes. The harness admits only 48 bytes
of hook instructions plus its four-byte read-only literal and 34 bytes of
comparator instructions. Neighboring cap bytes, literals as code and unread callees
remain terminal boundaries. One emulated RAM page gains RX permission solely
to run this captured RAM function; the code hook still restricts execution to
its selected body and grants no write permission. No ring operation occurred.

### Timer creation: actual hook, not the ROM-default shortcut

The complete selected success path now executes wrapper `0x13634`, observed
hook `0x205c00`, default `0x13f9e`, unsigned division `0x3f97a` and native
allocator/create `0x10774/0x10b5c`. The observed hook slot is not overwritten
with zero. With captured rate configuration 100 and inhibit zero, tested
periods round up by ten and valid creation publishes a new timer containing
the requested name, ID, callback and reload flag. The timer is **inactive**:
creation does not submit START or execute the callback. Pool/list/interrupt
serialization, logging and timer object state remain explicitly synthetic.
This is not measured physical timing or safe current-settings job admission.

Executed negative witnesses:

- Empty pool, a marked-allocated free head, zero requested period and null
  callback with an empty handle store result zero, then call **unread `0x111a6`**.
  Execution stops there. The symbol name `vTimerCreateFailedHook` does not say
  whether it returns, resets, asserts or recovers. No success/failure behavior
  after that boundary is fabricated.
- An occupied output slot returns failure and leaves the handle untouched;
  it does not take that empty-handle failure call. This is not fresh creation.
- Only inhibit **bit 0** blocks this path. Explicit counterfactual odd bytes
  suppress both creation and the failure call; even nonzero bytes tested do
  not. Captured inhibit remains zero; no live state was changed.
- With a null output pointer the default rejects the request, but the hook
  subsequently attempts a read at address zero. The emulator rejects this
  unadmitted read. It does not establish what address zero contains or how the
  physical device reacts; the binding must never pass a null output pointer.
- Requested periods `0xfffffff7` and `0xffffffff` wrap through actual conversion
  to a native zero period. Allocation is consumed before the assertion
  boundary; the handle and new callback have not been published. The hook
  has not yet stored a result. Period checks must happen before creation,
  not after a supposed failure return.
- Hook return value **1 means handled**, not successful creation. Its separate
  output byte is the operation result returned by the wrapper. Explicit
  mocked-default ABI tests verify forwarding, truncation and no duplicate
  fallback, separately from tests executing the real default.

The unread failure call prevents claiming that the live creation API safely
returns failure on pool exhaustion. Merely inspecting a free entry beforehand
is not a fix: allocation/slot lifetime and competing jobs still need proven
serialization. No production create/resume API or pointer to this RAM function
was added to the firmware. Existing STOP/fence components remain unattached.

### Header comparator: field checks, not image validation

The actual comparator returns one for equal bytes (including zero length) and
zero for mismatches. Every UUID-byte position is tested. It keeps reading after
a mismatch; a short-buffer negative witness stops at the next unadmitted byte,
not at a fabricated early return.

The complete selected header check `0x8a82` now executes through that comparator
and the real error helper `0x4c7a`. APP ID `0x2793` and ROM-patch ID `0x2792`
accept the captured UUID; any tested UUID byte mismatch returns zero and stores
error `0x15` at `0x200063` or `0x200062` respectively. Wrong IC, `not_ready` and
wrong image ID retain early errors `0x11/0x13/0x14` without needing the comparator.
Initial test expectations had the two error-byte offsets wrong; captured
helper/literal arithmetic confirmed `0x200060 + (image_id - 0x2790)`, and only
those expectations were corrected. No firmware behavior was changed.

Exact hash-pinned local original25Hz and V2 nested prefixes pass this selected
check. The stock **source file's** prefix fails with `0x13` because its
`not_ready` bit is still set; this is the already documented container-build
step, not evidence that an installed stock image fails. No file is modified.
The exact newly captured 52-byte ROM-patch prefix also passes. None of these
tests includes payload integrity/authentication, key fields, actual flash
capacity, copying, boot selection, rollback or power-loss recovery. A successful
field check must never serve as flash approval.

### Remaining work

Health remains boot/default and Gesture opt-in. The ring remains disconnected
on V2 optical-off. This work closes the selected hook-success and comparator
instruction gaps, **not** the unread failure handler, complete producer/result
fencing, physical STOP, current-settings fresh resume, RAM/stack ownership,
recovery, fresh FIFO/model qualification or steps/sleep continuity. Additional
device access needs a separately bounded plan and new exclusive-idle coordination.

## Hook-execution build

The later [optical-event/commit continuation](UNIFIED_OPTICAL_DISPATCH.md) adds
32 cases, with 2645 tests / 230 hashes in its passing v2 build. Both ARM ELFs
remain unchanged. The hook-specific build below is its preceding snapshot.

`firmware/unified/build-20260924-create-hook-execution-v1/`: **2613 passed in
145.13 seconds**, zero skips/failures/errors/xfails. All **228 hashes** rechecked:
158 inputs, 67 artifacts and three reports. The 121 new cases above are included.
Manifest SHA-256:
`fb3d50e081a34bc82ca3541298a5b5b90683e3626469f8440489e6001469fed4`.
Both ARM ELFs are unchanged from the preceding capture build: test ELF
`2e66a8133a753103ff412dd959d42d7e39bb177fc2c2120aaa344b9426a67b7e`,
actual-address ELF
`2c75d78867394ac4c9beb9ca18b3e4f5dca58c701884b64b92a65ac5720013e6`.
Components remain 9272 configured bytes, 248 remaining; combined state is
796 bytes, neither complete fit nor approved RAM ownership. No firmware C,
compiler flags, stock bytes or construction/production gate changed.

## Prior guarded capture and replay

Preceding guarded capture/replay build (2026-09-24):
`firmware/unified/build-20260924-create-hook-capture-v1/` passed **2492 tests in
153.48 seconds**, zero skips/failures/errors/xfails. All **227 hashes** matched:
157 inputs, 67 artifacts and three reports. It adds the exact 359-transaction
archive replay, not new hook/comparator execution tests or a production binding.
Manifest SHA-256:
`b3123dce765d24bc3fdf2a33f02a6aeb52c06a7f2ca143e355b39ed3a8c2a0b7`.
Both ARM ELFs match the prior build. Components remain 9272/9520 configured
bytes, combined state 796 bytes, with no fit/ownership or construction approval.

## Why the SDK cannot substitute for this ring's hook

The [support capture](UNIFIED_SUPPORT_READ.md) observed create/start/restart
hooks `(0x205c01, 0, 0)`. It deliberately did not follow that nonzero target.
The hash-pinned SDK-origin mirror for a **different e-paper board** was fetched
again from its existing pinned commit, not from a moving branch:

[ATC_RTL_BLE_OEPL, commit 49301d9](https://github.com/atc1441/ATC_RTL_BLE_OEPL/tree/49301d9b75816ccde1cc9657b827fdadf5736937/ATC_RTL_BLE_OEPL_8762ESL).
System blob `gcc/data_0x801000.bin`: 190668 bytes, SHA-256
`ca53de5cfabc4eb9f4071773fe65db0e573560a0ad0c53c9c4d4ddfa02124347`.
Local download: `/tmp/whip-timer-hook-reference.6yltSC/data_0x801000.bin`.

The external 20-byte initializer and its bounded literal pool at file offset
`0x2912` perform three stores in offline ARM execution:

| Slot | SDK initializer value |
|---|---|
| `0x2015fc` | `0x206331` |
| `0x20173c` | `0x20638d` |
| `0x201644` (timer create) | **`0x206359`**, unlike observed `0x205c01` |

This is a concrete mismatch, despite a matching ROM UUID. The 46-byte initializer/
literal excerpt and only the 52-byte non-secret ROM-patch header are retained in
`firmware/research/2026-09-23/reference-boot/rtl8762e-sdk-timer-hook.json`.
Both excerpts were checked byte-for-byte against the pinned source. This file
is explicitly external reference, not a ring capture or installable image.
It contains no key/authentication fields. No SDK hook body is promoted to ring
code. The external header declares RAM destination `0x203800`, load source
`0x18099c4`, length `0x30b0`, and image base `0x1803000`; those declarations
do not establish this ring's copied code, RAM ownership, or source decoding.

Terminology correction: image ID `0x2790` is the **OTA table header**, not the
factory-data header. The corresponding new test and notes were renamed; their
instruction coverage is unchanged. This does not change the separately reviewed
528-byte factory/OEM boot checker. The identifier comes from the pinned
[SDK header enum](https://raw.githubusercontent.com/atc1441/ATC_RTL_BLE_OEPL/49301d9b75816ccde1cc9657b827fdadf5736937/ATC_RTL_BLE_OEPL_8762ESL/sdk/inc/platform/patch_header_check.h).

## Fixed acquisition plan

`probe.rom_read --timer-create-hook` selects `whip/fwrom_hook.py`; it accepts no
memory address/length, is mutually exclusive with all older plans, and does not
reopen or extend a completed reader. All new addresses are fixed in reviewed
code, never taken from values returned in this new session.

Before connection, pin original25Hz/V2, the diagnostic code and symbol map,
the STOP, resume, integration and successful support captures. Then:

1. Repeat expected BLE/DIS, sampled V2 code, CD path, idle, configuration and
   bank0 descriptor checks (the existing 91-transaction plan).
2. Repeat the ROM UUID twice. Repeat **all** prior known support ROM and fixed
   state windows twice, matching archived values, including the exact create
   hook value; additionally repeat the captured BL at `0x8ac8..0x8acc` targeting
   header comparator `0x8e24`. A changed pointer never selects another target.
   All first **279 transactions** must pass before a new address is read.
3. Read the **52-byte non-secret ROM-patch header** `0x803000..0x803034` twice.
   The `dec_key` field begins at the exclusive end and is never included.
4. Only after equality and the conservative header gate below, read both fixed
   code caps twice:

| Fixed code cap, end exclusive | Bytes | Basis |
|---|---:|---|
| `0x205c00..0x205d00` | 256 | Prior captured create-hook value, frozen into this separate plan |
| `0x8e24..0x8ea4` | 128 | Prior captured direct BL from the header validator |

5. Recheck the three known state windows once each and the new header once,
   requiring exact equality; then repeat original config/idle postchecks.
   Unsubscribe and verify disconnect before saving a success JSON.

Exact budget: **359 serial CD01 transactions** = 279 prerequisites + eight
header reads + 38 RAM-code reads + 20 ROM-code reads + 14 final rechecks.
New data: **436 unique bytes** (52 header + 256 RAM code + 128 ROM code).
Frame payload remains at most 14 bytes. Collection deadline is 120 seconds;
the full connect/DIS/read/disconnect deadline is 180 seconds. No automatic retry.

The header gate requires IC 12, image ID `0x2792`, known ROM UUID, boot-load set,
not-ready clear and no composite image-type bits. Image/source extents must fit
the previously declared ROM-patch partition `0x803000..0x80d000`, accepting only
its explicit bit-24 alias. The declared RAM start must be `0x203800`; its end
must contain the whole fixed hook cap without reaching past app RAM `0x207c00`.
It checks containment, **not authenticity, successful runtime loading, memory
ownership or physical geometry**. A valid-looking different declaration fails
this conservative plan; it does not trigger a broader read or a new target.
The external SDK header is a test fixture, not an equality requirement for the
ring. Returned load-source and image pointers are never followed.

Code caps are acquisition bounds, not function-length/callee-closure claims.
State repeats are not atomic snapshots and do not prove immutability. Missing
callees/literals or a cap ending mid-function remain unknown after capture.
No inspected code is executed on the ring. No sensor start/stop, clock/settings,
DFU/reset, key field, MMIO/FIFO, source-pointer read or adjacent bank access.
CD01's existing connection/timer/activity bookkeeping effects remain.

## Failure and preflight

Local pin/identity/prerequisite/header/repeat/postcheck failure, malformed,
foreign or duplicate traffic, timeout, cancellation or failed disconnect aborts
without a success capture. Reader phases close and the session is poisoned;
there is no retry/reconnect or pointer-following fallback. Success would be
`rom-create-hook.json`, schema `whip.rom-create-hook.capture.v1`, only after
exact budget and verified disconnect. Physical/recovery/flash flags stay false.

132 new tests cover the SDK mismatch witness, declared-header gate, exact
addresses/order/budget, every prior comparison on both reads, malformed header
bounds/flags, all new repeat/transport faults, all final checks, cancellation,
key/adjacent/source-pointer refusal, every CLI plan conflict, identity and
disconnect/late-traffic failures. Original25Hz/V2 CD instructions copy first/
last chunks at all three new windows under three synthetic dispatch states.
Those new data are fake, not executed. An initial emulator fixture lacked the
`0x803000` page; it was corrected with an explicit synthetic read-only page,
without weakening any assertion or claiming actual device accessibility.

Focused regression: **789 passed in 11.46 seconds**, zero failures, including
all 132 new tests and prior readers/archive/support execution. This is not a new
ring session or a full firmware release gate. No current creation-hook code,
safe health pause/resume, qualified source, steps/sleep trial or recovery proof
has been obtained by preflight. No final unified firmware exists.

Review subsequently corrected the CLI's ROM-byte summary: its former hard-coded
1278 omitted the additional four-byte comparator BL witness. It is now derived
from fixed ROM windows and independently checked against their address union:
**1282 unique ROM bytes** excluding the separate UUID, RAM state/code and patch
header. Addresses, order and the 359-request budget were already correct and
are unchanged. All 132 selected tests pass after this correction (2.74 seconds).
`build-20260923-create-hook-preflight-v1/` is the retained pre-correction build,
not the current diagnostic release. No ring read occurred on either revision.

## Historical guarded preflight used for the attempted session

`firmware/unified/build-20260923-create-hook-preflight-v2/`: **2455 tests passed
in 157.65 seconds**, zero skips/failures/errors/xfails. All **222 hashes** checked:
152 inputs, 67 artifacts and three reports. All 132 new cases were collected and
executed in the full suite. Manifest SHA-256:
`0ce73277782c43ad3eb0e34c4686bafbb49035867a297eba114d98f2489c9d41`.

Both ARM ELFs match the preceding support-execution build byte-for-byte:

- Test ELF: `2e66a8133a753103ff412dd959d42d7e39bb177fc2c2120aaa344b9426a67b7e`.
- Actual-address ELF: `2c75d78867394ac4c9beb9ca18b3e4f5dca58c701884b64b92a65ac5720013e6`.

Components still occupy 9272/9520 configured bytes (248 remaining); combined
dispatcher/frame/fence state remains 796 bytes. Neither full integration fit
nor RAM/stack ownership is approved. `flashable`, `stock_linked`,
`hardware_access` and `ram_ownership_verified` stay false. No simulator rerun,
phone deployment, firmware patch, device access, commit or push occurred.
This is the preflight build record. The later attempted session described above
does not change these inputs or approve an automatic retry.
