# Integrated control owner — off-ring checkpoint

2026-09-24/25. **Not flash-ready.** Health remains the required boot/default;
Gesture is temporary and opt-in. Claude retains separately authorized ring work.
Codex made no BLE connection, stock/container edit, phone deployment, production
attachment, commit or push. All six [release gates](UNIFIED_READINESS.md) remain
open. This checkpoint supersedes the single-slot/provider-missing claims in the
[preceding mailbox/wait checkpoint](UNIFIED_OWNER_WAIT_BUDGET.md).

## What is actually implemented

`firmware/unified/control_owner.c/.h` now supplies the real `wuw_supervise`
function, not a no-op or proof counter. One `wco_owner` embeds the dispatcher,
two-frame mailbox, original fragment-arrival anchor, coordinator and reusable
STOP submission record. Its `wco_service` performs this sequence:

1. Read fresh current milliseconds and reconcile copied input/closure/deadlines.
2. Call the actual `wc_pump` coordinator with interrupts enabled.
3. Read time again after potentially blocking stock work and reconcile again.
4. Reject the returned phase result if closure/deadline processing changed its
   token, session or action. Never manufacture a physical completion receipt.

The pure `wco_step` consumes at most two frames under one PRIMASK section. Core
calls receive **current time**, not old packet timestamps. The first packet's
original arrival independently bounds the whole fragment exchange, including
later idle passes with no traffic. Dequeue cannot restart that deadline. All
ROM/RTOS/coordinator/hardware operations stay outside this masked section.
Selected execution is bounded by structure, not qualified hardware WCET.

The mailbox now holds **one complete two-fragment command**, 56 bytes total.
This fixes the prior single-slot rejection of a legitimate immediate pair.
A third queued frame, malformed current input or expired oldest frame closes
with FAULT and drops pending input. The host must await the complete reply
before another command. There is still no actual unified BLE sender/admission
adapter; a radio write acknowledgment would not prove owner consumption.

`wim_admitted` is a guarded snapshot, not a lease. The owner holds an outer
interrupt mask across query and pure dispatcher mutation; external send and
completion paths still need the same serialized owner, fresh reconciliation,
original identities and a genuine physical drain/fence. Logical close cannot
recall already queued radio work. A late charging reason is preserved even
after the earlier disconnect event was consumed.

The STOP output slot is reusable. An asynchronous observer must copy the
**original submission identity at submission time**, not reread a later slot
and relabel an old completion. The candidate calls no completion APIs itself.

## Integrated ARM witness and its boundaries

`tests/test_control_owner.py` has **32 focused passing cases**. It compiles the
three new units twice and links them with the 22 exact prior objects. One
explicit TEST-ONLY ABI unit supplies artificial singleton storage, stock
pointers, a clock slot and compiled layout witnesses. The actual production
objects still refuse to link without three strong bindings:

- `wco_bound_owner`: initialized, owned, boot/retention-qualified storage.
- `wco_bound_stock`: reviewed current revision/buffer/status objects.
- `wco_monotonic_ms`: fresh, qualified monotonic milliseconds.

The integrated ELF is at artificial proof addresses, has **no retirement
stubs**, and is rejected by the unchanged production placement inspector.
Its successful test link is not a whole-image fit or installable firmware.

The exact stock wait-loop BL at file `0x135c` calls compiled `wuw_take`, then
real `wuw_supervise`, `wco_service`, dispatcher and coordinator. The original
zero/nonzero branch and surrounding instructions execute. ROM semaphore
results, the task prologue and seven stock-body callees remain named fixtures:
requesting a 100 ms wait is not measured cadence and cannot preempt a blocked
body. Two reviewed sample-reader BL edits also exist only in emulator memory.
The full mapped stock bytes are compared against exactly these three edits.

One persistent context executes Health → Gesture → Health, checked original
optical reads/result stores, original motion drain/Health consumer, current
settings changes and rejection of the old job. A stale settings preparation
does not restore Health. Synthetic inventory/source profiles, cancellation,
queue/IRQ drain, physical STOP/start and scheduler preparation are explicitly
fixtures. Algorithms and real records for steps/sleep remain unproved.
The earlier 21-object, 18-edit retired-layout switch is a **separate** witness;
the new artificial owner test does not merge or extend its root-retirement proof.

Negative coverage includes idle action cleanup, exact 1000/1001 ms fragment
boundaries, unsigned wrap, backward/future arrivals, both missing-admission
cases, invalid task/mask entry, charging after disconnect, and closure during
blocking STOP. The latter copies the actual original receipt before the second
clock read, overwrites the reusable output and rejects the saved stale callback.
Stock TX success alone does not prove physical optical shutdown.

## Whole-candidate budget, without double counting

The updated strict budget batches **25 objects / 146 functions / 3 constants**.
It preserves all nine existing **unowned** placements and the configured APP
boundary, discards no unwind metadata and provides no fake physical bindings.
All three strict link attempts refuse; no full25 production ELF is emitted.

| Quantity | Bytes |
|---|---:|
| New mailbox / wait / owner text | 564 / 72 / 744 |
| All input text / constants | 12,216 / 288 |
| Text assigned to unchanged unowned intervals | 1,894 |
| Append input-only lower bound | **10,610** |
| Configured allowance / minimum excess | **9,520 / 1,090** |
| Input unwind, retained for linking | 1,168 |

The lower bound excludes alignment, veneers, linked unwind and still-missing
bindings. Neither the earlier 264-byte margin nor a failed map is current fit.

ARM layout gives owner **880 = 764 + 56 + 4 + 28 + 28** bytes. Dispatcher,
coordinator and STOP record were already counted in the old 1164-byte planning
selection. Correct persistent arithmetic is therefore
**1164 + identity20 + mailbox56 + arrival4 = 1244**, not 1164 + 880.
This exceeds the nominal **unowned** 1224-byte overlay/gap by 20 before further
bindings. The const stock-pointer binding adds 12 if placed in RAM. Event32 is
currently stack scratch, not another persistent allocation.

Compiler-local stack is owner step 88/service 40/supervise 8, mailbox 8–28 and
wait 16. These figures are not nested stack, interrupt reserve or proven task
headroom. No choice to move receipts to the stack is approved by this arithmetic.

A bounded compiler-only study also failed to solve capacity. Pinned Apple
Clang bitcode is rejected by Zig LLD. Compatible direct LLVM20 `-Oz` LTO saves
72 input bytes for all 25 or **40** when all nine moved objects stay exact.
The latter still needs at least **10,570/9,520**, 1050 over. Function names and
bindings remain, but exact sizes/toolchain/object selectors change and require
broad revalidation. It is not the accepted build, a storage approval or an ELF.

## Validation archives and next work

The unchanged main 3251-case suite was rerun successfully in **424.69 s**, zero
skips/failures/errors, at
`firmware/unified/build-20260925-control-owner-regression-v1/`.
That main source list does **not** include the new owner/mailbox/wait units;
their integration proof is separate, not implied by the 3251 result.

The combined guarded checkpoint is complete at
`firmware/unified/research-20260925-control-owner-v2/`: **258 passed in 90.35 s**,
zero failures/errors/skips/xfails. Scope is 116 mailbox + 31 wait + 16 budget +
32 owner + 63 preceding retired-switch/discovery/budget cases. All 258 ordered
identities and 774 setup/call/teardown phases match and pass. The manifest
records **767 content hashes**: 440 inputs, 324 artifacts and 3 reports, plus
four tools and three support fingerprints (launcher, SDK metadata and the
optimization report). Main regression and prior discovery evidence are checked
before/after; hashing is boundary drift detection, not a hermeticity guarantee.
Independent final review rehashed all 767 files, tools/support, nested code
reports and repeat builds, verified all identities/phases and independently
reconstructed the 25-object budget and unchanged placement/refusal policy.

Owner/mailbox artificial ELFs and code reports are preserved there alongside
the expected full25 link refusals and the bounded optimization study. The main
regression's 371 content hashes, four tools and SDK metadata were independently
verified; both main ELFs remain byte-identical to the preceding baseline.

- Main manifest SHA: `061b0f851942f286a2868f4b222641ff910cd36b037c882151bfd59e30dabaeb`.
- Budget SHA: `bef0a01786a01e84b4bc998c012375eb70612010013181755d4b423d63e005f0`.
- Supplement SHA: `7dcf4fb5ad98f4798b2e3dc3b9f6a059f9a38bef4a98f37056a16c408eb69a36`.
- Reproduction launcher: `/tmp/whip-control-owner-proof.46Zyej/run.py`;
  choose fresh output paths for another run, never overwrite the archive.

The retained `research-20260925-control-owner-v1/` passed 258 tests but stopped
during evidence packaging because pytest's `current` symlink duplicated a
report path. It has no aggregate success manifest. V2 excludes the alias and
reruns the full scope; no C/test change was required. Earlier owner-wait-v2
source pins changed with this work and are historical, not current validation.

Next finite work is actual owner/callback/clock/boot-ID binding and bounded
service/output handoff, paired with a real whole-code/storage solution. No
additional speculative ring instrumentation is authorized by this checkpoint.
Physical FIFO/source/model quality, optical STOP/current-settings resume,
steps/sleep/history and recovery remain independent requirements. No finite
test count can substitute for their missing evidence.
