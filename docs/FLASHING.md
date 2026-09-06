# Flashing the low-latency firmware

Takes the ring's raw motion stream from **1.00 Hz to 62.5 Hz**, clearing the M0
gate of 25 Hz.

Firmware from [Nosh118/colmi-ring-tools](https://github.com/Nosh118/colmi-ring-tools).
Both images are archived in `firmware/` so a flash never depends on a URL still
resolving.

---

## Read this first

Flashing can brick the ring. What limits the damage here:

- The image declares `RT02CR_V3.1`, matching this ring exactly.
- Its SHA-256 is pinned in `tests/test_fwimage.py`, so an upstream change breaks
  the build instead of reaching the hardware.
- The patch has been read at instruction level, not taken on trust.
- The stock image is archived locally as a restore path.

What does not:

- **There is no published RT02CR recovery image.** RT02R has one; this ring does
  not. If DFU itself stops responding, recovery means SWD pads inside a potted
  ring, which is not practical.
- The upstream project is new and has few users. The binary verifies, but you
  are the test population.
- Their base build is `RT02CR_3.12.00_251205`; this ring runs
  `RT02CR_3.12.02_260824`. Same family and covered by their declared
  `RT02CR_3.12.` prefix rule, but not an exact version match.

**This is a real risk on a ring you own. Nothing downstream in this project
requires it** -- M2 through M6 need no hardware at all.

---

## 1. Verify the images offline

```sh
source .venv/bin/activate
python -m probe.firmware firmware/rt02cr-low-latency.bin \
    --hardware RT02CR_V3.1 \
    --expect-sha 2ea1bb08826891604fb714a3820c859d77f52f8d22f1d9a870db10cd5fbffe34
```

Expect `hardware string 'RT02CR_V3.1'  [MATCH]` and one timer site at
**16 ms / 62.50 Hz**. If either is missing, stop.

```sh
python -m pytest tests/test_fwimage.py -q
```

Compare against stock to see exactly what changes:

```sh
python -m probe.firmware firmware/*.bin --hardware RT02CR_V3.1
```

Stock's fastest raw motion period is 1000 ms. The low-latency image adds a 16 ms
site that stock does not have. Both contain an unrelated 24 ms site, so "has a
fast timer" alone would not distinguish them -- the 16 ms site is the patch.

## 2. Prepare the ring

- **Charge above 50%.** The flasher enforces a 20% minimum; do not flash near it.
- **Force-quit QRing** and turn phone Bluetooth off. The ring accepts one
  connection at a time.
- **Do not bind the ring in QRing.** Binding preceded the BLE connect failures
  documented in `HARDWARE.md`.
- Keep the ring within a few centimetres of the machine for the whole transfer.

## 3. Flash

Two routes. **Try the browser first** -- its transfer path has been exercised
against real hardware; ours has not.

### 3a. Local flasher (`probe/flash.py`)

```sh
python -m probe.flash firmware/rt02cr-low-latency.bin --dry-run   # always first
python -m probe.flash firmware/rt02cr-low-latency.bin
```

`--dry-run` builds and validates every byte that would be transmitted, confirms
the 135 chunks reassemble to the original image, and never opens a connection.

The live run refuses unless all of these hold, in order: the image hash matches
its pinned value, the ring's hardware string equals the image's, the ring's
firmware is within the catalogue's compatibility rule, and battery is at or
above 50%. It then asks you to type `FLASH`. Every frame is acknowledged before
the next is sent, and any status other than `ok` aborts immediately.

**The on-device transfer path is unproven.** Frame construction is verified
against upstream's published CRC-16 and checksum-16 for this exact image, but
the sequencing has been reasoned about rather than observed. Treat the first
real run as an experiment.

If the ring shows more than one address in a picker, use the one currently
advertising -- this ring rotates its BLE address, and stale bonded entries for
old addresses never answer.

### 3b. Browser flasher

Open <https://nosh118.github.io/colmi-ring-tools/> in Chrome (Web Bluetooth;
Safari and Firefox will not work).

1. Connect, and confirm **Device Information** reports `RT02CR_V3.1` and a
   `RT02CR_3.12.*` firmware string. **If the hardware string is anything else,
   stop.**
2. Select **RT02CR low-latency firmware**. Do not pick an RT02R image.
3. Confirm the transfer and do not refresh, sleep the machine, or move the ring
   until it completes.

Local BLE from Python has been failing on this machine for unrelated reasons.
The flasher uses the browser's own Bluetooth stack, so it may work regardless --
try it before debugging anything else.

## 4. Verify the gate

```sh
python -m probe.scan
```

The firmware string should have changed.

```sh
python -m probe.stream --duration 60 --label postflash_idle --stationary
python -m probe.stream --duration 600 --label postflash_typing
```

Exit code 0 means the gate passed. Expect roughly:

| | Before | After |
|---|---|---|
| Accel rate | 1.00 Hz | ~62.5 Hz |
| Channels | spo2, ppg, accel, `0x05` | accel only |
| Interval | ~1023 ms | ~16 ms |

The other channels disappear because the patch NOPs the A101 / A102 / A105
notification sends, freeing BLE airtime for motion.

Then record the real numbers in `HARDWARE.md` and mark M0 passed or failed on
the evidence.

## 5. Things that only become answerable after the flash

- **The 12-bit decoder.** At 1 Hz a six-orientation stationary capture was
  impractical. At 62.5 Hz it takes a minute:
  `python -m probe.stream --duration 60 --label decoder --stationary`, resting
  the ring on each of its six faces for ten seconds. Six orientations, not one --
  a single orientation cannot distinguish the candidates.
- **Battery life.** `python -m probe.drain --max-hours 2`. This decides whether
  live capture in v2 is viable at all; a 17 mAh cell driving a 62.5 Hz stream is
  the worst case it will ever see.
- **Sustained loss.** 62.5 Hz on one channel is ~62 packets/s. The patch lowers
  the notify queue retry thresholds to help, but the ten-minute worn capture is
  what proves it holds up.

## Recovery

If the ring still connects over BLE but behaves badly, flash the archived stock
image:

```sh
python -m probe.flash firmware/rt02cr-stock-3.12.02.bin --init-type 1
```

or upload `firmware/rt02cr-stock-3.12.02.bin` through the browser tool's
custom-file option. That image is hash-pinned in `firmware/SHA256SUMS`, so the
verification does not lapse at the moment it matters most.

That is `RT02CR_3.12.02_260824`, pulled from the vendor CDN at
`http://api2.qcwxkjvip.com/download/ota/RT02CR_V3.1/RT02CR_3.12.02_260824.bin`
and matching this ring's original firmware string exactly.

If the ring stops connecting entirely, there is no recovery path. Accept it and
fall back to the ESP32-S3 + MPU6050 build described in `HARDWARE.md`.
