# Indicator retirement experiment — not a firmware image

2026-09-23. Entirely off-ring. Health remains the unified boot/default; Gesture
is temporary and opt-in. Installed V2 optical-off is unchanged. No connection,
sensor command, phone deployment, firmware file patch, flash or gate unlock.

The stock indicator cancellation path does not invalidate an already-dispatched
brightness callback: after cancellation, that callback can request LEDs again.
The unified policy already forbids decorative indicators in both modes. This
experiment removes their entry paths **in emulator memory only**, while leaving
the ordinary optical Health enable path intact. It does not globally disable
health optics like V2, and it is not a substitute for physical AFE STOP.

## Exact scope

`whip/fwindicator.py` requires the complete stock SHA-256
`b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0`.
Original25Hz, V2, partial images and any changed byte are rejected. The module
only reports witnesses; it does not return an installable image or recompute
OTA checksums. `tests/test_fwindicator.py` loads the unchanged pinned stock into
the existing bounded emulator, then replaces precisely four bytes at each of
these ten file offsets with `movs r0,#0; bx lr`:

| Entry | Purpose |
|---|---|
| `0x3ac4` | Brightness callback |
| `0x3b1a` | Brightness apply/start/stop helper |
| `0x3b7a` | Pattern callback |
| `0x3c18` | Pattern request |
| `0x3cac` | Indicator cancellation |
| `0x3cd2` | Custom pattern request, including a fifth stack argument |
| `0x3d36` | Timed pattern request |
| `0x3d9e` | Request with brightness setting |
| `0x3dc0` | Indicator-active query |
| `0x3dc8` | Pattern cancellation |

The query reports not busy; other reviewed callers either ignore the return or
overwrite it. The stubs preserve argument registers r1–r3, callee-saved r4–r11,
SP and all RAM, return zero in r0, and may clobber condition flags as permitted
by the call ABI. They do not clear handles, claim successful shutdown, restore
settings, delete timers or access hardware. They are **not safe live hotpatches**
for already-active indicators: those optics/timers would still need shutdown.

All other bytes remain unchanged in the experiment, including the internal
shared epilogue `0x3ca8`, literal pool `0x3de8..0x3dfc`, four neighboring
`bx lr` hooks `0x3dfc..0x3e04`, timer wrappers at `0x3e04/0x3e30`, DFU and the
final 200-byte relocated boot overlay. Reaching an indicator body past its
stub fails the experiment explicitly instead of silently executing it.

## References and possible space saving

The pinned audit scans immediate B/Bcc/BL candidates at every halfword of the
code-bearing XIP, permanent-RAM and boot-overlay regions, using each region's
actual execution address. It also scans all byte alignments for 32-bit pointer
candidates. Code/data and second-instruction-half false positives are possible;
the report calls them candidates deliberately. It finds these incoming BLs:

| Target | Call sites, file offsets |
|---|---|
| `0x3c18` | `0x1344`, `0x1650`, `0x47fe`, `0x583a`, `0x5b04` |
| `0x3dc0` | `0x167a` |
| `0x3d36` | `0x3468`, `0x35d8`, `0x35e4`, `0x35f2`, `0xd780` |
| `0x3cd2` | `0x5856` |
| `0x3cac` | `0xf828`, inside normal optical Health enable |

The two literal pointer candidates are `0x3df0 -> 0x3ac5` and
`0x3df8 -> 0x3b7b` (Thumb addresses after adding the load bias).
This does **not** close computed, indirect, ROM/patch or retained callback
references, nor prove startup/retention initialization. Full boot and every
caller have not been executed. No reclamation follows from an empty additional
candidate list.

The executable region is 804 bytes. Retaining ten four-byte entries would leave
**764 body bytes potentially reusable**, split around the entries. Alignment,
branch reach, veneers and final integration may consume part of that amount.
**Approved reclaimed space remains zero.** No body bytes were overwritten,
linker bounds enlarged or stock-address component layout changed. The current
components still use 9224/9520 configured append bytes, with only 296 remaining.
Dispatcher/frame/fence still totals 796 bytes, in unapproved RAM.

## Executed evidence and its limits

The focused suite passes **117 tests**. It covers all ten entries with six
argument patterns, register/stack/whole-fixture-RAM preservation, exact patch
scope and rejection of entry bypasses. Positive controls execute the unchanged
stock late-callback restart; entry retirement removes that new request, without
pretending it stopped pre-existing hardware or cleared old timer state.

Real stock Health enable executes with HR, SpO2 and other reviewed owner masks,
successful/failed probe fixtures, and already-active ownership combinations.
Return, ownership/state, requested optical start, bus operations and all stock
initialized data/BSS match the unmodified control. Optical probe/start and
algorithm initialization remain explicit mocks: this establishes selected
software-path equivalence, not physical Health operation or clinical accuracy.

The actual command handler at `0x47f4` still builds its acknowledgment. UART51
subcommands 1/8/9 still produce their original checksummed replies. Adjacent
non-indicator request boundaries at `0x148fe/0x14902` remain observable and
unchanged; their hardware is not modeled or removed. This includes the custom
pattern's stack argument and shared epilogue dependency in the stock control.

The audit is recorded in the full guarded build manifest under
`stock_indicator_audit`. It explicitly leaves reference closure, cold-boot/
retention, physical shutdown and flashability false. The full build record is
also linked from [the current resource handoff](UNIFIED_RESOURCE_BUDGET.md).

`firmware/unified/build-20260923-indicator-retirement-v1/` passed **1907 tests
in 120.68 seconds**, zero skips/failures/errors/xfails. All **198 hashes** checked
(132 inputs, 63 artifacts, three reports). Manifest SHA-256:
`ad9dded12a4b27d127584f38bd8bb43266511974d8b13554b996d58b07446758`.
Both compiled ARM ELFs are byte-identical to the preceding queue-compaction
build. The 117 focused cases are included, not an additional count. A separate
Capstone candidate scan at the same execution addresses matched all 13 incoming
immediate branches; this is still not indirect-reference closure. No new Swift
source, simulator run, separate legacy-regression run, commit or push.

## Remaining release work

This narrows one LED-restart path; it is not the complete AFE pause/resume
implementation. All other measurement producers, hub/IRQ/RUN/result barriers,
current-settings fresh-job resume and physical STOP still need real bindings.
Verified RAM/stack ownership, complete integration fit, flash geometry and a
usable recovery route remain required. Physical FIFO timing/completion/overflow,
final-model replay, controlled steps and overnight sleep continuity still need
measurements. No number of emulator tests substitutes for those observations.
Further ring access needs a new bounded plan and fresh client coordination.
