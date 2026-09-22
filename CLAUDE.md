# Whip — working notes

Read this before touching the ring or the firmware. It records what has been
measured, what was got wrong along the way, and the traps that cost hours.

Project goal: a smart ring emits a gesture when the model does something the
user dislikes; those gestures become preference data for a LoRA adapter. The
research question is whether preferences baked into weights hold up better than
preferences written into a context file as context fills.

---

## Status

| Milestone | State |
|---|---|
| M0 hardware gate | **PASSED** on `#4`: 25.00 Hz, 0.24% loss, 10 min worn |
| M1 gesture classifier | **COMPLETE (2026-09-21)**: 11 classes (flick x4, double_flick x4, snap, double_clap, wave), room-frame direction, held-out test 95/96 both seeds, 0 ambient events; live engine + web console; next: real-time use |
| M2 calibration corpus | **two layers.** Layer 1 (artifact style) finalized: 60 items, 5 per dimension. Layer 2 (agency / working style, `docs/AGENCY.md`): 11 axes, 28 items, situation-conditioned; `step_size` at a full 2x2, the rest paired exemplars. 88 items total, validated. Planner is layer-scoped |
| M3 labeling session | **tooling built, keypress-primary**: `python -m probe.label run / join / score / aggregate` (`whip/labeling.py`). Ring joined offline from `data/live/events_*.jsonl` as a secondary source. Blocked only on the rule-3 read-through of `corpus/gold/`, then four sessions on different days |
| M4 reward model | **built and tested** (`whip/reward.py`): factored reward, situation-aware direction, judge validation + trust gate. Blocked only on a judge backend |
| M5 LoRA adapter | **datasets built** (`reward.dpo_examples` / `kto_examples` / `split_by_item`); training blocked on a GPU and real labels |
| M6 three-arm eval | **harness built and tested** (`whip/arms.py`): mechanical context file, fill sweep, adherence with bootstrap CIs, per-dimension slopes. `python -m probe.pipeline dryrun` runs the whole chain on fixtures |

**M2–M6 need no ring.** They are the path to the research question. The ring only
ever replaces a keypress in the labeling UI. Do not let hardware work block them.

---

## The ring

| | |
|---|---|
| Model | Colmi R02, advertises as `R02_CC07` (was `COLMI R02_CC07` on stock) |
| MAC | `30:32:41:33:CC:07` |
| Hardware | `RT02CR_V3.1` |
| Firmware now | `RT02CR_3.12.07_260514`, immediate `#4` (`rt02cr-25hz.bin`) |
| Firmware was | `RT02CR_3.12.02_260824` (stock) |
| SoC | BlueX Micro RF03, Cortex-M0 |
| Accelerometer | STK8321 |
| Battery | 17 mAh |

**Name matching:** it advertises `COLMI R02_...`, so `startswith("R02")` misses it.
Use `protocol.looks_like_ring()`, which matches anywhere in the string.

---

## Operational traps

These each cost significant time. Check them before debugging anything else.

**A stale BLE bond on the Mac blocks all connections.** Symptom: the ring
advertises reliably at strong signal, but every connect times out — in `bleak`
*and* in Chrome, with no error either side. Fix: System Settings → Bluetooth →
**forget the device**. Nothing else works. Not Bluetooth toggles, not
`sudo pkill bluetoothd`, not a full restart (the bond is on disk), not charger
taps, not unbinding from QRing.

**A ring can be visible and still "not found".** `BLEDevice.name` is often
`None` while the name lives in the advertisement's `local_name`. Matching on
`device.name` alone missed a ring sitting at -67 dBm, then "worked" on a retry
that happened to populate it -- which reads exactly like a flaky ring.
`find_ring` now matches on `adv.local_name or device.name`, and on the UART
service UUID as a fallback.

**The ring rotates its BLE address.** Chrome's picker showed it twice under one
name, at `30:32:41:33:CC:07` and `53:20:0D:60:4C:8F`, both marked Paired — one
live, one a stale bonded record. From Python this is invisible: CoreBluetooth
collapses both to one identifier and may pick the dead one.

**A healthy connect is slow.** The ring advertises infrequently and negotiates a
slow connection interval, so service discovery across four services takes tens of
seconds. Early 10–30 s timeouts could not distinguish slow from broken.
`CONNECT_TIMEOUT_S` is now 90 s.

**Binding the ring in QRing causes trouble.** Avoid it. If you must, unbind
afterwards *and* forget the device on the Mac.

**The LEDs cannot be turned off while streaming.** See "LED" below. A charger
tap — a few seconds in the case and out — is the only remedy, and it also clears
other stuck states.

---

## Protocol

All commands over the nRF UART service. 16-byte packets: command byte, up to 14
sub-data bytes, checksum = sum of the preceding bytes mod 256.

| Purpose | UUID |
|---|---|
| UART service | `6e40fff0-b5a3-f393-e0a9-e50e24dcca9e` |
| Write | `6e400002-...` |
| Notify | `6e400003-...` |
| DFU service | `de5bf728-d711-4e47-af26-65e3012a5dc7` |
| DFU notify / write | `de5bf729-...` / `de5bf72a-...` |

**Raw sensor:** `A1 04` starts, `A1 02` stops. Notifications are tagged `A1` with
a subtype in byte 1: `0x01` SpO2, `0x02` PPG, `0x03` accelerometer, `0x05`
undocumented and near-static.

**On this firmware `0x04` is the only usable parameter.** Swept `0x01`–`0x0F`;
nothing else streams motion. There is no accel-only mode.

**Accelerometer decode — settled empirically:**

```python
x = int.from_bytes(payload[6:8], "big", signed=True)   # note the axis order
y = int.from_bytes(payload[2:4], "big", signed=True)
z = int.from_bytes(payload[4:6], "big", signed=True)
```

`signed16_be`, **8005 counts per g** (≈ ±4 g full scale). Axis order is Y, Z, X.
One sample per packet; bytes 8–14 are always zero.

The public Edge Impulse implementation decodes this as 12-bit with an incoherent
sign check. It is wrong. Three independent lines of evidence are in
`docs/HARDWARE.md`.

---

## Firmware

### Container (RT02CR, magic `e5c3bd81`)

| Offset | Field |
|---|---|
| `0x000c` | u32 LE sum of every byte from `0x50` to EOF |
| `0x0010` | firmware version string |
| `0x0030` | hardware version string |
| `0x0050` | nested Realtek header |
| `0x0052` | u16 LE control flags; **bit 7 is `not_ready`** |
| `0x0058` | u32 payload length (filesize − `0x450`) |
| `0x01c4` | 32-byte SHA-256 of the payload at `0x450`→EOF |
| `0x0450` | Realtek application payload |

**It is not encrypted.** An earlier conclusion in this repo said it was, inferred
from entropy and a CRC32 that would not verify. Both were wrong — the payload
disassembles as plain ARM Thumb from `0x450`. Never conclude a binary is opaque
without disassembling it.

To build a bootable custom image: patch the payload, refresh the SHA-256, clear
`not_ready`, recompute the body sum **last** (it covers the other two fields),
and transfer with init type `0x04`. `whip/fwbuild.py` does all of this, validated
by reproducing the published low-latency image byte-for-byte.

### The raw motion rate is one byte

`movs rN, #imm` feeding `lsls rN, rN, #3`, at file offset `0x2248`.

**The instruction computes `imm * 8` ms, but the delivered period is
`imm * 10` ms.** Measured at three points, so predict from the measurement, not
the arithmetic -- the instruction is 25% optimistic. Where the extra 25% comes
from is not established: a slower timer tick, or scheduling overhead between the
timer firing and the notification going out.

| Immediate | Measured rate | Loss | |
|---|---|---|---|
| `#125` | 1.00 Hz | 0.00% | stock, with a 1114 ms hole |
| `#2` | 50.00 Hz | 25.94% | published low-latency; bimodal arrivals |
| `#3` | 33.33 Hz | 2.99% | more headroom, fails the loss bar |
| `#4` | **25.00 Hz** | **0.24%** | **currently flashed, passes M0** |

`#3` is the operating point. `#2` produces faster than BLE delivers -- 61% of
intervals at one period and 33% at double it, the signature of dropped samples.
`#3` and `#4` are unimodal with jitter only. `probe/build.py` locates the timer
site by period rather than a hard-coded address.

**`#4` is the operating point.** Over 10 minutes worn: exactly 25.00 Hz
(15000 packets in 600 s) and 0.24% loss. An earlier 60 s capture read 24.98,
which was a window-boundary artifact -- the period is a firmware constant, so
the rate does not drift.

Loss does not scale with rate the way you would expect. `#3` at 33 Hz loses
2.99% worn; `#4` at 25 Hz loses 0.24%, ten times better for a 25% rate cut.
Producing under what the link comfortably carries stops the notify queue
thrashing rather than merely reducing it.

Loss also tracks **motion**, not the link: still chunks read 0.1-0.2%, moving
chunks up to 6%. A loss figure is partly a statement about how much the wearer
moved.

### The accelerometer range is one byte too

`write_register(0x0F, 0x05)` at **file offset `0x00bf0a`** -- `RANGESEL` set to
±4 g, which is why counts-per-g measures 8005.

Found by `probe/accelrange.py`, structurally rather than by hunting immediates:
counting occurrences of `0x0F` gives 141 sites and settles nothing, and many are
`movs r1,#0x0f; mov r0,sp; bl`, a 15-byte buffer length. What works is finding a
*run* of `movs rA,#x; movs rB,#y; bl helper` triples sharing one call target --
a peripheral init -- which needs no load base. The decisive anchor is
`write(0x14, 0xB6)`, the documented STK832x soft reset. The same helper writes
`POWMODE2`, `BWSEL`, `FIFO_CONFIG`, `SWRST`, then the range.

`0x08` would give ±8 g and recover the top fifth of the amplitude information
now lost to clipping (gesture peaks reach 6-7 g against a ±4.09 g rail).

**The cost is not the flash.** Changing the range changes counts-per-g, so
`accel.COUNTS_PER_G`, every amplitude threshold derived from it, and the
comparability of the entire recorded corpus all go with it. That is a decision
about re-recording. Not patched, not flashed.

Two disassembly traps, both of which produced "nothing found": linear
disassembly from byte zero yields nothing because the container header is not
instructions and capstone stops at the first thing it cannot decode -- start at
`0x450` and resync past data islands. And in a test fixture, a BL with a constant
delta sends every call to a *different* absolute target, so the grouping never
fires.

**Never patch `0x007ed4`.** It carries the identical timer idiom but belongs to
DFU frame reassembly; lowering it can break OTA recovery. It is excluded via
`fwimage.DO_NOT_PATCH`.

### DFU

Frame: `BC | cmd | len_lo | len_hi | crc16_lo | crc16_hi | payload`. CRC-16/Modbus
over the payload. Commands: START `0x01`, INIT `0x02`, DATA `0x03`, CHECK `0x04`,
END `0x05`. 1024-byte chunks, 240-byte BLE segments, init type `0x04`.

**The ring never acknowledges END** — it reboots to apply the image. CHECK is the
frame that confirms receipt. Treating END's silence as failure reported a
successful flash as ABORTED.

---

## Measurements

**M0 gate:**

| | Stock `#125` | Low-latency `#2` | **Custom `#3`** |
|---|---|---|---|
| Rate | 1.00 Hz | 50.00 Hz | **33.33 Hz** |
| Interval median | 1023 ms | 16.99 ms | 30.00 ms |
| Interval mean | — | 20.00 ms | 29.99 ms |
| Jitter | 77 ms | 6.99 ms | **4.51 ms** |
| Gap max | 1114 ms | 74 ms | 60 ms |
| Windows with a stall | — | 0 of 400 | 0 of 40 |
| Implied loss | 0.00% | 25.94% | **1.96%** |
| Gate | FAIL | rate only | **PASS** |

**The 25.94% at `#2` was real dropping, not a metric artifact.** The interval
histogram is bimodal — 61% at one period, 33% at exactly double — which is what
missed samples look like. At `#3` the distribution is unimodal and median equals
mean, and the loss falls to 1.96%.

Worth keeping in mind: stock scored **0.00% loss while containing a 1114 ms
hole**. A perfect score on a useless stream. Rate and loss together, plus the
gap distribution, are what actually characterise a capture.

**Battery, measured on three images:**

| Image | Rate | Drain | Projected runtime |
|---|---|---|---|
| `#2` | 50 Hz | 1.0 %/min | ~1.7 h |
| `#3` | 33 Hz | 0.27 %/min | ~6.3 h |
| `#4` | 25 Hz | 0.30 %/min | ~5.5 h |

**Drain is not dominated by the packet rate.** Going 50 → 33 Hz gave a 3.7x
improvement, far more than the rate ratio, because it stopped the retransmission
churn. Going 33 → 25 Hz changed nothing measurable. So the remaining cost is the
LEDs and holding the BLE link, and **no rate choice unlocks Phase B** -- ~6 h is
the ceiling until the emitters can be turned off. Phase A (1 h session) has
ample margin.

---

## LED

Green and red are the PPG and SpO2 emitters. They light whenever `A1 04` runs
and cannot be turned off:

- the realtime stop commands (`69 01 04`, `6a 01 00 00`, `6a 03 00 00`) do
  nothing, sent during streaming or after it
- **no command lights them either** — `69 01 01` (start HR) produced no LED at
  all, so they are not driven by the health-command path
- no `A1` parameter streams motion without them

### Everything ruled out, with evidence

**Protocol: exhausted.**

- Periodic HR logging (`16 02 02 3c`) was **already disabled** before we sent
  anything -- confirmed by read-back (`16 01`) -- and the LEDs flicker anyway.
- SpO2 (`0x2c`), stress (`0x36`), `0x38` all read zero; `0x37`/`0x39` unsupported.
- Realtime stop commands (`69`/`6a`) do nothing, sent before, during or after.
- All 15 `A1` parameters light them; none streams motion alone.
- Sending the logging disable *before* `A1 04` darkens the ring but the
  accelerometer never starts -- one packet in three minutes. The only dark state
  is the one with no data.

**Not a regression from the mod.** Stock `RT02CR_3.12.02` was flashed back and
streamed for three minutes: **it flickers too**, while emitting spo2, ppg, accel
and `0x05` at 1 Hz each. The optical sensor was always sampling; the low-latency
build only suppresses the *reports*. All three of upstream's NOPs remove calls to
one function, `bl #0x7e30`, the notification send -- no power-down instruction
was dropped.

So `A1 04` means "power the whole sensor front end" on every firmware, and the
emitters are inseparable from the accelerometer at the protocol level.

**Firmware: attempted and not cracked.** The call graph reachable from the A1
handler is ~5100 call sites, far past blind bisection. Following the raw-sampling
timer callback needs the image's load base, and solving for it failed -- the best
candidate put only 49 of 206 function pointers on a prologue, with the top six
scoring within noise across a 100 KB spread. Position-dependent code, no symbols,
no memory map, and validation only by flashing and looking at the ring.

**If revisiting:** ask the upstream author. Nosh118 found the timer immediate,
the three send sites, the connection-parameter call and the Realtek activation
sequence in this exact image. One question could replace days of work.

---

## The gesture platform

The CNN is a **general gesture classifier**; the Whip app consumes only the
gestures it maps to actions. One vocabulary, declared in `whip/registry.py`:
flick, double_flick, snap, double_snap, double_clap (impulsive), wave, clap
(sustained).
Classes materialise from data -- the exporter emits only classes with windows
and prints the declared-but-absent ones. Legacy names on disk (`flag`,
`approve`, `waving`, `snapping`, `clapping`) map in via aliases.

**Two labelling modes, decided by the mark's shape.** Point marks (prompted
gestures) keep the coverage rule. Span marks (20 s "keep waving" blocks) label
windows fully inside the span, with a 0.5 g hygiene floor so pauses inside a
span stay `none` -- the label source is the human cue; amplitude only gates
whether the cued motion was happening at that moment. Unrecognised motions
('dismissive flick', 'so-so wobble') stay attribution-only **negatives**:
promoting every cued motion to a class would silently convert hard negatives
into positives. `snapping` IS promoted, deliberately -- the model learns the
snap/flick boundary explicitly.

**Event policies are per gesture.** Impulsive keeps the 3-14 run band.
Sustained fires once at min_run with **no upper bound** -- `max_run` exists to
reject sustained motion, so a bounded wave is unfirable by construction -- plus
a refractory measured from run end, so a mid-wave dip cannot split one wave
into two. Judgement happens exactly once per run. Batch `events.detect` is a
loop over the incremental `RunTracker`; the realtime engine feeds the same
tracker, so live and offline are one implementation.

**Direction: what it physically is, measured** (`probe/directions.py`). In the
ring's frame ALL FOUR directions rotate about one shared axis (unsigned axis
angles 4-17 degrees in every session). An earlier sentence here said `up` was
"the opposite sense, 119-153 degrees away" from the other three; that came
from the gravity-track sense estimator, which re-measured is a coin flip for
every direction but `down` (same-sense agreement 31-69%), so it cannot assign
sense at all and that claim is withdrawn. Sense measured on the full-band
shape channels instead (signed area swept in the plane perpendicular to the
finger) IS consistent: `down` and `right` share one sign (90-100%), `left`
the other (87-98%), and `up` shares `left`'s sign but weakly (66-80% in the
training sessions, 47% -- a coin flip -- in the reference session). So the
same-sense pairs are up/left and down/right, exactly the pairs the models
confuse. What separates the palm-down pair from the hand-vertical pair is
POSTURE: the gravity vector during the gesture differs by 47-58 degrees
between the pairs and 3-15 within them. Between days each posture cluster
moves 23-55 degrees, the same order as the pair separation, yet the pair
assignment survives -- nearest s1+s2 centroid put 100% of the reference
session's up/down windows in the palm-down pair and 91%/79% of left/right in
the hand-vertical pair. Every direction is a repeatable motion -- unsigned
axis consistency 0.88-1.00 in all three prompted sessions -- and `up` is the
least stereotyped: soft, broader, and its waveform changes most between days.

Two earlier claims in this file were wrong and are withdrawn: the ring did not
sit "60 degrees rotated" between sessions (rest gravity in the finger-
perpendicular plane differs by ~15 degrees; hand PITCH differs by ~50 -- the
60 came from averaging rotation axes across directions that rotate about
different axes); and `up` was never "random" (signed consistency 0.06 was the
rotation-SENSE estimator flipping sign; unsigned it is 0.97).

**Why the first direction models permuted** (down->right, up->left): trained on
ONE session, they could only see the sense of the flexion, because posture --
the per-window gravity vector -- was subtracted before the model saw anything.
Same-sense/different-posture pairs were indistinguishable by construction.

**Fixed by data first, posture second.** Trained on two sessions and tested on
a fresh 32-gesture session: direction 93% with the plain channels, 96% with the
`posture` channel group (the window's unit gravity vector, export v5 keeps it),
recall 88-91% on both seeds. Direction-split classes (`split_by_direction`)
and the direction head both exist; the head's loss is still off (it cost ~10
recall points when trained on 264 gestures). `invariant` channels (|a|,
along-finger, perpendicular magnitude) are exactly spin-invariant and exist for
gesture TYPE; with posture they scored worse for direction (81%), as expected.

**The physically right direction feature is gravity-referenced, not the
ring frame** (`gref` channel group, 2026-09-15). Up/left and down/right are
the same wrist motion at a different forearm roll, so in the ring frame the
waveforms are identical and only gravity's position differs. Resolving the
impulsive acceleration ALONG gravity and PERPENDICULAR to it turns that into
a relation between a and g measured in one frame -- invariant to how the
ring sits and to which way its axes point (test: rotating window and gravity
together leaves it unchanged). Hand-computed, no training: the fraction of
impulsive energy along g is 0.49-0.69 for up/down and 0.10-0.16 for
left/right in all three sessions, and ONE fixed cut separates the pairs for
95% of 296 gestures across three days. Within a pair, left/right is the
rotation sense (swept area sign, 88-100% consistent); up/down sense is the
weak link (down 94-100%, up 66-80%, and 47% in the reference session).
Trained (`shape,scale,saturation,gref`, sessions 1+2, reference held out,
2 seeds): every up gesture right (8/8 both seeds, vs 5-6/8 without), recall
93.8% both seeds (CI 84-100), and ambient false positives LOWER than the
plain channels at every threshold (0.03-0.13/min at thr 0.4 vs 0.27-0.30;
0.00-0.03 at 0.9 vs 0.07) -- the opposite of `posture`, which raised them.
The remaining misses are the same two uneven doubles read as singles and
one or two soft (1.8-1.9 g) double_flick_right read as left. ONE reference
session and 30 ambient minutes: not yet the default, re-measure on the next
session before promoting it.

**Every cued gesture is audited from its own stream and gets a verdict**
(`python -m probe.audit <session> --write`; `notebooks/data_quality.ipynb`
has the full analysis, 2026-09-15). valid / suspect (kept, listed) /
invalid (dropped: `dataset` treats every window touching it as ambiguous,
`probe.rollout` does not score it). **The double flick is DEFINED as a
range**: two strokes 0.20-0.50 s apart, second peak 0.5-2.0x the first
(corpus p5-p95 0.22-0.46 s and 0.70-1.66, with margin). A "double" with a
pause is a different gesture, not a tempo. The two doubles every held-out
model missed are exactly that (spacing 0.51 and 0.68 s), and the audit finds
them from the stream alone, before any model. Direction is checked against
gravity: one fixed cut on the impulsive-energy-along-g fraction puts 96.3%
of 296 gestures in the cued vertical/horizontal pair, no training.

The corpus, audited: 296 gestures -- 255 valid, 29 suspect, 12 invalid
(86.1% clean). Invalid: 5 doubles with a pause, 3 with a stroke ratio
outside range, 3 doubles with one stroke, 1 with no motion (session 1 #190,
0.7 g). Suspect is uncertain rather than wrong (a single whose recoil is 70%
of its stroke, a soft cue done hard, motion just across the pair cut).
**Only valid trains and scores** (`audit.EXCLUDED_VERDICTS`, decided
2026-09-15): uncertain data is dropped and made up next session, not trained
on -- including a correct gesture whose prompt word was not followed. A
shape review of all 29 suspect gestures added two hard rules: peak under
1.5 g is `WEAK` and onset after 0.6 s is `LATE_ONSET` (both invalid; every
gesture they catch was a smear or a non-response). The make-up list is 44
gestures (`probe.audit` prints it per session as "to re-record";
`scripts/rerun.sh` runs audit -> export -> train -> rollout, and with
`--notebook` the experiments and `notebooks/data_quality.ipynb` too). Stroke COUNT is never a hard check: at 25 Hz a recoil and a
weak second tap are the same size, and 27 of 100 singles would otherwise be
flagged. Synthesising slow/unequal doubles from pairs of singles was tried
and is net zero: it recovers the two misses and loses the same number of
recoil-heavy singles, with more ambient false positives.

Protocol facts from the audit: the amplitude prompt is followed (soft
2.3-3.8 g vs hard 4.7-5.7 g medians); the "brisk/deliberate" tempo prompt
changed NOTHING in any session (stroke spacing medians 0.29-0.39 s for every
word) and should be dropped; a fifth of gestures start before the cue
(predictable schedule); nothing starts after 1.0 s.

What the exclusion costs, measured (`shape,scale,saturation,gref`, sessions
1+2, reference held out, 2 seeds, scored on the 21 valid reference
gestures): trained on valid only, 19-20/21 exact class and 21/21 type at
thr 0.4-0.6, ambient false positives 0.20-0.27/min at 0.4 and 0.00-0.03 at
0.9. Trained on everything: the same 19-20/21 and 21/21, ambient 0.07/min
at 0.4. Recall is a tie; the suspect boundary cases were buying
low-threshold false-positive margin, which the next session's clean
examples have to replace. Both remaining misses are one soft (1.9 g)
double_flick_right read as double_flick_left: right type, wrong sense.
Learning curve over 57-231 valid training gestures: gesture TYPE is 20-21/21
from 115 on; exact class is 19-20/21 at every size, so more of the SAME two
days is not the lever -- new days are. Days matter more than
gestures (posture and the up waveform moved more between days than within
one), so the ask is sessions: 4-5 training days of 64 audited gestures, a
never-trained demonstration set of >= 100 gestures on >= 2 further days
(observed 97% on 100 bounds recall above 91%; on 28 it bounds nothing above
84%), 3 days x 3 spans per sustained class plus snap/double_snap sets, and
180+ ambient minutes across >= 2 days.

**The ring can go on either way round, and the model must not care**
(2026-09-15 evening). The fill session and the second ambient hour were
recorded with the ring turned around: the along-finger gravity component
was positive in 93-97% of 2 s chunks, negative in 0-47% of every earlier
session. The deployed model scored 0/44 exact on that session; rotating
the recorded frame a half-turn about the ring's perpendicular axis gave
37/44. The audit cannot see this (its measures are frame-invariant) --
`probe.checkup`/the collector should report the along-finger gravity sign
so a flipped ring is noticed at recording time. Fix in the model, not the
protocol: `probe.train --frame-aug flips` (default) rotates each training
batch by a random proper half-turn of the frame, window and gravity
together, so every channel group sees one consistent frame and rotation
sense survives. Held out, as recorded, 2 seeds: 37-38/44 exact (21/22 of
the valid ones, every hit with the right direction), ambient 0.00-0.03/min
at thr 0.4; without flips 0-3/44. The same session also shows the posture
protocol drifting: down, left and right were done in ONE hand posture
(rest gravity 2 degrees apart) and only up differed, so 18 of 44 gestures
fail the vertical/horizontal pair check -- that is the wearer, not the
ring, and it is why the pair check stays a flag rather than a hard rule.

**"Left" and "right" are wrist motions, not room directions** (posture x
direction matrix, `probe.collect --matrix`, 2026-09-16: 12 hard single
flicks, every hand orientation but palm-down, all audit-valid). The
vertical/horizontal pair from gravity held in EVERY posture (up/down 0.45-
0.74 along g, left/right 0.02-0.21) and the model called up and down right
in all three postures. Left/right were right with the palm facing right
(the posture every training session used for them), one of two right with
the palm facing left, and BOTH SWAPPED with the palm up. That is what the
training data taught: "left" is the wrist motion that moves a
palm-right hand left. Room-left needs the palm's facing, and the frame
flips that make the model orientation-proof deliberately erase which way
the ring is on -- so room-left versus room-right is not recoverable from
the ring alone once the palm may face up or down. The decision is a
definition: either the horizontal gestures are wrist-relative (toward the
thumb / toward the little finger; the ring senses that unambiguously in any
posture) or they require the hand-vertical posture. **Decided the same day: room frame.** Every direction is the
direction the hand moved in the room, in any posture. That needs the one
bit the flips erased -- which way the finger axis points -- so: the `room`
channel group (along gravity, lateral = gravity x finger, forward; signed),
`--frame-aug spin` (full spin about the finger, no front-to-back flip), and
a **wear rule: the ring goes on the same way round every time.** A session
worn back to front is not thrown away: `<session>.frame.json`
(`audit.set_frame`) names the half-turn and the exporter rotates the stream
into the canonical frame. Which way a session was worn is measured, not
eyeballed -- the static along-finger gravity sign is posture-confounded
(the 22-gesture fill read 65% positive and was the right way round) -- by
scoring it under the four rotations with a room model trained on
known-canonical sessions: last night's 44-gesture session 19/22 flipped vs
12/22 as recorded, so it and the ambient hour from the same wearing are
corrected; every session since is canonical. Matrix session held out, room
model: 8/12, and the palm-up left/right that the wrist-frame model swapped
are both right. The corpus has no horizontal flicks outside the
hand-vertical posture; `probe.collect --matrix --reps 3` (and with
`--gestures flick,double_flick`) is the recording that fills that.

**The finger is ring axis 1, not axis 0 -- measured, and it mattered.**
The flick's ROTATION axis is axis 0, which was read as "axis 0 runs along
the finger". A wrist flick rotates about the palm normal, not about the
finger. Resting gravity in three known palm orientations (`--matrix`)
settles it: palm up puts gravity on axis 0 (palm normal), palm left/right
on -/+ axis 2 (thumb-pinky line), so the finger is axis 1
(`model.FINGER_AXIS`). With the wrong axis, gravity x finger was
near-degenerate in every palm-down window and the room channel carried
nothing. With the right one the hand-computed rule -- sign of the first
stroke along gravity (up/down) or along gravity x finger (left/right) --
gives the cued direction in all 12 matrix cells and 25-39 vs 1-8 per
training session, no model. The same rule reads which way round the ring
was worn (`audit.hand_rule`, canonical = sensor-below: left negative);
every session's frame file comes from it, `probe.audit --auto-frame`
writes it for new sessions. Room model, matrix held out: **11/12** (palm
right 4/4, palm left 4/4, palm up 3/4 with one no-fire) from a model that
never saw a horizontal flick outside the hand-vertical posture.

**Full matrix, 48 flicks in four palm orientations, held out** (2026-09-16,
`prompted_20260916_040358`, 41 valid; one skipped cue, six up/down done
sideways enough to fail the pair check): room models trained on nothing
from that posture set, thr 0.4, seed 0 39/41 and seed 1 34/41; at thr 0.9
34 and 29. Every miss but one is a NO-FIRE, not a wrong direction --
direction was right in 79 of the 80 calls that fired, in all four
orientations. The no-fires cluster in palm-up, which no training data
covered. The room frame delivers direction as derived; firing confidence
in an unseen posture is the data-limited part, and that session now trains.

**A snap is a glitch-shaped event, and the despiker was eating it**
(2026-09-16, `prompted_20260916_044426`: 37 each of snap, double_snap,
clap, double_clap in blocks, then one 60 s wave). At the ring a finger snap
is a 1-2 sample shock at 5-7 g -- the width of the BLE glitches the Hampel
filter exists to remove -- and it removed them: median snap peak 5.8 g raw,
1.1 g filtered, 24 of 37 audited as no motion. Both filters now replace
only an ISOLATED outlier (both neighbours within the centre's threshold).
Kept: snap 73% above 1.5 g, double_snap 86%, claps all. Cost: ambient
windows above 3 g rise ~40% (68 -> 94/hour, 225 -> 359/hour); they are real
desk shocks and are the natural hard negatives for a snap class. A clap is
wider (3-4 samples, with recoil) and never had the problem. After the
change the session audits 95 valid: snap 28, double_snap 13, clap 34,
double_clap 20 (doubles lose to the ratio/one-stroke rules when the
despiker still takes a one-sample second spike), plus 242 wave windows.
Single snap remains the marginal class: 1-2 samples at 25 Hz is the same
signature as a desk tap, and ambient wear has ~100 of those an hour.

**One fixed split BY GESTURE, decided 2026-09-16; leave-one-out and the
by-session split are both retired.** Sessions are lopsided in size, one
session holds whole classes, and the deployed model trains on every day
anyway -- so every valid cued gesture is dealt to train / val / test at
random, stratified by class, seed fixed in `data/split.json` (65/15/20;
`probe.split make` writes `data/split/{train,val,test,trainval}.npz`). A
gesture's windows go with it; consecutive gestures' intervals meet midway
between cues and any window straddling a boundary is dropped (the 88%
overlap leak, closed by construction; ~16% of windows). The non-gesture
timeline of every recording, ambient hours included, is dealt in 20 s
chunks the same way, so the false-positive rate is measured on pieces of
every negative recording. Val chooses threshold and seed; test is scored
once per model and never tuned on; the deployed checkpoint trains on
train + val. Earlier by-session numbers (77/97 on a 3-session hold-out;
adding the snap/clap session cost the posture fold 40 -> 24 of 41) are
superseded and kept only as the record of why.

**First scores under the gesture split** (train-only models, 2 seeds; val
69 gestures, test 90; ambient = the val/test chunks of every negative
recording, ~19 and ~26 min):

| thr | val exact | val ambient /h | test exact | test type | test ambient /h |
|---|---|---|---|---|---|
| 0.4 | 63, 62 / 69 | 6.3, 15.9 | 85, 84 / 90 | 86, 84 | 7.0, 4.6 |
| 0.7 | 62, 61 / 69 | 0.0, 3.2 | 81, 83 / 90 | 82, 83 | 4.7, 0.0 |
| 0.9 | 62, 60 / 69 | 3.3, 6.4 | 78, 78 / 90 | 79, 78 | 2.3, 2.3 |

Threshold 0.7 is the operating point chosen on val. On test at 0.4, seed
0: every single flick 40/40, doubles 28/30, snap 5/6, clap 7/7,
double_clap 4/4, double_snap 1/3; every miss but one is a no-fire, the
one direction error is double_flick_right -> left. The gesture interval
must hold every window that carries the label (cue-1.4 .. cue+2.85); the
first bounds kept 3 of 10 and scored 4/69.

**Left/right is a ~95% physical rule, not a proof, and the model beats it**
(2026-09-16). Every hand-computable estimator of a horizontal flick's
lateral sign was scored on all 186 valid left/right flicks and doubles in
the room frame: velocity extremum over the first 0.6 s 94.6%, first five
samples 89.2%, first-lobe integral 52.7%, sign at peak 55.4%, largest lobe
66.7%. So the first-stroke sign that the derivation rests on is right for
about 19 in 20 gestures; the rest begin with a windup or a recoil-first
pattern and the sign of the initial lateral acceleration is the wrong way
round. The CNN, which sees the whole window, confused left and right 3
times in 236 held-out scores (98.7%). The frame makes the pair (vertical
vs horizontal) exact and makes the sign LEARNABLE in any posture; it does
not make it foolproof, and nothing about a 25 Hz accelerometer on one
finger can. What would close the last percent is not a rule but more
horizontal flicks recorded across postures (the matrix sessions).

**Scores on the raw stream, gesture split, thr 0.7 chosen on val** (train-
only models, 2 seeds; val 78 gestures, test 103; ambient = val/test chunks
of every negative recording, ~19 and ~25 min): val exact 69 and 72 of 78,
test exact 94 and 92 of 103 (91%, 89%), type 97 and 94; **ambient 0 events
in every part for both seeds at thr 0.4-0.9**. Test misses: 5-6 no-fires
(double_flick_down 2, flick_right 1-2, clap 1-2), and the shock classes
mixing among themselves (double_snap <-> double_clap, clap -> snap); zero
left/right confusions on test, one flick_up -> left on val. Against the
filtered stream the same split gave 81-83/103 and 0-5 ambient events/h.
Corpus after the raw re-audit: snap 43, double_snap 40, clap 37,
double_clap 29, flicks 37-57 per class; 17 short of level.

**Ablations on the gesture split, 2026-09-20** (`notebooks/experiments/
ablate.py`, test exact of 103, threshold 0.7 chosen on val, ambient 0
events in every run): baseline 94, 92, 93 (3 seeds). Shock-class data
curve: a third of the snap/clap gestures 86, 80; two thirds 92, 91; all
92-94 -- still rising, the shock classes are data-limited. 120 epochs 94,
96. Adding the raw gravity-swing channel 97, 94, 93. Both together 90, 96,
95 -- no better than either alone; seed spread (+/-3) is as big as any
single change. Balancing classes by subsetting the flicks to 19 each:
92, 94 -- a tie, imbalance is not the problem. Without the room channels
gesture TYPE is best of all (98, 99) but direction falls (91, 89): the
room frame buys direction at a small cost in firing confidence. Event
policy: a 2-window minimum run would add 2-3 shock-class hits and zero
ambient events; the no-fires mostly have a correct-class run of 0-2
windows. Window-level confusion inside the shock group is small (snap 95-
98% itself, double_snap 73-83% with 10% to double_clap and snap, clap
66-84% with up to 19% none, double_clap 89%). Conclusion: recall is at
89-94% with the remaining loss in the shock classes; the levers that
showed are more shock-class data (the curve has not flattened) and
possibly min_run 2; channels and epochs are within noise.

**Shock classes levelled to 47-66 (2026-09-21), and the double clap got its
own definition.** A double clap at the ring is one clap landing squarely
(5-7 g) and one glancing (1.5-2.5 g), 0.2-0.45 s apart, either order;
the flick ranges rejected 16 of 21. `GestureSpec` now carries
double_gap_s / double_ratio / stroke_ratio_floor per gesture. After the
fill: snap 50, double_snap 50, clap 47, double_clap 66. Test (115
gestures, 2 seeds, thr 0.7): exact 108 and 107 (94%, 93%), type 108,
ambient 0; snap 10/10 and 9/10, double_snap 9/10, clap 7/9, double_clap
12/13 and 13/13. Val 74 and 72 of 89, weaker on clap (3/7 both seeds:
no-fires) and double_snap (5/8). Every remaining miss but one is a
no-fire; the one confusion is double_clap -> double_snap.

**Root causes of the val misses, traced gesture by gesture (2026-09-21).**
Two were the SCORER, not the model: (1) the split's wholly-inside rule
stripped a gesture's later windows when its neighbour was in the same
part (fixed: same-part straddlers are kept); (2) scoring on a part's
windows alone cut runs at boundary zones (fixed: the whole session
stream is run, only the part's gestures are counted). Same checkpoints,
val 74/72 -> 78/75 of 89, test 108/107 -> 110/110 of 115 (95.7%),
ambient 0. What remains, per gesture: (a) four soft shock gestures at
1.5-2.2 g called `none` by both seeds -- at the WEAK floor, marginal by
construction; (b) five hard shock gestures read as the other family
(clap -> snap, double_clap -> double_snap at p 1.0, double_snap -> clap):
a 5-fold random forest on 12 hand features separates the snap family
from the clap family at only 89.7% (width 2 vs 3 samples is the main
cue), so part of that confusion is the sensor, not the model; (c) two or
three mid-run confidence dips to 0.5-0.6 at thr 0.7, which thr 0.5
recovers (val 80/76, test 111/115) with ambient still 0; min_run 2
changes nothing. Ambient was never the val problem.

**Vocabulary settled 2026-09-21: snap and double_clap.** The sensor cannot
tell a snap from a clap (both a 2-3 sample shock; hand features 89.7%),
so the kept pair differs by COUNT, never by width alone. `double_snap`
and single `clap` are retired in the registry; their recordings stay and
export as unlabelled negatives. Live threshold 0.5. Retrained on the
11-class vocabulary (2 seeds, thr 0.5): **test 95/96 both seeds, every
flick class 100%, snap 10/10, double_clap 12/13, ambient 0**; val 69 and
68 of 74, the misses being two soft flick_ups and two or three double
claps called `none`, and one double_flick_up read as flick_up.

**Training recipe.** Default channels `shape,scale,saturation,room`,
direction head off, flicks direction-split, frame spin on (no flips),
despike OFF, threshold 0.5, wear rule: sensor below the finger, same way
round; the audit checks. Isolated one factor at a time on session 2
(2 seeds): 3-class old recipe 63.3%; 6-class costs ~5 (58.6%); saturation
buys it back (65.6%); direction head at 0.3 drops it to 55.5%. On the fresh
reference session (32 gestures, trained on sessions 1+2, 2 seeds), all of
unsplit / split / +posture tie on recall at 88-94% (thr 0.4) and ~85-88%
(thr 0.9); the split is free and yields direction, and `posture` raised
low-threshold ambient false positives in every arm (unsplit+posture worst:
0.53-0.80/min at thr 0.4 vs 0.30-0.37 without), so it stays off by default.
Session 2 is the hard session -- 76.6% recall even trained on session 1 + the
reference -- recorded at 1 a.m. at a ~50-degree different hand pitch.

**What "satisfactory" currently means, honestly.** Recall: 19-20 of 21
valid gestures on ONE held-out session (both misses one soft
double_flick_right read as left). False positives, MEASURED for the first
time on two held-out ambient hours (2026-09-15, 119 min, a model trained on
no ambient hour): hour 1 (1 a.m., vigorous) 8/h at thr 0.4, 4/h at 0.9,
3/h at 0.95; hour 2 (evening) 4.1/h at 0.4, 1/h at 0.9 and 0.95. The
deployed checkpoint (trained on hour 1, hour 2 held out): 4.1/h at 0.4,
1/h at 0.8-0.9 (a `clap`, unmapped), 0 at 0.95; zero mapped flag/approve
events in 59 min at thr 0.9, which bounds that rate at 3/h. The rollout's
calibrated threshold on hour 2 is 0.93. So at the deployed operating point
the ambient rate is about 1/h all-classes and bounded at 3/h for mapped
actions -- not yet demonstrated below 1/h, which needs the third hour.

**Realtime engine** (`whip/realtime.py`): decode -> `StreamingHampel` (fixed
120 ms lag; same maths as batch, running MAD floor because a stream has no
future -- and the floor must NOT be a constant, it varies 10x across sessions)
-> 50-window at stride 6 with dataset-identical centring -> the checkpoint's
channels -> forward -> threshold -> RunTracker. The parity test demands
identical events from the engine and the offline chain on the same samples.
Latency ~1.3 s for impulsive gestures, stated in the UI. Events + resolved
actions land in `data/live/events_*.jsonl` -- the artifact M2 consumes.
`data/app_config.json` maps gestures to actions (`flick`->flag,
`double_flick`->approve by default; `flick:up`-style keys win over bare names).

**Ring console** (`python -m probe.serve` -> http://127.0.0.1:8642): live
waveform/probabilities/events, settings, and stock <-> gesture flashing with
every refuse-by-default gate from `whip/flashing.py` (shared with the CLI so no
frontend can skip one) plus: state machine forbids flashing while streaming, a
server-enforced dry-run must pass per connection (HTTP 412), and the typed
FLASH word. After a flash the ring reboots and the manager settles to idle.
`probe/live.py` is the same engine headless.

**Checkpoints are self-describing**: labels, channels, direction_names,
direction_trained, trained_on. Consumers read the vocabulary from the file;
adding a gesture = record (`probe.collect --gestures snap,double_snap` or
`--cues` for sustained), re-export, retrain. No code edits.

The C++ daemon remains the eventual spec deliverable; the Python engine is the
reference implementation it must reproduce (numpy-only preprocessing on
purpose).

## M1 design decisions

Architecture is an InceptionTime-style 1D CNN, ~226k parameters, on 50-sample
windows (2.0 s at 25 Hz). Input is **four** channels, not three: see "shape and
scale" below.

```
InceptionBlock(4->128)    parallel k=9,19,39 + maxpool branch, 1x1 bottleneck
InceptionBlock(128->128)
InceptionBlock(128->128)  + residual 1x1 shortcut from the input
GlobalAvg (+) GlobalMax (+) GlobalStd -> Dropout -> Linear(384->3)
```

**No temporal pooling anywhere in the trunk**, and that is the point. The first
design pooled 2x twice (50 samples -> 12) and then pooled globally. The
discriminator is *oscillation count* -- singles 2 peaks, doubles 5 -- and a 1.4 s
double flick is ~35 samples, ~8 after pooling, so five distinguishable peaks sat
at the Nyquist limit. Global average and global max cannot count in any case: one
reports total activation, the other the largest single value. The architecture
was discarding the feature the classes differ on.

Kernels span three time scales because one scale cannot cover the problem: at
25 Hz, k=9 is 360 ms (one oscillation), k=19 is 760 ms (the gap between two),
k=39 is 1560 ms (the whole gesture).

**The architecture table below is PROVISIONAL and mostly ties.** It is kept
because the reasoning about pooling is sound and the ranking is the best that
exists, but it was produced under a protocol since found to be broken, and a
re-rank is pending. Read it with all four caveats.

| architecture | recall @ 1 FP/hour |
|---|---|
| CompactNet (the old one) | 57.1 ± 13.6 |
| + std pooling | 62.1 ± 6.3 |
| dilated, no pooling | 62.3 ± 8.9 |
| dilated + attention pooling | 63.8 ± 15.4 |
| resnet1d (499k params) | 59.4 ± 4.9 |
| conv + biGRU (DeepConvLSTM) | 56.2 ± 12.4 |
| **GestureNet (inception)** | **69.9 ± 7.4** |

**1. Every threshold was chosen by looking at the evaluation negative.** That is
tuning on test, and it inflates recall too, by a different amount per model. It
is also unstable in a way that reads as model variance: typing is 10 minutes, so
a 1/hour budget permits zero events and the threshold becomes an extreme-order
statistic. A real share of the ± columns is that number moving. `whip/evaluate.py`
now forbids this; see "Measurement rules" below.

**2. Only seed spread is shown. Sampling spread is larger and absent.** At 64
held-out gestures the binomial interval on 70% recall is about ±11 points. The
earlier claim that "differences under ~8 points are not resolvable" counted seed
variance alone and was wrong by roughly half. **Most rows here are ties.**

**3. "+12.8 from fixing the pooling" conflated several changes.** GestureNet also
changed the block type, the width, and 18k → 226k parameters. The *isolated*
pooling change is the std-pooling row: **+5, with overlapping intervals.**

**4. Two specific claims do not survive.**
- *"Recurrence lost"* -- 56.2 ± 12.4 against CompactNet's 57.1 ± 13.6 is a **tie**,
  not a loss. It remains true that `GestureNet` is pure convolution and needs no
  recurrent port, but that convenience was doing some of the deciding.
- *"Size bought reliability"* -- **withdrawn.** `resnet1d` has the tightest spread
  in the table at 499k params and a lower mean. The claim never held.

The flatten-head comparison elsewhere in this file has the same problem: it used
its own conv trunk, so it was never a pooling ablation. And the explanation given
for why it lost -- translation sensitivity against 88% window overlap -- is
backwards. Overlap supplies every offset during training, and event scoring needs
only one of ~8 windows to fire. The observation stands; the explanation does not.

---

## Measurement rules

Each of these exists because breaking it produced a confident wrong answer.

**Calibrate on data you do not report on.** `whip/evaluate.py` takes a
calibration negative and reports on a different one;
`dataset.split_session_by_time()` splits one session in two when there is only
one, with a guard band because 2.0 s windows at 88% overlap would otherwise share
samples across the cut.

**Report a curve, not a point.** A single operating point compares confidence
calibration as much as discriminative power.

**Report both variances.** Seed spread and sampling spread are different
quantities; `bootstrap_recall_ci` gives the second.

**A rate is per minute of the activity measured.** Nobody waves for an hour, so
"73 false positives per hour of waving" was never a meaningful number. Per-hour
is for ambient wear.

**Zero events is not evidence of a low rate.** By the rule of three, zero in T
minutes bounds the rate at 3/T. A clean *hour* of ambient wear bounds it at
3/hour, not 1 -- so it could never have settled the build spec's criterion.
**Demonstrating < 1/hour takes over three hours of clean wear.** An earlier
recommendation in this project for "one hour of ambient" was insufficient, and
`MIN_AMBIENT_MIN` is 190, not 30.

**Count false positives per segment, never on a concatenated stream.**
`events.detect` has no notion of time, so joining sessions end to end lets the
tail of one and the head of the next form a run that never happened.
The same artifact appears INSIDE a session once the audit removes a
gesture's windows: the two same-class gestures either side of the hole fused
into one 12-window run centred on the hole, and both scored as misses
(2026-09-15, four "misses" that were all called correctly window by window).
`RunTracker` now ends a run at any step longer than two strides
(`MAX_RUN_STEP_S`), live and offline alike.

**A model cannot reject what it has never seen.** The claim that the
loud-deliberate versus loud-incidental distinction was absent from the data
rested on 13 architectures failing on waving -- with the waving clip held out of
training in every one of those runs. Split a negative session in half by time and
train on one half instead. Doing that moved waving false positives from 73.6/hour
to about 14/hour.

**Shape and scale are separate channels.** Trained on raw g, the network keys on
amplitude, because amplitude is the easiest feature there. That one shortcut
causes both failure modes at once: soft flicks peak near 2.3 g and typing peaks
near 2.0 g, so an amplitude threshold misses half the soft gestures *and* fires
while you type. `to_model_input` feeds three unit-amplitude waveform channels
plus one log-peak channel. Over five seeds: soft recall 28 -> 39%, hard 61 ->
78%, typing false positives 10 -> 4/hour, variance roughly halved.

Dividing amplitude out *entirely* is worse in the other direction -- a quiet
window normalises sensor noise up to full scale and starts to look like a
gesture, costing 6 points on hard flicks. Keep both, separately.

Also ruled out: biasing amplitude augmentation downward to synthesise soft
flicks from hard ones. It makes things worse (soft 31 -> 24%), because hard
flicks clip at ±4.09 g, so scaling one down yields a flat-topped signal at low
amplitude -- not what a real soft flick looks like.

**Window and receptive field were both sized from measurement, not assumption.**
A first pass used 38-sample windows and a k=3 third layer, giving a 960 ms
receptive field on the assumption that a double-flick was two taps ~300 ms apart.
Measuring 33 real gestures showed they run **0.8-1.4 s**, so 74% of them exceeded
that receptive field and the window left only 125 ms of alignment slack.

That lesson holds, but the fix changed. The k=39 branch alone spans 1560 ms, and
with three blocks the stack sees the whole window, so receptive field is no
longer the binding constraint -- resolution is. Window stays 2.0 s (~600 ms of
alignment slack).

**The discriminator is oscillation count, not duration.** Singles average 2 peaks,
doubles 5. Duration overlaps completely between classes -- best duration-only
split is 73%, peak-count reaches 85%. Those are the baselines the model must beat.

**Clipping is confirmed.** Flicks peak at ~6.5 g against a ±4.09 g range, so
amplitude saturates on hard gestures and shape has to carry the discrimination.

**Three poolings, concatenated.** Max reports pattern identity ("did the two-peak
template match"), average reports total activation, and **std reports variation
over time**, which is the closest cheap proxy for oscillation count. Adding std
alone to the old architecture was worth 5 points -- mean and max both discard it,
and neither can count.

**The dataset makes amplitude a 95% solution.** Peak amplitude alone separates
gesture from not-gesture at **AUC 0.953** on the training set (0.918 held out).
Negatives have p90 = 2.53 g; gestures p10 = 2.48 g. Of 6555 negative windows only
~134 are gesture-loud, nearly all from one 1.7-minute waving clip. A network
trained on this leans on amplitude because amplitude answers the question asked.

**But "the distinction is not in the data" was wrong, and the reasoning was
circular.** That claim rested on 13 architectures all failing on waving -- while
the waving clip was in `HELD` for every one of those runs. No model ever saw a
wave in training. Models fail on data withheld from them; that is not evidence
about separability.

**Amplitude-matched test settles it.** Restrict to windows whose peak lies in
3.6-7.0 g, so amplitude is matched by construction, de-overlap by taking every
9th window in time, then score gesture vs waving:

| feature | separation |
|---|---|
| peak amplitude | 0.707 |
| crest factor | 0.870 |
| zero crossings | 0.927 |
| **energy concentration** | **0.972** |

Medians: zero crossings 6 (gesture) vs 17 (waving); energy concentration 0.47 vs
0.27. One hand-computed feature, no model, no training. A flick is one impulsive
lobe then quiet; a wave is periodic for seconds.

So the real diagnosis is an **objective and weighting problem, not an information
problem**. 134 loud negatives out of 6555 is 2% of the negative set -- under plain
cross-entropy, getting every one of them wrong costs almost nothing. Fixes are
oversampling loud negatives, a two-stage amplitude-gate-then-shape-classifier, or
explicit shape features. Not "collect until the model notices."

Collecting high-energy negatives is still right, for a different reason: 16
de-overlapped waving windows from one person on one day demonstrates the feature
exists and cannot train or validate a deployable rejector.

**The loud idle and typing windows are artifacts, not motion.** Windows above
3.6 g have a median width above half-peak of **1.0 samples (40 ms)**; a real flick
is ~9 samples. Idle has 27 such windows, typing 2. These are BLE or firmware
glitches, and the log-peak scale channel has been consuming them. A median-3
filter removes them (idle 27 -> 1, typing 2 -> 0) at a 17% cost to real gesture
peaks -- worth doing, but it moves every amplitude threshold, so it invalidates
existing calibration rather than dropping in.

**Ruled out, with numbers.** Each of these is the obvious simpler thing, and
each is measurably worse at a matched 1 FP/hour budget (7 seeds):

| variant | recall @ 1 FP/hour |
|---|---|
| **GestureNet, shape+scale** | **69.9** |
| GestureNet, raw g | 57.4 |
| flatten head instead of pooling, shape+scale | 56.0 |
| flatten head, raw g | 43.8 |
| flatten head without BatchNorm | 31.0 |
| MLP, no convolution at all | 27.5 |

- **Removing pooling entirely loses 14 points**, with twice the parameters. A
  flatten head keeps exact peak positions, which sounds right for counting
  oscillations, but it is translation-sensitive: with 88% window overlap the same
  gesture lands at many offsets and each must be learned separately, which
  divides an already small gesture count. Global pooling is not waste, it is the
  correct prior -- a flick is the same flick wherever it falls in the window.
- **BatchNorm is load-bearing, not decoration.** Removing it costs 25 points.
- **Convolution earns its keep by ~42 points** over a plain MLP.
- **Raw g loses ~12 points under both architectures.** The penalty being the same
  size regardless of design is the strongest evidence that the shape/scale split
  is real rather than an artifact of one model.

**No softmax in the model** (CrossEntropyLoss wants logits); it lives in the C++
daemon. **No RNN** -- originally assumed, now measured: a conv+biGRU scored worst
of seven architectures (56.2% vs 69.9%). Recurrence was the one mechanism that
could in principle count events, so this was worth testing rather than asserting.
It lost, which conveniently removes the only design that was painful to port.

Classes are `none`, `flag` (single flick), `approve` (double flick). `none` is not
a gesture: it is ~99.99% of windows, and it is why the false-positive budget
rather than F1 is the binding constraint. Two positives rather than one because a
negative-only signal trains the model toward terseness and refusal.

Split: PyTorch for training (user), hand-written C++ for inference (~200 lines, no
dependency). Export weights plus **golden vectors**; the C++ must reproduce them
to 1e-5 in float. Get float parity first, then quantise -- changing both at once
makes a discrepancy unattributable.

**Single-sample artifacts were being fed to the model as amplitude.** Windows
above 3.6 g in the idle and typing sessions have a median width above half-peak
of **1.0 samples (40 ms)**; a real flick is ~9. They are BLE or firmware
glitches, and `to_model_input` derives its log-peak channel from the window
maximum, so every one arrived as "something loud happened here". `whip/despike.py`
removes them with a Hampel filter: loud idle windows 27 → 0, typing 2 → 0, at a
cost of 1.3% of gesture peak height. A plain median-3 achieves the same removal
for **16.9%**, because it smooths every sharp peak including the real ones.

**The wrist rotation axis is measured, not assumed.** A flick is a very clean
rotation -- eigenvalue ratio 0.008-0.010 on the gravity trajectory -- about an
axis that every gesture in a session shares (agreement 0.97). That axis is 0.919
aligned with axis 0, so `model.augment` rotating axes 1 and 2 about axis 0 is
right. `probe/axes.py` measures it.

**Between-session change is posture, not ring spin.** An earlier reading of
"60 degrees of ring rotation between sessions" was wrong -- it averaged the
rotation axes of directions that rotate about different axes. Measured
directly, the ring's spin about the finger differs by ~15 degrees between
sessions and the hand's pitch by ~50. The session-holdout gap is posture and
execution variety, which more sessions cover; see "The gesture platform".

**Measured false-positive baselines.** Typing and walking are cleanly separable:
a conjunction of amplitude, duration and oscillation count gives zero false
positives on both, though any single feature gives 36-66/hour. Idle coding
motions also give zero. The real hard negatives are **waving** (1320 ms, 6 peaks
-- more oscillations than a median double-flick) and **snapping** (540 ms, 5.4 g
-- a single-flick profile). Both must be in the training set.

**Debounce with a band, not a floor.** A gesture fires ~8 consecutive windows; a
3-second wave fires ~15. Requiring `>= 4 consecutive` makes sustained motion
*more* likely to fire, not less. Accept 4-12.

See `docs/COLLECTION.md` for the collection protocol and the confounds it controls.

## Tooling

```
whip/       protocol.py  packets, commands, UUIDs
            accel.py     decoding, candidate ranking, stationary filtering
            capture.py   BLE connect and notification recording
            analyze.py   rate, jitter, gaps, loss, the gate decision
            fwimage.py   OTA container parsing, timer-site location
            fwbuild.py   custom image construction
            dfu.py       DFU framing, pure and hardware-free
            corpus.py    M2 corpus: both layers, situations, validation, session plans
            labeling.py  M3 labels: records, ring join by wall/action, scoring, preferences.json
            reward.py    M4 factored reward, judge validation, M5 datasets
            arms.py      M6 three arms, fill sweep, adherence, slopes
            persona.py   synthetic labeler + arm simulator (fixtures only)
probe/      scan stream sweep drain report simulate find quiet
            firmware flash build ledsweep ledtest gestures subdata
            calibrate    M2: validate / stats / plan
            label        M3: run / join / score / aggregate
            pipeline     M4-M6: dryrun / contextfile / judgecheck
corpus/     taxonomy.json  layer 1: 12 artifact-style dimensions
            agency.json    layer 2: 11 working-style axes + 5 situation factors
            gold/          contrast items, both layers
docs/       CALIBRATION.md  M2/M3 design and confounds
            AGENCY.md       layer 2: trajectories, situations, conditional policies
            PIPELINE.md     M4-M6 components, gates, falsifiers, sample budgets
            PIPELINE.md     M4-M6 architecture, gates, falsifiers
firmware/   archived images + SHA256SUMS
              rt02cr-stock-3.12.02.bin   vendor stock, the recovery path
              rt02cr-low-latency.bin     upstream #2, 50 Hz
              rt02cr-33hz.bin            ours, #3, 33 Hz -- currently flashed
              rt02cr-31hz.bin            ours, #4, 25 Hz
```

81 tests, none needing hardware. `probe/simulate.py` fabricates captures so the
whole pipeline runs without a ring.

**Design rule:** the capture callback only timestamps and stores. The quantity
being measured is arrival timing, and any work in the notification handler
contaminates it. All decoding and analysis is offline against saved payloads,
so any new idea can be tested against old captures without recapturing.

**The build spec requires C++ for the ring daemon.** This harness is not the
daemon — it is diagnostic tooling whose job was to answer whether the hardware
clears the gate. `ring/` will be C++17, ported from these constants.

---

## Methodological lessons

Worth keeping, because each was caught by data rather than review.

**Ranking on spread alone is exploitable.** A decoder right in some orientations
and wrong in others yields a tight cluster plus outliers, and scores well once
the outliers are dropped. It put the *worst* candidate top by discarding 40% of
the data. Coverage — how much of the data a hypothesis reconciles — has to
dominate, with spread only as tie-break.

**A metric can pass on a stream that is useless and fail on one that is fine.**
Stock scored 0.00% loss with a 1114 ms hole; the low-latency firmware scores 26%
with a 74 ms worst gap. Report both readings rather than choosing the flattering
one or quietly redefining the criterion.

**Entropy is not evidence of encryption**, and a checksum that will not verify
only means the algorithm differs.

**Predict from measurement, not from the instruction.** The timer arithmetic says
`imm * 8` ms and every delivered period was `imm * 10`. Three hardware
measurements beat a correct reading of one instruction, because the instruction
is not the whole path.

**Judge preprocessing with data independent of the hypothesis under test.**
Stationarity is decided on raw bytes, so the decoder being scored cannot select
the data it is scored on.

---

## Open

- **Killing the LEDs is the only lever left on battery.** Rate is not it.
- If M1's false-positive target proves hard, `#3` offers 33% more samples at
  the cost of the loss criterion. Revisit then, not now.
- LED: find and NOP the optical enable in the raw path.
- **Preferences are policies, not archetypes.** The first taxonomy measured
  only what a single response looks like, because the presentation format
  (one response, one screen) could not show anything else. The properties that
  actually distinguish coders -- how much the model does before checking in,
  what makes it stop, whether it narrates, whether it proves its work -- are
  properties of a *trajectory*. Layer 2 (`docs/AGENCY.md`) measures those by
  contrasting **compressed action logs**, which do fit the 40-second budget.
  Two rules came out of it:
  - **Do not box a coder into an archetype.** Nobody is hands-off all the
    time. Items declare a *situation* (reversible/irreversible,
    familiar/foreign, determined/underdetermined, exploring/shipping,
    small/large) and each axis declares which factors might flip it; whether
    they do is measured. The output is "large steps by default, small when the
    action cannot be undone", not "prefers autonomy".
  - **Conditionals are detected before the main effect.** A preference that
    flips cleanly cancels out in aggregate -- four votes each way -- and the
    first implementation dismissed exactly that as `contested`. Backwards: a
    perfect flip is the most informative result there is. A flip needs 4
    decided pairs per level, each lopsided, so the design detects flips, not
    gradients.
- **Layer 2's next steps are specific**, and `probe.calibrate stats` prints
  them: four items per level on any axis whose policy matters (the detection
  threshold); items for the three declared-but-unprobed second conditioners
  (`stop_trigger`/`scope_renegotiation` on reversibility, `verification` on
  familiarity) or drop those conditioners; and two sentinels, since the agency
  layer currently has none and the fatigue check would not run.
- **Guardrails are not dimensions.** Secrets, destructive commands, unilateral
  deploys: those have right answers, are trained in regardless, and never
  appear on screen -- putting one in the corpus invites approving reckless
  behaviour. Operationally: in an irreversible situation **both variants stop
  at the same safety line**, and the axis is how much is prepared before
  returning. If one pole is wrong, it is not a dimension.
- **M2 is a curated contrastive corpus, not mined repo data.** The earlier plan
  to pull interactions from the FDD pipeline and AsyncWorld repos is replaced
  (2026-09-15): mined responses differ from their alternatives on many axes at
  once with no counterfactual, so a flag cannot identify *which* property was
  disliked, and correctness confounds taste. Each corpus item is instead a pair
  of equally-correct responses differing on exactly one of 12 taste dimensions;
  the gesture identifies the class by construction. Finalized at 60 gold items
  (5 per dimension, `corpus/gold/`), machine-validated for schema, poles, and
  length leaks. Design and confound table: `docs/CALIBRATION.md`.
- **M3 tooling is built; the sessions are not run.** `probe/label.py` is the
  presenter. Order of operations:
  1. Rule-3 read-through of the 48 expanded items in `corpus/gold/` -- both
     variants correct, no strawmen. A bug found after labeling voids that
     item's labels, so this is human review, not a formality.
  2. `python -m probe.calibrate plan --session N --pairs 40 --seed <fixed>
     --layer artifact|agency` (one layer per session -- 23 axes cannot each
     get enough pairs in one sitting),
     then `python -m probe.label run --plan ...`. Keys f / a / Enter; the
     file appends per slot and resumes. The presenter never shows the
     dimension or pole.
  3. If the ring was streaming (`probe.serve` or `probe.live`):
     `python -m probe.label join --labels ... --events data/live/events_*.jsonl`.
     Joins by `wall` on `action` in {flag, approve} only, nearest key-label
     time, 2.0 s window past the key. Missed slots are reported, not skipped.
  4. `python -m probe.label score` -- sentinel agreement >= 80%, all 12
     dimensions, none-rate <= 85%, first-shown balance; exit 2 on reject.
     Ring-vs-key agreement is printed as matched / mismatched / missed and
     silent / spurious, which is M1's acceptance check at the same time.
  5. Four sessions on different days, then
     `python -m probe.label aggregate --labels data/calibration/labels_s*.jsonl`
     -> `data/calibration/preferences.json`: per dimension the winning pole,
     `indifferent` (> 60% indifferent pairs), `contested` (a later session
     flips it -- back to item review), or `unmeasured`; plus the ordered
     `context_file` statements the M6 context arm uses verbatim.
- **The ring is secondary in M3 by measurement, not caution.** Latency ~1.3 s
  gesture-end to event. Recall reached ~90% once two sessions were in
  training, but on one fresh 32-gesture session (95% CI 75-100); ambient false
  positives are bounded only at ~6/h by 30 min of wear, and every one observed
  was unmapped (wave/snap, `action: null`), so a spurious flag/approve has not
  been seen but also not bounded below the 1/h bar. Both numbers need a wider
  sample before the ring leads; the presenter would then also need an explicit
  no-gesture-arrived path, never a silent skip.
- **Direction is recorded but deliberately not routed on.** It transfers at
  93-96% to a fresh session once two sessions are in training (2026-09-15,
  `probe/directions.py`) -- the earlier "clean permutation between sessions"
  was a one-session-training artifact, not a rotated ring -- and
  `data/app_config.json` supports `flick:up`-style keys. M3 still joins on
  `action` alone: the label vocabulary is three states, which two gestures
  plus silence already cover, so a direction qualifier would add a second way
  for a ring label to be wrong on a path the keyboard already handles at 100%.
  It is stored on every joined record and reported as a per-action habit,
  because a coder who flags down and approves up without being asked is the
  only evidence that would justify routing on it later. M3 cannot score
  direction accuracy -- the labeler is never asked for a direction, so there
  is no ground truth.
- **M4-M6 harnesses are built and exercised on fixtures; only the model-facing
  parts are blocked.** `python -m probe.pipeline dryrun` plants a known
  preference (including conditionals) and runs sessions -> labels ->
  preferences.json -> context file -> reward -> three-arm sweep, failing unless
  the plant comes back, the base arm is flat, and context degrades faster than
  weights. It proves the chain wires together and the metrics have the power to
  see an effect of the hypothesised shape -- it is **not** a result about
  weights versus context, since the arms are simulated by a function written to
  contain the effect. Same standing as `probe/simulate.py`.
- **Two eval faults surfaced from the dry run, before any real data existed** --
  the argument for building the harness first:
  - **The base arm's slope was not flat** at low sampling. Unnoticed, that
    drift would have read as context-independent degradation and contaminated
    both other arms. Now a precondition the dry run asserts.
  - **The per-dimension conditional prediction needs ~160 samples per dimension
    per fill level** (measured over 12 seeds: at ~48 it inverts on 1 seed in
    12; at 160 it holds 12/12, and more buys nothing). The pooled arm
    comparison is stable well below that, so the headline number and its most
    interesting breakdown have different sample budgets -- and the breakdown
    sets the real cost of the sweep.
- **M4-M6 design, gates and falsifiers:** `docs/PIPELINE.md`. The decisions
  that matter:
  - **M4's direction term is a function of the prompt**, not a constant:
    `s_d(prompt)`, because a conditional preference cannot be scored by a
    fixed sign. That needs a second classifier over *prompts* -- which level
    of each situation factor does this task sit at -- supervised free by the
    corpus, since every item records its situation in frontmatter. A factor
    below the 90% bar forces the dimensions conditioned on it back to their
    unconditional default rather than guessing.
  - **M6 gets a sharper prediction from layer 2.** A style rule ("be terse")
    is a local constraint on every output; a conditional policy has to fire at
    a decision point buried in a filled context. So the context arm should
    degrade **fastest on conditional axes and slowest on unconditional ones**
    -- a per-dimension prediction that a pooled adherence number would hide.
  - **M4 is a factored reward**, `sum_d w_d * s_d * (2 p_d - 1)`: pole
    classifiers `p_d` trained on the corpus's own variant labels (120
    examples, free by construction, held out *by item*), direction `s_d` and
    weight `w_d` from `preferences.json`. Indifferent dimensions get `w_d = 0`
    -- flat by construction, not by hoping a scalar head learns it. An
    LLM-judge with the taxonomy text as rubric is tried first (>= 90% per
    dimension or that dimension is not scorable). Bradley-Terry on the pairs
    is the baseline; if it beats the factored RM outside its interval, the
    taxonomy is wrong, not the RM.
  - **M5 is DPO first, GRPO second.** DPO on ~160 pairs (rank-16 LoRA, beta
    picked by held-out win-rate under the RM, not by DPO loss), KTO on ~320
    singles as an ablation, then optional GRPO against the factored RM on
    prompts the corpus never contained -- the only stage where the RM
    generalizes beyond the 60 contrasts. Guards: KL budget, reward-hacking
    check (RM score rising while human spot-check agreement falls), and a
    functional-correctness canary that must hold at the base model's rate.
  - **M6 is built first.** Three arms on one base model: none / mechanical
    context file from `preferences.json` / adapter. Neutral non-code filler
    at 0, 8k, 32k, 64k, max tokens between system prompt and task. Metrics
    in order of authority: pole-classifier adherence per dimension, human
    blind spot-check through the same keypress presenter, correctness canary,
    BT score. The research question is two numbers: the B-C gap at zero fill
    and the two slopes against fill, with bootstrap CIs and a per-dimension
    breakdown -- because "weights hold for style axes, context for behavioral
    ones" is a plausible honest result that pooling would hide.
  - **Falsifiers are written down** for each stage in `docs/PIPELINE.md`;
    a flat result across all three arms is a result, not a failure to find
    one.
