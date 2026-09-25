# Unified firmware: stock health lifecycle and adapter constraints

Offline audit, 2026-09-22. **No ring/phone access, flash, installable image or
claim of complete health continuity.** This supplements
[UNIFIED_STOCK_MOTION.md](UNIFIED_STOCK_MOTION.md). All file offsets below refer
only to `rt02cr-stock-3.12.02.bin`, SHA-256
`b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0`.
Runtime = file offset + `0x825fb0`. V2 addresses must not be transplanted.

Follow-up: [exact-stock binding work](UNIFIED_STOCK_BINDING.md) executes the
deeper optical bus chain and corrects the earlier test fixture's return polarity:
`0x12496` returns **zero** on successful writes, `UINT32_MAX` on bus/mutex
failure, and 1 for an unknown operation. Full STOP still discards those results.
The follow-up also finds an unchecked allocation and adds an unattached,
heap-free bus-write shim; it does not close the physical lifecycle gate.

Later [optical-event execution](UNIFIED_OPTICAL_DISPATCH.md) adds a distinct
GPIO/software hub-subtype-zero producer. An old event can repopulate HR/SpO₂
result state after STOP under synthetic cached-ready/algorithm fixtures. The
actual acquisition helper's early return is not checked by its caller. Origin
identity, processor/result commit serialization and notification retirement are
required alongside timer fencing; no physical occurrence or safe adapter is
claimed by these offline cases.

## The important conclusions

1. Stock active motion acquisition is **not established as 25 Hz**. Health
   consumes every valid FIFO sample; Gesture needs an independent, validated
   25 Hz selection/timing path without changing the Health input sequence.
2. STK driver operations and ordinary optical ownership operations share one
   hub task. Health consumption, raw callbacks, indicator callbacks and IRQs
   are not thereby proven serialized with that hub.
3. Queue acceptance, a cleared optical mask and a zero optical state do **not**
   establish successful hardware STOP. Stock ignores some underlying failures.
4. Blocking optical RUN alone is unsafe for data integrity: an uncancelled
   stock measurement timeout can produce a generated fallback value and pass
   it to result aggregation without receiving an optical result.
5. The old raw mode is not a suitable unified-mode ownership mechanism. Its
   mask behavior and cached reader introduce unnecessary interactions.

## Sensor cadence and algorithm input

The active STK configuration routine at file `0xbf34` writes, in order:

| Register | Value | Stock write call |
|---|---:|---:|
| `0x11` | `0x74` | `0xbf3a` |
| `0x10` | `0x0f` | `0xbf42` |
| `0x3e` | `0xc8` | `0xbf4a` |

Initialization `0xbf50` first resets the sensor (`0x14=0xb6`), writes range
`0x0f=5` at `0xbf66`, configures interrupts/FIFO, then calls this routine.
Do not reset or reconfigure an already-active sensor merely to enter Gesture.

The manufacturer datasheet decodes `0x74` as low-power equidistant sampling
with 10 ms sleep duration; `0x0f` selects 1 kHz bandwidth. **`0x3e=0xc8` also
selects stream mode, XYZ and FIFO subsampling every four sensor outputs.**
The power-mode table's nominal 75 Hz entry therefore cannot be equated with
FIFO delivery. Equidistant-mode timing, settling, subsampling and the table's
applicability must be resolved together. No physical FIFO rate follows from
this audit; do not choose a 3:1 decimator or change ODR from the table alone.
The same document describes a 32-frame FIFO; writing its configuration clears
the FIFO and its overflow state. [Sensortek STK8321 preliminary datasheet
v0.9.4, pp. 10–12, 22–23 and 28](https://cdn.hackaday.io/files/1822057795458720/STK8321.pdf).

The sample consumer `0xcd60` iterates six bytes at a time over every pending
sample (`0xcdbc..0xceb2`). For this chip it passes signed `(word1, word0, word2)`
to `0x1d9d8`, excluding third-word zero or -1. There is no 3:1 decimator in
this path. The front end:

- truncates signed axes toward zero after division by eight;
- computes integer square-root magnitude and multiplies by eight;
- applies `(3 * previous + 7 * magnitude) / 10` smoothing;
- calls `0x1db40` once for each valid input;
- separately maintains two-sample axis means.

Disassembly of `0x1db40` shows a 75-sample magnitude moving average and
per-input counters. The new front-end execution test mocks that downstream
algorithm, so it establishes arithmetic/call count, not numerical steps/sleep.

The apparent `#12` / `#25` initialization at `0xcf8a` / `0xcf8e` is **not
evidence of sample frequency**: `0x1dd54` clamps the value to 10..40 and writes
RAM `0x2085ee`. `0x1d5b4`, `0x1d71e` and `0x1d94c` compare it with accumulated
candidate-event count at `0x20cc69`; the first path flushes that count into
step-delta RAM `0x20cc5c`. This supports a step-confirmation threshold
interpretation, not an ODR control. Preserve it, including its time-dependent
selection by stock code.

## Execution contexts and ownership

| Path | Stock evidence | Implication |
|---|---|---|
| Driver timer | `0xcfcc` creates callback `0xcd46`; callback posts type 0 through `0x14bc` | Timer callback requests work, not immediate FIFO drain |
| Hub task | `0x1466` receives eight-byte messages, dispatches through `0x1420` | Common serialized queue for the two paths below |
| Motion hub message | type 0 → `0xd024` → `0xcab8` | Driver wake/reinit/idle/drain runs in hub task |
| Optical hub message | type 3 → `0xdd38` → enable `0xf824` / disable `0xf8da` | Ordinary optical ownership changes run in same hub task |
| Main task | semaphore wait `0x135c`; command dispatch `0x1366`; health consumer `0x136e` | Consumer is not the hub task |
| Raw reader | `0xcc32` can independently call FIFO drain `0xc280` | Do not use this reader as the new Gesture acquisition source |

Hub queue is RAM slot `0x208ca8`; creation at `0x148c` requests 32 entries of
eight bytes. Posting wrapper `0x14bc` uses zero wait and returns queue-send
success/failure. Optical post wrappers `0xdcea` / `0xdd04` create
`{u16 type=3, u16 subtype=2/1, u32 mask}`. A successful post only accepts
intent. It does not acknowledge hub execution or sensor shutdown. Existing
callers often ignore the returned status.

Driver wake `0xcb5e` resets the Health cursor to the producer at `0xcbaa`.
Driver init `0xcab8` sets a pending idle request at `0xcad4`. The actual idle
decision is consumed at `0xcb2a`; suppressing only a higher-level inactivity
predicate does not cover that pending request. Full driver stop also discards
the Health backlog at `0xcafa`. The ownership adapter needs its own temporary
hold without taking these paths unnecessarily.

## Optical entry, exit and bypasses

| Role | Stock file / RAM |
|---|---|
| Ownership mask and state | RAM `0x20c01c`, state at +4 |
| Chip absent flag | RAM `0x20c00c` |
| Optical config rate field / mode | RAM `0x20854c` / +2 |
| Normal enable / disable | `0xf824` / `0xf8da` |
| Normal start request | `0xf128` |
| Full stop | `0x10eaa`: RESET then STOP |
| Control register helper | `0x12496`: `0x7b=0xa5/0x00/0x5a` |
| Indicator cancel | `0x3cac` |
| Indicator entry bypassing normal enable | `0xf812` → `0x11246` |

Verified with original instructions and explicit I2C failure mocks:

- `0xbf34` returns the final write's status, hiding failed earlier active
  power/bandwidth writes. `0xbeba` idle configuration does not include its last
  three power/bandwidth writes in the accumulated success result.
- `0xf8da(0xffff)` can clear mask/state even when both STOP-path writes fail.
  The low-level `0x12496` does return write status, but `0x10eaa` ignores both
  results and returns zero; its callers do not establish physical STOP.
- With the chip-absent flag set, disable returns without clearing the mask.
- Removing owner `0x80` while `0x10` remains can STOP and then call normal start
  in mode 0. Restart happens for state 0, 1, 2 and 3; only the state-byte update
  is conditional on state 2. The existing config rate field is retained.
- Existing raw owner `0x40` prevents later owners from being recorded. Raw
  owner `0x800` does not prevent a subsequent `0x80` request from restarting
  optics in mode 1.

Normal enable calls indicator cancellation, but indicator callbacks also enter
the lower driver directly. A final conditional RUN check needs a reviewed
purpose/lifecycle guard, plus cancellation of indicator timers and delayed
callbacks. Diagnostic direct register writes are another bypass; this audit
does not establish a universal hardware interlock.

## Cancel the optical job, not just its emitter

The scheduled start/callback/timer pairs mapped from the pinned image are:

| Feature bit | Start | Callback | Timer slot RAM |
|---|---:|---:|---:|
| HR `0x10` | `0xe420` | `0xe384` | `0x20c0c4` |
| SpO2 `0x80` | `0xe168` | `0xe104` | `0x20c0ac` |
| `0x200` | `0xe8c2` | `0xe856` | `0x20c0e8` |
| `0x100` | `0xea58` | `0xe9e0` | `0x20c0f0` |
| `0x1000` | `0xecbe` | `0xec54` | `0x20c104` |

Minute scheduler `0x1202` calls these after stock settings/time/wear/charging
guards. HR has a dedicated cancel wrapper `0xe578`: clears working counters,
posts disable `0x10`, stops/deletes timer through `0x3e30`, clears active byte.
This is still asynchronous and does not acknowledge completed optical STOP.
No single reviewed cancel-all wrapper covering every job was established.
Realtime/BLE jobs, on-demand ownership and indicator jobs are additional work.

**Negative witness:** with no received SpO2 result and callback count 64,
`0xe104`'s next invocation reaches `0xe14c`, calls generator `0x081c`, computes
`value % 7 + 93`, and calls result setter `0xe094`. The setter can generate
another bounded value for input at or below 93. The following callback sends
the now-nonzero value to aggregation `0xe0c6`, posts optical disable, and
cancels the timer. The test runs this unchanged stock control flow with explicit
PRNG values and an observed aggregation boundary: outputs 93, 96 and 99 can
reach aggregation without any optical start or sensor result in the fixture.

`0x081c` is an additive state-table generator, not a sensor read. Static
inspection finds comparable bounded-generator fallback branches in callbacks
`0xe856`, `0xe9e0` and `0xec54`; only the SpO2 path is execution-tested here.
The aggregation boundary is mocked: persistence, historical export and phone
display are not thereby proven. Nevertheless, leaving these jobs alive under
a RUN-only gate cannot support a claim of valid measured Health.

## Required adapter contract before Gesture can be acknowledged

1. Serialize a mode-generation change with relevant stock producers/consumers.
   Stop accepting new optical jobs and fence late job callbacks/publications.
   Do not acknowledge completion merely because a queue send succeeded.
2. Cancel all applicable optical jobs and indicators without changing saved
   Health settings or history. Deliberately interrupted measurements must be
   marked absent/interrupted, never allowed to complete using fallback values.
3. Run reviewed optical shutdown in its owning context and propagate transport
   failure. A zero mask/state or a read of control register `0x7b` is not a
   sufficient physical postcondition. Do not turn UNKNOWN into SUCCESS.
4. Preserve active STK configuration, Health cursor, full sample sequence and
   servicing bounds. Obtain a Gesture-only idle hold; do not unconditionally
   wake/reset/stop the shared driver. On acquisition reset/error, invalidate
   Gesture freshness and start cleanup rather than emitting cached samples.
5. Publish Gesture only from verified successful acquisitions using a separate
   reviewed 25 Hz timing strategy. Stop/revoke the session before releasing
   the hold; a delayed old callback must not revive output.
6. Reevaluate **current** stock settings on Health return; do not replay a stale
   mask or force all sensors on. Resume legitimate scheduler eligibility and
   validate fresh results. Record the intentional optical gap independently
   from still-unproven steps/sleep continuity.

The safest insertion candidates are the common hub dispatch and its driver
publication/idle boundaries, but **no adapter hook is yet certified**: missing
RTOS/interrupt exclusion, callback lifetime proof and memory allocation remain
blocking. The stock algorithm/storage continuation and overnight/day-boundary
behavior still require separate tests. No physical health guarantee follows
from this map.

## Reproduction and proof limits

`whip/fwhealth_lifecycle.py` adds separate opt-in harness classes; it does not
widen `StockMotionHarness` or patch stock bytes. Its test file is
`tests/test_fwhealth_lifecycle.py`. Install `requirements-firmware-proof.txt`,
then run `python -m pytest -q tests/test_fwhealth_lifecycle.py` in the offline
proof environment. On this Mac Unicorn initialization requires approved
outside-sandbox host execution; this is not device access authorization.
The completed isolated lifecycle run passed **45 tests**. A preceding run of
the first 37 lifecycle tests together with the existing 40 motion tests passed
77 tests; these overlap and are not additive counts. Python compilation and
`git diff --check` also passed.

Explicit mocks: physical I2C, optical probe/start/algorithm-reset, indicator
cancellation, queue delivery, selected timer cancellation, PRNG output and
result aggregation; for the motion front-end test the downstream algorithm is
also mocked. These tests establish specified stock branches and failure
propagation gaps, not physical power state, sensor timing, RTOS races,
step/sleep accuracy or safe flashing. The stock-only build gate stays closed.
