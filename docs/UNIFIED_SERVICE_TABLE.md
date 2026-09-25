# Unified service table: unlinked development candidate

2026-09-24. Entirely off-ring. `firmware/unified/stock_service.{c,h}` defines
the actual ARM32 attribute table and development UUIDs. It does **not** register
a service, declare an approved build/capability, implement callbacks, change
stock bytes or enable the app's production transport. Installed V2 is unchanged.

Later [discovery implementation](UNIFIED_DISCOVERY.md) adds an unattached
20-byte C encoder/borrowed view and matching Swift parser. The exact table and
its pinned header remain unchanged; the callback, value allocation, boot-ID
owner and admission are still absent. The latest 22-object conditional link
includes this table and discovery, with 9256 append bytes / 264 remaining in
unapproved geometry. The historical append-only subtotals below are not that
whole-code budget.

## Why eight entries, not the earlier six-entry planning case

Every existing control request, including STATUS, contains an expected nonzero
64-bit boot ID. Write-only RX/notify-only TX cannot bootstrap that ID under the
current protocol. This candidate chooses a separate read-only discovery
characteristic. Adding a reviewed read operation to RX is a smaller alternative
(six rows plus the primary UUID, 184 bytes); it is not ruled out, but is not the
table implemented here. Either shape still needs a safe identity read before
the first control request. The chosen discovery characteristic's
immutable-per-boot format is now implemented separately, but its publication,
authorization, lifetime and read callback remain unimplemented; a null
application-supplied value is not an empty valid identity.

| Index | Attribute | Properties / permissions |
|---|---|---|
| 0 | Primary service | Readable 128-bit service UUID |
| 1, 2 | RX declaration/value | Write with or without response; not readable |
| 3, 4 | TX declaration/value | Notify only |
| 5 | TX client configuration | Read/write; notifications initially disabled |
| 6, 7 | Discovery declaration/value | Read only; application must supply value |

Compiled storage is **224 bytes for eight 28-byte entries + 16 bytes for the
external primary-service UUID = 240 read-only bytes**. The three characteristic
UUIDs are inline types, not additional external blobs. No executable bytes,
writable static allocation or function stack report is produced by this unit.
That excludes discovery contents, callbacks, registration resources and all
other integration code. The earlier 168-byte estimate was explicitly a six-row
table-only lower bound, not the whole service.

Development service UUID: `33cdf03c-77d9-458b-aedf-12a7a189ef20`; RX, TX and
discovery use final octets `21`, `22`, `23`. These are local candidate assignments,
not an advertised or production-approved interface. UUIDs use all-16-byte GATT
little-endian order, **not** the mixed-endian GUID representation. No Swift UUID
or CoreBluetooth registration has been added.

## Stock and source evidence

The complete stock SHA-256 remains
`b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0`.
Its six-entry UART table is file `0x1f25c..0x1f304`; external primary UUID is
`0x1f24c..0x1f25c`. The first six candidate rows match every stock byte except
the three UUID locations (primary pointer and two inline types). Stock Device
Information rows at `0x1f080` independently show application-supplied readable
values with zero length/pointer fields. The discovery entry combines that pattern
with the already observed inline-128-bit UUID flag.

The pinned vendor-derived [attribute header](https://raw.githubusercontent.com/atc1441/ATC_RTL_BLE_OEPL/49301d9b75816ccde1cc9657b827fdadf5736937/ATC_RTL_BLE_OEPL_8762ESL/sdk/inc/bluetooth/profile/gatt.h)
matches the fields: flags at 0, type/value at 2, length at 18, pointer at 20 and
32-bit permissions at 24. Static assertions enforce each offset, ARM32 pointer
width, 28-byte stride and four-byte alignment. This is compatible-source evidence,
not proof of physical stack semantics or this ring's exact SDK release.

In particular, the read callback ABI includes an offset, but the reviewed stock
callbacks return a base pointer/full length. Whether ROM applies the offset
afterward remains unproved. Do not install a sliced-span helper on that assumption.
CCCD change notification is also not retained subscription ownership, generation
fencing or send-credit proof. Stock-style open permissions do not establish
authentication or authorization; these remain separate admission obligations.

## Validation boundary

`tests/test_stock_service.py` double-compiles and double-links the table/shim,
checks all bytes, UUID order, permissions and zero defaults, and runs the compiled
registration shim through the original stock wrapper. ROM results are named
fixtures. Callback addresses are borrowed only as ABI values; no old callback
is invoked or claimed as a valid new-service implementation.

The unchanged stock setup still reserves and registers exactly **five** services.
A simulated assigned ID of 5 does not prove a sixth slot is available. The focused
ELF is deliberately incomplete/artificial-address and rejected by the production
placement verifier. The guarded builder archives this unit as an **unlinked
candidate**, excluded from both main ELFs. Missing `.su` is allowed only after
checking that the object has no allocated executable bytes or defined functions;
an executable object with a missing report still fails.

The whole known append-only subtotal is now `9468 + 196 + 240 = 9904`, **384
bytes beyond 9520**, before changed alignment/unwind, discovery contents, owner,
callbacks, coordinator and hooks. Even a hypothetical 408-byte relocation leaves
only 24 arithmetic bytes before relocation overhead and the missing pieces.
Actual relocation measurements are separate and never approve those stock holes.
The [measured relocation experiment](UNIFIED_RELOCATION_TRIAL.md) additionally
finds 80 bytes of linked unwind coalescing, but the service-inclusive link still
refuses because its initial pre-coalescing estimate crosses the unchanged bound.
Its later map is not a successful ELF or an approved fit.
All six [release gates](UNIFIED_READINESS.md) remain open.
