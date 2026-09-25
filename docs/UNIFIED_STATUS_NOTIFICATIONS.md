# Status notifications and the interrupted create-hook read

2026-09-23. Entirely off-ring investigation following the requested reconnect.
No new BLE session, sensor operation, firmware write, hardware binding or
construction approval. Health remains the unified default; installed V2 is
unchanged and still globally optical-off.

Subsequent separately requested device session: the updated fixed code reader
completed all 359 transactions with repeated equality/postchecks and verified
disconnect; see [the create-hook record](UNIFIED_CREATE_HOOK_READ.md). No foreign
notification occurred, so this does not identify the first failure's subtype or
cause. The metadata-only passive observer v2 still has not run. The implementation
and its original build record below remain an off-ring historical snapshot.

## What the physical record actually says

The [aborted create-hook read](UNIFIED_CREATE_HOOK_READ.md) connected and
accepted 169 replies. Request 170 was still a known prerequisite. An unexpected
16-byte notification starting with `0x73` caused a terminal abort and verified
disconnect. No new code window or successful capture resulted.

That original log deliberately retained no payload, subtype or checksum-validity
field. They cannot be recovered from the command byte or invented from local
code. In particular, the type does **not** establish another client's presence,
a sensor start, a dead battery, an RTOS failure or a harmless event. The exact
physical cause is still unknown. The original archive and its hash are unchanged.

## Exact-image constructor evidence

The three pinned images contain these selected packet constructors. Addresses
are **file offsets**, not runtime addresses; the established runtime bias is
`0x825fb0`. Original25Hz and V2 share the reviewed offsets below, not the stock
offsets.

| Selected operation | Stock 3.12.02 | Original25Hz / installed V2 |
|---|---:|---:|
| Status constructor with getter-selected fields | `0x66b6` | `0x646e` |
| Status constructor with one supplied value | `0x67a6` | `0x655e` |
| Status constructor with at most 12 supplied bytes | `0x67d0` | `0x6588` |
| Actual additive checksum helper | `0x3fe8` | `0x3eec` |
| Transport boundary, **intercepted in these tests** | `0x7e30` | `0x7c0c` |

Each constructor initializes a 16-byte packet, writes `0x73` in byte 0 and its
subtype in byte 1, adds fields in bytes 2 onward, and computes the checksum in
byte 15. The buffer variant caps copying at 12 bytes and leaves byte 14 zero.
Thus `0x73` is a shared status/event family, not a unique error or sensor type.

`tests/test_status_notification.py` executes the exact unmodified instructions
and actual checksum helper for stock, original25Hz and V2. All 256 subtype
arguments exercise the first constructor. The supplied-value and buffer
variants cover zero, boundary and oversized arguments. Getters return explicitly
synthetic values; only the two-byte field for subtype `0x28` is a fixed RAM
fixture. Reads/writes and execution have narrow allowlists. BLE/queue delivery
is intercepted, not executed or asserted successful. This proves packet layout,
not the physical meaning, acquisition provenance or schedule of any value.

Selected exact direct-call witnesses include:

| Caller family / existing audit | Stock call and subtype | V2 call and subtype |
|---|---|---|
| Motion/Health consumer | `0xcefa`, `0x12` | `0xce98`, `0x12` |
| SpO2 result aggregation | `0xe0fa`, `0x03` | `0xe036`, `0x03` |
| Device-state setter | `0x2c4e`, `0x0c` | `0x2bee`, `0x0c` |

These sites show why the command alone cannot select one cause. They are not an
exhaustive direct/indirect caller inventory, do not imply each path runs on V2,
and do not identify which path produced the archived notification. Unlike
subtype `0x12`, subtype `0x03` in the first constructor carries no additional
getter value; it still reports an event. Do not mistake no in-packet measurement
for no associated Health work.

## Logging improvement, not a relaxed acceptance policy

`protocol.notification_metadata` returns command, length, checksum validity,
and `status_subtype` **only for a complete checksum-valid 16-byte `0x73` packet**.
For malformed packets and every other family, subtype is null. It never returns
bytes 2 onward, the checksum value, a payload hash, or other encoded health data.
Callers add host monotonic time; no ring clock/settings are changed.

The fixed code/config readers still poison and stop on **every** unrelated
notification, including all valid `0x73` subtypes. Before-read, pending-request
and after-reply tests verify terminal behavior, no second request, and redacted
logs. No filter, retry, silence command or sensor-stop command was added. Read
addresses, order, prerequisites, deadlines and the 359-request budget are
unchanged. The improvement cannot retrospectively enrich the failed archive.

The separate passive observer uses the same metadata, with plan identifier
`passive-notification-types-v2`. It still reads DIS, subscribes for at most 60
seconds / 120 notifications, sends zero UART commands, refuses stream/diagnostic
traffic, unsubscribes and verifies disconnect. Observed silence does not prove
inactivity. This updated observer has **not run on the ring**.

## Implications for the unified binding

The result-publication inventory must account for status constructors as well
as scheduled aggregation, realtime replies and deferred pointer writes. Some
`0x73` subtypes are Health-related, others device status; blindly blocking or
allowing the entire family would not establish correct health continuity.
Generation/commit checks must cover the actual relevant publication lifetime,
including already queued packets. The existing stock transport audit's queue
limitations remain; packet construction is not a delivery or drain receipt.

No production guard or completed inventory was added here. Safe Health pause/
resume, physical STOP, memory/recovery and fresh-source/model/steps/sleep gates
remain open. Further device access needs one newly coordinated bounded session;
the last aborted process is terminal, not a live test to poll or auto-restart.

## Guarded verification

`firmware/unified/build-20260923-status-metadata-v1/` passed **2491 tests in
145.36 seconds**, zero skips/failures/errors/xfails. All **224 hashes** matched:
154 inputs, 67 artifacts and three reports. The 35 new constructor/metadata/
terminal/archive cases plus one passive-observer case are included in that
total, not additional. The focused four-file run passed 226 tests in 3.84 seconds;
20 separate existing protocol/cleanup tests passed in 5.37 seconds.

Manifest SHA-256:
`f074b21c1756c732e643852d8dcc80820538f8fd6448a190f5bad4c664186267`.
Both ARM ELFs remain byte-identical to create-hook preflight v2:

- Test: `2e66a8133a753103ff412dd959d42d7e39bb177fc2c2120aaa344b9426a67b7e`.
- Actual-address: `2c75d78867394ac4c9beb9ca18b3e4f5dca58c701884b64b92a65ac5720013e6`.

No firmware C, compiler flag, stock byte, placement or RAM allocation changed.
Components remain 9272/9520 configured bytes, 248 remaining; combined dispatcher/
frame/fence state remains 796 bytes, without approved fit/ownership. `flashable`,
`stock_linked`, `hardware_access` and `ram_ownership_verified` remain false.
No phone deployment, simulator run, device access, commit or push occurred.
