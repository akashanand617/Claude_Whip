# Ring battery comparisons

## Scope and evidence

The current ring image is the original custom 25 Hz `firmware/rt02cr-25hz.bin`,
SHA-256 `f13e63d3fdef3b10aa20fd4e0672077b66f60bb19c689ef64053840e4d35d3d9`.
Neither optical-off firmware candidate has been flashed. An LED-off test here uses
the temporary host workaround, not the permanent firmware patch.

| Condition | Existing evidence | Limits |
|---|---|---|
| Stock 1 Hz raw streaming | Rate and optical flashing observed; stock drain deliberately skipped in `HARDWARE.md` | No measured stock runtime baseline |
| Stock ordinary health tracking | No controlled discharge run located | Different workload from continuously connected raw streaming |
| 50 Hz original optical operation | Historical estimate ~1 percentage point/minute, ~1.7 h extrapolated | Not a matched fresh-motion comparison |
| 33 Hz original optical operation | Historical ~0.27 points/minute, ~6.3 h extrapolated; `data/drain/drain_20260906_202930.csv` records 99→90% | Chunked acquisition, no freshness gate |
| 25 Hz original optical operation | Historical project estimate ~0.30 points/minute, ~5.5 h extrapolated | Matched raw evidence/freshness not established by that estimate |
| Custom firmware, connected idle (no raw stream) | `drain_20260906_212434.csv`: 87→86%, about 34 minutes logged; `data/drain_idle2.log` explicitly names the idle workload | Not stock health tracking and not LED-off gesture tracking; one-point drop is too coarse for a robust runtime estimate |
| 25 Hz temporary LED-off, explicit accelerometer hold | Completed 600.04 s battery run: 92→90%, ~0.20 points/minute; fresh ~25 Hz throughout the checks | Short, coarse battery reading; not a matched LED-on comparison or a full-discharge runtime |

The other old drain files (`drain_20260906_212016.csv` and
`drain_20260906_212434.csv`) report **0 Hz** throughout. Their companion logs
identify deliberate idle tests, not failed tracking tests. They are useful as
connected-idle observations, but not evidence of low-power tracking. Historical
`probe/drain.py` reads battery before a chunk
but associates it with the chunk-end elapsed time, and restarts capture for each
chunk. Do not silently combine these records with continuous-session results.

## Requested short test — 2026-09-22

The user selected LED-off tracking on the current image and requested **10 minutes**.
The harness is `probe/batterycheck.py`; results are incremental JSONL records under
`data/batterycheck/`. A requested/prepared test is not a measured result: consult
the actual log's identity, phase, battery, stream-health, result and cleanup records.

Started capture: `data/batterycheck/battery_1790075215600058000.jsonl`,
2026-09-22 at approximately 04:07:11 America/Phoenix for the measured phase.
The preflight read all 22 critical-code chunks successfully and classified
`original25Hz`; initial motion state was `000100`. Starting battery was 92%,
not charging. The first complete freshness window contained 250/250 distinct
XYZ samples at 25.0 Hz, maximum gap 75.3 ms. These are **startup observations**,
not a completed ten-minute result or a user confirmation of darkness.

This first run was deliberately interrupted after ~83.4 measured seconds at the
user's request to repeat while watching: the user did not see any startup flash.
Both reported battery samples in the measured phase were 92%; the last was only
~60 seconds in, so this is not a ten-minute drain result. Freshness passed again
at 25.0 Hz with 250/250 distinct XYZ. Cancellation sent `A1 05`, `A1 02`, and
motion disable; cleanup had no errors and read back `000100`. No fault or stale
data triggered this stop. The repeat is recorded separately in
`data/batterycheck/battery_1790075332801725000.jsonl`; do not join the two runs
into one continuous measurement.

Repeat startup: measured phase began at approximately 04:09:08 America/Phoenix,
battery 92%, not charging, with the original25Hz fingerprint and `000100`
preflight state again verified. The first post-STOP window passed at 25.0 Hz,
250/250 distinct XYZ, maximum gap 76.0 ms. The user then confirmed: "yes it
flashed and stopped flashing". This confirms the observed startup transition;
it does not yet establish darkness throughout ten minutes or specifically during
movement.

**Completed:** the repeat stopped automatically after 600.0378 measured seconds,
at approximately 04:19:08 America/Phoenix. Battery reply times were 600.0065 seconds
apart: 92% initially, 90% finally, approximately **0.20 percentage points/minute**.
The minute readings were 92, 91, 91, 91, 90, 90, 90, 90, 90, 90, 90 percent.
The ten logged freshness windows passed (25.0–25.1 Hz, 249–250 distinct XYZ;
one window contained 251 samples); the continuous rolling gate never failed.
Sensor-active reads remained `0101`. There was no charging or disconnect error.
Cleanup sent both raw stops and disabled the temporary hold, then read back
`000100` without errors; the shell exited successfully. No firmware was flashed.

The historical flashing-LED estimate was 0.30 points/minute, equivalent to about
5.56 hours by linear extrapolation. The new short run is nominally one-third lower
drain, but is not a controlled causal comparison. In particular, its final six
minutes stayed at the same reported percentage. Do not claim an established
runtime or savings from extrapolating a two-point drop.

Both battery logs are preserved byte-for-byte in
[`firmware/research/2026-09-22/captures/`](../firmware/research/2026-09-22/captures/),
with SHA-256 checksums in that archive's manifest. The first, deliberately
interrupted run remains separate from the completed repeat.

Command used (no flashing):

```sh
.venv/bin/python -m probe.batterycheck \
  --address 3C2FA77E-1BE3-A0C5-0DD5-DB6A3AD452B2 \
  --optical-stop --duration 600 --poll-seconds 60 --stop-at 40
```

Offline checks before launch: 24 battery-harness tests passed; the related
LED/identity/validation/cleanup/protocol suite also passed (85 tests). The
combined related suite run by the implementation agent passed 171 tests.

Test protocol:

1. Keep the ring off its charger. Disconnect QRing, the iOS health app and other
   capture tools so there is one BLE owner. Do not change health schedules during
   the run; note any visible optical restart.
2. Verify hardware/version and the original 25 Hz critical-code-site fingerprint.
   This is sampled identity, not a full flash hash readback. Refuse an unknown image.
3. Require the audited motion-control RAM state `00 01 00` and battery above 40%.
4. Start raw capture once (`A1 04`), apply volatile motion action mode 3 to keep
   the accelerometer fresh, then send the fixed optical-only STOP. The LEDs can
   flash briefly during setup. Human observation, not the command echo, establishes
   visible darkness. `A1 05` is not sent during the tracking interval.
5. Record battery at the actual reply times, at the start, roughly every minute,
   and at the end. Save all notifications with phase and receipt timestamps.
   Check rolling sample rate, changing XYZ values, gaps and the active sensor flag.
   Moving the ring initially demonstrates responsiveness; normal quiet periods
   should still contain fresh sensor noise rather than a frozen cached value.
6. End after ten measured minutes, or earlier for low battery, charging, disconnect,
   failed reads or failed freshness. Independently attempt `A1 05`, `A1 02` and
   motion-hold disable during cleanup, including cancellation/error paths.

## Interpretation and next comparisons

Report start/end percentage, their actual time separation, sample freshness/rate,
visible LED observations and any early termination. Ten minutes is a screening
measurement: a one-point reporting step corresponds to ~0.1 points/minute. Zero
reported drop is **not zero power consumption**, and a short slope is not a validated
full-discharge runtime. Battery state, rounding, workload and charging history matter.

A causal optical comparison should next hold the image, BLE workload, explicit motion
hold, movement and starting charge range constant while varying optical STOP. A stock
comparison requires a separately approved restore and two clearly named workloads:
ordinary health tracking versus stock raw streaming. Do not flash stock automatically
or treat the zero-data old captures as stock health measurements.

Background health/indicator paths can restart optics on the unchanged firmware.
This test does not establish a permanent LED fix, classifier accuracy, disconnect
sleep behavior, or the battery performance of the unflashed v2 image.

References: [firmware handoff](FIRMWARE_RESEARCH.md),
[hardware measurements](HARDWARE.md), [LED experiment chronology](LED_FIX.md).
