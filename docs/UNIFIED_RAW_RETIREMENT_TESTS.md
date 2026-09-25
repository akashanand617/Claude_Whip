# Raw-entry retirement: selected stock differential execution

2026-09-24. **17 focused tests passed in 0.25 s**, zero failures or skips.
This is a separate off-ring test module, not part of the preceding guarded
legacy-gate checkpoint. Only `tests/test_raw_retirement.py` and this document
were added; no existing checkpoint input, firmware file, construction gate,
app or live-ring state changed. No new build/OTA artifact was generated.

## Outcome

Disabling only the two audited raw entries in emulator memory preserves the
**exercised** ordinary Health and command paths against exact stock. In
particular, the original optical motion helper still calls the shared reader,
the stock FIFO/Health path receives the same samples, and its real magnitude/
smoothing front-end produces the same outputs. The raw entries themselves
return without clearing dirty state or pretending to cancel a live timer.

This advances the [raw-retirement audit](UNIFIED_RAW_RETIREMENT.md) from static
references to selected differential execution. It does **not** establish whole-
program Health independence, alternate-entry closure, physical steps/sleep,
timer draining, boot/retention, memory ownership, recovery or flash approval.
No body bytes were reclaimed. **A1 still passes the separate BF/CE/CD filter**;
these tests do not modify that policy or install the experimental entry stubs.

## Exact experiment

Input: `firmware/rt02cr-stock-3.12.02.bin`, SHA-256
`b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0`.
The existing harness rejects non-matching images before any experiment.

Both original entries begin `f0 b5 89 b0`. The experimental harness writes only
`00 20 70 47` (`movs r0,#0; bx lr`) at file offsets **`0x1e4a`** and **`0x2104`**,
using their XIP execution addresses in Unicorn. The whole emulator image is
compared with stock plus exactly those eight bytes. All remaining bodies,
shared epilogues, literal/identity pools, neighboring code, DFU and boot overlay
remain byte-identical. The source file is compared again after the module run.

The packet/source/state fixtures are intentionally synthetic. No BLE client,
flash writer, UART transfer or target execution API is imported or called.

## What actually executes, and where it stops

| Witness | Actual unchanged stock execution | Explicit substituted boundary / limit |
|---|---|---|
| Ordinary optical motion source | `0xee50` request=0, call `0xee86 -> 0xcc32`, FIFO drain `0xc280`, cursor publication and optical XYZ scaling | Synthetic status/data reads at `0xbc6a`; only the request=0 branch and selected rate/count fixture are admitted |
| Steps/sleep input delivery | Health consumer `0xcd60`, actual feed `0x1d9d8`, integer square root `0x1d4cc`, scaling/smoothing and original invalid-third-axis filter | Downstream step algorithm `0x1db40` and aggregate `0x1e190` are recorded substitutes; no resulting steps, sleep or records are asserted |
| Current-settings scheduled selection | Minute dispatcher `0x1202`, real settings getters, selected scheduled job starts, working-state stores and optical-post packaging | Time/calendar, wear/charging predicates, timer creation, hub delivery and minute/hour/day bookkeeping remain named fixtures |
| Optical ownership and STOP packaging | Enable `0xf824`, disable `0xf8da`, original optical mutex/TX path through `0xee12` and `0xdbca`; RESET/STOP bytes `7b a5`, `7b 00` | Chip probe, normal hardware start, algorithm initialization, mutex/allocation and final peripheral transaction completion are fixtures, not electrical observations |
| A0 retained command | Handler `0x1dca`, actual battery/status/STK-state getters, original shared-literal loads, checksum `0x3fe8` and complete packet construction | STK state was seeded, not physically read; `0xf80e` reaches a mocked optical probe; notify `0x7e30` records the packet without BLE delivery |
| 9C retained command | Handler `0x1cb4`, actual reply, raw-slot lookup and shared stop/delete wrapper `0x3e30`, both null/live slot cases | ROM STOP/DELETE returns are fixtures that do not drain or clear handles; selected reset/default/optical/state callees are explicitly recorded substitutes |
| Charging dependency | Actual predicate `0x2dae`; bounded original tail `0x34ee..0x34fc`, including raw-flag clear at `0x34f6` | Tail begins with the original caller's prepared six-word frame and R5=0; subsystem calls `0x3328`/`0x6ab6` are fixtures; full `0x343a` charging flow is not executed |
| Idle dependency | Whole `0xa762` table traversal, actual raw-mode getter `0x1e42`, positive/negative callback results and mode-4 veto | Two fixed indirect callback targets are fixtures with checked return site; neither actual low-power transition nor every registered subsystem runs |
| Direct A1 start | Unmodified `0x2104` A1 04 posts disable-all/enable-800, invokes actual timer wrapper and direct report callback | Hub and ROM timer operations are requests only; test enters the handler directly, not through UART/main queue |
| Late callback root | Original callback pointer loaded from file `0x239c`, then actual report callback `0x1e4a` | The test invokes that pointer directly, not from a running timer daemon; this is not scheduling/drain evidence |

The first source comparison crosses the stock sample-buffer wrap. An optical
request takes the latest two samples but preserves all three pending Health
inputs. Its independently checked scaled arrays are `(4,5)`, `(-8,-9)`,
`(251,252)`, and the actual Health front-end outputs `8000,8022,8051`.
A second source comparison retains stock's zero/-1 third-axis rejection and
failed-data-read behavior. In the failure case stock still advances the cursor
with zero data and delivers no valid Health sample; these tests preserve and
expose that limitation rather than converting it into source-freshness proof.

The selected minute scenarios cover the 60-minute multi-job boundary, the
92-minute SpO2 selection, and charging rejection. They are not a day-boundary,
sleep-history or fresh-resume validation. Other scheduled/result paths and
real producer identities remain separate work.

## Non-vacuous controls and memory/ABI bounds

- Each ordinary-path comparison starts once from exact stock and once from the
  same stock with only the two entry edits. It compares **all fixture RAM**,
  ordered direct reads/writes, relevant requests, packets, source samples and
  algorithm-boundary inputs, not just return status.
- Real execution witnesses are asserted at key call sites, and independent
  packet/sample/transaction expectations accompany the differential equality.
  A0's expected packet, optical XYZ values, Health input ordering, scheduled
  masks and RESET/STOP bytes are not copied from the experimental output.
- CPU reads/writes are bounded to original stock data/BSS fixture storage,
  explicitly reserved mock buffers/records, the fixture stack and pinned
  read-only literals. Only the reviewed delay-pointer slot is admitted outside
  those regions. The ranges are **not physical memory ownership approval**.
  Parent mocks validate their call ABI; their host-side RAM writes are included
  in the final full-RAM comparison.
- Calls check restored stack, R4–R11 and PRIMASK. Direct retired-entry tests
  also retain R1–R3, dirty mode/auxiliary flags and a nonzero timer handle under
  both incoming interrupt masks. No timer request or state clear is fabricated.
- The retired body guard rejects exercised interior entries, including the
  shared `0x202a` epilogue. It does not erase the body or assume a static scan
  excluded all possible references.
- Original A1 04 is a positive control: two optical hub requests, timer
  create/start requests and all four report subtypes must occur. The experimental
  entry produces none. No external UART/filter semantics are inferred.
- With **raw mode zero**, the original callback still emits subtypes 1/2/3/5
  before its later mode checks. The retired callback emits none, while its
  deliberately dirty timer handle remains unchanged in both runs. Thus clearing
  the mode is not equivalent to retiring a callback, and returning silently
  does not mean the timer stopped.

Negative controls demonstrate that the oracle detects important mistakes:

1. Entering a retired body or its shared epilogue bypasses the stub and fails.
2. Replacing the stub with a write to mapped but unadmitted fixture memory fails.
3. Incorrectly retiring shared reader `0xcc32` fails the independent optical
   XYZ expectation: the Health dependency cannot be hidden by a successful return.
4. Corrupting shared A0 literal `0x1f48` fails the expected retained packet.

## Reproduction and remaining work

With `requirements-firmware-proof.txt` installed:

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
  python -m pytest -q -c /dev/null --noconftest -o addopts= \
  -p no:cacheprovider --rootdir . tests/test_raw_retirement.py
```

The focused run uses the existing pinned Unicorn M-class/M0 configuration.
It compiles nothing and does not amend the preceding guarded manifest.

Still required before any reclamation proposal: remaining default-Health and
result routes, the other mode-getter caller at `0x2bf8`, complete queue/retained-
timer/indirect-entry closure, boot/retention ordering, protocol compatibility
and whole-image placement with every real hook. The 9C reset subsystems,
charging subsystem, idle callbacks and algorithm/history fixtures must not be
described as executed implementations. Physical source qualification, optical
pause/resume, steps/sleep continuity and usable recovery remain open release
gates regardless of these passing software comparisons.
