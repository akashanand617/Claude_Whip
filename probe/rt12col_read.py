"""Acquire and authenticate the installed RT12COL application; never flash.

This is a deliberately separate, fixed plan. CD01 has stock bookkeeping side
effects, so close QRing, the iPhone app and every other laptop client first.
The output directory must not exist. A malformed/late/foreign reply aborts the
session with no retry and no firmware artifact.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import time

from whip import capture, fwrt12col, fwrt12col_read, protocol


async def run(args) -> int:
    if not args.confirmed_idle_clients:
        raise ValueError("explicit idle/exclusive-session confirmation is required")
    out = args.output.resolve()
    out.mkdir(exist_ok=False)
    resume_header = None
    resume_prefix = b""
    resume_sha256 = None
    if args.resume_transcript is not None:
        resume_raw = args.resume_transcript.resolve().read_bytes()
        resume_header, resume_prefix = fwrt12col_read.recover_resume_prefix(resume_raw)
        resume_sha256 = hashlib.sha256(resume_raw).hexdigest()
    transcript_path = out / "transcript.jsonl"
    with transcript_path.open("x") as stream:
        request_count = 0

        def emit(item):
            nonlocal request_count
            if item.get("kind") == "request":
                request_count += 1
            stream.write(json.dumps(item, sort_keys=True) + "\n")
            stream.flush()

        emit({
            "kind": "header",
            "wall": time.time(),
            "plan": "rt12col-stock-partition-v1",
            "flashing": False,
            "sensor_commands": False,
            "memory_writes": False,
            "automatic_retry": False,
            "warning": "CD01 changes stock bookkeeping; full payload read only after repeated header validation",
            "resume_transcript_sha256": resume_sha256,
            "resume_payload_bytes": len(resume_prefix),
        })
        reader = None
        try:
            device = await capture.find_ring(address=args.address, timeout=args.scan_timeout)
            async with capture.connected(device) as client:
                info = await capture.read_device_info(client, device)
                emit({"kind": "device", **info.as_dict()})
                if ((args.address is not None and info.address != args.address)
                        or info.hardware != fwrt12col.HARDWARE
                        or info.firmware != fwrt12col.STOCK_VERSION
                        or not protocol.looks_like_ring(info.name)):
                    raise RuntimeError("unexpected ring identity; no CD01 command sent")
                reader = fwrt12col_read.RT12COLReader(
                    client, emit, timeout=args.reply_timeout, spacing=args.spacing,
                    batch_size=args.batch_size,
                )
                await client.start_notify(protocol.UART_TX_CHAR_UUID, reader.notify)
                try:
                    async with asyncio.timeout(args.session_timeout):
                        partition, report = await fwrt12col_read.collect_stock_partition(
                            reader,
                            resume_header=resume_header,
                            resume_prefix=resume_prefix,
                        )
                finally:
                    await client.stop_notify(protocol.UART_TX_CHAR_UUID)

            if (args.expected_payload_sha256 is not None
                    and report["payload_sha256"] != args.expected_payload_sha256):
                raise RuntimeError(
                    "independent RT12COL payload SHA differs from the expected prior read"
                )
            restore = fwrt12col.reconstruct_stock_ota(
                partition, expected_payload_sha256=args.expected_payload_sha256
            )
            (out / "rt12col-installed-partition.bin").write_bytes(partition)
            (out / "rt12col-stock-restore.bin").write_bytes(restore)
            report.update(
                ota_bytes=len(restore),
                ota_sha256=hashlib.sha256(restore).hexdigest(),
                requests=request_count,
                ota_validation=fwrt12col.verify_ota(restore, require_ready=False),
                install_approved=False,
                independent_payload_sha_required=not report["header_payload_sha_matches"],
                expected_payload_sha256=args.expected_payload_sha256,
            )
            with (out / "report.json").open("x") as target:
                json.dump(report, target, indent=2, sort_keys=True)
                target.write("\n")
            emit({"kind": "completed", **report})
            print(f"Authenticated RT12COL stock application saved under {out}; nothing was flashed.")
            return 0
        except BaseException as exc:
            if reader is not None:
                reader.poisoned = True
                reader.closed = True
            emit({"kind": "aborted", "error": str(exc), "retry": False})
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", help="exact CoreBluetooth UUID or platform BLE address; otherwise require one unambiguous ring")
    parser.add_argument("--output", required=True, type=Path, help="new evidence directory")
    parser.add_argument("--confirmed-idle-clients", action="store_true")
    parser.add_argument("--scan-timeout", type=float, default=20.0)
    parser.add_argument("--reply-timeout", type=float, default=3.0)
    parser.add_argument("--session-timeout", type=float, default=900.0)
    parser.add_argument("--spacing", type=float, default=0.005)
    parser.add_argument("--batch-size", type=int, default=8,
                        help="ordered CD01 requests in flight (1..32); payload SHA detects loss/reordering")
    parser.add_argument("--resume-transcript", type=Path,
                        help="aborted prior transcript; reuse only its exact contiguous checksummed prefix")
    parser.add_argument("--expected-payload-sha256",
                        help="required independent whole-payload SHA when the installed factory header is stale")
    args = parser.parse_args()
    try:
        return asyncio.run(run(args))
    except (RuntimeError, ValueError, TimeoutError) as exc:
        print(f"RT12COL acquisition stopped without retry: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
