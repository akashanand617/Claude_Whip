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

Current-state correction, 2026-09-23: the installed image is V2 optical-off,
not original 25 Hz and not unified. The stock archive below is an application
OTA restore image, not a complete factory backup or a demonstrated recovery
route after BLE/OTA fails to boot. See the
[memory/recovery boundary](../docs/UNIFIED_RESOURCE_BUDGET.md).

---

## Sources

All links verified 2026-09-09.

### `rt02cr-stock-3.12.02.bin` — vendor stock, application OTA restore image

```
http://api2.qcwxkjvip.com/download/ota/RT02CR_V3.1/RT02CR_3.12.02_260824.bin
```

138,016 bytes · `b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0`

Unmodified Colmi/QRing vendor image, served from their OTA CDN. The URL pattern
is `download/ota/<HARDWARE_STRING>/<FIRMWARE_STRING>.bin`, so any ring's stock
image can be fetched given the two strings `probe/scan.py` prints. Directory
listing is blocked (403), so you need the exact filename.

This exact RT02CR stock application is archived for restoration through a
working OTA path. It does not include the ring's complete boot/ROM-patch/upper-
stack image or establish recovery from a failed application boot.

### `rt02cr-25hz-health-default-gesture-v1-experimental.bin` — built here

137,540 bytes · `b1070bed755ce14936501431e379c6c47570ce747265fe0b6af0e87553eb2dc4`

Built only from the exact pinned `rt02cr-25hz.bin` SHA-256
`f13e63d3fdef3b10aa20fd4e0672077b66f60bb19c689ef64053840e4d35d3d9`
by `python -m probe.build_unified_mode --out <new path>`. The source, exact
patch map, ARM helpers, proof tests and remaining physical gates are in
[UNIFIED_MODE_V1.md](../docs/UNIFIED_MODE_V1.md). It is bundled for a bounded
app-driven validation but has not been flashed or device-validated.

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

`rt02cr-25hz.bin` passed the M0 gate and was subsequently replaced on the ring
by the optical-off V2 image below.

2026-09-23 reference recheck: all five current hashes matched this record and
`SHA256SUMS`. Byte comparison of the entire payload (`0x450..EOF`) confirms
that low-latency 50 Hz, 33 Hz and original 25 Hz differ only at `0x2248`, with
immediates 2, 3 and 4 respectively. Their other payload bytes, including Health
code, are identical. This is code/layout equivalence outside that timer byte,
not proof of identical scheduling, health accuracy or physical continuity.
The distinct stock 3.12.02 map and V2's global optical disable remain separate.

### `rt02cr-25hz-optical-off-v2-experimental.bin` — installed experimental V2

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

V2 was subsequently deployed and native motion/visible-darkness trials were
recorded; see [the deployment record](../docs/FIRMWARE_RESEARCH.md). Those tests
are not proof of health continuity, complete recovery or unified-image safety.
Optical health is globally disabled on V2. The earlier one-minute command-
workaround trial ran on original 25 Hz and must not be relabeled as a V2 test.

The preserved, superseded `rt02cr-25hz-optical-off-experimental.bin` has hash
`f862e5bb1b65ff43d6133524d20fd82bcbc072bd8a1245a9927367993a213f27` (47 payload
bytes changed). It lacks disconnect timer/mode cleanup. It is no longer in the
current build/hash manifest; the current builder does not reproduce it, and the
candidate identity validator rejects it. V1 was not flashed; V2 was later
deployed as described above.
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
