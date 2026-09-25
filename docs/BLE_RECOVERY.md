# Raw BLE reachability recovery

Status: **tool built and unit-tested.** The same-Mac cached-direct transport was
run against the ring on 2026-09-25; no raw-capable adapter is attached, so the
raw-HCI transport has not been physically run. This is a link diagnostic, not a
firmware flasher.

The direct run retrieved cached peripheral
`3C2FA77E-1BE3-A0C5-0DD5-DB6A3AD452B2` with name `R02_CC07` and disconnected
state, then queued a direct CoreBluetooth connection for the complete 300-second
window. It received no connection callback and timed out. It performed zero
characteristic reads, characteristic writes, sensor commands, or DFU writes.
This establishes no connectable response through the Mac controller during that
window; it does not attest the installed image or prove the MCU is unpowered.

The installed candidate's Bluetooth failure has two separate layers:

1. The phone app used to depend on advertisements or one saved CoreBluetooth
   identifier. That app path is now repaired and deployed, including recovery
   of historical identifiers and system-connected UART/DFU peripherals.
2. The ring currently emits no R02/UART/DFU or other plausible connectable
   advertisement visible to CoreBluetooth, and cached direct connections from
   both macOS and iOS receive no radio response.

`python -m probe.ble_recovery` has two transports. `darwin-wait` asks
CoreBluetooth for the exact cached peripheral and queues a direct connection,
bypassing scan/name matching. It discovers and reports service UUIDs only after
a link; it performs no characteristic read/write. The raw-HCI transport on a
dedicated Linux BLE adapter parses legacy, directed and extended advertising
reports, including advertisements with no name. Its `recover` command issues LE
Create Connection only after the exact address was observed as connectable in
that same process. A successful link is immediately disconnected. Neither path
sends ring protocol, sensor, DFU, or firmware data.

## Same-Mac cached direct latch

Close the phone ring app and every other ring client before using this path.
The historical macOS CoreBluetooth identifier is intentionally different from
the iPhone's identifier.

```sh
.venv/bin/python -m probe.ble_recovery darwin-wait \
  --identifier 3C2FA77E-1BE3-A0C5-0DD5-DB6A3AD452B2 \
  --seconds 300 --execute
```

This is stronger than another application scan: CoreBluetooth queues the exact
cached peripheral even while it is absent from scan results. It is not stronger
than the BLE link layer; the controller still waits for a connectable packet.

## Hardware requirement

The current Mac has only an Apple BCM_4388C2 PCIe controller. Apple exposes it
through CoreBluetooth, not Linux's raw HCI socket. Use a dedicated USB BLE 5
adapter attached to native Linux, a Linux VM with USB pass-through, or a
Raspberry Pi. Do not share the adapter with keyboards or other active devices.

```sh
python -m probe.ble_recovery doctor
sudo .venv/bin/python -m probe.ble_recovery scan \
  --adapter 1 --seconds 90 --execute
sudo .venv/bin/python -m probe.ble_recovery recover \
  --adapter 1 --address 30:32:41:33:CC:07 --seconds 90 --execute
```

The known rotating address `53:20:0D:60:4C:8F` must be treated separately and
may no longer be current. `scan` prints address type, connectability, direction,
name, service UUIDs and raw AD bytes. Never choose an address merely because it
is strong; use an R02 name/UART/DFU UUID or a controlled proximity movement.

## Hard boundary

Raw HCI bypasses CoreBluetooth's discovery filtering and stale peripheral
cache. It does **not** bypass the BLE link layer. An initiator transmits a
connection request in response to a connectable advertisement. If the ring's
firmware left advertising stopped, its controller crashed, or its radio is
unpowered, a binary connection command has nothing on-air to answer.

If a raw scan sees the ring, the next bounded step is a link proof followed by
a reviewed BlueZ GATT/DFU recovery plan. If it sees nothing, repeating connection
commands is not recovery; only a true power-on reset or the board's physical ROM
boot/UART path can run code. The RT02CR_V3.1 pad map, voltage/reset routing,
security state and calibration-preserving factory procedure are not known, so
opening or shorting the daily ring is not authorized by this document.
