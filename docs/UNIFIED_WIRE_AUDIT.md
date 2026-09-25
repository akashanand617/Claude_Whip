# Unified firmware: stock wire audit

2026-09-23 follow-up: [the offline C/Swift codec](UNIFIED_WIRE_CODEC.md) now
defines candidate framing for a **distinct future GATT service**, never the
legacy UART dispatcher. No production opcode, UUID, service registration or
transport is enabled. The audit below records the original 2026-09-22 findings;
its warning against speculative UART commands remains in force.
The later [stock transport proof](UNIFIED_STOCK_TRANSPORT.md) executes registration,
send wrappers and the queue overflow/wake/connection hazards described below.
Its new exact-stock call shim remains unattached; no service is registered.

2026-09-22. **Offline research only. No unified wire opcode or codec allocated,
no image built, no BLE/phone operation, and no gate unlocked.** This concerns
the Health-default design, not the historical optical-off V2 firmware.

## Result

There are opcode values absent from both stock dispatch switches, but **none
is a safe speculative capability query**. The fast dispatcher runs a stateful
prelude before its default error reply. Unknown `A1` subcommands are worse:
they clear two legacy mode bytes. Future unified commands must be intercepted
before that prelude, and the host must first identify an approved unified image
through a separately reviewed mechanism. A version string is not exact identity.

The existing notification helper copies exactly 16 bytes into an unchecked
128-slot queue. It supplies neither trustworthy enqueue acceptance nor delivery
acknowledgment. The current Swift `ModeReply` cannot fit in one such frame even
before framing. Correlation, fragmentation, backpressure and serialized callback
ownership must be designed before allocating a production codec.

## Evidence boundary and reproduction

Only `firmware/rt02cr-stock-3.12.02.bin`, 138016 bytes, SHA-256
`b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0`.
All code addresses below are **file offsets**; runtime = file + `0x825fb0`.
RAM addresses are explicitly labeled. Do not transplant offsets from V2/25 Hz.

`whip/fwcommands.py` is a read-only, whole-file-hash-bound branch/data-flow audit,
not a codec, patcher or BLE client. It decodes the actual Thumb instructions for
both opcode trees, the two compiler switch tables and three short witness slices.
It rejects unmodeled instructions/accesses and bounds execution to 100 instructions.
It starts after reviewed prologues and stops before handlers/epilogues; it does
**not** emulate the CPU ABI, stack, scheduling, ROM or hardware.

```sh
.venv/bin/python -m pytest -q tests/test_fwcommands.py
```

Result: **11 passed**, including all 256 fast routes, all 256 queued routes, all
256 prelude-state values, all 256 `A1` subcommands, and 2,048 length/state cases.
Whole-image mutations, including switch-table/helper mutations, are rejected.
The archived `firmware/research/2026-09-22/fwmap.py` aided navigation; explicitly
construct `Image(stock_path)` because its CLI default is the different 25 Hz image.
Its heuristic function boundaries and linear decoding of jump-table data are
not evidence of executable instructions.

## Receive chain

```text
registered UART write callback 7ace (table pointer at 1f308)
  attribute index r2 == 2, non-null data
    5c22: RAM208c44 != 1 AND length == 16
      tail branch 5c2e -> 5882: fast dispatcher
        except opcodes43/48: 5890 -> 8112 stateful prelude
        direct handler / inline leaf / silent return / default NAK
        selected commands: 5c0c -> 4cbc copies into command queue
          RAM209d50, ten 16-byte slots, semaphore wake 1178
          main-loop call1366 -> 657c queued dispatcher
            A1: call6688 -> handler2104
```

Registration `0x7b40` passes the attribute database at `0x1f25c`, length `0xa8`,
to `0x15824` at `0x7b5a`. It contains the UART write/notify UUIDs ending
`...0002` / `...0003`. Callback pointer slots are `0x1f304` read (`0x7aa4`),
`0x1f308` write (`0x7ace`), `0x1f30c` CCCD (`0x7b22`), with Thumb bit set.
Their exact values are `0x82da55`, `0x82da7f`, `0x82dad3`. The primary service
UUID at `0x1f24c` is `6e40fff0-b5a3-f393-e0a9-e50e24dcca9e` (16-byte
little-endian representation `9ecadc240ee5a9e093f3a3b5f0ff406e`).

Lifecycle anchors: boot/setup function `0x09dc` calls `0x76b8` at `0x09fc`.
`0x76bc` calls `0x1580a` with argument5; `0x76c2` registers this service via
`0x7b40`, passing common application callback pointer `0x82ced9` (file`0x6f28`).
Registration success stores that callback at RAM`0x209e44` (`0x7b64`) and
returns the assigned service ID; `0x76ca` stores it at RAM`0x209e1b`, the same
ID read by the UART notifier. Failure returns`0xff` at `0x7b78`.
`0x15824` delegates registration to ROM `SystemCall_Stack`, service code`0x3102`.
The setup also registers other services and calls `0x7f10` at `0x77a2`.
These anchors do not prove safe dynamic registration or SDK table lifetime rules.

The read callback has a special index7 path at `0x7ac0`: data pointer
RAM`0x208528`, length RAM`0x208526` minus1. It is existing opaque behavior,
**not evidence of an available capability characteristic**. The CCCD callback
`0x7b22` logs; application-level subscription gating is not established here.

`0x7ace` saves 16 bytes. `0x7ad0` loads the data pointer from incoming stack
argument +4; `0x7ad6` loads length from incoming stack argument +0. The compared
register `r2` is the attribute index. Null data returns `0x40d`; an unsupported
index returns `0x40a`; index 7 logs and returns success without command dispatch.
Do not infer the unnamed SDK callback parameters from these observations.

Gate bytes at `0x5c22` are `fe4a1278012a02d0102900d128e67047`.
There is no application-level RX checksum check in this mapped callback,
length gate, fast tree or queued tree. Individual handlers/ROM are not exhaustively
audited for all validation. BLE link integrity is not a custom packet checksum.
The proposed gateway must validate its own framing; legacy behavior stays intact.

### Stateful default path: executable negative witness

At `0x5890`, all outer opcodes except `0x43`/`0x48` call `0x8112`, **including
unrecognized opcodes and explicit silent returns**. `0x96e0` reads RAM
`0x20bbf8`. State 2 or 3 calls `0x80ee`, then `0x948a(0,0)`; every state writes
`1` to RAM `0x20a66c` at `0x8136`.

The bounded witness executes `0x8118..0x8136` after the state getter returns;
it records, but does not emulate, `0x80ee`/`0x948a`. The unconditional store is
therefore demonstrated without making claims about those helpers' further effects.
`0x80ee` can restart the timer at RAM `0x20a670`. Its immediate at **`0x80f8`
is the stock protected DFU reassembly timer**; preserve it. `0x948a` has further
state/timer behavior, not fully characterized here.

Default `0x59ce -> 0x4ade` produces a 16-byte error reply: byte0 is
`opcode | 0x80`, byte1 `0xee`, bytes2..14 zero, byte15 the byte-sum checksum.
It sends via `0x7e30`. A NAK is not proof that the request had no effect, and
high-bit response construction can alias an existing command family.

## Complete outer-opcode route map

Each row's columns are low nibble `0..f`. `N` = default NAK, `Q` = enqueue,
`H` = first handler call, `I` = inline/subcommand-dependent leaf, `S` = explicit
silent return. **174 NAK, 20 enqueue, 49 first-call, 5 inline, 8 silent**.

```text
     0 1 2 3 4 5 6 7 8 9 a b c d e f
00:  N Q H H H Q N N Q N H N H H Q N
10:  H N N N S Q H N Q H N N N N H N
20:  N H N N N H H H H N N H H N N N
30:  N N N N N N H Q Q Q Q Q H N N N
40:  N N N Q N N N N H N N N N N N N
50:  I H H N N N N N N N N N N N N N
60:  H H N N N N N N N H H N N N N N
70:  N N Q N N N N Q N N Q H H N N N
80:  N Q N N N N N N N N N N N N N N
90:  H H H H H H H H H H H H H N H H
a0:  H Q N N N N N N N N N N N N N N
b0:  S N N N N N N N N N N N N N N H
c0:  H S S I H I Q Q I S N N S H H N
d0:  N N N N N N N N N N N N N N N N
e0:  N N N N N N N N N N N N N N N N
f0:  S S N N N N N N N N N N N N I Q
```

The first switch helper call is `0x58a4 -> 0x1a378`: max/default-index byte
at `0x58a8` is 39; entries at `0x58a9..0x58d0`; index is opcode. The second
call is `0x5940`, max byte `0x5944`, entries `0x5945..0x596c`, index is
`uint32(opcode - 0x7a)`. Thus `0x78/0x79` underflow to default, not a negative
index. Helper `0x1a378..0x1a390` clamps index to max and branches to
`(entries_start + 2 * unsigned_entry) & ~1`.

### Fast handler leaves

This is the **first** non-prelude/non-switch call, not an exhaustive transitive
call graph. The executable test pins both call site and target for every row.

| Opcode | Call site → target | Opcode | Call site → target |
|---|---|---|---|
| 02 | 5a2e → 554a | 03 | 5a56 → 4aa0 |
| 04 | 5a5e → 54a6 | 0a | 5a3e → 480c |
| 0c | 5aaa → 4fdc | 0d | 5aba → e7ae; then 5abe → 4fa2 |
| 10 | 5a36 → 47f4 | 16 | 5a92 → 50ba |
| 19 | 5a4e → 54f8 | 1e | 5ade → 4e4a |
| 21 | 5ac6 → 4ed6 | 25 | 5ace → 4ec6 |
| 26 | 5ad6 → 4e9a | 27 | 5a0a → 5742 |
| 28 | 5a16 → 5706 | 2b | 5a46 → 48a0 |
| 2c | 5a9a → 5062 | 36 | 5aa2 → 5010 |
| 3c | 5a26 → 5582 | 48 | 5ae6 → 4d76 |
| 51 | 59ea → 580e | 52 | 59fa → 57b6 |
| 60 | 5af6 → 4cea | 61 | 5aee → 4d34 |
| 69 | 5a66 → 52a0 | 6a | 5a8a → 5138 |
| 7b | 5a1e → 55cc | 7c | 5a02 → 5756 |
| 90 | 5b36 → 1b8c | 91 | 5b3e → 1ba8 |
| 92 | 5b46 → 1bce | 93 | 5b4e → 1cfa |
| 94 | 5b56 → 1be8 | 95 | 5b5e → 1c0e |
| 96 | 5b66 → 1c36 | 97 | 5b6e → 1c5e |
| 98 | 5b76 → 1c7c | 99 | 5b7e → 1c80 |
| 9a | 5b86 → 1c82 | 9b | 5b8e → 1c86 |
| 9c | 5b96 → 1cb4 | 9e | 5b9e → 1d78 |
| 9f | 5bae → 1bd0 | a0 | 5ba6 → 1dca |
| bf | 5bb6 → 48c6 | c0 | 5bbe → 4924 |
| c4 | 5be8 → a864 | cd | 5c14 → 4c36 |
| ce | 5c1c → 4b02 | | |

Inline leaves, separately inspected:

- `50`, entry `0x5afc`: calls `0x3c18` at `0x5b04`, then `0x148fe` at `0x5b0e`.
- `c3`, entry `0x5bc4`: packet[2]==1 calls `0x71d2`; packet[1] selects calls to
  `0x948a` for values 1/2. Not a vacant namespace.
- `c5`, entry `0x5bfc`: writes packet[1]==1 to RAM `0x208c47`.
- `c8`, entry `0x5bee`: writes packet[1]==1 to RAM `0x208c48`.
- `fe`, entry `0x59da`: calls `0x1dfe0` with little-endian packet[1:3].

Silent opcodes `14 b0 c1 c2 c9 cc f0 f1` return at `0x5990` **after the prelude**.
Enqueued opcodes `01 05 08 0e 15 18 37 38 39 3a 3b 43 72 77 7a 81 a1 c6 c7 ff`
all reach `0x5c0c -> 0x4cbc`.

### Command queue and complete queued switch

`0x4cbc` copies 16 bytes synchronously into RAM `0x209d50 + 4 + 16*write`;
read cursor is u16 at +0, write u16 at +2, both modulo ten. No full-queue test
appears before copy/increment. Ten queued writes without a dequeue can alias
full to empty. Two other callers, `0x68a8` / `0x68ce`, synthesize internal `77`
commands; this is shared infrastructure. `0x4ce4 -> 0x1178` gives a semaphore
at RAM `0x208c90` when non-null. The caller's `r1=0x344` is not a message ID:
`0x1178` does not use it.

`0x657c` loops until read==write; unhandled opcodes advance/read-discard at
`0x6694`, without a reply. These are all queued cases:

| Opcode | Queued call site → target / special path |
|---|---|
| 01 | 6632 → 4966 |
| 08 | entry663e: packet[1]==0 → 664a → 16b0; ==1 → 6650 → 162a; else discard |
| 15 | 6600 → 6278 |
| 18 | 661a → 5fe2 |
| 37 | 6638 → 5d68 |
| 38 | 667c → 5d16 |
| 39 | 6682 → 5c9c |
| 3a | 6620 → 5f8a |
| 3b | 6626 → 5e8e |
| 43 | 65fa → 634a |
| 72 | 65ee → 3f8e |
| 77 | 6606 → 613c |
| 7a | 662c → 5de2 |
| 7c | 65f4 → 64f6 |
| 81 | 6614 → 60dc, r0=packet+1 |
| a1 | 6688 → 2104 |
| c6 | entry6656: packet[1]==6c calls16d2/37d0/382c/83c4; otherwise 6660 → 47b4(c6,1) |
| c7 | 6690 → cbd0, r0=packet+1 |
| ff | 660c → 6118 |

`05/0e` enqueue but are discarded here. Conversely `7c` has a queued case but
arriving UART `7c` runs a different fast handler. Therefore neither switch alone
establishes the complete UART namespace.

### A1 is not an extension point

Stock handler `0x2104` tests charging (`0x2dae`) then subcommands 1..8. Unknown
subcommands, or the charging rejection, store zero to RAM `0x209cb1` and
`0x209cb2` at `0x2146/0x2148`, then send `a1 ff` via `0x2160 -> 0x7e30`.
This path does not stop the raw timer. The unknown-subcommand witness executes
the noncharging comparison/store slice, not hardware or full handler behavior.

Stock raw start `a1 04` at `0x2220` disables masks via `0xdcea`, enables `0x800`
via `0xdd04`, stores mode4 at RAM `0x209cb1` and rawflag1 at `0x209cb0`.
Timer handle slot is RAM `0x209cc0`; `0x22a4 -> 0x3e04` installs callback
`0x1e4a`. `a1 05` clears mode/rawflag and stops at `0x2248 -> 0x3e30`;
`a1 02` clears mode and shares that timer-stop path. These differ from old V2
locations. Reusing raw start is not the Health-preserving unified adapter.

## Notification ABI, context and backpressure

| Function | Observed contract |
|---|---|
| `7e30` | r0 points to at least16 bytes. Copies exactly16 into owned RAM if connected; preserves r4/r5/r6/LR (16-byte frame); no meaningful acceptance return. |
| `71e6` | true only when RAM209e11==2; false makes7e30 silently return. |
| `7dde` | if RAM209e54 busy byte is0, set1 and submit event type14/subtype13 through8e8. |
| `8e8` | calls ROM os_msg_send_intern for application queues; can fail.7dde does not undo busy on failure. |
| `70ba` | event subtype13 switch resolves70f4 →7e64. |
| `7e64` | consumer clears busy, drains small frames then a separate larger queue; can delay and discard. |
| `7dc4` | r0=data,r1=len; passes connection ID RAM209e12, service ID RAM209e1b, attribute index4, data pointer, length, literal1 to158ee. |
| `158ee` | calls ROM SystemCall_Stack with service code3108; returns byte status, accepted as success only when==1 by7e64. |

The 16-byte source may be a stack buffer because the copy completes before
`0x7e30` returns. This does not make the helper ISR-safe or multi-producer-safe.
No locking/interrupt masking appears in the enqueue/wake routines. Existing
call sites include fast callbacks and deferred handlers; that establishes use,
not the thread/interrupt ownership or an SDK concurrency guarantee. Full event
queue capacity, SDK lifetime rules and reentrancy remain unproven.

Small TX queue layout: RAM `0x209e54` busy byte; +1 retry byte; +2 u16 read;
+4 u16 write; +6 frames (`128 * 16` bytes). `0x7e42..0x7e5c` never compare the
next write against read. **128 enqueues without a drain alias full to empty;
more writes can overwrite unsent frames.** This is a static control/data-flow
inference, not a physical stress test or an executable queue witness.

Consequently, the new runtime's `wr_next` / `wr_sent` one-inflight contract
must not be adapted as `7e30(frame); wr_sent(..., true)`: enqueue is void-like,
can discard when disconnected, and may lose/overwrite frames later. One-inflight
limits only the runtime's own pending sample; it does not bound other stock
producers using this shared queue. A reviewed adapter must establish a precise
acceptance/completion observation tied to the pending session/sequence, bounded
queue ownership and loss/failure handling. `wr_sent` success is still not phone
processing; renewals require separately validated processed progress.

At `0x7e7e`, low-level return1 advances read and resets retries. Other returns
increment retry count while below20 and call `os_delay(20)` at `0x7e8e`; at
count>=20, `0x7e94..0x7e96` sets read=write, dropping the pending small queue.
The same retry byte is shared with the larger queue. Future wake scheduling
after failure is not completely proven. A lower-level accepted send is not
an over-the-air acknowledgment, much less processed inference at the phone.

`0x7f34` is a separate variable-length sender: `BC` framing, command, u16 length,
CRC16, fragmentation capped at `0xb6`, eight slots, service ID RAM `0x209e1c`.
It is not a drop-in larger UART reply. Its service/legacy collisions, ownership
and recovery interactions need a separate audit; do not repurpose it or DFU.

## Namespace and intercept policy — proposal, not allocation

`d0..ef`, for example, are default NAK in the fast tree and discard in the
queued tree on this exact stock image. This proves only absence of an existing
outer UART handler here, not vendor-wide reservation, safe legacy discovery,
response uniqueness or absence from other services. **No particular byte is
chosen by this audit.** Explicit silent opcodes and existing command families
are not preferred merely because they appear unused.

A future reviewed candidate should satisfy this policy:

1. Host enables the new namespace only after an approved, exact-unified-image
   identification policy passes. Unknown, stock, 25 Hz and V2 identities never
   receive new commands; disconnect/timeout invalidates authorization. Existing
   DIS version routing and `fwidentity` critical-site sampling are not full-image
   attestation. `CD01` reads do not write the requested memory, but on stock even
   opcodeCD runs `0x8112`; “read-only” must not be confused with zero side effects.
   No new identification mechanism is implemented or authorized here.
   A future **distinct read-only GATT characteristic/service** is a candidate
   discovery mechanism: discovering/reading its immutable protocol/build descriptor
   would avoid speculative legacy UART writes and their prelude. It still needs
   UUID allocation, registration/table/memory ownership, versioning and exact-image
   identity policy review. A self-reported image hash is not cryptographic
   attestation of the running image, nor does it prove the physical mode behavior.
2. Intercept after the existing pointer/length/state gate but **before**
   `0x5890 -> 0x8112`: semantically the `0x5c2e -> 0x5882` boundary. This is a
   routing location, not a reviewed patch-size/trampoline or RAM allocation.
   Non-unified packets continue exactly the original path. All packets in the
   allocated unified family, even invalid versions/checksums, terminate within
   the new validator; they must never fall through to legacy handlers.
3. Validate exact length, version, operation, reserved bytes, checksum, request
   correlation and session before admitting work. No sensor/optical transition
   runs inside the fast receive callback. Copy into separately bounded command
   ownership, prove serialization with the controller, and reject overflow;
   do not silently rely on the stock ten-entry overwrite-prone queue.
4. Reply only from committed controller state after physical postconditions.
   Enqueue/success acknowledgment, if any, is distinct from mode completion.
   Define backpressure, duplicate/idempotent requests, stale sessions, timeouts,
   reconnect, malformed fragments and priority versus 25 Hz motion explicitly.
   No ACK or sequence may claim phone processing; only validated/correlated
   processing progress may renew the lease under the chosen trust model.
5. Preserve all old routes and protected stock ranges, especially DFU timer
   `0x80f8`. Independently execute the actual linked gateway and complete wire
   adapter before image construction; this map does not satisfy that gate.

## Swift semantic contract: required integration decisions

`ios/R02Ring/Health/UnifiedMode.swift` explicitly has **no wire encoding**;
the production app does not attach its transport to BLE. Keep that separation.

- Capabilities require protocol1, Health-default, dark Gesture, sequenced motion,
  lease30s and rate25Hz. `capabilities()` has no exposed request ID, so the wire
  adapter must provide its own correlation/reassembly for discovery after image
  authorization; a bare opcode match cannot distinguish stale responses.
- A `ModeReply` contains requestID u32, bootID u64, session u32, runtime mode and
  charging. Even packing mode+charging into one byte totals **17 bytes before
  opcode, version or checksum**. The current16-byte queue requires a reviewed
  fragmentation/reassembly design or a separately audited larger transport.
  Do not truncate bootID, omit requestID, or infer completion from one fragment.
- `renew` carries session, processedSequence and requestID (12 bytes) and must
  remain bound to the observed boot/connection generation. Numeric enum values,
  endian order, operation IDs and negative-response format are still unallocated.
- Motion session4 + sequence4 + XYZ6 already consumes14 bytes: a one-byte type
  and checksum would fill16 with no further framing space. This is a size bound,
  **not a proposed encoding or axis allocation**. The driver-word mapping in
  `UNIFIED_STOCK_MOTION.md` is not the future wire's axis convention.
- Coordinator rejects request-ID and connection-generation mismatches, does not
  wrap request IDs, and renews no faster than5s from successful inference within
  0.5s, with advancing sequence in the same Gesture session. Transport must retain
  those guarantees, including reordered/duplicated fragments and boot changes.
- On attach, an old Gesture/EnteringGesture session is explicitly returned to
  Health, not adopted. On disconnect the app clears status because it cannot
  attest physical Health; firmware cleanup/lease must work independently.

Further evidence needed: approved identity/discovery scheme; output framing and
request/error correlation; actual gateway code/ABI; safe memory and stack space;
serialized RX/TX producer ownership; queue bounds and notification scheduling;
disconnect/reboot stale-fragment handling; physical sensor/optical postconditions.
No physical probes are proposed by this audit. See `UNIFIED_STOCK_MOTION.md`
for the separate acquisition-freshness and Health-continuity limits.
