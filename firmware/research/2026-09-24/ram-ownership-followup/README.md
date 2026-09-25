# RAM-ownership follow-up: installed V2 ring, read-only

2026-09-24/25. Same authorization and plan family as `../ram-ownership/`. The
user freshly confirmed that all other clients were closed, and Codex stayed
off-ring. Plan: `probe.ram_read --followup`. **No flash, sensor command,
write, pointer following or retry.** CD01 bookkeeping effects remain.

## Result: completed on the first attempt

- **274 of 274** matching CD01 transactions, then a verified disconnect.
- Identity `optical_off_candidate` (critical sites only).
- Descriptor, config and ROM identifier matched; idle postcheck passed.
- Started 16,606 s (**~4.6 h**) after the first session's header. The ring
  was disconnected and idle in between, as far as the user reports.

| Window | Observation |
|---|---|
| Gap `0x20e7dc..0x20ec00`, 67 blocks, hashed twice | **Every block identical** to the first session's digests, and within this session |
| Heap counters `0x2014d8` | Unchanged: data free 264, minimum 104, total 29688; buffer 3680/3680/14440 |
| ROM vectors `0x0..0x40`, recorded, **not followed** | SP `0x203800`; Reset `0x4eff`; NMI `0xd6d7`; HardFault `0x101`; SVCall `0x10fd5`; PendSV `0x25b`; SysTick `0x110a5` (repeated equal) |

## Interpretation, bounded

- **No observed net change over 4.6 h:** 1060 bytes of non-zero content were
  identical in samples 16,606 s apart, with the ring disconnected and idle
  in between. This does **not** establish that DLPS occurred, retention
  through DLPS, or the absence of intervening write-and-restore. It does not
  cover `0x20e738..0x20e7dc` (V2's own overlay), boot, DFU or charging.
- **ROM initial SP `0x203800`** equals the vendor-documented main-stack top
  and stock's startup SP.
- **Reset handler `0x4efe` lies inside the previously captured ROM window
  `0x4a78..0x53a4`** (`../../2026-09-23/rom-integration/`), so its branch
  structure can be read offline. See `docs/UNIFIED_RAM_OWNERSHIP.md`.
