# RT02 consecutive-duplicate control

There is no separate RT02 control ring. Per the user, the completed RT02
captures already in the repository are the control. They are substantially
longer than the proposed replacement capture and identify the exact device as
`RT02CR_V3.1` / `RT02CR_3.12.07_260514`.

The metric was recomputed from every checksum-valid `A1/03` packet in each
completed `optical_stop_mode3` phase. A duplicate means exact equality of raw
XYZ bytes `packet[2:8]` on consecutive notifications—the same definition used
for RT12 V1. The reproducible command is:

```sh
python -m probe.rt02_duplicate_control --archive \
  data/batterycheck/battery_1790109591966012000.jsonl \
  data/batterycheck/battery_1790111870918145000.jsonl \
  data/batterycheck/battery_1790075332801725000.jsonl
```

| source | duration | packets | rate | duplicate transitions | duplicate rate |
|---|---:|---:|---:|---:|---:|
| `battery_1790109591966012000.jsonl` | 30 min | 45,002 | 25.00084 Hz | 25 / 45,001 | 0.05555% |
| `battery_1790111870918145000.jsonl` | 30 min | 45,002 | 25.00076 Hz | 23 / 45,001 | 0.05111% |
| `battery_1790075332801725000.jsonl` | 10 min | 15,002 | 25.00066 Hz | 5 / 15,001 | 0.03333% |

All three phases ended by their time limit and their cleanup records have no
errors with `restoration=verified_000100`. By contrast, RT12 V1 capture
`phone_domain_20260927_180327.jsonl` has 1,034 / 5,923 duplicate transitions,
or **17.45737%**, at 25.00181 notifications/s. The difference is about 314x
against the worse of the two 30-minute RT02 controls. This resolves the RT02
duplicate-control requirement from existing data; a new physical recapture is
not a gate.

Pinned source SHA-256 values are recorded in `archive-analysis.json`.

## Abandoned fresh-capture attempt

On 2026-09-27 the bounded control tool was run for exact CoreBluetooth identity
`3C2FA77E-1BE3-A0C5-0DD5-DB6A3AD452B2` with a 60-second discovery timeout:

```sh
python -m probe.rt02_duplicate_control \
  --address 3C2FA77E-1BE3-A0C5-0DD5-DB6A3AD452B2 \
  --duration 60 --timeout 60
```

Result: `no device found at address
3C2FA77E-1BE3-A0C5-0DD5-DB6A3AD452B2`.

The failure occurred before connection and before Device Information, battery,
notification subscription, or any UART command. No raw start, sensor command,
diagnostic read, or firmware write was sent. It is retained only as chronology;
there is no separate control device to retry.

The live path remains available if ever needed. It fails closed on
hardware/firmware mismatch, uses the same rate and consecutive-payload
definitions as `whip.domain_analysis`, and always attempts `A1 05` then `A1 02`
cleanup after any raw-start attempt.
