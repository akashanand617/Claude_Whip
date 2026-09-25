# Discovery read callback: actual ABI adapter, ownership still missing

## New unattached implementation — 2026-09-24/25

`firmware/unified/stock_discovery_read.{c,h}` now implements `wdr_read` with
the six stock arguments below. It clears each nonnull output before refusal,
rejects missing output slots (0x411), unpublished/mismatched/sentinel service
IDs or non-discovery attributes (0x40a), and nonzero offsets (0x407). A valid
read returns the entire 20-byte identity through a borrowed const pointer.
No seventh context argument, stack-local returned value, session creation,
capability declaration, mode switch or notification is added.

The mandatory strong binding `wdr_identity[20]` is deliberately undefined.
Its storage declaration is mutable to permit real boot-time `wdi_encode`
initialization; the callback itself never writes it. The actual boot owner
must successfully encode a qualified fresh boot ID and build tag before
publishing `wgs_service_id`, then keep the value immutable throughout every
stack borrow. A declaration and nonnull address do not prove those conditions.
Connection ID is deliberately unused for this public read-only identity;
control/write-generation admission is a separate, still-missing binding.
Outputs must be valid, writable and mutually disjoint from owned storage.

The focused actual-ARM suite passes 28 cases. It calls the real encoder and
runtime, checks six-argument/stack-output placement, exact output widths and
clearing, sentinel and unpublished service refusal, attribute/offset bounds,
borrowed-value stability and unchanged Health/no-action state. Boot publication
is an explicit fixture, not a real initialization hook or stack-lifetime test.
The callback is not yet installed in a production service callback table;
write and CCCD implementations remain missing.

Double compilation/relink reproduces an eight-object artificial ELF. The
callback adds **92 text bytes, 8 input-unwind bytes and 20 local-stack bytes**.
Whole **28 objects / 149 functions / three constants** now have an input-only
append lower bound **10798/9520, at least 1278 over**, before callback-table12,
alignment, final unwind and remaining code. Strict whole-28 links refuse six
strong bindings; no production ELF. Its identity20 was already in the RAM
planning subtotal and is not counted twice; no allocation is approved.
The chronological ABI audit below predates this candidate. All physical,
full-startup, callback lifetime, publication and recovery gates remain open.

2026-09-24/25. Off-ring review of exact stock instructions and public,
commit-pinned vendor-origin SDK sources only. No vendor-guide content, ring
access, service registration, firmware edit or new production caller. This is
not the separately proposed GATT resource audit; that audit was not delivered
and is not counted as evidence here.

## What can now be fixed in the implementation contract

The public [profile_server.h](https://github.com/atc1441/ATC_RTL_BLE_OEPL/blob/49301d9b75816ccde1cc9657b827fdadf5736937/ATC_RTL_BLE_OEPL_8762ESL/sdk/inc/bluetooth/profile/profile_server.h)
defines **six arguments and no context pointer** for an application attribute
read. The exact stock callback at file `0x7aa4` independently confirms where
the two output arguments arrive. On entry:

| ARM location | Meaning in the compatible declaration | Exact-stock use |
|---|---|---|
| r0 | 8-bit connection ID | Overwritten; no connection validation |
| r1 | 8-bit assigned service ID | Overwritten; no service validation |
| r2 | 16-bit attribute index | Compared with 7 |
| r3 | 16-bit requested offset | Overwritten; no offset handling |
| incoming stack word 0 | Pointer to 16-bit output length | Loaded at `0x7aa8`, then halfword store |
| incoming stack word 1 | Pointer to returned value pointer | Loaded at `0x7aaa`, then word store |

The callback first pushes eight bytes, so the stack loads use current SP+8/+12.
The index-7 branch returns pointer `0x208528` and a stored byte length minus one;
zero underflows to 65535. That branch is outside the registered six-row UART
table. It is **not an available discovery attribute** and must not be enabled
or copied as a safe read implementation. Stock callbacks elsewhere and the
public service example likewise use retained application data, not a returned
pointer into callback stack scratch.

The [public simple-service example](https://github.com/atc1441/ATC_RTL_BLE_OEPL/blob/49301d9b75816ccde1cc9657b827fdadf5736937/ATC_RTL_BLE_OEPL_8762ESL/sdk/src/ble/profile/server/simple_ble_service.c)
returns its array base and whole length without using the offset. That supports
the callback shape, **not** a conclusion about where the actual ring stack
performs slicing or when it releases the borrowed pointer.

[gap.h](https://github.com/atc1441/ATC_RTL_BLE_OEPL/blob/49301d9b75816ccde1cc9657b827fdadf5736937/ATC_RTL_BLE_OEPL_8762ESL/sdk/inc/bluetooth/gap/gap.h)
combines the module/error constants in
[bt_types.h](https://github.com/atc1441/ATC_RTL_BLE_OEPL/blob/49301d9b75816ccde1cc9657b827fdadf5736937/ATC_RTL_BLE_OEPL_8762ESL/sdk/inc/bluetooth/gap/bt_types.h)
into application results: success `0`, invalid offset `0x407`, attribute not
found `0x40a`, invalid value size `0x40d`, insufficient resources `0x411`.
The existing exact-stock write tests independently observe `0x40a/0x40d`.
The new offset result is source-supported, not a measured client-visible reply
on this ring. These are scalar return values; do not import enum-dependent
event-structure layouts on the strength of this result list.

## The owner is a required binding, not another callback argument

`wdi_read` from [discovery](UNIFIED_DISCOVERY.md) intentionally accepts a value
pointer and a view output. It is **not** a GATT callback. Adding a seventh
context argument to the six-argument callback would not make it one: the stock
stack has no obligation to supply that argument.

The actual binding therefore needs a reviewed stable lookup for the assigned
service ID and its immutable per-boot identity value, without accessing guessed
RAM or borrowing a temporary stack object. Merely declaring an external owner
symbol or supplying it from a test fixture would leave the same obligation.
The 20-byte value is already in the planning budget; lookup/publication state
and callback code have additional, as-yet-unmeasured costs.

Once that owner exists, the callback must validate the assigned service and
discovery index, return only the initialized identity, refuse unsupported
offsets, initialize its output fields on refusal, and keep the returned bytes
alive throughout the stack's read lifetime. Read success must not mutate the
mode, create a session, or authorize Gesture. Connection-generation fencing
belongs to the control/notification binding, not this public immutable identity.
No buffer aliasing or readiness guarantee can be inferred from nonnull pointers.

The existing encoder and offset-zero view are left unchanged. No callback
candidate or static owner was added merely to create an apparently linkable
image. Sixth-service capacity, callback thread, retained lookup ownership,
registration rollback and reset/publication ordering remain unresolved.
Task-context evidence belongs in [the task mapping](UNIFIED_TASK_BINDINGS.md);
boot-source evidence belongs in [the boot-ID audit](UNIFIED_BOOT_ID_SOURCE.md).

## Verification record

The exact stock image remains SHA-256
`b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0`.
The independently decoded 42-byte file slice `0x7aa4..0x7ace` hashes to
`afa084929b14bc6fb0374e11056bf4efd67c69b0c1d7cbed5616af500820ae95`.

The unchanged `tests/test_fwtransport.py` suite was rerun with the current
hash-pinned main test ELF: **62 passed in 0.20 s**, no skips. Its four read cases
cover stored lengths 0/1/10 and offsets 0/8; other cases cover registration,
write ABI, notifications and queue failure boundaries. This is a focused rerun,
not 62 newly added tests, a new guarded checkpoint or a physical stack test.
The prior 3251-test build and 63-test supplement remain unchanged.

Source hashes at commit `49301d9b75816ccde1cc9657b827fdadf5736937`:

| Source under `ATC_RTL_BLE_OEPL_8762ESL/` | Bytes | SHA-256 |
|---|---:|---|
| `sdk/inc/bluetooth/profile/profile_server.h` | 23053 | `c3b04ad9a164ce1e7c0e05f3314ebe401027031c2abf479a1e15bb983f4497b0` |
| `sdk/inc/bluetooth/gap/gap.h` | 24289 | `856080e9ec5cf29e530f555a957cf0fc217840021db188e23a974833a0830260` |
| `sdk/inc/bluetooth/gap/bt_types.h` | 33945 | `5ddd8206ff7ae25a537447370821ceb98af96ca4223b130650a080f738c2d452` |
| `sdk/src/ble/profile/server/simple_ble_service.c` | 18322 | `794c3405071589edd9d489c8e8c2b5592e1b15ec2abda0f45348caa4e937e8f6` |

These compatible-source declarations are not a signed SDK, exact upper-stack
implementation or buffer/thread ownership proof. All release gates stay open.
