# Unified control/motion codec — offline candidate

2026-09-23. Continues the full Health-default, temporary-Gesture goal after
[workflow 3](UNIFIED_WORKFLOW_3.md). **No service registered, BLE transport
attached, capability unlocked, image constructed or ring accessed.**

Later follow-up: [UNIFIED_DISPATCH.md](UNIFIED_DISPATCH.md) now connects these
frames to the portable guarded adapter and owns command completion/replies.
Its combined guarded build passes 874 tests with zero skips. No real service or
hardware binding is attached; this codec's original results below are historical.

The previous goal turn was progress: the descriptor session and exact-code
witnesses changed the evidence. This continuation closes a different real
implementation gap: a bounded representation shared by firmware and the app.
It does not redefine the goal as merely passing a codec test.

## Scope and identity boundary

`firmware/unified/wire.{c,h}` and `ios/R02Ring/Health/UnifiedWire.swift` implement
matching candidate framing, validation and reassembly. Swift's checked conversion
to existing `ModeReply` lives in `UnifiedMode.swift`. A negative, incomplete,
wrong-operation or wrong-boot reply cannot become a published mode status through
that conversion.

This is for a **distinct future GATT service**, not a new UART command. `0x57`
below is frame magic, **not an allocated legacy opcode**. Do not send these bytes
to the current ring. No GATT UUID, attribute table, registration hook or approved
build identifier has been allocated. The production transport stays unattached.
The legacy 16-byte queue cannot carry these frames and is not used.

Before enabling a future service, the binding must establish an approved build,
its actual capability obligations, a nonzero stable-per-boot ID and a fresh
nonzero connection generation. Discovery must not speculate on legacy UART.
Build/boot declarations are not cryptographic image attestation. CRC is error
detection, not authentication or permission to control someone else's device.

## Frame layout

Every frame is exactly 20 bytes. Multi-byte integers are little-endian. CRC is
CRC-16/CCITT-FALSE: polynomial `0x1021`, initial `0xffff`, no reflection or final
XOR; `123456789` gives `0x29b1`. CRC covers bytes 0–17 and is stored low byte first.

| Bytes | Control request/reply | Motion |
|---|---|---|
| 0 | `0x57` magic | same |
| 1 | version 1 | same |
| 2 | 1 request, 2 reply | 3 |
| 3 | fragment index 0 then 1 | reserved, zero |
| 4–7 | nonzero request ID, repeated in both fragments | nonzero session |
| 8–11 | body fragment | nonzero sample sequence |
| 12–17 | body fragment | signed16 model X, Y, Z |
| 18–19 | CRC | CRC |

A control body is exactly 20 bytes: frame 0 carries body bytes 0–9 at frame
8–17, frame 1 carries body 10–19 there. Motion needs **one**, not two or three,
notifications per sample. This is a size calculation, not physical throughput
or delivery-loss validation. The eventual binding must prove a supported payload
size of at least 20 and actual scheduling/backpressure behavior.

### Request body

| Body bytes | Meaning |
|---|---|
| 0 | operation: 1 status, 2 return Health, 3 enter Gesture, 4 renew |
| 1 | reserved zero |
| 2–9 | expected boot ID, full 64 bits, nonzero |
| 10–13 | session for renew; zero for other operations |
| 14–17 | last successfully processed sequence for renew; zero otherwise |
| 18–19 | reserved zero |

Renew requires nonzero session and sequence. Runtime-generated sequences start
at one and exhaust rather than wrap; the codec does not fabricate processing
progress or allocate sample numbers. Admission still must compare session and
sequence to actual sent/processed state in the existing runtime.

### Reply body

| Body bytes | Meaning |
|---|---|
| 0 | exact echoed operation |
| 1 | result: 0 success, 1 unavailable, 2 busy, 3 invalid, 4 fault |
| 2 | mode: 0 Health, 1 Entering, 2 Gesture, 3 Returning, 4 Fault |
| 3 | charging: exactly 0 or 1 |
| 4–11 | boot ID, full 64 bits, nonzero |
| 12–15 | session; Health may retain the last session counter |
| 16–19 | reserved zero |

Entering/Gesture require a nonzero session. Gesture plus charging is invalid.
A successful Health command must report Health; successful Gesture/renew must
report Gesture. Thus accepting queued work cannot be encoded as a successful
mode transition. Status may report an intermediate or faulted state. Nonzero
results remain error replies, never `ModeReply` success or closed health coverage.
Actual physical completion is a separate binding obligation, not something a
valid byte layout can prove.

## Reassembly, timeout and replay boundaries

One assembler is bound to an expected kind, operation, request ID, boot ID and
connection generation. Only index 0 then index 1 is accepted. A malformed CRC,
wrong length/version/type/ID, duplicate, reordering, stale generation, wrong boot,
reserved-byte violation or timeout poisons it and clears buffered body bytes.
It cannot silently restart on another first fragment. A second publication after
completion is rejected. A new assembler needs a deliberately rebound exchange.

The fragment assembly deadline is 1000 ms with unsigned monotonic wrap semantics.
`begin` starts that deadline; a caller expecting a long physical transition can
begin assembly when the first **already-correlated** reply fragment arrives.
It must separately enforce the complete operation deadline and reject late
responses after cancellation. Timeout is checked on feed; a real adapter must
also time out stalled I/O when no next frame arrives. Motion must be demultiplexed
to its own handler/characteristic, not fed into the control assembler.

This component does **not** allocate IDs, cache/re-execute requests, provide a
queue, serialize RTOS work, or prove boot entropy. The future binding must:

- never reuse a request ID during a connection and fail on exhaustion;
- capture callback generation when queued, not stamp old data on delivery;
- prevent stale/retried requests from performing a second transition;
- maintain at most the explicitly owned control exchange and bounded queues;
- preserve backpressure and cleanup if either reply fragment cannot be sent;
- check firmware session immediately at actual enqueue, and fence old enqueues;
- continue the existing independent firmware lease/cleanup during phone loss.

C callers own valid contexts and non-overlapping, sufficiently sized buffers:
20-byte body, 40-byte control output, 20-byte motion output and three int16 axes.
Public decoders verify lengths before reading input fields. No allocation, I/O,
timer, sensor command or direct stock address appears in this codec.

## Motion and the finalized model

Motion carries model-axis signed counts without rescaling: `(X,Y,Z) = (w2,w0,w1)`
for reviewed native FIFO words, with 8005 counts/g. Its little-endian fields are
deliberately distinct from legacy A1/03's big-endian fields. Never send it through
the legacy packet decoder or infer a format from only the leading byte.

Boot ID is bound by the approved connection/control context, not repeated in
each motion packet. The binding must invalidate the entire stream on disconnect,
boot change or unresolved identity and cannot relabel an old BLE callback with
the current generation. The decoder checks representation/session only; strict
sequence advance, sample freshness, committed Gesture and inference completion
remain mandatory separate checks. CRC-valid, changing data alone do not satisfy
the source gate. No physical source profile or new model accuracy is claimed.

## Evidence and remaining work

`tests/test_unified_wire.py` executes compiled ARM instructions under the existing
strict artificial-address harness, including stack/register/memory guards. Its
reference frames use Python's independent `binascii.crc_hqx`, not a port of the C
loop. Tests compile the whole Swift codec and compare 240 control scenarios and
256 motion scenarios, with boundary/random values, old identities, corruption
and incomplete/incorrect control messages. A single motion frame is tested at
all 160 single-bit corruption positions. Initial scoped run: **45 passed**.

`ios/R02RingTests/UnifiedWireTests.swift` passed **5/5** on iPhone 18 Pro / iOS 27
simulator. It checks conversion into the existing app mode types, refusal of
negative/intermediate completion, connection/order poisoning, clock wrap and
signed motion values. Result: `/tmp/whip-wire-20260923.xcresult`. No physical phone
was deployed or used. The full combined build and simulator results appear in
the completed validation record below.

Remaining end-state gates are unchanged: actual producer/result closure and
serialized hardware bindings; physical FIFO timing/completion/overflow plus
model validation; physical optical STOP/current-settings resume and steps/sleep
continuity; approved flash/RAM placement and recovery; service registration and
live transport/boot identity. This codec is not the missing runtime dispatcher
or GATT driver. No image may be flashed based on these tests.

External recheck in this continuation: the compatible vendor-derived
[timer API](https://raw.githubusercontent.com/atc1441/ATC_RTL_BLE_OEPL/49301d9b75816ccde1cc9657b827fdadf5736937/ATC_RTL_BLE_OEPL_8762ESL/sdk/inc/os/os_timer.h)
documents stop/delete results, not a sufficient callback-drain receipt for this
ring. Other projects' reported fast sensor streams do not qualify this ring's
unchanged Health source. No outside firmware or probe script was executed.

## Completed validation record

- Guarded build: **793 passed in 117.99 s**, zero failures/errors/skips; exact
  collected/executed identities and phase outcomes agree. Output is
  `firmware/unified/build-20260923-wire-v1/`, never an OTA image.
- All component/support objects were double-compiled and the test ELF double-
  linked with identical bytes. All **105** source/artifact/report hashes were
  rechecked afterward. Older workflow3 manifests are historical after these edits.
- Test ELF SHA-256:
  `58d9618d0774cfb759c98bc63c30a1f7228ee180646ee5dc6900ee8cfa5abcea`.
- Manifest SHA-256:
  `f29a5c2a303e7285111b409af050a03f4567ac5729a923e2f27644b5cacecd5b`.
- The codec contributes 1058 `.text` bytes; eight component objects total 6786
  before real hooks/transport, compiler helpers, alignment and metadata. This is
  not a linked-placement approval, full stack budget or proof the finished image fits.
- Full iOS simulator suite: **58 passed, zero failed/skipped/expected failures**,
  including the five new integration checks. Result bundle:
  `/tmp/whip-unified-wire-full-20260923.xcresult`; the extracted authoritative
  summary is archived at
  [`wire-simulator-summary.json`](../firmware/research/2026-09-23/wire-simulator-summary.json).
- `git diff --check` passed. Existing production client/manager/runtime adapter
  contain no calls to the candidate codec; production discovery remains absent.

Next implementation work is the bounded request dispatcher, reply ownership and
actual service/notification binding. They must execute against the reviewed
stock registration/queue/ABI paths and retain every open hardware gate. No flash
approval or claim of completely risk-free firmware follows from this record.
