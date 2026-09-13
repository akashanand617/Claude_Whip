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
| M1 gesture classifier | protocol designed (`docs/COLLECTION.md`); harness not built |
| M2 calibration corpus | not started, **not blocked on hardware** |
| M3 labeling session | not started, **not blocked on hardware** |
| M4 reward model | not started |
| M5 LoRA adapter | not started |
| M6 three-arm eval | not started |

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

**Compare architectures only at a matched false-positive budget.** Uncalibrated,
`resnet1d` and a conv+biGRU looked precise (0.9 FP/hour) when they were merely
reluctant to fire. Tuning every model's threshold to the same 1 FP/hour budget
*first*, then reading recall, reverses the ranking. Seven seeds:

| architecture | recall @ 1 FP/hour |
|---|---|
| CompactNet (the old one) | 57.1 ± 13.6 |
| + std pooling | 62.1 ± 6.3 |
| dilated, no pooling | 62.3 ± 8.9 |
| dilated + attention pooling | 63.8 ± 15.4 |
| resnet1d (499k params) | 59.4 ± 4.9 |
| conv + biGRU (DeepConvLSTM) | 56.2 ± 12.4 |
| **GestureNet (inception)** | **69.9 ± 7.4** |

**Recurrence lost.** The biGRU was worst on recall, so the one architecture that
would have forced a painful hand-written C++ port is also the one not worth
porting. `GestureNet` is pure convolution.

Size bought reliability, not just capacity: seed-to-seed spread roughly halves
against the baseline's ±13.6. At this sample size (64 held-out gestures)
**differences under ~8 points are not resolvable** -- treat them as ties.

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
probe/      scan stream sweep drain report simulate find quiet
            firmware flash build ledsweep ledtest gestures subdata
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
- **M2: pull the calibration corpus from the FDD pipeline and AsyncWorld repos.**
  This is the actual next milestone and needs none of the above.
