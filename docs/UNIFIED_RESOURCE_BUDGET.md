# Unified memory budget and daily-ring boundary

## New discovery read and startup composition — 2026-09-24/25

### UART multiplexing fit lead: 36 bytes is not production headroom

A new measurement-only architecture keeps the existing Colmi UART service for
both ordinary 16-byte Health traffic and versioned 20-byte unified frames. It
therefore omits the unattached replacement service, database, discovery
callback, slot adapter and event gate while preserving UART, DFU, DIS, HID and
all Health components. The candidate early hook recognizes only the existing
wire magic/version/request tuple at length20; ordinary traffic continues toward
the original gate. FEE7/WeChat alone remains the proposed retired feature.

Archive `firmware/unified/research-20260925-uart-mux-fit-lead-v1/`, report
SHA-256 `231cccf7a85e93a3a9d28b5177adbd5598e7682a61a81b8376d63ec05bcb143d`.
Two independent compiles/links are byte-identical. The link uses the exact
current objects except five sources rebuilt with function sections, a 92-byte
UART mux, the exact 48-byte UART notify-only wrapper, and fake six-byte
clock/ingress bindings. Selected current functions occupy 760 gross surveyed
FEE7 bytes. Append text is **9468**, linked unwind16 and total configured
occupancy **9484/9520: only 36 bytes left**.

`tests/test_uart_mux_experiment.py` adds a focused actual-ARM routing witness:
**34 passed in 3.14s**. It double-compiles/links the 92-byte mux, confirms the
production verifier rejects that artificial ELF, runs all 256 legacy opcodes
under three stock-mode values, routes only matching versioned 20-byte requests
to the fake unified sink, rejects malformed 20-byte variants, and confirms the
separate DFU callback never enters this hook. Original dispatch is still an
explicit boundary fixture; the fake sink does not supply owner identity or
transport lifetime.

This is the first structural fit lead, not a demonstrated fit. The linker is
explicitly measurement-only: the nine older holes are still unowned; complete
FEE7 reference retirement is not proved; the two-byte ingress stub does not
capture original connection generation or arrival time; the four-byte constant
clock is invalid; status-with-zero-boot discovery, app migration, callback/send
drain, placement, physical Health and recovery are absent. Thirty-six bytes
cannot be treated as enough for those real bindings. Accepted sources, objects
and release gates are unchanged.

### Subsequent whole-28 compiler trials: rejected

The current sources reproduce all **28 exact accepted/checkpoint objects**.
A new finite trial then tested two broader compiler ideas without changing those
sources or objects. Archive:
`firmware/unified/research-20260925-whole28-flags-rejected-v2/`; report SHA-256
`8cdcd42e778304624c48e809243c723314e8c53b0abfc197f365d1997d4b94e1`.
Root rechecked **538 content hashes** (92 inputs, 446 report-listed artifacts)
and three tools. Both compiler/link variants reproduce twice. The incomplete v1
run stopped before its report and is retained only as failed-run provenance.

`-fshort-enums` fails the reviewed owner ABI at compile time: `wco_owner` becomes
868 bytes rather than880. Disabling only the static assertions to measure the
idea reduces whole-28 input text by **72 bytes** (12404→12332), with rodata288
and input unwind1192 unchanged. It was not linked or behavior-tested and is
rejected; the saving cannot close the budget.

The second trial keeps the nine moved Apple-Clang objects byte-exact, retains
all **38 public functions with no reviewed in-set relocation caller**, and
internalizes/LTO-optimizes only append units using the different Zig/LLVM
frontend. An expanded measurement-only append region and artificial absolute
bindings make the non-fit measurable. The exact-object baseline occupies
**10844 bytes** (10828 text +16 linked unwind), **1324 over 9520**. LTO reduces
text by112, but linked unwind grows by456: total **11188**, **1668 over**, or
**344 bytes worse**. It is rejected. No unwind was discarded.

The artificial baseline already includes a 12-byte callback constant and tiny
fake clock/placeholder functions, but it does not implement write/CCCD, owned
RAM, physical hooks or recovery. Even granting all790 gross FEE7 bytes would
leave this measured baseline at least **534 bytes over** before those missing
real implementations. The experiment does not approve that reclamation or the
nine historical holes. The accepted whole-28 lower bound remains10798/9520;
this linked artificial measurement is a stricter non-fit witness, not a new
production layout. Do not retry short enums or this LTO/internalization setup as
untried shortcuts.

[Checkpoint](UNIFIED_WECHAT_RETIREMENT.md): 178 guarded tests pass. Actual
discovery-read callback adds 92 text / 8 input-unwind bytes and a 20-byte local
stack frame. Whole **28 objects / 149 functions / three constants**, input-only
append lower bound **10798/9520, 1278 over**. Six strong bindings are missing
(prior five plus `wdr_identity`); strict links emit no production ELF. Identity20
was already planned, so selected persistent subtotal stays 1244 + service ID1,
not 1265. Callback12 flash, final alignment/unwind and remaining code are extra.
Even all 790 surveyed FEE7 bytes hypothetically reclaimed leaves at least 500
bytes excess after callback12. Approved reclamation remains zero.
The below 27-object figures are historical; read callback remains unattached.

### Compiler-size review: no demonstrated fit shortcut

The prior `/tmp/whip-owner-lto.vFb7OT/direct-oz-assessment.json` already
measured all 25 earlier units with every public root retained: 72 text/constant
bytes saved, but the merged object violated existing whole-object placement
selectors. Keeping all nine moved objects byte-exact and optimizing all 16
append units together saved only 40 bytes. Both native baselines totalled
12216 text bytes. This was a different LLVM20 frontend contract; the original
Apple LLVM21 bitcode could not be consumed by that linker. Neither experiment
is an accepted build, a new result for all 28 units, or an approved fit.

For the reviewed ARMv6-M/Thumb1 target, forcing machine outlining is not a
credible shortcut: the target implementation explicitly rejects Thumb1
functions in both [LLVM20.1.8](https://raw.githubusercontent.com/llvm/llvm-project/llvmorg-20.1.8/llvm/lib/Target/ARM/ARMBaseInstrInfo.cpp)
and [LLVM21.1.0](https://raw.githubusercontent.com/llvm/llvm-project/llvmorg-21.1.0/llvm/lib/Target/ARM/ARMBaseInstrInfo.cpp).
This is source evidence about that optimization, not proof that every possible
compiler or source transformation has been exhausted.

### Bounded source-size experiments completed: all rejected

Archive `firmware/unified/research-20260925-source-size-rejected-v1/` retains
five candidate source copies, double-compiled objects/stack reports and exact
compiler commands. Report SHA-256:
`9906db7c9aefbd6c6e84ca9f052b9b6ebd47ede7c11f820846c236f0d5f0d421`.
The pinned compiler/flags were used throughout; accepted sources, all 28 input
objects and the nine conditional placements were not changed.

| Whole `fresh_source` module | Text | Input unwind | Total | Delta |
|---|---:|---:|---:|---:|
| Accepted baseline | 1004 | 56 | 1060 | — |
| Extract preflight (compiler inlined) | 1044 | 56 | 1100 | +40 |
| Extract preflight/frame (compiler inlined) | 1040 | 56 | 1096 | +36 |
| Force private helpers out of line | 998 | 72 | 1070 | +10 |
| Exact remainder test instead of second bucket division | 1004 | 56 | 1060 | 0 |
| Multiplication instead of FIFO-headroom division | 1044 | 56 | 1100 | +40 |

The outlined caller alone shrinks from 642 to 244 text bytes and local stack
112 to 72, but those numbers omit its new helpers. Caller+frame-helper local
stack is 128 rather than112; including the existing 28-byte division helper
gives a known static chain 156 rather than140. These are partial static chain
calculations, **not measured execution maxima or physical task headroom**.
The apparent six-byte text saving also adds16 input-unwind bytes. It is not
an accepted saving. Other variants retain the112-byte local observer frame.

The headroom algebra is equivalent for positive minimum periods; a corrupted
zero period is outside `ws_start`'s validated profile contract. Original C then
divides by zero (undefined); the pinned ARM helper happens to return0, whereas
the replacement faults. No arbitrary-corrupted-state equivalence is claimed.

All five candidates lost the size gate before behavioral qualification, so no
ARM differential, native behavioral regression or full-candidate relink is
claimed for them. Accepted baseline remains the178-test discovery/startup
checkpoint and3251-test main checkpoint, not a new test count. Whole28 lower
bound remains10798/9520, **1278 over**, before callback12 and other costs. This
closes the finite helper-split/remainder/headroom experiment; do not repeat it
or adopt one merely because its caller looks smaller. Broader compiler or
source transformations are not ruled out. No queue/timeout/evidence weakening
or invented free space is justified by the deficit.

### Alternate-sensor filename lead rejected

A subsequent bounded stock-code audit found **no defensible reclaim amount**
from the `lis3dh_spi.c` path at file `0xd2dc`. Its direct ADR user `0xd032`
is inside live hub wrapper `0xd024`; the normal branch at `0xd04e` calls the
existing Health/motion path `0xcab8`. It is not a private unused driver island.
Configuration `0xbfea` and FIFO `0xc280` dispatch on mutable sensor ID byte
`0x20bd98`, including STK `0x23` and other IDs. Boot/recovery probe `0xc16a`
tries address `0x19` before STK `0x1f`; wrappers share mutex `0x208c98` and
I2C core `0xdbca/0xdcce`. Removing the apparently alternate-address wrappers
would change stock probe/recovery even on the intended STK ring. Root verified
the filename reference and selected configuration/probe call edges directly.
This is a rejection of that shortcut, not complete indirect-reference closure
or proof that every alternative-specific branch is indispensable. No code,
calibration table, image, device state or approved memory budget changed.

## Latest unattached WeChat routing checkpoint — 2026-09-24/25

[Dual-root event gate and advertising slices](UNIFIED_WECHAT_RETIREMENT.md):
144 guarded tests pass. The gate adds 32 text / 8 input-unwind bytes and an
8-byte local stack frame; advertising's 13 fixed instruction replacements are
size-neutral. Whole **27 objects / 148 functions / three constants** now have
an append input-only lower bound **10706/9520, 1186 over**. The same five strong
bindings remain missing; no production ELF or final placement. Callback table
12 flash bytes and separate service ID 1 owned RAM byte are additional costs.
Persistent planning is therefore 1244 + 1, not an allocation. Gate has no
further state. Even all 790 surveyed FEE7 bytes hypothetically usable leaves
at least 408 excess after the callback constant, before alignment/unwind and
missing code. Approved reclamation is still zero. Low16 remains separate.
Previous subtotals below are historical; none establishes hardware fit.

## New unattached WeChat-slot integration — 2026-09-24/25

[Direct audit and compiled adapter](UNIFIED_WECHAT_RETIREMENT.md): 98 guarded
tests pass. The adapter is 64 text + 8 input-unwind bytes; local stack is16.
Including it with the accepted25 produces **26 objects / 147 functions /
3 constants**, lower bound **10674/9520**, **1154 over**. Its callback table12
and separately owned service ID1 are additional flash/RAM costs. Five strong
bindings remain unresolved; no full26 ELF. Low16 is still a separate experiment.
Gross FEE7 survey790 does not approve reclamation or solve the whole deficit;
setup/shared-ID mismatch and advertising cleanup remain explicit work.

## New experiment, not adopted: lossless queue timestamps

[Low16 timestamp experiment](UNIFIED_TIMESTAMP_STORAGE.md): 44 guarded tests
pass, preserving all 32 slots/live timestamps. Prospective persistent subtotal
1244→1180, but `wr_next` local stack24→32 needs nested review. Generated whole25
input lower bound10608/9520 still exceeds capacity by1088, and three physical
bindings remain missing. Accepted source/pins and the baseline below are
unchanged; runtime-only differential execution is not full low16 integration
or owned RAM. New hypothetical reclamation leads are not approved storage.

## Latest: actual control-owner composition — 2026-09-24/25

The [new owner checkpoint](UNIFIED_CONTROL_OWNER.md) includes all 25 objects,
146 functions and 3 constants. Real `wuw_supervise` now exists; strict links
refuse owned storage, stock-object bindings and a qualified clock. No production
ELF is emitted. New text is mailbox 564 + wait 72 + owner 744. The input-only
append lower bound is **10610/9520, at least 1090 over**, preserving the same
1894 unowned moved bytes and all unwind metadata. Remaining bindings/alignment/
veneers/final unwind are additional, not absorbed in this lower bound.

The 880-byte owner embeds dispatcher 764, mailbox 56, arrival 4, coordinator 28
and STOP record 28. Do not double count existing dispatcher/coordinator/STOP:
**1164 + identity 20 + mailbox 56 + arrival 4 = 1244 planning bytes**,
20 beyond the nominal unowned 1224-byte overlay/gap before remaining bindings.
The 32-byte event is stack scratch; the const stock binding costs 12 if in RAM.
Local step 88/service 40/supervise 8 frames are not nested stack/headroom.
Neither code-space nor RAM ownership is established.

Compiler-only `-Oz` LTO with the nine moved objects kept exact saves only 40
input bytes and still exceeds the allowance by at least 1050. It changes the
compiler/inventory contract and is not the accepted build or a fit solution.
The unchanged main regression passes 3251 again. The final separate supplement
passes **258 in 90.35 s**, zero skips/failures/errors, with 767 content hashes:
`firmware/unified/research-20260925-control-owner-v2/`. The linked checkpoint
records the exact scope, artificial bindings and all qualification boundaries.

## Preceding: mailbox and wait-hook batch — 2026-09-24/25

The [whole24 checkpoint](UNIFIED_OWNER_WAIT_BUDGET.md) adds unattached mailbox
and wait-wrapper code to all 22 prior pinned objects. It now has an append
**input-only lower bound of 9782/9520 bytes: at least 262 over**, before final
alignment/unwind and the missing real owner. Existing unowned moved text remains
1894 bytes. Strict links refuse the strong undefined `wuw_supervise`; no full24
ELF, extra hole, discarded unwind or installable image. The prior 264-byte margin
below is a historical subtotal, not current whole-code capacity.

New text: mailbox 480 bytes, wrapper 72. Mailbox state 32 plus separate event
scratch 32 have no allocation owner. Adding the state to the previous 1184 yields
**1216 persistent planning bytes**, not approved use of the nominal 1224-byte
overlay/gap. Local stack 8–24 and 16 respectively is not total nested stack.

Final archive `firmware/unified/research-20260925-owner-wait-v2/`: **131 guarded
tests passed in 41.44 s**, zero skips/failures/errors, 279 content hashes plus
three tools/launcher guarded. The earlier v1 contains the pre-hardening 125-case
result, superseded after two budget-checker edge fixes. Candidate ARM tests use
separate artificial ELFs and named ROM/body/supervisor fixtures, not full24
integrated switching or real deadlines. All six release gates remain open.

## Preceding: integrated retirement and read-only discovery — 2026-09-24/25

The [integrated retired-layout runner](UNIFIED_RETIRED_SWITCH.md) now executes
actual C Health→Gesture→Health orchestration, original Health sample paths and
known queued/stored legacy-root suppression in one persistent ARM context.
It uses the exact pinned 21-object ELF, sixteen retirement edits and two
reviewed sample-reader BLs. Physical/source/RTOS/steps/sleep remain fixtures.

[Discovery](UNIFIED_DISCOVERY.md) adds an unattached 20-byte identity format,
C encoder/borrowed view and pure Swift decoder. The complete simulator app
build passes without launch/deployment. New full **22-object/132-function**
archive: `firmware/unified/research-20260924-discovery-budget-v1/`.
Only discovery is newly double-compiled; the other 21 objects are exact pinned
inputs. Three links reproduce. Discovery is **122 text bytes**; full append is
**9240 + 16 = 9256/9520**, **264 remaining**, with unchanged **1894 unowned**
moved-text bytes. No new hole, APP expansion, unwind removal or source-policy
change. Encoder/read local stack is 24/0; immutable storage would add 20 bytes
to the unallocated 1164-byte selected planning case, yielding **1184**.

The separate guarded supplement passes **63 in 40.88 s**: 16 integrated switch,
19 cross-language discovery, 28 budget/actual-address cases. Root and independent
review checked **253 content hashes** (238 inputs, 12 artifacts, three reports),
four tools and launcher/SDK metadata; 63 ordered identities and 189 phases all
pass. The switch uses the old 21-object ELF; discovery runs separately in the
new 22-object ELF. The unchanged full 3251-suite was not rerun.

- New ELF: `932203212bae6fd1354030dadba21db3c388d575def6389891da56929fc26e66`.
- Budget report: `54aa06cb7608519ff14c8e865d82867699dd3256b6f1804ee59e624ee55e53e3`.
- Supplement: `4ec869f67ffe7e25be32152add9451c20c33e6ce389fbe4f7bde53c256180d3a`.

The budget's own 80 inputs/12 artifacts/three tools also match; all prior main
371 and retirement-supplement 277 content hashes remain unchanged. The new ELF
has no retirement stubs, actual GATT callback/owner or production hooks. All
construction/physical/ownership/admission flags stay false and production
rejects it. **Never install either conditional ELF.** No Codex device work.

The [stack evidence review](UNIFIED_STACK_EVIDENCE.md) independently replayed
Claude's 198/194/454-transaction archives, confirmed integrity/disconnects,
rebuilt unredacted TCB windows and checked known-A5 candidates against saved
hashes. Six task bases/names narrow future hook-to-task mapping. Allocation
headers and the seventh task remain unread; samples are non-atomic, and
paint is not SP-depth history, future reserve or Health workload qualification.
Neither the 192-byte app prefix nor a 244-byte candidate call alone establishes
fit or impossibility. No RAM/task ownership or stack gate closes.

The later [task map](UNIFIED_TASK_BINDINGS.md) puts selected Health scheduling
and consumption in qc_app, not the separate 1024-byte BLE app task. qc_app's
indefinite semaphore wait and blocking handlers do not provide a bounded
supervisor cadence. Explicit wake resources, cross-context handoff, identity
lookup and qualified boot-ID initialization are **additional unknown costs**,
not absorbed in the 264-byte conditional margin or 1184-byte planning object.
See [read ABI](UNIFIED_GATT_READ_BINDING.md) and
[boot source](UNIFIED_BOOT_ID_SOURCE.md). No source/object/build pin changed.

## Preceding: raw-ingress and combined known-root retirement — 2026-09-24/25

`build-20260924-raw-ingress-v1` passed **3251 guarded tests in 515.24 s**,
zero failures/errors/skips/xfails. Root and independent review checked **371
content hashes** (197 inputs, 171 artifacts, three reports), four tools and SDK
metadata, all ordered identities and 9753 passing phases. Main ELFs remain
identical to legacy-gate-v1. The unattached filter now denies A1 as well as
BF/CE/CD: **64 text / 8 input unwind / 8 local stack** bytes.
All current code in append alone attempts **11012 + 96 = 11108 bytes**,
**1588 over**, with no full ELF. Unknown remaining hooks are additional.

The new conditional archive is
`firmware/unified/research-20260924-raw-retirement-v1/`. All 21 object pins
recompile identically; all 130 functions and service constants remain. The
64-byte filter occupies `0x4c3c..0x4c7c`; all nine moved texts now total
**1894 bytes**. Append remains **9116 + 16 = 9132/9520**, **388 left**;
total allocation is **11026**. Ordinary/repeat/map links are byte-identical.
The 85 input/46 artifact hashes and tool hashes were rechecked.

[Combined retirement](UNIFIED_STOCK_RETIREMENT.md) adds a fixed, exact-ELF-pinned
**16-record emulator plan**, not a firmware writer. Fifteen stubs plus one BL
change 64 additional stock instruction bytes only in emulator memory. Selected
queued/direct/stored roots and ordinary Health/DFU paths execute together with
the full conditional layout; only the legacy helper among relocated functions
executes in these combined probes. This is not a complete switch or root-closure
proof. All original file bytes outside approved-for-test intervals remain equal.
The standalone ELF still has no entry stubs and must never be installed.

The separate guarded supplement passed **55 in 5.57 s**, zero skips/failures/
errors/xfails: 42 layout cases and 13 combined cases. All 165 phases and ordered
identities match. **277 content hashes** (228 inputs, 46 artifacts, three reports)
plus tools pass pre/post checks. Its 1078 internal policy vectors are not
separate pytest cases. The first developmental combined run exposed a test
oracle assuming a successful chip probe in the deliberate failure case;
unmodified stock failed too. The expected A0 byte/checksum was corrected,
without a firmware change, before this final guarded run.

SHA-256:

- Main manifest: `4ab65e86daeab7fee1d186c4fd873fe95fec7dd1dbb3040ba3ba5ee9d37d1cee`.
- Filter object: `c50b394d7be6458cf50f6e1736723ff5f9fcb3ee43fb7a7e85c7bf566bdd3aaa`.
- Conditional ELF: `9cad661e85edd74ebc9f425956aa1937da0dfa9f2f5344ddf20cf9d61109d432`.
- Conditional report: `f0fe65cbb83130c62f8384f92cc29eedc1a3ff84ae9d25ac3058ae9c21c23a7d`.
- Guarded supplement: `5d5c058abbe066ad662946450b986611dafa2d4a1b97f5ce50e2af925f304eac`.

Approved reclaimed space remains zero. All layout/integration/physical flags
remain false; the production verifier rejects the scattered ELF. No Codex ring
access, stock binary change, container/OTA generation, deployment, commit or
push. Health remains boot/default, Gesture opt-in. See the six
[release gates](UNIFIED_READINESS.md) and the
[ROM resume review](UNIFIED_ROM_RESUME_EVIDENCE.md). The historical counts and
source hashes below describe their own checkpoints, not current source identity.

At that earlier checkpoint the three stack archives were pending independent
review. That review is now complete as described above; its limitations remain.

## Earlier supplement: whole-code conditional placement — 2026-09-24

The [new research-only trial](UNIFIED_RAW_RELOCATION_TRIAL.md) links all **21
current objects, 130 functions** without changing component source, compiler
flags, queue capacity, APP end or retained unwind input. Nine whole texts occupy
**1886 bytes** in conditional raw/diagnostic/indicator regions; append is
**9116 text/constants + 16 linked unwind = 9132/9520**, leaving **388**. All
three ordinary/map links are byte-identical. This is actual conditional link
evidence; the append-only capacity refusal below remains correct.

These regions are **not owned**, their original entries are not retired, and
remaining hooks cost additional unknown space. Production rejects the ELF;
all nine approval/integration flags are false. It must not be treated as runnable
stock firmware. No stock binary is changed. A1 still passes the separate legacy
filter. Structural ELF inspection checks geometry/inventory, not every opcode;
pinned compilation, immediate snapshots and artifact hashes are separate duties.

Independent review found and closed a timing gap: each compiled object and
stack report is now snapshotted before pin comparison, not after all compiles.
An opcode-corruption test verifies rejection before linking. The final archive
is `firmware/unified/research-20260924-raw-relocation-v2/`; v1 is preserved as
historical evidence. The archive's **85 input, 46 artifact and three tool hashes**
were independently rechecked. Its ELF and layout match v1.

The separate [raw-entry experiment](UNIFIED_RAW_RETIREMENT_TESTS.md) compares
selected ordinary stock paths with only two four-byte stubs in emulator memory.
The shared optical reader, FIFO/Health front-end, scheduled selection, A0/9C,
bounded charging tail and idle walk preserve their exercised behavior. Hardware,
downstream step/aggregate, selected reset/bookkeeping and callback boundaries
remain explicit fixtures. No full Health, steps/sleep or retained-entry closure
is claimed, and no code body was erased by those tests.

Final **guarded supplemental run: 59 passed in 5.28 s**, zero failures/errors/
skips/xfails, comprising 42 placement and 17 raw-entry cases. Identical collection
and execution identities, all 177 phases, and JUnit agree. All **274 content
hashes** match (225 inputs, 46 artifacts, three reports), plus three tool hashes.
The earlier console runs overlap, not additional tests. This is **not a rerun
of the full 3212-test firmware checkpoint**, whose inputs/artifacts remain
unchanged. No main ELF, production source list or construction gate changed.

SHA-256:

- Research ELF: `0d86ddec5c56c28b4d34ab3517c7fea32894ab04d5239a4a3d2b3641f4ee012d`.
- V2 layout report: `a50c69b7d360306a183725af6e122402fa274d75a125bfada723f39546a6f5b4`.
- Guarded supplement: `da91ae46d68f8060a29b185ec2d1663c4e7a9f725cccdaf8c2e3a754ef8cc9aa`.

No release gate closes. Next integration work must retire the old roots, preserve
ordinary Health, implement app discovery and the remaining real hooks, then
re-budget them together. RAM ownership, physical source/pause/resume/continuity
and viable recovery remain separate evidence requirements. Codex stayed off-ring;
Claude's later device sessions are separate archives, not inferred successes here.

Subsequent independent review: Claude's completed/disconnected
`firmware/research/2026-09-24/ram-ownership-followup/` (274 reads),
`ram-ownership-resume-pointers/` (108) and `ram-ownership-resume-code/` (178),
each separately coordinated, now pass hash and bounded transcript reconstruction.
See [the ROM resume review](UNIFIED_ROM_RESUME_EVIDENCE.md). Captured ordinary
returns permit `0xd242 -> 0x4efc -> 0x4f12 -> first-boot`; excluding that path
requires unread context-restoration behavior, not merely its SDK symbol name.
Even the indirect restore-slot address depends on uncaptured literal `0xd478`.
Equal gap digests across 16605.56 seconds establish no observed net change, not
uninterrupted retention, observed DLPS, or absence of intervening writers.
The separate current RAM/reader suite passed 59 tests in 1.79 s, including fake
transport plans; that count is neither physical evidence nor part of the guarded
firmware checkpoint. Allocation and flash gates remain unchanged.

## Latest: early legacy filter and measured heap limit — 2026-09-24

`firmware/unified/build-20260924-legacy-gate-v1/` passed **3212 tests in
434.50 seconds**, zero failures/errors/skips/xfails. All **370 hashes** match:
196 inputs, 171 artifacts and three reports. Ordered collection/execution
identities agree. Both main ELFs are byte-identical to the coordinator checkpoint
below; its three candidates and the new filter remain absent from both.

The [56-byte legacy filter](UNIFIED_LEGACY_GATE.md) rejects BF/CE/CD before
the original stateful receive prelude. Its 69 focused tests run exact stock
UART callback/gate and separate DFU callback paths, not downstream Health or
completed DFU. No production hook is attached. A1 still passes. Existing app
CD01 identity probing must be replaced by dedicated unified discovery before
retiring CD on a deployed image; otherwise reconnect/identity failure also
prevents its return-to-stock battery preflight.

| Current measurement | Bytes / result |
|---|---:|
| Existing component text/constants + linked unwind | 9404 + 96 = **9500** |
| Configured margin, not approved expansion | **20** |
| Components + all four candidates, failed map | 11004 + 96 = **11100** |
| Actual final-region overflow | **1580**, no full ELF |
| Legacy filter object text / input unwind / local stack | **56 / 8 / 8** |
| Selected persistent state including receipt, coordinator and revision | **1164**, not allocated/owned |

Refusal logs/maps are now snapshotted immediately upon creation, before parsing,
then rechecked with the other artifacts. Flags, target CPU, queue capacities,
unwind retention, APP end and production placement checks are unchanged.
The whole-code budget still omits the remaining hardware/service/source hooks.

Two conditional retirement audits provide concrete next work: diagnostic code
has [476 aligned bytes](UNIFIED_DIAGNOSTIC_RETIREMENT.md), and the legacy raw
callback/handler has [1220 aligned bytes](UNIFIED_RAW_RETIREMENT.md), both after
entry-stub allowances. Raw's ordinary optical reader is shared Health code and
must remain, as must literal islands, timer slots and other external users.
Their combined 1696 bytes exceed this deficit by only 116 **arithmetically**;
fragmentation, placement, extra hooks and reference/retained-work closure remain
unresolved. Neither this arithmetic nor the older unowned 408-byte indicator
trial approves reclamation. Approved reclaimed space is still zero.

Claude's separately coordinated [device archive](../firmware/research/2026-09-24/ram-ownership/README.md)
completed 268 matching CD01 reads with verified disconnect. Root rechecked both
archive hashes and reran **39 RAM/reader tests in 1.41 s**, separate from the
3212 guarded cases. The installed V2 data heap showed **264 free bytes**, a
**104-byte minimum-ever**, and words consistent with an allocated-block header
at the configured heap start `0x20ec00` (header format remains an assumption).
Allocating the
1164-byte selected unified state from that measured heap is not viable. This
does not measure stock Health's peak or approve another heap. The 1060-byte
nonzero gap remained unchanged in one 60-second connected-idle window: no
observed writer is not ownership or boot/DLPS/DFU lifetime evidence.

SHA-256:

- Manifest: `cbfd74c0eb2218b5f2e6d5f10570b5dceb811a1c817087fd4c04bd6bf60e3467`.
- Legacy filter object: `08be187ce3fc5e80daa6cfec727544592716b72c0e1da9fec5ce8a9e83b544cc`.
- Full-candidate failed map: `525399d7e561d365cafd43dc14a0dbc240384b825fff7a697a094ce956577b92`.
- Each refusal log: `c87c41e7643fdaba142c106412c555797d7912fa4526262c2e884d56efceb46f`.
- Main ELF hashes are unchanged from the coordinator checkpoint below.

Codex made no ring connection, firmware-file change, OTA image, phone deployment,
commit or push. Claude has released the ring; further access needs fresh
coordination. Installed V2 is unchanged. All six release gates remain open.

## Prior: actual C coordinator and whole-code refusal — 2026-09-24

Entirely off-ring, coordinated with the active Claude Code session and parallel
implementation/review. The [new coordinator](UNIFIED_COORDINATOR.md) executes
one-shot checked STOP, original-token software retirement and atomic
current-settings Health commit. Quiet partial-entry resume now has an explicit
retirement predicate. It does not fabricate producer cancellation, queue fences,
physical STOP, fresh motion or scheduler receipts; those remain named fixtures.
Independent review found and fixed a returned-interrupt-mask failure path.

`firmware/unified/build-20260924-coordinator-v1/` passed **3143 tests in
454.34 seconds**, zero failures/errors/skips/xfails. All **365 hashes** independently
match: 193 inputs, 169 artifacts, three reports. Objects and both main links
reproduce. Focused runs overlap this count; Claude's separate RAM audit was
independently rerun here: **24 passed in 1.15 seconds**, not part of 3143.

| Current measurement | Bytes / result |
|---|---:|
| Existing component text/constants + linked unwind | 9404 + 96 = **9500** |
| Configured margin, not approved expansion | **20** |
| All components + commit + service + coordinator, failed map | 10948 + 96 = **11044** |
| Actual final-region overflow | **1524** |
| Coordinator object text / input unwind | **1106 / 72** |
| Selected persistent state including receipt, coordinator and revision | **1164**, not allocated/owned |

The builder archives two specific final-capacity refusals and their failed map;
no full-candidate ELF exists. Unknown remaining hook/communication costs are
additional, not zero. Health commit, service and coordinator are reproducible
**unlinked candidates**, absent from both main ELFs. The main ELF's component
margin is not a whole-image fit.

The exact APP region remains `0x847ad0..0x84a000`. Only the premature
pre-coalescing unwind-end assertion was removed; final region overflow checks
remain, and the mandatory ELF verifier now enforces tighter section/segment
geometry. Exact-boundary, overflow and malformed-ELF tests pass. This correction
does not enlarge storage or accept writable state. The separate unowned
relocation diagnostic intentionally retains its older strict script.

That diagnostic moves the same 408 bytes into unowned indicator holes. Its new
baseline, including Health commit and the quiet-resume predicate but **not the
coordinator**, occupies 9208 append bytes, leaving 312 configured bytes and
retaining 120 defined function names. Production still rejects it. Adding the
service still refuses under that diagnostic's provisional unwind assertion;
its failed map is not fit evidence. Approved reclaimed space remains zero.

Claude's [RAM audit/prototype](UNIFIED_RAM_OWNERSHIP.md) packs 1164 selected bytes
into the conditional 1224-byte overlay-plus-gap candidate, leaving 60. The resume
receipt already includes preparation; it is not counted twice. Vendor-guide
evidence supports APP/heap partitioning, not exact-ring startup/DLPS ownership.
The [code-space research](UNIFIED_CODE_SPACE.md) reports older-baseline size
experiments, not adopted optimizations or a current complete fit. The
[settings-writer inventory](UNIFIED_SETTINGS_WRITERS.md) identifies legacy BF
arbitrary writes and other bypass paths requiring retirement/gating before a
real revision owner can be trusted. These are not attached protections.

SHA-256:

- Manifest: `00a65e568e1c2900ca83a48a1ffee69adb11ecc1d1f75b0c52cfc8503601e61c`.
- Test ELF: `1672acb87bf298741410a5126f9b9f7ef079ca2181a0adfd719f3c2eac1f10aa`.
- Actual-address component ELF: `95a8a160a6f76878390f637a83156ffb5962056b949df2f8359e87b065556fa3`.
- Coordinator object: `9fad922bdeca22f5e724f815e2361f370f5270138594b6452b17834e6a5bc5ce`.
- Full-candidate failed map: `3ef247ae3952d0103b8d7a717a155b8ea967877666048c5fbc95a8a846c0ed2e`.
- Each refusal log: `b8937e3e5503b826892c10f874e94a81685e394216bc4b9d09a81b573f3240ad`.
- Unowned baseline ELF: `3aa417daeca73c48dd0385b15b60a236a0eab8d9dad75be8f7efa0aff3385ebf`.

No ring access, firmware-file change, OTA image, phone deployment, commit or push
was performed by this Codex batch. The user subsequently assigned live ring
testing to Claude Code; that separate session's results must be archived and
reviewed independently, not inferred from this off-ring checkpoint. Installed
V2 optical-off is unchanged by this batch. No release gate is fully closed.

## Prior: parallel service, relocation and RAM candidates — 2026-09-24

Coordinated with the active Claude Code session, entirely off-ring. The new
[service database](UNIFIED_SERVICE_TABLE.md) compiles to 240 read-only bytes;
it has no registration/callback implementation, approved UUID or writable state.
It and the 196-byte Health commit helper remain separately archived, **unlinked
from both main ELFs**. Existing component extent stays 9468/9520 configured
bytes. Adding these two candidates append-only needs at least 9904 bytes,
384 over capacity before other hooks/metadata. A shared RX read/write design
could save 56 database bytes, but is not implemented or ruled out.

The [relocation diagnostic](UNIFIED_RELOCATION_TRIAL.md) moves four unchanged
objects (408 bytes) into explicitly **unowned** indicator-code holes. With all
16 existing components and Health commit, it links reproducibly at 9176 append
bytes, 344 configured bytes remaining. It retains all 119 defined function
names and unwind metadata, and the production verifier rejects it. No stock
file is written; ROM/indirect/retained references are not closed. Approved
reclaimed space remains zero.

The service-inclusive diagnostic **fails the unchanged APP assertion twice**;
its map and refusal logs are archived, with no ELF. Exact LLD source explains
the provisional 144-byte unwind estimate: it temporarily exceeds the bound
by 24 bytes, before coalescing to the failed map's 16 bytes. The final map's
104-byte apparent margin is not a successful fit. The original 52-byte main
component margin likewise is final-layout arithmetic, not a guarantee that
another object can link. No assertion, region, compiler flag or production
verifier was weakened to force success.

Claude's [RAM audit](UNIFIED_RAM_OWNERSHIP.md) passes 15 tests independently
rerun here. It identifies an unapproved 1224-byte overlay/gap candidate, not
owned storage. Selected literal/reference scans cannot close dynamic/ROM roots,
DLPS/boot re-entry, heap, stack or patch ownership. Receipt/commit/revision
storage and alignment must be counted together; no NOLOAD region was added
to the production builder. Research prototypes are separate from this build.

Guarded `firmware/unified/build-20260924-layout-candidates-v1/` passed **3060
tests in 327.59 seconds**, zero failures/errors/skips/xfails. All **357 hashes**
independently match: 190 inputs, 164 artifacts, three reports. The two main ELFs
remain byte-identical to the preceding checkpoint. Focused service/relocation
tests are included in 3060; the 15 Claude RAM cases are separate, not silently
counted as guarded-build coverage. Both diagnostic archives retain their actual
success/refusal and false ownership/flash-approval flags.

Manifest SHA-256:
`ad5ad8705c40cd68e7dc1a9e4064c7a4001ab0ce9baeb824e44946d10cc36512`.
Unowned baseline ELF SHA-256:
`27b9415b21353dc315bba3f37f89f064163dd9f795765dba498138626532b8a2`.
Unlinked service object SHA-256:
`95d0f4514b47dd87964513a65b794e418439cec7c63be9b33dc39a2ecba9e0ff`.

The complete coordinator, physical bindings/continuity, memory ownership and
recovery remain unresolved. Installed V2 optical-off is unchanged; Health stays
unified boot/default, Gesture temporary/opt-in. No ring access, OTA generation,
stock-file change, app deployment, commit or push occurred. No release gate
closed. Claude's additional code-space research is not a result of this build.

## Prior: bounded delivery scratch and parallel integration — 2026-09-24

Entirely off-ring. The source selector's temporary delivery is **64 bytes**, down
from 208. All 32 raw input frames and the 32-sample persistent queue remain.
Within the unchanged <250 ms horizon, earliest acquisition endpoints span at
most eight 40 ms buckets: `floor((249 + 39) / 40) + 1 = 8`. This window-only
bound does not assume nominal cadence, exact timestamps, or consistent retained
progress. A local pre-write capacity check still rejects rather than truncates.

The tests compare native/current ARM against the pinned prior ARM, including
all window phases, clock wraps, nonzero uncertainty, healthy maximum batches,
an eight-output inconsistent-progress witness, native/ARM buffer canaries and
late transactional failures. The independent review found no blocking defect;
its suggestions to combine eight outputs with wrap/canaries were implemented.
Input provenance remains simulated, not physical source qualification.

| Measurement | Source-storage checkpoint | Current code |
|---|---:|---:|
| Full source receipt | 288 bytes | 288 bytes |
| Temporary source delivery | 208 bytes | 64 bytes |
| Observed integrated observation nested stack | 388 bytes | 244 bytes |
| Persistent dispatcher/frame/fence subtotal | 796 bytes | 796 bytes |
| Existing linked component extent | 9464 bytes | 9468 bytes |
| Configured remaining append bytes | 56 bytes | 52 bytes |

Receipt-on-stack planning is now **532 bytes** before the outer caller and
interrupts, not an approved 1024-byte task-stack fit. Separate persistent receipt
scratch still makes **1084 bytes**, 60 beyond the unapproved aligned RAM gap.
No physical RAM ownership or reclaimed stock space has been established.

The persistent integrated switch runner additionally sends both reply fragments
and packed motion through the actual stock notification wrapper, including its
shared return tail. ROM submission status, dedicated admission, buffer lifetime
and transport draining remain named fixtures. Refused sends, Health-default
preservation and late software receipts after reconnect are exercised. The
unsafe legacy UART queue is not reused or silently repaired.

The parallel [Health commit candidate](UNIFIED_HEALTH_COMMIT.md) closes the
software current-settings check-to-commit gap under one critical section. Its
196 text bytes **do not fit** with the existing components; the unchanged full
APP-bound link correctly refuses the addition. The candidate is archived and
tested separately, not included in the fitting subtotal or either main ELF.
Its immutable preparation/revision storage would add 20 bytes **if newly
allocated**, making an illustrative persistent subtotal of 1104 with the receipt;
neither lifetime/ownership nor a final allocation design is proved.

The stock-shaped six-entry service database alone would make current append
usage 9636 bytes, **116 beyond** configured capacity, before the candidate,
UUIDs, callbacks and remaining hooks. The complete architecture must solve
that combined budget; the helper's focused incomplete link is not a workaround.

Guarded `firmware/unified/build-20260924-parallel-integration-v1/` passed
**3004 tests in 218.01 seconds**, zero failures/errors/skips/xfails. All **265
source/artifact/report hashes** independently match: 180 inputs, 82 artifacts,
three reports. Both main ELFs and archived objects reproduce. The helper object
is explicitly marked unlinked in the manifest; symbol checks confirm it is
absent from both main ELFs. Focused/independent runs overlap these cases.

Manifest SHA-256:
`fae04b2e10e1ddc1b6a645db0cac72c43d5c98d274320b5a50c1bbd4cd02a040`.
Test ELF SHA-256:
`0b8101eb1603e9813c79d010b05fb20dbd6fabc42970e56983362d887c975a75`.
Actual-address component ELF SHA-256:
`f21fa753bf1e604a882183affe641219b67f989253d2dafbe3d02ede16e11ec2`.
Unlinked Health commit object SHA-256:
`a9d781b9257a905ff0f0a015bd7737f7471b76ba13822aa7ffc0cb932412dd7c`.
Existing components contain 9372 text/constants bytes and 96 linked unwind,
ending at `0x849fcc`. Selector local stack remains 112; adapter observation's
local frame drops 248→104 bytes. The observed nested path remains the correct
244-byte planning figure, not the sum of only these two local frames.

Source/compiler/linker bounds, unwind data and construction gates are unchanged.
The [vendor follow-up](UNIFIED_VENDOR_RECOVERY_LEADS.md) adds concrete family
references, not RT02CR-specific source or a demonstrated recovery route.

## Prior: lossless source receipt and progress storage — 2026-09-24

Source-level implementation, off-ring. Health remains boot/default and Gesture
temporary/opt-in. The 32-frame input capacity and 32-sample output queue are
unchanged; no sensor, stock bytes, production hooks or construction gates change.
The integrated runner still has explicit physical/coordinator fixtures.

| Measurement | Previous checkpoint | Current implementation |
|---|---:|---:|
| Full source receipt | 480 bytes | 288 bytes |
| Selector local frame (`ws_observe`) | 184 bytes | 112 bytes |
| Observed integrated `wa_observe` nested path | 460 bytes | 388 bytes |
| Persistent dispatcher/frame/fence subtotal | 796 bytes | 796 bytes |
| Actual-address component extent | 9480 bytes | 9464 bytes |
| Configured append margin | 40 bytes | 56 bytes |

These are compiled sizes/selected execution paths, not allocated ring memory.
Receipt-on-task-stack planning drops from 940 to **676 bytes** before outer
caller/interrupts. Persistent receipt scratch instead gives **1084 bytes**,
still 60 beyond the unapproved aligned 1024-byte gap. Complete hooks, scratch
lifetimes and stack/heap reserve remain unbudgeted. Even the six-entry service
table alone would take the component extent to **9632 bytes**, 112 over capacity
before callbacks, UUIDs or the other missing integrations. No reclaimed space
has been approved. See [the whole checklist](UNIFIED_READINESS.md).

### Exact representation, not lower precision

Every formerly accepted physical interval already lay less than 250 ms before
`status_at`: the former observer bounded its age at `now`, checked that status
was not future, and checked that the latest endpoint did not follow status.
The new receipt keeps each endpoint as an exact byte-sized age relative to the
final status timestamp. Two bytes replace eight per frame: **192 bytes saved**,
with all 192 raw data bytes and all 64 acquisition endpoints retained.
Unsigned subtraction reconstructs the original u32 timestamps across wrap.
There is no quantization, timestamp interpolation or change to 40 ms selection.

`ws_set_bounds` accepts u32 endpoints and validates before casting. Reversed,
future, too-old or out-of-range-index input poisons the receipt's transport
result; later valid encoding cannot clear an existing failure. The receiver
also checks the raw ages, so bypassing the encoder cannot make ages 250..255 or
reversed intervals acceptable. A compile-time guard prevents increasing the
horizon beyond this representation. `status_at` must be final before encoding;
the caller may not retime/reset/reuse the receipt across concurrent operations.
Zero bounds remain a claim, not physical evidence; the binding is still absent.

The transaction scratch now copies only a 16-byte `ws_progress`, not the full
92-byte source including its immutable 60-byte profile. All progress remains
uncommitted until the entire batch and counter checks pass. Failures clear the
caller-owned output and deactivate only the source; no partial batch escapes.
The source's ARM ABI remains 92 bytes. Full FIFO status equality against a
count bounded to 32 preserves overflow rejection without masking bit 7.
No I/O result, overflow rule, cadence/freshness test or queue capacity is dropped.

### Validation boundary

`tests/test_source_storage.py` runs current native C and ARM against the pinned
pre-change ARM test ELF, including streams with five cadences/three clock bases,
bad receipts, wrap/half-range boundaries, old sessions, empty batches, nulls,
exhausted counters and late failures after scratch has been written. The prior
ELF hash is checked in the test and included in the guarded build inputs.
Separate native cases exhaust all **65536 age pairs at each of two clock bases**
and all **65536 FIFO status/count pairs**, against independent predicates.
Checked-encoder canaries/sticky errors and native undefined-behavior stress also
run. None of these synthetic timestamps qualifies a physical profile.

Full guarded checkpoint `firmware/unified/build-20260924-source-storage-v1/`:
**2912 passed in 191.86 seconds**, zero failures/errors/skips/xfails. Both links
reproduce; all **260 recorded hashes** independently match (177 inputs,
80 artifacts, three reports). Focused final batch: **222 passed**, overlapping,
not additional tests. Manifest SHA-256:
`f6790c649e7213b60aaf2a59b10ea945eaa8b65ab9675161b2401117411e0b95`.
Test ELF SHA-256:
`42868008c8aa239a677e9e0dd081b00318aadfebd743758631220030731c9f75`.
Actual-address component ELF SHA-256:
`912d38929dce833da0828c6fe5cb47766819ab101f539a7fd15c2f00ab032c26`.
Its text/constants are 9368 bytes and unwind 96, ending at `0x849fc8`.
All construction/production/physical gates remain closed; no OTA image exists.
The source/adapter/integrated tests pass without changing compiler flags,
unwind metadata, linker script, fixed APP bounds or the final ELF verifier.
Additional linker fixtures reject payloads that fill/exceed the configured
margin while omitting their code/metadata overhead. Early drafts failed the
APP assertion despite an in-bounds final diagnostic map; a trial end-symbol
assertion did not resolve it and was reverted. No failed draft is a build pass.

Next bounded source-memory candidate: prove the maximum selected batch implied
by the unchanged <250 ms horizon and 40 ms buckets before shrinking delivery
scratch. That is separate from the 32-sample persistent output queue, which
must not be silently reduced. No delivery-size reduction is implemented here;
the witness still measures 208 bytes. This would still not allocate RAM or
resolve the missing coordinator/service/hooks or recovery.

## Prior: integrated switching and complete-budget constraints — 2026-09-24

Use [the finite readiness checklist](UNIFIED_READINESS.md). The new runner joins
command/reply and mode/lifecycle C with selected actual stock optical and motion
paths in one persistent ARM context. Its physical receipts, complete inventory,
fresh scheduler setup and real transport remain explicit fixtures, not approval.
It checks sample delivery to stock Health in eight transition phases, not the
downstream step/sleep algorithms or physical continuity.

`firmware/unified/build-20260924-integrated-switch-v1/`: **2883 passed in
179.35 seconds**, zero skips/failures/errors/xfails. All **258 hashes** matched:
175 inputs, 80 artifacts, three reports. The 15 new integration cases are
included; the focused 210-case run overlaps, not additional evidence counts.
Manifest SHA-256:
`6d6c8a5ee06f89f9c91231688362274913871a0d9e1e0087bf249492463f8119`.
Test ELF SHA-256:
`8bf55e59526a56c787b16d9d46a623dd8b9d72574d8a01fb6b6a898aeec8c267`.
Actual-address component ELF SHA-256:
`80cf2a1a48ad183c9f65044ce15375fc343c2fa5ae0b5e760d7f89f8cb8f04fa`.

Both links reproduce; **production components are byte-identical** to the I/O
checkpoint. Test-only ABI witnesses now record source receipt **480** and
delivery scratch **208** bytes in the manifest. Integrated successful observation
uses **460 observed nested stack bytes**, not just the older 440-byte local-frame
pair; the external receipt, outer stock caller and interrupts are excluded.
Delivery scratch is already included in that stack and must not be counted twice.

Code remains 9480/9520 configured bytes, only 40 remaining; persistent candidate
state remains 796 bytes. Mirroring the six-entry stock RX/TX service needs 168
database bytes alone: append-only subtotal 9648, **128 over capacity before all
other missing code/data**. Persistent receipt scratch would bring 796 to 1276
bytes, exceeding the unapproved aligned-gap idea before considering stack.
This is a whole-integration constraint, not a final image-size/ownership proof.
No source-profile/physical/STOP/resume/recovery gate, stock byte or hardware state
changed. No further ring access, app deployment, commit or push occurred.

## Prior: checked sample I/O integration — 2026-09-24

[Heap-free sample I/O](UNIFIED_OPTICAL_IO.md) executes compiled C through two
fixed replacement BLs in the original stock reader, in emulator memory only.
It retains bus/release failures and avoids the old allocating wrappers. No
stock file is modified and no complete firmware or physical receipt is produced.

`firmware/unified/build-20260924-optical-io-v1/`: **2868 passed in 183.28 s**,
zero skips/failures/errors/xfails. All **257 hashes** independently match:
174 inputs, 80 artifacts, three reports. Both ARM links reproduce identically.
Manifest SHA-256:
`f04a5dd7dab093f3c02cb375737583cc348637e09463298e1bea625ad164cc48`.
Test ELF SHA-256:
`76c3cdea54e70f7c54724fd93544e8fca43114bd9effd0c55eb102e82de7a252`.
Actual-address component ELF SHA-256:
`80cf2a1a48ad183c9f65044ce15375fc343c2fa5ae0b5e760d7f89f8cb8f04fa`.

Components occupy **9480/9520 configured bytes**, **40 remaining**:
9384 text/constants and 96 unwind bytes, ending at `0x849fd8`. Dispatcher,
frame and fence still total 796 bytes; none is approved RAM. The I/O helper adds
148 text bytes, offset by single-fragment reply encoding, moving the host-only
motion validator to test support and sharing existing checked logic. Net link
growth is 12 bytes. Production incoming-control checks, queues, unwind metadata
and compiler flags remain intact; no stock code is reclaimed.

Selected read nested stack is 336 observed bytes, excluding substituted ROM/
peripheral internals; dispatcher reply local frame is 32 (previously 72).
Neither is a full task/interrupt stack budget. Physical/source/lifetime/STOP,
resume, recovery and steps/sleep gates remain open. No hardware access occurred.
The next milestone is integrated switching and a **whole-image** budget, not
assuming the remaining hooks/service fit in these 40 bytes.

## Prior: optical work implementation and shared code — 2026-09-24

[Optical work lifetime and retirement](UNIFIED_OPTICAL_WORK.md) adds actual
unattached C: `wop_read` holds original acquisition work in flight through the
stock read, then rejects stale completion; `wop_retire` clears stock software
buffers/flags only after fully evidenced PAUSED. Neither creates measurement
provenance, flushes hardware FIFO nor completes the physical Health binding.

`firmware/unified/build-20260924-optical-work-v2/`: **2812 tests passed in
188.17 seconds**, zero skips/failures/errors/xfails. All **248 hashes** matched:
170 inputs, 75 artifacts, three reports. The 59 compiled-work cases, 15 original-
sample witnesses and four shared-codec alignment cases are included. The earlier
379-case focused run overlaps and predates the final added edge cases.
Manifest SHA-256:
`a9ce16455f17c1c0a55d2d6af22f21ec96ad1e2e1edf5ecb28c6528a1d4613e2`.
Test ELF SHA-256:
`a64a1b03f36cf11d597d9f65562086b34771ed096830d4379e4d08caa4b87d11`.
Actual-address component ELF SHA-256:
`2924d039b10cf142524ab446d072696c70da80ddaf3f856629b830371bad51ef`.

Both link layouts reproduce identically. New work-module text is 324 bytes;
sharing existing checked bodies and byte-wise wire helpers yields a net linked
increase of 116 bytes. Components occupy **9468/9520 configured bytes**,
**52 remaining**: 9372 text/constants and 96 unwind bytes, ending at `0x849fcc`.
No bound, queue capacity, predicate, unwind data or compiler flag was removed.
The initial `build-20260924-optical-work-fit-v1/` retained a failed APP-bound link
and has no success manifest; it is not a passing gate.

Dispatcher/frame/fence remains **796 bytes**, with 228 nominal aligned bytes
remaining. Read/retire observed nested stack peaks are **352/56 bytes**; the
selected retirement executes **5417 masked instruction boundaries**. These
exclude mocked internals and do not establish physical latency or task headroom.
Stock bytes, static RAM, installed V2 and all production/construction gates are
unchanged. Full integration fit, ownership/recovery, original producer/source
identity, physical STOP/freshness and steps/sleep continuity remain unproved.
Only 52 configured bytes remain before adding outstanding hooks/service/bindings.
No ring access occurred and no unified image is installable.

## Prior: optical acquisition/error propagation — 2026-09-24

The [optical acquisition audit](UNIFIED_OPTICAL_ACQUISITION.md) executes stock
status/metadata parsing, selected classification and mutex/RX wrappers formerly
substituted by fixtures. A top-level zero and parsed/read flags can survive
failed reads or occur without a read. They cannot supply the HR guard's measured
provenance. Completion's register operation is RX, correcting a former label.
No actual source/producer binding, physical observation or ring access follows.

`firmware/unified/build-20260924-optical-acquisition-v1/`: **2734 tests passed in
170.36 seconds**, zero skips/failures/errors/xfails; all **239 hashes** matched
(165 inputs, 71 artifacts, three reports). The 29 new cases are included, not
an additional gate; the focused 61-case run overlaps. Manifest SHA-256:
`2de14d67ced3621281a69c615f1db9bc04571328d712373b831e99fa5629503b`.
Both ARM ELFs match the HR-commit build below byte-for-byte. Components remain
**9352/9520 configured bytes**, **168 remaining**; dispatcher/frame/fence remains
**796 bytes**, with 228 nominal aligned RAM bytes remaining. No C, compiler
flags, stock bytes, RAM allocation or production/construction gates changed.
Full integration fit, ownership/recovery, producer/source identity and physical
tracking continuity remain unproved. The next sample-producing path is present
in the pinned image; its analysis needs no new device session.

## Prior: bounded HR result-commit implementation — 2026-09-24

The [HR commit guard](UNIFIED_HR_RESULT_COMMIT.md) implements an unattached
check-and-store critical section for exactly four stock positive-HR-result
stores. It requires the original work ticket and caller-proved provenance;
ordinary interrupts cannot split its permission check from those stores.
It preserves prior PRIMASK and adds no static RAM. This is not complete
producer/result coverage, installed stock hooks or physical pause/resume.

`firmware/unified/build-20260924-hr-commit-v1/`: **2705 tests passed in
166.52 seconds**, zero skips/failures/errors/xfails; all **237 hashes** matched
(163 inputs, 71 artifacts, three reports). Its 60 new actual-ARM cases include
stock-store equivalence, stale/invalid tickets, lifecycle rejection, modeled
pause arrival at all 64 instruction boundaries and two mask/restore mutants.
Manifest SHA-256:
`954c042ddf9f9ecca308c8fe8fc25f1c34bbe6751363d6bd7b61f9cc374bad07`.
Test ELF SHA-256:
`ff78dcb86c8affc11b52f5372c91404751c864119db61267ee6da72de50acf7f`.
Actual-address component ELF SHA-256:
`f848e492042d2498040d4281403bd914456faa57a47fc45deac891ebcd987ecd`.

Both ARM ELFs change because firmware C was added. Components now occupy
**9352/9520 configured bytes**, **168 remaining** (+80 bytes): 9264 text/constants
and 88 unwind bytes, ending at `0x849f58`. Both link layouts reproduce identically.
Dispatcher/frame/fence remains **796 bytes**, 228 nominal aligned RAM bytes
remaining; the guard's observed nested stack peak is 56 bytes. These are not
approved allocations, task headroom or complete integration fit. Stock bytes,
compiler flags, production/construction gates and installed V2 are unchanged.
`flashable`, `stock_linked`, `hardware_access`, `ram_ownership_verified` and
recovery approval remain false. No ring access occurred in this continuation.

## Prior: optical-event lifetime and result-commit evidence — 2026-09-24

The [new optical-dispatch audit](UNIFIED_OPTICAL_DISPATCH.md) adds 32 cases
covering the separate GPIO/software hub event and actual HR/SpO₂ cache stores.
Under synthetic cached-ready/algorithm fixtures, old work after STOP can
restore result state and reach later aggregation without a new enable. Entry-
only guards and assigning new tickets at dequeue have negative witnesses.
These are binding requirements, not physical observations or installed guards.

`firmware/unified/build-20260924-optical-dispatch-v2/`: **2645 tests passed in
162.99 seconds**, zero skips/failures/errors/xfails; all **230 hashes** matched
(160 inputs, 67 artifacts, three reports). Manifest SHA-256:
`ba6ba322e00ca6b4efd422668c53324a0ba8e00e89432194898f46c1cb41b9d1`.
Both ARM ELFs match the hook-execution build. Components remain **9272/9520
configured bytes**, 248 remaining; dispatcher/frame/fence remains **796 bytes**.
No C, flags, stock byte, allocation, device access or production gate changed.
Full integration fit, RAM/stack ownership, recovery and physical continuity
remain unproved. V1 was deliberately interrupted for fixture terminology
correction; it has no success manifest and is not a passing gate.

## Prior: captured hook and comparator execution — 2026-09-24

The [captured-body execution audit](UNIFIED_CREATE_HOOK_READ.md#captured-body-execution--2026-09-24)
adds 121 cases through the real RAM hook, ROM default/allocator and header
comparator. The selected success path creates an inactive timer; empty-handle
failure reaches unread `0x111a6`, not a proven safe return. Pool/list/critical
boundaries remain synthetic. APP/patch field checks are not boot/recovery.
No device access occurred in this continuation.

`firmware/unified/build-20260924-create-hook-execution-v1/`: **2613 tests passed
in 145.13 seconds**, zero skips/failures/errors/xfails; all **228 hashes** matched
(158 inputs, 67 artifacts, three reports). Manifest SHA-256:
`fb3d50e081a34bc82ca3541298a5b5b90683e3626469f8440489e6001469fed4`.
Both ARM ELFs match the capture build. Components remain **9272/9520 configured
bytes**, 248 remaining; dispatcher/frame/fence totals **796 bytes**. No C,
compiler flags, stock byte, RAM allocation or physical/production gate changed.
Complete integration fit and RAM/stack ownership remain unproved.

## Prior: create-hook capture and exact replay — 2026-09-24

A separately requested [create-hook read](UNIFIED_CREATE_HOOK_READ.md) completed
359 transactions, all repeated code/header and postchecks, and verified
disconnect. The earlier `0x73` abort remains historical. No sensor/flash command
or follow-up address read. The new code is available for off-ring execution
analysis; its header declarations do not establish memory ownership/recovery.

`firmware/unified/build-20260924-create-hook-capture-v1/`: **2492 tests passed
in 153.48 seconds**, zero skips/failures/errors/xfails; all **227 hashes** matched
(157 inputs, 67 artifacts, three reports). The added case replays the exact
archive. Manifest SHA-256:
`b3123dce765d24bc3fdf2a33f02a6aeb52c06a7f2ca143e355b39ed3a8c2a0b7`.
Both ARM ELFs are unchanged. Components remain 9272/9520 configured bytes,
248 remaining, combined state 796 bytes; no complete fit/ownership approval,
new firmware C, production binding or construction gate. Further ring access
needs new coordination; next work is the bounded OFF-RING code analysis.

## Prior: status-event evidence and redacted diagnostic metadata — 2026-09-23

The [status-notification audit](UNIFIED_STATUS_NOTIFICATIONS.md) executes three
packet constructors in stock/original25Hz/V2 and adds subtype/checksum metadata
without saving health values or accepting foreign packets. The old failed
archive still cannot identify its event. No device access occurred here.

`firmware/unified/build-20260923-status-metadata-v1/`: **2491 tests passed in
145.36 seconds**, zero skips/failures/errors/xfails; all **224 hashes** checked
(154 inputs, 67 artifacts, three reports). Manifest SHA-256:
`f074b21c1756c732e643852d8dcc80820538f8fd6448a190f5bad4c664186267`.
Both ARM ELFs match create-hook preflight v2. Components remain 9272 configured
bytes, 248 remaining; combined state 796 bytes. No firmware C/flags, stock byte,
allocation, fit/ownership approval or construction gate changed. Twenty separate
protocol/cleanup tests also pass. No new physical evidence or ring session.

## Prior: create-hook read preflight — 2026-09-23

The [bounded create-hook plan](UNIFIED_CREATE_HOOK_READ.md) was attempted on a
newly requested reconnect: 170 requests / 169 accepted replies, then unexpected
`0x73` traffic during prerequisites. Disconnect was verified; none of its new
windows was requested, and no success capture or automatic retry occurred.
The external SDK initializer writes a different create-hook address
from the ring's capture; no reference body was substituted for live code. The
new fixed plan permits 359 transactions for prerequisites, a 52-byte non-secret
header, two code caps totaling 384 bytes, and postchecks. No keys/pointer
following/execution/sensor/flash command, retry or continuing authorization.

`firmware/unified/build-20260923-create-hook-preflight-v2/` passed **2455 tests
in 157.65 seconds**, zero skips/failures/errors/xfails. All **222 hashes** verified:
152 inputs, 67 artifacts, three reports. Its 132 new cases are included. V1 is
the retained pre-correction build: the CLI byte summary is now derived and
includes the extra four-byte caller witness (1282 ROM bytes); actual read bounds
and the 359-transaction budget did not change. Manifest SHA-256:
`0ce73277782c43ad3eb0e34c4686bafbb49035867a297eba114d98f2489c9d41`.
Both ARM ELFs are byte-identical to the preceding build. No firmware C, flags,
stock bytes or allocation changed: 9272 configured code bytes, 248 remaining,
796 combined state bytes, no complete fit/ownership or production gate approval.

## Prior: captured support-code execution — 2026-09-23

The [support-code/state diagnostic](UNIFIED_SUPPORT_READ.md) subsequently
completed on a separately requested retry: 284 matching transactions, 616 new
ROM bytes and 17 fixed state bytes repeated, final checks and verified disconnect.
The earlier zero-command discovery failure is retained separately. No inspected
code was executed on the ring, returned pointer followed, or image/sensor
operation sent. New offline execution closes helper/context assumptions, but
the observed create-hook target `0x205c01` remains unread. Further device access
requires new exclusive-client coordination.

`firmware/unified/build-20260923-support-execution-v1/` passed **2323 tests in
163.21 seconds**, zero skips/failures/errors/xfails. All **219 hashes** checked:
149 inputs, 67 artifacts, three reports. All 60 added archive/execution cases
are included, not an extra count. The preceding 2263-test preflight remains
historical and was checked before connection. Current manifest SHA-256:
`88d44cd1317cd44f891b4b1f1739d9cd85e7549fb4f2d5907070e4263c2d0c2f`.
Both ARM ELFs match the preceding build byte-for-byte. Firmware C, stock bytes,
compiler flags and memory placement are unchanged: 9272 configured code bytes,
248 remaining, 796 bytes of dispatcher/frame/fence state, no approved ownership
or full integration fit. Construction/production and physical gates stay closed.

## Prior: captured creation/resume execution — 2026-09-23

[Captured timer execution](UNIFIED_TIMER_RESUME_READ.md) now includes the real
create/start/restart wrappers/defaults and native allocator/create instructions.
Native zero-period create consumes allocation state before asserting; valid
create replaces callback/ID but does not enqueue START. Wrapper conversion and
physical serialization still depend on unproved boundaries. No C component,
memory reservation or production rearm API was added; no device access occurred.

`firmware/unified/build-20260923-resume-execution-v1/` passed **2129 tests in
182.19 seconds**, zero skips/failures/errors/xfails. All **213 hashes** checked:
143 inputs, 67 artifacts and three reports. The 80 added cases comprise the
actual capture replay and 79 execution cases; the focused 184-test run overlaps
this count. Manifest SHA-256:
`0f9616dfb830164ecc51f8b3f8d02754c94868522bf134faf32f895e60300cb9`.
Both ARM ELFs match the preceding build byte-for-byte. Components remain
**9272/9520 configured bytes**, with 248 remaining and 796 bytes of dispatcher/
frame/fence state. No complete fit, RAM/stack ownership, recovery or physical
continuity approval follows; all construction gates remain closed.

## Prior: timer-resume prerequisites and read preflight — 2026-09-23

[Timer resume code/read plan](UNIFIED_TIMER_RESUME_READ.md) executes captured
kernel restart hazards. Its later, freshly coordinated 452-byte follow-up
completed 180 matching transactions, repeated equality/postchecks and verified
disconnect. The separate archive replay passes; it is outside the preceding
build manifest. No new firmware component, image, memory reservation or
production rearm API was added. The diagnostic session has ended.

`firmware/unified/build-20260923-resume-code-preflight-v1/` passed **2049 tests
in 160.49 seconds**, zero skips/failures/errors/xfails. All **209 hashes** checked:
139 inputs, 67 artifacts, three reports. Manifest SHA-256:
`d7f4b860a44a7fe7b9b6c8d4bd0a03eae3020d596a38707fdb37fcad256d5f27`.
Both ARM ELFs are byte-identical to the stock-settings build below: components
remain **9272/9520 configured bytes**, 248 remaining, with 796 bytes of dispatcher/
frame/fence state. Complete integration fit and RAM/stack/recovery remain unproved.
Installed V2 and every construction/physical-approval gate remain unchanged.

## Prior: exact-stock current-controls read — 2026-09-23

[Current settings and resume boundaries](UNIFIED_STOCK_SETTINGS.md) adds an
unattached four-byte snapshot primitive with bounded PRIMASK preservation.
No settings/history/clock writes, static RAM, heap or resume receipt. It adds
48 linked bytes: **9272/9520 configured bytes**, with **248 remaining**. Its
local ARM frame is eight bytes; dispatcher/frame/fence remains 796 bytes.
Full integration fit and all RAM/stack ownership/recovery gates remain open.

`firmware/unified/build-20260923-stock-settings-v1/` passed **1949 tests in
157.48 seconds**, zero skips/failures/errors/xfails. All **206 hashes** checked:
136 inputs, 67 artifacts, three reports. Manifest SHA-256:
`fd45710dc6dfff56dbb87e38e1fc7e92a8da925a987db8f1b357619437687c34`.
Actual-address ELF SHA-256:
`2c75d78867394ac4c9beb9ca18b3e4f5dca58c701884b64b92a65ac5720013e6`.
Append ends at `0x849f08` (9184 text/constants + 88 unwind bytes). Both compile/
link layouts reproduce identically. No stock bytes, linker bounds, compiler
flags, queue capacity, construction gates or physical ring state changed.

## Prior: entry-only indicator retirement experiment — 2026-09-23

[Indicator retirement](UNIFIED_INDICATOR_RETIREMENT.md) disables ten entry points
only in emulator memory. It prevents the tested late callback from requesting
LEDs and preserves selected Health starts/command replies. No production image,
physical STOP or reclaimed space follows. The 764 body bytes potentially reusable
are **not approved**; indirect references and full boot/retention remain open.

`firmware/unified/build-20260923-indicator-retirement-v1/` passed **1907 tests in
120.68 seconds**, zero skips/failures/errors/xfails. All **198 hashes** verified:
132 inputs, 63 artifacts and three reports. Manifest SHA-256:
`ad9dded12a4b27d127584f38bd8bb43266511974d8b13554b996d58b07446758`.
Both ARM ELF files are byte-identical to the preceding compacted build below.
Components remain 9224/9520 configured flash bytes; dispatcher/frame/fence remains
796 bytes. No memory allocation, construction gate, ring state or production
capability changed. This supersedes the current build count, not the compaction
measurements, hashes or safety limitations recorded below.

## Prior: lossless queue storage compaction — 2026-09-23

Entirely off-ring. This supersedes earlier component sizes below; it does not
approve RAM ownership, a complete integration fit or flashing. Installed V2
optical-off is unchanged. Unified Health remains boot/default and Gesture opt-in.

`sample_tap.c` now stores only the three signed axes per queued sample. It does
**not** reduce the 32-sample capacity, change the public `wt_sample` output,
alter wire packets, loosen freshness checks or replace physical timestamps.
Per-entry sequence numbers and alignment padding were redundant:

- A successful offer appends consecutive sequence numbers, rejecting exhaustion
  before any append. Sequence numbers never wrap within a session.
- A take removes only the oldest entry; stop/fault discards the entire backlog.
- Therefore the oldest sequence is exactly `sequence - count + 1`, with
  `count <= sequence`. Ring-buffer indices may wrap, but this subtraction does
  not underflow for an API-maintained live queue.

The existing single-owner serialization requirement remains. No concurrent
reader may observe a partially appended batch. No packed structs, unaligned
word accesses, new heap allocations, pointer lifetimes or stock RAM were added.

| Actual ARM quantity | Reviewed-timer build | Compacted build |
|---|---:|---:|
| 32-entry tap | 404 bytes | 212 bytes |
| Runtime | 600 bytes | 408 bytes |
| Health/source/runtime adapter | 864 bytes | 672 bytes |
| Dispatcher | 956 bytes | 764 bytes |
| Dispatcher + caller-owned frame + timer fence | 988 bytes | 796 bytes |
| Remainder against nominal aligned 1024-byte gap | 36 bytes | 228 bytes |
| Linked flash components | 9264 bytes | 9224 bytes |
| Remainder against configured 9520-byte append extent | 256 bytes | 296 bytes |

The RAM saving is **192 bytes**; linked flash also decreases by **40 bytes**.
`wt_offer` and `wt_take` local ARM frames remain 40 and 16 bytes respectively,
excluding their callees/interrupts. Existing application and ROM addresses,
linker boundaries, stock bytes, queue capacity and compiler flags are unchanged.
The 228/296-byte remainders are still arithmetic, not approved ownership or
proof that all missing hardware/service hooks fit.

### Verification

The permanent regression retains the pre-change FIFO algorithm/struct in
`tests/native/sample_tap_reference.c`, **test-only**, never in the stock-address
link. Actual ARM comparison checks return values, metadata, output sequences
and all axes against that reference and an independent Python deque. It covers
all 32 physical head positions with retained backlog/refill, maximum sequence
delivery and exhaustion, acquisition rollover, malformed/overflow/replayed
batches, old sessions, null output, stop/restart and 12 randomized interleavings.

A separate direct check ran the same **57 cases against the actual archived
pre-change ARM ELF**, not just the source reference. All matched. Baseline SHA:
`9c5598e7ef242176bbb20dbd5d645459e54fe6a9f0e52cc80f19b37c65eeb5da`;
new test ELF SHA:
`273789bf2b01cd9fc7a974be79cb4346e990231886c30af3befa7c5524113db3`.
This is additional comparison evidence, not 57 extra tests to add to the full
suite count. The archived baseline stays in the preceding local build directory;
permanent regression builds its checked-in C reference instead of depending on
an ignored build artifact.

Native ASan/UBSan retains the existing >3-million-sample/10,000-session stress
test and adds 100,000 interleaved operations against a shifting reference FIFO.
Existing stock-consumer observation, freshness, Health transition, dispatcher,
compiled Swift and captured-ROM cancellation tests remain in the full gate.
The ctypes layout and test-only field accessor were updated to the new internal
storage. The sequence-exhaustion fixture now queries an executed ARM offset
instead of using the former hard-coded 392-byte offset.

`firmware/unified/build-20260923-queue-compact-v1/` passed **1790 tests in
110.39 seconds**, zero skips/failures/errors/xfails. All **196 hashes** verified:
130 inputs, 63 artifacts, three proof reports. Both compile/link layouts
reproduce identically. The manifest also records executed tap/runtime sizes.

- Manifest: `1a5d0233941f73035b3ee6abab2ced8e5fbcfbe835c6a8920e7c6c481dd0b01e`.
- Actual-address ELF: `a246adceb10a0e43f8359912aad7179130206beacc79c150850df6ce1d5cf700`.
- Append ends at `0x849ed8`: 9136 text/constant bytes plus 88 unwind bytes.

No ring connection, phone deployment, new simulator/legacy-regression run,
commit or push. All construction/physical approval flags remain false. Real
health serialization/STOP/current-settings resume, full integration placement
and recovery, and physical source/model/steps/sleep validation remain required.

## Earlier memory investigation and daily-ring boundary

Later update: the user permits considering a specifically reviewed daily-ring
test if risk is reduced, and authorized diagnostics first. The subsequent
[fixed ROM-code diagnostic](UNIFIED_ROM_DIAGNOSTIC.md) completed without flash
or sensor commands. A spare is preferred, not an absolute requirement; this
change does not waive memory/recovery/physical gates or authorize a flash.

2026-09-23. Off-ring continuation after the stock transport audit. The user
confirmed **only the daily-use ring is available**, not a matching spare. No
ring connection, read, sensor command, phone deployment or flash occurred in
this continuation. Do not repeat the completed descriptor session or interpret
its old idle confirmation as authorization for new hardware work.

**No stock-linked unified image or approved allocation exists.** Health remains
the required unified boot/default; Gesture remains temporary and opt-in. The
installed V2 image is still optical-off and does not provide optical Health.

## Resource arithmetic is not a placement proof

The measurements below compare the reproducible offline builds
`build-20260923-transport-v1` and `build-20260923-memory-v1` under
`firmware/unified/`. Component numbers exclude test support. Artificial-address
ELF size is not an installable-image size and must not be used as one.

| Quantity | Transport build | Memory continuation | Limit on interpretation |
|---|---:|---:|---|
| Ten component `.text` sections, summed | 8242 bytes | 8252 bytes | Not a stock-linked extent; hooks, service database, helpers, alignment and veneers are missing |
| Ten component `.ARM.exidx` sections, summed | 808 bytes | 808 bytes | Relocatable input size, not final merged unwind-table size |
| All allocated component sections, summed | 9050 bytes | 9060 bytes | Neither a lower nor an upper bound on a future linked image |
| ARM dispatcher object, including adapter | 1016 bytes | 1016 bytes | Does not include actual transport/binding state or prove RAM ownership |
| Test fixture: dispatcher plus one 20-byte frame | 1036 bytes | 1036 bytes | Illustrative fixture, not a mandated production allocation |
| `ws_observe` local stack frame | 344 bytes | 184 bytes | Compiler local frame only |
| `wa_observe` local stack frame | 256 bytes | 256 bytes | Calls `ws_observe` while its frame is live |
| Those two nested frames together | 600 bytes | 440 bytes | Excludes their caller, other callees, exception/preemption overhead and stock task usage |

The captured APP/staging limits leave **9520 configured bytes** beyond the
complete stock image. Against component `.text` alone the new arithmetic
remainder is 1268 bytes; including all current relocatable allocated sections
gives 460 bytes. Neither remainder is available space: a real link can merge
sections and add helpers/veneers, and the missing bindings still need code/data.
Do not strip unwind metadata, reduce queue capacity or remove safety checks just
to make an unqualified sum fit. See [the placement audit](UNIFIED_PLACEMENT_GATE.md).

The nominal RAM gap is 1028 bytes, or 1024 after aligning its start to
`0x20e800`. A 1016-byte dispatcher would leave only eight bytes in the aligned
gap. The test fixture with one persistent frame already exceeds it by 12 bytes.
This does **not** establish that a production design is impossible or must use
that fixture: buffer lifetime/copy behavior is still unproved. It establishes
that “the controller fits in about 1 KiB” is not a sufficient memory plan.
No part of the gap is approved for use, and moving state onto the heap does not
prove future Health allocations remain safe. Stock/ROM/upper-stack indirect
writers, retention, initialization and task stack headroom remain unknown.

## Implemented stack reduction

`fresh_source.c` no longer creates a second 208-byte `ws_delivery` alongside
the caller's delivery buffer. It uses the exclusively owned output as scratch,
clears it on every rejection, and commits source progress only after the entire
batch validates. The compiler reduces the local frame by **160 bytes**, at a
cost of **10 extra `.text` bytes** in this toolchain. No global state, heap
allocation, source profile, sensor setting, protocol or queue size changed.

The API explicitly requires nonoverlapping source/receipt/output objects and
exclusive ownership of output until return. This is not an interrupt-safe
publication mechanism. Only `WS_DELIVER` permits publication; callers must not
observe partially filled scratch while the serialized call is running.

New regressions corrupt each of twelve acquisition bounds, including failures
after earlier samples have been decoded. Native direct tests cover both initial
and already-progressed source state, unchanged receipts, completely cleared
output fields and no committed source progress beyond fault deactivation. A
post-decode acquisition-counter exhaustion test checks the final failure edge.
Native and actual ARM adapter tests verify that late rejection neither completes
Gesture entry nor exposes a sample. A compiled ARM stack-report check caps this
local frame at 192 bytes; **that cap is not a ring-task headroom guarantee**.

## Recovery evidence is still missing

The archived stock `.bin` is an application OTA restore image, **not a complete
factory flash backup or proof of recovery when BLE/OTA no longer boots**.
The existing narrow descriptor capture gives ROM-patch, secure-boot and upper-
stack extents, not their implementations. A successful previous OTA transfer
does not establish interrupted-copy recovery or approve extending the image.

The public [upstream firmware manifest](https://raw.githubusercontent.com/Nosh118/colmi-ring-tools/main/site/public/firmware/manifest.json)
reviewed during this continuation lists RT02CR low-latency application firmware;
its entry labeled recovery targets RT02R/RT02R12 and explicitly assumes a ring
that still connects. It does not supply this ring's full factory package or
prove recovery after a nonbooting application. This is a finding about that
catalogue, not a claim that no manufacturer recovery method exists.

Useful external evidence would be the exact manufacturer's flash identity,
factory components, RAM ownership/link map and single-bank recovery procedure.
Physical source timing, STOP/resume and steps/sleep continuity still require
measurements, not more synthetic passing tests. A matching spare would also
need a validated independent recovery route before speculative instrumentation;
merely owning a second ring would not clear the gates. Do not order hardware,
open the daily ring, or flash it automatically to obtain that evidence.

## Build verification

`firmware/unified/build-20260923-memory-v1/` passed **986 tests, zero skips,
errors or failures**, in 103.43 seconds. All 120 source/artifact/report hashes
were rechecked: 88 inputs, 29 artifacts and three proof reports. The ten
components and four test-support objects were double-compiled identically;
the artificial-address ELF was double-linked identically. No source inputs
changed during the build.

- Manifest SHA-256: `f0b5484c09d0a611245c7a4ef5e7b597cebf621d3e18a93d945c00537805b1b5`
- Test ELF SHA-256: `8f87fd2133f9ff32dba43638b2bafd0c9e0488bcabd4b8a391c03652af505ee3`
- `flashable=false`, `stock_linked=false`, `hardware_access=false`.

Reproduce in a **new** output directory with the locked proof environment:

```sh
/tmp/whip-unified-build.m1E9lk/proof-env/bin/python -m probe.unified_build \
  --zig /tmp/whip-unified-build.m1E9lk/zig-aarch64-macos-0.15.2/zig \
  --output /tmp/whip-unified-memory-reproduction-new
```

The manifest's `objects` entries carry exact allocated-section sizes and local
stack reports. `RuntimeThumb` executing the test ELF's
`proof_dispatch_output_offset` returns the ARM dispatcher size (1016), while
`proof_dispatch_size` returns its fixture size (1036). These are executed ARM
`sizeof`/`offsetof` witnesses, not host pointer-size assumptions.

Construction, placement and production-capability gates remain closed. The
prior 58-test full simulator result is historical; no Swift changed and no
simulator was rerun here. The 194 separate legacy regressions from workflow 3
were not rerun in this continuation. The prior transport build remains intact
as a historical artifact, but its input hashes no longer match edited sources.
