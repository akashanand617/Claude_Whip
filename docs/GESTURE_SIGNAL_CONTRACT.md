# Gesture signal contract

Status: the coordinate/scale contract below is frozen. RT12COL V6 and V7 have
both physically passed bounded 25 Hz freshness checks; V6 additionally has the
stronger renewal and frozen-model transfer evidence and remains the selected
cross-ring baseline. V7 is currently installed for comparison but is not an app
install target. This document does not claim exact cross-ring model parity.

## What the adapter is allowed to do

For every decoded XYZ sample, in original sample order:

1. convert packet counts to physical acceleration using the corpus contract of
   8005 counts/g;
2. clip only to the common signed-16 packet rails (about +/-4.09 g);
3. apply the measured proper rotation:
   - RT02CR: `[x, y, z]`;
   - RT12COL: `[x, z, -y]`;
4. apply only a separately measured per-device zero/gain calibration in the
   canonical frame; identity is the default;
5. express the result in the same 8005-count/g model units.

It must not fit a gain from classifier accuracy, round one family to a guessed
ADC grid, interpolate using BLE callback timestamps, or attempt to invert an
unknown transient response. BLE time describes delivery, not the instant at
which the accelerometer sampled the movement.

The Python implementation is `whip/ring_profile.py`; the iOS implementation is
`ios/R02Ring/Gesture/GestureSession.swift`. Their parity is pinned by
`tests/test_ring_profile.py` and `ios/R02RingTests/GestureReplayTests.swift`.

In equations, the default live mapping is deliberately small:

```
RT02 model sample = clip(raw / 8005 g) * 8005
RT12 model sample = clip(R * raw / 8005 g) * 8005

R = [[1,  0,  0],
     [0,  0,  1],
     [0, -1,  0]]
```

`det(R) = +1`, so this is a rotation, not a reflection that would silently
reverse gesture handedness. Fingers-forward and fingertips-down poses determine
two non-collinear physical directions; the right-handed constraint determines
the third. Changing finger or hand does not change this board-coordinate map.
It changes how a person produces a gesture, which belongs in model validation,
not in the hardware adapter.

An optional per-device offset/gain exists only for a future static multi-pose
calibration. It must be fit from known gravity vectors, with held-out pose
residuals reported. It must never be fit from gesture accuracy or from one snap
session; until that procedure is measured, its value is identity.

## Why the numerical scale already matches

| Property | RT02CR | RT12COL V6 |
|---|---:|---:|
| Sensor | STK8321 | LIS2DW12 |
| Range | +/-4 g | +/-4 g |
| Meaningful resolution | 12 bit | 14 bit (LP2) |
| Meaningful sensor LSB | 512 LSB/g | 2048 LSB/g |
| Left alignment in 16-bit word | 16 packet counts/LSB | 4 packet counts/LSB |
| Nominal encoded scale | 8192 counts/g | 8192 counts/g |
| Measured/corpus scale | 8005 counts/g | about the same under gravity |

The two nominal scales are therefore the same by construction:
`512 * 16 == 2048 * 4 == 8192`. The RT12 captures use four-count steps, as
expected. Actual RT02 packets contain every low-bit residue even though its ADC
is nominally 12-bit, so erasing the low nibble would change the established
firmware/model contract rather than make it more physical.

The RT12 gravity norm is already approximately 1 g. A fixed 1.25x or 1.5x
multiplier may recover classifier hits from a force-sensitive model, but it
would turn gravity into 1.25--1.5 g and is rejected as a sensor mapping.

## Acquisition path and the irreducible difference

The exact RT02 image configures the STK8321 for low-power equidistant sampling
with a 10 ms sleep, selects the filtered output with its 1 kHz bandwidth
setting, keeps every fourth XYZ frame in its FIFO, and returns the newest cached
frame on each 25 Hz raw callback. The image never writes `DATASETUP 0x13` in the
STK initialization path, so this is not the public unfiltered/352 Hz mode. The
long controls' near-zero duplicate rate plus every-fourth retention implies
roughly 100 or more source frames/s if the preliminary FIFO definition applies;
it does not establish an exact 100 Hz source clock.

RT12COL V6 configures the LIS2DW12 for 200 Hz, LP2 14-bit mode, +/-4 g and its
widest LP2 bandwidth. The stock reader drains the FIFO and the raw callback
returns the newest frame every 40 ms, so about eight physical samples compete
for each delivered sample. V6 has measured zero consecutive duplicates across
the tested moving capture and lease renewals.

Both front ends pass much more bandwidth than a 25 Hz delivered stream can
represent. A finger snap is consequently sampled by phase: a slightly different
instant can change its peak greatly without changing the movement. No static
3x3 transform or scalar gain can undo that aliasing. The model must learn
amplitude/phase/response variation from shape-preserving augmentation and
multiple sessions; firmware may reduce the mismatch only by changing the
physical acquisition schedule and then re-passing freshness tests.

This also defines what "maps like RT02" can honestly mean. Spatial direction
and physical units can be made equivalent. The delivered time series cannot be
made mathematically identical after the fact because RT02 discards three of
every four source frames inside its FIFO while RT12 V6 stores every source frame
and later selects the newest. Arrival-time interpolation, duplicate deletion or
an inverse filter would invent unobserved motion and is outside the contract.

## Result of the 100 Hz firmware comparison

V7 tested LIS2DW12 `CTRL1=0x51`: 100 Hz, LP2, 14-bit, retaining four fresh
source frames per 25 Hz callback and the V6 SLEEP_ON fix. It passed bounded
freshness with zero consecutive duplicates, so 100 Hz is not a source-
reliability failure. It nevertheless produced only 4/10 and 5/10 snap events in
two short sessions under the unchanged frozen model, versus 12/15 on V6.

The comparison exposed an omitted variable: with `CTRL6=0x10`, V7's digital
cutoff is 50 Hz while V6's is 100 Hz. RT02 uses its wide STK bandwidth setting
before FIFO retention. Matching a guessed source cadence while halving bandwidth
is not a one-to-one source match. Separate-session bootstrap intervals do not
prove V6's modest waveform-correlation advantage is a universal rate effect,
but V7 supplied no evidence to replace V6. The selected firmware baseline is
therefore V6's 200 Hz/wider configuration, with 25 Hz fresh delivery.

Only isolated snaps were recorded on V6/V7. V1's earlier complete 11-class
session is useful historical evidence but cannot qualify V6's changed source.
A single full-vocabulary V6 validation session is still required; it is a
validation set, not a request to retrain the classifier on a new per-ring
corpus.

Directly selecting 25 Hz remains a poor next comparison: independently clocked
25 Hz acquisition and 25 Hz delivery can race, and the widest LIS digital
cutoff would fall to 12.5 Hz. Raising ODR/bandwidth beyond V6 could preserve a
sharper impulse but increases FIFO, CPU, battery and alias/false-positive risk;
it requires a new bounded experiment rather than an inferred conversion.

## Model policy after the adapter

The selected implementation and its candidate/false-positive evidence are
recorded in [GESTURE_MODEL_V2.md](GESTURE_MODEL_V2.md). Its pinned checkpoint is
SHA-256 `1158a0b6c0aaaccbc90ca6352791481aa3a734cc1ac4c75e959ad8588c56d6c7`.

- Preserve shape as the primary evidence. The current model already uses
  peak-normalized waveform channels, a normalized impulse envelope and
  multiscale convolutions.
- Treat peak scale as uncertain evidence, especially for snap and clap. Train
  invariance to plausible strength and sensor-response variation instead of
  correcting a particular session with a gain.
- Keep stroke count and temporal ordering explicit so snap, double-clap and
  flick are not separated by force alone. A double prediction requires at least
  five physical 25 Hz sample intervals (0.20 s) in its movement burst.
- Evaluate RT02 held-out gestures, RT12 held-out sessions, and long ambient/hard
  negatives separately. False positives choose the operating threshold after
  the adapter and model are frozen.
- Do not claim a false-positive rate from a 30-second ambient tail. A one-sided
  rule-of-three bound below one false positive/hour needs more than three clean
  hours at the frozen operating point.

## Sources and local evidence

- [ST LIS2DW12 datasheet](https://www.st.com/resource/en/datasheet/lis2dw12.pdf)
- [ST LIS2DW12 application note AN5038](https://www.st.com/resource/en/application_note/an5038-lis2dw12-alwayson-3axis-accelerometer-stmicroelectronics.pdf)
- [Sensortek MEMS product table](https://www.sensortek.com.tw/index.php/en/products/mems-sensor/)
- [STK8321 manufacturer-datasheet mirror](https://pdf.elecfans.com/p/11204311.html)
- Exact disassembly and physical results: `docs/RT12COL_FIRMWARE.md`
- RT02 duplicate controls:
  `firmware/research/2026-09-27/rt02-duplicate-control/`
- RT12 V6 capture: `data/sessions/prompted_20260927_213001.jsonl`
