# Unattached control mailbox: ARM contract evidence

## Current two-frame implementation — 2026-09-24/25

The [integrated owner checkpoint](UNIFIED_CONTROL_OWNER.md) supersedes the
single-slot implementation below. Current mailbox size is **56 bytes**, with
two copied 20-byte slots, individual arrival times and a two-entry FIFO. It
holds one complete fragmented command, not an arbitrary command backlog.
The third queued current-generation frame closes with FAULT. Host admission must wait
for the complete reply before the next command; no production sender is bound.
`wim_admitted` supplies a mask-preserving snapshot, not a future commit lease.

**116 focused guarded tests pass**, including 2,800 randomized state events and
136 legal actual-ARM producer injections inside 14 selected scenario cases.
The independent oracle compares all 56 mailbox bytes and all 32 event bytes.
New cases cover a complete burst, refill/head wrap, per-slot expiry, expired
head dropping a fresh second slot, stale third input and admission snapshots.
These internal vectors are not additional pytest cases or arbitrary schedules.

Current text is **564 bytes**, input unwind 56, no writable static data. Local
stack is init/open 8, post 28, close 20, admitted 16, take 24 and retire 16; not nested
stack or physical headroom. The latest aggregate report and archived artificial
ELF/code report are in `research-20260925-control-owner-v2/` under
`firmware/unified/`. Actual C owner composition is now separate evidence;
owned storage, a real callback/clock binding and physical fencing remain open.

Source SHA: `8a2a7240a55f8206236635c4e49dc535afbb9ee1246a4ea3e95c8ef6ce62c228`.
Header SHA: `e4cb325aa11a40b46cc75f7cc41f0427744b2326f6229186caba4fcd53b37e88`.
Test SHA: `c240172ce2d2c215318d9666babe1a73dfddf5b23ebe25c34bbc73bbb5754bba`.

## Historical single-slot checkpoint

Everything below describes the preceding 32-byte/84-case version, not the
current source pins or queue capacity. Its raw evidence is retained as history.

2026-09-24/25. Entirely off-ring. The mailbox source is a new standalone
candidate; this review added only `tests/test_control_mailbox.py` and this
document. No stock bytes, production source inventory, task binding, device
state, OTA image, deployment or release gate changed.

## Result and purpose

The 32-byte mailbox safely transfers one 20-byte control frame under its stated
single-core, maskable-context contract. Its separate consumer event is another
32 bytes. **84 guarded tests passed in 4.20 s**, with no skips, failures or
collection differences. This is an input-handoff primitive, not a dispatcher,
serialized firmware owner, command authorization or physical transport fence.

`wim_post` and `wim_close` can be called by task or normal maskable-IRQ producers.
Open, take and retire belong to one externally serialized consumer. Initialization
must occur once per boot before producers/retained callbacks exist. PRIMASK
cannot serialize NMI, HardFault, DMA, reset or another core. Valid, disjoint
storage and frame-read lifetime remain caller obligations.

| Operation | Tested meaning |
|---|---|
| Open | Requires logical retirement and a strictly increasing nonzero generation; maximum generation cannot wrap or be reused |
| Post | Copies exactly 20 bytes and the original arrival timestamp; never overwrites a pending frame |
| Bad current input / overflow | Closes with FAULT and logically drops pending input; a false return still requires consumer wake/service |
| Stale generation | Does not change a newer mailbox, even with an invalid frame address or length |
| Close | Outranks a pending frame; valid reason bits accumulate and newly added reasons cause a new close event |
| Take | Delivers at most one event; a frame older than 1000 ms becomes FAULT instead of a FRAME; exactly 1000 ms remains eligible |
| Retire | Requires the close to have been reported; actual callback/send fencing is an external precondition, never manufactured here |

FRAME events retain generation, original arrival time and exact payload, with
zero reasons. CLOSED events contain generation and accumulated reasons, with
zero timestamp/payload. NONE/null refusal leaves the output untouched. Close
and retirement invalidate the pending flag; they do not securely erase old
mailbox payload bytes. Exactly 20 arbitrary bytes are accepted: wire-content
validation remains downstream, not a claim of this module.

Close cannot retract a FRAME already copied to consumer scratch or an in-flight
operation. The binding must revalidate ownership at actual commit and retain
original identities through delayed work. Reinitializing to reuse generations
while old callbacks exist would violate the contract.

## Independent tests and interleaving limits

The Python semantic oracle models retired/open/closed states independently of
the compiled C. After every step it compares **all 32 mailbox bytes and all
32 event bytes**, including stale private storage and untouched-output behavior.
Four seeded sequences exercise 2,800 persistent events. Directed cases cover
nulls, invalid lengths/reason masks, stale and exhausted generations, input
alignments 0–3, overflow, repeated/new close reasons, retire/open ordering,
unsigned timestamp wrap and the 1000/1001 ms boundary. Deliberately invalid
backward chronology is tested as refusal, not support for ambiguous intervals
of at least `2^31` ms. Correct monotonic milliseconds still require a binding.

The strict Unicorn harness executes actual ARM mailbox and compiler-runtime
instructions at artificial addresses. It permits execution only within linked
function spans, rejects reads/writes outside exact caller objects, enforces
16-byte canaries, checks unchanged input, AAPCS registers/stack and original
PRIMASK. Every live mailbox, event or input access must occur masked. Both
initial mask states are exercised; six producer cases preserve simulated
maskable-IRQ IPSR values 16, 31 and 63 without calling the consumer.

Eight selected producer/consumer scenarios inject an actual compiled producer
at **all 82 legal unmasked instruction boundaries** in their baseline paths,
including every unmasked memory-instruction boundary. They cover post/post,
post/close, take/close, take/post, empty-take/post, close/post, accumulating
close reasons and stale-post/close. Before-lock and after-unlock outcomes must
match the corresponding serial oracle ordering. Starting masked exposes no
legal normal-IRQ injection point; there is no injection halfway through the
masked payload copy. Separate negative ELFs with the post-path CPSID or PRIMASK
restore removed are both detected.

The injected producer has separate artificial registers/stack and shares only
mailbox bytes with the paused consumer. This models a legal complete producer
between instructions; it does **not** execute hardware exception entry/return,
priority arbitration, concurrent DMA or arbitrary nested schedules. These 82
interleavings are test vectors inside eight pytest cases, not 82 extra cases.
Likewise, the randomized events are not additional pytest cases.

## Build provenance and measured local cost

The fixture verifies the pinned Clang, Zig 0.15.2 and Python executable hashes
against `build-20260924-raw-ingress-v1/manifest.json`, and uses its unchanged
ARM flags. It verifies the existing wire header/compiler-runtime source pins
before compilation. Mailbox, compiler runtime and the small ABI assertion shim
are each compiled twice; each object and `.su` file is snapshotted immediately
before any subsequent command. Two links also match byte-for-byte and are
immediately snapshotted. Inputs/tools/artifacts are rechecked at each command
boundary and fixture teardown. Command logs include stdout, stderr and status.

The mailbox object contains **480 text bytes**, including two alignment bytes,
with no writable static section. These are compiler-reported local frames:

| Function | Function bytes | Local stack bytes |
|---|---:|---:|
| `wim_init` | 14 | 8 |
| `wim_open` | 52 | 8 |
| `wim_post` | 120 | 24 |
| `wim_close` | 76 | 20 |
| `wim_take` | 152 | 24 |
| `wim_retire` | 64 | 16 |

These figures exclude enclosing caller/IRQ/ROM depth and are not physical
headroom, approved RAM, complete linked growth or whole-firmware fit. The
artificial ELF deliberately fails the unchanged production placement inspector.
No core/RTOS/hardware call or physical completion receipt was introduced.

The focused proof directory is `/tmp/whip-mailbox-proof.iJ3LvE/`:

- Collection: `collected.json`, SHA-256
  `8301dd85ebe2d520ab7b5866db453e5bc110cb3472b4b5e95e83ae02bf1774f0`.
- Execution: `executed.json`, SHA-256
  `d27d752b9526aaeae7625ef94c89a6cfd02335469b0be7ab97d763883d4c143d`.
- Code report: `artifacts/control-mailbox0/mailbox-code-report.json`, SHA-256
  `27a9b75e9b023e7149f81e7e3958a3c4d1533360fc22fce380fbb03a163a82cc`.
- Artificial ELF: `artifacts/control-mailbox0/MAILBOX-ARTIFICIAL-NOT-INSTALLABLE.elf`,
  SHA-256 `f9205143704e342443722e743427a1409bf90b870beb2898243c88c25494d1e0`.

All 12 report input hashes and 22 artifact hashes were independently rechecked,
in addition to the three executable pins and valid matching guarded reports.
Source `control_mailbox.c` SHA-256:
`43c9524eee5c1de54447992dcd5cef9f5dfe98de5be3996f0494003c99ca92af`.
Header SHA-256:
`f8fbee83a8480990461f98b064459c15e082100aa7e797b2b74b4b9bba9e88b1`.
Test source SHA-256:
`ddd6498ce80de92019c829d167a0e4bc4f65a49adfcff615df97a98f6fc43e82`.

Reproduction requires the pinned proof Python and `WHIP_ZIG`. Run only
`tests/test_control_mailbox.py` with `-c /dev/null --noconftest -o addopts=`,
explicit repository `--rootdir`, `-p no:cacheprovider -p whip.fwproof_guard`,
and the sanitized environment from `whip.fwproof_guard`. First collect with
`--collect-only --proof-report NEW_COLLECTED`; then execute with
`--proof-expected NEW_COLLECTED --proof-report NEW_EXECUTED` and a new temporary
artifact directory. This is a focused run, not a full regression checkpoint.

## Review outcome and remaining integration

No blocking transition defect was found under the stated contract. Review
caused two header clarifications: only maskable task/IRQ producers are covered,
and only FRAME events retain arrival time. No behavior change was required.
The fixed slot, closed-state persistence and monotonic generations are kept
because they prevent overwrite, lost closure and stale input relabeling; no
general queue framework or speculative callback interface was added.

The [task map](UNIFIED_TASK_BINDINGS.md) still has no approved serialized owner
or supervisor cadence. This mailbox supplies neither a wake source nor a bound
on service latency: rejection must wake the consumer too, and a frame can expire
while no new traffic arrives. Actual GATT callback context/lifetime, disconnect
and charging identity, generation issuance, owned storage, fresh clock, bounded
handoff, physical drain and commit revalidation all remain required. The A5
[stack samples](UNIFIED_STACK_EVIDENCE.md) cannot approve the added scratch or
interrupt/caller stack, and installed V2 optics-off is not stock Health load.
