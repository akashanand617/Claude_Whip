# RT12COL V4-LP2 physical rejection

Date: 2026-09-27

Target:

- advertised name: `COLMI R02_DE07`
- CoreBluetooth identifier: `D8697CFC-67BA-CF99-F790-C860C205AE4A`
- hardware: `RT12COL_V1.0`
- starting firmware: `RT12COL_1.00.01_260927` (V1)
- battery before deployment: 100%

Artifact:

- file: `firmware/rt12col-25hz-health-default-gesture-v4-lp2-experimental.bin`
- version: `RT12COL_1.00.04_260927`
- size: 137,996 bytes
- SHA-256: `21de9507955e102e846932f1d3c1b16e736a73d9d355560af8cf89cc61093d78`
- DFU init type: `0x04`

The dry run reassembled all 135 chunks and 674 BLE segments exactly. The
physical transfer acknowledged START, INIT, every DATA chunk, and CHECK. END
produced the expected reboot silence. The ring reconnected with exact V4
firmware/hardware identity and battery 100%.

## Source-freshness test

The bounded source test was:

```sh
python -m probe.stream --duration 15 \
  --label rt12_v4_lp2_first_source \
  --address D8697CFC-67BA-CF99-F790-C860C205AE4A --timeout 90 \
  --motion-hold \
  --out data/raw/rt12_v4_lp2_first_source_20260927.jsonl
```

The exact capture is retained here as `capture.jsonl`. Its SHA-256 is
`61af77598443f88a614dded8aed63a7e4f0bc066944181fec2c9be782152faea`.

V4's nominal ten-second firmware lease expired before the 15-second host window,
so the generic whole-window report displayed 16.67 Hz. Restricting the metric to
the actual first-to-last A1/03 interval gives:

| Metric | Result |
|---|---:|
| A1/03 packets | 250 |
| active first-to-last span | 9.945105 s |
| notification interval rate | 25.0374/s |
| consecutive duplicate transitions | 123 / 249 |
| consecutive duplicate fraction | **49.3976%** |
| payload runs | 123 pairs, 4 singletons |
| unique payload values | 124 / 250 |
| median spacing | 44.5730 ms |
| mean spacing | 39.9402 ms |
| maximum spacing | 75.3190 ms |

The lease backstop behaved correctly, but LP2 produced the same almost exact
new/repeat pairing as LP1 V5. This fails before renewal, model inference or
Health-continuity testing. The capture did not establish a broad movement span,
but that does not explain 123 successive two-packet runs aligned to delivery.
LED darkness was not user-attested and cannot rescue failed source freshness.

The capture cleanup sent `A1 05`, `A1 02`, and released the RT12 motion hold.
V4 is permanently rejected.

## Recovery

The exact V1 image was immediately transferred through the same bounded path:

- V1 SHA-256: `52736f328dd2ea60e284a25438284447b54837e93a0dbcc2da88737968b4483b`
- START, INIT, all 135 DATA chunks, and CHECK acknowledged
- END reboot silence was expected
- post-reboot scan reported `RT12COL_1.00.01_260927`
- hardware remained `RT12COL_V1.0`
- battery reported 100%

The shared flashing preflight denies the V4 content hash before connecting,
even if the file is renamed or pinned. There is no override. The image remains
in `SHA256SUMS` only for exact provenance.
