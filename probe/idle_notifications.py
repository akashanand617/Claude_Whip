"""Bounded passive UART observation; read DIS, never send a UART command.

Subscribe for 60 seconds, unsubscribe and disconnect. Retain only command byte,
length, checksum validity and valid 0x73 subtype, never health values. Not a capability probe,
retry of a failed read, or proof that the ring is idle.
"""
import argparse
import asyncio
import json
import time
from pathlib import Path

from whip import protocol

OBSERVATION_SECONDS = 60
MAX_NOTIFICATIONS = 120


async def observe(client, emit):
    fault = asyncio.Event()
    reason = None
    count = 0
    families = {}
    closed = False

    def notify(_sender, raw):
        nonlocal reason, count
        if closed or fault.is_set(): return
        packet = bytes(raw)
        metadata = protocol.notification_metadata(packet)
        command, valid = metadata["command"], metadata["checksum_valid"]
        count += 1
        label = "empty" if command is None else f"{command:02x}"
        families[label] = families.get(label, 0) + 1
        emit({"kind": "notification_metadata", **metadata, "monotonic": time.monotonic()})
        if not valid: reason = "invalid UART notification; stop passive observation"
        elif command in (0xA1, 0xCD): reason = "stream or diagnostic traffic; exclusive idle assumption not met"
        elif count >= MAX_NOTIFICATIONS: reason = "notification budget reached"
        if reason is not None: fault.set()

    await client.start_notify(protocol.UART_TX_CHAR_UUID, notify)
    try:
        try:
            await asyncio.wait_for(fault.wait(), OBSERVATION_SECONDS)
        except TimeoutError:
            pass
    finally:
        closed = True
        await client.stop_notify(protocol.UART_TX_CHAR_UUID)
    if reason is not None: raise RuntimeError(reason)
    return {"notifications": count, "families": families,
            "observation_seconds": OBSERVATION_SECONDS, "idle_proven": False,
            "uart_commands_sent": 0, "payload_saved": False}


async def run(args):
    if not args.confirmed_idle_clients:
        raise ValueError("fresh closed-client confirmation required")
    output = args.output.resolve()
    output.mkdir(exist_ok=False)
    from whip import capture
    with (output / "transcript.jsonl").open("x") as stream:
        def emit(item):
            stream.write(json.dumps(item) + "\n")
            stream.flush()
        emit({"kind": "header", "plan": "passive-notification-types-v2", "wall": time.time(),
              "observation_seconds": OBSERVATION_SECONDS, "max_notifications": MAX_NOTIFICATIONS,
              "uart_commands_sent": 0, "sensor_commands": False, "flashing": False,
              "payload_saved": False})
        client = None
        try:
            async with asyncio.timeout(210):
                device = await capture.find_ring(address=args.address)
                async with capture.connected(device) as client:
                    info = await capture.read_device_info(client, device)
                    emit({"kind": "device", **info.as_dict()})
                    if (info.address != args.address or info.hardware != "RT02CR_V3.1" or
                            info.firmware != "RT02CR_3.12.07_260514" or not protocol.is_expected_ring(info.name)):
                        raise RuntimeError("unexpected ring identity; no observation started")
                    result = await observe(client, emit)
                if client.is_connected: raise RuntimeError("disconnect not confirmed")
            emit({"kind": "disconnected", "confirmed": True})
            emit({"kind": "completed", **result})
            print(f"Passive observation saved: {output}. Disconnected; no UART command sent.")
            return 0
        except BaseException as exc:
            disconnected = None
            if client is not None:
                try: disconnected = not client.is_connected
                except Exception: pass
            emit({"kind": "aborted", "error": str(exc), "retry": False,
                  "disconnect_confirmed": disconnected})
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True, help="specific BLE device identifier")
    parser.add_argument("--output", required=True, type=Path, help="new evidence directory")
    parser.add_argument("--confirmed-idle-clients", action="store_true")
    args = parser.parse_args()
    try: return asyncio.run(run(args))
    except (Exception, KeyboardInterrupt) as exc:
        print(f"Passive observation stopped without retry: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
