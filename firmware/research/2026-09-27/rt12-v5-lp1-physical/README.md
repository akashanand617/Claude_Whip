# RT12COL V5-LP1 physical rejection

Date: 2026-09-27

Target:

- advertised name: `COLMI R02_DE07`
- CoreBluetooth identifier: `D8697CFC-67BA-CF99-F790-C860C205AE4A`
- hardware: `RT12COL_V1.0`
- starting firmware: `RT12COL_1.00.01_260927` (V1)
- battery before deployment: 100%

Artifact:

- file: `firmware/rt12col-25hz-health-default-gesture-v5-lp1-experimental.bin`
- version: `RT12COL_1.00.05_260927`
- size: 137,996 bytes
- SHA-256: `23267b5e25e65591349861048c24b72b5cdbc60ea2d583a58315b4cd33d38217`
- DFU init type: `0x04`

The preflight dry-run reassembled all 135 chunks and 674 BLE segments exactly.
The physical transfer acknowledged START, INIT, every DATA chunk, and CHECK.
END produced the expected reboot silence. The ring reconnected with exact V5
firmware/hardware identity and battery 100%.

## Source-freshness test

The first bounded source test was:

```sh
python -m probe.stream --duration 8 \
  --label rt12_v5_lp1_first_source \
  --address D8697CFC-67BA-CF99-F790-C860C205AE4A --timeout 90 \
  --motion-hold \
  --out data/raw/rt12_v5_lp1_first_source_20260927.jsonl
```

The exact capture is retained here as `capture.jsonl` (copied byte-for-byte from
the original `data/raw/rt12_v5_lp1_first_source_20260927.jsonl`). Capture SHA-256:
`74ae851af8c68578e94ca8f51e610985b42e472c3fe50acac65c3c6967a5638f`.

Using exact equality of A1/03 XYZ bytes 2 through 7:

| Metric | Result |
|---|---:|
| A1/03 packets | 201 |
| first-to-last span | 7.995054 s |
| notification interval rate | 25.0155/s |
| consecutive duplicate transitions | 98 / 200 |
| consecutive duplicate fraction | **49.0%** |
| payload runs | 98 pairs, 5 singletons |
| unique payload values | 98 / 201 |
| median spacing | 44.3645 ms |
| mean spacing | 39.9753 ms |

The nearly exact pairs disprove source freshness despite normal notification
delivery. This is worse than the prior RT12 V1 result (17.4574%) and far above
the exact archived RT02 controls (0.0333%-0.0556%). V5 is permanently rejected.
LED darkness was not user-attested and is not needed to reject this image.

The capture's `finally` cleanup sent `A1 05`, `A1 02`, and released the RT12
motion hold. No renewal, Health-continuity, steps/sleep, or model test was run
after the freshness gate failed.

## Recovery

The exact V1 image was immediately transferred with the same bounded DFU path:

- V1 SHA-256: `52736f328dd2ea60e284a25438284447b54837e93a0dbcc2da88737968b4483b`
- START, INIT, all 135 DATA chunks, and CHECK acknowledged
- END reboot silence was expected
- post-reboot scan reported `RT12COL_1.00.01_260927`
- hardware remained `RT12COL_V1.0`
- battery reported 100%

The ring therefore remained recoverable and is currently back on V1.

`whip.flashing.preflight` now denies the V5 content hash before any connection,
even if the file is renamed or locally pinned. There is no override. The image
remains in `SHA256SUMS` only so its exact identity and provenance stay auditable.
