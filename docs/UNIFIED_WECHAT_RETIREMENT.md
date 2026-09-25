# WeChat retirement: direct audit, slot adapter and routing guards

2026-09-24/25. The user explicitly accepts removing WeChat/FEE7 sync, then
asks Codex to do the check directly after Claude's closure analysis stopped.
This work uses the pinned stock binary and repository code, entirely off-ring.
It does not remove Health steps/sleep, HID, UART, DFU or Device Information.
**No stock byte, production hook, memory allocation or flash gate changed.**

## Subsequent discovery and combined-startup checkpoint

The [actual six-argument discovery read](UNIFIED_GATT_READ_BINDING.md) is now
implemented as an unattached callback. It refuses unpublished/wrong services,
wrong attributes and nonzero offsets, clears refusal outputs, and returns the
20-byte per-boot identity without changing Health or admitting Gesture.
Identity storage/initialization/lifetime remain a mandatory strong binding;
write/CCCD callbacks and production callback-table attachment remain absent.

`tests/test_wechat_startup.py` additionally composes the slot adapter, both
event-gate roots, advertising builder and resubmission in **one persistent ARM
context**. Both fixture call orders preserve the five service IDs and actual
stored UART/DFU/HID callback pointers. The combined stock edit-span union is
38 bytes (26 advertising + 12 slot/gate); the complete mapped stock image is
compared outside it. Subsequent owned-ID suppression and original UART common
event forwarding execute. This is selected-path integration, not full boot
ordering, ordinary UART traffic continuity or physical discovery. MAC,
registration/ROM/RTOS and skipped boot work retain their explicit fixtures.

The final batch passes **178 tests in 30.93 s**, zero failures/errors/skips:
the prior 144 cases, six combined-startup cases and 28 discovery-read cases.
Archive: `firmware/unified/research-20260925-discovery-read-v1/`, with **1130
content hashes** (1001 inputs, 126 artifacts, three reports), four tools and
178 identities / 534 phases. Supplement SHA:
`efc06a5a3540d82ad16239aceb54521b383931187ba124b9ce392e9d2a1d90ee`.
Launcher: `/tmp/whip-discovery-read-proof.K8flA0/run.py` (new output paths).
The startup witness was independently reviewed without a blocking defect;
its scope is not broadened by that review.
Independent discovery/archive review also found no blocking defect within its
storage/publication contract, verified all 1130 content and four tool hashes,
178 identities / 534 passing phases, all nested input/artifact hashes and the
prior 994 unchanged content files. Repeated objects, stack reports and artificial
ELF match. ARM disassembly confirms six-argument stack placement and output
widths. It independently reconstructed the whole-28 inventory and both strict
six-symbol link refusals. This does not establish the missing physical contracts.

The read callback adds 92 text / 8 input-unwind bytes and a 20-byte local
stack frame. Whole **28 objects / 149 functions / three constants** now have
an input-only append lower bound **10798/9520, at least 1278 over**, before
callback12, final alignment/unwind and remaining bindings. Six strong symbols
remain unresolved, adding `wdr_identity` to the prior five; no production ELF.
Identity20 is already in RAM planning and is not added again. No gate closes.
The 27-object figures below are the preceding checkpoint, not the latest fit.

## Preceding callback and advertising checkpoint

The unattached `stock_event_gate.{c,h}` now supplies `wge_common`. After a
unique service ID has been published, it drops only events for that ID before
reading the event pointer. Every other ID, including general-event `0xff`, is
passed unchanged to the original common callback. It does not parse differently
packed events, manufacture completion receipts or enable admission.

There are **two distinct callback pointer roots**: literal `0x7788` supplies
service-add arguments and literal `0x77ac` supplies global registration through
stock wrapper `0x1587c` / stack operation `0x3104`. Both need redirection.
UART, DFU and HID store their supplied callback; DIS ignores its argument.
The actual-ARM witness changes these two literals and the previous slot-call
BL only in emulator memory. Negative tests show either single-root edit leaves
the other route unguarded. Own IDs 0, 3 and 254 are tested against both legacy
selectors; unrelated events and general events retain original behavior.

The gate needs the slot adapter's stable, once-per-boot ID. Before publication,
dedicated new read/write/CCCD callbacks must fail closed, never fall through to
the old common callback. Those callbacks are still absent. Re-registration,
ID reuse, retained/computed/direct roots and physical callback fencing remain
unqualified. General-event forwarding does not qualify unified send completion.

`whip/fwwechat_advertising.py` separately describes **13 fixed Thumb edits / 26
instruction bytes**, adding no code or RAM. They remove only the four-byte
FEE7 service-list AD element. The opaque manufacturer element, including its
own FE E7 bytes and reversed six-byte MAC, is preserved exactly. Builder
`0x7498..0x74f0` packs 12 bytes at RAM `0x209e21`; both submission sites
`0x74e6` and `0x75fe` change length 31 to 12. Dirty trailing bytes are never
assumed zero. Stock GAP parameter **0x262** is treated as opaque, not assigned
a public-SDK meaning. No replacement service UUID is falsely advertised.

The advertising witness executes the original prologues/epilogues, selected
builder/resubmission instructions and actual GAP wrapper `0x15b30`. Source-MAC
acquisition, skipped boot/configuration work and ROM outcomes are named fixtures.
Three MACs and three status bytes preserve manufacturer data and adjacent RAM;
omitting either length edit exposes stale trailing data and fails parsing.
Other advertising/name bytes are unchanged in these slices, not proof of full
boot, app discovery or physical radio behavior. Callback and advertising tests
are separate witnesses, not a single fully integrated firmware startup.

The guarded batch passes **144 tests in 12.92 s**, zero failures/errors/skips:
the preceding 98 cases, 28 gate cases and 18 advertising cases. It records 144
ordered identities / 432 phases, **994 content hashes** (922 inputs, 69 artifacts,
three reports) and four tool hashes. Archive:
`firmware/unified/research-20260925-wechat-routing-v1/`.
Supplement SHA:
`8048944469be3727f3ec78f74672d3bcf5a3a9e83c6893fb4fb357aaf8725f02`.
Launcher: `/tmp/whip-wechat-routing-proof.eW8vOz/run.py` (fresh paths required).
Independent review found no serious bugs within these contracts, reran the 46
new cases (46 passed in 5.97 s), and verified all 994 content hashes, four tools,
144 identities / 432 passing phases and the prior 915 unchanged content files.
It independently decoded all 13 advertising edits and checked the whole-27
inventory/refusal. This review does not extend the stated fixture boundaries.

The gate costs 32 text bytes, 8 input-unwind bytes and an 8-byte local stack
frame, with no new storage. The current **27 objects / 148 functions / three
constants** have an input-only append lower bound of **10706/9520, at least
1186 over**, plus the uncounted 12-byte callback constant and remaining bindings.
Both strict whole-27 links still refuse the same five strong bindings. There
is no production ELF. Even all 790 surveyed bytes hypothetically reclaimed
would leave at least **408 bytes** excess after that callback constant, before
alignment, final unwind and missing code. Approved reclamation remains zero.
Earlier 26-object numbers below are retained as the preceding checkpoint.

## Direct reference check

Stock SHA-256:
`b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0`.
Code offsets below are file offsets; ordinary execution bias is `0x825fb0`.
The scan separately maps permanent RAM code and the final boot overlay at their
actual execution addresses, rather than treating them as XIP code.

| Stock span | Interpretation | Bytes |
|---|---|---:|
| `0x7b94..0x7bc0` | FEE7 parameter helper | 44 |
| `0x7bc0..0x7bd2` | Indication wrapper | 18 |
| `0x7bd2..0x7bf6` | Read-confirmation wrapper | 36 |
| `0x7bf6..0x7ca0` | Registered read callback | 170 |
| `0x7ca0..0x7d0e` | Registered write callback | 110 |
| `0x7d0e..0x7d5e` | Registered CCCD callback | 80 |
| `0x7d5e..0x7da2` | FEE7 service registration | 68 |
| `0x1f310..0x1f40c` | Nine-entry FEE7 attribute database | 252 |
| `0x1f40c..0x1f418` | Three callback pointers | 12 |

Gross surveyed total: **790 bytes, zero approved reclaimed bytes**. Function
labels are interpretations of exact code/table relationships, not vendor symbols.

The scan covers 67,832 mapped halfword branch/PC-relative candidate positions
and 138,013 unaligned whole-image word positions. The known entry into service
registration is the setup BL at `0x76de`. The three callback pointers name
`0x7bf6`, `0x7ca0` and `0x7d0e` with their Thumb bits. No additional stored
absolute pointers or immediate entry candidates into the other surveyed bodies
were found, subject to the explicit scan limits below.

An apparent incoming branch at `0x7e90` is **not an entry**: it is the second
halfword of the retained UART delay BL at `0x7e8e`, targeting ROM `0x13146`.
The original UART instruction must remain intact. The FEE7 database is derived
from a pointer into its callback table; absence of a direct pointer to the
database start would not make it unreferenced.

Preserve the shared callback `0x6f28..0x7042`, literal pool `0x7da2..0x7dc4`,
all shared Stack/ROM wrappers, and neighboring Health/other-service code. The
FEE7 callbacks invoke the application callback through RAM `0x209e50`; their
registration function stores that pointer. Neither that RAM nor its lifetime
has been declared available for the unified owner.

### Two concrete integration hazards

1. **Setup IDs and shared callback selectors differ.** Setup stores FEE7's
   returned ID at `0x209e1e`. Shared callback `0x6f28` compares IDs against
   `0x209df7`, then `0x209df8`. An earlier assumption that these were the same
   slot was wrong. The initial negative test failed and exposed it; the
   corrected test proves changing the setup slot does not change routing,
   while setting the real selector can enter the legacy route even with
   setup's slot at `0xff`. Any copy/relationship between the distinct objects
   remains unproved. A dedicated shared-event routing/fencing design is needed.
2. **Advertising is separate.** Stock instructions `0x7498..0x74a8` write
   `[3, 3, 0xe7, 0xfe]` at RAM `0x209e21`: an advertising element naming FEE7.
   Replacing the service registration does not remove this startup advertising
   path. Advertising/scan-response changes need their own exact path review;
   do not leave a phantom WeChat service or overwrite adjacent payload fields.

## Implemented, but not attached

`firmware/unified/stock_service_slot.{c,h}` supplies `wgs_replace_fee7`.
It requires all three callback pointers, registers the existing eight-row
unified database through checked `wg_stock_add`, then publishes a separate
assigned ID only after success. It always returns `0xff` to the old setup slot.
That return prevents publishing the new ID there; it **does not close shared
callback routing**. The legacy application-callback argument is ignored.

Two mandatory strong bindings remain undefined: `wgs_callbacks` and
`wgs_service_id`. Callback bodies, stable storage, admission, ID uniqueness,
boot lifetime and old-event fencing are not supplied by syntax checks or tests.
Registration may invoke callbacks before ID publication; they must fail closed.
No re-registration while old callbacks/sends exist is supported.

The ARM witness replaces exactly one BL in emulator memory and runs the original
five-service setup. UART, DFU, DIS and HID registration arguments/database bytes
match the unchanged-stock baseline; the count remains five. ROM allocation,
assigned IDs and callback bodies are explicit fixtures, not a physical GATT test.

The adapter costs **64 text bytes, 8 input-unwind bytes and 16 local-stack bytes**.
All 26 known objects now have an input-only append lower bound of
**10674/9520: at least 1154 bytes over**, with the same unowned placements.
The callback constant adds another 12 flash bytes and the separate ID needs one
owned RAM byte; neither is hidden in the object-only lower bound. Both strict
whole-26 links refuse all five missing bindings; no production ELF is emitted.

The existing new database's 240 bytes are already counted. Replacing the old
252-byte table leaves only 12 table bytes after that replacement, not 252 free
bytes plus an uncharged new table. Even optimistically using **all** 790 surveyed
bytes leaves at least **376 bytes** excess after the callback constant, before
alignment, final unwind and other missing bindings. This is arithmetic only,
not an actual placement, an exhaustive space inventory or a fit proof.

## Verification and retained artifacts

The final guarded run passes **98 tests in 5.22 s**, zero failures/errors/skips:
23 new slot cases, 13 existing service-table cases and 62 transport cases.
It records 98 ordered identities/294 passing phases, **915 content hashes**
(880 inputs, 32 artifacts, three reports) and four tool fingerprints.
This is not a rerun of the full main suite. Prior accepted pins are unchanged.
Independent final review verified every content/tool hash, all identities and
phases, nested code-report inputs/artifacts and byte-identical repeated objects,
stack reports and artificial ELF. It independently reconstructed all26 objects,
147 functions, three constants and the 10674-byte lower bound; both strict
links refused exactly the five strong bindings. No production ELF, writable
allocation or reference-closure approval resulted.

- Build/witness archive: `firmware/unified/research-20260925-wechat-slot-v1/`.
- Supplement SHA: `d2550cf66dce8cc8ad2fb0ae9a3bc5c885ae59dd5df7279ec266cf85d6b0e4bf`.
- Guard launcher: `/tmp/whip-wechat-slot-proof.iHTuhu/run.py` (fresh output paths required).
- Direct scan/reproducer: `firmware/unified/research-20260925-wechat-reference-v1/`.
- Survey SHA: `9ef0bfe3a30ad84de3bd8981268574424eb7b564ef0535d69ee4b05f7a16aa6a`.
- Checked findings SHA: `f5d1e8962ef9f4cc794f1134c9fb887d64ce50269d121e06a3599273945ad413`.

The static scan and scripted findings are a separate audit, not additional
pytest cases. All-halfword scans include data/second-half false candidates;
absolute-pointer scans do not cover computed, relative, ROM, upper-stack or
retained references. Full retirement/reclamation closure remains open.
The [final bindings](UNIFIED_FINAL_BINDINGS.md) and [six release gates](UNIFIED_READINESS.md)
still govern final-image construction and device approval.
