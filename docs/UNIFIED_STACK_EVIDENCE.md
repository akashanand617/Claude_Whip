# Stack captures: independent bounded review

Reviewed entirely off-ring, 2026-09-24/25. The three captures are internally
consistent and identify useful task/paint observations on installed V2 with
optics disabled. They do **not** establish stack-pointer depth, future headroom,
stock-Health maxima, owned RAM or a closed release gate. No device access,
firmware edit, deployment, commit or push occurred in this review.

## Archive and transcript checks

All six files named by the three `SHA256SUMS` files match. An independent
offline check verified all request packets' CD01 command, address, length,
padding and checksum; strict request/reply alternation and matching logged
address/length; increasing transaction timestamps; and the complete fixed
order, including the 95-transaction prerequisite and seven postchecks.
Prerequisite bytes match the pinned V2 sites, diagnostic code, configuration,
descriptor and ROM identifier. This is sampled identity, not full attestation.
All sessions finish with `disconnected {confirmed: true}` then `completed`
naming the capture hash; no abort or unexpected-notification event appears.
CD replies themselves contain no address or request identifier, so matching
means the serialized transcript association, not cryptographic correlation.

| Session under `firmware/research/2026-09-24/` | Requests/replies | Raw reply checksums checked | Redacted replies |
|---|---:|---:|---:|
| `ram-ownership-stacks` | 198/198 | 142 | 56 |
| `ram-ownership-tcbs` | 194/194 | 194 | 0 |
| `ram-ownership-stack-watermarks` | 454/454 | 102 | 352 |

| Session | Capture SHA-256 | Transcript SHA-256 |
|---|---|---|
| stacks | `9cc0038e7bd1233898acfad16f613ec7d20a5c14a37794716b4249c6b4b9ed9f` | `88617ba26c8286d42217eb1e728605fed9789d9ed472651574a1791bb7471584` |
| tcbs | `45f5f16b8f13da5f3f3e3907a0abe2bcb4b61604eb8001f8e24f438c8439557e` | `c974f0bde7fa724615b160ef71553a9292471d1104d87e24b7725ae6b57c86c4` |
| stack-watermarks | `1101efed9615fa8961ac430fd08341be5d59938daa01aa11ff472a4dc8459405` | `65ac6388f77b530f35b4ff90a7650ff62b35455708063ad03f78cc353f958baf` |

The check rebuilt every new unredacted window from its individual responses:
four stage-1 windows and fourteen stage-2 windows, including both passes, each
matching saved bytes and embedded hashes. The existing focused tests also
passed: `pytest -q tests/test_fwram_read.py -k 'stack or tcb or watermark or paint'`
gave **13 passed, 29 deselected in 0.25 s**. This is not a full-suite rerun.

## Task observations and layout inference

Both `pxCurrentTCB` samples at `0x201340` contain `0x213768`. The first word of
both kernel windows at `0x201374` is `0x2117a0`. The independently rebuilt
handle table there starts with seven handles:
`0x211740, 0x212cb0, 0x213768, 0x214730, 0x2152f0, 0x215758, 0x215bc0`;
five following words are zero and the word at +48 is seven. The additional
TCB at `0x211740` was not read; its task identity/stack are unresolved.

The stage-1 kernel-list endpoint heuristic reproduces the six selected TCB
addresses from the two archived passes. The kernel window itself changes
between passes. Its `nonzero_handles` field and `handles: 56` event count
nonzero kernel words, including counters, sentinels and list links; they are
**not 56 task handles**.

| Captured name | TCB | Inferred `pxStack` (+48) | Inferred size | Priority (+44) | Bytes read | Reported contiguous A5 prefix |
|---|---|---|---:|---:|---:|---:|
| app | `0x213768` | `0x213360` | 1024 | 2 | 1024 | 192 |
| Tmr Svc | `0x215bc0` | `0x2157b8` | 1024 | 6 | 1024 | 504 |
| hub | `0x2152f0` | `0x2148e8` | 2560 | 2 | 1024 | 1024 (entire read) |
| qc_app | `0x214730` | `0x213928` | 3584 | 1 | 1024 | 1024 (entire read) |
| IDLE | `0x215758` | `0x215350` | 1024 | 0 | 256 | 256 (entire read) |
| UpperStac | `0x212cb0` | `0x2120a8` | 3072 | 5 | 512 | 512 (entire read) |

Names at +52, priority, stack base and the saved top word at +0 agree across
the two TCB passes. Mutable words differ at offsets +8/+12 for `qc_app`,
+4/+8/+12 for `hub`, and +4 for `Tmr Svc`. These are sequential live reads,
not an atomic scheduler snapshot. The saved top is not a measured current SP.

Sizes above reproduce `TCB address - 8 - pxStack`, as used by `tcb_table`.
The intervening eight bytes were **not captured**; identifying them as an
allocation header and inferring the exact extent remains a layout assumption.
The three app-task sizes agree with the separately reviewed stock creation
arguments in [UNIFIED_MEMORY_AUDIT.md](UNIFIED_MEMORY_AUDIT.md). That agreement
does not establish every kernel task's allocation or lifetime. The exact
captured name is `UpperStac`; the expanded label `UpperStack` is interpretation.

## What redaction and paint establish

Raw MSP/task stack bytes are absent from the captures and transcripts. Saved
data comprise profiles and 16-byte block hashes; transcript replies retain a
packet hash and zero flag. Arbitrary mixed stack contents and their checksums
cannot be independently reconstructed from those records.

The known all-`0xa5` candidate can nevertheless be hashed without recovering
unknown data. Every MSP packet hash, including its checksum and final short
packet, matches that candidate, as do all 24 block hashes in each pass.
Thus the sampled `0x203200..0x203380` window contains 384 A5 bytes in both
reads, consistent with the captured ROM paint loop described in
[UNIFIED_ROM_RESUME_EVIDENCE.md](UNIFIED_ROM_RESUME_EVIDENCE.md).

The same independent comparison confirms every packet/block of the four
entirely painted task windows. For `app`, twelve saved block hashes confirm
192 initial A5 bytes; whole-packet hashes independently cover the first 182.
For `Tmr Svc`, packet hashes confirm 504 initial A5 bytes; block hashes cover
496. The next mixed packet/block differs from the all-A5 candidate. Exact
first-nonpainted-word positions and total painted-word counts still depend
on the saved profile calculation; unknown mixed bytes were not reconstructed.

An intact paint byte can have been skipped by an SP adjustment, overwritten
with the same value, restored or repainted. These multi-packet reads are also
non-atomic. Paint therefore records sampled contents, not a strict historical
SP bound, proof of never being touched, or guaranteed future reserve. Reset,
DLPS and paint lifetime remain unresolved. V2 optics-off workload is not
stock Health or unified switching.

The archive READMEs' `MSP depth ... <= 1152` and `minimum headroom` wording,
`paint_profile.max_depth_bound_bytes`, `stack_profile.headroom_lower_bound_bytes`
and similarly named tests overstate this evidence. The value 1152 is the
arithmetic distance `0x203800 - 0x203380`; the tests establish that arithmetic
on fixtures, not historical SP behavior. Comparing the reported 192-byte
app prefix with a 244-byte candidate call chain does not alone prove either
fit or impossibility: the actual caller, nesting and execution context must
be established. No stack reuse or enlargement is approved by these captures.

## Next finite inference

Use the six observed task identities/bases to map each proposed unified hook
to its actual stock task and full caller chain. Verify the exact allocation,
TCB and fill semantics before treating inferred sizes as owned extents; then
budget the complete nested path and applicable interrupt/context costs under
the intended Health workload. Keep the seventh task and MSP/context lifecycle
explicitly unresolved. The captures narrow that analysis without approving a
task binding, allocation or another device session.
