# RT12COL Health-default / temporary-Gesture firmware

## V10 keyboard-primary HID maps — 2026-09-29

V10 is an offline-only descriptor-order correction on top of V9. Physical iOS
logs after a successful V9 forget/re-pair show the exact map and ID4 Input
reference were read, followed by `Ignoring service with secondary keyboard
usage`. The iPhone map still began with Mouse ID1, making Mouse primary even
though V9 appended its Keyboard ID4 descriptor. Keyboard actions were tried
only before the re-pair, so classification—not sender delivery—is the proven
V9 defect.

V10 places the exact V9 81-byte Keyboard descriptor first in each complete
selectable map, followed by the byte-exact original 66-byte Mouse or 82-byte
Digitizer descriptor. The full maps remain exactly 147 and 163 bytes. Report
IDs, fields, ID4 sender/release, wheel helper, bridge, motion/lease code, A2
actions, Boot Mouse characteristic, `[0x04, 0x01]` Report Reference and GATT
database are unchanged.

Artifact:
`rt12col-25hz-health-default-gesture-v10-hid-keyboard-primary-experimental.bin`,
version `RT12COL_1.00.10_260929`, SHA-256
`7e04ae9973341233d2dbbe06fc6eb4c228aab625b1c3687462416edbe7d21ce2`.
Builder revision is `v10-hid-keyboard-primary-experimental`. No phone deploy,
BLE connection, DFU or ring write occurred while building it. Offline proofs
pin the exact artifact and map ordering; iOS interpretation remains a physical
gate.

## V9 keyboard + mouse HID — 2026-09-29

V9 is a size-neutral, offline-only successor to V8. It retains the selected V6
200 Hz/wide-band Gesture source, lease and corrected 3B route. It adds a bounded
wheel helper, replaces the exact three-byte ID4 sender, and replaces both exact
81-byte ID4 map copies with ten Consumer bits plus an 8-bit Keyboard Array.
The existing HID service and characteristics are unchanged. No RAM, task,
timer, partition or image-size growth is introduced.

The guarded iOS catalog now offers V9 and retains V8 as rollback. V9 commands
are enabled only after a complete 707-byte changed-region fingerprint. A report
map change may require forgetting and reconnecting the ring so iOS discards its
cached V8 descriptor. Keyboard and Consumer controls do not use AssistiveTouch;
mouse wheel/drags may still require iPhone pointer support. No phone deploy,
BLE connection, DFU or physical validation occurred. A first bounded deployment
must validate pairing/rebond, keyboard and Consumer interpretation, wheel
direction/amount, session/renewal coexistence, Health return, optical history,
steps/sleep and rollback before any safety claim.

## V8 HID bridge — 2026-09-29

V8 is a guarded, app-installable experimental candidate based on the selected V6
200 Hz/wide-band source, not V7. It adds one checksum-valid UART command,
`A2 <action>`, that calls the unchanged stock HID mouse-drag and Consumer Control
senders. It adds no service, report descriptor, RAM, task, timer, partition or
image size. At the user's 2026-09-29 request, the iOS firmware-maintenance
catalog exposes this exact bundle behind the existing identity, history,
Health-mode, battery, charging, hash, header and destructive-confirmation gates.
It also supports the same-mode V7→V8 upgrade. See
[RING_HID_RESEARCH.md](RING_HID_RESEARCH.md).

The corrected bridge explicitly restores the stock 3B handler route displaced
by the dispatcher hook and uses mouse transport 1 for iPhone swipes. An earlier
unflashed draft omitted the 3B taken branch and selected touch transport 2; it
is revoked and rejected by the exact bridge fingerprint. iPhone swipes require
AssistiveTouch. A2 itself is neither authenticated nor Gesture-gated in
firmware; those restrictions are enforced by the exact-fingerprint app path.

Nothing in this section authorizes DFU, BLE device commands, or a phone deploy.
The current ring still runs V7. Before V8 can be considered for a bounded
deployment, review the static bridge proof and repeat the existing identity,
source freshness, renewal, Health-return, optical/steps/sleep and rollback
gates, then validate every enabled HID action on the physical iPhone.

Status: **no corrected candidate is validated or approved for general
installation.** V3 is revoked off-ring.
V4-LP2 and V5-LP1 were both physically tested on 2026-09-27 and are also
**revoked**: they delivered 49.3976% and 49.0% consecutive duplicate payloads
in almost exact pair patterns. Each was immediately rolled back to verified V1.
V1 boots and streams, but retains the stock 25 Hz source and previously produced
17.46% consecutive duplicate motion payloads. Static analysis then confirmed
that stock enables LIS2DW12 activity/inactivity auto-sleep. V6 is the resulting
single-variable SLEEP_ON experiment. It has one bounded deployment with DFU
CHECK, reboot and identity verified. Its first bounded source test passed with
zero duplicates at 25.0004 Hz. V7 changes only Gesture CTRL1 from `0x61` to
`0x51` (200 to 100 Hz LP2). It was subsequently deployed for a bounded source
and waveform comparison and remains installed as of 2026-09-28. It passed
freshness but transferred worse to the frozen RT02 model in two short snap
sessions. V7 remains absent from the app install catalog; V6 is the preferred
rollback and cross-ring baseline.

This firmware family is only for exact `RT12COL_V1.0` hardware running a known,
fingerprinted RT12COL image. It must never be routed to RT02CR.

## Exact artifacts

| Artifact | Device version | Status | SHA-256 |
|---|---|---|---|
| Stock restore | `RT12COL_1.00.00_260520` | rollback application image | `b180b27a3fddd24db8a49de7c6b0041b94621062187300ceeb79af3d7908c639` |
| V1 | `RT12COL_1.00.01_260927` | installed; source remained stock 25 Hz | `52736f328dd2ea60e284a25438284447b54837e93a0dbcc2da88737968b4483b` |
| V2 | `RT12COL_1.00.02_260927` | superseded off-ring draft | `cca729f1b36543bea9d1076c8cf7a39542db608df40e24b9ce2920753e2efab4` |
| V3 | `RT12COL_1.00.03_260927` | **revoked**: wrong LP-mode interpretation and unsafe renewal path | `ea5b7a61041d7c64213307018a29f7dc6d803a135afd94d1f1a25178c0ab5026` |
| V4-LP2 | `RT12COL_1.00.04_260927` | **revoked after physical test**: 49.3976% paired duplicates; not installable | `21de9507955e102e846932f1d3c1b16e736a73d9d355560af8cf89cc61093d78` |
| V5-LP1 | `RT12COL_1.00.05_260927` | **revoked after physical test**: 49.0% paired duplicates; not installable | `23267b5e25e65591349861048c24b72b5cdbc60ea2d583a58315b4cd33d38217` |
| V6 sleep fix | `RT12COL_1.00.06_260927` | physically passed freshness/renewal; preferred cross-ring baseline and rollback | `e92c5bc0d2751c3348aeea56ece4e5b5693baf1f6ba45c2a869c2d79729e134d` |
| V7 100 Hz comparison | `RT12COL_1.00.07_260927` | currently installed; freshness passed, frozen-model transfer did not beat V6; no app install route | `cb815abea8d0ed0b4734b83790a45f632113e0bed4184de606b897727d4e9bd5` |
| V8 HID bridge | `RT12COL_1.00.08_260929` | corrected guarded app target; V6 signal source, restored 3B route, A2→stock HID; not yet flashed | `a8be4e97051b25adffaadfd7f23632c54f396c6711960edf7dd0bfce9d683fc6` |
| V9 keyboard + mouse HID | `RT12COL_1.00.09_260929` | guarded app target; changed ID4 map, keyboard array and bounded wheel; not yet flashed | `27fdfa741407da90def1a1124f8f551503d519d8ef730d30e61fa195476339ef` |
| V10 keyboard-primary HID | `RT12COL_1.00.10_260929` | offline full-map reorder addressing iOS secondary-keyboard rejection; not physically validated | `7e04ae9973341233d2dbbe06fc6eb4c228aab625b1c3687462416edbe7d21ce2` |

All are 137,996-byte application OTA images, declare `RT12COL_V1.0`, and use
DFU init type `0x04`. The stock restore is not a full-flash dump or wired
recovery image.

## Correct LIS2DW12 mode decode

LIS2DW12 `CTRL1.LP_MODE` is the low two bits. Per datasheet Table 31,
`00/01/10/11` select low-power modes 1/2/3/4. Therefore both stock `0x32` and
the revoked V3 value `0x62` select **LP mode 3**, not LP mode 2. At the widest
bandwidth setting, LP1/LP2/LP3/LP4 are 3200/720/360/180 Hz respectively.

| State/build | `CTRL1 0x20` | ODR | Low-power mode | Widest bandwidth | `CTRL6 0x25` |
|---|---:|---:|---:|---:|---:|
| Stock Health | `0x32` | 25 Hz | LP3 | 360 Hz | `0x50` (+/-4 g, ODR/4) |
| Revoked V3 | `0x62` | 200 Hz | LP3 | 360 Hz | `0x10` (+/-4 g, widest) |
| V4-LP2 | `0x61` | 200 Hz | LP2 | 720 Hz | `0x10` (+/-4 g, widest) |
| V5-LP1 | `0x60` | 200 Hz | LP1 | 3200 Hz | `0x10` (+/-4 g, widest) |
| V6 sleep fix | `0x61` | 200 Hz | LP2 | 720 Hz | `0x10` (+/-4 g, widest) |
| V7 comparison | `0x51` | 100 Hz | LP2 | 720 Hz | `0x10` (+/-4 g, widest) |
| V8 HID bridge | `0x61` | 200 Hz | LP2 | 720 Hz | `0x10` (+/-4 g, widest) |

V5-LP1 was designed as the resolution comparison and V4-LP2 as the bandwidth/
resolution comparison. Physical testing disqualified both. They retained 25 Hz
BLE delivery (`#4` raw timer), but only about half the payloads were new. The
register interpretation is pinned to
ST's [LIS2DW12 datasheet](https://www.st.com/resource/en/datasheet/lis2dw12.pdf)
and [AN5038](https://www.st.com/resource/en/application_note/dm00401877-lis2dw12-alwayson-3d-accelerometer-stmicroelectronics.pdf).

## Stock activity/inactivity configuration and V6

The exact stock initializer directly writes:

| Register | Stock value | Decoded fields |
|---|---:|---|
| `WAKE_UP_THS 0x34` | `0x41` | `SLEEP_ON=1`; wake threshold 1 = FS/64 = 62.5 mg at +/-4 g |
| `WAKE_UP_DUR 0x35` | `0x40` | `SLEEP_DUR=0`; `STATIONARY=0`; `WAKE_DUR=2` |
| `CTRL7 0x3f` | `0x20` | `INTERRUPTS_ENABLE=1` |

The writes occur at calls `0xca16`, `0xca0a` and `0xca2e`. Other fixed CTRL7
writes are `0x00` at `0xc036`, `0xc644` and `0xc9fe`, and `0x20` at `0xc606`.
The stock read/modify/write at `0xc5ca..0xc5e2` clears only bit 7 of 0x34 and
therefore preserves `SLEEP_ON` at bit 6.

The proposed timeout explanation required one correction: ST defines
`SLEEP_DUR` as 512/ODR per LSB; `WAKE_DUR`, not `SLEEP_DUR`, uses 1/ODR per
LSB. Since stock programs `SLEEP_DUR=0`, there is no nonzero sleep timeout that
becomes eight times shorter at 200 Hz. The configuration still enables
automatic activity/inactivity mode, so an immediate or persistent inactivity
state remains a viable explanation for the exact 12.5-distinct-values/s pair
pattern. The register fields and timing units are pinned to ST's
[register definitions](https://github.com/STMicroelectronics/lis2dw12-pid/blob/master/lis2dw12_reg.h)
and [official driver](https://github.com/STMicroelectronics/lis2dw12-pid/blob/master/lis2dw12_reg.c).

The archived V4/V5 captures cannot prove a motion-triggered transition because
both were essentially stationary: total axis spans were below 0.04 g and the
largest change between distinct runs was below 0.03 g. Three singleton runs in
each capture were stream startup. V4's only later singleton was about 0.0115 g;
V5's only interior singleton was not a high-motion transition, and another was
the final packet. Singletons therefore do not systematically align with motion.
The captures are nevertheless consistent with persistent inactivity: roughly
12.5 distinct payloads/s delivered as pairs at 25 notifications/s.

V6 changes V4 at one semantic boundary only. Gesture configuration first writes
`WAKE_UP_THS=0x01`, clearing only SLEEP_ON, then retains V4's `CTRL6=0x10` and
`CTRL1=0x61`. Explicit stop, disconnect and lease expiry use the same common
helper and restore stock `CTRL1=0x32`, `CTRL6=0x50`, and finally exact stock
`WAKE_UP_THS=0x41`. Active `A1 04` renewal remains lease-only. The full audit,
capture arithmetic and hashes are archived under
`firmware/research/2026-09-27/rt12-activity-hypothesis/`.

## Fully decoded RT02 reference source

The RT02 `rt02cr-25hz.bin` STK8321 initialization is exact:

| Register | Value | Decoded behavior |
|---|---:|---|
| `POWMODE 0x11` | `0x74` | LOWPOWER enabled, equidistant sampling, 10 ms sleep |
| `BWSEL 0x10` | `0x0f` | nominal 1 kHz bandwidth setting |
| `FIFO_CONFIG 0x3e` | `0xc8` | stream mode, every fourth sample, XYZ |
| `RANGESEL 0x0f` | `0x05` | +/-4 g |

The code trace settles how those samples reach A1/03:

1. raw callback `0x1ec0..0x1ec8` requests one XYZ frame from `0xcbda`;
2. active reader `0xcbee` calls hardware drain `0xc228`;
3. chip ID `0x23` selects the STK branch at `0xc2fe`;
4. that branch reads FIFO status register `0x0c`, bounds the count to 32,
   multiplies it by six bytes, and reads the block from `FIFODATA 0x3f` through
   I2C helper `0xbc12`;
5. the reader returns the newest cached six-byte frame.

The RT02 raw path therefore reads **FIFO data**, not live registers
`XOUT1..ZOUT2 0x02..0x07`. `tests/test_fwrt12col_unified.py` pins every decisive
instruction and register value so this conclusion cannot silently regress.

The STK branch does not write `DATASETUP 0x13` during reset, initialization or
active configuration. Enumeration of all 41 direct calls to the exact register
writer in both stock and 25 Hz images finds no fixed `0x13` write. The one
dynamic register-write route is the existing host command dispatcher, not an
initialization call. The active source therefore uses reset-default
`DATA_SEL=0`, the filtered data path; the public 352 Hz unfiltered experiment is
not the source represented by the RT02 training corpus.

The preliminary STK table's nominal 75 Hz entry is inconsistent with the live
path if the documented every-fourth FIFO interval applies: the two long RT02
controls deliver a fresh retained frame on more than 99.94% of 25 Hz callbacks,
which requires approximately 100 or more source frames/s. This is an empirical
lower-bound argument, not proof of an exact 100 Hz source clock; revision-
specific behavior, equidistant-mode timing and the undocumented `0x5e=0xc0`
write remain unresolved.

The same payload-equality metric used on RT12 V1 was also applied to archived
RT02 controls. The steady measured phases of two 30-minute LED-off runs each
contained 45,002 packets at 25.0008 notifications/s, with 0.0511% and 0.0556%
consecutive duplicate XYZ payloads. A ten-minute phase measured 0.0333%. Older
cached-source workaround trials are deliberately excluded. These archive
results establish the expected scale. There is no separate RT02 control ring;
the user designated these completed exact-identity runs as the control, so a
new physical recapture is not a gate. The hashes, exact counts, cleanup records,
and reproducible command are archived under
`firmware/research/2026-09-27/rt02-duplicate-control/`. The earlier 60-second
search found no RT02 and sent no command; it remains chronology only.

The corresponding cross-family scale and acquisition contract is frozen in
[GESTURE_SIGNAL_CONTRACT.md](GESTURE_SIGNAL_CONTRACT.md). In particular, the
nominal 12-bit-versus-14-bit distinction does not justify a fitted gain or an
RT02 low-nibble quantizer: both sensors encode nominally 8192 packet counts/g at
+/-4 g, and actual RT02 packets empirically use every low-bit residue.

## Lease-only repeated `A1 04`

V4/V5/V6 distinguish first entry from renewal in the A1 handler itself.

- On first entry (raw mode is not 4), the stock ownership path runs, the
  selected Gesture registers are written, the original one-shot producer runs,
  and the stock 25 Hz timer starts.
- When Gesture is already active (`active=1` and raw mode is 4), `A1 04` writes zero only to
  the lease counter and jumps directly to the handler epilogue. It performs no
  ownership call, sensor-register write, one-shot producer call, timer create,
  or timer restart.

The exact 22-byte entry gate is checked structurally and executed under Unicorn
for every corrected build. The active-renewal path must reach `0x22ee` with no
calls and only the lease byte changed; first entry must still reach the original
path at `0x2240`.

The app no longer treats a successful UART write as renewal success. It waits
out the UART throttle, snapshots ten packets immediately before the exact
`A1 04` write, and arms the post-boundary collector before `writeUART` can
return motion reentrantly. This occurs only while the exact Gesture session is
active and recently processed. Ten post-renewal packets then gate median
spacing, the exact boundary gap, maximum gap, and consecutive duplicates
relative to the pre-boundary baseline. A gap, timeout, or new duplicate burst
rejects renewal and immediately requests the audited `A1 05` / `A1 02` Health
return; the firmware lease is the final backstop.

## Bounded ownership and fail-closed return

V4/V5 reuse 220 bytes of the dormant `WHO_AM_I=0x48` branch
(`0xc064..0xc13f`) for Cortex-M0+ helpers. Physical device ID `0x44` is routed
past that dormant branch. The source in `firmware/rt12col_gesture_helpers.S`
builds independently for `CTRL1=0x61` and `CTRL1=0x60`; the builder pins compiled
bytes, every replaced source byte, source/output hashes, unchanged image size,
and a closed allowlist.

Each 25 Hz callback advances the lease. At 250 callbacks (nominally ten seconds)
without renewal, the common restore path:

1. clears raw active/mode/lease state;
2. releases exclusive raw owner `0x40`;
3. stops/deletes the raw timer;
4. restores exact stock `CTRL1=0x32`, then `CTRL6=0x50`;
5. applies stock volatile motion state `{mode=0,sensitivity=1,arg=0}` and its
   normal release follow-up when the state changed.

`A1 05`, disconnect while mode 4 is active, and lease expiry call the same
restore helper. `A1 02` and host hold-release remain idempotent cleanup.
V6's equivalent common helper adds the exact stock `WAKE_UP_THS=0x41` restore
after CTRL1/CTRL6 on all three exit paths.

## Preserved behavior and limits

The corrected candidates are size-preserving patches. They retain stock boot,
GATT/UART/DFU services, partitions, image size, native LIS2DW12 reader, Health
boot/default state, notification framing, and the protected RT12 DFU reassembly
timer. The A1 stream still suppresses optical/subtype reports and retains A1/03
motion.

Off-ring proof does not establish optics-off behavior, Health restart,
step/sleep continuity, or OTA rollback. The app now recognizes an already
installed, byte-fingerprinted V6 or V7 so the same lease transport and signal
adapter can be used; every changed application byte in either image is covered
by 335 bounded CD01 comparison bytes. App installation remains disabled for
both. Revoked V3 is retained only for authentication/recovery messaging; V4 and
V5 have no descriptor and remain unavailable. Recognition does not make V7 a
general install option.

## Reproducible build

Every revision must be named explicitly:

```sh
python -m probe.build_rt12col_unified --revision v3-revoked --out /tmp/rt12-v3.bin
python -m probe.build_rt12col_unified --revision v4-lp2 --out /tmp/rt12-v4.bin
python -m probe.build_rt12col_unified --revision v5-lp1 --out /tmp/rt12-v5.bin
python -m probe.build_rt12col_unified --revision v6-sleep-fix --out /tmp/rt12-v6.bin
python -m probe.build_rt12col_unified --revision v7-100hz-compare --out /tmp/rt12-v7.bin
```

The CLI refuses existing outputs and unknown sources. `firmware/fetch.sh`
rebuilds missing revisions only when the exact local stock restore exists.

Current build and physical evidence:

- all six revisions reproduce byte-for-byte to pinned hashes;
- the checked-in helper assembles as a 220-byte ARMv6-M section for both LP1
  and LP2 with no relocations or growth;
- the separate 212-byte V6 ARMv6-M helper also assembles exactly with no
  relocations or growth;
- focused tests execute first-entry, lease-only renewal, explicit stop,
  disconnect, and 250-tick expiry, including V6's exact 0x41 restore;
- the RT02 source-to-`FIFODATA` trace is instruction-pinned;
- app renewal tests require post-boundary evidence and reject duplicate bursts;
- V6 and V7 are recognized through complete changed-byte fingerprints but are
  not app install targets; V3 remains disabled and V4/V5 remain unavailable;
- the physical V4/V5 results below permanently disqualify both.

## Historical physical evidence from V1

On 2026-09-27, V1 passed DFU CHECK/END, rebooted, returned UART/DFU/Device
Information, reported `RT12COL_1.00.01_260927`, and matched eleven bounded
fingerprints. Live A1/03 data changed with motion, and explicit return sent
`A1 05`, `A1 02`, then `3B 02 01 00`, followed by Health sync.

Those results establish only that exact-source patching/routing can boot and
stream. Its stock 25 Hz LIS2DW12 source delivered 25.002 notifications/s but
17.46% consecutive duplicate payloads (about 20.64 distinct payloads/s).

The measured RT12 packet-to-model rotation is `[source0, source2, -source1]`.
It is a proper rotation (determinant +1) and remains separate from source-rate,
resolution, amplitude calibration, and model work.

## Physical V5-LP1 rejection and V1 rollback

On 2026-09-27, the exact V5-LP1 artifact passed the bounded preflight and DFU
CHECK, rebooted, reconnected, and reported `RT12COL_1.00.05_260927` on exact
`RT12COL_V1.0` hardware. An eight-second A1/03 capture with the RT12 motion hold
then recorded 201 packets over 7.995054 seconds:

- 25.0155 notification intervals/s;
- 98 duplicate transitions out of 200, or **49.0%**;
- 98 runs of length two and only five singleton runs;
- 98 unique payload values among 201 notifications;
- 44.3645 ms median and 39.9753 ms mean packet spacing.

This is a source-freshness failure, not transport loss: notification timing
remained near 25 Hz while the payloads arrived almost strictly in pairs. It is
worse than RT12 V1's earlier 17.4574% and is three orders of magnitude above
the 0.0333%-0.0556% archived RT02 controls. The bounded capture cleanup sent
`A1 05`, `A1 02`, and released the motion hold. V5 was then replaced with the
exact V1 artifact; the ring reconnected as `RT12COL_1.00.01_260927`, reported
`RT12COL_V1.0`, and returned battery 100%.

The raw capture and reproducible arithmetic are archived in
`firmware/research/2026-09-27/rt12-v5-lp1-physical/`. Whether the LEDs were dark
was not user-attested, but that cannot rescue the failed freshness gate.
The shared flashing preflight now rejects the V5 hash before connecting, even
if the file is renamed or pinned; there is no bypass flag for revoked content.

## Physical V4-LP2 rejection and V1 rollback

The exact V4-LP2 artifact also passed preflight, DFU CHECK, reboot and identity.
Its nominal ten-second lease produced 250 A1/03 packets over 9.945105 seconds:

- 25.0374 notification intervals/s;
- 123 duplicate transitions out of 249, or **49.3976%**;
- 123 runs of length two and only four singleton runs;
- 124 unique payload values among 250 notifications;
- 44.5730 ms median and 39.9402 ms mean packet spacing.

The lease then correctly stopped the stream. The generic 15-second host report
therefore showed 16.67 Hz, but this does not change the active-interval result.
LP2 reproduced LP1's almost exact new/repeat pairing before renewal. Cleanup
sent `A1 05`, `A1 02`, and released the motion hold. The ring was restored and
verified on V1 at 100% battery.

The raw capture is archived under
`firmware/research/2026-09-27/rt12-v4-lp2-physical/`. The shared flashing
preflight rejects V4 by hash before connecting, with no bypass flag.

## Conclusion

Changing LIS2DW12 LP mode alone did not fix source freshness. Never flash V3,
V4 or V5 again. Static analysis confirmed that stock also enables the sensor's
12.5 Hz inactivity mode, a variable V4/V5 left untouched. V6 isolates that
variable and is ready only for review and a separately authorized bounded
physical test. A failed V6 freshness gate would send the investigation back to
the reader/FIFO trace; an off-ring build is not evidence that V6 fixes the ring.

## V6 deployment record

On 2026-09-27, the user authorized one bounded V6 deployment. The guarded
preflight connected to `COLMI R02_DE07`, verified exact `RT12COL_V1.0` hardware,
current V1 identity and 98% battery. START and INIT type 4 passed, all 135
chunks transferred, and CHECK returned OK. END produced the expected silence as
the ring rebooted. A subsequent read-only connection reported
`RT12COL_1.00.06_260927`, `RT12COL_V1.0`, and 97% battery. This establishes
transfer, boot, BLE service availability and identity.

The immediately following bounded Gesture test captured 250 A1/03 samples over
9.959843 seconds of active lease time:

- 25.0004 notifications/s;
- 250/250 distinct payloads;
- zero duplicate transitions out of 249;
- 44.604 ms median, 47.104 ms p95 and 60.368 ms maximum gap;
- axis spans 904/380/1116 counts.

The generic 15-second report displayed 16.67 Hz only because V6's nominal
ten-second lease stopped the stream after 250 callbacks. Restricting the metric
to the first/last A1/03 samples gives the correct active rate above. The axis
spans do not cross the pre-existing 2000-count broad-motion threshold, so this
is a low-motion source-freshness pass, not a waveform or gesture-model test. It
is nevertheless a like-for-like answer to low-motion V4/V5: the exact pairs are
gone after clearing SLEEP_ON. Cleanup sent `A1 05`, `A1 02` and released the
motion hold. LED state, physical register restore, optical Health return and
steps/sleep continuity remain open.

A user-confirmed high-motion repeat reached 7.09 g with six axis-rail hits and
still delivered 250 samples at 25.0378 Hz with zero consecutive duplicates.
A later 20-second isolated-snap test renewed active `A1 04` at 8 and 16 seconds.
It delivered 501/501 distinct samples at 25.0065 Hz. Gaps across the two renewal
boundaries were 60.146 and 47.178 ms, with no duplicate across or near either
boundary. The lease-only path is therefore physically verified not to restart
or stale the producer.

The gesture engine detected the intended snap's 7.77 g burst but classified it
as `flick left` at 0.621 confidence. This is the remaining RT12 model/domain
problem; it is not a transport, source-freshness or lease-renewal failure.

The corrected CLI collector then recorded a 15-snap diagnostic across repeated
eight-second host renewals (`prompted_20260927_213001`). It delivered 2,313
A1/03 samples at 25.0007 active Hz with no consecutive duplicates; all 15 cues
contained motion. The one 649.8 ms delivery gap preceded the first cue. Compared
with 54 exact RT02 snaps through unchanged preprocessing, RT12's median peak was
0.88x, signed waveform correlation 0.77 and magnitude correlation 0.97. Median
peak was 5.06 g and the ordinary burst returned to the RT02-like two-sample/~43
ms shape. The currently pinned model produces twelve snap events from fifteen
motions. This is
strong physical source/waveform evidence, not a model-accuracy or training-set
approval: single-class drift is rejected, and the cue audit retained only nine
valid plus one suspect item.

## V7 bounded comparison and physical result

V7 is V6 with one behavioral byte changed: the Gesture-only LIS2DW12 `CTRL1`
literal at file offset `0xc094` is `0x61 -> 0x51`, changing LP2 source ODR from
200 to 100 Hz. Three additional payload bytes change `1.00.06` to `1.00.07` at
the runtime identity copies. The other 35 OTA byte differences are solely the
outer version/checksum and nested payload SHA fields. A complete comparison
found no unexplained difference.

The image was rebuilt independently to SHA-256
`cb815abea8d0ed0b4734b83790a45f632113e0bed4184de606b897727d4e9bd5`.
The guarded CLI recognizes that exact local pin; its dry run reassembled all
137,996 bytes through 135 DATA frames and 674 BLE writes. The separately pinned
stock rollback passed the same dry run. Firmware/flash gates pass 51/51; the
combined profile/capture/flash suite passes 79/79, and the recognition-only app
passes 87/87 simulator tests. No BLE connection or ring write occurred during
this preflight.

The guarded transfer completed all 135 DATA chunks, CHECK passed, reboot
silence at END was expected, and read-only identity returned
`RT12COL_1.00.07_260927` on `RT12COL_V1.0`. The first physical gate captured
751 A1/03 packets at 25.03 notifications/s with zero consecutive duplicate XYZ,
0.40% implied delivery loss and no frozen run. Lease boundaries near 8.5 and
16.5 seconds were clean. One later 106 ms notification gap was followed by
fresh queued values rather than repeats or a producer restart. This establishes
fresh delivery for the bounded run, not Health/steps/sleep continuity.

Two V7 snap sessions then captured 10 motions each at 25.02 notifications/s
with zero consecutive duplicates. Against 54 RT02 snap references, their median
peak ratios were 0.93 and 0.89, nearest magnitude correlations 0.95 and 0.96,
and nearest signed correlations 0.75 and 0.69. The unchanged frozen engine
produced 4/10 and 5/10 snap events, plus one double-clap confusion in the second
session. By comparison, V6's 15-snap session had peak ratio 0.88, magnitude
correlation 0.97, signed correlation 0.77 and 12/15 snap events under the same
current checkpoint.

The small waveform differences do not prove that 100 Hz acquisition itself is
unreliable: a bootstrap over these separate user-performed sessions includes
zero for the V6-minus-V7 median signed- and magnitude-correlation differences.
They do prove that V7 did not improve transfer. The likely design error was
matching a guessed RT02 source cadence while ignoring front-end bandwidth:
V7's `CTRL6=0x10` gives a 50 Hz digital cutoff at 100 Hz ODR, whereas V6 gives
100 Hz at 200 Hz ODR and the RT02 source uses its very wide 1 kHz STK bandwidth
setting before every-fourth FIFO retention. V6 is therefore the selected
near-equivalence baseline. V7 stays a diagnostic artifact and recognition-only
installed identity; no app install route is enabled.

This selection is not full-vocabulary qualification. The only complete
11-class RT12 session was recorded on V1's stale-prone stock source; V6/V7 were
compared with isolated snaps plus source gates. One V6 full-vocabulary session
and a separate long ambient/hard-negative run remain the minimum model-facing
checks before calling cross-ring behavior satisfactory.
