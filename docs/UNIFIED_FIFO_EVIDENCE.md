# FIFO completion, timing and model-input evidence

Status: 2026-09-23, workflow 3, **offline evidence only**. The exact stock/V2
transaction paths and packet representation now have executable witnesses.
There is still **no qualified physical acquisition trace, physical source
profile, installed observer, or model validation of a newly timed source**.
No ring connection, BLE command, sensor access, firmware write or flash was
performed for this work. This document does not authorize those operations.

Read alongside [UNIFIED_WORKFLOW.md](UNIFIED_WORKFLOW.md),
[UNIFIED_FRESH_SOURCE.md](UNIFIED_FRESH_SOURCE.md),
[UNIFIED_STOCK_MOTION.md](UNIFIED_STOCK_MOTION.md) and
[UNIFIED_HEALTH_LIFECYCLE.md](UNIFIED_HEALTH_LIFECYCLE.md).

## What is implemented

[`whip/fwfifo_trace.py`](../whip/fwfifo_trace.py) has three bounded jobs:

1. Read actual archived notification/register records, retaining their hashes
   and identity-claim scope. Report delivery statistics and observed FIFO status;
   explicitly refuse acquisition/model qualification.
2. Execute unchanged, exact-image STK read, controller polling and FIFO drain
   instructions against scripted MMIO. Reproduce success, partial failure,
   ignored overflow and the gap between transaction mutex scopes.
3. Execute the original raw-packet encoder/checksum, stopping before transport.
   Cross-check native frame representation against Python and compiled actual
   Swift decoder functions. This is not a new production wire protocol.

The module neither imports BLE nor exports a source profile or timestamped model
stream. `native_to_model_counts` accepts exactly one complete six-byte frame and
returns existing model-axis counts. It makes no freshness assertion.

| Capability | Status |
|---|---|
| Exact stock/V2 read-return ABI and partial-transfer witnesses | Implemented, offline |
| Unmasked overflow/ignored-error and mutex-scope witnesses | Implemented, offline |
| Native → legacy packet → Python/Swift axis and scale parity | Implemented, offline |
| Real archive evidence extraction and refusal report | Implemented |
| Physical FIFO cadence, acquisition time, live completion/overrun | Not established |
| Stock-linked observer, Health timing preservation, production profile | Not implemented/qualified |
| Finalized classifier validation on a newly acquired physical source | Blocked on acquisition trace |

## Exact image anchors

All code addresses are **file offsets**; add `0x825fb0` for runtime addresses.
RAM and ROM addresses are explicitly marked. The harness rejects any full-image
SHA-256 other than these two. File identity does not attest the installed ring.

| Image | SHA-256 |
|---|---|
| `rt02cr-stock-3.12.02.bin` | `b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0` |
| Historical `rt02cr-25hz-optical-off-v2-experimental.bin` | `0d18a0fa860d58ab8f984b5f542f45dac105241f47bf1c2af41321eb0431e14c` |

| Meaning | Stock | V2 |
|---|---|---|
| STK read wrapper | `0xbc6a` | `0xbc12` |
| Bus wrapper / transaction / recovery | `0xdcce / 0xdc40 / 0xdaf0` | `0xdc66 / 0xdbd8 / 0xda88` |
| Byte polling / abort decoding | `0x1371e / 0x1360a` | `0x1357a / 0x13466` |
| Whole FIFO drain / producer store | `0xc280 / 0xc4e8` | `0xc228 / 0xc490` |
| Empty-drain watchdog | `0xc25a` | `0xc202` |
| Driver / sample state, RAM | `0x20bd98 / 0x20bdc8` | `0x20bd94 / 0x20bdc4` |
| Shared bus mutex handle, RAM | `0x208c98` | `0x208c94` |
| Poll budget, RAM / file initializer | `0x2085c8 / 0x21690` | `0x2085c4 / 0x214ac` |
| Raw encoder / checksum tail | `0x1f18 / 0x1f70` | `0x1ecc / 0x1f28` |
| Packet checksum / unexecuted notify boundary | `0x3fe8 / 0x7e30` | `0x3eec / 0x7c0c` |

The reviewed active configuration/init remain unchanged across stock, historical
25 Hz and V2: range `0f=05`, active `11=74`, `10=0f`, `3e=c8`, watermark `3d=20`,
plus other initialization including undocumented `5e=c0`. See the earlier
[datasheet/configuration audit](UNIFIED_FRESH_SOURCE.md#why-the-physical-rate-remains-unresolved).
The new suite executes stock and V2, not a third copy of the historical 25 Hz
image. None of these configuration bytes establishes a physical frame period;
there is no assumed 75 Hz source or 3:1 decimation.

## Transaction completion: what the instructions prove

Stock `0xbc6a` accepts `r0=register`, `r1=destination`, `r2=byte count`.
It takes the shared mutex through ROM `0x133f4` with timeout argument 100,
calls the bus with device address `0x1f`, and gives the mutex through ROM
`0x1341c`. It returns **1 for bus result zero, otherwise 0**; mutex failure
returns zero without a transaction. Whole-function witnesses check restored
`r4..r11`, stack pointer, aligned public mutex calls and destination canaries.

The executed chain is `bc6a → dcce → dc40 → 1371e`. The final routine polls
controller flags and writes destination bytes progressively. The abort helper
examines I2C0 abort-source bits under mask `0x180f`; timeout/abort becomes a
nonzero result, then read-wrapper failure. This API does not return a completed
byte count. The harness observes CPU stores and scripted peripheral reads
separately, without changing the stock instructions.

| Executed witness, both exact images | Result |
|---|---|
| Complete 1/6/18/192-byte scripted input | Return 1; all requested bytes stored; ABI/canaries intact |
| Timeout after 0/1/5/6/11/17 of 18 bytes | Return 0; only the completed prefix changed |
| Abort-source bits 1/2/4/8/`0800`/`1000` | Read failure after the supplied prefix |
| Mutex failure | No controller access or destination writes |
| TX-empty/master-busy timeout | Read failure before receive routine; 501 scripted delay calls |
| **Poll budget deliberately forced to zero** | Return 1 despite six unready MMIO reads |

The last row is a **negative precondition witness**, not an observation of live
stock. Both exact image initializers contain `0x000fffff`; normal tests use a
bounded positive budget of four. The zero-budget path skips the readiness loop,
so success alone is insufficient without a reviewed live-state invariant.
Literal references establish consumers, not closure over every possible indirect
RAM write. Instruction counts and scripted delay calls are not elapsed time.

The controller and ROM are not emulated hardware: mutex take/give, delay,
memory-copy/clear, readiness flags, incoming bytes and abort bits are explicit
mocks. The actual selected polling/error/cleanup code executes. Code execution,
RAM access, MMIO registers and writes are guarded; flash reads stop at the actual
pinned image EOF, not the larger mapped page. Watchdog writes permit only its
three reviewed instructions writing driver byte +3. No broad driver-RAM write
permission was added to make a failing test pass.

## Overflow, partial publication and concurrency

For stock's STK-ID-`23` path, `0xc360` reads register `0x0c`. The return at
`0xc364` still carries read success; `[sp]` contains the full status. Instructions
`0xc36c..0xc36e` discard bit 7 and retain only count. The count is capped at 32.
`0xc388` clears the 192-byte destination; `0xc39a` reads data from `0x3f`.
At **`0xc39e` the burst result is ignored**, and copying eventually publishes
the producer at `0xc4e8`.

Actual-code witnesses show status `03` and `83` produce the same published
frames. Failed data reads publish the completed prefix plus cleared zero bytes,
and advance the producer by the entire requested batch. A failed status read
does not drain/publish. Thus neither cursor advancement nor a nonzero XYZ value
is a completion or losslessness receipt.

The status and burst reads acquire/release the bus mutex **separately**:

```
status: take → read 0c → give    gap    burst: take → read 3f → give → publish
```

That lock does not protect the whole drain, buffer publication or the future
observer. Stock direct callers of `0xc280` include configuration at `0xc538`,
hub driver work at `0xcb4e`, and raw reader at `0xcc46`. The raw reader is also
called from the raw timer (`0x1f14`) and optical motion helper (`0xee86`). A
single publication hook cannot establish complete transaction ordering.

Stock task creation `0x148c` passes a `0xa00`-byte stack and priority 2 at
`0x14b6` to ROM `0x13468`. Realtek's SDK describes priority-6 software timers and
priority-based preemption; under that documented setup a timer can preempt this
task. This is an inference from SDK defaults, **not a measured live RTOS/OTP
priority configuration**. Timer helper `0x3e30` calls stop/delete without testing
stop success; it is not a demonstrated callback-drain fence. [RTL8762E SDK User
Guide v1.0, pp. 19–20](https://www.realmcu.com/img/ipd/en_637839320584437719.pdf).

## Real archives: delivery is not acquisition

The extractor reads these unchanged files under
`firmware/research/2026-09-22/captures/`:

| Capture | SHA-256 |
|---|---|
| `check_1790071705479474000.jsonl` | `c89c75edbfe4b98edc1b1f46ff3a608321c0a14b3621f801171c18918589831c` |
| `firmware_validation_1790114546989490000.jsonl` | `a9eabd11c2e7b165ddbfe0d73a23d6c3807b30a0281c851bad5f9606dfdddc8f` |

The first has **208 packets at 25.044/s but only one distinct XYZ** in its
initial streaming phase. A status snapshot at host time 8.1895848 s is `a0`:
overflow set, count 32. Later optical-stopped packets vary (1509 packets,
1483 distinct XYZ, 24.996/s), but still lack per-frame acquisition times.

The V2 capture has 1503 packets, 1501 distinct XYZ and 25.002/s across **all
records tagged** `tracking_A104_only`. The older summary's 1450/1450 count uses
its post-warmup interval; these are different windows, not contradictory counts.
Its identity is expressly `critical_code_sites_only_not_full_image`, and it
contains no FIFO-status records. The extractor retains this limited scope.

Both reports return `qualified=false`, `physical_period_ms=null` and
`model_validation=blocked_no_physical_acquisition_trace`. The archive contains
host delivery timestamps and isolated sensor snapshots, not a complete FIFO
transaction trace. Values changing is useful evidence, not a proof of one fresh
sample per 40 ms or absence of missed frames.

## Native frames and the finalized model

Call-site `0x1f14` supplies three output pointers to raw reader `0xcc32`.
Its stores at `0xccba/0xccc4/0xccce` preserve the first, second and third native
little-endian words respectively. The encoder packs those words into legacy
big-endian fields. The new execution fixture starts at the encoder with that
reviewed caller-stack layout, runs its actual checksum, and stops before notify.
It does **not** execute raw acquisition or treat a notify call as acceptance.

| Native FIFO signed word | Legacy A1/03 packet | Existing Python/iOS model axis |
|---|---|---|
| `w0`, bytes 0–1 little-endian | bytes 2–3 big-endian | Y |
| `w1`, bytes 2–3 little-endian | bytes 4–5 big-endian | Z |
| `w2`, bytes 4–5 little-endian | bytes 6–7 big-endian | X |

Therefore the existing model input is **`(w2,w0,w1)`**, preserving all signed
16 bits and using **8005 counts/g**. Do not pass native `(w0,w1,w2)` straight
through, shift to twelve bits, or substitute Health's `(w1,w0,w2)` algorithm
order. The new source component's native delivery format is not itself the
model-axis mapping or a new wire allocation.

Tests execute both image encoders on boundary and 128 deterministic random
frames each, compare with [`whip.accel`](../whip/accel.py), then compile and run
the actual checksum/decoder functions extracted from
[`RingProtocol.swift`](../ios/R02Ring/Health/RingProtocol.swift) and
[`GestureInference.swift`](../ios/R02Ring/Gesture/GestureInference.swift) on 130
frames. Scale comes from the actual Swift `countsPerG` declaration. `WHIP_SWIFTC`
selects the resolved compiler for the guarded build; invalid paths fail rather
than falling back. The builder also resolves `WHIP_SWIFT_SDKROOT`, fingerprints
its `SDKSettings.json` and passes `-sdk` explicitly: invoking the resolved
compiler directly does not inherit the SDK selection provided by `/usr/bin/swiftc`.
This fingerprints SDK metadata, not every SDK library/header. Compiler errors
retain their stderr in the test failure. No simulator, app, CoreML or phone is launched.

The checked-in contract pins finalized checkpoint SHA-256
`77ed774f03ce3eaddbb8ac29ac8dfc1be32fdd7bef997b56c54157891aff26d5`.
Its 50-sample windows/6-sample stride and room-frame processing still depend on
the incoming stream. Representation parity does not validate classifier
performance after cadence/selection changes. Historical model replays cannot be
relabelled as acquisition validation, and no host time is converted into a
fabricated physical timestamp here.

## What a real observer still needs

The bounded candidate is a **passive copy of existing Health-owned transactions**,
not another FIFO reader, faster timer, raw start, wake call or configuration
change. Potential stock observation sites are `0xc280` entry, `0xc364` before
status masking, `0xc39e` before the failed-read result is lost, and `0xc4e8`
publication. Corresponding V2 sites are each `0x58` earlier. These are review
anchors only: no hook bytes, placement or observer C binding is supplied.

Before a binding can issue receipts accepted by `ws_source`, it must establish:

1. Every participating drain, configuration/reset and recovery, with transaction
   ordering and concurrency across all callers. Preserve failed transactions as
   failures; do not silently repair or drop frames from the Health path.
2. Full pre-burst status and read success, requested/completed byte boundaries,
   transfer result and live polling-state invariants. Model-controller witnesses
   do not prove actual FIFO advancement on partial physical transfers.
3. Independently defensible physical frame-time bounds and clock-error bounds,
   sensor phase/cadence, overflow behavior during a burst, and complete relevant
   configuration. A callback timestamp is at best a receipt-time bound.
4. Timing/capacity feasibility without changing Health drains: full 32-frame
   status lacks conservative headroom, the 82-frame software ring can lap, and
   the source requires fresh selections within its age/bucket limits.
5. Stock baseline versus observed execution: identical Health frame bytes/order,
   cursor and algorithm-call behavior, drain timing, idle/wake, and measured
   instrumentation overhead. Instruction/stack/code-space tests precede any
   separately authorized hardware validation.

Existing images do not retain these complete receipts. Approved fixed-plan code
or bank-descriptor reads can identify sampled bytes but cannot recover historical
per-drain stack status, ignored return values or physical acquisition times.
The `CD 01` diagnostic path itself has timer/activity bookkeeping effects, so it
is not a wholly nonmutating acquisition observer. This work neither extends that
approved read plan nor requests `CE` sensor reads, FIFO/configuration reads, or
`A1` start. The latter introduces its own drains and changes the source under
measurement. If strict passive observation cannot meet the freshness/headroom
contract, that is a design blocker, not permission to alter Health cadence.

## Reproduction and audit

```
python -m pytest -q tests/test_fwfifo_trace.py
python -m whip.fwfifo_trace firmware/research/2026-09-22/captures/check_1790071705479474000.jsonl firmware/research/2026-09-22/captures/firmware_validation_1790114546989490000.jsonl
```

Recorded result: **78 passed, zero skips**. Unicorn local JIT requires permitted
executable memory; Swift parity requires the compiler. A skipped dependency test
must not count as successful guarded proof. The report command is stdlib-only,
prints JSON, and performs no hardware access or output-file writes.

Proof inputs include this module/tests, both exact images and capture files,
`whip/accel.py`, the two Swift files above, and the executed Swift compiler.
There is no NumPy, Torch or CoreML dependency in this suite. The shared guarded
builder owns comprehensive input/artifact fingerprints and test identity checks.

Complexity verdict: **KEEP WITH CAVEAT**. The small archive extractor consumes
real evidence and cannot qualify it; the larger harness is justified by actual
instruction-level negative witnesses. It is a test tool, not an embedded driver
or production protocol layer. A second synthetic receipt format or native
observer stub would add apparent progress without resolving timing/serialization,
so neither was added. The code-review and PDF skills kept this distinction and
the SDK-versus-live-priority caveat explicit.
