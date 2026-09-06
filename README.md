# Whip

Gesture-driven preference learning for a local coding model.

A smart ring worn while coding emits a gesture when the model does something you
dislike. Those gestures become preference data, which trains a LoRA adapter
baked into a locally served coding model.

The research question: **do preferences baked into weights hold up better than
preferences written into a context file, and does the gap widen as context
fills?**

## Status

**M0 — hardware gate.** Everything downstream is blocked on raw accelerometer
streaming at ≥ 25 Hz.

Stock firmware measured **1.00 Hz** — a firmware refresh timer, not a bandwidth
limit, and no protocol parameter changes it. A low-latency firmware exists for
this exact hardware that takes the timer to 16 ms, or **62.5 Hz**. The image is
archived in `firmware/`, verified at instruction level, and its hash is pinned
by a test. **The flash has not been performed yet** — see `docs/FLASHING.md`.

| Milestone | State |
|---|---|
| M0 hardware gate | stock firmware FAILED at 1.00 Hz; **flash pending** for 62.5 Hz |
| M1 gesture classifier | not started |
| M2 calibration corpus | not started, **not blocked on hardware** |
| M3 labeling session | not started, **not blocked on hardware** |
| M4 reward model | not started |
| M5 LoRA adapter | not started |
| M6 three-arm eval | not started |

M2 through M6 need no ring. They are the path to the actual research question,
and they can proceed in parallel with the hardware track.

## Setup

```sh
./setup.sh
source .venv/bin/activate
```

Needs Python 3.11+. The only runtime dependency is `bleak`.

## Flashing

The stock ring cannot clear the gate. `docs/FLASHING.md` is the runbook, and
`probe/firmware.py` verifies any image offline before it touches hardware:

```sh
python -m probe.firmware firmware/rt02cr-low-latency.bin --hardware RT02CR_V3.1
```

## The M0 runbook

Run these in order.

### 1. Identify the ring

```sh
python -m probe.scan
```

Reports name, address, firmware and hardware revision, and battery. **Record the
firmware string in `docs/HARDWARE.md`** — rings that look identical ship
different firmware, and it is the first thing that explains a rate difference.

If nothing is found, make sure the phone app is closed; it holds the connection.

### 2. Verify the decoder — six orientations, ring stationary

```sh
python -m probe.stream --duration 60 --label idle --stationary
```

Rest the ring on each of its six faces for ten seconds during the capture.

The 12-bit accelerometer decode is not settled — the one public working
implementation has an internally inconsistent sign check. This capture ranks
five candidate decoders by which one holds gravity's magnitude constant.

Six orientations matter. With gravity on one axis every value stays positive,
several candidates tie, and the ranking means nothing.

### 3. Run the gate — ten minutes, worn, typing

```sh
python -m probe.stream --duration 600 --label typing
```

This is the measurement that decides M0. A rate measured on a motionless ring on
a desk is not the rate you get in use. Exit code is 0 on pass, 2 on fail.

### 4. If the rate falls short, sweep before flashing

```sh
python -m probe.sweep
```

`A1 04` enables SpO2, PPG **and** accelerometer on one shared notification
channel. If accel is only a third of the traffic, two thirds of the bandwidth is
going to sensors this project does not use. `0x04` starts and `0x02` stops;
every other parameter byte is unexplored. An accel-only mode would be worth a
large multiple on the rate for free.

This is the cheapest lever available and it should be exhausted before touching
firmware.

### 5. Battery

```sh
python -m probe.drain --max-hours 2
```

17 mAh cell. A one-hour calibration session needs ~1.5 h of headroom; all-day
passive capture (v2) needs ~8 h and is the requirement most likely to fail.

### 6. Write it up

Paste the numbers into `docs/HARDWARE.md`. Every TBD in that file is a real
blank, not a placeholder to skip.

## Re-analysing without the ring

Captures keep raw notification payloads, so any new idea can be tested against
data collected weeks ago:

```sh
python -m probe.report data/raw/typing_*.jsonl
python -m probe.report data/raw/idle_*.jsonl --stationary --dump 20
python -m probe.report data/raw/idle_*.jsonl --hex 10
```

## Trying the harness before the ring arrives

`probe/simulate.py` fabricates a capture so the whole pipeline can be exercised
with no hardware:

```sh
python -m probe.simulate --rate 21 --duration 60 --label sim_marginal
python -m probe.report data/raw/sim_marginal_*.jsonl --stationary
```

It is a test fixture, not a model of the ring. The default 21 Hz with a 3-way
channel split roughly matches what the published Edge Impulse capture implies,
which makes it a useful rehearsal of the failure path.

## Tests

```sh
python -m pytest tests -q
```

34 tests, no hardware required.

## Layout

```
whip/           protocol, decoding, capture, analysis
  protocol.py   packet construction, command and subtype constants
  accel.py      12-bit decoding, candidate unpackers, gravity-based scoring
  fwimage.py    OTA container parsing and timer-site analysis
  capture.py    BLE connection and notification recording
  analyze.py    rate, jitter, gap and loss metrics; the gate decision
probe/          command line tools
  scan.py       find the ring, report identity and battery
  stream.py     capture a stream and decide the gate
  sweep.py      search the 0xA1 parameter space for an accel-only mode
  drain.py      battery life under continuous streaming
  report.py     re-analyse a saved capture
  simulate.py   synthetic captures for testing without hardware
  firmware.py   inspect and diff firmware images offline
  gestures.py   hunt for gesture events and a hidden rate parameter
  subdata.py    sweep sub-data bytes of the enable command
  find.py       identify the ring by proximity when the name does not match
firmware/       archived OTA images, stock and low-latency
tests/
docs/
  HARDWARE.md   the M0 gate record
  FLASHING.md   the flashing runbook and recovery path
data/           captures (gitignored)
```

### Why this part is Python

The build spec requires **C++ for the ring daemon**, and that still holds — the
daemon in `ring/` will be C++17 when it is written.

This harness is not the daemon. It is throwaway diagnostic tooling whose entire
job is to answer one question: does the hardware clear the gate. Writing it in
C++ would have delayed that answer for no benefit. The protocol constants and
the decoder logic here are the reference the C++ implementation gets ported
from, and `docs/HARDWARE.md` is the spec it implements against.

## Design notes

**The capture callback does nothing but timestamp and store.** The number being
measured is arrival timing, and any work in the notification handler
contaminates it. Decoding and analysis are entirely offline.

**Packet loss is reported as gap-implied loss.** The notifications carry no
sequence number, so true loss is not observable. What is reported is how many
expected sample slots produced nothing, given the modal interval — a lower
bound. It should not be described as measured loss.

**Gaps are reported against the 1.5 s gesture window.** A mean rate can clear
25 Hz while still being useless if it arrives in bursts separated by half-second
stalls. `windows hit` counts how many gesture windows contain a stall.

## Prior art

- [tahnok/colmi_r02_client](https://github.com/tahnok/colmi_r02_client) — connection handling and packet format
- [edgeimpulse/example-data-collection-colmi-r02](https://github.com/edgeimpulse/example-data-collection-colmi-r02) — the raw sensor commands and accelerometer byte layout
- [atc1441/ATC_RF03_Ring](https://github.com/atc1441/ATC_RF03_Ring) — SoC and sensor identification, modified firmware
