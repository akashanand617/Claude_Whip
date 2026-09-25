"""Idle-only fixed RAM-ownership reads on the installed V2 ring. NO flashing.

User-authorized 2026-09-24 for read-only connection. Requires fresh confirmation
that every other client is closed and nothing is streaming or updating. CD01
has connection/timer bookkeeping side effects. No arbitrary addresses, pointer
following, sensor/flash command, retry or reconnect. See whip/fwram_read.py.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import time

from whip import fwram_read as mr, protocol

ROOT = Path(__file__).resolve().parents[1]


async def run(args):
    if not getattr(args, "confirmed_idle_clients", False):
        raise ValueError("fresh idle/exclusive-session confirmation is required")
    base = (ROOT / "firmware/rt02cr-25hz.bin").read_bytes()
    candidate = (ROOT / "firmware/rt02cr-25hz-optical-off-v2-experimental.bin").read_bytes()
    symbols = (ROOT / "firmware/research/2026-09-22/rom_symbol_gcc.axf").read_bytes()
    from whip import fwrom_read as rr
    rr.validate_references(base, candidate, symbols)
    followup = getattr(args, "followup", False)
    resume = getattr(args, "resume_pointers", False)
    resume_code = getattr(args, "resume_code", False)
    stacks = getattr(args, "stacks", False)
    tcbs = getattr(args, "tcbs", False)
    watermarks = getattr(args, "watermarks", False)
    gatt = getattr(args, "gatt_resources", False)
    if followup + resume + resume_code + stacks + tcbs + watermarks + gatt > 1:
        raise ValueError("select exactly one fixed plan")
    pointer_archive = None
    if resume_code:
        pointer_archive = (ROOT / "firmware/research/2026-09-24/ram-ownership-resume-pointers/"
                           "resume-pointers.json").read_bytes()
    prior = None
    if followup:
        prior = (ROOT / "firmware/research/2026-09-24/ram-ownership/ram-ownership.json").read_bytes()
        if hashlib.sha256(prior).hexdigest() != mr.PRIOR_CAPTURE_SHA256:
            raise ValueError("unreviewed prior RAM capture")
    maximum = mr.FOLLOWUP_TRANSACTIONS if followup else mr.EXPECTED_TRANSACTIONS
    plan = "ram-ownership-followup-v1" if followup else "ram-ownership-v1"
    capture_name = "ram-ownership-followup.json" if followup else "ram-ownership.json"
    if resume:
        maximum, plan, capture_name = (mr.RESUME_TRANSACTIONS, "ram-ownership-resume-pointers-v1",
                                       "resume-pointers.json")
    if stacks:
        maximum, plan, capture_name = mr.STACKS_TRANSACTIONS, "ram-ownership-stacks-v1", "stacks.json"
    stacks_archive = None
    if tcbs:
        stacks_archive = (ROOT / "firmware/research/2026-09-24/ram-ownership-stacks/stacks.json").read_bytes()
        maximum, plan, capture_name = mr.TCB_TRANSACTIONS, "ram-ownership-tcbs-v1", "tcbs.json"
    if gatt:
        maximum, plan, capture_name = mr.GATT_TRANSACTIONS, "gatt-resources-v1", "gatt-resources.json"
    tcb_archive = stack_windows = None
    if watermarks:
        tcb_archive = (ROOT / "firmware/research/2026-09-24/ram-ownership-tcbs/tcbs.json").read_bytes()
        stack_windows = mr.stack_windows_from_tcbs(tcb_archive)
        maximum, plan, capture_name = (mr.watermark_transactions(stack_windows),
                                       "ram-ownership-stack-watermarks-v1", "stack-watermarks.json")
    if resume_code:
        maximum, plan, capture_name = (mr.RESUME_CODE_TRANSACTIONS, "ram-ownership-resume-code-v1",
                                       "resume-code.json")
    out = args.output.resolve()
    out.mkdir(exist_ok=False)
    from whip import capture  # BLE import only in this explicit hardware entry point
    with (out / "transcript.jsonl").open("x") as stream:
        requests = 0

        def emit(item):
            nonlocal requests
            if item["kind"] == "request":
                requests += 1
                if requests > maximum:
                    raise RuntimeError("fixed diagnostic transaction budget exceeded")
            stream.write(json.dumps(item) + "\n")
            stream.flush()

        emit({"kind": "header", "wall": time.time(), "plan": plan,
              "flashing": False, "sensor_commands": False, "target_execution": False,
              "pointer_following": False, "max_transactions": maximum,
              "gap_bytes_logged": False,
              "warning": "CD bookkeeping side effects; sampled identity is not full attestation"})
        reader = client = None
        try:
            async with asyncio.timeout(360):
                device = await capture.find_ring(address=args.address, timeout=60.0)  # infrequent adverts
                async with capture.connected(device) as client:
                    async with asyncio.timeout(300):
                        info = await capture.read_device_info(client, device)
                        emit({"kind": "device", **info.as_dict()})
                        if (info.address != args.address or info.hardware != "RT02CR_V3.1"
                                or info.firmware != "RT02CR_3.12.07_260514"
                                or not protocol.is_expected_ring(info.name)):
                            raise RuntimeError("unexpected device/firmware; no diagnostic command sent")
                        if watermarks:
                            reader = mr.RAMWatermarkReader(client, emit, stack_windows)
                        else:
                            reader_class = (mr.GATTResourcesReader if gatt else
                                            mr.RAMTCBReader if tcbs else
                                            mr.RAMStacksReader if stacks else
                                            mr.RAMResumeCodeReader if resume_code else
                                            mr.RAMResumeReader if resume else
                                            mr.RAMFollowupReader if followup else mr.RAMOwnershipReader)
                            reader = reader_class(client, emit)
                        await client.start_notify(protocol.UART_TX_CHAR_UUID, reader.notify)
                        try:
                            if gatt:
                                captured = await mr.collect_gatt(reader, base, candidate, symbols, out.name)
                            elif watermarks:
                                captured = await mr.collect_watermarks(reader, base, candidate, symbols,
                                                                       out.name, tcb_archive)
                            elif tcbs:
                                captured = await mr.collect_tcbs(reader, base, candidate, symbols,
                                                                 out.name, stacks_archive)
                            elif stacks:
                                captured = await mr.collect_stacks(reader, base, candidate, symbols, out.name)
                            elif resume_code:
                                captured = await mr.collect_resume_code(reader, base, candidate, symbols,
                                                                        out.name, pointer_archive)
                            elif resume:
                                captured = await mr.collect_resume_pointers(reader, base, candidate,
                                                                            symbols, out.name)
                            elif followup:
                                captured = await mr.collect_followup(reader, base, candidate, symbols,
                                                                     out.name, prior)
                            else:
                                captured = await mr.collect(reader, base, candidate, symbols, out.name)
                        finally:
                            reader.closed = True
                            await client.stop_notify(protocol.UART_TX_CHAR_UUID)
                if client.is_connected:
                    raise RuntimeError("disconnect not confirmed; no successful capture declared")
            emit({"kind": "disconnected", "confirmed": True})
            if reader.poisoned or requests != maximum:
                raise RuntimeError("ambiguous traffic or transaction count; no successful capture")
            with (out / capture_name).open("x") as target:
                json.dump(captured, target, indent=2)
                target.write("\n")
            emit({"kind": "completed", "requests": requests, "flash_authorized": False,
                  "capture_sha256": hashlib.sha256((out / capture_name).read_bytes()).hexdigest()})
            print(f"Saved RAM-ownership read: {out}. Disconnected; no flash or sensor command.")
            return 0
        except BaseException as exc:
            if reader is not None:
                reader.closed = True
            disconnected = None
            if client is not None:
                try:
                    disconnected = not client.is_connected
                except Exception:
                    pass
            emit({"kind": "aborted", "error": str(exc), "retry": False,
                  "disconnect_confirmed": disconnected})
            raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--address", required=True, help="specific BLE device identifier, never a memory address")
    p.add_argument("--output", required=True, type=Path, help="new evidence directory; never overwritten")
    p.add_argument("--followup", action="store_true",
                   help="separate fixed plan: ROM vectors 0x0..0x40 (not followed), heap counters, gap vs prior capture")
    p.add_argument("--resume-pointers", action="store_true",
                   help="separate fixed plan: ROM-data boot/resume function pointers 0x2000f0 (16 B), 0x20014c (4 B); not followed")
    p.add_argument("--resume-code", action="store_true",
                   help="separate fixed plan: recheck 0x2000f8 == 0xd22d, then ROM 0xd200..0xd400 twice; no execution")
    p.add_argument("--stacks", action="store_true",
                   help="separate fixed plan: MSP paint watermark (hash-only), pxCurrentTCB, pTaskHandleList; not followed")
    p.add_argument("--tcbs", action="store_true",
                   help="separate fixed plan: task-handle table and six TCB headers chosen offline from the stacks archive")
    p.add_argument("--watermarks", action="store_true",
                   help="separate fixed plan: hash-only stack-bottom paint watermarks at offline-derived windows")
    p.add_argument("--gatt-resources", action="store_true",
                   help="separate fixed plan: Upper Stack header/code samples vs SDK mirror, upper OTP config, server/pool state words")
    p.add_argument("--confirmed-idle-clients", action="store_true",
                   help="fresh confirmation: all other clients closed, no stream or DFU")
    args = p.parse_args()
    if not args.confirmed_idle_clients:
        p.error("fresh idle/exclusive-session confirmation is required")
    try:
        return asyncio.run(run(args))
    except (RuntimeError, ValueError, TimeoutError) as exc:
        print(f"Diagnostic aborted without retry: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
