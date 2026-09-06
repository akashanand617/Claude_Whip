"""
Flash firmware to the ring over BLE.

    python -m probe.flash firmware/rt02cr-low-latency.bin --dry-run
    python -m probe.flash firmware/rt02cr-low-latency.bin
    python -m probe.flash firmware/rt02cr-stock-3.12.02.bin --init-type 1   # restore

This ring has no recovery path if DFU itself stops answering, so the design
here is refuse-by-default:

  - the image is parsed and its hardware string compared to the ring's before
    anything is written
  - the SHA-256 is checked against the pinned catalogue value unless explicitly
    waived
  - battery is read and the transfer refused below a floor well above the 20%
    the protocol enforces
  - every frame is acknowledged before the next is sent, and any status other
    than `ok` aborts immediately rather than continuing hopefully
  - `--dry-run` builds and validates every byte that would be transmitted,
    without connecting

`--dry-run` is the whole transfer minus the radio. Run it first, every time.

NOTE: the on-device transfer path has not been exercised against hardware. The
frame construction is verified against upstream's published constants (see
tests/test_dfu.py), but the sequencing has only been reasoned about, not
observed. Treat the first real run as an experiment.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from pathlib import Path

from whip import capture, dfu, fwimage, protocol

MANIFEST_PATH = Path("firmware/upstream-manifest.json")

# The protocol refuses below 20%. A stalled transfer is unrecoverable, so keep
# a wide margin rather than the bare minimum.
BATTERY_FLOOR_PERCENT = 50

DEFAULT_SEGMENT_BYTES = 240
ACK_TIMEOUT_S = 15.0
CONFIRM_WORD = "FLASH"


class FlashAborted(RuntimeError):
    pass


def load_catalogue_entry(image: fwimage.FirmwareImage) -> dict | None:
    """
    Find a pinned hash for this image.

    Two sources. Upstream's manifest covers the catalogue firmware and also
    carries compatibility rules. `firmware/SHA256SUMS` covers everything else we
    archive -- notably the vendor stock image, which is the only restore path
    for this ring and is not in anyone's catalogue. Recovery is the worst moment
    to be flashing something unverified, so it gets pinned too.
    """
    if MANIFEST_PATH.exists():
        manifest = json.loads(MANIFEST_PATH.read_text())
        entry = next((e for e in manifest["firmware"] if e["fileName"] == image.path.name), None)
        if entry:
            return entry

    sums = MANIFEST_PATH.parent / "SHA256SUMS"
    if sums.exists():
        for line in sums.read_text().splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1] == image.path.name:
                return {"id": f"local:{parts[1]}", "sha256": parts[0]}

    return None


def firmware_is_compatible(entry: dict, hardware: str, firmware: str) -> bool:
    """Upstream's compatibility rule: hardware exact, firmware exact or by prefix."""
    hardware_ok = hardware.strip() in [h.strip() for h in entry["compatibleCurrentHardware"]]
    firmware_ok = firmware.strip() in [f.strip() for f in entry["compatibleCurrentFirmware"]] or any(
        firmware.strip().startswith(p.strip()) for p in entry["compatibleCurrentFirmwarePrefixes"]
    )
    return hardware_ok and firmware_ok


def preflight(image: fwimage.FirmwareImage, entry: dict | None, allow_unpinned: bool) -> None:
    """Everything checkable without a ring. Raises FlashAborted on any failure."""
    print("  image           ", image.path.name)
    print("  size            ", image.size, "bytes")
    print("  sha256          ", image.sha256)
    print("  declares hw     ", repr(image.hardware_string))
    print("  declares fw     ", repr(image.firmware_string))

    stats = dfu.firmware_stats(image.path.read_bytes())
    print(f"  crc16 / sum16    {stats['crc16']} / {stats['checksum16']}")
    print(f"  chunks           {dfu.chunk_count(image.size)} x {dfu.CHUNK_SIZE_BYTES} bytes")

    if entry is None:
        if not allow_unpinned:
            raise FlashAborted(
                f"{image.path.name} is not in firmware/upstream-manifest.json, so its hash cannot "
                "be checked. Pass --allow-unpinned if this is deliberate."
            )
        print("  catalogue        NOT PINNED (--allow-unpinned)")
        return

    if image.sha256 != entry["sha256"]:
        raise FlashAborted(
            f"sha256 mismatch.\n    expected {entry['sha256']}\n    got      {image.sha256}"
        )
    print(f"  catalogue        {entry['id']}  sha256 OK")


class DfuChannel:
    """
    One notification subscription for the whole transfer, with a slot for the
    reply we are currently waiting on.

    Subscribing per frame would mean 135 subscribe/unsubscribe cycles mid-flash,
    each a chance to miss the acknowledgement it was meant to catch.
    """

    def __init__(self, client, segment_bytes: int) -> None:
        self._client = client
        self._segment_bytes = segment_bytes
        self._pending: asyncio.Future | None = None

    def on_notify(self, _sender, data: bytearray) -> None:
        if self._pending is not None and not self._pending.done():
            self._pending.set_result(bytes(data))

    async def subscribe(self) -> None:
        await self._client.start_notify(protocol.DFU_NOTIFY_CHAR_UUID, self.on_notify)

    async def unsubscribe(self) -> None:
        try:
            await self._client.stop_notify(protocol.DFU_NOTIFY_CHAR_UUID)
        except Exception:  # noqa: BLE001, S110 - teardown only
            pass

    async def send(self, frame: dfu.Frame) -> dfu.Response:
        """Write one frame in BLE-sized segments, then wait for its acknowledgement."""
        name = dfu.COMMAND_NAMES.get(frame.command, str(frame.command))
        self._pending = asyncio.get_running_loop().create_future()

        # Write-with-response throughout. It is slower than fire-and-forget, but
        # a silently dropped segment mid-image is the failure with no recovery.
        for chunk in dfu.segment(frame, self._segment_bytes):
            await self._client.write_gatt_char(protocol.DFU_WRITE_CHAR_UUID, chunk, response=True)

        try:
            raw = await asyncio.wait_for(self._pending, timeout=ACK_TIMEOUT_S)
        except asyncio.TimeoutError as exc:
            raise FlashAborted(f"no acknowledgement for {name} within {ACK_TIMEOUT_S:.0f}s") from exc
        finally:
            self._pending = None

        response = dfu.parse_response(raw)
        if not response.valid:
            raise FlashAborted(f"malformed reply to {name}: {response.error}")
        if not response.ok:
            raise FlashAborted(
                f"ring rejected {name}: {response.status_name} (code {response.status_code})"
            )
        return response


async def transfer(channel: DfuChannel, firmware: bytes, init_type: int) -> None:
    """START -> INIT -> DATA* -> CHECK -> END, aborting on the first bad status."""
    total = dfu.chunk_count(len(firmware))

    print("\n  starting transfer -- do not move the ring or sleep the machine\n")
    await channel.send(dfu.start_frame())
    print("    START   ok")

    await channel.send(dfu.init_frame(firmware, init_type))
    print(f"    INIT    ok (type {init_type})")

    started = time.perf_counter()
    for index in range(total):
        await channel.send(dfu.data_frame(firmware, index))
        done = index + 1
        if done % 5 == 0 or done == total:
            elapsed = time.perf_counter() - started
            rate = done / elapsed if elapsed else 0
            eta = (total - done) / rate if rate else 0
            print(f"    DATA    {done:3d}/{total}  {done / total * 100:5.1f}%  eta {eta:4.0f}s")

    await channel.send(dfu.check_frame())
    print("    CHECK   ok")

    await channel.send(dfu.end_frame())
    print("    END     ok")


async def run(args: argparse.Namespace) -> int:
    image = fwimage.inspect(args.image)
    entry = load_catalogue_entry(image)

    print("=" * 64)
    print("  PREFLIGHT")
    print("=" * 64)
    preflight(image, entry, args.allow_unpinned)

    if args.dry_run:
        firmware = image.path.read_bytes()
        total = dfu.chunk_count(len(firmware))
        rebuilt = b"".join(dfu.data_frame(firmware, i).payload[2:] for i in range(total))
        if rebuilt != firmware:
            raise FlashAborted("chunking does not reassemble to the original image")
        segments = sum(len(dfu.segment(dfu.data_frame(firmware, i), args.segment_bytes)) for i in range(total))
        print(f"\n  dry run: {total} chunks -> {segments} BLE writes, reassembly verified")
        print("  no connection attempted")
        return 0

    print()
    print("=" * 64)
    print("  RING")
    print("=" * 64)
    device = await capture.find_ring(address=args.address, timeout=args.timeout)
    async with capture.connected(device) as client:
        info = await capture.read_device_info(client, device)
        print(f"  connected       {info.name}")
        print(f"  hardware        {info.hardware!r}")
        print(f"  firmware        {info.firmware!r}")

        if image.hardware_string.strip() != (info.hardware or "").strip():
            raise FlashAborted(
                f"hardware mismatch: image is for {image.hardware_string!r}, "
                f"ring reports {info.hardware!r}"
            )
        print("  hardware match  OK")

        if entry and not firmware_is_compatible(entry, info.hardware or "", info.firmware or ""):
            raise FlashAborted(
                f"ring firmware {info.firmware!r} is outside the catalogue compatibility list for "
                f"{entry['id']}"
            )
        if entry:
            print("  compatibility   OK")

        battery = await capture.read_battery(client)
        if battery is None:
            raise FlashAborted("could not read battery level; refusing to flash blind")
        level, charging = battery
        print(f"  battery         {level}%{' (charging)' if charging else ''}")
        if level < args.battery_floor:
            raise FlashAborted(f"battery {level}% is below the {args.battery_floor}% floor")

        if not args.yes:
            print(f"\n  About to overwrite firmware on {info.name}.")
            print("  There is no recovery path if DFU stops responding.")
            reply = input(f"  Type {CONFIRM_WORD} to proceed: ").strip()
            if reply != CONFIRM_WORD:
                print("  aborted")
                return 1

        channel = DfuChannel(client, args.segment_bytes)
        await channel.subscribe()
        try:
            await transfer(channel, image.path.read_bytes(), args.init_type)
        finally:
            await channel.unsubscribe()

    print("\n  transfer complete. Verify with:")
    print("    python -m probe.scan")
    print("    python -m probe.stream --duration 60 --label postflash --stationary")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Flash firmware to a Colmi ring over BLE")
    parser.add_argument("image", help="path to the OTA image")
    parser.add_argument("--dry-run", action="store_true", help="build and validate every frame, do not connect")
    parser.add_argument("--init-type", type=int, choices=(1, 4), default=4,
                        help="4 skips the app-level hardware-string compare (catalogue images expect 4)")
    parser.add_argument("--segment-bytes", type=int, default=DEFAULT_SEGMENT_BYTES)
    parser.add_argument("--battery-floor", type=int, default=BATTERY_FLOOR_PERCENT)
    parser.add_argument("--allow-unpinned", action="store_true", help="permit an image absent from the manifest")
    parser.add_argument("--yes", action="store_true", help="skip the typed confirmation")
    parser.add_argument("--address")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    try:
        return asyncio.run(run(args))
    except FlashAborted as exc:
        print(f"\n  ABORTED: {exc}")
        return 2
    except RuntimeError as exc:
        print(f"\n  error: {exc}")
        return 1
    except KeyboardInterrupt:
        print("\n  interrupted -- if a transfer was in progress the ring may be in DFU state")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
