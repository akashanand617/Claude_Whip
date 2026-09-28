# Firmware provenance and sources

The code in this repository is under the repository licence. **These `.bin` files
are not.** No claim is made that vendor firmware bytes are open source; they are
kept for interoperability, repair and research, with hashes in `SHA256SUMS`.

The RT02CR images in `SHA256SUMS` are reproducible from public sources. Run
`./fetch.sh` to rebuild those images and verify all locally present images. The
RT12COL images are reproducible only from the exact, independently repeated
application read archived locally; the vendor API/CDN did not provide this
version. V1 through V7 are separately hash-pinned and reproducible with an
explicit `--revision`. V3 is revoked off-ring. V4-LP2 and V5-LP1 are revoked
after physical tests delivered 49.3976% and 49.0% consecutive duplicate
payloads. V6 is a single-variable SLEEP_ON experiment with one bounded,
identity-verified deployment and a 250/250-distinct source-freshness pass. None
has an enabled app install route. V7 differs from V6 only by the Gesture
LIS2DW12 ODR byte (`CTRL1 0x61` to `0x51`) plus version/container metadata; it
is pinned only for one separately authorized bounded comparison.

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

### `rt12col-stock-1.00.00.bin` — exact local application restore

137,996 bytes · `b180b27a3fddd24db8a49de7c6b0041b94621062187300ceeb79af3d7908c639`

The vendor version endpoint and exact CDN path returned no RT12COL OTA. On
2026-09-27, an idle `RT12COL_V1.0` ring running
`RT12COL_1.00.00_260520` was therefore read through the stock, read-only CD01
diagnostic command. The fixed reader admitted only application partition
`0x826000..0x849fff`, repeated and compared the nested 0x400-byte header, then
read only its declared 136,892-byte payload. Two complete, independent runs
produced the same payload SHA-256
`ffb4cfe62eb34bb32a6a36bd31ff88e3937d155352f0336d84745c1937b08da5`
and application-partition SHA-256
`234718fd22419f96de0f6789a5ed60eb0630205407171871c68e107b494574b7`.
The ring was disconnected afterward; no sensor or flash command was sent.

The installed nested header carried a stale payload digest, so reconstruction
was permitted only after the second complete read independently established the
payload digest. `whip/fwrt12col.py` normalizes that digest, clears `not_ready`,
and adds the standard QRing OTA wrapper. This is an exact application restore,
not a full-chip backup and not a recovery path after BLE/DFU stops advertising.
See [RT12COL_FIRMWARE.md](../docs/RT12COL_FIRMWARE.md).

### RT12COL experimental application lineage — built here

All are 137,996 bytes and derive only from the exact stock restore above:

| Revision | SHA-256 | Disposition |
|---|---|---|
| V1 | `52736f328dd2ea60e284a25438284447b54837e93a0dbcc2da88737968b4483b` | physically booted; source remained stock 25 Hz |
| V2 | `cca729f1b36543bea9d1076c8cf7a39542db608df40e24b9ce2920753e2efab4` | superseded off-ring 200 Hz / ODR/4 draft |
| V3 | `ea5b7a61041d7c64213307018a29f7dc6d803a135afd94d1f1a25178c0ab5026` | revoked: `0x62` is LP3 and renewal re-entered setup |
| V4-LP2 | `21de9507955e102e846932f1d3c1b16e736a73d9d355560af8cf89cc61093d78` | **physically rejected**: 49.3976% paired duplicates; never install |
| V5-LP1 | `23267b5e25e65591349861048c24b72b5cdbc60ea2d583a58315b4cd33d38217` | **physically rejected**: 49.0% paired duplicates; never install |
| V6 sleep fix | `e92c5bc0d2751c3348aeea56ece4e5b5693baf1f6ba45c2a869c2d79729e134d` | deployed; 250/250 distinct at 25.0004 Hz, Health continuity pending |
| V7 100 Hz comparison | `cb815abea8d0ed0b4734b83790a45f632113e0bed4184de606b897727d4e9bd5` | physically deployed; freshness passed, model transfer did not beat V6; recognition only, no app install route |

Reproduce each artifact explicitly:

```sh
python -m probe.build_rt12col_unified --revision v1 --out /tmp/rt12-v1.bin
python -m probe.build_rt12col_unified --revision v2 --out /tmp/rt12-v2.bin
python -m probe.build_rt12col_unified --revision v3-revoked --out /tmp/rt12-v3.bin
python -m probe.build_rt12col_unified --revision v4-lp2 --out /tmp/rt12-v4.bin
python -m probe.build_rt12col_unified --revision v5-lp1 --out /tmp/rt12-v5.bin
python -m probe.build_rt12col_unified --revision v6-sleep-fix --out /tmp/rt12-v6.bin
python -m probe.build_rt12col_unified --revision v7-100hz-compare --out /tmp/rt12-v7.bin
```

`whip/fwrt12col_unified.py` pins the source size/hash, complete instruction
signatures, every source byte, the output hash and a closed change allowlist.
It preserves the stock boot path, GATT registrations, DFU path, partitions and
image size. Health remains the boot/default path; Gesture is temporary and uses
existing A1 and volatile motion-feature commands. V4/V5 select the native
LIS2DW12's +/-4 g, 200 Hz configuration with `CTRL1=0x61` (LP2) or `0x60`
(LP1), then restore exact stock `CTRL1=0x32` (LP3), `CTRL6=0x50` plus the
volatile motion state on explicit stop, disconnect or nominal ten-second lease
expiry. Repeated active `A1 04` only resets the lease byte and bypasses register
writes, the one-shot producer and timer restart. V4 and V5 were physically
flashed, failed freshness at 49.3976% and 49.0% consecutive duplicates, and were
each rolled back to verified V1 identity. Neither may be routed to RT02CR or
offered for installation. See `research/2026-09-27/rt12-v4-lp2-physical/` and
`research/2026-09-27/rt12-v5-lp1-physical/`.

The exact stock RT12 initializer writes `WAKE_UP_THS 0x34=0x41`
(`SLEEP_ON=1`, threshold 1), `WAKE_UP_DUR 0x35=0x40` (`SLEEP_DUR=0`,
`WAKE_DUR=2`) and `CTRL7 0x3f=0x20` (`INTERRUPTS_ENABLE=1`). V4/V5 left this
auto-inactivity configuration active. Their low-motion captures contain no
motion-triggered wake evidence, but their almost exact pair pattern is
consistent with 12.5 distinct values/s. V6 retains V4-LP2 and changes only
Gesture SLEEP_ON ownership: entry writes 0x34=0x01, while explicit stop,
disconnect and lease expiry restore 0x34=0x41 through the common helper. One
user-authorized transfer passed DFU CHECK and rebooted as V6 on exact hardware.
Its first bounded lease delivered 250/250 distinct payloads at 25.0004 Hz with
zero duplicate transitions; a 7.09 g repeat also had zero consecutive
duplicates. Two physical lease renewals preserved 25.0065 Hz and 501/501
distinct samples with clean boundaries. The low-motion V4/V5 pair failure is
absent; the current model still misclassified an isolated snap as `flick left`.
See
`research/2026-09-27/rt12-activity-hypothesis/`.

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
