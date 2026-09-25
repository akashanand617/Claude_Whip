# Hypothetical scattered relocation — not approved stock space

2026-09-24. Entirely off-ring. This diagnostic does not construct an OTA image,
modify stock files, register a service, attach hooks, allocate ring RAM, or change
the installed V2 firmware. The unchanged production placement verifier rejects
every trial ELF. Health remains the intended unified boot/default.

## What the experiment answers

Can four *whole existing object text sections* fit inside the fragmented indicator
body candidates, while the append section contains all 16 current components and
the previously unlinked 196-byte Health-commit candidate? A second layout also
includes the new 240-byte service-data candidate (eight 28-byte attributes and a
16-byte service UUID). Neither layout contains the missing callback/coordinator,
source-observer, producer hooks, boot/retention binding or final container work.

The four objects are pinned to the verified 3004-test checkpoint. Current sources
are compiled with the same flags and must reproduce those complete object bytes:

| Object | File interval, end exclusive | Text bytes |
|---|---|---:|
| `stock_result_commit` | `0x3ac8..0x3b18` | 80 |
| `stock_schedule_settings` | `0x3b20..0x3b50` | 48 |
| `compiler_runtime` | `0x3b80..0x3c18` | 152 |
| `stock_binding` | `0x3c1c..0x3c9c` | 128 |
| Total hypothetical stock-body occupation | | **408** |

Execution addresses are these file offsets plus `0x825fb0`. All four object
sections require four-byte alignment. Entry stubs, the shared epilogue at
`0x3ca8..0x3cac`, literal pool `0x3de8..0x3dfc`, adjacent hooks/timers and all other
stock bytes remain outside the ELF's load intervals. No claim is made that the
overwritten bodies are unreachable in a real boot or retained callback.

`whip/fwrelocation_trial.py` generates a separate diagnostic linker script only
inside a new output directory. Each hole gets its own exact-length load segment;
segment padding cannot span retained stock bytes. Existing source/linker files,
compiler flags, unwind sections and the `0x84a000` APP bound are unchanged. All
118 function names in the pinned baseline ELF, plus `wsc_commit_health`, must
remain in the trial. The service variant adds data, not function removal.

## Measured layout

The first baseline trial links deterministically with **9160 append text/constants
bytes + 16 unwind bytes = 9176 occupied append bytes**, leaving **344** within the
configured 9520-byte append extent. Including the four scattered sections gives
**9584 allocated bytes** total. The Health-commit candidate is included.

The original append-only checkpoint had 96 linked unwind bytes. The diagnostic
linker coalesces them to 16 in the scattered layout; no unwind input was removed
and no stripping/GC/compiler flag was added. This is a measured link-layout effect,
**not proof of whole-stock unwinder integration or equivalent global unwind lookup**.
That needs its own exact image/runtime treatment before any production placement.

The service-inclusive attempt **fails the unchanged linker assertion**
`configured APP bound exceeded`, twice through the normal driver and again
through the same Zig executable's embedded LLD to obtain a failure map. **No ELF
is emitted for this variant.** Failure logs/map/objects are archived, not converted
into a successful-fit report. No bound, compiler option or unwind rule is relaxed.

The exact linker source explains the apparent inconsistency. LLD initially uses
eight bytes for each of the 18 input unwind sections (144 bytes), and evaluates
the assertion before merging them. The initial end is `0x84a018`: **24 bytes over
the bound**. The later failure map shows text/constants ending `0x849f88`, plus
16 merged unwind bytes, ending `0x849f98`: 104 bytes below the bound. The first
error is not undone by that later shrinking. This is a source-backed explanation
matching the actual object counts/map, not an instrumented linker trace or an
accepted ELF. See the exact installed Zig-bootstrap commit's
[initial estimate](https://github.com/ziglang/zig-bootstrap/blob/7ef74e656cf8ddbd6bf891a8475892aa1afa6891/lld/ELF/SyntheticSections.cpp#L3782-L3790),
[evaluation order](https://github.com/ziglang/zig-bootstrap/blob/7ef74e656cf8ddbd6bf891a8475892aa1afa6891/lld/ELF/Writer.cpp#L1376-L1391),
and [immediate assertion error](https://github.com/ziglang/zig-bootstrap/blob/7ef74e656cf8ddbd6bf891a8475892aa1afa6891/lld/ELF/ScriptParser.cpp#L833-L844).

Unknown remaining callback/coordinator/hook sizes are still not zero. Even the
failed map's 104-byte apparent remainder is not a complete integration budget.

## Integrity and executed scope

Inputs and tools are snapshotted before compilation, including the stock image,
descriptor, all component sources/headers, pinned objects, pinned baseline ELF,
and imported local validation dependencies. Object/linker outputs are snapshotted
before linking. The baseline links twice to identical ELF bytes; the service
variant reproduces the exact bound refusal twice without leaving an ELF.
Inputs and outputs are rechecked before each diagnostic report is written.
This is a diagnostic evidence report, not the main guarded-build success manifest.

The tests load exact function intervals derived from the trial ELF into an ARM
runner with bounded reads/writes, stack/callee-saved-register checks and canaries.
They execute relocated division, copy/overlap/clear, settings reads, STOP-report
construction and HR publication guards. Cross-region calls into current Health
ticket guards and boot initialization run as actual ARM. The refused service
variant is not executed; its data bytes and original registration ABI are checked
by the separate [service-table tests](UNIFIED_SERVICE_TABLE.md).

The STOP test substitutes **explicit mocks at original mutex and bus-write ABI
boundaries**. It does not execute the original bus-write body or prove physical
optical shutdown. Settings/RAM contents, tickets and bus statuses are synthetic.
Normal stock bodies outside the selected new code are not implicitly permitted
to execute. Preserved bytes are compared across the entire loaded stock image;
the ten indicator stubs exist in emulator memory only.

Negative cases include forbidden entry/shared-tail/pool placements, actual section
overlap, missing baseline function roots, wrong machine/entry, expanded load
segments, writable mappings and function pointers outside their declared section.
Production-verifier refusal is itself required; it is never bypassed or weakened.

## Remaining boundary

The stronger result is a concrete fragmented-space *layout option*, not a safe
firmware architecture. [Indicator retirement](UNIFIED_INDICATOR_RETIREMENT.md)
still lacks computed/indirect/ROM/patch/retained-reference closure, complete
cold-boot/retention proof and physical shutdown evidence. Approved reclaimed
stock space remains **zero**. The trial does not qualify flash geometry, recovery,
RAM/stack ownership, timing/completion/overflow provenance, Health continuity,
or dedicated-service registration capacity/identity/callbacks.

Use `build_trial(new_directory, reviewed_zig, include_service=False/True)` only
for this offline experiment. Outputs deliberately contain `unowned`, `trial` and
`NOT-INSTALLABLE` names. They must not be passed to an image builder or flasher.
