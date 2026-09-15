"""
Firmware flashing as a library, so the CLI and the web frontend share one path.

This ring has no recovery if DFU itself stops answering, so the design is
refuse-by-default, and every gate lives HERE -- not in the callers -- so no
frontend can forget one:

  - the image is parsed and its hardware string compared to the ring's before
    anything is written
  - the SHA-256 is checked against the pinned catalogue value unless explicitly
    waived
  - battery is read and the transfer refused below a floor well above the 20%
    the protocol enforces
  - every frame is acknowledged before the next is sent, and any status other
    than `ok` aborts immediately rather than continuing hopefully

Progress is reported through a callback taking small dicts, because the two
consumers want different things done with it: the CLI prints lines, the server
pushes websocket frames. Confirmation is deliberately NOT here -- asking "type
FLASH" is interaction, and interaction belongs to the caller.

`probe.flash` is the CLI over this; the server's /api/flash is the other caller.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from whip import capture, dfu, fwimage, protocol

MANIFEST_PATH = Path("firmware/upstream-manifest.json")

# The protocol refuses below 20%. A stalled transfer is unrecoverable, so keep
# a margin -- but not an arbitrary one. The transfer is a few hundred BLE writes
# over a minute or two, well under 1 mAh out of a 17 mAh cell, so the charge
# level is not what decides whether it survives.
BATTERY_FLOOR_PERCENT = 40

DEFAULT_SEGMENT_BYTES = 240
ACK_TIMEOUT_S = 15.0

# What the frontend offers. Both images are hash-pinned in firmware/SHA256SUMS;
# init type 1 is the stock-restore path, 4 the catalogue path -- measured, not
# guessed, during the original flashing work.
FLASH_TARGETS = {
    "gesture": {
        "image": Path("firmware/rt02cr-25hz.bin"),
        "init_type": 4,
        "title": "Gesture firmware (25 Hz)",
        "description": "Streams motion at 25 Hz for gesture detection. "
                       "LEDs stay lit while streaming; ~5.5 h of continuous "
                       "streaming on a charge. Health features unavailable.",
    },
    "stock": {
        "image": Path("firmware/rt02cr-stock-3.12.02.bin"),
        "init_type": 1,
        "title": "Stock firmware (normal ring)",
        "description": "The vendor firmware: health tracking, phone app, "
                       "normal battery life. Motion streams at 1 Hz, far too "
                       "slow for gestures.",
    },
}

# Ring-reported firmware strings, for telling a user which mode they are in.
# The container's internal version string and what the ring reports over DIS
# are not always identical, so both known spellings are listed. Anything else
# is honestly "unknown", never a guess.
GESTURE_FIRMWARE_STRINGS = {"RT02CR_3.12.07_260514", "RT02CR_3.12.00_251205"}
STOCK_FIRMWARE_STRINGS = {"RT02CR_3.12.02_260824"}


def detect_mode(firmware: str | None) -> str:
    if not firmware:
        return "unknown"
    fw = firmware.strip()
    if fw in GESTURE_FIRMWARE_STRINGS:
        return "gesture"
    if fw in STOCK_FIRMWARE_STRINGS:
        return "stock"
    return "unknown"


class FlashAborted(RuntimeError):
    pass


def _emit(progress, **payload) -> None:
    if progress is not None:
        progress(payload)


def print_progress(payload: dict) -> None:
    """The CLI's progress consumer: the same lines the tool always printed."""
    stage = payload.get("stage")
    if stage == "fact":
        print(f"  {payload['name']:<16} {payload['value']}")
    elif stage == "data":
        done, total = payload["done"], payload["total"]
        print(f"    DATA    {done:3d}/{total}  {done / total * 100:5.1f}%  "
              f"eta {payload['eta_s']:4.0f}s")
    elif stage == "frame":
        print(f"    {payload['frame']:<7} {payload['message']}")
    elif stage == "message":
        print(f"  {payload['message']}")


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


def has_compatibility_rules(entry: dict | None) -> bool:
    """
    Whether this entry carries upstream's compatibility metadata.

    Images pinned locally via firmware/SHA256SUMS -- our own builds, and the
    vendor stock image -- have a hash and nothing else. They are still gated on
    the image's declared hardware string matching the ring, which is the check
    that actually protects the device; the catalogue's firmware-family rule
    simply does not exist for them.
    """
    return bool(entry) and "compatibleCurrentHardware" in entry


def firmware_is_compatible(entry: dict, hardware: str, firmware: str) -> bool:
    """Upstream's compatibility rule: hardware exact, firmware exact or by prefix."""
    hardware_ok = hardware.strip() in [h.strip() for h in entry["compatibleCurrentHardware"]]
    firmware_ok = firmware.strip() in [f.strip() for f in entry["compatibleCurrentFirmware"]] or any(
        firmware.strip().startswith(p.strip()) for p in entry["compatibleCurrentFirmwarePrefixes"]
    )
    return hardware_ok and firmware_ok


def preflight(image: fwimage.FirmwareImage, entry: dict | None, allow_unpinned: bool,
              progress=print_progress) -> None:
    """Everything checkable without a ring. Raises FlashAborted on any failure."""
    _emit(progress, stage="fact", name="image", value=image.path.name)
    _emit(progress, stage="fact", name="size", value=f"{image.size} bytes")
    _emit(progress, stage="fact", name="sha256", value=image.sha256)
    _emit(progress, stage="fact", name="declares hw", value=repr(image.hardware_string))
    _emit(progress, stage="fact", name="declares fw", value=repr(image.firmware_string))

    stats = dfu.firmware_stats(image.path.read_bytes())
    _emit(progress, stage="fact", name="crc16 / sum16",
          value=f"{stats['crc16']} / {stats['checksum16']}")
    _emit(progress, stage="fact", name="chunks",
          value=f"{dfu.chunk_count(image.size)} x {dfu.CHUNK_SIZE_BYTES} bytes")

    if entry is None:
        if not allow_unpinned:
            raise FlashAborted(
                f"{image.path.name} is not in firmware/upstream-manifest.json, so its hash cannot "
                "be checked. Pass --allow-unpinned if this is deliberate."
            )
        _emit(progress, stage="fact", name="catalogue", value="NOT PINNED (--allow-unpinned)")
        return

    if image.sha256 != entry["sha256"]:
        raise FlashAborted(
            f"sha256 mismatch.\n    expected {entry['sha256']}\n    got      {image.sha256}"
        )
    _emit(progress, stage="fact", name="catalogue", value=f"{entry['id']}  sha256 OK")


def dry_run(image: fwimage.FirmwareImage, segment_bytes: int = DEFAULT_SEGMENT_BYTES,
            progress=print_progress) -> dict:
    """The whole transfer minus the radio: build and validate every byte."""
    firmware = image.path.read_bytes()
    total = dfu.chunk_count(len(firmware))
    rebuilt = b"".join(dfu.data_frame(firmware, i).payload[2:] for i in range(total))
    if rebuilt != firmware:
        raise FlashAborted("chunking does not reassemble to the original image")
    segments = sum(len(dfu.segment(dfu.data_frame(firmware, i), segment_bytes))
                   for i in range(total))
    _emit(progress, stage="message",
          message=f"dry run: {total} chunks -> {segments} BLE writes, reassembly verified")
    return {"chunks": total, "ble_writes": segments}


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


async def transfer(channel: DfuChannel, firmware: bytes, init_type: int,
                   progress=print_progress) -> None:
    """START -> INIT -> DATA* -> CHECK -> END, aborting on the first bad status."""
    total = dfu.chunk_count(len(firmware))

    _emit(progress, stage="message",
          message="starting transfer -- do not move the ring or sleep the machine")
    await channel.send(dfu.start_frame())
    _emit(progress, stage="frame", frame="START", message="ok")

    await channel.send(dfu.init_frame(firmware, init_type))
    _emit(progress, stage="frame", frame="INIT", message=f"ok (type {init_type})")

    started = time.perf_counter()
    for index in range(total):
        await channel.send(dfu.data_frame(firmware, index))
        done = index + 1
        if done % 5 == 0 or done == total:
            elapsed = time.perf_counter() - started
            rate = done / elapsed if elapsed else 0
            eta = (total - done) / rate if rate else 0
            _emit(progress, stage="data", done=done, total=total, eta_s=eta)

    await channel.send(dfu.check_frame())
    _emit(progress, stage="frame", frame="CHECK", message="ok")

    # The ring reboots on END to apply the image, so it often never answers.
    # A missing acknowledgement here is expected, not a failure -- CHECK is the
    # frame that confirms the image was received and validated. Treating the
    # silence as an error made a successful flash report as ABORTED.
    try:
        await channel.send(dfu.end_frame())
        _emit(progress, stage="frame", frame="END", message="ok")
    except FlashAborted:
        _emit(progress, stage="frame", frame="END",
              message="no reply (expected -- the ring reboots to apply the image)")


async def flash_connected(client, device_info, image_path: Path, init_type: int,
                          battery_floor: int = BATTERY_FLOOR_PERCENT,
                          allow_unpinned: bool = False,
                          segment_bytes: int = DEFAULT_SEGMENT_BYTES,
                          progress=print_progress) -> None:
    """
    Every gate, then the transfer, against an already-connected client.

    Raises FlashAborted on any refusal. The caller owns connection lifecycle and
    confirmation; this owns everything that protects the ring.
    """
    image = fwimage.inspect(image_path)
    entry = load_catalogue_entry(image)
    preflight(image, entry, allow_unpinned, progress=progress)

    if image.hardware_string.strip() != (device_info.hardware or "").strip():
        raise FlashAborted(
            f"hardware mismatch: image is for {image.hardware_string!r}, "
            f"ring reports {device_info.hardware!r}"
        )
    _emit(progress, stage="fact", name="hardware match", value="OK")

    if has_compatibility_rules(entry):
        if not firmware_is_compatible(entry, device_info.hardware or "",
                                      device_info.firmware or ""):
            raise FlashAborted(
                f"ring firmware {device_info.firmware!r} is outside the catalogue "
                f"compatibility list for {entry['id']}"
            )
        _emit(progress, stage="fact", name="compatibility", value="OK")
    elif entry:
        _emit(progress, stage="fact", name="compatibility",
              value=f"no catalogue rules for {entry['id']} (hash-pinned only)")

    battery = await capture.read_battery(client)
    if battery is None:
        raise FlashAborted("could not read battery level; refusing to flash blind")
    level, charging = battery
    _emit(progress, stage="fact", name="battery",
          value=f"{level}%{' (charging)' if charging else ''}")
    if level < battery_floor:
        raise FlashAborted(f"battery {level}% is below the {battery_floor}% floor")

    channel = DfuChannel(client, segment_bytes)
    await channel.subscribe()
    try:
        await transfer(channel, image_path.read_bytes(), init_type, progress=progress)
    finally:
        await channel.unsubscribe()
