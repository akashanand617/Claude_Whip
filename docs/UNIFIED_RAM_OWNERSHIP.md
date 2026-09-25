# Unified firmware: RAM ownership candidate

**Latest planning correction, 2026-09-24/25:** the
[integrated control owner](UNIFIED_CONTROL_OWNER.md) embeds already-counted
dispatcher/coordinator/STOP objects. Its 880 bytes are not an additional 880.
The selected persistent subtotal is now **1164 + identity 20 + mailbox 56 +
arrival 4 = 1244 bytes**, before remaining bindings, exceeding the nominal
unowned 1224-byte overlay/gap by 20. Event32 is stack scratch; moving other
receipts to the stack is not a qualified allocation strategy. The historical
subtotals and region observations below do not establish ownership or fit.

2026-09-24. Off-ring static analysis of the pinned stock image
`firmware/rt02cr-stock-3.12.02.bin` (SHA-256 `b58fd303…a750b0`). **No
allocation is approved.** No device access, stock change, build change or
gate change. This adds evidence toward the *Memory ownership* gate in
[the readiness checklist](UNIFIED_READINESS.md); it does not close it.

Modules: `whip/fwram.py`, `whip/fwram_read.py`, `probe/ram_read.py`. Tests:
`tests/test_ram_ownership.py` + `tests/test_fwram_read.py`, **69 passed, zero
skips** in `.venv`. The read-plan and replay tests also pass in the Unicorn
proof env.

**Device session 2026-09-24 (read-only, user-authorized, no flash):**
[`firmware/research/2026-09-24/ram-ownership/`](../firmware/research/2026-09-24/ram-ownership/README.md).
268/268 CD01 transactions, verified disconnect.
- Header-shaped words at the configured heap start `0x20ec00` (format assumed).
- Data heap has only **264 B free, 104 B at its lowest**.
- No net gap change between samples 60 s apart.
Details are under *Read plan* below.

**Follow-up session, ~4.6 h later (read-only):**
[`firmware/research/2026-09-24/ram-ownership-followup/`](../firmware/research/2026-09-24/ram-ownership-followup/README.md).
274/274 CD01 transactions, verified disconnect.
- **All 67 gap blocks were identical** in samples 16,606 s apart (no net
  change; DLPS and write-and-restore not observed).
- Heap counters were unchanged.
- ROM vectors: reset handler `0x4efe`, initial SP `0x203800`. Both are read
  offline below; nothing was followed on the ring.

## The question

Where do the unified objects live: 796 persistent bytes (dispatcher, output
frame, timer fence), the 288-byte `ws_receipt`, and possibly the 20-byte
Health-commit preparation? The earlier answer was "the nominal 1024-byte gap
`0x20e800..0x20ec00`, 60 bytes short with the receipt". That figure is
unchanged. What is new is a larger candidate region with better evidence.

## New evidence

Scan boundary: stored constant pointers at **every byte offset**, plus
immediate Thumb BL candidates decoded at their **execution** address (XIP
flash, permanent RAM code `0x207c00`, overlay `0x20e734`). Register-indirect
calls and computed addresses are not closed by these scans (Codex review,
2026-09-24).

**1. Stock's statically addressed app RAM ends at `0x20e734`.** For the two
highest literal-addressed objects, every access *found by PC-literal base
tracking* stays in bounds. Dynamic, indirect and ROM accesses remain open:

| Object | Extent | Accesses found (selected, not exhaustive) |
|---|---|---|
| `0x20e708` | 40 bytes, ends `0x20e730` | Offsets 0..0x24; two 40-byte `__rt_memclr_w`; a callee-saved base across a divide helper; one hand-off through `0x169a0` to `0x17188`, a store-free 10-word mean |
| `0x20e730` | 4 bytes, ends `0x20e734` | Offset 0 only; no escape |

The next lower object (`0x20e320`, cleared as 1000 bytes) ends at `0x20e708`,
so objects tile to `0x20e734`. Of 194 ROM clear/copy call sites, 34 have
constant destination and length. The highest app-RAM end among them is
`0x20e730`. **160 are unresolved** (runtime pointers/lengths) and are not
claimed.

**2. Only zero-length descriptor endpoints name the gap.** Every
word at any byte offset in the image that points into `0x20e7fc..0x20ec00` is
one of the two `0x20e7fc` end pointers in the overlay table. This repeats
the earlier survey, now as a regression.

**3. The boot overlay's RAM copy is boot-only in stock's own terms.**
- Scenario 0's signature is literally `BootOnce`. Scenarios `Scene_B`/`Scene_C`
  share its RAM base with zero length. This is the SDK overlay design, where
  the region is meant to be reused once boot is done.
- The loader `0xa34` has exactly one BL caller (`0x670`) and no pointer
  literal. The overlay query `0xa7e` has none of either.
- RAM `0x20e734..0x20e7fc` is entered by exactly one BL (`0x6a4`). No code
  pointer with the Thumb bit names it; only the descriptor table does.
- Both calls sit in `0x662`, which matches the SDK's `pre_main`: interrupts
  disabled, load overlay, log, run the vector-table setup (in the overlay),
  optional callback. `0x662` has no BL callers and one pointer literal
  (`0x7fc`). Reset code at `0x6c6` stores it into `0x2011d0`, which is ROM
  symbol `app_pre_main` in the pinned symbol file. The pinned SDK
  `pre_main` calls `load_overlay(OVERLAY_SCENARIO_BOOT_ONCE)`.

**4. Captured RAM configuration tiles to the cache boundary.** The
V2-session window gives `appDataAddr 0x207c00`, `appDataSize 0x7000` and
`heapDataONSize 0x7400`. Summed, they end exactly at `0x216000`, the vendor
guide's configurable-cache start. The stock startup passes the same
`update_ram_layout(0x7000, 0x7400, 0)`: bytes `0x6d4..0x6f0` are identical in
stock, 25 Hz and V2. This supports a heap base of `0x20ec00`, above every
candidate region. **It does not prove it**: the ROM heap initializer was not
read.

The public [RTL8762E SDK User Guide v1.4](https://www.realmcu.com/img/ipd/en_638324676932758544.pdf)
(fetched PDF SHA-256 `58545831…6e3d5640`, text-extracted locally) §6.3 states
Data RAM is one piece, `[0x200000, 0x216000)`. Buffer RAM is separate at
`[0x280000, 0x282000)`. So the 29696-byte data heap exactly fills
`0x20ec00..0x216000`, from the end of the app reservation to the end of
Data RAM. If the heap started lower (e.g. at `0x20e7fc`), Data RAM would be
left with an unexplained 1028-byte tail. This is stronger support, still
not the initializer. §6.3.1 lists Data RAM uses as "ROM static data
storage, main stack, patch, upperstack/app static data storage, code
execution and system dynamic memory management". §8 defers DLPS to a
separate *Deep Low Power State User Guide*. That guide and the *Memory User
Guide* are listed on RealMCU's RTL8762E SDK page, but both need a RealMCU
account; neither was obtained.

## Vendor documentation (user-supplied, 2026-09-24)

The user downloaded two account-gated Realtek guides. Both are watermarked
confidential. They are **not stored in this repository**; only section/page
citations and short quotes appear here.

| Guide | Local PDF SHA-256 |
|---|---|
| RTL8762E Deep Low Power State User Guide EN | `435afbece458963d9c400fd68f13b2c72a428245ddebfc9d9e492bf5c4fc0153` |
| RTL8762E Memory User Guide EN | `76754c41843fb1da33915e71c2bca716204b9b11be86c7a53158fdcb3847883d` |

**Data RAM layout is documented in fixed order** (Memory guide §3.1,
Figure 3-1 / Table 3-1, pp. 9–10). From `0x200000`: ROM data (12.5 KB), main
stack (1.5 KB), patch RAM (15 KB), upperstack, APP RAM ("for global/static
variables and RAM code of APP"), then the data RAM heap. The heap is "the
remain size" after `APP_GLOBAL_SIZE`. `fwram.documented_layout` sizes this
with the captured configuration, and it lands on **four independent
observations**:

| Documented boundary | Observed independently |
|---|---|
| Main stack top `0x203800` | Stock entry sets SP `0x203800` (file `0x48c`) |
| Patch RAM `0x203800..0x207400` | Captured ROM-patch declaration `0x203800..0x206d10` |
| APP RAM `0x207c00..0x20ec00` (upperstack = the default 2 KB) | Captured `appDataAddr`/`appDataSize` |
| Data heap `0x20ec00..0x216000` | `heapDataONSize 0x7400`, ending at the end of Data RAM |

The whole candidate `0x20e738..0x20ec00` therefore lies inside the
documented **APP RAM** part, below the heap. §3.4.1 (p. 12) also locates the
app's actual static end at its last overlay execution region, which matches
stock's `0x20e7fc`. The same section warns that the data heap "is shared by
the whole system" and that it "has used 25.4KB DATA Heap by default". Under
that SDK default (not this ring's measured load), 29 KB leaves only about
3.6 KB. A permanent 1.1 KB heap allocation would take roughly 30% of it,
which is another reason to prefer static placement.

**DLPS exit does not take the boot path** (DLPS guide §2.4, p. 10): "In
reset handler, the reset reason will be detected. If system is powered on,
it will perform First Boot flow. If system exits from DLPS mode, it will
perform DLPS recovery flow." Recovery restores platform, BT, CPU, pinmux,
peripherals and user callbacks. §1.2 (p. 7) and §3 name clock, CPU and
peripherals as powered off and "recovered to the previous status". RAM is
not listed as powered off, and no retention split within APP RAM is
described.

## ROM reset branch (captured ROM, read offline, not executed)

The reset vector read on 2026-09-24 points to `0x4efe`. That address lies
inside ROM window `0x4a78..0x53a4`, which was captured twice-equal on
2026-09-23 (`rom-integration`). `fwram.reset_branch_evidence` pins the
following:

1. The handler's first action reads AON word 0 (`btaon_fast_read(0)`) and
   passes **bit 1** to `0x4ee6`.
2. If the bit is set, `0x4ee6` masks interrupts and jumps through the saved
   pointer `[0x2000f4 + 4]` (`0x2000f8`). This happens **before** stack
   painting, NVIC clear, boot-mode selection, image loading and the
   `0x2000f0` boot hook.
3. Otherwise, first boot continues at `0x4e36`. It selects a boot mode,
   loads the ROM-patch image (`0x4b60(0x2792)`) or an alternative
   (`0x4b3c`), then calls `*0x2000f0`.
4. Neither `0x2011d0` (`app_pre_main`) nor `0x2011d8` (`app_main`) appears
   in this window. Their caller lies further down the first-boot chain and
   has not been located.

This is the reset-reason split that the DLPS guide describes ("DLPS recovery
flow" vs "First Boot flow"), now visible in the ring's own ROM bytes.

**Resume target, read in two further read-only sessions** (2026-09-25,
[`ram-ownership-resume-pointers/`](../firmware/research/2026-09-24/ram-ownership-resume-pointers/README.md)
108/108 and [`ram-ownership-resume-code/`](../firmware/research/2026-09-24/ram-ownership-resume-code/README.md)
178/178, both with verified disconnect). `0x2000f8` holds `0xd22d`, chosen
offline and rechecked before the code read. ROM `0xd22c` calls `0xd0b8(0x100)`,
then one indirect restore callback, then **`os_task_dlps_return_idle_task`**,
and returns with a normal `POP`. The wake path reaches the named
idle-task-return routine; **if** that routine restores context and never returns
(expected, unread), the wake path never reaches first boot. If it returned,
control would unwind `0xd242 → 0x4efc → 0x4f12` into first boot. The
callback-slot literal at `0xd478` is outside the window read (Codex's
independent review, `docs/UNIFIED_ROM_RESUME_EVIDENCE.md`). `0x2000f0` (first-boot hook) is `0x40eb`, and `0x20014c`
(early hook) is `0xb9b3`. Three callees remain unread, so this strongly
supports item 1 but does not exhaustively prove it. Assigning bit
1 to "DLPS wake" follows the guide's description and the code's shape; it
is not independently measured.

## Stack paint observations (V2, 2026-09-25)

**Qualification (Codex independent review, `docs/UNIFIED_STACK_EVIDENCE.md`):** intact `0xa5` paint is *observed untouched fill*. It is not a strict bound on maximum SP depth, because reserved but unwritten frame space leaves paint intact, and it is not a guarantee of future headroom. The workload is V2 with optics off. Stack sizes assume uncaptured 8-byte heap headers. The TCB reads are not one atomic snapshot, the 7th TCB is unread, and the 56 non-zero kernel-window words are list fields, not 56 handles. No task binding is approved.


Three read-only sessions, each with a verified disconnect; addresses were
chosen offline between stages. See
[`ram-ownership-stack-watermarks/`](../firmware/research/2026-09-24/ram-ownership-stack-watermarks/README.md).
Stack contents were hash-only; only painted/unpainted profiles were kept.

- **Main stack (boot + all ISRs):** the ROM-painted bottom is fully intact,
  so no write landed in its lowest 384 bytes (observed paint, not a strict depth bound).
- **Tasks**, untouched `0xa5` fill at each stack base (observed paint, not guaranteed headroom):

| Task | Prio | Stack | Untouched bottom paint |
|---|---:|---:|---|
| app | 2 | 1024 | **192 B** |
| Tmr Svc | 6 | 1024 | **504 B** |
| hub | 2 | 2560 | ≥ 1024 B |
| qc_app | 1 | 3584 | ≥ 1024 B |
| IDLE | 0 | 1024 | ≥ 256 B |
| UpperStack | 5 | 3072 | ≥ 512 B |

Consequences for the unified design:
- The observed 244-byte `wa_observe` path **does not fit on the `app` task**
  (192 B of untouched paint), even with the receipt placed statically. The full heap
  also rules out a bigger `app` stack.
- `hub` and `qc_app` each show ≥ 1 KB of untouched paint on V2. `hub` is the sensor-hub
  task, and V2 runs with optics off, so stock Health will use more there;
  re-measure on the stock base before choosing it.
- Timer-service callbacks, such as the unified timer fence, must stay well
  under 504 B of total depth.
- ISRs run on the main stack (lowest 384 B paint untouched), not on task stacks. An ISR
  frame adds 32–36 B to whichever task it interrupts.

## Candidate architecture: one static region, no heap, receipt off the task stack

| Region | Bytes (8-aligned) | 796 + 20 | 796 + 288 | 796 + 20 + 288 |
|---|---:|---:|---:|---:|
| Aligned gap `0x20e800..0x20ec00` | 1024 | fits, 204 spare | **−64** | **−88** |
| Post-boot overlay + gap `0x20e738..0x20ec00` | 1224 | fits, 404 spare | fits, 136 spare | **fits, 112 spare** |

These are planning sums. The measured single object, which also includes
the 4-byte settings-revision owner and Codex's coordinator state, is 1164
bytes with 60 spare (see *Measured prototype*). That margin is thin for
integration growth still to come; the aligned gap alone could not hold it.

Proposed: place all persistent unified state and the single input receipt
statically in `0x20e738..0x20ec00`. Initialize explicitly in the unified boot
init, which already must run after stock Health initialization and therefore
after `pre_main`. This removes:
- the receipt-on-stack question (otherwise 288 + 244 observed nested + 32–36
  exception frame = **568** before the outer caller; no measured task except
  `hub`/`qc_app` on V2 has that headroom);
- the heap-starvation question from a permanent allocation.

The 244-byte observation path and the 64-byte delivery scratch stay on the
serialized task's stack. The receipt and delivery scratch must not alias
(`ws_observe` contract). A reboot recopies the overlay before any unified
code runs, so state is per-boot, as `wd_init` already assumes.

Stock's app code makes few direct heap calls: 2 malloc-wrapper calls, 5
direct allocations, 3 zero-allocations and 6 frees. Only one has a constant
size, 1024 bytes at `0x1a500`. Heap demand is dominated by ROM/RTOS objects
created through `os_*` APIs, such as the three app task stacks (1024 + 3584 +
2560 = 7168 bytes if drawn from the data heap), queues and timers. A static
survey therefore cannot bound the peak. The watermark read below is the
right instrument.

Without overlay reuse, the fallback is the aligned gap for the state
without the receipt. The receipt then has to go on a proven task stack,
whose headroom is unmeasured. A heap allocation is **ruled out** by the
2026-09-24 read: the data heap's lowest free is 104 bytes.

## Measured prototype (not a source or builder input)

Saved under [`firmware/research/2026-09-24/ram-owner-prototype/`](../firmware/research/2026-09-24/ram-owner-prototype/README.md),
with a reproduction script that links the **pinned**
`build-20260924-layout-candidates-v1` stock-address objects. One static
`uw_state` in a `NOLOAD` section at `0x20e738`:

| Member | Bytes |
|---|---:|
| `wd_dispatch` + output frame + `wf_timer_fence` | 764 + 20 + 12 |
| Coordinator: `wc_owner` + `wc_stop_receipt` + `wc_resume_receipt` (holds the 16-byte `wsc_prepared`) | 28 + 28 + 20 |
| Settings revision owner | 4 |
| `ws_receipt` | 288 |
| **Total**, all 4-aligned, no padding | **1164** (`0x48c`); **60 spare** to `0x20ec00` |

The synchronous resume receipt could live on the stack instead (+20
spare). Without the coordinator, the object measured 1104 bytes.

The RAM program header has **filesz 0**: no image bytes. The minimal owner
(`uw_state_claim`, explicit clear plus address) costs **+24 flash bytes**
(16 code + 8 literal), with no new unwind entry. Folding in
`wd_init`/`wf_init` makes it +56. The boot hook that calls it is not
counted.

**Linker caveat found while measuring.** The unchanged `stock_append.ld`
accepts only about **4 extra bytes** of new code, not the reported 52 spare.
Its outside-`SECTIONS` APP `ASSERT` fires during an intermediate lld pass,
while `.ARM.exidx` is still pre-merge (`0x88` plus 8 per new object, against
`0x60` final). With only that `ASSERT` removed, the `MEMORY` region length is
exact on the final layout: 52 extra bytes link with the unwind table ending
exactly at `0x84a000`, and 54 overflow by 4. Whether to change the script is
the build owner's decision; no bound was loosened here. Codex traced the same
cause independently in the pinned lld source and is correcting that assert,
while keeping the exact `MEMORY` capacity and a stricter final-ELF verifier.

## Still open, ranked

1. **`app_pre_main` runs only on First Boot.** *Vendor-documented. The ring
   ROM shows the bit-1 path taken first, via `BL`, into `0xd22c`, which ends
   in `os_task_dlps_return_idle_task`. Divergence from first boot depends on
   that unread routine never returning. Also unread: `0xd0b8`, the callback
   slot and target, and the `app_pre_main` caller. This is a lead, not a
   proof.* The DLPS guide routes DLPS exit to a recovery flow
   instead of First Boot. The guide does not name `app_pre_main`, and the
   ROM reset handler is unread. Power Down wake is not described in these
   terms; a full boot would recopy the overlay and re-run unified init,
   which is harmless for per-boot state. Stock app code has no other path to
   `0x662`, and none of the 42 captured ROM archive files contains
   `0x2011d0`. If `pre_main` did re-run, `0xa34` would probably skip the
   copy (the retained scenario name already reads `BootOnce`), but `0x6a4`
   would still execute unified state as code.
2. **No foreign owner in `0x20e734..0x20ec00`.** *Heap base now
   vendor-documented, with header-shaped words observed at the configured
   start `0x20ec00` (2026-09-24; the allocator format is assumed). Gap samples
   showed no net change.* ROM data,
   patch and upperstack have their own documented parts below
   `0x207c00`. Writes outside those parts (bugs, undocumented
   ROM-patch behavior) are not excluded by documentation.
3. **Retention.** *Vendor documentation supports it. Observed: identical
   samples of 1060 non-zero bytes 16,606 s apart across disconnect and idle.
   That is no net change, not witnessed DLPS or proof against intervening
   write-and-restore. `0x20e738..0x20e7dc` was not testable.* DLPS
   powers off clock, CPU and peripherals, not RAM. The system resumes its
   "previous status", which requires APP RAM and heap contents. No
   sub-region power gating is described. The SDK guide's "Retention RAM"
   block is not explained.
4. **Dynamic-index writes from lower stock objects.** The 160 unresolved
   bulk sites and indexed stores rely on the usual argument that the linker
   bounds each object, not on closure.
5. **Build integration (Codex-owned, not applied).** A `NOLOAD` section at
   `0x20e738` with length `0x4c8` in `stock_append.ld`. The ELF verifier
   must then accept exactly that writable range and refuse `.data` or any
   load image into it. Explicit per-boot zeroing, never startup clear.
6. **Serialization.** A single writer for the receipt, inside the proven
   serialization domain. This is unchanged from the adapter contract.

## Read plan: executed once on the installed V2, 2026-09-24

The user authorized read-only access, and it ran once as `probe.ram_read`.
Four earlier attempts sent zero requests: discovery misses, one connect
timeout and one discovery disconnect, all after the user reset the macOS
bond. The windows target item 2 and the heap fallback on the **installed V2**
image. The ROM and
`update_ram_layout` arguments are shared with stock; the app map is not.
The heap-base window was narrowed to the 8-byte header, so no raw gap
byte is stored.

| Window | Bytes | Why | Host storage |
|---|---:|---|---|
| `0x2011d0` | 4 | ROM `app_pre_main` hook slot | raw, twice |
| `0x2014d8` | 60 | ROM symbols `xFreeBytesRemaining`, `xMinimumEverFreeBytesRemaining`, `xHeapTotalSize`, `xStart` (two words each, assumed data/buffer heaps) and an unnamed 20-byte tail | raw, twice |
| `0x20ec00` | 8 | Presumed first heap block header only (no gap bytes) | raw, twice |
| `0x20e7dc..0x20ec00` | 1060 | V2's post-overlay gap: a change between two reads ≥60 s apart proves a writer | **per-16-byte SHA-256 and zero flag only; raw discarded** |

With the vendor layout, the heap-base window is now a confirmation, not the
main evidence. The watermark counters remain the only planned measure of
heap reserve on this ring.

Decision rules:
- An allocated FreeRTOS-shaped header at `0x20ec00` (next NULL, size with
  the top bit set, ≤ `0x7400`, 8-granular) is *consistent with* the heap
  base. Anything else is inconclusive. The header format is assumed.
- Consistent counters give V2's peak data-heap use. V2 runs with optics
  off, so this is **not** stock Health's peak.
- A changed gap block proves a writer and disqualifies that part. No change
  proves nothing.

**Observed** (both reads equal, except the gap, which is hashed):

| Item | Result |
|---|---|
| `app_pre_main` slot | `0x00826613` = V2's `pre_main` (file `0x662`); the slot holds the app boot callback, as the symbol file and SDK say |
| Heap header `0x20ec00` | next 0, size `0x80000058`: **header-shaped words at the configured heap start** (FreeRTOS format assumed) |
| Data heap | total 29688 (= `0x7400` − 8), **free 264, minimum ever 104** (pinned-symbol counters); free-list head `0x215ef0`; `0x215ef0 + 264 + 8`-byte end marker `= 0x216000` is consistent, node unread |
| Buffer heap | total 14440 (= `0x3870` − 8), free 3680, minimum 3680 |
| Gap `0x20e7dc..0x20ec00` | all 67 blocks non-zero, **none changed in 60 s**; none equals any 16-byte image slice |

Consequences:
- The heap-allocation fallback is **not viable**: even V2 with optics off
  leaves 104 bytes at its lowest. This rejects an additional ~1.1 KB
  allocation under the measured V2 workload. It does not by itself forbid
  every smaller allocation or predict the stock-base peak.
- Item 2 is strengthened: header-shaped words sit at the configured heap
  start `0x20ec00`, above the whole candidate.
- The gap result is only "no net change between samples 60 s apart" (and
  later 16,606 s apart). Write-and-restore is not excluded.
  Its non-zero content has unknown origin. `0x20e738..0x20e7dc` (V2's own
  overlay) was not testable, and boot, DLPS cycles and DFU were not
  observed.

The plan never follows pointers, reads OTP/key fields or MMIO/FIFO, writes,
sends sensor or flash commands, or retries. The CD01 dispatch prelude side effects
documented in [the memory audit](UNIFIED_MEMORY_AUDIT.md) still apply. This
plan cannot establish item 1 or item 3.

What remains for items 1–3 is verification on this ring, not design
intent. That means reading the ROM reset-handler branch that calls
`app_pre_main`, or observing the gap and heap counters across DLPS cycles.
Either needs a new bounded plan and fresh coordination; this document
authorizes neither.

## Scope

Static analysis only. Findings are pinned to the stock SHA; the module
refuses any other image. Addresses do not transfer to 25 Hz or V2 maps.
Nothing here changes a compiler flag, the queue capacity, validation, unwind
data or a construction gate.
