# Serialized final Health commit boundary

2026-09-24. Entirely off-ring; **unattached and not in either main component
ELF**. No sensor, phone, BLE, flash, production capability or construction gate
changed. Health remains the unified boot/default. The installed optical-off
V2 image is untouched.

## Concrete boundary implemented

`firmware/unified/stock_health_commit.{c,h}` adds `wsc_commit_health`. Previously,
`wss_read_controls` protected its four stock-byte loads, and `wa_commit_health`
required callers to serialize settings revalidation and the two software gates.
Calling them with interrupts enabled between the operations left that final
check-to-commit exclusion as an unimplemented binding obligation.

The new candidate performs the following in one bounded PRIMASK-preserving
critical section, with no RTOS or peripheral calls:

1. Require task context, non-null aligned arguments, runtime RETURNING/RESUME,
   Health READY, and exact original resume token, Health generation and prepared
   revision. Stale preparation is refused without adapter mutation.
2. Read a **caller-owned, independent** current revision word. A changed revision
   goes through existing `wa_commit_health` invalidation: READY becomes RESUMING
   without committing Health. This is not scheduler completion or a retry.
3. Execute existing exact-stock `wss_read_controls`: HR interval `0x208aac`,
   all control bits `0x208aad`, operating mode `0x208c44`, time-set `0x208c46`.
   Its nested interrupt-mask save/restore leaves the outer exclusion intact.
4. If those bytes differ while the revision is unchanged, fail the attempt
   closed through `wh_fail` and `wa_tick`. A visible writer-contract violation
   must not retain reusable READY evidence or invent a new revision.
5. Otherwise execute existing `wa_commit_health` under the same exclusion.
   Its quiet/inventory/deadline checks still apply; runtime commits Health
   before the Health lifecycle gate opens. Old job tickets are invalidated,
   not relabeled. A new job still needs `wh_job_begin` with a new serial.

The caller's preparation record contains four 32-bit words: token, generation,
revision and controls. It must be captured when genuine current-settings
scheduler preparation completes, in the same domain as `wa_resume_ready`, then
kept immutable for the attempt. It is **not** a new physical receipt or evidence
that a scheduler/timer was created successfully.

Prior PRIMASK is preserved, including a task caller that already has interrupts
masked. Every exception-context call is rejected before shared-state reads or
writes. The helper writes only adapter state; it does not write stock settings,
clock, history, working sensor buffers, motion cursors or timer handles.

## Required writer contract remains unresolved

No real revision counter, writer hook, counter address or RAM owner is supplied.
The caller must prove that every relevant settings/eligibility writer advances
the same monotonic, non-wrapping revision as part of the same serialized state
change. All other adapter/preparation writers must obey that domain too. The
revision word must be separate from the adapter and preparation record; argument
alignment is not pointer-validity, lifetime, non-aliasing or ownership proof.

Raw control bits cannot detect change-and-change-back. The tests deliberately
show both cases:

- Controls return to their original bytes but a real revision advances: old
  preparation is rejected.
- An unobserved change-and-change-back also leaves a lying revision unchanged:
  the helper cannot detect it. The test does **not** claim otherwise.

PRIMASK excludes ordinary maskable Cortex-M preemption in this bounded operation.
It does not cover NMI, DMA, debug writes, reset or an unproved scheduler/ownership
model. No blocking call is made inside the critical section. The observed
instruction count is not measured ring interrupt latency or permission to
install it. Complete producer/start/result inventory, queue/IRQ/hub/RUN drains,
physical STOP, preserved Health state and real fresh-job/current-settings resume
remain separate, open obligations. See [readiness](UNIFIED_READINESS.md) and
[cancellation](UNIFIED_HEALTH_CANCELLATION.md).

## Executed evidence and explicit simulated boundaries

`tests/test_stock_health_commit.py`: **63 passed in 21.81 seconds** in the first
complete expanded focused run. A subsequent equivalent rerun is recorded in
the parent checkpoint; test counts are overlapping, not additive.

The runner executes compiled Cortex-M0+ code at the actual stock append address
under the unchanged `stock_append.ld`. It links only the needed core/settings/
helper functions plus test-only ABI witnesses. The normal production placement
verifier explicitly **rejects** this incomplete test ELF. No existing verifier,
linker bound, unwind policy or compiler flag is relaxed to execute it.

The setup uses real controller/lifecycle calls, but inventory, drain, physical
STOP, resource release, preserved Health state and scheduler preparation are
explicitly simulated inputs. Revision storage is synthetic emulator memory,
not an allocation on the ring. No timer creation, RUN or real resume is executed.

The cases cover:

- Original job rejection before and after commit, new serial creation only
  after Health opens, and one-shot use of a preparation.
- Each changed stock controls byte, revision changes including unequal unusual
  values, stale token/generation/revision, null/misaligned arguments, missing
  quiet/inventory evidence and expired action deadlines.
- Re-preparation after changed current settings; old prepared fields cannot
  relabel themselves as the newly prepared scheduler state.
- Preservation of unavailable-inventory boot passthrough; a rejected call does
  not turn incomplete unified guards into a shutdown of stock Health.
- A simulated maskable settings writer arriving at **every instruction boundary**
  of the successful path. Observed PRIMASK controls delivery: the settings change
  occurs before the guarded transaction or after all its shared reads/writes.
  This is a deterministic interleaving witness, not measured RTOS scheduling.
- Preexisting mask preservation and emulator-only missing-mask/missing-restore
  mutants, which the tests detect. Mutation never touches a stock file.

The helper and ABI witness objects are independently recompiled and compared,
then the focused ELF is relinked and compared. Source/toolchain snapshots are
checked around the build. The test also recompiles the complete current source
set, links its unchanged baseline, and verifies that appending this helper fails
the **unchanged** configured APP-bound assertion.

## Separate footprint, not a whole-image fit

Measured with the unchanged Clang ARMv6-M `-Oz` flags and pinned Zig 0.15.2:

| Quantity | Measured |
|---|---:|
| Helper object text/constants | 196 bytes, alignment 4 |
| Helper object unwind | 8 bytes, alignment 4 |
| Writable static storage | 0 bytes |
| Helper local ARM stack frame | 32 bytes |
| Successful observed nested call-chain stack | 128 bytes |
| Successful path instructions | 757, of which 733 run with PRIMASK set |
| Focused incomplete ELF occupied extent | 5924 bytes |
| Focused extent increase versus same subset without helper | 196 bytes |
| Full current baseline components | 9468/9520 bytes |
| Full components plus helper | Link refused: configured APP bound exceeded |

Object unwind entries can merge during linking; do not add an arbitrary eight
bytes to every linked size. The focused linked delta includes its alignment and
retained linked unwind, but is not an emitted full-image size. The full link
refuses output, and no larger linker region is used to manufacture a fit claim.
The helper's 196 text bytes alone exceed the full baseline's 52-byte remaining
extent. It is therefore **not added to production SOURCES or either main ELF**.

The immutable 16-byte preparation record and a separate aligned four-byte
current-revision word, **if newly allocated**, add an illustrative 20 bytes of
caller-owned state. The existing 796-byte dispatcher/frame/fence subtotal does
not include these. Revision storage may already exist in an eventual owner;
do not double count or assign it to stack without a reviewed allocation plan.
Both need proven lifetime/storage if this design is integrated; neither is
allocated here. The
128-byte stack observation excludes the outer stock caller and interrupts;
it is not a task-stack approval. Complete architecture/flash/RAM fit, actual
resume hardware evidence, steps/sleep continuity and recovery remain open.
