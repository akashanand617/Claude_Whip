# Bounded stock HR result-commit guard

Subsequent [optical work implementation](UNIFIED_OPTICAL_WORK.md) holds an
original acquisition in flight and retires software buffers only after verified
pause. Its zero return still cannot supply this guard's `measured` argument;
downstream commits must retain and recheck their original identity/provenance.
The build sizes/counts below record this HR component's earlier addition.

2026-09-24. **Implemented and tested off-ring; unattached, not flash-ready.**
This is the first concrete result-store primitive following the
[optical-event audit](UNIFIED_OPTICAL_DISPATCH.md). No ring connection, image
patch, sensor command or production capability was enabled. Installed V2
optical-off is unchanged; unified Health remains the required boot/default.

`firmware/unified/stock_result_commit.{c,h}` adds `wrc_commit_hr`. The function
is compiled into both the artificial test ELF and the proposed real-address
component ELF, not installed into stock. The real-address verifier requires
its symbol so an older ELF missing the component cannot pass as the new build.

## Exactly what is protected

The helper replaces only the positive-result store block at stock file
`0xf456..0xf464`, not the optical processor or its earlier unconditional state
writes. The pinned image remains
`b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0`,
with runtime bias `0x825fb0`. These are not V2 addresses.

| Store order | Exact stock RAM | Store |
|---|---|---|
| 1 | `0x20c020` | Byte 2, positive-result state |
| 2 | `0x20c01e` | Low byte of the positive signed result |
| 3 | `0x20c028` | Same low byte, cached/fallback getter source |
| 4 | `0x20c022` | Auxiliary halfword copied from the caller |

The caller supplies a valid initialized `wh_adapter`, the **original**
HR-producing work ticket, established measured provenance, signed result and
auxiliary value. The guard refuses null context, nonpositive result and exception
context. It saves PRIMASK, masks ordinary interrupts, checks `inventory_proven`
and the real compiled `wh_result_allowed`, performs all four stores only when
allowed, then restores the original PRIMASK on every entered critical path.

No IRQ is blindly enabled. Calls made with PRIMASK already 1 keep it 1. The
guard itself makes no ROM, RTOS, bus, heap, storage, notification or blocking
call; its only callee is the bounded pure-C predicate and its ticket matcher.
There is no new static RAM, queue or allocation and no adapter/settings/history
write. Ordinary task/maskable-interrupt mode changes cannot interleave the
permission read with the four stores under the stated single-core assumptions.

Value semantics deliberately match the original **positive signed** branch:
for example 256 stores a zero byte and `0x7fffffff` stores 255. This primitive
does not redesign stock numeric policy or certify physiological validity.
Source validation and job-to-metric association are caller obligations. It
does not infer an HR-producing source merely because some job ticket is valid.

Subsequent [acquisition evidence](UNIFIED_OPTICAL_ACQUISITION.md) establishes that
the actual stock wrapper can report zero after failed reads or without a read.
Parsed/status-read flags are equally insufficient. These must not be used as
the source of `measured`; the original caller-proven provenance requirement
remains, and this component still has no real producer attachment.

## Executed verification

`tests/test_stock_result_commit.py` adds **60 cases**. Together with the 32
optical-dispatch cases, the focused run passes **92 tests in 2.18 seconds**.
The tests execute actual ARM code at its proposed stock append addresses;
`wh_init`, `wh_job_begin`, quiesce, synthetic receipt handling, resume and ticket
retirement execute the same compiled lifecycle code, not a Python predicate.

- Every accepted write matches execution of the unchanged stock basic block,
  including byte truncation, auxiliary halfword and untouched neighbors.
- Null, zero/negative, unmeasured, unproved-inventory, exception-context,
  wrong-generation/serial/job and retired tickets do not write the stock cache.
- QUIESCING, PAUSED, RESUMING, READY and FAULT reject; returning to HEALTH with
  a new serial/generation still rejects the old ticket and accepts the new one.
  The pause/STOP/resume receipts used here are explicit synthetic inputs, not
  claims of actual hardware completion.
- An explicit normal-interrupt arrival schedule visits every one of the
  successful path's **64 instruction boundaries including return**. Delivery
  occurs only when observed PRIMASK is zero. Each case either rejects with zero
  writes or completes all four writes before pause; no partial commit crosses
  the delivered mode change. Pre-existing masking keeps the event pending.
- Emulator-only mutants remove CPSID or the PRIMASK restore. The test detects
  an unprotected adapter read or the leaked mask respectively. No ELF file or
  stock image is modified by these mutation tests.

The positive path has **49 observed masked instruction boundaries** and a
**56-byte observed nested stack peak**: guard local frame 24, predicate 16,
ticket matcher 16. AAPCS callee-saved registers, stack restoration, context
canaries, allowed stock addresses/store widths and bounded callees are checked.
These are instruction/stack witnesses, not physical clock-cycle, interrupt
latency, RTOS correctness or real task-headroom measurements.

## Remaining attachment and safety obligations

This component closes the selected check/store race only. It does **not**:

- identify or tag real producers, make untagged hub events fresh, or prove the
  bool `measured`; never obtain a new ticket when an old event is dequeued;
- guard SpO₂/other owners, earlier processor writes, immediate packets,
  scheduled aggregation, wear-pointer writes or already queued transport data;
- make a mode change safe against NMI, HardFault or DMA writers; they must be
  proved not to modify this state, and the routine refuses exception entry;
- allocate or establish the lifetime/ownership of the context or stock cache,
  fence IRQ/timer/hub work, prove physical STOP or resume current settings;
- establish complete integration fit, memory geometry, recovery, physical FIFO
  cadence, final-model qualification or steps/sleep continuity.

No production inventory mask or metric/job mapping was assigned. Tests use
explicit synthetic inventories, including job 31 to exercise the ticket bound.
An unresolved binding must leave stock Health alone and unified Gesture
unavailable; do not install this closed guard over ordinary default Health.
Its entry/return trampoline and all surrounding producer/result attachments
still need review. No arbitrary function pointer or generalized callback runs
inside the critical section.

## Size and build

The verified reproducible real-address link adds **80 bytes**, taking
components to **9352/9520 configured bytes**, leaving **168**. It adds no static
RAM; dispatcher/frame/fence remains 796 bytes, with 228 nominal aligned bytes
remaining in the still-unapproved arithmetic budget. The 56-byte nested stack
peak is not permission to use that much on an actual ring task.

Unlike the preceding diagnostic-only continuations, this changes both ARM
ELFs by adding firmware C. It changes no stock bytes, compiler flags, RAM
allocation or construction/production gate. The complete guarded build and
hashes are recorded in [the resource handoff](UNIFIED_RESOURCE_BUDGET.md).

Full build: `firmware/unified/build-20260924-hr-commit-v1/`, **2705 passed in
166.52 seconds**, zero skips/failures/errors/xfails. All **237 hashes** checked:
163 inputs, 71 artifacts and three proof reports. Manifest SHA-256:
`954c042ddf9f9ecca308c8fe8fc25f1c34bbe6751363d6bd7b61f9cc374bad07`.
Both compile/link layouts reproduce identically. No stock hooks, production
inventory, RAM reservation, recovery approval or installable image was added.
