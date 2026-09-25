# Bounded firmware diagnostic evidence

## Create-hook diagnostic — separate requested retry completed

After the user explicitly requested a new connection, the unchanged fixed plan
completed all **359 matching CD01 transactions**. It repeated 279 prerequisites,
read the fixed 52-byte non-secret patch prefix and 384 bytes of RAM/ROM code
twice, passed final state/header/config/idle checks and verified disconnect.
No unexpected notification, retry, sensor or flash command. Exact archive replay
passes. See [the success archive](rom-create-hook/README.md). The first failed
session below remains intact and its unrecorded subtype remains unknown.
Code capture does not establish safe physical creation/resume or recovery;
further device access needs new coordination.

Later off-ring captured-body execution adds 121 cases through the real hook
and comparator; current guarded build passes 2613 tests, all 228 hashes checked,
with both ARM ELFs unchanged. Hook success creates an inactive timer; failure
with an empty handle reaches unread `0x111a6`. Synthetic pool/list/critical
boundaries and physical resume/recovery gaps remain. Details:
[create-hook audit](../../../docs/UNIFIED_CREATE_HOOK_READ.md#captured-body-execution--2026-09-24).

## Create-hook diagnostic — connected, prerequisite read aborted

The user requested one reconnect. BLE/DIS succeeded, followed by 170 CD01
requests and 169 accepted replies. Unexpected notification type `0x73` aborted
the prerequisite read at `0x1409a`; its payload was not retained. Disconnect was
verified; no retry, sensor command or flash occurred. **No new header/hook/
comparator window was requested**, no final postchecks ran and no success capture
exists. See [the exact failure archive](rom-create-hook-aborted/README.md).
All 222 preflight hashes and 132 selected tests passed before connection.
The notification's cause is unknown; further access needs new coordination.

## Support-code/state diagnostic — separate retry completed

After the battery-only connection reported 99%, not charging, the user requested
testing again. The fixed support retry completed all 284 CD01 transactions:
616 new ROM bytes and 17 fixed state bytes read twice, known-code and final
idle/config checks passed, disconnect verified. Exact archive replay passes.
Create/start/restart hook snapshot is `(0x205c01, 0, 0)`; the nonzero target
was not read or followed. See [the success archive](rom-support/README.md).
No sensor/flash/reset or target-execution operation; no construction gate opened.
This session has ended and grants no continuing device authorization.

## Support-code/state diagnostic — discovery failed

After renewed client-closure confirmation, the fixed support plan could not
find the expected BLE identifier. Zero CD01 commands, no connection or DIS
read, no success capture, no sensor/flash command and no automatic retry.
The process exited 2; the cause of unavailability is unknown. See
[the exact failure archive](rom-support-not-found/README.md). All new support
windows remain unread and further device work requires renewed coordination.

## Timer create/start/restart code — completed

After fresh exclusive-idle confirmation, `rom-timer-resume/` captured 452 new
ROM bytes twice, with 180 matching CD01 transactions, matching prerequisites/
known STOP/configuration/idle postchecks and verified disconnect. All replies
replay through the unchanged reader and reproduce the capture. No sensor-start,
flash, new hook-state RAM, key/MMIO/FIFO read or target execution. Captured
literals locate three optional hooks but do not establish their current values.
See [the archive](rom-timer-resume/README.md) for hashes and evidence limits.
The session ended; further device access requires new coordination.

## Consolidated ROM read — separately requested retry completed

After explicit user request and renewed client-closure confirmation,
`rom-integration/` captured all **6076 fixed ROM-code bytes twice**, with **974
matching CD01 transactions**, passing identity/configuration/idle prerequisites
and postchecks, and verified disconnect. No unexpected packet recurred; no
sensor, flash, key-field, MMIO/FIFO or target-execution command was sent.
All captured replies replay through the unchanged reader and reproduce its
saved result. This supplies code for offline analysis, not hardware integration
or recovery approval. The earlier failed and passive sessions below are retained.

## Passive notification follow-up — completed

`idle-notifications/` records a separately coordinated **60-second listen-only
connection**: zero UART notifications, zero UART commands, verified disconnect.
DIS identity matched the expected strings; no code/sensor/flash command was sent.
The prior interruption did not recur, but its unknown type/cause is not resolved
by a quiet interval. No code-read retry or relaxed diagnostic filter followed.
Transcript SHA-256:
`e459b22c6edc55800c03d2401f0190d300de8ad37f2eaab2760a9d89cf0f2cf6`.

## Consolidated ROM read — aborted

`rom-integration-aborted/` preserves a later, separately coordinated attempt:
189 CD01 requests, 188 matching replies, terminal abort on unrelated UART
traffic. Only 1302 new ROM bytes were returned once. No new window passed its
repeat/postcheck gate, no success capture exists and there was no retry. The
original abort log omitted packet type and verified disconnect state; neither
may be invented retrospectively. See its README for exact scope and hash.

## Boot-reference comparison

`reference-boot/` retains only the non-secret header prefix and code from the
pinned SDK-origin external reference, not a ring factory/recovery image.
`boot-reference/` preserves the separate fresh idle-session capture: 182 matching
CD01 transactions, repeated header/code equality, identity/configuration/idle
postchecks and verified disconnect. The ring's 52-byte non-secret prefix and
528-byte code match the reference exactly. No key field was read; no sensor or
flash command was sent. No returned pointer was followed and no target code was
executed on the device. CD's known bookkeeping side effects remain.

| File | SHA-256 |
|---|---|
| `boot-reference/boot-reference.json` | `f9798ed89e9d2e5b055a2fd5f930be635621e7ec7f35e0e0ada6bd82e36b8aed` |
| `boot-reference/transcript.jsonl` | `e5391cc14ccb75d3f196316bf05af54d26b685a5ecd39d1e142118c7b23d1925` |
| `reference-boot/rtl8762e-sdk-boot.json` | `2fe73838cc94264ac43ea5c5cef99290e0a3d1ac266b266cd047230826e0ecb8` |

The component checks/selects factory/OEM configuration. Matching it is not full
boot/recovery evidence or permission to transplant the SDK board's different
flash/RAM map. See [the boot comparison](../../../docs/UNIFIED_BOOT_REFERENCE.md)
for exclusions, actual-code/mock boundaries and remaining flash blockers.

## Bank0 descriptor session

One newly coordinated session, after the user confirmed all clients closed and
the ring idle. No stream, sensor start, register/FIFO read, flash or reset was
requested. The diagnostic `CD 01` handler does perform known activity/timer and
connection-policy bookkeeping, so this is not a wholly non-mutating protocol.

`bank0-descriptor/` preserves the exact original generated artifacts from
`data/capacity-20260923-bank0-descriptor/`; their SHA-256 values are unchanged:

| File | SHA-256 |
|---|---|
| `configuration.json` | `ba6f56f927bae69ad8144673b878970ea0279a9e96ad89b986f0e76891e58dd7` |
| `report.json` | `604fe44e0ac19b9e510abfd9d47a4dfa285ac23ca2c46dd169263f113aa51762` |
| `transcript.jsonl` | `9b98a908895249d2987ff675b7ebf340898f67437e3f2f5bc8e6f08a6d666043` |

The fixed reader repeated identity/configuration/idle checks, read only the
80-byte descriptor at `0x802198` twice, rechecked configuration/idle, then
disconnected. All 91 request/reply pairs matched. Returned pointers were not
followed. The image hash in the capture identifies the sampled-code reference,
**not** a complete hash read from the installed ring image.

The application descriptor declares `0x826000..0x84a000` (144 KiB), a configured
9520-byte margin beyond the stock inner image. This does not authorize expansion,
prove physical erase geometry, reserve RAM or establish recovery behavior.
Parser approval flags deliberately remain false. See
[workflow 3](../../../docs/UNIFIED_WORKFLOW_3.md) for the code cross-checks,
test manifest and remaining physical gates.

## ROM timer-wrapper session

`rom-timers/` preserves the separately authorized daily-ring diagnostic from
`data/rom-timers-20260923-01/`. After repeating prior identity, configuration,
idle and descriptor gates, the reader checked the 16-byte application ROM
identifier twice and read exactly 72 bytes at `0x136bc..0x13704` twice.
Postchecks matched; all 114 CD01 transactions matched; disconnect was verified.
No sensor command, flash, MMIO/FIFO access, target execution or pointer following
occurred. CD bookkeeping side effects remain; no brick-rate claim follows.

| File | SHA-256 |
|---|---|
| `rom-timers.json` | `4290a08b6703c6b3e2ddf262285a28100368253ccff6a46b9116d31df039f16d` |
| `transcript.jsonl` | `fa32687d8e7f15a83c721ff2678f1fc9273d1245eea08b514bc42a9854962a78` |

The wrappers consult optional indirect hooks and otherwise call unread ROM
implementations. Actual hook locations/values and callback-drain behavior remain
unknown. Provenance and executed/mocked boundaries are in
[the ROM diagnostic record](../../../docs/UNIFIED_ROM_DIAGNOSTIC.md).

## ROM defaults and hook-state follow-ups

After renewed user readiness, two separately selected plans repeated all earlier
prerequisites. `rom-timer-internals/` adds two ROM literals and 172 bounded code
bytes: 142 matching transactions. `rom-timer-hooks/` rechecks those exact bytes
then reads only the two identified SRAM function-pointer slots: 144 matching
transactions. Both sessions repeated new windows, passed configuration/idle
postchecks and verified disconnect; no flash, sensor command or target call.

| File | SHA-256 |
|---|---|
| `rom-timer-internals/rom-timer-internals.json` | `79fe567846b308a081d6820ce552b45fba107470f2258035d67e4cd2d1c88525` |
| `rom-timer-internals/transcript.jsonl` | `cd7bee72e54f8a3d346c8b835e0eed4cf29c8c4cfaa6c99741b622f1a774f9c7` |
| `rom-timer-hooks/rom-timer-hooks.json` | `1551f253f43fbd3b852f866ea76da07084c503124406ae38a3acbdfbb028de53` |
| `rom-timer-hooks/transcript.jsonl` | `9bc112033d125cbd9d0da037e4ed085f8a4751522e0518dcb1f8cf7f8133f504` |

Both hook slots were zero twice, selecting the captured default bodies in that
idle snapshot. Defaults delegate to `xTimerGenericCommand`; delete clears the
handle on nonzero return. Its implementation, other external state and callback
drain remain unproved. Tests replay all captures and execute the captured callers
with explicit unread-boundary mocks. This is not physical shutdown or recovery
proof. The user was told clients could reopen; further device work needs new
coordination. The full diagnostic record above distinguishes all scopes.
