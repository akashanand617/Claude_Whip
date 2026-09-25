# Legacy A1/raw retirement: bounded conditional code-space audit

2026-09-24. Off-ring, read-only analysis of pinned stock instructions and
references. Only this document is added. No C, test, builder, linker, firmware
file or live-ring change; the concurrent guarded build's inputs stay frozen.

**A1 is not retired.** The new unlinked legacy filter denies only BF/CE/CD;
A1 deliberately still follows the ordinary stock path. This audit neither
expands that policy nor approves replacing any handler body. Ordinary Health
independence, complete entry closure and a fitting final image are not proved.

## Result and useful size

The raw report callback and A1 command handler together contain **1232 code
bytes**, excluding their shared-data island. They share an epilogue and must
be considered together. With a hypothetical four-byte entry-stub allowance at
each of their two entries and inward four-byte alignment, the primary planning
regions total **1220 bytes**; the largest is **576 bytes**.

That alone is **360 bytes short** of the approximately **1580-byte** deficit
being budgeted with the legacy filter. Combined optimistically with the
[diagnostic candidate's 476 bytes](UNIFIED_DIAGNOSTIC_RETIREMENT.md), it exceeds
that deficit by **116 bytes**; adding the separate
[408-byte indicator candidate](UNIFIED_RELOCATION_TRIAL.md) gives **2104 bytes**,
or **524 bytes** beyond the deficit. These are arithmetic comparisons, **not
successful links**, and exclude additional hooks, retirement implementation,
branch/literal placement and changed unwind/alignment costs. Unknown costs are
not zero. All three candidates remain unowned; approved reclaimed space is zero.

The most important exclusion is the routine called the **raw reader**:
`0xcc32` also serves ordinary optical processing. Its code and shared epilogue
must not be reclaimed. Neither the shared sensor/FIFO driver nor the Health
consumer becomes disposable when the A1 transport is removed.

## Input, mapping and method

Input: `firmware/rt02cr-stock-3.12.02.bin`, 138016 bytes, SHA-256:

```text
b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0
```

Code locations below are **file offsets**, with exclusive range ends. XIP
runtime addresses add `0x825fb0`. Direct-reference scans used the actual
execution mappings, not that bias over RAM-resident code:

| File region | Runtime mapping |
|---|---|
| `0x450..0x20cc8` | File offset + `0x825fb0` |
| `0x20cc8..0x21578` | Permanent RAM code starts at `0x207c00` |
| `0x21a58..0x21b20` | BootOnce overlay starts at `0x20e734` |

Capstone 5.0.7 decoded candidate immediate branches/calls at every halfword;
confirmed incoming sites were checked in context. Full LE32 pointers, even or
Thumb-tagged, were scanned at every byte of the entire image, including data
and headers. PC-relative literal loads and ADR users were inspected separately.
Candidate spans were decoded continuously from their reviewed entries or
continuations. This is not whole-program pointer analysis: computed/relative
entries, live ROM patches, retained callbacks and mutable state remain open.

The exact-image anchors in `whip/fwunified.py`, `whip/fwcommands.py`,
`whip/fwlayout.py`, [wire audit](UNIFIED_WIRE_AUDIT.md),
[stock motion](UNIFIED_STOCK_MOTION.md) and
[timer cancellation](UNIFIED_HEALTH_CANCELLATION.md) agree with these locations.
The older A1 section of [firmware research](FIRMWARE_RESEARCH.md) describes the
different 25 Hz lineage: **do not transplant** its handler `0x20bc`, callback
`0x1dfe`, timer slot `0x209cbc` or DFU timer `0x7ed4` into this stock map.

## Ordinary A1 route and raw producers

```text
UART callback 7ace -> narrow BL at 7b0a -> gate 5c22 -> fast dispatcher 5882
  -> stateful prelude 5890 -> 8112
  -> A1 enqueue 5c0c -> 4cbc -> shared ten-entry queue RAM209d50
  -> main-loop call1366 -> queued dispatcher657c -> call6688 -> handler2104
       -> timer setup22a4/22c2 -> shared helper3e04, slot RAM209cc0
            -> callback pointer827dfb, stored at file239c -> callback1e4a
       -> immediate callback call2342 -> 1e4a
```

`StockWireAudit` independently resolves A1 to fast enqueue `0x5c0c -> 0x4cbc`
and queued call `0x6688 -> 0x2104`. The current helper's BF/CE/CD-only denylist
does not change either result. Rejecting only at the queued handler would still
allow the prelude, queue mutation and semaphore wake; it is not equivalent to
early retirement at `0x7b0a`.

Exact stock raw state is **mode `0x209cb1`**, auxiliary `0x209cb2`, raw flag
`0x209cb0`, and timer slot **`0x209cc0`**. Setup loads the callback literal at
`0x22a0` and `0x22be`, supplies period argument `125 << 3 = 1000` and calls
`0x3e04` at `0x22a4`/`0x22c2`. This is a decoded timer argument, not measured
physical cadence. Helper `0x3e04` creates/starts or restarts a timer; helper
`0x3e30` stops/deletes and ignores operation results. Both are widely shared.

Handler subcommands 1..8 include optical/raw starts, stops, report-now and
counter work. A1 04 posts disable-all then enable `0x800`, sets mode 4/raw flag
1, creates/restarts the timer and reports immediately. A1 05 clears that owner,
mode and raw flag and stops the timer. A1 02 handles `0x40`, not `0x800`.
Unknown subcommands and the charging rejection clear mode/auxiliary bytes and
reply A1 FF without stopping the timer. These are not safe unified transitions.

The report callback constructs subtype 1, 2, 3 and 5 packets; notify calls are
`0x1ea4`, `0x1efe`, `0x1f7a`, `0x1fbc`. It reads motion through
`0x1f14 -> 0xcc32`. **All four notifications precede its charging check at
`0x1fc0` and later mode checks.** Merely clearing the raw mode is not sufficient
to suppress a retained/late callback. Its remaining work can restore/copy
shared statistics, post optical disable, stop the timer and persist results.

## Complete core instruction spans

| Body | File span | Runtime span | Bytes / instructions |
|---|---|---|---:|
| Raw callback prefix | `0x1e4a..0x1f42` | `0x827dfa..0x827ef2` | 248 / 117 |
| Raw callback continuation | `0x1f70..0x2104` | `0x827f20..0x8280b4` | 404 / 179 |
| A1 handler | `0x2104..0x2348` | `0x8280b4..0x8282f8` | 580 / 258 |
| Total | Three code spans, two functions | | **1232 / 554** |

The callback branches across the excluded island at `0x1f40 -> 0x1f70`.
Its shared epilogue is `0x202a: add sp,#0x24; 0x202c: pop {r4-r7,pc}`.
A1 reaches that epilogue at `0x2164`, `0x224c` and `0x2346`; therefore the
callback's middle/tail cannot be erased while retaining an executable handler.
The handler's last call at `0x2342` invokes the callback itself. The following
`0x2348` starts a separate return stub, not more handler code.

Exact code span SHA-256 values:

```text
1e4a..1f42  1d9ef378d75d7c15e0f389c4ce9556c15818d1891fb37636cd20cd16de907dcb
1f70..2104  59b6e3c0f949ccec3ed19d87a2138f71090762e0063585ce2588ef31bcde3c33
2104..2348  33a4fbb4f33978472a6113a1c5b05abfee86aae278b3fd4310ade532d0869cb3
```

Across all mapped source regions, the only confirmed external immediate entry
into any of these code bytes was `0x6688 -> 0x2104`. The only full absolute
pointer into them was the callback word **`0x827dfb` at file `0x239c`**. Its two
known loads are the timer setups above. Other found branches are internal to
the two-function cluster, including their shared epilogue. No external
immediate interior entry was found. **These findings do not close indirect or
retained entries, or prove that the existing timer is drained.**

## Shared islands, neighboring routines and RAM must remain

The **46 bytes `0x1f42..0x1f70`** are excluded in full, including padding:

| Contents | Confirmed outside user(s) |
|---|---|
| `0x1f44 = 0x209cb5` | Initialization `0x1b48`, adjacent commands `0x1bd4`, `0x1c02`, `0x1c28`, `0x1c50`, `0x1cce`, mode getter `0x1e42` |
| `0x1f48 = 0x20899c` | Getters `0x1b50/0x1b60`, identity commands `0x1d20` and others, A0 `0x1e1a/0x1e22` |
| `0x1f4c = 0x827b83` | Distinct timer callback `0x1bd2`; load `0x1bde` |
| `0x1f50`: `3.12.02_` | ADR at `0x1d2e` |
| `0x1f5c`: `260824` | ADR at `0x1d3e` |
| `0x1f64`: `RT02CR_V3.1` | ADR at `0x1d9c` |

Island SHA-256:
`671ca007f45fa3046d63a766e291530e43f1f44ea42f62e2c92b36df67e2c23f`.

Preserve all **24 bytes `0x238c..0x23a4`** too. `0x238c = 0x209cd0` is shared
with `0x234a`, `0x2360`, `0x2378`; `0x2390 = 0x2089dc` is shared with
`0x2384`; `0x23a0 = 0x8282f9` supplies the separate callback at `0x2348` to
startup's timer creator. Even the raw-only-observed literals `0x2394` (FFFF),
`0x2398` (10000) and `0x239c` (raw callback) are not counted as free data.

Adjacent code is not an A1 extension:

- `0x1e42..0x1e4a` is a mode getter called by `0x2bf8` and `0xa764`. Those
  paths change behavior for mode 4; the latter takes an early zero return in
  its callback-based eligibility traversal. Keep the getter and its data.
- Boot initialization calls `0x2360` at `0x12f8`. That function creates a
  different timer at RAM `0x209cb8` with callback `0x2348`, then calls
  `0x1b44`, which clears three bytes beginning `0x209cb5`. Keep it.
- `0x1bd4` uses another timer slot, **RAM `0x209cbc`**, for commands 94/95/96;
  its caller sites are `0x1c08`, `0x1c30`, `0x1c58`. This is not the stock raw
  timer at `0x209cc0`. Keep this creator, callback and neighbor `0x2378`.
- OTA completion calls **`0x2384` at `0x864a`** and branches on its result.
  Keep this getter and its literal. No part of `0x2348..0x238c` is budgeted.
- Command 9C's `0x1cd2 -> 0x3e30` also stops slot **`0x209cc0`**. That
  ordinary retained command must not dereference a repurposed raw-slot address.
- Shared charging/state work stores to raw flag `0x209cb0` at `0x34f6`;
  another path tests it at `0x6bc4` before conditionally calling `0x6ab6`.
  Full pointer words to the raw-state area occur at `0x1f44`, `0x238c`,
  `0x3628`, `0x6d84`. This is not a RAM allocation inventory: computed aliases
  and retained state are not closed. **No raw-state RAM is reclaimed.**

## Keep the Health/sensor, timer and transport dependencies

The reader's exact selected range is `0xcc32..0xccee`, not everything up to
Health consumer `0xcd60`. Ordinary optical motion helper **`0xee50` calls
`0xcc32` at `0xee86`**; that helper has callers at `0xf370`, `0xf5a0`, `0xf682`,
`0xf696`, `0xf6c8`. This alone disproves treating the reader as A1-only.

Additionally, the reader's epilogue `0xcca8` is reached from driver sites
`0xcf3a`, `0xcf50`, `0xcfa8`, `0xd3ee` and then branches to another shared
restore at `0xc7d2`. Neighboring code after `0xccee` contains actual driver
callbacks/getters, not raw padding. Preserve the complete driver/FIFO path
`0xc280`, publication `0xc4e8`, wake `0xcb5e`, consumer `0xcd60` and algorithm
feed `0x1d9d8`. Their live sample buffers and both cursors stay unchanged.

Other shared outgoing dependencies are also excluded:

| Target | Outside raw-cluster caller examples |
|---|---|
| Clock clear `0x1a7c` | `0x1704`, `0x1cec` |
| Charging predicate `0x2dae` | `0x162c`, `0xe53e`, `0xecd8` |
| `0x3768`, `0x3798` | `0x16e0/0x1cdc`; `0x6104/0x76ae/0x8ef8` |
| Timer helpers `0x3e04`, `0x3e30` | Numerous scheduled Health, activity and driver paths, including `0xe566`, `0xe588`, `0xcb8e` |
| Checksum `0x3fe8`, notify `0x7e30` | Ordinary Health/settings/history replies |
| Initialization/reset `0xb086`, `0xb85a`, `0xe4f2` | Boot/default paths `0x15f4`, `0x15f0`, `0x15ec`; non-A1 callers also exist |
| Optical disable/enable `0xdcea`, `0xdd04` | Scheduled Health and other independent optical owners |

The **stock DFU timer at `0x80f8`** (`7d21c900`) also constructs a nominal 1000
argument. It is unrelated to A1 despite the similar instruction pattern.
Preserve it and the stateful `0x8112` receive prelude/DFU paths; changing a
matching timer immediate globally would be unsafe.

### Small remote helpers: measured, excluded from the primary budget

Five functions have only raw-cluster immediate callers in this scan and no
stored full pointers into their complete bodies:

| Span | Bytes | Observed operation |
|---|---:|---|
| `0xdf40..0xdf58` | 24 | Clears two optical accumulator blocks |
| `0xdf58..0xdf60` | 8 | Reads a word from the second accumulator |
| `0xdf60..0xdf68` | 8 | Reads a word from the first accumulator |
| `0xdfce..0xdfd4` | 6 | Reads optical state halfword at RAM `0x20c016` |
| `0xdfd4..0xdfdc` | 8 | Clears that halfword |
| Total | **54** | Two small remote code intervals |

This does not make their **data** raw-only: optical processing calls shared
accumulator updater `0xdf68` at `0xf2ca/0xf2e4`, and setter `0xdfc8` at
`0xf302`. Keep those writers, all their shared data and literal `0xe008`.
The 54 bytes are a secondary closure candidate, **not included in 1220**.
Four two-byte `bx lr` leaves (`0xd7ac`, `0xd7ae`, `0x148f8`, `0x14900`) likewise
have only observed raw callers but remain excluded as tiny remote stubs.
Do not attribute hardware or energy effects to those empty functions.

Thus the full first-level raw-only-observed code inventory is **1232 + 54 + 8
= 1294 bytes**, before any retained entries, alignment or closure proof. The
usable planning comparison deliberately uses only the larger core regions.

## Conditional placement and finite next evidence

| Core region after entry allowance/alignment | Runtime region | Bytes |
|---|---|---:|
| `0x1e50..0x1f40` | `0x827e00..0x827ef0` | 240 |
| `0x1f70..0x2104` | `0x827f20..0x8280b4` | 404 |
| `0x2108..0x2348` | `0x8280b8..0x8282f8` | 576 |
| Total | 1232 − 8 entry allowance − 4 alignment | **1220** |

Entry stubs are a planning allowance, not an implementation or ABI approval.
They cannot guard interior entry or substitute for timer/queue retirement.
The two unbroken post-island code bodies occupy `0x1f70..0x2348` (984 bytes),
but retaining the A1 entry splits that into the table's 404/576-byte regions.
Do not describe it as an available 984-byte hole.

Before proposing reclamation or a broader filter policy:

1. **Prove ordinary Health independence off-ring.** Compare default Health,
   scheduled optical starts/results, steps/sleep input delivery, retained
   commands (especially A0/9C), charging/state changes and idle eligibility
   against exact stock while only the two reviewed raw entry paths are
   retired in emulator memory. Preserve shared pools, RAM and callees. Name
   every substituted algorithm/hardware boundary; do not call this physical
   health continuity. This audit did not execute such a comparison.
2. **Close the two producer roots and activation order.** A future A1 policy
   needs review at UART ingress and queued handler `0x6688`, plus callback
   pointer `0x239c`, immediate call `0x2342` and any retained timer/queued work.
   Establish boot/retention initialization before traffic, or a proved
   drain/retirement boundary for existing work. A raw mode byte of zero, an
   accepted timer STOP, and static-reference absence are not drain receipts.
3. **Check protocol/app compatibility.** Unified Gesture must use its new
   source/service without A1 fallback; stock/V2 clients still need their old
   commands. Retiring all A1 removes its optical/test/counter functions too,
   not just 25 Hz reporting. Vendor-client expectations are not audited here.
4. **Demonstrate an actual complete placement.** Use all current candidates
   and remaining hooks, exact stock-byte preservation, bounded relocations,
   unwind/ELF geometry and reproducibility. Do not spend the arithmetic 116
   or 524 bytes as certified remaining capacity. RAM ownership, physical
   source/pause/resume/continuity and viable recovery remain separate gates.

This is a larger, concrete research lead—not permission to overwrite raw
bodies or evidence that unified firmware is flash-ready.
