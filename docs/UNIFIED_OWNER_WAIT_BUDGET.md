# Control handoff and idle-wait checkpoint

**Historical checkpoint, superseded by [the integrated control owner](UNIFIED_CONTROL_OWNER.md).**
Current code has a two-frame 56-byte mailbox, real `wuw_supervise` composition
and 25 objects. The strict link now refuses three physical bindings, not the
supervisor function. Input-only append lower bound is 10610/9520, 1090 over.
The old 131-test/v2 result and hashes below describe the preceding source;
they must not be presented as current-source validation.

2026-09-24/25. **Off-ring, not flash-ready.** Claude retains separately
authorized live-device work. Health remains unified boot/default and Gesture
temporary/opt-in. Codex changed no stock image, device, production source list,
hook plan, app admission or release gate.

## Implemented, but not attached

- [Control mailbox](UNIFIED_CONTROL_MAILBOX.md): one copied 20-byte frame,
  generation and original arrival time; current overflow/invalid length closes
  with FAULT, closure outranks undelivered input, and stale generations cannot
  overwrite a new session. Copies preserve PRIMASK. It is not a physical fence,
  dispatcher, authorization rule or complete owner.
- [Wait wrapper](UNIFIED_SUPERVISOR_WAKE.md): exact two-register candidate for
  the stock qc_app semaphore-take BL at file `0x135c`. It requests a 100 ms wait,
  polls after either take result and preserves stock's raw zero/nonzero branch.
  The real `wuw_supervise` provider is deliberately **strong and undefined**.
  There is no production weak/no-op fallback. Only a proof-only counter supplies
  that symbol in the isolated ARM tests.

An idle failed take is not necessarily a timeout. A blocked stock handler still
prevents another poll. No elapsed cadence or 1 s/3 s/10 s deadline has been
established. The mailbox does not wake a task, recall delivered work or invent
physical completion receipts. Valid pointers, maskable single-core producers,
fresh clock units and an externally serialized consumer remain preconditions.

The one-slot design can reject a valid burst of two control fragments if the
consumer has not taken the first before the second arrives. Closing on overflow
is intentional protection, not proof of usable app throughput. Real fragment
admission/backpressure and wake/service ordering must be qualified together;
do not assume requesting a 100 ms idle wait solves this interaction.

## Whole-candidate cost: refusal, not a fit

`probe/owner_wait_budget.py` batches both new units with the **22 exact prior
objects**. Each new object and stack-usage output is compiled twice and hashed
immediately. The existing nine **unowned** text placements and APP bound stay
unchanged; no unwind is discarded and no fake owner is linked.

| Quantity | Measured or derived result |
|---|---:|
| Objects / functions / constants | 24 / 139 / 3 |
| Mailbox text | 480 bytes |
| Wait wrapper text | 72 bytes |
| All input text | 11,388 bytes |
| Input read-only constants | 288 bytes |
| Text assigned to existing unowned intervals | 1,894 bytes |
| Append **input-only lower bound** | **9,782 bytes** |
| Configured append allowance | 9,520 bytes |
| Minimum excess before remaining costs | **262 bytes** |
| Input unwind, retained for linking | 1,112 bytes |

The lower bound is `11388 + 288 − 1894 = 9782`. It excludes alignment,
veneers, final linked unwind and every unimplemented owner/hook. It is **not** a
successful linked size. The old 22-object ELF's 264-byte margin no longer
describes the full implemented candidate. All three strict link attempts
refuse the missing `wuw_supervise`; no full24 ELF is produced. The failure map
is archived as `failed-link-NOT-FIT.map`, never counted as successful fit.

Mailbox state needs 32 persistent bytes and a separate 32-byte consumer event.
If added to the previous 1184-byte planning selection, persistent arithmetic
becomes **1216 bytes**, before further owner resources. This is not an allocated
layout or proof that the nominal unowned 1224-byte overlay/gap can be used.
Event scratch reuse has not been established. Compiler-local stack frames are
8–24 bytes for mailbox functions and 16 for the wrapper, excluding caller,
interrupt, supervisor, ROM and stock-handler nesting. Stack paint is not reserve.

## Final guarded checkpoint

Archive: `firmware/unified/research-20260925-owner-wait-v2/`.

**131 tests passed in 41.44 s**, zero failures/errors/skips/xfails:
84 mailbox, 31 wait/stock-loop, 16 budget/integrity cases. Collection identities
match execution and all 393 setup/call/teardown phases pass. The proof manifest
records **279 content hashes**: 262 inputs, 14 artifacts (including the budget
report), and three test reports; three tool executables and the launcher are
also guarded. The previous 63-case supplement's 253 content hashes were checked
before and after. The unchanged 3251-case main suite was not rerun.

Independent final review rechecked all 279 content hashes, the three tools and
launcher, exact 131 identities/393 phases, lower-bound arithmetic, unchanged
placement policy and all three genuine missing-provider link refusals.

- Budget report SHA-256:
  `26630ef432b42d08e98846864dbb0ee3854aea1dca142860043aceaba76a8c43`.
- Proof supplement SHA-256:
  `45b82ad5414076cba77c0af1c5544bb8883135b0a9ad5750bb11b835dbe935fa`.
- Reproduction launcher: `/tmp/whip-owner-wait-proof.YPtUUy/run-v2.py`.
  Use new output paths for another run; existing reports are never overwritten.

Independent review prompted two budget-guard fixes: missing required sources
now refuse instead of dropping from the input guard, and local ELF symbols
cannot satisfy external references. Six additional cases cover these fixes,
including actual compiled static/global/weak definitions. The earlier
`research-20260925-owner-wait-v1/` retains the pre-hardening 125-test result;
its changed source pins are historical and **v2 is the current checkpoint**.

Mailbox tests use actual ARM with an independent semantic oracle, 2,800 state
events, 82 selected legal producer interleavings, IRQ-context/mask checks and
negative mask/restore mutants. These internal vectors are not extra test cases.
Wait tests use one emulator-only stock BL edit; original surrounding stock
instructions execute, but ROM semaphore, stock-body calls and supervisor are
explicit fixtures. The two candidates execute in **separate artificial proof
ELFs**, not a whole24 integrated firmware. Source hash checks detect drift at
boundaries, not all transient edits or a hermetic toolchain.

## Next finite integration work

1. Implement the real serialized owner/provider and commit-time generation
   validation against the actual stock paths, preserving physical boundaries.
   Qualify fresh time, semaphore lifetime, two-fragment input admission and
   bounded work per service pass.
2. Rebudget that whole owner, callbacks and hooks together. Establish code/RAM
   ownership; do not enlarge holes or treat the former 264-byte margin as fit.
3. Connect the implemented handoff and provider into the persistent stock-path
   Health→Gesture→Health witness, explicitly retaining unresolved ROM/physical
   fixtures until measured. Then rerun full regression at that integration point.

Physical fresh motion, optical STOP/current-settings resume, real steps/sleep
records and viable recovery remain separate [release gates](UNIFIED_READINESS.md).
None closes from this checkpoint; no installable container was made.
