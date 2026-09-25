# GATT registration resources: installed V2 ring, read-only

2026-09-25. The user confirmed all other clients were closed; Codex stayed
off-ring. Plan: `probe.ram_read --gatt-resources` (`whip/fwram_read.py`).
**No flash, sensor command, write, execution or pointer following.**
Result: **172 of 172** matching CD01 transactions, verified disconnect, first
attempt; every window was identical across both reads.

The windows were chosen offline from the public SDK mirror's Upper Stack
image (atc1441/ATC_RTL_BLE_OEPL @ 49301d9b, `data_0x801000.bin`, SHA-256
`ca53de5c…`) and the ring's bank0 descriptor (Upper Stack at `0x80e000`,
`0x18000`).

| Window | Result |
|---|---|
| Upper Stack header `0x80e000` (96 B) | Same ic/flags/image ID `0x279a`/ROM UUID/addresses as the mirror; **payload length `0x16c3c` vs mirror `0x214cc`** |
| Header field `0x80e174` (32 B) | Differs from the mirror |
| Mirror `server_init` address `0x828e5c` (100 B) | Outside this ring's Upper Stack; matches installed APP file `0x2eac`. Not the ring's corresponding allocator |
| Mirror pool-allocator bytes `0x818ef8` (104 B) | **Differ** |
| OTP upper block `0x2002e4` (60 B) | Recorded raw; field meanings for this build are not established |
| Mirror RAM state `0x207974`, `0x207810` (16 B each) | Recorded; **not interpreted**, because the build differs |

**Conclusion:** the ring's Upper Stack is a different build from the public
mirror. The mirror's GATT allocation code is a same-family reference, not
ring evidence. See `docs/UNIFIED_GATT_RESOURCES.md`.

Independent archive check verified all 172 request/reply pairs, both listed
file hashes, repeated windows and confirmed disconnect. The address correction
above changes interpretation only; capture and transcript bytes are unchanged.
