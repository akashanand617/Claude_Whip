# RT12COL activity/inactivity hypothesis

The hypothesis audit and V6 build were completed off-ring. Later explicitly
authorized deployment, source, high-motion and renewal tests are recorded below.

## Static result

The exact stock RT12 image directly writes:

- `WAKE_UP_THS 0x34 = 0x41` at `0xca16`: `SLEEP_ON=1`, wake threshold 1;
- `WAKE_UP_DUR 0x35 = 0x40` at `0xca0a`: `SLEEP_DUR=0`, `STATIONARY=0`,
  `WAKE_DUR=2`;
- `CTRL7 0x3f = 0x20` at `0xca2e`: `INTERRUPTS_ENABLE=1`.

Other fixed CTRL7 writes are `0x00` at `0xc036`, `0xc644`, and `0xc9fe`, and
`0x20` at `0xc606`. The read/modify/write at `0xc5ca..0xc5e2` clears only bit 7
of register `0x34`; it preserves `SLEEP_ON` at bit 6.

One timing detail in the proposed explanation needed correction. ST's official
driver defines `SLEEP_DUR` as 512/ODR per LSB, while `WAKE_DUR` is 1/ODR per
LSB. Stock programs `SLEEP_DUR=0`, not a nonzero timeout that becomes eight
times shorter. Nevertheless, the exact configuration does enable automatic
activity/inactivity mode, and the low-motion V4/V5 captures are consistent with
the device remaining in the 12.5 Hz inactivity state.

## Capture correlation

Neither V4 nor V5 contains a genuine high-motion interval. Their total axis
spans are below 0.04 g and the maximum change between distinct runs is below
0.03 g. The few singleton runs therefore do not systematically line up with
high motion:

- V4: three singletons occur at startup; the only later singleton has a large
  relative noise step but only about 0.0115 g absolute change.
- V5: three occur at startup, one at the final packet, and the sole interior
  singleton is not a high-motion transition.

This means the captures cannot demonstrate a motion-triggered wake transition.
They do show the predicted persistent-inactivity signature: approximately
12.5 distinct values/s delivered as almost exact pairs at 25 notifications/s.

## V6 disposition

The targeted off-ring candidate is V4-LP2 plus only the requested behavior:

- Gesture entry/reconfiguration writes `WAKE_UP_THS=0x01`, clearing only
  `SLEEP_ON` while retaining threshold 1;
- explicit stop, disconnect, and lease expiry all use one common helper that
  restores exact stock `WAKE_UP_THS=0x41` after stock CTRL1/CTRL6;
- the repeated active `A1 04` path remains lease-only and performs no sensor
  rewrite;
- boot, services, partitions, DFU, notification framing, timer and V4 LP2
  values remain unchanged.

Artifact:

- version: `RT12COL_1.00.06_260927`
- SHA-256: `e92c5bc0d2751c3348aeea56ece4e5b5693baf1f6ba45c2a869c2d79729e134d`
- size: 137,996 bytes
- status: deployed once; boot/identity and source freshness verified; not an
  approved general install target

`analysis.json` pins the exact inputs and computed data result.

## Bounded deployment

The exact artifact above was flashed once to `COLMI R02_DE07`. Preflight
verified exact `RT12COL_V1.0`, current V1 identity and 98% battery. START, INIT
type 4, all 135 DATA chunks and CHECK passed. END was silent as expected during
reboot. Read-only reconnection reported `RT12COL_1.00.06_260927`, exact hardware
and 97% battery. This proves transfer, boot and BLE identity only. Gesture
freshness was tested next; LEDs, physical common-exit restoration and Health
continuity remain open.
`deployment.json` records the exact observed facts.

## First V6 source-freshness result

The same bounded host procedure used for V4/V5 captured 15 seconds while V6's
firmware lease intentionally stopped A1/03 after 250 callbacks. Analysing the
actual first-to-last A1/03 interval produced:

| Metric | Result |
|---|---:|
| samples | 250 |
| active span | 9.959843 s |
| notification rate | 25.0004 Hz |
| duplicate transitions | **0 / 249** |
| distinct payloads | **250 / 250** |
| median / p95 / max gap | 44.604 / 47.104 / 60.368 ms |
| axis spans | 904 / 380 / 1116 counts |

The host's generic whole-window 16.67 Hz failure is expected because it divides
250 lease-bounded samples by the full 15-second request. Source delivery during
the active lease is 25 Hz. The capture remained below the existing 2000-count
broad-motion threshold, so it is not a waveform/model qualification. It is a
direct low-motion comparison with V4/V5 and shows that clearing SLEEP_ON removes
their near-exact pairs. Cleanup sent `A1 05`, `A1 02` and disabled the motion
hold.

Capture: `data/raw/rt12_v6_sleep_fix_first_source_20260927.jsonl`, SHA-256
`49364908fcd8fb724dd735057e7db094e0d0e9e0d8665e56a2637feb901614bb`.

## High-motion and renewal results

The user-confirmed repeat high-motion run reached 7.09 g with six axis-rail
hits. Its active lease still delivered 250 samples at 25.0378 Hz with zero
consecutive duplicates, no stalls, and a 75.269 ms maximum gap. The earlier
`rt12_v6_high_motion_20260927.jsonl` was started before the user was ready and
is explicitly excluded.

Capture: `data/raw/rt12_v6_high_motion_repeat_20260927.jsonl`, SHA-256
`e6140ee87e27cd608e8a959ee12612fd1d35f1cba1f254c576c6ff8156d28b33`.

A subsequent isolated-snap run renewed active `A1 04` at 8 and 16 seconds.
The 20-second result was 501 A1/03 samples at 25.0065 Hz, 501/501 distinct,
zero consecutive duplicates and a 75.788 ms maximum gap. The two renewal
boundaries had 60.146 ms and 47.178 ms gaps, no boundary duplicate, and zero
duplicates in the ten samples on either side. This physically confirms the
lease-only renewal path does not restart or stale the source.

The gesture engine detected the isolated movement as a 7.77 g burst, but called
the intended snap `flick left` at 0.621 confidence (two votes, decision latency
1.715 seconds). That is a model/domain error, not a firmware-source failure.

Capture: `data/raw/rt12_v6_snap_renewed_20260927.jsonl`, SHA-256
`451a34f810ba36566c6d375765bc3144683eccc2d37eb38cc3a67230c4b3b77f`.
