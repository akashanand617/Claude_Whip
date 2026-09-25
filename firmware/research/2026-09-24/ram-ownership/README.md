# RAM-ownership read session: installed V2 ring, read-only

2026-09-24. The user authorized read-only ring connection ("as long as we
aren't flashing") and freshly confirmed that all other clients were closed.
Codex confirmed it made no BLE connections during the session. Plan:
`probe.ram_read` / `whip/fwram_read.py`. **No flash, sensor command, write,
pointer following or retry within the session.** CD01 bookkeeping side effects
remain, as in every earlier CD session.

## Result: completed

- **268 of 268** matching CD01 transactions, then a verified disconnect.
- Identity: `optical_off_candidate` on critical sites and diagnostic code. This
  is not a full image attestation.
- The prior bank0 descriptor and config matched, the ROM identifier was read
  twice, and the config/idle postcheck passed.

| Window | Both reads | Observation |
|---|---|---|
| `app_pre_main` slot `0x2011d0` (4 B) | `0x00826613` | Exactly V2's `pre_main`, so the ROM hook slot holds the app's boot callback |
| Heap counters `0x2014d8` (60 B) | identical | Data heap: total **29688** (= `0x7400` − 8), free **264**, minimum-ever free **104**. Buffer heap: total 14440 (= `0x3870` − 8), free 3680, minimum 3680 |
| Heap header `0x20ec00` (8 B) | `00000000 58000080` | next = 0, size `0x80000058`: an allocated 88-byte block, a FreeRTOS-shaped header at the documented heap base |
| Gap `0x20e7dc..0x20ec00` (1060 B, 67 blocks) | hashes only | **No block changed across 60 s**; all 67 non-zero; none equals any 16-byte slice of the stock or 25 Hz images |

The data-heap free-list head is `0x215ef0`, 272 bytes below the end of Data
RAM. Under the assumed FreeRTOS layout, 264 already includes the block
header: `0x215ef0 + 264 = 0x215ff8`, then the 8-byte end marker reaches
`0x216000`. The node was not read, so a single-block topology is inferred,
not observed. The
buffer-heap head is `0x283198`. The unnamed 20-byte tail was recorded raw and
is not interpreted.

## What this does and does not establish

- **Header-shaped words at the configured heap start `0x20ec00`.** An
  allocated-looking header sits exactly there, and both heap totals equal the configured sizes minus the
  8-byte end marker. This agrees with the vendor layout and the captured
  config. The header shape is an assumed FreeRTOS format.
- **The heap fallback is not viable on this ring.** V2, with optics off, has
  only 264 free data-heap bytes and a lifetime low of 104. A ~1.1 KB unified
  allocation would fail. Stock Health's own peak on the stock base is **not**
  measured here.
- **Gap:** no net change was seen between two samples 60 s apart. Intervening
  write-and-restore is not excluded.
  Non-zero content of unknown origin is not proof of use or non-use. It does
  not cover boot, DLPS cycles, DFU or the stock image's map. `0x20e738..0x20e7dc`
  is V2's own overlay/BSS range and was not tested.
- Not established: `pre_main` running once per reset (ROM unread), DLPS
  retention, or any allocation approval.

## Earlier attempts in this session: no device contact

Four earlier runs each sent **zero** requests; their transcripts are kept
beside this directory. The user had just forgotten the ring in macOS
Bluetooth settings.

| Directory | Outcome |
|---|---|
| `ram-ownership-not-found/` | 10 s discovery missed the infrequent adverts |
| `ram-ownership-connect-timeout/` | found; connect timed out at 90 s |
| `ram-ownership-not-found-2/` | 30 s discovery missed, after a Mac Bluetooth toggle |
| `ram-ownership-discovery-disconnect/` | connected; the ring dropped during service discovery |

The successful run used 60 s discovery, after the user forgot the device
again and approved one more attempt.
