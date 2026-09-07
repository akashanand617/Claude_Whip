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
| M0 hardware gate | rate PASSES at 33.33 Hz; loss 2.99% vs a <2% bar. See "the rate ladder" |
| M1 gesture classifier | not started |
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
| Firmware now | `RT02CR_3.12.07_260514`, immediate `#3` (`rt02cr-33hz.bin`) |
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
| `#3` | **33.33 Hz** | 2.99% | **currently flashed**; 1.96% on a 60 s desk capture |
| `#4` | 24.98 Hz | 0.07% | clean, but 0.02 Hz under the gate |

`#3` is the operating point. `#2` produces faster than BLE delivers -- 61% of
intervals at one period and 33% at double it, the signature of dropped samples.
`#3` and `#4` are unimodal with jitter only. `probe/build.py` locates the timer
site by period rather than a hard-coded address.

**The rate ladder has no rung that satisfies both criteria.** The immediate is
an integer, so the choices are 50 / 33.3 / 25 Hz. `#3` clears the rate with
margin and misses loss (2.99% vs <2%); `#4` clears loss easily (0.07%) and sits
*exactly* at the 25 Hz threshold, measuring 24.98. This is a property of the
hardware, not an untried option.

Both have **zero contaminated gesture windows** and a worst-case gap under 5% of
a 1.5 s window, which is what the loss criterion is a proxy for. Judge a capture
on rate, gap distribution and window contamination together -- stock scored
0.00% loss while containing a 1114 ms hole.

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

**Battery: 78% → 68% over 10 minutes**, ≈1%/min, ≈1.7 h from full. This is the
real operational figure — the LEDs cannot be turned off while streaming, so
there is no better case. Phase A (1 h session) is viable; Phase B (all-day
capture) is not, and v2 should assume duty-cycled capture.

---

## LED

Green and red are the PPG and SpO2 emitters. They light whenever `A1 04` runs
and cannot be turned off:

- the realtime stop commands (`69 01 04`, `6a 01 00 00`, `6a 03 00 00`) do
  nothing, sent during streaming or after it
- **no command lights them either** — `69 01 01` (start HR) produced no LED at
  all, so they are not driven by the health-command path
- no `A1` parameter streams motion without them

They are wired into the raw-sensor path in firmware. Killing them means finding
the sensor enable in that path and NOPing it, which is a flash-and-observe search
with no debugger. `whip/fwbuild.py` makes the iteration possible; nobody has
attempted it yet.

---

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

- Re-measure battery on `#3` — two thirds the packet rate of `#2` and no
  bimodal retransmission should extend the ~1.7 h measured at 50 Hz.
- The 1.96% loss at `#3` sits close to the 2% line. If a longer worn capture
  tips it over, `#4` gives 0.07% at 24.98 Hz — which needs the gate's rate
  threshold met some other way, or acceptance that 25 Hz is the floor.
- LED: find and NOP the optical enable in the raw path.
- **M2: pull the calibration corpus from the FDD pipeline and AsyncWorld repos.**
  This is the actual next milestone and needs none of the above.
