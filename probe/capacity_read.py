"""Explicit idle-only configuration/optional fixed bank0 descriptor diagnostic.

CD01 reads DATA but its legacy dispatch changes bookkeeping. Close all other
clients and ensure no stream/DFU first. Requires an explicit address and idle
confirmation. No arbitrary addresses, bank following, retries or auto-reconnect.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import time

from whip import fwcapacity, fwcapacity_read, fwidentity, protocol

ROOT = Path(__file__).resolve().parents[1]


async def run(args):
    if not getattr(args, "confirmed_idle_clients", False):
        raise ValueError("explicit idle/exclusive-session confirmation is required")
    # Import BLE only in this explicitly invoked hardware entry point.
    from whip import capture
    base = (ROOT / "firmware/rt02cr-25hz.bin").read_bytes()
    candidate = (ROOT / "firmware/rt02cr-25hz-optical-off-v2-experimental.bin").read_bytes()
    fwidentity.validate_images(base, candidate)
    fwcapacity.audit_cd_image(base)
    fwcapacity.audit_cd_image(candidate)
    out = args.output.resolve()
    out.mkdir(exist_ok=False)
    with (out / "transcript.jsonl").open("x") as stream:
        def emit(item):
            stream.write(json.dumps(item) + "\n")
            stream.flush()
        emit({"kind": "header", "wall": time.time(), "flashing": False,
              "sensor_commands": False, "arbitrary_memory": False,
              "bank0_descriptor_plan": bool(args.bank0_descriptor),
              "warning": "CD prelude bookkeeping side effects; critical-site fingerprint is not full attestation"})
        try:
            device = await capture.find_ring(address=args.address)
            async with capture.connected(device) as client:
                info = await capture.read_device_info(client, device)
                emit({"kind": "device", **info.as_dict()})
                if (info.hardware != "RT02CR_V3.1" or info.firmware != "RT02CR_3.12.07_260514"
                        or not protocol.is_expected_ring(info.name)):
                    raise RuntimeError("unexpected device/firmware family; no diagnostic command sent")
                reader_type = (fwcapacity_read.DescriptorReader if args.bank0_descriptor
                               else fwcapacity_read.CapacityReader)
                reader = reader_type(client, emit)
                await client.start_notify(protocol.UART_TX_CHAR_UUID, reader.notify)
                try:
                    collect = (fwcapacity_read.collect_bank0_descriptor if args.bank0_descriptor
                               else fwcapacity_read.collect_configuration)
                    captured = await collect(reader, base, candidate, out.name)
                finally:
                    await client.stop_notify(protocol.UART_TX_CHAR_UUID)
            with (out / "configuration.json").open("x") as target:
                json.dump(captured, target, indent=2)
                target.write("\n")
            try:
                report = fwcapacity.analyze_capture(captured, vendor_file_size=138016)
            except ValueError as exc:
                emit({"kind": "interpretation_refused", "error": str(exc)})
                print(f"Saved bounded data at {out}; configuration interpretation refused: {exc}")
                return 2
            with (out / "report.json").open("x") as target:
                json.dump(report, target, indent=2)
                target.write("\n")
            emit({"kind": "completed", "configuration_bytes": 64, "repeated_equal": True,
                  "flash_authorized": False, "bank_descriptor_reads": bool(args.bank0_descriptor),
                  "descriptor_bytes": 80 if args.bank0_descriptor else 0})
            print(f"Saved configuration and transcript: {out}. No flash or sensor command.")
            return 0
        except BaseException as exc:
            emit({"kind": "aborted", "error": str(exc), "retry": False})
            raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--address", required=True)
    p.add_argument("--output", required=True, type=Path, help="new evidence directory; never overwritten")
    p.add_argument("--bank0-descriptor", action="store_true",
                   help="separately coordinated fixed 0x802198/80 read after exact prior V2/config match")
    p.add_argument("--confirmed-idle-clients", action="store_true",
                   help="all other clients closed; no stream/DFU; acknowledge CD bookkeeping side effects")
    args = p.parse_args()
    if not args.confirmed_idle_clients:
        p.error("explicit idle/exclusive-session confirmation is required")
    try:
        return asyncio.run(run(args))
    except (RuntimeError, ValueError, TimeoutError) as exc:
        print(f"Diagnostic stopped without retry: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
