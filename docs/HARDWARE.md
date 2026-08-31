# Hardware

M0 gate record. **Numbers below marked TBD are unmeasured** — they get filled in
the day the ring arrives, by pasting the output of `probe/stream.py`. Nothing in
this file should be an estimate presented as a measurement.

---

## Device under test

| | |
|---|---|
| Model | TBD (`probe.scan`) |
| Advertised name | TBD |
| Address | TBD |
| Firmware revision | TBD |
| Hardware revision | TBD |
| Purchased from / when | TBD |

Firmware revision is the single most important field here. Rings that look
identical ship different firmware, and the firmware string is the first thing
that explains a rate difference between two units that are otherwise the same.

## Known internals

From [atc1441/ATC_RF03_Ring](https://github.com/atc1441/ATC_RF03_Ring), for the
R02 family:

| | |
|---|---|
| SoC | BlueX Micro RF03, ARM Cortex-M0, 512 KB flash, 200 KB RAM |
| Accelerometer | STK8321, 12-bit |
| Heart rate | VCare VC30F |
| Battery | 17 mAh |
| Debug pins | P00 (SWCK), P01 (SWD) — inside the epoxy |

The 17 mAh cell is the constraint that decides what the ring can be used for.
It does not affect a one-hour calibration session; it very likely rules out
all-day passive capture in v2.

## Protocol

All command traffic runs over the nRF UART service.

| | |
|---|---|
| Service | `6E40FFF0-B5A3-F393-E0A9-E50E24DCCA9E` |
| Write (host → ring) | `6E400002-B5A3-F393-E0A9-E50E24DCCA9E` |
| Notify (ring → host) | `6E400003-B5A3-F393-E0A9-E50E24DCCA9E` |

Commands are 16 bytes: command byte, up to 14 bytes of sub data, then a
checksum which is the sum of the preceding bytes mod 256.

### Raw sensor streaming

```
enable   A1 04 00 ... 00 <checksum>
disable  A1 02 00 ... 00 <checksum>
```

Source: [edgeimpulse/example-data-collection-colmi-r02](https://github.com/edgeimpulse/example-data-collection-colmi-r02).
These two parameter values are the only ones confirmed to work. The rest of the
byte space is unexplored — see `probe/sweep.py`.

Notifications arrive on the notify characteristic tagged `A1`, with the stream
identified by byte 1:

| Subtype | Stream | Payload |
|---|---|---|
| `0x01` | SpO2 | bytes 2–3 big endian, plus max/min/diff |
| `0x02` | PPG | bytes 2–3 big endian, plus max/min/diff |
| `0x03` | **Accelerometer** | three 12-bit axes across bytes 2–7 |

**`A1 04` enables all three streams at once.** They share one notification
channel, so PPG and SpO2 consume bandwidth this project has no use for. If an
accel-only parameter exists, it is worth a large multiple on the accelerometer
rate for free. This is the first thing to try if the gate fails.

### Accelerometer byte layout

Axis order in the payload is **not** X, Y, Z:

```
bytes 2-3  ->  Y
bytes 4-5  ->  Z
bytes 6-7  ->  X
```

Each axis is 12 bits. The exact decode is **not yet settled**. The one public
working implementation tests bit 3 of the high byte for sign but subtracts
`1 << 11`, which is not a coherent two's complement decode for a 12-bit value.
It may be correct for a packing we do not understand, or it may be a latent bug
that never mattered for step counting.

Rather than guess, `whip/accel.py` implements five candidate decoders and
`probe/report.py --stationary` ranks them against real data. A stationary ring
measures only gravity, so the correct decoder is the one that holds vector
magnitude constant.

**The stationary capture must cover six orientations.** Rest the ring on each of
its faces for ten seconds. With gravity on a single axis every value stays
positive, the candidates never disagree about sign, and several tie at
near-zero spread — the ranking is then meaningless. This is not a theoretical
concern; it showed up immediately in testing.

| | |
|---|---|
| Selected decoder | TBD |
| Runner-up spread | TBD |
| Counts per g | TBD |

---

## M0 gate results

Gate from the build spec: **≥ 25 Hz sustained**, verified over 10 minutes, with
**packet loss below 2%**.

### Sample rate

| Condition | Accel rate | Jitter (sd) | Gap p95 | Gap max | Implied loss |
|---|---|---|---|---|---|
| 60 s, ring at rest | TBD | TBD | TBD | TBD | TBD |
| 10 min, worn while typing | TBD | TBD | TBD | TBD | TBD |

The 10-minute worn-while-typing run is the one that decides the gate. A rate
measured on a motionless ring on a desk is not the rate you get in use.

### Channel bandwidth split

| Stream | Rate | Share |
|---|---|---|
| accel | TBD | TBD |
| ppg | TBD | TBD |
| spo2 | TBD | TBD |

If accel is roughly a third of traffic, an accel-only mode would be worth about
3× the measured rate.

### On packet loss

The ring's notifications carry **no sequence number**, so true packet loss is
not directly observable. What `probe/analyze.py` reports is *gap-implied* loss:
given the modal inter-arrival interval, how many expected sample slots produced
nothing. That is a lower bound on real loss, and it is the honest number to
report against the 2% criterion. Do not describe it as measured loss.

### 0xA1 parameter sweep

Run `probe/sweep.py` if the rate falls short. Results:

| Param | Packets | Accel Hz | Accel share | Channels seen |
|---|---|---|---|---|
| `0x04` (known) | TBD | TBD | TBD | TBD |
| | | | | |

### Battery under continuous streaming

| | |
|---|---|
| Runtime to 5% | TBD |
| Projected full-charge runtime | TBD |
| Rate degradation as battery drops | TBD |

Thresholds: a one-hour calibration session needs ~1.5 h of headroom. All-day
passive capture (v2) needs ~8 h and is the requirement most likely to fail.

---

## Gate verdict

**Status: NOT YET RUN** — ring has not arrived.

Fill in on completion:

- [ ] ≥ 25 Hz sustained over 10 minutes
- [ ] Implied loss < 2%
- [ ] Decoder identified and validated against six orientations
- [ ] Battery runtime measured

## If the gate fails

In order, cheapest first:

1. **Sweep the `0xA1` parameter space** for an accel-only mode. Free, no risk,
   and if accel is a third of the traffic this is where the headroom is.
2. **Flash `R02_3.00.06_FasterRawValuesMOD.bin`** from
   [atc1441's repo](https://github.com/atc1441/ATC_RF03_Ring), via the
   [browser OTA tool](https://atc1441.github.io/ATC_RF03_Writer.html). The
   change is described only as lowering the raw-value refresh timeout;
   [the question of what it actually does](https://github.com/atc1441/ATC_RF03_Ring/issues/7)
   was asked in July 2024 and never answered. Recovery from a bad flash means
   SWD pads inside a potted ring, so in practice a failed flash is a dead ring.
   **Buy a spare before flashing.**
3. **Fall back to the ESP32-S3 + MPU6050 build.** ~$31. Removes the rate
   question entirely — an MPU6050 does 1 kHz — at the cost of the ring form
   factor. Parts list in the project notes.

Per the build spec: **do not proceed with a degraded sample rate.** A flick
gesture cannot be classified below ~25 Hz, and every downstream label depends
on the classifier being trustworthy.

---

## Prior art measurement

Edge Impulse ships a two-minute capture in their repo, resampled to 50 Hz. The
interpolation pattern in that file implies roughly **20–30 Hz** actual
accelerometer rate with **dropouts up to 740 ms**.

Treat this as an order-of-magnitude expectation, not a measurement: the file is
resampled, and the firmware that produced it is not stated. It does suggest the
stock configuration lands near the gate rather than comfortably above it, and
that a 740 ms hole — half a gesture window — is a real failure mode to watch for.
