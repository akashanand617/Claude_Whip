# Hardware

M0 gate record.

**Verdict on stock firmware: FAILED.** Raw accelerometer streaming works, but at
1.00 Hz against a 25 Hz requirement. Measured 2026-09-02.

**This is not the end of the story.** A low-latency firmware exists for this
exact hardware and takes the raw motion timer to 16 ms — 62.5 Hz. See
"CORRECTION" at the end of this file, which also documents an error in the
reasoning below. Read that before acting on anything in the middle sections.

---

## Device under test

| | |
|---|---|
| Model | Colmi R02 |
| Advertised name | `COLMI R02_CC07` |
| Bluetooth MAC | `30:32:41:33:CC:07` |
| CoreBluetooth UUID (macOS) | `3C2FA77E-1BE3-A0C5-0DD5-DB6A3AD452B2` |
| Firmware revision | **`RT02CR_3.12.02_260824`** |
| Hardware revision | `RT02CR_V3.1` |
| Tested | 2026-09-02, battery 82% |

The advertised name is `COLMI R02_CC07`, not `R02...`. A `startswith` match on
the model number misses this unit entirely -- match anywhere in the string.

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
| `0x05` | undocumented | near-static, observed on this unit only |

`A1 04` enables all of these at once, on one shared notification channel.

It was reasonable to expect that sharing to be the rate constraint — free the
channel of PPG and SpO2 and the accelerometer gets the bandwidth. **On this unit
that is wrong.** All four channels together produce 4 packets/s, which is
nowhere near any bandwidth limit. The rate is set by a firmware refresh timer,
and no parameter changes it. See the sweep results below.

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
| Selected decoder | **undetermined** |
| Runner-up spread | n/a |
| Counts per g | n/a |

Not resolved, and deliberately not pursued. Identifying the decoder needs a
stationary six-orientation capture, and at 1 Hz that would take an hour to
gather enough samples per face -- for a stream that fails the gate regardless
of how it is decoded. Revisit only if the rate problem is solved.

---

## M0 gate results

Gate from the build spec: **≥ 25 Hz sustained**, verified over 10 minutes, with
**packet loss below 2%**.

### Sample rate

| Condition | Accel rate | Interval median | Jitter (sd) | Gap max | Implied loss |
|---|---|---|---|---|---|
| 20 s smoke test, param `0x04` | **1.00 Hz** | 1023 ms | 77 ms | 1114 ms | 0.00% |

**The gate fails by a factor of 25.** The 10-minute worn capture was not run:
there is nothing a longer capture can reveal when the rate is 1 Hz, and the
build spec is explicit that a degraded rate is not to be worked around.

The rate is a firmware refresh timer, not a bandwidth or radio limit:

- interval is a clean ~1023 ms with only 77 ms of jitter
- implied loss is 0.00% -- nothing is being dropped, the ring simply sends
  one sample per second
- total traffic across all four channels is 4 packets/s, orders of magnitude
  below what BLE can carry

This matches the other public data point for this ring: the iOS collector at
smithandrewk/colmi-r02-data-collector describes itself as collecting
"accelerometer data from Colmi R02 smart ring at 1 Hz".

### Channel bandwidth split

| Stream | Subtype | Rate | Share |
|---|---|---|---|
| spo2 | `0x01` | 1.00 Hz | 24% |
| ppg | `0x02` | 1.00 Hz | 24% |
| accel | `0x03` | 1.00 Hz | 24% |
| **undocumented** | `0x05` | 1.00 Hz | 24% |

Subtype `0x05` is not described in any public source. Its payload is nearly
static (`a10501380000000000000100000000e0`), so it is probably a status or
counter frame rather than sensor data.

**Accel payloads carry exactly one sample.** Bytes 8–14 are zero in every frame,
so there is no batching and the packet rate is the sample rate:

```
a103 1606 cef9 03c6 00000000000000 50
a103 fb78 2662 7fff 00000000000000 1d
a103 e630 021f 68d2 00000000000000 15
```

### On packet loss

The ring's notifications carry **no sequence number**, so true packet loss is
not directly observable. What `probe/analyze.py` reports is *gap-implied* loss:
given the modal inter-arrival interval, how many expected sample slots produced
nothing. That is a lower bound on real loss, and it is the honest number to
report against the 2% criterion. Do not describe it as measured loss.

### 0xA1 parameter sweep

Run `probe/sweep.py` if the rate falls short. Results:

Swept `0x01` through `0x08` at 12 s each. **No parameter beats 1 Hz.**

| Param | Packets | Accel Hz | Channels seen |
|---|---|---|---|
| `0x01` | 48 | 1.00 | spo2, ppg, accel, 0x05 |
| `0x03` | 5 | 0.08 | one frame of each, then quiet |
| `0x04` (known enable) | 49 | 1.00 | spo2, ppg, accel, 0x05 |
| `0x05` | 6 | 0.00 | silence |
| `0x06` | 48 | 1.00 | spo2, ppg, accel, 0x05 |
| `0x07` | 20 | 0.33 | all four, slower |
| `0x08` | 16 | 0.08 | all four plus an `0x08` frame |

`0x01`, `0x04` and `0x06` behave identically. Nothing unlocks a faster timer.

### Battery under continuous streaming

Not measured. Battery held at 82% across the 20 s smoke test.

Measuring drain was deliberately skipped: runtime only matters if the stream is
usable, and at 1 Hz it is not. If a firmware or hardware change later clears the
rate gate, run `probe/drain.py` then.

---

## Gate verdict

**Status: FAILED** — measured 2026-09-02 on firmware `RT02CR_3.12.02_260824`.

- [x] Raw accelerometer streaming works (`A1 04` enables, `A1 02` stops)
- [ ] **≥ 25 Hz sustained — FAILED, measured 1.00 Hz**
- [x] Implied loss < 2% — measured 0.00%, nothing is dropped
- [ ] Decoder identified — not pursued, see above
- [ ] Battery runtime — not measured, see above

Per the build spec, a degraded sample rate is not to be worked around: a flick
gesture cannot be classified at 1 Hz, and no downstream cleverness recovers a
signal that was never sampled.

## If the gate fails

1. ~~**Sweep the `0xA1` parameter space** for an accel-only mode.~~ **Done, and
   it did not help.** `0x01` through `0x08` all cap at 1 Hz. The limit is a
   firmware timer, not bandwidth.

2. **Flash a FasterRawValues-style firmware.** The only path that keeps the ring
   form factor. Note that 1 Hz is the stock behaviour on *every* Colmi R02 --
   there is no faster unit to buy instead, so flashing is the only option that
   ends with a working ring.

   The published mod is `R02_3.00.06_FasterRawValuesMOD.bin` from
   [atc1441's repo](https://github.com/atc1441/ATC_RF03_Ring), flashed via the
   [browser OTA tool](https://atc1441.github.io/ATC_RF03_Writer.html). It is
   described only as lowering the raw-value refresh timeout --
   [asked in July 2024](https://github.com/atc1441/ATC_RF03_Ring/issues/7),
   never answered.

   **The OTA transport is confirmed present on this unit.** The writer drives
   service `de5bf728-d711-4e47-af26-65e3012a5dc7` with `de5bf72a` for write and
   `de5bf729` for notify. This ring exposes all three, exactly. It is an
   RF03-family device and the tool can talk to it.

   An earlier note here guessed that the `RT02CR` firmware lineage meant the
   ring was probably unflashable. That was wrong -- the GATT table settles it.

   What remains unverified is the **image**, not the transport: whether
   `R02_3.00.06` is correct for `RT02CR_V3.1` hardware. The writer performs no
   validation ("This tool cannot check if the file is correct!!!") and recovery
   means SWD pads inside a potted ring, so a wrong image is a dead ring.

   The ring also exposes a Tencent `0000fee7` service, a second OTA path common
   on Chinese BLE parts, if the first is rejected.

   **Flash a spare, never the only unit.**

3. **Fall back to the ESP32-S3 + MPU6050 build.** ~$31, and it removes the rate
   question entirely: an MPU6050 does 1 kHz and the sample rate becomes a
   register you write. Costs the ring form factor.

   Parts: XIAO ESP32-S3 (buy 2), MPU6050 ×2, 400–500 mAh LiPo, JST-PH 2.0
   pigtail (the board has bare `BAT+`/`BAT-` pads and no connector — negative
   is the side nearest USB), velcro strap.

**Recommendation:** option 3 if you want certainty, option 2 if the ring form
factor is worth a $20 spare and a two-week wait. Option 2 is a genuine bet now
that the OTA transport is confirmed, not the long shot recorded earlier -- but
it still leaves the 17 mAh battery problem for v2 untouched even when it works.

Buying a different ring instead of flashing is not an option: 1 Hz is the stock
behaviour across the product line.

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

---

## GATT table

Enumerated 2026-09-02 from `COLMI R02_CC07`.

| Service | Characteristics | Purpose |
|---|---|---|
| `6e40fff0-b5a3-f393-e0a9-e50e24dcca9e` | `6e400002` write, `6e400003` notify | Nordic UART — all command traffic |
| `de5bf728-d711-4e47-af26-65e3012a5dc7` | `de5bf72a` write, `de5bf729` notify | **OTA firmware update** — the service atc1441's writer drives |
| `0000180a` | serial, hardware rev, firmware rev, system ID | Device Information |
| `0000fee7` | `0000fea1` notify/read, `0000fea2` indicate/read/write, `0000fec9` read | Tencent — a second OTA/config path |

Reproduce with the GATT dump in the project history, or any BLE explorer.

---

## Firmware analysis (2026-09-02)

Done to answer one question without flashing: **would the mod actually clear the
gate on this ring?** Answer: no, on two independent grounds.

### OTA container format

Header layout, from atc1441's `OTA_Firmware_Header_description.png`:

| Offset | Field |
|---|---|
| `0x00` | start magic |
| `0x04` | CRC32 of firmware from payload start to end |
| `0x08` | length of firmware from payload start |
| `0x10` | firmware version string |
| `0x30` | hardware version string |
| `0x100` | raw firmware |

Parsing every published image plus two pulled from the vendor CDN:

| Image | Magic | Payload | CRC32 verifies |
|---|---|---|---|
| `R02_3.00.06_240523` | `78563412` | `0x100` | yes |
| `R02_3.00.06_FasterRawValuesMOD` | `78563412` | `0x100` | yes |
| `R02_3.00.17_240903` | `78563412` | `0x100` | yes |
| `R01_1.00.01_231229` | `78563412` | `0x100` | yes |
| **`RT02CR_3.12.02_260824`** (this ring) | **`e5c3bd81`** | `0x50` | **no** |
| `RY02_3.00.33_250117` | `e5c3bd81` | `0x50` | no |

**This ring's firmware uses a different container.** Different magic, payload at
`0x50` not `0x100`, and the CRC32 field does not verify as a plain CRC32 of the
payload. Entropy is 6.92 bits/byte with 9.6% zero bytes, against 6.67 and 15.5%
for the `78563412` images, and `RT02CR` and `RY02` share a fixed 16-byte prefix
(`0c00810993270000...f94c6b7e`). That is a wrapper -- encrypted or compressed --
not the plaintext ARM image the older format exposes.

Consequence: **the FasterRawValues patch cannot be ported to this ring.** There
is no plaintext firmware to locate the constant in.

### What the mod actually does

The mod differs from its base by **five bytes**: four are the CRC32 in the
header, and one is the real change.

```
offset 0x9b0a (payload 0x9a0a)
orig: ...40 78 7d 27 28 4d ff 00...   byte = 125
mod : ...40 78 20 27 28 4d ff 00...   byte =  32
```

In Thumb, `7d 27` is `MOVS r7, #125` and `20 27` is `MOVS r7, #32`. It is a
single immediate constant, changed by a factor of **3.91x**.

Two things follow.

**The mod is a 3.91x speedup, not a 25x one.** Whether that clears 25 Hz depends
entirely on the base rate of `R02_3.00.06`, which has not been measured here.
The Edge Impulse capture implies roughly 20-30 Hz on their setup, which would be
self-consistent with a ~5-8 Hz base -- putting a modded `R02_V3.0` ring right at
the gate rather than comfortably past it. Applied to *this* ring's measured
1.00 Hz, 3.91x is 3.9 Hz, nowhere near the gate.

**The constant is an 8-bit immediate, so a custom value is possible** -- `#4`
would be ~31x rather than 3.91x. That is the interesting path, and it is closed
for this ring by the container format above. It would need an `R02_V3.0`-lineage
unit, a rebuilt image, and a recomputed CRC32.

### Vendor firmware CDN

Images are fetchable directly, no app required:

```
http://api2.qcwxkjvip.com/download/ota/<HW_STRING>/<FW_STRING>.bin
```

`RT02CR_V3.1/RT02CR_3.12.02_260824.bin` returns 200 and 138016 bytes -- the
exact stock image for this unit, matching its reported hardware and firmware
strings. Useful for recovery or future analysis.

### Conclusion

The ring path is closed for v1:

1. Stock is 1.00 Hz, 25x short.
2. No `0xA1` parameter changes it.
3. The one published mod is 3.91x, which is not enough even if it applied.
4. It does not apply -- this ring's firmware is in a container we cannot patch.
5. Building a custom mod needs different hardware, a rebuilt image, and a flash
   with no recovery path.

**Use the ESP32-S3 + MPU6050 build.**

---

## CORRECTION (2026-09-06): the ring path is NOT closed

Everything above concluding "this ring cannot be patched" was wrong on one
point, and that point carried the whole conclusion.

[Nosh118/colmi-ring-tools](https://github.com/Nosh118/colmi-ring-tools) targets
`RT02R`/`RT02CR` rings on the 3.1x firmware family — this exact hardware — and
publishes a low-latency firmware for it.

### The error

This document claimed the `e5c3bd81` container was "encrypted or compressed"
and therefore unpatchable. That was inferred from entropy (6.92 bits/byte) and a
CRC32 field that did not verify. **Neither is evidence of encryption**, and the
inference was never tested against the obvious check: does the payload
disassemble?

It does. The nested payload begins at file offset `0x450` and is plain ARM Thumb:

```
0x000450  0048  ldr r0, [pc]
0x000452  0047  bx  r0
```

It is a nested Realtek container with a different header layout, not an opaque
blob. The lesson: entropy is a weak signal for a compiled ARM image, and a
failing checksum means the checksum algorithm is different, not that the
contents are unreadable.

### What the low-latency firmware does

Verified independently against the published binary. SHA-256 matches the
manifest (`2ea1bb08...961c`), and the header declares `hw=RT02CR_V3.1`.

The raw-motion timer patch, at file offset `0x002248`:

| | Instruction | Period | Rate |
|---|---|---|---|
| Stock | `movs r2, #0x7d` / `lsls r2, r2, #3` | 125 × 8 = 1000 ms | 1.0 Hz |
| Low-latency | `movs r2, #0x02` / `lsls r2, r2, #3` | 2 × 8 = 16 ms | **62.5 Hz** |

Same `#N * 8` millisecond idiom identified in the R02 firmware analysis above,
confirming that reading independently.

It also NOPs the A101 / A102 / A105 notification sends, so PPG, SpO2 and the
undocumented `0x05` channel stop competing for BLE airtime while raw motion is
active, and lowers the notify queue retry thresholds. The `a1 03` packet shape
is unchanged, so the decoder in `whip/accel.py` still applies.

### Revised gate outlook

62.5 Hz against a 25 Hz requirement, on the ring already in hand. **Not yet
measured** — this is a claim verified at the byte level, not a capture.

### Before flashing

- Compatibility is declared by prefix `RT02CR_3.12.`; this ring is
  `RT02CR_3.12.02_260824`, their base build is `RT02CR_3.12.00_251205`. In
  family, not an exact version match.
- **No RT02CR recovery or stock-restore image is published** — those exist only
  for RT02R. The restore path is the vendor CDN image
  `RT02CR_V3.1/RT02CR_3.12.02_260824.bin`, already archived.
- Charge above 50%. The flasher enforces a 20% minimum.
- BLE connect from this Mac is currently failing for unrelated reasons. The
  flasher is Web Bluetooth in Chrome and may not be affected.


---

## Connection troubleshooting (resolved 2026-09-06)

**Symptom:** the ring advertises reliably at strong signal, but every connection
attempt times out. Both `bleak` and Chrome's Web Bluetooth hang identically,
with no error from either side.

**Cause:** a stale BLE bond on the Mac. The ring cleared its pairing keys (via
unbinding in QRing and charger resets) while macOS kept the old ones, so link
encryption never completed and the connect stalled silently.

**Fix:** System Settings -> Bluetooth -> forget the ring. Nothing else worked.

Things that did **not** fix it, all tried:

- toggling Bluetooth off and on
- `sudo pkill bluetoothd`
- restarting the Mac -- the bond is on disk and survives
- charger taps and waking the ring
- unbinding from the QRing app
- connecting the instant an advertisement is detected

**A misleading signature:** Chrome's device picker showed the ring twice under
the same name, at `30:32:41:33:CC:07` and `53:20:0D:60:4C:8F`, both marked
Paired. The ring rotates its BLE address, so one entry was the live address and
the other a stale bonded record. From Python this is invisible -- CoreBluetooth
resolves both to one identifier (`3C2FA77E-...`) and picks for you.

**Also worth knowing:** a connect to this ring is legitimately slow. It
advertises infrequently and negotiates a slow connection interval, so service
discovery across four services takes tens of seconds. Every earlier timeout was
set at 10-30s, inside the range a healthy connect can take -- impatience looked
exactly like a broken device. `whip/capture.py` now allows 90s.

### State at the point of connection

| | |
|---|---|
| Firmware | `RT02CR_3.12.02_260824` |
| Hardware | `RT02CR_V3.1` |
| Battery | 46% |

46% is below the 50% floor in `probe/flash.py`. The protocol itself refuses only
below 20%, and the transfer is short, so 46% is not truly dangerous -- but this
ring has no recovery path, which is what the wider margin is for.
