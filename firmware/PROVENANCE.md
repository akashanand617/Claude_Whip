# Firmware provenance and sources

The code in this repository is under the repository licence. **These `.bin` files
are not.** No claim is made that vendor firmware bytes are open source; they are
kept for interoperability, repair and research, with hashes in `SHA256SUMS`.

Every current image listed in `SHA256SUMS` is reproducible from a public source.
Run `./fetch.sh` to rebuild those images and verify their hashes. Superseded
experimental artifacts are recorded separately below and are not rebuilt.

Detailed reverse-engineering and mode-switching handoff:
[FIRMWARE_RESEARCH.md](../docs/FIRMWARE_RESEARCH.md). The
[2026-09-22 evidence archive](research/2026-09-22/README.md) preserves completed
reviews, mapping tools, hardware captures and exact experimental patch bytes.

---

## Sources

All links verified 2026-09-09.

### `rt02cr-stock-3.12.02.bin` — vendor stock, the recovery image

```
http://api2.qcwxkjvip.com/download/ota/RT02CR_V3.1/RT02CR_3.12.02_260824.bin
```

138,016 bytes · `b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0`

Unmodified Colmi/QRing vendor image, served from their OTA CDN. The URL pattern
is `download/ota/<HARDWARE_STRING>/<FIRMWARE_STRING>.bin`, so any ring's stock
image can be fetched given the two strings `probe/scan.py` prints. Directory
listing is blocked (403), so you need the exact filename.

Upstream publishes no RT02CR stock image, which is why this one is archived here:
without it there is no recovery path for this hardware.

### `rt02cr-low-latency.bin` — upstream patched image

```
https://raw.githubusercontent.com/Nosh118/colmi-ring-tools/main/site/public/firmware/rt02cr-low-latency.bin
```

137,540 bytes · `2ea1bb08826891604fb714a3820c859d77f52f8d22f1d9a870db10cd5fbffe34`

From [Nosh118/colmi-ring-tools](https://github.com/Nosh118/colmi-ring-tools),
which reverse-engineered this firmware family. Their notes are the source for the
Realtek container format, the DFU protocol and the raw-motion timer.

Supporting files:

```
manifest.json      https://raw.githubusercontent.com/Nosh118/colmi-ring-tools/main/site/public/firmware/manifest.json
FIRMWARE-LICENCE   https://raw.githubusercontent.com/Nosh118/colmi-ring-tools/main/FIRMWARE-LICENCE.md
browser flasher    https://nosh118.github.io/colmi-ring-tools/
```

Their licence asks that redistributors preserve a provenance record alongside the
manifest. That is what this file is.

### `rt02cr-33hz.bin` and `rt02cr-25hz.bin` — built here

Not downloadable; built from `rt02cr-low-latency.bin` by changing one byte:

```sh
python -m probe.build --immediate 3    # 33.33 Hz  -> rt02cr-33hz.bin
python -m probe.build --immediate 4    # 25.00 Hz  -> rt02cr-25hz.bin
```

The raw-motion timer immediate at file offset `0x2248`. `whip/fwbuild.py` then
refreshes the payload SHA-256, clears the Realtek `not_ready` bit and recomputes
the outer body sum, without which the image transfers but does not boot.

`rt02cr-25hz.bin` is the one that passes the M0 gate and is currently flashed.

### `rt02cr-25hz-optical-off-v2-experimental.bin` — unflashed research candidate

Built locally on 2026-09-22 from the exact hash-pinned 25 Hz image:

```sh
python -m probe.build_optical_off --out firmware/rt02cr-25hz-optical-off-v2-experimental.bin
```

137,540 bytes · `0d18a0fa860d58ab8f984b5f542f45dac105241f47bf1c2af41321eb0431e14c`

The builder refuses existing output files and unknown bases. It changes 81
payload bytes plus derived container checksums: optical sensor-enable returns
without starting optics, ordinary VC30F RUN becomes STOP, raw start explicitly
wakes the accelerometer, and its idle request is deferred only during connected
raw mode 4. Stop or disconnect releases that hold. V2 additionally clears raw
mode 4 and stops/deletes its producer timer on disconnect, releasing the
mode-4 deep-sleep veto. Reconnect requires a new `A1 04`. Rate, range and DFU are
unchanged. Optical health measurements and optical indicators are disabled
globally, not only during streaming.

This is **not hardware validated or the default flash target**. Pinning its hash
does not certify safety. Boot behavior, LED darkness, fresh motion, start/stop,
disconnect/reconnect and battery drain still require tests on this candidate.
The successful one-minute optical-off command trial ran on the original 25 Hz
firmware, not on this image. See [the investigation record](../docs/LED_FIX.md).

The preserved, superseded `rt02cr-25hz-optical-off-experimental.bin` has hash
`f862e5bb1b65ff43d6133524d20fd82bcbc072bd8a1245a9927367993a213f27` (47 payload
bytes changed). It lacks disconnect timer/mode cleanup. It is no longer in the
current build/hash manifest; the current builder does not reproduce it, and the
candidate identity validator rejects it. Neither version has been flashed.
Fable's separate one-halfword candidate (`3c57b73e…`) is also superseded; its
verification results must not be represented as verification of either image here.

### Prior art, not redistributed here

The R02 (2024) lineage, whose plaintext container first made this tractable:

```
FasterRawValues mod  https://raw.githubusercontent.com/atc1441/ATC_RF03_Ring/main/R02_3.00.06_FasterRawValuesMOD.bin
its stock base       https://raw.githubusercontent.com/atc1441/ATC_RF03_Ring/main/OTA_firmwares/R02_3.00.06_240523.bin
repository           https://github.com/atc1441/ATC_RF03_Ring
OTA writer           https://atc1441.github.io/ATC_RF03_Writer.html
```

**These do not work on RT02CR hardware** — different container (`78563412` vs
`e5c3bd81`), payload at `0x100` not `0x450`. Listed because the R02 analysis is
what identified the `movs rN,#imm / lsls rN,rN,#3` timer idiom that the RT02CR
patch depends on.

Other references:

```
protocol docs        https://colmi.puxtril.com/commands/
python client        https://github.com/tahnok/colmi_r02_client
raw sensor streaming https://github.com/edgeimpulse/example-data-collection-colmi-r02
```

---

## Removal

If a rights holder asks for an artefact to be removed: delete the binary, keep
the hash and this provenance record, and rely on `fetch.sh` for anyone who needs
to reconstruct it from the original source.
