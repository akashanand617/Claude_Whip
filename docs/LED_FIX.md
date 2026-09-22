# LED investigation — 2026-09-22

The comprehensive, corrected firmware handoff is now
[FIRMWARE_RESEARCH.md](FIRMWARE_RESEARCH.md). Original review outputs, all six
capture copies, address-mapping tools and exact v2 patch bytes are preserved in
the [research archive](../firmware/research/2026-09-22/README.md). This file remains
the experiment chronology. No optical-off firmware has been flashed.

Goal: fresh accelerometer readings at 25 Hz with optical emitters off throughout
tracking. Stopping all streaming does not meet this goal. Battery savings remain
unmeasured.

## Hardware evidence

Ring: `R02_CC07`, hardware `RT02CR_V3.1`, reported firmware
`RT02CR_3.12.07_260514`. Existing `rt02cr-25hz.bin`; no firmware flashed in these
tests. Battery reported 99%, not charging.

1. `A1 04` for 12 seconds: 300 accelerometer packets, 159 distinct XYZ values.
   Then `A1 05` for 10 seconds: zero accelerometer packets. The user observed
   flashing at start and darkness after stop, without another charger tap.
   Capture: `data/ledcheck/check_1790069430476372000.jsonl`.
2. A stop-only repeat sent no start command and received zero motion packets.
   Capture: `data/ledcheck/check_1790069554509973000.jsonl`.
3. An optical-only STOP experiment started raw streaming, then sent
   `CE 02 33 7B 01 00 00 00 00 00 00 00 00 00 00 7F`.
   This writes one zero byte to VC30F I2C address `0x33`, register `0x7B`.
   Baseline: 199 packets in 8 seconds, 197 distinct XYZ values. After optical
   STOP: 1,501 packets in 60 seconds (~25 Hz), but only 63 distinct values.
   The last XYZ change occurred **2.479 seconds** after the command. The next
   ~57.5 seconds repeated the exact same XYZ bytes `e0 4c fe ec f9 f1`.
   The user reported the LED was "always dark"; this confirms observed darkness
   during the test but does not establish the exact transition time. The CE
   response was `ce0000000000000000000000000000ce`; the handler echoes data,
   not an explicit I2C-success status.
   Capture: `data/ledcheck/check_1790069719668453000.jsonl`.
4. Repeated optical STOP with fixed, read-only sensor and RAM diagnostics.
   Before STOP, STK range/bandwidth/power registers `0x0F..0x11` read
   `05 0F 74`, interrupt mapping `0x1A` read `02`, and FIFO-consumer flag
   `0x20BDC5` was `1`. Five seconds after STOP they were `05 0A 7C`,
   `00`, and `0`; inactivity counter `0x20CC4E` reached `125`.
   The 20-second optical-stopped phase delivered 500 packets (~25 Hz), but
   its final ~18.27 seconds repeated unchanged XYZ. The user observed flashing
   immediately at the start and then darkness. A 3.55-second unchanged run
   also occurred in the optical-on baseline before fresh readings resumed:
   **optical STOP is not established as the cause of the idle transition**.
   The VC30F command register read zero even before STOP, so its readback is
   not a trustworthy optical-running indicator. Battery reported 98%.
   Capture: `data/ledcheck/check_1790070844062449000.jsonl`.
5. **First successful LED-off sampling trial, on unchanged firmware.**
   Baseline `A1 04` delivered 208 packets with only **one** distinct XYZ value;
   the STK was already idle (`05 0A 7C`, FIFO-consumer flag `0`). Sending
   `3B 02 01 03 00 00 00 00 00 00 00 00 00 00 00 41` enabled volatile
   motion action mode 3, waking the STK and inhibiting connected inactivity.
   Its action dispatch is a no-op in this exact firmware; mode 1 is **not**
   interchangeable because it can emit host input events.

   After this wake, optical-only STOP delivered **1,509 accelerometer packets
   over ~60.3 seconds at 24.996 Hz**, with 1,483 distinct XYZ values and no
   consecutive identical XYZ samples. The STK remained at `05 0F 74`, interrupt
   mapping `02`, FIFO-consumer flag `1` at both the 5-second and final snapshots,
   even with inactivity counter at `125`. The user reported initial flashing
   followed by darkness while the test was still running, and subsequently
   explicitly confirmed that the LEDs stayed dark while moving the ring.
   `A1 05` was sent
   **after** the optical-stopped measurement, not to create the dark phase.

   Cleanup sent `A1 05`, `A1 02`, and motion mode disable
   `3B 02 01 00 00 00 00 00 00 00 00 00 00 00 00 3E`.
   RAM `0x20BFC0..2` read back `00 01 00`, exactly the pre-test state.
   At the final snapshot the normal idle request was pending; completion of
   the idle transition after disconnect was not measured. Battery reported 97%.
   Capture: `data/ledcheck/check_1790071705479474000.jsonl`.
6. **User-requested repeat, 120-second optical-stopped interval.** Same command
   sequence on the unchanged firmware, after a new connection; battery 96%.
   The user observed the LED turn off and then tested movement. The interval
   delivered **3,008 packets at 25.0018 Hz**, 3,007 distinct XYZ values, maximum
   consecutive identical duration 30.2 ms, and no unchanged tail. Clear motion
   was present after the initial five seconds: the middle two 30-second blocks
   peaked at 6.88 g and 6.05 g vector magnitude, with rail clipping on some axes.
   The final quieter 30-second block still had 750 distinct readings from 750
   packets. Maximum packet gap was 76.4 ms. This establishes a motion-responsive
   stream rather than only noise variation or repeated notifications.

   Final registers remained active (`05 0F 74`, interrupt mapping `02`,
   FIFO-consumer flag `1`) despite inactivity counter reaching `125`.
   `A1 05` ended the measurement afterward; no motion packets arrived more than
   two seconds after it. Cleanup restored motion state `00 01 00`, then
   disconnected. The user explicitly confirmed the LEDs stayed dark after
   initial flashing, including while moving the ring. That is the visual
   evidence for darkness; BLE data alone cannot establish it. No firmware
   was flashed.
   Capture: `data/ledcheck/check_1790072161023025000.jsonl`.

**Optical STOP alone is insufficient; wake/hold plus optical STOP passed the
one-minute freshness test and a two-minute movement/rest repeat.** This is not
yet proof of long-term LED suppression,
normal post-disconnect battery use, or improved battery runtime. Background
optical restarts remain possible on the unchanged firmware.

## What the disassembly establishes

Addresses below are file offsets in the archived 25 Hz image.

- `A1 04` enables optical sensor bit `0x800`. `A1 02` clears `0x40` instead;
  `A1 05` clears the correct `0x800` bit and stops the raw producer timer.
  The host stop sequence now includes `A1 05`, fixing shutdown independently
  of the remaining during-tracking problem.
- Fable's candidate `0xF710: 51 48 -> E5 E7` bypasses initial optical startup
  with the sensor mask left clear. Periodic health requests can still enable
  optics later. Indicator path `0x3A8E -> 0xF67A -> 0x110AE` also bypasses the
  sensor-enable function entirely.
- Shared VC30F control function `0x122FE` maps STOP to register `0x7B = 0`,
  RUN to `0x5A`, and RESET to `0xA5`. Changing the immediate at `0x1231A`
  from `0x5A` to zero would suppress ordinary start/indicator/recovery paths.
  Skipping sensor-enable at `0xF68C` could additionally avoid configuration
  work. These are **experimental candidates, not a validated solution**.
- Diagnostic `CE 02` writes directly through the generic I2C helper and can
  bypass that RUN patch. No arbitrary diagnostic register writes belong in
  normal tracking.
- Raw producer `0x1DFE` obtains accelerometer data through `0xCBDA`. That
  function drains the sensor FIFO only when RAM flag `0x20BDC5` is set;
  otherwise it returns a cached ring-buffer sample. Hardware evidence now
  agrees with this distinction: active flag `1` became `0` as readings froze.
- Accelerometer task `0xCA60` consumes an idle request at state offset `+6`
  (`0x20BDCA`), calls `0xC888` to reconfigure the STK, and clears the
  FIFO-consumer flag. The inactivity predicate `0x1D91C` checks a counter
  against `125`; `0xCD08` uses it to request idle. Startup also posts an idle
  request, so suppressing only the inactivity predicate is insufficient.
- Raw tracking needs both an explicit wake when it starts from idle and a
  guard at the final idle transition while raw mode (`0x209CAC`) equals `4`.
  Non-tracking idle behavior must remain intact to avoid spending the battery
  savings outside a tracking session. This is a proposed design, not yet a
  hardware-validated patch.
- Disconnect clears connected-state byte `0x209E09`, but raw mode `4` can
  remain set. The firmware idle guard must therefore require **both** raw mode
  `4` and connected state `2`; raw mode alone would keep the accelerometer
  awake after an unexpected disconnect. Reconnection starts a new tracking
  session with `A1 04` to explicitly wake it again.
- Host motion command `3B 02 01 03` sets state `0x20BFC0`, wakes via `0xC4FC`,
  and inhibits inactivity through `0xD43E` while connected. The selected
  handler makes volatile changes, not NVM writes. Its setter forces sensitivity
  to `1`; diagnostic preflight therefore requires original state `00 01 00`
  so disabling restores it exactly. The API's ordinary read does not expose
  the third state byte, so the diagnostic uses a fixed read-only RAM snapshot.

## Next acceptance checks

- Review the conditional idle guard and explicit wake, including already
  pending idle requests, before producing a flash candidate.
- Repeat the successful fresh-data trial with intentional motion and rest,
  repeated start/stop, disconnect/reconnect, and long enough to cross background
  scheduling boundaries. A one-minute trial does not establish these.
- Only then test a reviewed firmware candidate and measure battery drain over
  a sufficiently long matched workload. Preserve the existing 25 Hz image as
  the rollback target.

## Superseded first candidate (not flashed)

`firmware/rt02cr-25hz-optical-off-experimental.bin`, built by the earlier version
of `probe.build_optical_off` from the strict hash-pinned base, has SHA-256
`f862e5bb1b65ff43d6133524d20fd82bcbc072bd8a1245a9927367993a213f27`.
It changes 47 payload bytes and derived container checksums:

| File offset | Change |
|---|---|
| `0xF68C` | Return from optical sensor-enable before its stack push |
| `0xF690` | Reclaimed function body holds the raw-mode + connection idle guard |
| `0xCAD2` | Call the guard instead of loading/comparing the pending idle request |
| `0x21DC` | Store raw mode 4, then call the existing STK wake-request function |
| `0x1231A` | Map ordinary VC30F RUN to STOP, including indicator/recovery paths |

Optical health and indicators are disabled globally. The normal gesture image
remains the default; this candidate is not a deployment recommendation yet.
Independent review checked the instruction targets, literal addresses, stack,
registers, flags, reclaimed region references, and disconnect handling. No
new synchronous wait-for-optical-data loop was found. Remaining hardware risks
include RESET transients, indicator configuration traffic despite dark optics,
asynchronous wake latency, and behavior across repeated start/stop/reconnect.

Validation before any flash: 107 focused tests passed; the full suite had
464 passing tests and one existing, unrelated `tests/test_script.py` cut-margin
failure. Container and all archive hashes verified. Offline DFU dry run verified
135 chunks / 672 BLE writes and exact reassembly, without a connection.
These checks do not eliminate flash risk or establish runtime behavior.

The Python capture path also now attempts both stop commands after setup
errors/cancellation, continues cleanup if one stop write fails, and closes the
recording file. These lifecycle fixes prevent avoidable stuck states but cannot
guarantee a stop command reaches a disconnected device.

## Completed Fable workflow refresh

Read directly from Fable's saved session
`fce5503d-9fbc-4aa8-93c0-bd04600def2d` and workflow
`wf_e507bed5-541/journal.jsonl` under its Claude project directory. The main
session's last visible message is a usage-limit notice at
`2026-09-22T10:24:33.798Z`; no final main-agent synthesis followed. The journal
contains nine verifier results plus the completed critic
`a5017e9fe202cd0b7`, whose verdict is **proceed_with_changes**. There were eleven
starts (including duplicate work), so this is not a claim that eleven agents
returned results. This is a saved-output context refresh, not a native UI
`/import` or a memory import. No hidden reasoning was imported.

Material findings and reconciliation:

- **`69 01 04` starts realtime HR; it is not a stop.** Independently confirmed
  against the archived firmware: `sub_050DC` enables bit 1 at `0x517E..0x5180`.
  `69 06 04` reaches `disable(1)` at `0x5292..0x5294`, then stops the report
  timer via `0x525C`. `69 06 02` stops reporting only. Corrected the host quiet
  tuple and LED probe, with regression tests. The successful trials above did
  not use the mislabeled health-stop command. Clearing bit 1 does not clear raw
  bit `0x800` or guarantee that other optical owners are absent.
- `16 02 02 3C` disables **only one** of five health schedules. Their settings
  are `0x16`, `0x2C`, `0x36`, `0x38`, `0x3A` (bits 0–4 of `0x208AB1`);
  `0x3A` had not been read back. The minute tick's `0x208C4A` gate is time-set,
  not HR logging enabled. Existing host logging-disable packets cover only
  the first two schedules; comments now say so. No additional persistent
  settings were changed in this refresh.
- The single-halfword `0xF710` patch is superseded: it does not cover ordinary
  background/indicator starts or hold the accelerometer awake. Fable's nine
  verifier results primarily covered that patch, **not** our multi-site image.
  Its final critic separately decoded the first multi-site image and found its
  mechanics sound, with hardware behavior unvalidated. Neither is flash approval.
- **Disconnect leaves more than an accelerometer-idle concern.** In the base
  and first candidate, retained raw mode 4 also vetoes MCU deep sleep
  (`0xA54E -> 0x1DF6`) and leaves the raw producer timer firing. V2 below adds
  cleanup for both; releasing the connected-only STK guard alone was insufficient.
- Charger insertion's disable-all comes from `0x33AC -> 0xE3B6 -> 0xDC82`,
  not from the A1 handler (which refuses commands while charging). No new
  charging test has been run. Deep-sleep state and battery savings remain
  unmeasured; clearing a code-level veto is not proof of actual sleep.
- Optical disable includes boot, charging, find-ring and low-battery
  indicators, plus realtime and scheduled optical health measurements.
  Indicator sequences can still generate configuration I2C traffic while dark;
  disabling LEDs does not establish zero optical-subsystem power.

## V2 candidate and hardware validation tooling (not flashed)

The current offline builder produces
`firmware/rt02cr-25hz-optical-off-v2-experimental.bin`, SHA-256
`0d18a0fa860d58ab8f984b5f542f45dac105241f47bf1c2af41321eb0431e14c`.
It changes 81 payload bytes plus derived container fields. In addition to the
first candidate's edits, a hook at `0x691E` calls a wrapper in reclaimed bytes
`0xF6B4..0xF6D3`: run the original `0x7042` cleanup, then, only for raw mode 4,
clear the mode byte and call the existing null-safe timer stop/delete helper
`0x3D38` on handle slot `0x209CBC`. Other raw modes retain their original
behavior. Separate local static reviews and instruction-execution tests cover
the hook, register/stack preservation, all 256 mode values and null/live timers.
This review is independent of Fable's older workflow; hardware validation is
still required. The old artifact is preserved but is no longer the current
manifest/build target.

`probe.validate_optical_off` uses 22 fixed serial code reads (244 bytes) to
distinguish the strict pinned base from this exact candidate at all patch sites
and neighboring bytes. It is a critical-site fingerprint, not a full flash
hash. Mixed bytes and the older candidate are rejected. DIS/version text alone
cannot distinguish these images. Code-read accessibility on the actual ring
has **not yet been tested**; `--check-only` does not start/stop streaming or
write sensor registers.

After a separately approved flash and successful identity check, the probe can
test repeated connections with `A1 04` only—no `3B` hold or `CE` optical STOP—
then `A1 05`/`A1 02` and an idle observation. Gates include rate, sample
variation, meaningful motion, gaps, FIFO-active state, stopped producer and
idle state. These checks are heuristics, not proof against every possible
cached/replayed stream. Visible darkness still requires human observation.
Unexpected disconnect/reconnect, boot/charger behavior and a long matched
battery experiment remain separate acceptance tests. No BLE commands were sent
and no firmware was flashed during this workflow refresh.

Offline refresh validation: **179 focused tests passed**, all five current
archive hashes verified, and `git diff --check` plus the fetch script's shell
syntax check passed. These cover host protocol/cleanup, experimental probes,
builder, identity and container tests; they are not a new full-suite or
hardware pass.
