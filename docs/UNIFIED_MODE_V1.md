# Unified Health-default / temporary-Gesture V1

## 2026-09-25 postmortem — original image is structurally invalid

The original image/hash documented below has a proven builder defect. Startup
call `0x749A -> 0x791C` registers UART, while `0x74B6 -> 0x7B3A` registers FEE7.
The original builder disabled `0x749A` and then overwrote FEE7's attribute table,
so it removed UART registration while leaving FEE7 registered over helper code.
The earlier claim below that UART remained registered is false. Never install or
rebundle SHA-256 `b1070bed755ce14936501431e379c6c47570ce747265fe0b6af0e87553eb2dc4`.

The corrected offline builder uses `0x74B6`, fingerprints all five setup calls
and their callback tables, and produces SHA-256
`7e2b3e2e61906031f5b79262ca39022fc34518ab421f814a586f9e49f8691243`.
With pinned Zig 0.15.2, 154 focused builder/identity/container/recovery tests
pass with zero skips. This corrected image is **not installed, device-validated,
or flash-approved**; it cannot recover a ring that supplies no BLE link.

The invalid image is a credible cause of startup/service failure if it became
active, but current on-device identity was never attested. A normal encrypted
system link with fresh service discovery persisted before the final forced
Forget, and the separately decoded disconnect path can leave advertising in a
transitional state. The cause of the present silent radio therefore remains
unproven. See [BLE_RECOVERY.md](BLE_RECOVERY.md) for the new raw-HCI diagnostic.

Status: **REVOKED after failed physical boot validation on 2026-09-24.** The
ring accepted every DFU stage through CHECK and received END, but never returned
a valid R02/UART/DFU advertisement. Its charging indicator still operates.
Repeated charger wakes, corrected phone discovery and raw scan-only inventories
did not recover BLE. Do not install this image on another ring. The app's
Unified install action is hard-disabled; the stock rollback remains preserved
but requires a working BLE/DFU service.

A later all-advertisement proximity check corrected two additional false leads.
CoreBluetooth's invalid RSSI sentinel `127` is now discarded. The strongest
unnamed device that followed the first near/far movement was identified from
manufacturer payload `004c:12020003` as an Apple device and explicitly reported
`kCBAdvDataIsConnectable = 0`; it was not the ring. A second controlled pass,
with Apple devices held stationary and manufacturer/connectability recorded,
found no R02 name, UART/DFU service advertisement, or strong connectable
non-Apple device that followed the ring. No command or firmware write was sent.
The public COLMI instructions document charger attachment as activation, not a
separate charger-tap recovery or factory-reset sequence.

A subsequent stationary charger-trigger test kept other devices fixed, recorded
a 20-second baseline, and compared two separate 30-second windows after explicit
two-second charger taps. Neither tap produced an R02 name, UART/DFU UUID, or
nearby connectable non-Apple candidate. Apparent cross-window matches were weak
ambient Apple advertisements, a named Govee device, and unrelated advertised
services. This closes the current wireless-discovery attempt; repeating generic
scans is not a recovery method.

## Artifact

- Image: `firmware/rt02cr-25hz-health-default-gesture-v1-experimental.bin`
- Size: 137,540 bytes, exactly the pinned 25 Hz base size
- SHA-256: `b1070bed755ce14936501431e379c6c47570ce747265fe0b6af0e87553eb2dc4`
- Exact base SHA-256: `f13e63d3fdef3b10aa20fd4e0672077b66f60bb19c689ef64053840e4d35d3d9`
- Hardware: `RT02CR_V3.1`
- Builder: `python -m probe.build_unified_mode --out <new path>`
- Implementation: `whip/fwoptical_unified.py` and
  `firmware/unified/experiments/unified_mode_helpers.S`

The builder refuses every other base hash, size, hardware header, instruction
signature, or FEE7 database signature. It changes only the audited hook bytes,
the retired 252-byte FEE7 attribute database, and the container's derived hash
and body-sum fields. It does not grow the application, add persistent RAM, move
partitions, modify the 25 Hz period, change the accelerometer range, or touch the
DFU reassembly site.

## Runtime contract

Health is the boot/default behavior. With the existing raw-mode byte not equal
to four, the optical-enable and VC30F control paths reproduce stock behavior.

- Enter Gesture: `A1 04`. The existing STK wake and 25 Hz producer run, while
  optical sensor starts are rejected and VC30F RUN is translated to STOP.
- Return to Health: `A1 05`, then `A1 02`.
- Disconnect during Gesture: firmware clears raw mode and stops/deletes the raw
  timer; the next connection begins by sending the same two stop packets.

The 184-byte helper fits entirely in the retired FEE7 database, leaving 68
bytes untouched. FEE7's sole add-function call is disabled; its three callbacks
have no branch callers and only the retired descriptor pointers reference them.
UART, DFU, DIS, HID, Health, steps, and sleep services remain registered.

The phone accepts Gesture only after three checksum-valid A1/03 samples with at
least two distinct XYZ payloads. It assigns a connection-bound monotonic sample
sequence, runs the pinned gesture model, and returns to Health on explicit stop,
stale/inference failure, app backgrounding, or disconnect. Health jobs and mode
changes share one operation gate. Gesture intervals remain recorded as
unverified health coverage; the app does not manufacture zero steps or sleep.

## Offline evidence

- 71 candidate-specific tests pass, including byte-exact ARM assembly rebuild,
  container/change allowlists, FEE7 retirement references, and Cortex-M0
  execution of every new hook.
- 300 focused firmware/container/optical/capacity/transport regression tests
  pass; 128 unrelated legacy cases skip where their optional proof fixtures are
  unavailable.
- All 61 iOS tests pass with zero skips, including actual Core ML replay,
  checksum/freshness transition gates, all DFU frames compared with the Python
  implementation, and all three bundled image hashes.
- Debug and Release simulator builds succeed; the app bundles the exact image,
  fingerprints nine preselected code regions after reboot, and exposes
  **Unified Health + Gesture firmware** under Firmware maintenance.
- Independent Python DFU dry runs reconstruct all 135 chunks exactly: the
  unified transfer is 672 acknowledged BLE writes and the pinned stock rollback
  is 674. Both pass their local SHA/hardware preflights.

## Required bounded device validation

Offline evidence lowers risk but cannot make a reverse-engineered image
"completely safe." Before calling this production-ready on the only daily ring:

1. Confirm battery above 40%, not charging, exact RT02CR_V3.1 identity, all
   competing BLE clients closed, stock rollback image present, and DFU CHECK/END
   recovery path ready.
2. Flash only the SHA above. Confirm reboot/reconnect and the nine-site app
   fingerprint before issuing any mode command.
3. In default Health, verify battery, historical sync, current steps, configured
   heart-rate logging, and a successful live heart-rate measurement.
4. Enter Gesture once. Confirm no visible LEDs and fresh, distinct 25 Hz A1/03
   motion before testing the model.
5. Return to Health. Confirm raw notifications stop and live optical measurement
   works again; repeat switch, app-background, and disconnect cases.
6. Check a controlled step delta after the cycle. Sleep continuity requires an
   overnight observation and cannot honestly be approved in a short bench run.

After the post-flash reconnect, steps 3–5 are consolidated by:

```sh
python -m probe.validate_unified_mode --address <ring-address>
```

It refuses every sampled identity except `unified_candidate`, requires at least
40% battery and no charger, cleans up raw and realtime-HR modes in `finally`
paths, and writes one durable JSONL log under `data/unified_validation/`. Its
measured gates do not replace the wearer's LED observations or the later
steps/sleep checks.

No device write is authorized by this document alone.
