# Whole-candidate raw/diagnostic/indicator relocation trial

## Current A1-denying layout — 2026-09-24/25

The builder now pins verified `build-20260924-raw-ingress-v1`, manifest
`4ab65e86daeab7fee1d186c4fd873fe95fec7dd1dbb3040ba3ba5ee9d37d1cee`.
New archive: `firmware/unified/research-20260924-raw-retirement-v1/`.
All 21 objects/130 functions remain; the legacy filter grew from 56 to 64
bytes and now denies A1/BF/CE/CD. Its whole text occupies `0x4c3c..0x4c7c`.
Total moved text is **1894** and total allocated bytes **11026**; append remains
**9132/9520**, **388 left**, with unchanged input unwind and compiler flags.
All three links reproduce; 85 inputs, 46 artifacts and tools recheck.

ELF SHA-256: `9cad661e85edd74ebc9f425956aa1937da0dfa9f2f5344ddf20cf9d61109d432`.
Report: `f0fe65cbb83130c62f8384f92cc29eedc1a3ff84ae9d25ac3058ae9c21c23a7d`.
The ELF alone still has no entry stubs and must never be installed. A separate
[exact-ELF-pinned emulator retirement plan](UNIFIED_STOCK_RETIREMENT.md) combines
16 fixed edits with this layout. The guarded 42-placement/13-combined supplement
passed **55 in 5.57 s**; its 277 content hashes and tool hashes agree.
Supplement: `5d5c058abbe066ad662946450b986611dafa2d4a1b97f5ce50e2af925f304eac`.
All approval flags remain false. This supersedes current figures below;
the older archives/hashes remain historical, not overwritten.

## Historical BF/CE/CD-only layout

2026-09-24. Off-ring research only. This is a successful **conditional layout**,
not an executable replacement firmware: the stock entry paths have not been
retired, no hooks are attached, and none of the scattered regions is owned.
No stock file, container, OTA output, production verifier, compiler flag, queue,
component source or prior frozen checkpoint was changed. No device access.

## Actual result

All **16 current SOURCES + four UNLINKED_CANDIDATES + compiler_runtime** link
together in the unchanged APP bound, with nine unchanged whole object texts
placed in the conditional regions below. No function splitting, LTO, garbage
collection, queue reduction, guard removal or unwind discard was introduced.

| Measured ELF allocation | Bytes |
|---|---:|
| Nine whole texts in hypothetical stock regions | 1886 |
| Append text and constants | 9116 |
| Final linked append unwind | 16 |
| Append occupancy / unchanged capacity | **9132 / 9520** |
| Configured append margin | **388** |
| Total allocated bytes across all regions | **11018** |

Append starts at `0x847ad0`; `.text` ends at `0x849e6c`; unwind ends at
`0x849e7c`, below the unchanged `0x84a000` APP end. Two ordinary links and a
third map-producing link yield **byte-identical ELFs**. These are successful
link results, not arithmetic inferred from a failed map.

The current stock linker uses final MEMORY-region enforcement after LLD unwind
coalescing. The new diagnostic uses that same fixed APP capacity and its own
strict final geometry checks; it does not copy the older indicator trial's
premature pre-coalescing assertion or modify that older trial. All **1040 bytes
of input unwind sections** are supplied unchanged. LLD coalesces them to 16
output bytes. This measures ordinary linker behavior; it does not establish
global stock unwinder registration or runtime unwind correctness.

## Exact conditional placement

File ranges below have exclusive ends. Add stock XIP bias `0x825fb0` for their
runtime addresses. Every moved text receives its own exact, read/execute
PT_LOAD; unused hole tails and all intervening stock bytes are **not loaded**.

| Whole object `.text` | Actual file interval | Bytes |
|---|---|---:|
| `stock_health_commit` | `0x1e50..0x1f14` | 196 |
| `stock_timer_fence` | `0x1f70..0x20f6` | 390 |
| `mode_controller` | `0x2108..0x2328` | 544 |
| `stock_result_commit` | `0x3ac8..0x3b18` | 80 |
| `stock_schedule_settings` | `0x3b20..0x3b50` | 48 |
| `compiler_runtime` | `0x3b80..0x3c18` | 152 |
| `stock_binding` | `0x3c1c..0x3c9c` | 128 |
| `stock_health_timers` | `0x4b08..0x4c2c` | 292 |
| `stock_legacy_gate` | `0x4c3c..0x4c74` | 56 |

Only the regions already enumerated in [raw retirement](UNIFIED_RAW_RETIREMENT.md),
[diagnostic retirement](UNIFIED_DIAGNOSTIC_RETIREMENT.md) and the four existing
[indicator placements](UNIFIED_RELOCATION_TRIAL.md) are considered. The two
small BF fragments remain unused. Of 2104 conditional planning bytes, 218
remain unused/fragmented; that is not another approved allocation.

The 48-byte `stock_health_timers` **rodata remains in append**, separate from
its relocated 292-byte text. The complete 240-byte service UUID/database also
remains in append. Its single input `R_ARM_ABS32` at rodata offset 36 must point
to the actual linked `wgd_service_uuid`; every other service byte must match
the pinned object. No discovery/table entries were removed.

## Provenance and preservation

Pinned source checkpoint: `build-20260924-legacy-gate-v1`, manifest SHA-256
`cbfd74c0eb2218b5f2e6d5f10570b5dceb811a1c817087fd4c04bd6bf60e3467`.
All 21 units are freshly compiled using its exact Cortex-M0+/Armv6-M flags;
every object must equal its pinned checkpoint object byte for byte. All **130
functions** and constant-symbol identities/sizes/bindings/multiplicities must
survive the final link, including compiler support and all four candidates.
No proof entry or mock function is linked into the diagnostic.

The builder snapshots exact stock, captured bank descriptor, current sources,
pinned objects/manifest, imported local validators, new module/tests, tool
executables and retirement documents before compilation. It snapshots each
object and stack report immediately after that compile, before pin comparison,
and verifies the initial snapshots before interpreting/linking the complete
object set. It similarly snapshots outputs immediately after each link, before
comparison/interpretation, and verifies all initial snapshots before writing
its report. This detects persistent content drift;
it is not a hermetic toolchain or a filesystem lock.

Archive: [`firmware/unified/research-20260924-raw-relocation-v2/`](../firmware/unified/research-20260924-raw-relocation-v2/).
The directory was newly created, not overwritten. It contains the objects,
stack reports, narrow linker script, three identical noninstallable ELFs,
actual linker map and separate diagnostic report (85 input, 46 artifact and
three tool hashes). The report has `tests_run=false`: the builder does not run
pytest and must not claim the separate tests below as an internal build gate.
The earlier research-v1 directory remains untouched and historical. Independent
review found that its object snapshots were deferred until all units compiled;
v2 closes that timing gap. The ELF and layout remain byte-identical. A negative
test now changes an earlier object's opcode after a later compilation, without
changing ELF names/geometry, and requires rejection before any link or report.

SHA-256 anchors:

```text
ELF      0d86ddec5c56c28b4d34ab3517c7fea32894ab04d5239a4a3d2b3641f4ee012d
report   a50c69b7d360306a183725af6e122402fa274d75a125bfada723f39546a6f5b4
map      6c20ec2a26b0eee7879b406b3ba22a43516f0271c830fe704a1e65b8dbddc148
script   ccff4c2fe8b8be08f721813461a212e14d9d71810cc41c5034d17f9e1f2eff92
module   5bad6ebeeafb23b30f69a10c2351e33dd35e5e34274dcddbdb66e0cc123596fa
tests    95afc20e281b46e85f3b004a11ce12a0d45feeb31eba7a108b0f927a8430b170
```

## Executed checks and limits

The parent reran the final V2 sources: **42 relocation + 17 raw-retirement
tests = 59 passed in 4.91 s**. A subsequent guarded supplement passed **59 in
5.28 s**, zero failures/errors/skips/xfails, with matching ordered collection,
execution and JUnit and all 177 phases passing. Its `proof-supplement.json`
records 225 input, 46 artifact, three report and three tool hashes, verified
before/after execution and rechecked afterward. Canonical reports are
`proof-collected.json`, `proof-executed.json`, `proof-tests.xml`; the earlier
`collected.json` is a separate preliminary collection, not the canonical run.
Supplement SHA-256:
`da91ae46d68f8060a29b185ec2d1663c4e7a9f725cccdaf8c2e3a754ef8cc9aa`.
This is a **separate research supplement**, not a full 3212-test firmware-suite
rerun or an amendment of the earlier guarded build. Prior 58-test console and
three-test selected runs overlap and are not counted again.
An earlier sandboxed run terminated in Unicorn host-JIT initialization before
ARM execution; that SIGILL is not counted as a pass or a firmware failure.

The relocation tests check exact allocated sections/LOADs, forbidden entries,
pools and neighbors, unchanged stock file and emulator bytes outside ELF
overlays, all-object identities, missing/extra function rejection, service-byte
mutation, unwind mapping and required production rejection. Selected actual
relocated ARM executes with stack/callee-save/canary and bounded memory guards:
controller completion/disconnect/timeout including clock wrap, compiler divide,
checked STOP and cross-region default-Health initialization. Relevant results
match the pinned append-address baseline ARM. STOP's bus/ROM calls are explicit
fixtures, not execution of the physical bus body or a physical STOP receipt.

The relocated legacy filter executes with the actual original stock gate;
ordinary dispatcher entry is an explicit fixture. The sole gate literal read
allowed outside ELF/context memory is the checked four-byte word at
file `0x601c` / runtime `0x82bfcc`, equal to mode pointer `0x208c44`.
The filter still forwards A1; tests preserve that current behavior rather than
inventing raw retirement. No original raw entry stubs are installed even in
this relocation emulator. Entering an unadmitted original body is rejected.

The unchanged production verifier rejects this ELF with
`unexpected/writable allocated section` (the unexpected scattered sections;
the trial's LOADs are not writable). Every ownership, reference-closure,
attachment, retirement, recovery, physical-continuity and flashable flag stays
**false**. Approved reclaimed space remains **zero**.

The inspector validates geometry and inventory, not each machine instruction.
Independent review confirmed that changing an instruction without changing
symbols/geometry can pass that structural checker alone. Pinned compile equality
and early artifact snapshots/hashes are therefore essential, and selected ARM
execution must not be generalized to every function or a full stock boot.

Before these bytes could be used, actual raw/diagnostic/indicator retirement
must close all traffic, queued, callback, retained and indirect roots and
preserve ordinary Health/steps/sleep. Entry allowances alone do not do this.
The original A1 entry still has instructions that would flow into overwritten
bodies, so this layout must never be treated as runnable stock firmware.
Discovery migration, real source and physical transition receipts, coordinator
attachment, settings ownership, RAM/stack lifetimes, recovery and full ordinary
Health continuity remain separate gates. The 388-byte margin is for this
implemented candidate only: unknown missing hook/retirement costs are not zero.
