# Conditional known-root retirement in one emulator

2026-09-24. **Off-ring research, not flash approval.**

`whip/fwretirement.py` describes sixteen exact four-byte edits for an emulator:
fifteen entry stubs and the original UART callback's one complete BL. It does
not write a firmware file, emit a combined image/container, open BLE, change a
production verifier or grant ownership of any legacy region. Health remains
the required default; Gesture remains temporary and opt-in.

The focused combined suite passes **13 tests in 0.93 seconds**, zero skips or
failures. Its ELF comes from the new source-pinned A1/BF/CE/CD checkpoint and
conditional link, not the historical BF/CE/CD-only helper. That older helper
fails the policy oracle specifically on A1 and the whole planner refuses its
artifact hash. Root's broader guarded supplement is separate evidence, not
included in this focused count.

The final root-run guarded supplement passed **55 tests in 5.57 s**: these
13 combined cases plus 42 conditional-placement cases. All 55 ordered identities,
165 passing phases and JUnit agree; **277 content hashes** (228 inputs, 46
artifacts, three reports) plus three tools were checked before/after and by an
independent reviewer. Manifest in the conditional archive:
`proof-supplement.json`, SHA-256
`5d5c058abbe066ad662946450b986611dafa2d4a1b97f5ce50e2af925f304eac`.
This is separate from the full **3251-test** raw-ingress checkpoint, not a rerun
of that full suite or proof of complete firmware-to-hardware integration.

The first development run was 12 passed / 1 failed: the unchanged stock baseline
itself disagreed with a positive-probe A0 expectation when the named probe fixture
was deliberately false. The corrected oracle explicitly expects byte 3 to be
`00` or `21` according to that fixture, and checks the matching checksum. No
firmware, geometry, boundary or safety predicate changed to obtain the pass.

Current conditional ELF:
`firmware/unified/research-20260924-raw-retirement-v1/UNOWNED-raw-relocation-NOT-INSTALLABLE.elf`,
SHA-256 `9cad661e85edd74ebc9f425956aa1937da0dfa9f2f5344ddf20cf9d61109d432`.
All 21 objects / 130 functions remain. The separate link reports 9132 append
bytes, 388 configured bytes remaining, and 1894 moved bytes in **unowned**
regions. None of those figures grants ownership or complete-image approval.

## Exact inputs and records

Stock is the same 138016-byte 3.12.02 image, SHA-256
`b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0`.
Addresses in this document are file offsets; runtime XIP addresses add
`0x825fb0`.

The entry stubs are `movs r0,#0; bx lr` (`00 20 70 47`). They replace exactly
two reviewed, complete 16-bit instructions at each entry. The planner checks
the full original stock identity and each local old-byte witness, rejects a
wide-instruction prefix, sorts records and rejects overlap with another record,
retained shared regions or a loaded ELF section.

| Group | Entry offsets |
|---|---|
| Raw callback and A1 handler | `1e4a`, `2104` |
| BF, CE and CD handlers | `48c6`, `4b02`, `4c36` |
| Reviewed indicator entries | `3ac4`, `3b1a`, `3b7a`, `3c18`, `3cac`, `3cd2`, `3d36`, `3d9e`, `3dc0`, `3dc8` |
| UART hook, not a return stub | Complete BL at `7b0a`, old bytes `fe f7 8a f8`, redirected to inspected `wlg_receive` |

The record set is fixed: callers cannot provide arbitrary addresses or extra
stubs. The fifteen stubs plus one BL total **64 instruction bytes**. The
separately inspected ELF has its own conditional section changes; 64 bytes is
not the total relocated code size.

The source SHA-256 for the reviewed filter is
`b144becce22476ef0ba553b52a1226325a5fd789434b1b5822416e329ce28e35`.
The planner requires all of the following, rather than accepting a policy
boolean or trusting function names/sizes alone:

1. The independently verified, fixed whole-ELF SHA-256 above must match. An
   absent artifact pin refuses every positive plan. A
   non-helper opcode mutation is rejected even if geometry and helper bytes
   remain unchanged; geometry/inventory alone do not authenticate all code.
2. The existing conditional-layout inspector accepts this exact ELF and stock
   descriptor, including its all-object inventory and narrow LOAD geometry;
   the production verifier still rejects the layout.
3. The current pinned checkpoint contains that exact C source hash. Its
   archived helper object hash is checked again after reading its bytes.
4. The helper has no text relocations. Linked `.trial_stock_legacy_gate` bytes
   must equal the source-pinned input object's `.text` exactly.
5. The actual linked helper and original stock mode/length gate execute a
   finite **1078-vector** policy/ABI witness. All 256 opcodes are tested with
   modes 0/1/2/255, plus invalid full-width lengths and unreadable/null pointer
   early-rejection cases. The four retired opcodes cannot reach the named
   dispatcher boundary; other eligible opcodes preserve pointer and full
   length. Reads, stack stores, return, preserved registers and PRIMASK are
   independently bounded. These are internal vectors, not 1078 pytest tests.

Source/object identity and these finite software witnesses are not packet
lifetime, concurrency or whole-program proofs. The caller must still own an
immutable, readable packet for its entire delegated lifetime.

Helper object SHA-256:
`c50b394d7be6458cf50f6e1736723ff5f9fcb3ee43fb7a7e85c7bf566bdd3aaa`.
The 1078-vector policy witness digest is
`fe56f9ec1ad65ec833e7029018e18bbe84ae44e1659743203e0d11a4001ca159`.

## Preserved stock dependencies

Every loaded segment and retirement record is accounted for in the full-image
emulator delta check. All stock bytes outside those explicit intervals must
remain equal. The retained slices include:

- Raw mode getter `1e42..1e4a`, shared island `1f40..1f70`, neighboring startup/
  OTA code and callback pool `2348..23a4`.
- Shared indicator return tail `3ca8..3cac`, pool and neighboring no-op hooks/
  timer helpers `3de8..3e48`.
- Shared BF literal/string island `48e8..4910`, adjacent C0 entry, preceding
  negative-reply routine and following queue helper.
- Original receive gate `5c22..5c32`, separate DFU callback `79b6..7a0c`,
  DFU timer immediate `80f8..80fc`, and the boot overlay.
- Shared Health/raw reader `cc32..ccee` including tail `cca8`, restore tail
  `c7d2`, Health consumer, optical caller and algorithm-input frontend.

The raw-only return tail at `202a` is shared by the two retired raw functions,
not by the retained Health reader. It lies within the separately inspected
conditional raw-tail allowance; the planner does not add a stub there or claim
that its original bytes survive ELF placement. No raw-state RAM is reclaimed.

## Combined execution coverage and fixtures

`tests/test_stock_retirement.py` loads all conditional ELF segments and all
sixteen edits into the same fresh Unicorn address space as exact stock. It
admits only the linked legacy helper for execution among the relocated C
functions used by these probes. An old interior address does **not** become
allowed merely because it now falls in a relocated function. These tests are
not an integrated run of every C coordinator/source component.

The finite scenarios are:

- All fifteen direct entries under both PRIMASK states, seeded with dirty raw
  flags and existing raw/indicator handles: return zero without changing RAM,
  timers, messages, indicator requests or notification state. Existing handles
  deliberately remain. This does not simulate timer cancellation.
- Exact UART callback, linked early filter and original gate: four retired
  commands are rejected before the dispatcher/prelude boundary. Selected A0,
  9C and 51 commands still reach that named boundary. Wide invalid lengths use
  a deliberately unreadable pointer.
- Separate real DFU callback with the same bytes and modes: it reaches its
  named `823e` reassembly boundary without entering UART/filter code. Reassembly,
  programming, boot validation and recovery are **not** executed.
- Actual queued dispatcher `657c`: two seeded A1 04 queue entries across the
  index-9-to-0 wrap reach the stub through original call `6688`; only the normal
  read-index advancement is permitted. This is a seeded queue, not live RTOS
  scheduling or proof that all producers are drained.
- Original raw callback pointer at `239c` and indicator callback pointers at
  `3df0/3df8` reach their entry stubs. These are stored-pointer invocations, not
  execution of the timer daemon or recovery of already-running callback frames.
- Real fast-dispatch comparisons and direct calls `5bb6/5c14/5c1c` reach BF/CD/CE
  stubs. This direct-entry experiment explicitly substitutes the stateful
  `8112` prelude; it does not pretend late/direct admission avoided that prelude.
- Selected ordinary optical enable/disable and actual TX packaging, A0 getters
  and checksum, minute selection/settings, 9C stop/delete wrapper, charging
  flag-clear tail and idle raw-mode veto are compared against original stock.
- Original optical caller reads through shared `cc32`, FIFO wrap and Health
  consumer. The three selected input samples, scaled optical arrays and
  frontend magnitudes match stock. Downstream step/sleep/health algorithms and
  record persistence remain named fixtures, not physical continuity.

Bus, optical probe/start, mutex, timer queue, clocks, selected reset/bookkeeping
and downstream algorithm behavior retain the existing harness's explicit
fixtures. Matching stock data/BSS and recorded effects covers only the paths
and input states actually executed. It does not establish ordinary Health's
complete independence from the retired cluster.

Negative checks include old policy acceptance of A1, changed source/stock,
wrong entry bytes, split BL, overlap with shared data or relocated code,
unexpected old interiors (including ones inside new ELF functions), an
out-of-bounds entry-store mutant, and deleting the shared Health/raw reader.

## Unchanged limitations and release status

Global **indicator-pattern** retirement is a conditional research policy,
not approval to remove Health-mode functionality to make code fit. Indicator
patterns are distinct from Health's optical emitters: the retained optical
start path is still allowed to operate. These stubs do not themselves implement
the desired mode-dependent physical optical shutdown/resume.

The overlay assumes a fresh emulator: no old body is suspended on stack, no
return address points into reclaimed instructions, and no already-executing
callback resumes after the edit. Boot-only real admission, retention/reset
semantics, computed/ROM/patch/interior roots, concurrent queues and callbacks,
actual producer cancellation, physical STOP, current-settings fresh resume,
RAM/stack ownership and usable recovery remain unproved. An entry stub cannot
solve an already-running interior frame.

App identity/discovery must migrate away from the retired CD01 path. Dedicated
Gesture service/source integration must exist; there is no A1 fallback.
All approval fields remain false and approved reclaimed bytes remain **zero**.
See the finite six gates in [readiness](UNIFIED_READINESS.md), the separate
[raw audit](UNIFIED_RAW_RETIREMENT.md),
[diagnostic audit](UNIFIED_DIAGNOSTIC_RETIREMENT.md), and
[indicator audit](UNIFIED_INDICATOR_RETIREMENT.md).
