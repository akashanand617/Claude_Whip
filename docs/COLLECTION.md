# M1 data collection protocol

Decide these before recording. Every item here is a collection choice, not a
model choice, and each one is cheap now and expensive to discover after four
sessions are in the bag.

**The goal: the only thing the model can learn is the flick itself.** Every other
attribute -- hand posture, windup, amplitude, orientation, session, time of day --
must be uncorrelated with the label, which means deliberately varying it.

---

## What we are controlling for

| Confound | How it bites | Fix |
|---|---|---|
| Demo flicks ≠ real flicks | Trained on calm deliberate gestures, deployed on annoyed sloppy ones | naturalistic sessions, held out |
| Windup leaks into the label | Every flick preceded by the same setup; model learns the setup | vary windup; flicks from ongoing activity |
| Session as oracle | Blocked recording makes ring position / drift / temperature separate the classes for free | interleave classes within every session |
| Gravity shortcut | Flicking posture differs from resting posture; DC orientation alone separates classes | subtract per-window per-axis mean |
| Ring rotation between wearings | Body-frame axes shift; model learns one alignment | finger-axis rotation augmentation; hold out a different-day session |
| Dropped BLE samples | A gap looks like a discontinuity, which looks like a flick onset | include gap-containing rest windows as negatives |
| Clipping | Hard flicks pin at full scale; amplitude stops carrying information | log clip rate per session |
| Marking motion | The keypress/tap that timestamps the gesture is *in* the recording | prompted timing, or mark with the non-ring hand |
| Window-level scoring | One gesture spans ~6 overlapping windows | debounce, then score at event level |
| Balanced test set | Makes the false-positive rate look ~1000x better than reality | evaluate on natural proportions |

---

## Factors to vary

Not a full factorial -- 2 classes x 4 directions x 3 amplitudes x 3 windups x 5
postures is 360 cells and you would need thousands of examples to fill it.

**Randomise instead.** Each prompt draws a combination at random. Over 300
examples per class every factor is marginally balanced, which is what breaks the
correlation with the label. Full crossing is only needed if you want to *measure*
interactions, and you do not.

| Factor | Levels |
|---|---|
| Class | `flag` (single), `approve` (double) |
| Direction | flexion (palm-ward), extension (back), ulnar (pinky-ward), radial (thumb-ward) |
| Amplitude | soft, normal, hard |
| Windup | none (from ongoing motion), minimal, deliberate |
| Posture at onset | on keyboard, on mouse, raised, flat on desk, hanging at side |
| Gesture tempo | brisk, natural, deliberate |

### Measured gesture characteristics (2026-09-08, n=33)

The "two impulses separated by a gap" model was **wrong**, and measuring it
before writing 300 examples saved the protocol.

A flick is not an impulse -- it is an oscillation train lasting ~0.8-1.4 s
including the return to rest, with an internal period of ~120-210 ms.

| | single | double |
|---|---|---|
| duration | 795-1125 ms, median 913 | 480-1395 ms, median 1065 |
| peaks per event | median 2, range 1-4 | median 5, range 2-9 |

**Duration does not separate the classes** -- all six singles fall inside the
double range, and the best duration-only split is 73% accurate. **Oscillation
count does**: a peak-count threshold reaches 85%.

So the discriminator is internal structure, which is what the CNN is for. Those
two numbers are the baselines the model must beat; a classifier that cannot clear
85% is learning nothing a threshold could not.

There is no "gap" to instruct. Standardise the overall tempo instead, and leave
at least 3 s between gestures during prompted collection so events stay separable.

### Open decision: one hand or two

The ring is worn on one hand, and the signal mirrors if you switch. Decide now:

- **One hand** -- half the data, and the model breaks if you ever switch.
- **Both hands** -- doubles the requirement to 300/class/hand.

Recommendation: pick one hand, wear it consistently, and record ~30 examples on
the other hand purely as a documented failure case. If you later switch, you will
know exactly what it costs.

---

## Probe sets

Small deliberate sets, ~30 each, that exist to *measure* a specific confound
rather than train on it. Keep them out of training; score them separately.

| Probe | Tests |
|---|---|
| hard single vs soft double | whether amplitude is being confused with count |
| slow double (~600 ms gap) | receptive-field limit; expect degradation, confirm it is graceful |
| flick from ongoing typing | windup leak |
| flick with ring re-seated 90° | rotation robustness |
| near-miss motions: reaching, mouse click, scratching, adjusting glasses | the hard negatives most likely to fire |

If soft-double reads as `none` and hard-single reads as `approve`, you will see it
here instead of during a labeling session.

---

## Session protocol

**Every session:**

1. Re-seat the ring (rotate it slightly on the finger). Do not preserve alignment
   between sessions -- variation is the point.
2. Record continuously. One capture file per session, gestures marked by
   timestamp. **Never pre-segment.**
3. Interleave classes. Never record 200 `flag` then 200 `approve`.
4. Log ring position, hand, and anything unusual in the session notes.

**Prompted blocks** -- where the volume comes from. Countdown, then a cue naming
the combination ("hard, extension, no windup"). Timestamp comes from the prompt,
so there is no marking motion at all.

**Naturalistic blocks** -- where the honesty comes from. Work normally. Flick when
you actually feel like it. Mark by voice, or with the non-ring hand. Expect far
fewer gestures per hour; that is the point.

**Negative capture** -- wear it and work. Everything unmarked is `none`. Target
4+ hours across sessions, weighted toward activity: typing, mouse, gesturing
while talking, standing, walking, making coffee. Passive reading contributes
almost nothing.

### Target volume

| | Target |
|---|---|
| `flag` | 300+, across 4+ sessions |
| `approve` | 300+, across 4+ sessions |
| negatives | 4+ hours of active wear |
| naturalistic sessions | 2+, at least one held out entirely |
| probe sets | ~30 each, excluded from training |

---

## Per-session acceptance checks

Run before accepting a session. A bad session found now costs an hour; found
after training it costs a week of confusion.

- **Sample rate** -- 25.0 Hz ± 0.2. Print actual timestamp deltas; do not trust
  the nominal rate.
- **Gap statistics** -- median interval, p95, max. Our baseline is 40 ms median,
  ~0.24% implied loss, worst gap ~91 ms. A session much worse than that is
  suspect.
- **Clipping** -- count samples within 1% of ±32767. Full scale is ±4.09 g at
  8005 counts/g, and a hard fingertip flick can plausibly exceed 4 g. If hard
  flicks clip, amplitude stops discriminating above that point.
- **Class balance within session** -- both positive classes present and
  interleaved, not blocked.
- **Marking contamination** -- for hand-marked sessions, confirm the marking
  motion did not land inside a labeled window.

---

## Preprocessing, fixed in both PyTorch and C++

These must match exactly. Add them to the parity vectors.

1. Decode with `signed16_be`, axis order Y, Z, X (bytes 2-3, 4-5, 6-7)
2. **Subtract the per-window per-axis mean** -- removes DC gravity so orientation
   cannot be a shortcut, while leaving dynamic magnitude intact. Do *not*
   normalise by standard deviation: amplitude is a real cue for separating
   deliberate gestures from incidental motion, and dividing it out destroys that.
3. Scale by `1 / COUNTS_PER_G` (8005) so units are g
4. Window: **38 samples** (1.52 s). Defined in samples, not seconds -- 1.5 s at
   25 Hz is 37.5, which is not an integer, and a training/daemon mismatch here is
   a day of debugging.
5. Stride: 6 samples (0.24 s)

## Augmentation, training only

- finger-axis rotation, ±30° (the ring spins about the finger; it does not tumble,
  so arbitrary SO(3) teaches invariance you do not need)
- amplitude scaling, ±30%
- time warp, ±15%
- random window offset, so the gesture appears at every phase
- additive noise at the level measured from stationary captures

**Window labeling near boundaries:** ≥70% of the gesture inside the window is
positive, ≤30% is negative, and **the ambiguous middle is dropped from training**.
Do not force a label onto a window you cannot confidently label. The debouncer
covers the gap, since a real gesture still sits cleanly inside 3-4 of its ~6
overlapping windows.

---

## Evaluation

**Score at the event level, not the window level.** A gesture spans ~6
overlapping windows; window-level F1 counts one gesture six times and is not the
quantity you care about.

1. Debounce: require k-of-n consecutive positive windows
2. A detection within ±0.5 s of a labeled gesture is a true positive
3. Extra detections are false positives; missed gestures are false negatives
4. Report **false positives per hour of natural wear**

**Evaluate on natural proportions.** A balanced test set makes the false-positive
rate look about a thousand times better than deployment.

**Hold out a naturalistic session recorded on a different day.** One holdout
tests three confounds at once: the windup leak, the session oracle, and ring
rotation. Your spec already requires a held-out session -- make it this one.

Gate: F1 ≥ 0.90, **false positives < 1/hour**. The second matters more; a
classifier that fires while you type poisons every downstream label.

---

## Existing data

Already captured, at the deployment rate and firmware:

| Capture | Duration | Use |
|---|---|---|
| `gate_imm4_20260906_210533` | 10.0 min | **worn while typing at 25.00 Hz** -- genuine hard negatives |
| `nolog_after_20260907_191427` | 2.0 min | stationary/handling negatives |
| `postflash_31hz`, `restore_check`, `nop223e` x2 | ~2 min total | short desk negatives |

~14.7 min at 25 Hz usable as-is. Another ~14 min exists at 50 Hz
(`typing_20260906_162156` is 10 min worn typing) and can be decimated 2:1, with
the caveat that dropping every other sample without an anti-alias filter may
introduce artifacts. For negative data that is arguably harmless or even useful,
but keep decimated data tagged so it can be excluded if it causes trouble.

Against a 4-hour negative target this is ~10%, but it is the right 10%: real
typing, real wear, correct rate, correct firmware.

**Not reusable:** anything captured on stock firmware (1 Hz), and the 33 Hz
captures (non-integer resampling ratio).
