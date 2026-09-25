# Completed support-code and timer-state diagnostic

2026-09-23. **The separately requested retry completed all 284 transactions.**
All known-code comparisons, repeated new windows and final idle/config checks
matched, followed by verified disconnect. This captured 616 new ROM bytes and
17 fixed non-secret timer-state bytes. No sensor command, firmware write, reset,
target execution, returned-pointer following or automatic retry occurred. Health
remains the unified boot/default; installed V2 optical-off is unchanged.

Success archive: [rom-support](../firmware/research/2026-09-23/rom-support/README.md),
byte-identical to `data/rom-support-20260923-idle-v2/`. Capture SHA-256:
`bcbffd1362964a186797e815fe15a17d4b66e0b1a8a54918cc09fd20d5cb874a`;
transcript SHA-256:
`05d72362a60f12dfab3958d9b3184d49523ba55d2ed9748b59e63b6b13111a05`.
First-request to last-reply interval was 38.679958166 seconds. All 215 prior-build
hashes matched and 134 preflight cases passed in 2.37 seconds before connection.
The preceding, separate battery-only session reported 99%, not charging; this
code-read session did not query battery again. Both sessions have ended.

Later, separately acquired [hook/comparator execution](UNIFIED_CREATE_HOOK_READ.md#captured-body-execution--2026-09-24)
closes the selected hook-success and header-equality code gaps. The support-only
negative tests below remain intentionally scoped to their earlier capture;
they do not contradict the later evidence. Actual failure/empty-handle creation
now reaches unread `0x111a6`; physical resume, ownership and recovery remain
unverified. Neither acquisition session grants ongoing hardware access.

## Earlier discovery failure — retained, not the successful retry

The first support-plan attempt exited 2 before connection because the expected
BLE identifier was not found. It sent zero commands and produced no success
capture. This failure is not combined with the successful retry's transactions.

Failure archive: [rom-support-not-found](../firmware/research/2026-09-23/rom-support-not-found/README.md).
The two-line transcript is byte-identical to the original in
`data/rom-support-20260923-idle-v1/`; SHA-256:
`d4a51b19c0c4f6786e8738276ad8cefc3f2a57fbbdf1b3e352bafe6863ce4dee`.
No success capture exists for that failed attempt. Before it, all 215 prior-build hashes
matched and 134 selected preflight tests passed in 2.39 seconds. The full build
record below remains the earlier offline result, not a new full build.
The availability failure does not identify its cause or change flash gates.

## New captured-code findings and limits

The repeated state windows hold inhibit `0`, rate configuration `100`, and
create/start/restart hooks `(0x205c01, 0, 0)`. The create hook is **nonzero** and
its body was not read. No returned pointer was followed. An offline execution
with these exact values stops at the unread `0x205c00` target; it does not
silently run the ROM create default. This is a concrete remaining prerequisite
for implementing the actual timer lifecycle, not a failed ring operation.

The captured arithmetic helper at `0x3f97a` implements unsigned quotient in r0
and remainder in r1 on the executed edge, power-of-two and randomized cases.
No divide mock is used. Division by zero returns quotient zero and the original
numerator as remainder on the tested path. Only `0x3f97a..0x3fad4` is admitted
for these tests; adjacent floating-point code in the acquisition cap is excluded.

The context selector `0x14238..0x14248` returns one in thread mode and zero in
exception context, tested using synthetic IPSR values. Its trailing literals
are `0xe000ed00`, `0x200364`, `0x200464`; they are data, never executed. START
and RESTART now execute actual helper/context/literals with the observed zero
hooks. Task/ISR commands and exact acceptance handling match the earlier
isolated tests; tick sources and queue behavior remain explicit substitutes.
No peripheral/MMIO write is admitted in these new tests.

Direct entry into the ROM create **default**, deliberately bypassing the unread
hook, converts 17 requested units to two ticks and 32 to four using the captured
configuration. Requests `0xfffffff7` and `0xffffffff` wrap to zero and consume
allocation before assertion in the synthetic pool, now without a divide mock.
This is not proof that the actual hooked wrapper behaves identically or a
physical cadence measurement. Do not infer safe current-job creation/resume.

The new OTA pool supplies image ID `0x2790`, magic `0x5a5a12a5`, and the known
ROM identifier. The selected OTA-table-header field checker accepts/rejects the
magic without mocks; it does not checksum/copy/boot an image. APP header checking
now reaches the unread comparison routine `0x8e24`, passing the captured expected
identifier and length 16. The proof stops there rather than inventing success.
Flash-layout literals include hardware addresses and RAM pointers; these were
archived as constants only, never followed or promoted to geometry/recovery proof.

The 60 new offline cases comprise one exact 284-transaction archive replay and
59 captured-code execution cases. Standalone result: **60 passed in 0.20 s**.
Firmware C, compiler flags, stock bytes and memory placement remain unchanged.
Real create-hook behavior, queue/producer serialization, physical STOP/resume,
ownership/recovery, source/model and steps/sleep continuity remain open.

Next: [the separately prepared create-hook read](UNIFIED_CREATE_HOOK_READ.md).
The external SDK installs a different timer-create hook; its code must not
substitute for the ring's. The fixed 359-transaction follow-up is NOT RUN and
needs fresh exclusive-idle coordination. No continuing access follows from this
completed session.

## Purpose and reference limits

The [captured timer execution](UNIFIED_TIMER_RESUME_READ.md) proves native
allocation and enqueue hazards, but its conversion helper, context selector,
some literals and current hook/configuration values are unknown. The earlier
6076-byte capture also missed the flash/OTA callers' shared literal pools.
These gaps prevent replacing several explicit emulator substitutes with exact
evidence. Reading these bytes does not itself implement resume or prove recovery.

Local archived binaries, ROM symbol map, prior captures and available scratch
references did not supply the missing exact ROM bytes. The reviewed SDK-origin
reference documents a different board and does not establish this ring's live
hook/configuration state. No borrowed implementation is promoted to ring code.

## One fixed plan

`probe.rom_read --support-code` selects `whip/fwrom_support.py`; no arbitrary
memory address/length is accepted. The flag is mutually exclusive with every
older diagnostic. Fresh confirmation must cover all phone/laptop clients
closed, no stream and no firmware transfer. It is not a sensor/resume command.

Before connection, verify original25Hz/V2 images and CD dispatcher, symbol map,
the STOP archive, the 452-byte timer archive and the 6076-byte integration
archive against their pinned hashes. Then require:

1. Exact expected BLE/DIS identity, the existing V2 sampled-code/idle/configuration
   checks and repeated bank0 descriptor (91 transactions). This is not full-image
   attestation and grants no expansion-space or recovery approval.
2. The known application ROM identifier twice (four transactions).
3. **Every known-code witness twice before any new read**: 72-byte STOP code,
   all 452 bytes of the latest timer capture, and four fixed flash/OTA caller
   instruction witnesses at `0x8062` (four bytes), `0x815e`, `0x8aa8`, `0x8c66`
   (two bytes each). Each must equal its pinned prior capture, not merely its
   current repeat. These total 534 unique known bytes and 86 transactions.
4. Each of the fixed new windows below, twice with equality required.
5. Repeat the existing configuration and idle postchecks (seven transactions),
   unsubscribe and verify disconnect before writing any success capture.

| New fixed window, end exclusive | Bytes | Basis and scope |
|---|---:|---|
| `0x3f97a..0x3fb7a` | 512 | Captured direct BL target from create/restart and timer-handle division. This is a fixed acquisition **cap**, not a known function length or full-callee coverage claim. |
| `0x14238..0x14254` | 28 | Captured context-selector BL plus referenced literals at `0x14248/4c/50`. No returned literal is followed. |
| `0x8420..0x8448` | 40 | Referenced shared flash-layout literal pool, bounded by actual captured LDR witnesses. These constants are not chip geometry measurements. |
| `0x8cbc..0x8ce0` | 36 | Referenced shared OTA-header literal pool; no header keys, authentication block, OTP or referenced storage is read. |
| `0x20037d..0x20037e` | 1 | Non-secret timer inhibit byte, independently fixed by the already captured create/start default. |
| `0x200484..0x200488` | 4 | Non-secret timer-rate configuration word, independently fixed by the captured create default. Its meaning/value must still be checked; this is not measured physical cadence. |
| `0x201644..0x201650` | 12 | Exactly the three create/start/restart hook slots located by the prior captured wrapper literals. Values are archived only, never dereferenced or executed. |

Totals: **616 new ROM bytes + 17 non-secret state bytes**, each repeated.
There are exactly **284 serial CD01 transactions**, of which all first 181 are
prerequisites/known witnesses; the new windows consume 96 and final postchecks
seven. Frame data remains at most 14 bytes. Collection is bounded to 120 seconds,
the whole connect/DIS/collection/disconnect workflow to 180 seconds.

The state fields are read as separate repeated windows, **not an atomic shared
snapshot or proof they remain constant after the session**. Even two equal
values do not rule out intervening changes. Nonzero hook pointers are evidence
to review off-ring, not permission to execute them or extend the capture.

The fixed state addresses come from already archived code, never from this
session's returned values. No adjacent fields, MMIO/FIFO, other bank, key field,
arbitrary pointer or on-device inspected-code execution is admitted. There are
no sensor-start/stop, clock/settings, DFU, reset, retry or reconnect operations.
CD01's reviewed connection/timer/activity bookkeeping side effects still apply;
do not call this a zero-side-effect operation.

## Failure and evidence contract

Any local reference mismatch, unexpected identity/state, changed known code,
changed repeat/postcheck, timeout, malformed/foreign/duplicate traffic or failed
disconnect aborts the session without a success JSON. No automatic retry.
The reader is poisoned/closed even on cancellation and cannot be reused.

The successful schema would be `whip.rom-support.capture.v1`, stored in
`rom-support.json` only after exact budget and disconnect validation. It retains
`timer_state_immutable=false`, `physical_timing_verified=false`,
`full_image_attestation=false`, `recovery_verified=false`, `flash_authorized=false`.
After capture, stop device work and review only the returned bytes off-ring.
Unknown callees stay unknown; a bounded code window need not contain a whole
function and must not trigger automatic follow-up reads.

## Off-ring preflight

134 new tests pass using fake transport and synthetic newly-read values. They
check the exact seven windows/order/budget, all known comparisons on both reads,
all new repeated values including live-state changes, local/reference and final
postcheck failures, six transport faults in each new phase, mutual exclusion
with every earlier CLI plan, fresh confirmation, disconnect and late traffic.
Injected failures assert they reached their intended phase. Returned values
shaped like MMIO/key addresses are preserved but never followed. A separate
instruction decoding check establishes the fixed call/literal origins from the
hash-pinned prior captures.

The original25Hz/V2 CD instructions copy the first/last chunk of each new window
under three synthetic dispatch states. Target values are fake and are not
executed. This proves selected dispatch/addressing behavior, not actual ROM
accessibility, physical sensor state, UART independence or flash readiness.

No complete health binding, memory/stack ownership, physical recovery route,
fresh-source model qualification, step trial or overnight sleep comparison is
provided by preflight. Construction and production gates remain closed.

## Full guarded capture/execution result

`firmware/unified/build-20260923-support-execution-v1/` passed **2323 tests in
163.21 seconds**, zero skips/failures/errors/xfails. All **219 hashes** checked:
149 inputs, 67 artifacts and three reports. All 60 new archive/execution cases
are included. Manifest SHA-256:
`88d44cd1317cd44f891b4b1f1739d9cd85e7549fb4f2d5907070e4263c2d0c2f`.
Both ARM ELFs exactly match the prior preflight hashes below. No firmware C,
stock bytes, compiler flags, RAM reservations or installed image changed.
Components remain 9272/9520 configured bytes, 248 remaining, and combined state
796 bytes; full integration fit and ownership remain unapproved. `flashable`,
`stock_linked`, `hardware_access` and `ram_ownership_verified` stay false.
No simulator rerun, phone deployment, commit or push occurred. The full suite
includes compiled Swift, native sanitizer and ARM checks, not physical health
continuity. The completed device session was only the bounded read above.

## Historical full guarded preflight result

`firmware/unified/build-20260923-support-preflight-v1/` passed **2263 tests in
193.45 seconds**, zero skips/failures/errors/xfails. All **215 hashes** verified:
145 inputs, 67 artifacts and three reports. The 134 new diagnostic cases are
included and all executed. Existing plan/archive replays also remain in the
guarded suite; no compatibility behavior was disabled to admit this plan.

Manifest SHA-256:
`a678ed40037b31fd5835f45ec7042b3c2c9359e9bf411972f92d789ac1ace4d4`.
Both ARM ELF hashes are unchanged from the preceding execution build:

- Test ELF: `2e66a8133a753103ff412dd959d42d7e39bb177fc2c2120aaa344b9426a67b7e`.
- Stock-address ELF: `2c75d78867394ac4c9beb9ca18b3e4f5dca58c701884b64b92a65ac5720013e6`.

No firmware C, stock bytes, compiler flags, memory allocation, simulator/phone
deployment, device connection or firmware transfer occurred. Components remain
9272 configured bytes, with 248 remaining and 796 bytes of dispatcher/frame/
fence state; no complete-fit or ownership approval. `flashable`, `stock_linked`,
`hardware_access` and `ram_ownership_verified` remain false. This result permits
asking for a freshly coordinated diagnostic, not claiming the read has run or
the final firmware is ready.
