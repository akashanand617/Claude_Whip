# Gesture model v2 — physical transfer and shape evidence

Status: selected for the app's offline/simulator build on 2026-09-27. RT12COL
V7 was later physically tested under a separately authorized bounded plan; this
model record does not enable V7 installation or claim right-hand/user
universality.
The sensor contract is frozen in
[GESTURE_SIGNAL_CONTRACT.md](GESTURE_SIGNAL_CONTRACT.md).

## Decision

The RT12COL adapter performs only the transformation established by static
physical poses: `RT12 [x, y, z] -> canonical [x, z, -y]`. This matrix has
determinant `+1`, so it preserves handedness. Both RT02CR's STK8321 and
RT12COL's LIS2DW12 nominally encode +/-4 g as 8192 packet counts/g; the corpus
uses the measured common value of 8005 counts/g. There is no fitted scalar gain,
guessed quantization, timestamp interpolation or classifier-derived calibration.

That makes spatial direction and acceleration units equivalent. It cannot make
the temporal samples identical. RT02 retains every fourth frame from a source
whose exact clock is unresolved (the measured retained freshness implies roughly
100 or more source frames/s if the preliminary FIFO definition applies); RT12
V6 drains a 200 Hz FIFO and returns its newest frame at each 25 Hz callback. The
remaining phase/peak variation is therefore
handled as uncertain model evidence, not disguised as a hardware conversion.

## Selected feature

The ninth input channel is a dimensionless impulse envelope:

```
impulse[t] = norm(a[t] - moving_average(a)[t]) / peak_t(norm(a[t]))
```

It records the movement's force-independent temporal shape, normalized by the
same overall waveform peak as the other shape channels. It is unchanged by a
proper axis rotation or a uniform amplitude change. Existing shape, scale,
saturation and room-frame channels remain; input shape is `[1, 9, 50]`.

Double gestures also require a physical burst duration of at least five 25 Hz
sample intervals (`0.20 s`). This prevents one short shock from becoming a
high-confidence double solely because overlapping classifier windows vote that
way. It does not impose an amplitude threshold and does not affect snaps or
single flicks.

## Candidate evidence

| Candidate | Fixed validation | Fixed test | RT12 valid snaps | Decision |
|---|---:|---:|---:|---|
| Corrected scale baseline | 74/77 | 98/102 | 7/9 | Rejected |
| No scale channel | 75/77 | not selected | 5/9 | Rejected |
| Impulse, seed 0 | 75/77 | 101/102 | 7/9 | Selected |
| Impulse, seed 1 | 73/77 | not selected | 8/9 | Rejected: worse fixed validation |
| Loud-negative x10 | 76/77 | not selected | 3/9 | Rejected: damaged RT12 transfer |

The selected model gets every fixed-test snap (11/11) and double clap (15/15).
Its one fixed-test miss is a right-flick. Validation gets all snaps (8/8) and
10/11 double claps; the other exact error is a right-flick direction confusion.
All 77 validation movements are still detected.

An intentionally difficult experiment held both historical ambient hours out of
training. It produced 22 false events in about 119 minutes at threshold 0.5,
including high-confidence mistakes, proving that threshold inflation is not a
sound fix. With one 59.13-minute ambient session held out, loud-negative training
still produced three short double-clap events. The 0.20-second physical gate
removed all three without changing fixed validation/test results.

Zero observed events in 59.13 minutes is not a demonstrated rate below one per
hour: the one-sided rule-of-three upper bound is about 3.04 events/hour. More
than three independent clean hours are still required at the frozen operating
point. Threshold remains 0.5 because the decoder requires a strict majority of
model votes; changing it did not address the high-confidence failure mode.

## Pinned artifacts

- PyTorch checkpoint: `data/model.pt`
  - SHA-256: `1158a0b6c0aaaccbc90ca6352791481aa3a734cc1ac4c75e959ad8588c56d6c7`
  - exact recipe is embedded in `training_config` (seed 0, 60 epochs,
    0.003 learning rate, 0.001 weight decay, batch 128, frame-spin and named
    channel/augmentation settings).
- Core ML package: `ios/R02Ring/Gesture/GestureClassifier.mlpackage`
  - float32 CPU export with Torch 2.11.0, coremltools 9.0 and NumPy 2.3.4.
  - 1,048 export-replay windows passed with max probability error
    `1.6689300537109375e-6`.
- Extended safety fixture:
  `ios/R02RingTests/Fixtures/gesture-safety-replay.json`
  - all 7,627 split windows passed Python/Core ML parity with maximum error
    `2.086162567138672e-6`.
  - Swift feature/model/full-trace replay: 15/15 targeted tests passed; the
    complete iOS simulator suite passed 87/87 with zero skips, including V6/V7
    changed-byte fingerprint coverage.

The prompted corpus is not a universal hand corpus: its recorded positive
gestures are left-hand data, dominated by index/middle-finger wear. The proper
rotation is a board property and remains valid, but accuracy for another hand,
finger, wearer or gesture style requires independent validation. The adapter
must not be changed to make one such session classify better.

## Completed physical comparison

RT12COL V7 (`CTRL1=0x51`, 100 Hz LP2) was physically deployed and passed its
bounded source-freshness gate with zero consecutive duplicates. It remains an
app recognition-only identity, not an install target. Its two short snap
sessions produced 4/10 and 5/10 frozen-model snap events (plus one double-clap
confusion), compared with 12/15 for V6 under the current checkpoint. V7 also
halves the LIS digital cutoff from V6's 100 Hz to 50 Hz, so it does not isolate
source cadence from response bandwidth and supplied no basis to replace V6.
Health return, steps/sleep continuity and a sufficient ambient false-positive
run remain separate gates.
