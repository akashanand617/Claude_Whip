# Queue timestamp storage: tested off-ring experiment

2026-09-24/25. **Not adopted into the accepted core; not flash-ready.**
Health remains boot/default, Gesture temporary/opt-in. No ring access, firmware
container edit, source-pin replacement, memory allocation, production hook,
deployment, commit or push occurred. Claude retains separately authorized ring
work; no new physical results were received for this checkpoint.

## Result

An isolated generated C variant saves **64 persistent RAM bytes**, preserving
all 32 motion queue slots, exact live timestamps, sequence/order, failure
behavior and public runtime APIs. The runtime alone grows 10 text bytes, but
recompiling all 25 objects with the smaller private layout saves 2 input bytes
overall. This is a RAM improvement, **not a solution to code-space capacity**.

| Quantity | Accepted baseline | Generated low16 variant |
|---|---:|---:|
| Runtime state | 408 | 344 |
| Embedded control owner | 880 | 816 |
| Selected persistent planning subtotal | 1244 | 1180 |
| Runtime text | 752 | 762 |
| Whole25 append input-only lower bound | 10610 | 10608 |
| Minimum excess over configured 9520 | 1090 | 1088 |
| `wr_next` compiler-local stack | 24 | 32 |

The 1180-byte subtotal would leave 44 arithmetic bytes in the nominal 1224-byte
overlay/gap **if that region were usable**. It is not approved or owned, and
remaining bindings are additional. The +8 local stack bytes need nested-path
review; persistent savings are not measured stack headroom. Accepted sources
still use the left column. No successful production ELF exists in either case.

## Why the representation is lossless under the existing contract

Only the queue's full32 timestamps become low16 values. The pending/in-flight
timestamp, current source time and clocks remain full32. Before an accepted
offer, `wr_tick` requires current time to be at most 249 ms after the previous
source time. Freshness and forward-source checks then bound each accepted
source advance by 249 ms.

An unconsumed FIFO entry can coexist with at most 31 later positive-count
offers: every accepted offer consumes at least one of the unchanged 32 slots.
Before dequeue, the current-time check adds at most another 249 ms. Therefore
the oldest live entry is at most **32 × 249 = 7968 ms** old. Its age cannot
alias modulo 65536. The variant reconstructs the exact full timestamp before
making it pending; no quantization, interpolation or new timing assumption is
used to make old data fresh.

This depends on initialized, exclusively owned runtime state and the existing
queue/cleanup paths. Directly mutating the embedded tap or bypassing runtime
ownership is not supported. Clock qualification and physical acquisition
provenance remain separate requirements. Generated compile-time assertions
bound the positive capacity/horizon using a wide product, avoiding overflow.

Changing array alignment reuses two padding bytes before the queue (offset268
becomes266); later full32 members realign, so total savings are64, not66.
Unused queue slots and non-live pending scratch need not preserve their old
private bytes. A specifically tested empty-dequeue case changes pending scratch
while `awaiting_send=false`; no public output or accepted completion exposes it.
Live pending identity and full timestamp match exactly.

## Evidence and its scope

`probe/runtime_stamp_budget.py` pins the existing 25-object checkpoint and
generates copies under a fresh output directory. It changes only generated
runtime source/header and the generated owner's size assertion. Every low16
object is recompiled with the generated header, twice. It does **not** edit
`firmware/unified/runtime.c/.h`, the accepted owner, builders or source pins.
All 146 function names/bindings with multiplicity and three constant identities
remain; six object binaries differ because of instructions or member offsets.
All nine conditional placement bounds and retained unwind policy stay unchanged.
The real link continues to refuse owned owner storage, stock-object bindings
and a qualified clock; no fake providers make it fit.

Final archive: `firmware/unified/research-20260925-runtime-stamp16-v1/`.
**44 guarded tests passed in 17.06 s**, zero skips/failures/errors/xfails:
39 runtime/representation cases and five stack-report integrity cases. All
44 ordered identities and 132 phases match. The proof records **1202 content
hashes** (775 inputs, 424 artifacts, three reports), four tool executables and
seven support fingerprints. The accepted preceding 767 content files remain
unchanged. This focused run does not re-execute the full 3251 or 258 suites.

Independent final review rechecked all 1202 content hashes, four tools, seven
support files, both generated builds and the 44 identities/132 passing phases.
It independently reproduced the 10608-byte lower bound and the same three
missing-binding refusals. No production ELF or ownership approval resulted.

Actual ARM differential execution compares the pinned full32 runtime against
low16, with strict memory/canary/AAPCS checks. Coverage includes 249/250 ms
boundaries, low16/full32 clock wraps, all 32 queue positions/capacity, maximal
7968 ms backlog, full pending identity, all-or-nothing faults, stale sessions,
sequence exhaustion and 1440 seeded persistent operations. The 7969 bounded
ages at five wrap anchors are an additional arithmetic check, not extra tests.
An actually compiled low8 negative variant falsely delivers a timestamp0 head
at time256 after a newer time249 offer; the tests catch the stale-data alias.

These are artificial **runtime** proof ELFs. The generated low16 control owner
has been compiled, not rerun through the full integrated stock-path witness.
That ABI-wide integration and nested-stack review are required before adoption.
No physical source, sensor shutdown, Health/steps/sleep or recovery gate closes.

- Budget SHA: `8ef1ff5f58842e09b7e9d2ef4300501397e80019a15d644b3498b0521e71fa62`.
- Supplement SHA: `cfced73f26753b7a0a9fc04bb50f9bcc6922586fb8fb7303895e3bde41cc3914`.
- Launcher: `/tmp/whip-runtime-stamp-proof.bhbqVC/run.py`; fresh output paths
  are required for reproduction. Existing archives are never overwritten.

## Parallel size investigations

Two source refactors were measured on scratch copies and rejected as a fit
solution: shared resume prechecks save0 text bytes; shared dispatcher clearing
saves10. Together they add16 input-unwind bytes and still leave at least1080
bytes excess before final linking. Their source copies, objects and report are
archived under `structural-study/`; no accepted source was changed.

A new read-only scan found378 indicator-helper instruction bytes at stock file
spans `f812..f824`, `11246..11364`, `121e8..1222c`, `f92e..f934`. It examined
67832 mapped halfword branch/PC-relative candidate positions and138013 unaligned
full-word pointer positions. Only retired-indicator/chain callers were observed.
After conservative entry allowances/alignment, the new planning allowance is
356 bytes. Adding unused existing bodies and known raw-helper allowances totals
768 hypothetical bytes—still322 short of the accepted1090-byte deficit before
new bindings/metadata. This is not an actual placement or ownership proof.

Keep shared epilogue `10e8a`, all literal pools and live lower helpers.
`f7ba` has retained callers through `1512/1682 → f94c` and is **not exclusive**.
No absence-of-reference scan closes computed/retained/ROM entries. Approved
reclamation remains **zero**; no linker hole was enlarged. The exact scan report
and reproducer are archived under `retired-descendants/`.

Next work must pair a real whole-code/storage solution with the missing actual
bindings and physical evidence. More passing isolated tests cannot convert
these candidate numbers into [flash approval](UNIFIED_READINESS.md).
