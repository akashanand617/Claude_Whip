# Unified code space: measured whole-image plan, not a fit

> **Current-scope note, 2026-09-24, later the same day (added at Codex's
> request).** This report is a historical baseline measured against
> `parallel-integration-v1`. Since then, root has removed only the premature
> pre-coalescing APP `ASSERT`, kept the exact `MEMORY` 9520 bound, and
> strengthened the final verifier (boundary ±1/+4 proved). The current core
> also includes a 34-byte quiet-resume predicate. The unlinked coordinator
> adds 1106 text bytes. All current implemented candidates together fail the
> final region by **1524 bytes** (11044 total; `build-20260924-coordinator-v1`),
> so the positive-room arithmetic below is **superseded/incomplete** without the
> coordinator. The test baseline here was **909 passed / 2 failed**: the two
> failures were expected mismatches with in-progress source, not a passing
> qualification of any variant.


2026-09-24. Entirely off-ring. No ring/BLE access, flash, stock-file change,
commit or push. This file is the only repository change. All prototypes live in
scratch (`$SCRATCH` below, the session scratchpad `…/scratchpad/codespace/`).
No source, test, build script, linker script or verifier was changed. **No
gate opens.** Approved reclaimed stock space remains **zero**.

## Bottom line

- **Append-only cannot close the integration budget.** The best measured
  append-only build uses 9240 bytes before additions. Adding the Health commit
  helper (196) and the eight-row service data (240) gives **9676, which is
  156 over**, before any callback, pump, owner, hook or resume code.
- **The configured 52-byte margin is not usable.** The unchanged `ASSERT`
  sees about 8 unwind bytes per input section before lld merges them.
  Baseline headroom under that assertion is **12 bytes**.
- **Two build-level reductions are real and measured:**
  - Link order: −80 final unwind bytes.
  - Link order plus a single-translation-unit build: −116 total. This one also
    makes the margin usable under the *unchanged* script.
- **Two runtime-helper substitutions are measured:**
  - The stock image's own divide helper: −72.
  - ROM `memcpy`/`memclr4`: −34. Their ROM bytes were never read.
- **Micro-trimming stays small.** wire/dispatch gives −14 source bytes. This
  agrees with Codex's audit, which found at most 306 bytes from trimming.
- **The only measured path with positive room needs all of these:**
  - Unapproved indicator reclaim (Codex's relocation trial).
  - The single-TU build.
  - The helper substitution.
  - Per-function placement of glue code into leftover holes.
- Even then, about 36–228 bytes remain for all still-unknown work: producer,
  start and result hooks, fresh-job resume, the motion observer, clock and
  connection bindings, and trampolines. That is not evidence of a fit.

## Method and reproduction

Toolchain matches the checkpoint:
- Clang `/usr/bin/clang`, SHA-256 `b8763cf2…f610e9`.
- Zig 0.15.2, `c65cd349…dcdf351c`.
- Flags and link command order are exactly those of `probe/stock_link.py`.
- Link order is the `SOURCES` order plus `compiler_runtime`.

Baseline reproduction:
- The scratch rebuild reproduces **both** checkpoint ELFs byte for byte:
  component ELF `f21fa753…ec2` and test ELF `0b8101eb…a75`.
- The main ELFs of `build-20260924-layout-candidates-v1/` are identical to
  these, so every number below applies to both checkpoints.
- The working-tree `health_adapter.c` changed after that build. Its baseline
  object is rebuilt from a reconstructed source that compiles to the archived
  object byte for byte.

Test runs:
- Tests that load ELFs ran from a frozen copy of the repository tree taken at
  12:21. Environment: `WHIP_UNIFIED_TEST_ELF` and `WHIP_STOCK_LINK_ELF`.
- 15 modules ran: `test_unified_thumb`, `fwstock_link`, `fwrom_fence`,
  `fwtransport`, `source_storage`, `stock_health_timers`,
  `stock_schedule_settings`, `stock_optical_io`, `stock_result_commit`,
  `unified_dispatch`, `stock_switch`, `stock_optical_work`, `tap_storage`,
  `unified_wire` and `unified_adapter`.
- The unchanged baseline gives **909 passed, 2 failed**. The 2 failures are
  new `test_quiet_resume_can_retire_before_fresh_preparation…` cases that
  expect an in-progress source change.
- Every variant below gives the **identical pass/fail set**.
- Native/sanitizer tests compile repository sources, so they do not cover
  scratch variants.

## The bound is checked on a provisional layout

`ASSERT(ADDR(.ARM.exidx)+SIZEOF(.ARM.exidx) <= 0x84a000)` is evaluated before
lld merges unwind entries. Filler objects of 4–168 bytes confirm this model:

`usable = 9520 − text − 8 × (number of input .ARM.exidx sections)`

- The final merged table is: every entry of the **first** executable input
  section, plus later sections that are not all-CANTUNWIND duplicates, plus one
  8-byte sentinel.
- Every component is all-CANTUNWIND. `mode_controller.o` comes first and has
  11 functions, so the final table is 96 bytes.
- 17 objects give 136 provisional bytes. Only 12 bytes are usable, not 52.
- Moving the four-byte-aligned bound check into a symbol or a SECTIONS
  statement behaves the same way. Only the MEMORY-region overflow and the
  post-link ELF verifier see the final layout.
- Codex's relocation trial fails the same way: 144 provisional bytes, a
  24-byte transient overflow.

## Inventory of the 9372 text/constant bytes

| Object | Text | Rodata | Functions | Literal words | Align nops |
|---|---:|---:|---:|---:|---:|
| adapter | 1782 | 0 | 24 | 0 | 0 |
| dispatch | 1202 | 0 | 10 | 16 B | 3 |
| fresh_source | 1004 | 0 | 7 | 4 B | 1 |
| health_adapter | 1002 | 0 | 19 | 0 | 0 |
| wire | 972 | 0 | 10 | 8 B | 1 |
| runtime | 752 | 0 | 10 | 0 | 0 |
| mode_controller | 544 | 0 | 11 | 16 B | 1 |
| stock_timer_fence | 390 | 0 | 5 | 12 B | 0 |
| stock_optical_work | 324 | 0 | 3 | 12 B | 3 |
| sample_tap | 318 | 0 | 5 | 0 | 0 |
| stock_health_timers | 292 | 48 | 3 | 16 B | 0 |
| stock_transport | 176 | 0 | 2 | 12 B | 0 |
| compiler_runtime | 152 | 0 | 5 | 0 | 0 |
| stock_optical_io | 148 | 0 | 1 | 12 B | 0 |
| stock_binding | 128 | 0 | 1 | 16 B | 0 |
| stock_result_commit | 80 | 0 | 1 | 4 B | 1 |
| stock_schedule_settings | 48 | 0 | 1 | 8 B | 1 |

- Object sum is 9362, plus 10 bytes of padding between objects.
- Padding inside functions is 24 bytes.
- Literal pools total 136 bytes, almost all reviewed stock addresses.
- The call graph has 118 functions. `__aeabi_memcpy4` has **no caller**
  (8 dead bytes).
- The largest function bodies are `ws_observe` 642, `wd_receive` 344,
  `ww_body_valid` 280 and `wht_stop_reviewed` 236.
- Diagnostic inlining flags change each object by 0 to −2 bytes, so existing
  `noinline` sharing is already tuned. These flags are diagnostic only, not
  proposals.

## Measured reductions

"Final" is the final layout. "Assert" is headroom under the unchanged
`stock_append.ld`.

| # | Change | Final Δ | Evidence and cost |
|---|---|---:|---|
| R1 | Link a one-function object first, e.g. `stock_schedule_settings` | **−80** | Unwind table goes from 96 to 16 bytes (12 to 2 entries). Every function start and end still resolves to `EXIDX_CANTUNWIND`. Same 118 functions. Snapshot suite identical to baseline. Changes only the unit order in `probe/stock_link.py`. **Gives 0 assert headroom on its own.** Same mechanism as the 16-byte unwind in the relocation trial; do not count it twice. |
| R2 | R1 plus one translation unit including the 16 `.c` files (`#define` renames for `leave`/`fail`/`inventory`, `#undef BYTE/WORD/HALF`) | **−116** (text −36) | Occupies 9352. Only 3 input sections, so the unchanged script accepts **+152 bytes of code or +160 of data** (filler links measured). Same 100 global and 18 static functions, so root parity holds. No component source edits. Snapshot suite identical. Observed `wa_observe` nested stack stays **244** (144/224/244). No local frame grows; two shrink from 8 to 0. The test ELF must be built from the same unity object. The builder and manifest would change. Earlier single-TU failures came from 113 unmerged entries (904 bytes). |
| R3 | `__aeabi_uidiv` → stock helper at runtime `0x83dceb` (file `0x17d3a`, 119 stock call sites) | **−72** | libgcc-style v6-M divide; divisor 0 returns 0, like ours. In Unicorn, 20,324 cases (edges, divisor 0, random) match our helper with **0 mismatches**; stock span `0x17d3a..0x17f20` executed. Needs a change to `fwstock_link` required symbols and harness admission of that span. |
| R4 | `__aeabi_memcpy` → ROM `0x3f849`, `__aeabi_memclr4` → ROM `0x3f919` | **−34** | Both appear in the ROM symbol table; stock calls them 121 and 73 times. **These ROM bytes were never captured or executed offline.** Weaker evidence than R3. |
| R5 | Drop dead `__aeabi_memcpy4` from the production link | −8 | No caller. May overlap Codex's "3 small exports". |
| R6 | wire.c/dispatch.c shared bodies | −14 src (−16 linked) | One shared exchange clear in dispatch (−10) and one shared frame header in wire (−4). Snapshot suite identical. |
| O1 | Owner-routed, untested: the 12 timer-slot addresses stored as 16-bit offsets | −20 | `stock_health_timers.c` 340 → 320. Not run through tests. |

Measured combinations:

| Combination | Occupied | Remaining |
|---|---:|---:|
| R1 | 9388 | 132 |
| R1 + R3–R5 | 9276 | 244 |
| R2 | 9352 | 168 |
| R2 + R3–R5 | 9240 | 280 |

Rejected after measurement:
- A shared dispatch admission helper: **+24**.
- Building the service table in RAM at boot (checked field by field against the
  eight-row table): generator is 219 flash bytes against a 240-byte table, so
  only −21 flash for +240 RAM.
- An earlier LTO build is invalid because it lacked roots (Codex). It is not
  counted here.

## Service-table options (constraints from the stock transport audit)

Stock facts:
- Setup `0x76b8` reserves **five** services and registers five. A sixth needs a
  stock byte change plus stack memory evidence.
- UART database `0x1f25c` (6×28 bytes). Its primary UUID pointer is
  `0x8451fc`. Callbacks at `0x1f304` are read `0x82da55`, write `0x82da7f`
  (file `0x7ace`) and CCCD `0x82dad3`.

| Option | Data bytes | Status |
|---|---:|---|
| Codex 8-row with separate discovery characteristic | **240** | Measured object; the chosen candidate. |
| Codex 6-row, boot info via RX read | 184 | Codex estimate; semantics unreviewed. |
| 4-row: one read/write/notify characteristic + CCCD | 128 | Measured shape; permissions/flags and read semantics unreviewed. |
| Point the service UUID at an inline characteristic UUID | −16 | Only if the service UUID equals that characteristic UUID; unusual. |
| Table built in RAM | −21 flash, +240 RAM | Rejected above. |
| Demultiplex 20-byte `57 01` frames on the existing UART RX, patching the write pointer at file `0x1f308` | 0 table + **84** wrapper | No sixth slot and no UUIDs. **It conflicts with the documented rule** that unified traffic uses a distinct service and is never a legacy UART command. It shares the TX characteristic and stock's stateless CCCD, and discovery would need a wire change. Needs an explicit user decision. |

## Required additions

| Addition | Bytes | Basis |
|---|---:|---|
| Health commit helper | 196 | Measured object. |
| Service data | 240 / 184 / 128 / 0 | See options above. |
| Owner / boot init | ≥24 (56 with inits) | Coordinator's RAM prototype. |
| Dedicated-service callbacks: write 60, CCCD 20, read 44, register 28 + 12 rodata | 164 | Scratch skeleton, `$SCRATCH/glue/dedicated.c`. |
| Reply pump 96, motion pump 108, tick 20 | 224 | Scratch skeleton, `$SCRATCH/glue/pumps.c`. |
| Demux wrapper (replaces dedicated callbacks) | 84 | `$SCRATCH/glue/mux.c`. |
| Producer/start/result hooks, ticket propagation, fresh-job resume, motion observer/receipt builder, clock and connection-generation bindings, discovery identity, trampolines, sixth-slot change | **unknown** | Not zero. |

The skeletons exclude their placeholder externals, so they are lower bounds,
not designs.

## Combined budget

A. Append-only. The first three rows are measured links; the others are
arithmetic.

| Configuration | Occupied | Against 9520 |
|---|---:|---:|
| Current components | 9468 | +52 (12 under assert) |
| + commit 196 + service 240 | 9904 | **−384** |
| R2+R3–R5 + commit + 8-row service | 9676 | −156 |
| … with 4-row service | 9564 | −44 |
| … with demux (0 table + 84 wrapper) | 9520 | 0 |
| Then minimum glue: owner 24 + pumps 224 (+164 dedicated callbacks) | — | −568 / −456 / −248 |

All are negative before the unknown hooks.

B. With Codex's hypothetical relocation of 408 bytes into indicator holes
(`result_commit`, `schedule_settings`, `compiler_runtime`, `binding`).
Append portion is measured with the same method; hole placement is arithmetic.

| Configuration | Append occupied | Against 9520 |
|---|---:|---:|
| Codex trial reproduced (13 components + commit) | 9176 | +344 (matches Codex) |
| + R2 single TU | 9136 | +384 |
| + R3/R4, `stock_optical_io` (148) into the freed 152-byte runtime hole, `memmove4` (38) into the 40-byte leftover | 8988 | +532 |
| … + 8-row service | 9228 | +292 |
| … + 4-row service | 9116 | +404 |
| + owner 24 + callbacks 164 + pumps 224 | — | −120 (8-row) / −8 (4-row) |
| Glue functions of ≤96 bytes (236 total) into leftover holes of 96/92/32/28/28/12 bytes | — | **+116 (8-row) / +228 (4-row)** |
| Same, under the unchanged assert: about 12 input sections, +80 transient | — | +36 / +148 |

Only this last configuration leaves positive room. What it needs:
- Indicator reference closure and cold-boot/retention proof.
- Separate sections per glue function.
- Adopting R2 and R3/R4.
- Whatever room remains must hold every unknown addition.

This is final-layout arithmetic, not an approved link or placement.

## Verdict

- Measured reductions alone are about 240 bytes (R2+R3–R5 −228, R6 −14). They cannot
  cover the 384-byte known deficit plus at least 412 bytes of measured glue.
- Closing the gap needs **all** of the following:
  - An approved reclaim (indicator holes, about 760 bytes and fragmented).
  - The single-TU build, qualified with full root parity (demonstrated here).
  - The stock/ROM helper evidence.
  - Probably the smaller service or the demux design (a user decision).
- Even then, it depends on the still-unknown hooks fitting in 36–228 bytes.
- If they do not fit, the alternatives are:
  - Larger owned flash, which needs qualified flash geometry and recovery.
  - Retiring more superseded stock code, which needs its own reference closure.
- None of these is approved. No construction, production or physical gate
  opens. Installed V2 optical-off is unchanged.

## Landing list for owners

Diffs are in scratch; nothing is applied.

1. R1/R2 build order and unity: `$SCRATCH/v/unity/unity.c` (all units, for the
   test ELF) and `unity2.c` (production, with the first object linked
   separately). Owner: build/verifier owner, not a component source. Validate:
   - Guarded full build with both ELFs from the unity object.
   - `test_fwstock_link`, `test_stock_switch` (stack ≤244), all ELF modules.
   - A new check that the unwind table maps every function to CANTUNWIND.
   - Root-parity assertion against the prior ELF.
2. R3/R4: `$SCRATCH/v/rt/{cr1.c, cr_no_uidiv.c, abs_all.s, abs_uidiv.s}`,
   `$SCRATCH/uidiv_equiv.py`. Needs:
   - Changes to the `whip/fwstock_link.py` required list and the
     `StockAppendThumb` admitted ranges.
   - The equivalence test above added to the suite.
   - ROM byte evidence for R4.
3. R6: `$SCRATCH/proposals-dispatch.diff`, `$SCRATCH/proposals-wire.diff`.
   Validate with `test_unified_dispatch`, `test_unified_wire`,
   `test_stock_switch` and native dispatch/wire stress.
4. O1: route to the `stock_health_timers.c` owner. Validate with
   `test_stock_health_timers` and `test_fwrom_fence`.

Scratch ELF SHA-256:

| ELF | SHA-256 |
|---|---|
| R1 | `74701dc1…aa67e` |
| R2 component | `03355ec5…b8e77` |
| R2 test | `6972edc3…6b761` |
| R6 + R1 component | `ed82bc24…f43d5` |
| R6 test | `451c530a…e7c5a` |
| R1 + R3–R5 | `baf51cd0…dd357` |
