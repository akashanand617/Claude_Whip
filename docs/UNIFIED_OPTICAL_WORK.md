# Optical read lifetime and buffer retirement implementation

2026-09-24. **Built as off-ring components; unattached, not installable.**
This continuation adds firmware C, not only evidence fixtures. Installed V2
optical-off is unchanged. Unified Health remains boot/default and Gesture opt-in.
No ring connection, sensor command, stock patch or production gate was enabled.

Later [heap-free sample I/O integration](UNIFIED_OPTICAL_IO.md) replaces the
two selected allocating/error-masking calls in emulator memory. Its current
build supersedes the counts/sizes below; this wrapper alone does not install
those edits or prove physical completion.

## What was built

`firmware/unified/stock_optical_work.{c,h}` implements two exact-stock bindings:

- `wop_read`: admits an original Health job, marks its shared-sensor operation
  in flight, executes the original sample reader with interrupts enabled, and
  rechecks the original ticket before accepting a zero return. An intervening
  pause cannot receive cancellation/fence/STOP completion while that operation
  is in flight. A stale zero is replaced by `INT32_MIN`, not accepted as new work.
- `wop_retire`: only after the adapter reaches fully evidenced PAUSED for the
  matching controller token, clears the original optical software sample arrays
  and four acquisition flags. Unlike the stock helper, it cannot silently skip
  clearing merely because the ready flag was already zero.

Both check thread context, initial PRIMASK zero, nonnull objects and equality
with stock's live buffer/status registration slots. The check/transition and
retirement run under PRIMASK. A mismatched object or invalid entry performs no
sensor operation or object write and preserves the incoming interrupt mask.
The read's blocking bus/RTOS path runs **outside** that critical section. If
stock unexpectedly returns with interrupts masked, Health faults and that mask
is retained; the wrapper does not blindly enable an unknown critical section.

`wh_run_begin/end`'s existing in-flight bit now explicitly also covers a
shared-sensor acquisition. This uses the same state and prevents a second
RUN/read for the job until the first returns. No job structure, static storage,
queue slot or production inventory is added. An old callback must carry its
original ticket, never acquire the current one at dequeue.

Stock nonzero statuses are preserved. `-2` (no data) and `-3` (insufficient
complete group) finish the operation without faulting Health, but cannot count
as new samples. Other surfaced errors and positive incomplete statuses fault
the adapter and invalidate its fence/STOP receipts. The software cursor is not
rolled back or automatically retried after I/O failure: device effects may have
already occurred. Returning zero is **not lasting permission**: a downstream
consumer/commit must recheck the same ticket and its own source provenance.

## Exact stock reference and executed sample behavior

Only stock 3.12.02 is the reference:
`b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0`.
Runtime address equals file offset plus `0x825fb0`; these are not V2 addresses.

| Binding / selected path | File offset or absolute slot | Evidence |
|---|---|---|
| Sample reader | `0x11994` → runtime Thumb `0x837945` | Real cursor/group arithmetic, FE write, FF read and sample demultiplexing execute |
| Channel counting | `0x11922` | Counts selected enabled channels/auxiliary flags; zero byte-sized group is invalid |
| Word decode | `0x124c6` | Actual big-endian two-byte conversion and local byte cursor |
| Ready bookkeeping | `0x10610` | Sets attempted before reading; a negative return can leave old ready set |
| Conditional software clear | `0xfbc0` → runtime Thumb `0x835b71` | Actual bounded clear and metadata initialization, through `0x113e8` |
| Registered buffer/status | Absolute `0x20859c` / `0x2085a8` | Binding checks supplied pointers against both live slots |

`whip/fwoptical_samples.py` executes these bounded original instructions, not
a Python replacement for their cursor or clearing behavior. Low-level bus
bytes/status, allocation, mutexes, scheduling and optical physics remain explicit
fixtures. Literal island `0x11b14..0x11b18`, adjacent readers and unreviewed reset
branches stay rejected. The fixtures select reviewed configurations; this is
not an exhaustive proof over every possible driver buffer/configuration.

The reader stores the new software cursor at `0x11a7a` **before** attempting
FE/FF I/O. Failed TX/RX and partial RX with an error status return `-6` without
rolling that cursor back. A second call at the same cursor can return `-2`
without retrying. Wrap cases execute for 96- and 128-byte layouts. Selected
success decodes fixture `12 34 ab cd` into native words `1234, abcd`.
An incomplete remainder returns positive 1; kind `0x10` can deliver its complete
prefix first, whereas kind `0x30` returns before I/O. The new wrapper accepts
neither as full success. Ready helper `0x10610` can latch attempted while leaving
old ready set after failure, then return zero without I/O on the next call.

The stock clear normally does nothing when `STATUS+0x1a` is zero. Retirement
temporarily sets it to one, executes the real clear, then zeros `STATUS+24..27`.
Across three channels at stride `0x18c`, stock clears the sample count, 128 sample
bytes and 256 metadata bytes, reinitializing each first metadata record from
that channel's configuration. It also clears the two 64-byte auxiliary arrays
and their count. The selected full buffer span extends through offset `0x53f`.
This is an access bound, **not approval of an actual 0x540-byte allocation**.
Configuration, software cursors, unrelated status, published HR cache, settings
and steps/sleep state are not cleared. The hardware FIFO is not flushed.

## Executed implementation tests

`tests/test_stock_optical_work.py` contains 59 cases using actual compiled ARM
and the unchanged stock sample/clear instructions in the same emulator. The
actual-address component link is also executed, not merely inspected. Cases
cover normal reads; TX/RX/partial-RX/mutex failures; no-data/incomplete/invalid
configuration; positive incomplete status; overlapping operations; original
serial/generation/job rejection; all pause/resume phases; invalid pointers and
context; unexpected returned mask; and complete retirement with ready 0, 1 or 2.

An explicit modeled pause at sample-reader entry uses state produced by actual
compiled lifecycle calls. Cancellation, fencing and STOP receipts reject during
the operation. Its late zero result is rejected; completion clears only the
in-flight bit, after which the synthetic receipts and retirement can proceed.
No real RTOS interrupt or physical STOP is asserted by that fixture.

Retirement bytes are compared with a separate execution of the original stock
clear for all three channels, rather than a rewritten expected clear. Object
canaries, write spans, PRIMASK, AAPCS registers and stack restoration are checked.
Retirement cannot call bus, heap or RTOS boundaries. Emulator-only missing-mask
mutants are detected before an unprotected adapter read.

The 15 original-sample witness tests and four shared-codec alignment cases are
additional parts of the full suite, not physical measurements. In the selected
successful instruction fixtures, read reaches **352 bytes of nested stack**;
retirement reaches **56 bytes** and **5417 masked instruction boundaries**.
Mocked ROM/peripheral internals are excluded. These are not cycle counts, an
interrupt-latency qualification or approved headroom on a real task.

## Code size and complete build

The initial `build-20260924-optical-work-fit-v1/` retained a failed configured-
APP-bound link; it has no success manifest and is not a passing build. No bound
was enlarged, unwind information removed or queue/safety check reduced.

The new work module contributes 324 bytes of text. To make room, existing
identical checked code is shared rather than inlined repeatedly: controller
action issue, timer RAM-span checks, adapter inventory and Health failure receipt
invalidation. Wire and dispatcher also share one byte-wise little-endian load/
store implementation. No predicate, limit, state transition, wire format or
queue capacity was removed. Four tests check the shared helpers at every
alignment with boundary/random values and untouched neighboring bytes.

The reproducible actual-address component link occupies **9468/9520 configured
bytes**, leaving **52**: 9372 text/constants and 96 unwind bytes. This is a net
116-byte increase over the preceding 9352-byte build. Compiler flags, stock
bytes and static RAM allocation are unchanged. Dispatcher/frame/fence stays
796 bytes; the nominal remaining 228 bytes still have no ownership approval.
The remaining service/hooks/bindings are not included in that fit claim.

Full build: `firmware/unified/build-20260924-optical-work-v2/`, **2812 passed
in 188.17 seconds**, zero skips/failures/errors/xfails. All **248 hashes** matched
(170 inputs, 75 artifacts and three reports); both ARM link layouts reproduce
identically. Manifest SHA-256:
`a9ce16455f17c1c0a55d2d6af22f21ec96ad1e2e1edf5ecb28c6528a1d4613e2`.
The [resource handoff](UNIFIED_RESOURCE_BUDGET.md) includes both ELF hashes.
The preceding focused run of 379 tests overlaps the full suite and predates the
final added edge cases.

## Still required before attachment or flashing

Zero from this reader is only a candidate software read outcome. It does not
prove actual delivery length, acquisition epoch, sensor timing/overflow,
algorithm-consumption identity, job-to-metric association or clinical accuracy.
It must **never directly supply** the HR commit guard's `measured` argument.
Stock's underlying FE-write allocation and ignored mutex-release result are
not repaired here; complete transport/allocation safety remains a binding
obligation. These components must not be represented as the completed safe
Health hardware adapter.

Pointer equality does not prove lifetime or ownership. Production inventory,
serialized lifecycle writers, original IRQ/hub/timer identities, no NMI/DMA
writers, all result/publication fences and physical STOP remain unproved.
Software clearing does not discard old hardware FIFO contents or establish a
new acquisition generation. Current-settings fresh-job resume, 25 Hz physical
source/model evidence and steps/sleep continuity still need integration and
physical validation. The long masked clear needs a real interrupt-latency
assessment. Complete flash/RAM/stack fit, geometry and recovery remain gates.

Until then, leave stock Health untouched and unified Gesture unavailable.
The existing construction/transport gates remain closed; no OTA image exists.
