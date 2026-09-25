# Resume-pointer read: installed V2 ring, read-only

2026-09-25. Same authorization family. The user freshly confirmed that all
other clients were closed, and Codex stayed off-ring. Plan:
`probe.ram_read --resume-pointers`. **No flash, sensor command, write,
pointer following or retry.** CD01 bookkeeping effects remain.

Result: **108 of 108** matching CD01 transactions, then a verified disconnect,
on the first attempt. Identity `optical_off_candidate`. Both reads equal.

| ROM-data word | Value | Where it points |
|---|---|---|
| `0x2000f0` (first-boot hook, called by `0x4e36`) | `0x40eb` | ROM `0x40ea`, uncaptured |
| `0x2000f4` | `0x400` | not a pointer |
| **`0x2000f8`** (resume target used by `0x4ee6`) | **`0xd22d`** | ROM `0xd22c`, just after `power_manager_resume_all` (`0xd210`), uncaptured |
| `0x2000fc` | `0xe8762` | not interpreted |
| `0x20014c` (early first-boot hook, `0x4fa2`) | `0xb9b3` | ROM `0xb9b2`, uncaptured |

The reset handler's bit-1 path therefore jumps into the ROM power-manager
module. The NMI vector (`0xd6d7`) points into the same area. The routine
body is unread, so whether it can reach `app_pre_main` is still open.
Nothing here was followed.
