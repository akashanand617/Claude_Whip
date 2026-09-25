# Heap-free optical sample I/O and fixed call-site integration

2026-09-24. **Implemented and executed off-ring, not installed or flash-ready.**
Health remains the unified boot/default; Gesture is temporary. Installed V2
optical-off and all stock files are unchanged. No ring connection, sensor
operation or firmware write occurred in this continuation.

This follows [optical work lifetime/retirement](UNIFIED_OPTICAL_WORK.md). The
prior `wop_read` guarded an original job's lifetime but inherited the original
reader's unchecked FE-write allocation and ignored mutex-release results.
The new C helper plus **both** fixed call-site edits remove those two defects
from the selected sample-read path. The wrapper alone does not apply the edits.

## Firmware code and exact reference

`firmware/unified/stock_optical_io.{c,h}` adds `woi_samples_io`. It accepts only:

- Register `0xfe`, one source byte: send the cursor using two stack bytes.
- Register `0xff`, 1–128 destination bytes: read samples into caller storage.

Other registers, zero/excessive lengths, null buffer, null mutex, exception
context or initially masked interrupts reject before bus work. The caller must
own the complete buffer span and prove its lifetime and acquisition serialization.
The helper does not infer those properties from a nonnull pointer.

The existing stock mutex is taken with its original timeout 100. FE calls the
original caller-buffer TX routine directly; FF calls the caller-buffer RX routine
directly. Neither path allocates memory or enters the allocating/recovery wrappers.
After a successful take, release is attempted once, including when the bus call
reports failure. Success requires **both** bus status zero and successful release.
Any other reported outcome returns `UINT32_MAX`, matching the reader's expected
failure ABI. Raw per-stage error numbers are not exported by this narrow ABI.
There is no retry, bus reset, automatic recovery or static state.

| Operation | Exact stock reference |
|---|---|
| Input image | Stock 3.12.02, SHA-256 `b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0` |
| Mutex slot | Absolute RAM `0x208c98` |
| Take / give | Thumb `0x133f5` / `0x1341d`, vendor boolean/opaque-handle ABI |
| Caller-buffer TX | File `0xdb42`, Thumb `0x833af3`; address `0x33`, command pointer, length 2 |
| Caller-buffer RX | File `0xdc40`, Thumb `0x833bf1`; address `0x33`, register pointer, length 1, destination, requested bytes |
| FE call-site replacement | File `0x11a80`, runtime `0x837a30`, original BL bytes `fdf7c7f9` |
| FF call-site replacement | File `0x11a92`, runtime `0x837a42`, original BL bytes `fdf7a2f9` |

All file/runtime conversions use bias `0x825fb0`. These are **not V2 offsets**.
Stock buffer/demultiplexing code remains otherwise unchanged, including cursor
advancement before I/O. The new helper does not roll back device/software cursors.

The old RX wrapper `0xdcce` also invokes `0xdaf0` after its operation. The new
direct RX route intentionally does not enter that recovery path after failure.
Future recovery requires a separately qualified operation and physical state;
silently continuing or resetting an unknown acquisition is not implemented.

## Fixed, non-installable integration artifact

`whip/fwoptical_io.py` emits a **plan**, never an image. It requires exact stock,
the pinned descriptor and a structurally checked real-address component ELF.
It checks the complete 36-byte surrounding instruction signature and supplies
exactly two four-byte Thumb BL replacements targeting `woi_samples_io` from
that ELF. Source/ELF/descriptor hashes and both before/after encodings are saved
by the guarded build in `optical-io-call-plan.json`.

The planner cannot refresh checksums, clear `not_ready`, append code, write a
stock binary, construct OTA, connect or flash. Its report explicitly retains
`stock_file_modified=false`, `stock_hooks_attached=false`, `flashable=false`.
The full firmware construction gate still refuses image creation.

Tests apply these exact bytes **only to emulator memory**. They execute compiled
`wop_read`, the original sample reader, each actual replacement BL, compiled I/O
helper and original lower TX/RX instructions. The lowest peripheral transfer,
bus status/delay and RTOS mutex behavior remain explicit fixtures. No test label
or plan substitutes for a real source/lifetime/physical validation receipt.

## Verification scope

`tests/test_stock_optical_io.py` adds 48 cases. They cover:

- Actual call-site execution and successful buffer/status equivalence to the
  unchanged reader, with no allocator/free, old wrapper or automatic recovery.
- Mutex release failure at FE and FF: the old path returns success under the
  fixture, whereas the new path returns `-6` through the reader and faults the
  original Health job. It does not publish decoded samples or acknowledge STOP.
- Take failure at either stage without releasing an unowned mutex; surfaced
  TX/RX errors and partial RX error, release on failure and no automatic retry.
- Invalid registers/lengths/pointers/context, null mutex, successful boundary
  lengths, buffer canaries, callee-saved registers and restored stack.
- Bus-not-ready/busy failure without entering automatic recovery, and allocator
  failure fixtures that are irrelevant because allocation is never reached.
- Modeled pause during read: in-flight work completes, but the late zero is
  rejected under its original ticket. No new identity is assigned at dequeue.
- Wrong plan inputs, BL alignment/range rejection, reproduction of the two
  known stock calls, and no emulator code edits outside the eight allowed bytes.
- A saved plan bound to its inputs and explicitly unable to claim deployment.

The first 43-case run passed before the final report/readiness cases were added.
A 219-case focused regression run overlaps the full suite and predates those
last cases. The full guarded build `build-20260924-optical-io-v1` passed
**2868 tests in 183.28 seconds**, zero skips/failures/errors/xfails. All **257
hashes** were independently checked (174 inputs, 80 artifacts, three reports).
Both ARM links reproduce identically. Exact hashes and sizes are in the
[resource handoff](UNIFIED_RESOURCE_BUDGET.md).

In the selected successful actual-address execution, the new integrated read
uses **336 bytes of observed nested stack**, versus 352 for the unmodified
wrapper path. Its 908 observed instruction boundaries include 165 masked by the
lifetime guard; bus work remains unmasked. Mocked ROM/peripheral internals are
excluded. These are neither task headroom nor physical latency measurements.

## Space recovered without removing inbound checks

The C control encoder now builds **one requested 20-byte fragment per call**.
`wd_reply_next` no longer builds both fragments in a temporary 40-byte array and
copies one out. Existing two-fragment/CRC/identity/timeout/ordering semantics
remain; the native stress caller and ARM/Swift parity tests use the new API.
Eight added cases check exact single-fragment writes, untouched neighbors and
invalid fragment rejection before output mutation.

`ww_motion_valid` was only a host-side reference decoder: no production caller
or function-pointer reference used it. It moves to `tests/native/wire_proof.c`,
where compiled ARM/Swift decoder parity coverage remains. It is no longer linked
into ring code that only emits motion. The real-address verifier now rejects
that test-support symbol. Production inbound control still contains
`ww_rx_feed`, `ww_body_valid` and `ww_crc`; **no incoming request validation is
removed**. Outgoing motion still uses `ww_pack_motion` and its original checks.

The tiny generation increment is explicitly inlined while its full fault/
receipt-invalidation body remains shared. Token exhaustion behavior is unchanged.
No compiler flag, unwind data, predicate, protocol field, queue capacity or
stock space was discarded to pass the size gate.

The I/O helper adds 148 text bytes; the complete link grows by only **12 bytes**
to **9480/9520 configured bytes**, leaving **40**. It contains 9384 text/constants
and 96 unwind bytes, ending at `0x849fd8`. Static RAM remains zero and the
dispatcher/frame/fence state budget remains 796 bytes. This still does not
establish complete hooks/service/bindings fit or approved memory ownership.

## Remaining obligations

Each FE/FF helper call takes/releases the mutex separately, preserving the old
scope. The pair is **not an atomic acquisition**. No complete producer inventory,
cross-job serialization, original IRQ/hub identity, physical byte-completion
receipt, FIFO timing/overflow or algorithm-to-job provenance is created here.
Zero is not a `measured` flag or physical STOP proof. RTOS and lower peripheral
contracts, object lifetimes, interrupt latency and full stack ownership remain
unproved. No geometry/recovery, actual current-settings resume, final-model
qualification or steps/sleep continuity gate is closed by these off-ring tests.

Only the specified reader calls are redirected in the emulator. Other optical
metadata/control paths still retain their original allocation/error behavior.
Both edits and the original lifetime wrapper must be integrated into a complete
reviewed image before their combined behavior can be claimed on hardware.
Stock Health must remain untouched and unified Gesture unavailable until then.
