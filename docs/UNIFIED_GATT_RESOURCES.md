# Unified firmware: GATT registration resources

2026-09-25. Evidence audit requested by the Codex root session. Sources: the
pinned stock image (`rt02cr-stock-3.12.02.bin`), one read-only device session
([`firmware/research/2026-09-24/gatt-resources/`](../firmware/research/2026-09-24/gatt-resources/README.md),
172/172, verified disconnect), and the public SDK mirror
atc1441/ATC_RTL_BLE_OEPL @ `49301d9b` as a same-family reference only. No
vendor-confidential material is used. **No memory or flash approval; no gate changes.**
The user subsequently approved the WeChat-only feature tradeoff. Codex's
[direct stock audit and compiled adapter](UNIFIED_WECHAT_RETIREMENT.md) record
the actual setup/callback distinction and remaining closure work. HID retirement
is not approved.

## 1. Stock registration (measured, stock bytes)

Setup `0x76b8` calls the `server_init` wrapper at `0x1580a` with **5**.
The wrapper enters ROM gateway `0x4926` with ID `0x3100`, and its return
value is not checked. Five add calls follow; each goes through the add
wrapper `0x15824` (gateway ID `0x3102`), and the returned service IDs are
stored at `0x209e1b..0x209e1f`. A failed add stores `0xff` and setup
continues ([stock transport audit](UNIFIED_STOCK_TRANSPORT.md)).

| Add function | Service (first attribute) | Database | Attributes / bytes |
|---|---|---|---:|
| `0x7b40` | Colmi UART `6e40fff0-…` | file `0x1f25c` | 6 / 168 |
| `0x7a2a` | Realtek DFU/OTA `de5bf728-…` | file `0x1f198` | 6 / 168 |
| `0x7918` | `0x180A` Device Information | file `0x1f080` | 9 / 252 |
| `0x7d5e` | `0xFEE7` (WeChat hardware service UUID) | file `0x1f310` | 9 / 252 |
| `0x1445c` | `0x1812` HID | file `0x1ff70` | 27 / 756 (length read from RAM `0x2085e6`; initial `.data` value 756) |

Attribute entries are 28 bytes, so the 168 B stock-shaped table and Codex's
240 B candidate follow the same encoding.

## 2. Where registration memory is allocated

Registration runs in the **Upper Stack image** (flash `0x80e000`, `0x18000`,
from the ring's bank0 descriptor), not in the app or in the captured ROM.

**The ring's Upper Stack is a different build from the public mirror
(measured).** The header's ic, flags, image ID `0x279a`, ROM UUID and
addresses match, but the payload length is `0x16c3c` against `0x214cc`, and
the hash field at `+0x174` differs. The in-partition pool-window bytes also
differ. **Independent correction:** the mirror's `server_init` address
`0x828e5c` is outside this ring's Upper Stack partition ending `0x826000`;
the 100 sampled bytes there match installed APP file offset `0x2eac`.
That window is not the ring's corresponding `server_init`. The header/hash
still establish a different build. Mirror code and RAM addresses therefore
**do not transfer**.

Same-family reference only, from the mirror's Upper Stack (not ring
evidence):
- `server_init(n)` zero-allocates **28 × (n + 2)** bytes, where the +2 is the
  built-in GAP/GATT services when they are enabled, from **RAM type 0 (data
  heap)** once at init. On allocation failure it **returns silently**: no
  log, no error, and a NULL table.
- `server_register_services` allocates 12 × N and the lower GATT layer
  8 × N. **Both are freed** in the same functions, so they are transient.
- Each service takes a record from a **fixed pool** created in `gatt_init`.
  Its capacity is a byte in the OTP "upper" configuration block. A full pool
  logs and fails that registration.

The ring's OTP upper block `0x2002e4..0x200320` was read (raw, in the
archive). Which byte is the service-pool capacity **for the ring's build** is
not established.

## 3. Would a sixth service cost data heap?

Unknown for the ring. If the ring's build follows the reference pattern, a
sixth service needs:
- `server_init(6)` instead of 5, since stock passes 5 and there is no spare
  declared slot;
- **+28 B of data heap at boot** for the server table, against a measured
  V2 lifetime minimum of 104 B free;
- one more free lower-GATT pool slot, whose capacity is unknown.

The buffer heap (3680 B free observed) is **not** assumed to substitute for
data-heap allocations. Transient registration arrays add a brief peak
during boot.

## 4. Is any stock service safely replaceable?

**None is strictly diagnostic.**
- **UART** carries commands and Health sync.
- **DFU** is the documented update and recovery path.
- **DIS** supplies the identity the app and tools read.

These three must stay.

- `0xFEE7` (WeChat hardware/sport) and `0x1812` HID are **optional
  features**. HID presumably backs host-input features; the link to
  motion-action mode 1's host-input events is inferred, not traced. Reusing one of their slots keeps the count at 5, so there is no
  `server_init` change and no extra server-table heap. The cost is losing
  that feature, which is a user decision.
- **Code-space lead, not approved:** the HID database alone is 756 flash
  bytes (file `0x1ff70`). If HID were retired, its database and callbacks
  might be reclaimable, subject to full reference closure (RAM length
  variable `0x2085e6`, report map, callbacks, and the motion-action path).

## 5. What would close the ring-specific allocation question

Locate the ring's own `server_init` through the gateway. ROM `0x4926`
reaches the Upper Stack through slot `upperstack_entry` (`0x2011d4`) and a
dispatch table in the ring's Upper Stack. That requires staged fixed reads:
slot value, then dispatch code, then the handler for `0x3100`. Addresses
must be chosen offline between stages, as in the earlier ROM resume reads.
This is not authorized by this document.
