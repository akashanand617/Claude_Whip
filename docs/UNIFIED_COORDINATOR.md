# Unified switching coordinator — implemented, unattached

2026-09-24. Entirely off-ring. Health remains boot/default, Gesture temporary
and opt-in. The installed ring remains V2 optical-off. This work does not
produce or authorize an installable image.

## What is now actual C

`firmware/unified/stock_coordinator.{c,h}` joins the existing adapter, checked
stock RESET/STOP writes, optical-work retirement and atomic current-settings
Health commit. It is a separately compiled **unlinked candidate**, not another
mode machine or a production capability. The owner points to the existing
adapter and preserves the original token/session/Health generation.

The positive ARM test runs Health → Gesture → Health through this coordinator
and exact stock sample-read, clear, bus-write and notification paths in one
persistent emulated state. Cancellation, queue fencing, physical STOP,
accelerometer ownership/source provenance and fresh scheduler preparation still
come from **explicit test fixtures**. Executing this C does not turn those
fixtures into hardware evidence.

| Stage | Implemented behavior | Still requires a real binding |
|---|---|---|
| Drain | Waits for proven nonempty inventory, all cancellations, zero in-flight work and completed fence | Original producer identities, timer/IRQ/hub/result/transport draining |
| Submit STOP | Executes checked stock RESET/STOP at most once for the captured identity; retains success internally | Correct live bus ownership and lower-call execution contracts |
| Observe STOP | Requires a separate original-identity receipt and fresh time; successful writes alone cannot advance | Physical optical shutdown observer |
| Retire | Uses the original Health pause token after the controller may already have issued HOLD with a new token; clears actual stock software work | Owned/living buffer/status objects and complete old-callback drain |
| Gesture | Gates HOLD completion on successful retirement; uses the existing adapter source gate | Physical hold/start, fresh 25 Hz completion/overflow/timing evidence |
| Resume | Starts from current settings revision, accepts fresh preparation, then invokes the atomic final Health commit | Serialized writer/version owner, fresh jobs and current-settings scheduler rebound |

All entry points require thread mode with interrupts enabled. One serialized
task must own the coordinator **and every adapter/lifecycle operation**. This
is a binding obligation; no RTOS queue/lock has been attached. Input/output
objects must have valid, non-aliasing storage for their documented lifetime.

### Partial entry and quiet resume

A return to Health during incomplete Gesture entry may need a new cancellation,
fence, STOP and software retirement under a new resume identity. The new
`wh_retirement_allowed` accepts PAUSED or RESUMING only while the same complete
quiet predicate holds. It does not change `wh_quiesced`, which remains
PAUSED-only, and does not relabel Health state to manufacture permission.

After a fully retired pause, resume may carry retirement only for the same
Health generation/session and the captured stock buffer/status objects. Old
STOP/source/preparation receipts cannot borrow the current token. A changed
settings revision, including change-and-change-back, prevents an old
preparation from committing; current control bytes are also checked.

Fresh-job preparation may **begin only after `WC_WAIT_RESUME`**, under the same
serialization and original identity. The coordinator does not issue a
preparation nonce: receiving a receipt after retirement does not establish
when its work occurred. The eventual binding must enforce this ordering.

### Independent review and failure behavior

Independent review found that a successful lower STOP call could return with
interrupts unexpectedly masked. The coordinator now checks returned PRIMASK,
latches Health/action failure and preserves that mask; it cannot report
`WC_STOP_SUBMITTED` in this case. It does not clear an unknown critical section.
A regression injects the violation at the original mutex-release return.
This protects the coordinator's return boundary, not every intermediate lower
call; complete lower-binding correctness remains required.

The integrated retirement oracle now checks the actual coordinator path for
masked stock-buffer writes. A deliberately broken retirement-mask mutant is
detected. Negative cases also cover STOP/reset/mutex failures, stale receipts,
edited diagnostic reports, missing inventory, pointer mismatch, partial entry,
timeouts, disconnect, charging, ISR entry and revision/control changes.

`tests/test_stock_coordinator.py` passed **32 focused cases in 10.48 seconds**
before the full guarded run. These overlap the guarded suite; do not add their
count to it. The source is rebuilt and its candidate object/ELF reproduced.
Only the two reviewed sample-reader call replacements exist in emulator memory;
no stock binary on disk is patched.

The older `test_stock_switch.py` separately feeds the original stock motion
consumer in eight transition phases. The new coordinator's positive source
receipt is still synthetic; neither test establishes actual step counts,
overnight sleep or optical-history continuity.

## Whole implemented budget, including this coordinator

The guarded builder now attempts one fixed-bound link of all 16 existing
components, Health commit, service database, coordinator and compiler runtime.
It excludes all test support. The link must fail specifically for real final
region capacity; an unexpected successful link or unrelated error aborts this
negative proof. Both the compiler-driver and direct-linker attempts are saved.

Current failed-map measurement in
`firmware/unified/build-20260924-coordinator-v1/`:

- Text/constants: **10,948 bytes**; linked unwind: **96 bytes**.
- Total attempted extent: **11,044 bytes**, **1,524 beyond** 9,520 configured
  bytes, before the remaining hardware/communication hooks.
- No full-candidate ELF exists. A failed map is not an approved layout.
- Coordinator object: **1,106 text bytes**, 72 input unwind bytes; input unwind
  cannot be summed as if it were final coalesced unwind.
- Coordinator owner 28 bytes, original STOP receipt 28, resume receipt 20;
  the latter already contains the 16-byte prepared object. Revision adds four.
- Dispatcher/frame/fence 796 + source receipt 288 + coordinator owner 28 +
  STOP receipt 28 + resume receipt 20 + revision 4 = **1,164 candidate persistent
  bytes**, before other callbacks/hooks. No storage is allocated or owned.

Claude's separate RAM prototype fits these selected objects without padding
inside its **unapproved** 1,224-byte overlay-plus-gap candidate, leaving 60.
That is layout arithmetic, not boot/DLPS/ROM lifetime proof. Its standalone
prototype still uses the previous checkpoint's stock objects; it is not the
current integrated image. See [RAM ownership](UNIFIED_RAM_OWNERSHIP.md).

Local coordinator stack frames are 8/72/40/48/24 bytes for init/pump/STOP
observer/resume/physical completion respectively. These are not nested-call,
outer-task or interrupt stack budgets; no approved stack fit follows.

## Linker boundary correction, without more capacity

`stock_append.ld` retains the exact `append` region at `0x847ad0`, length
`0x2530`, with no writable static sections. Its redundant end assertion was
evaluated against provisional unwind sizes before LLD coalescing; only that
premature assertion was removed. Final linker region checks and the mandatory
ELF verifier still enforce the same `0x84a000` limit.

The verifier is stricter: it checks exact section types/flags/alignment/file
extent, the two load-segment/section mappings and the unwind program header.
Zero-sized extra loads, malformed paddr/offset/flags and sectionless padding
are rejected. Boundary tests retain all component roots, link at the exact
limit reproducibly and reject additional payload. A temporary reinstatement
of the old assertion reproduces the false rejection.

This ordering agrees with the pinned LLD implementation's
[address finalization before final checks](https://github.com/ziglang/zig-bootstrap/blob/7ef74e656cf8ddbd6bf891a8475892aa1afa6891/lld/ELF/Writer.cpp#L1960-L1984)
and [final region overflow checks](https://github.com/ziglang/zig-bootstrap/blob/7ef74e656cf8ddbd6bf891a8475892aa1afa6891/lld/ELF/LinkerScript.cpp#L1642-L1660).
The separate relocation diagnostic intentionally retains its older strict
script and refusal evidence; it is not a production placement exception.

## Next concrete bindings

The [settings-writer inventory](UNIFIED_SETTINGS_WRITERS.md) identifies 18 direct
byte stores, seven enable leaves, interval/default/FTL paths and different
execution owners. Legacy BF permits arbitrary RAM writes; ordinary setter
hooks cannot protect a revision counter from that path. BF retirement before
the legacy stateful prelude, and gating CE/CD side effects, are required design
work, not implemented protections.

The follow-up pins a proposed early filter to the complete stock BL at file
`0x7b0a` (`fe f7 8a f8`), after the callback's pointer/attribute checks but before
its mode/length gate and stateful prelude. The helper must preserve the full
32-bit length comparison and mode-1 rejection before opcode access, as well as
the callback's saved return/register contract. The nearby `0x5c2e` branch is
**not** a safe four-byte overwrite because it shares the rejection return at
`0x5c30`. This is a concrete next off-ring implementation target, not a compiled
filter, installed patch or permission to interfere with Claude's device session.

The [code-space research](UNIFIED_CODE_SPACE.md) measures possible reductions
against an older checkpoint. Those experiments are not adopted here and their
earlier positive-room arithmetic excludes this coordinator. Symbol-only ROM
helper substitutions are weaker than executing captured code. Approved
reclaimed flash remains zero. See [the finite readiness checklist](UNIFIED_READINESS.md)
for the still-open physical source/health continuity, ownership and recovery
gates; the full guarded result is recorded in [the resource handoff](UNIFIED_RESOURCE_BUDGET.md).
