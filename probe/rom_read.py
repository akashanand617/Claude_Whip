"""Idle-only, fixed code diagnostics. No firmware/sensor operations.

Fresh coordination required. CD01 has connection/timer bookkeeping side effects.
No arbitrary addresses, target execution, retries, reconnect or pointer following.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import time

from whip import fwrom_read as rr, fwboot_read as br, fwrom_integration as ir, fwrom_resume as tr, protocol
from whip import fwrom_support as sr
from whip import fwrom_hook as hr

ROOT = Path(__file__).resolve().parents[1]


async def run(args):
    if not getattr(args, "confirmed_idle_clients", False):
        raise ValueError("fresh idle/exclusive-session confirmation is required")
    if sum(bool(getattr(args, flag, False)) for flag in
           ("boot_reference", "timer_hook_state", "timer_internals", "integration_code", "timer_resume_code", "support_code", "timer_create_hook")) > 1:
        raise ValueError("select exactly one fixed diagnostic plan")
    base = (ROOT / "firmware/rt02cr-25hz.bin").read_bytes()
    candidate = (ROOT / "firmware/rt02cr-25hz-optical-off-v2-experimental.bin").read_bytes()
    symbols = (ROOT / "firmware/research/2026-09-22/rom_symbol_gcc.axf").read_bytes()
    rr.validate_references(base, candidate, symbols)
    integration = getattr(args, "integration_code", False)
    if integration: ir.validate_symbols(symbols)
    timer_resume = getattr(args, "timer_resume_code", False)
    if timer_resume: tr.validate_symbols(symbols)
    support = getattr(args, "support_code", False)
    if support: tr.validate_symbols(symbols)
    create_hook = getattr(args, "timer_create_hook", False)
    if create_hook: tr.validate_symbols(symbols)
    boot = getattr(args, "boot_reference", False)
    boot_reference = None
    if boot:
        boot_reference = (ROOT / "firmware/research/2026-09-23/reference-boot/rtl8762e-sdk-boot.json").read_bytes()
        br.validate_reference(boot_reference)
    hooks = getattr(args, "timer_hook_state", False)
    internals = getattr(args, "timer_internals", False) or hooks
    prior = None
    if internals or timer_resume or support or create_hook:
        prior = (ROOT / "firmware/research/2026-09-23/rom-timers/rom-timers.json").read_bytes()
        rr.validate_prior_capture(prior)
    prior_resume = prior_integration = None
    if support or create_hook:
        prior_resume = (ROOT / "firmware/research/2026-09-23/rom-timer-resume/rom-timer-resume-code.json").read_bytes()
        prior_integration = (ROOT / "firmware/research/2026-09-23/rom-integration/rom-integration.json").read_bytes()
        sr.validate_archives(prior, prior_resume, prior_integration)
    prior_support = None
    if create_hook:
        prior_support = (ROOT / "firmware/research/2026-09-23/rom-support/rom-support.json").read_bytes()
        hr.validate_archives(prior, prior_resume, prior_integration, prior_support)
    prior_internals = None
    if hooks:
        prior_internals = (ROOT / "firmware/research/2026-09-23/rom-timer-internals/rom-timer-internals.json").read_bytes()
        rr.validate_internal_capture(prior_internals)
    maximum = rr.INTERNAL_TRANSACTIONS if internals else rr.EXPECTED_TRANSACTIONS
    plan = "rom-timer-internals-v1" if internals else "rom-timers-v1"
    capture_name = "rom-timer-internals.json" if internals else "rom-timers.json"
    if hooks:
        maximum, plan, capture_name = rr.HOOK_TRANSACTIONS, "rom-timer-hooks-v1", "rom-timer-hooks.json"
    if boot:
        maximum, plan, capture_name = br.EXPECTED_TRANSACTIONS, "boot-reference-v1", "boot-reference.json"
    if integration:
        maximum, plan, capture_name = ir.EXPECTED_TRANSACTIONS, "rom-integration-v1", "rom-integration.json"
    if timer_resume:
        maximum, plan, capture_name = tr.EXPECTED_TRANSACTIONS, "rom-timer-resume-code-v1", "rom-timer-resume-code.json"
    if support:
        maximum, plan, capture_name = sr.EXPECTED_TRANSACTIONS, "rom-support-v1", "rom-support.json"
    if create_hook:
        maximum, plan, capture_name = hr.EXPECTED_TRANSACTIONS, "rom-create-hook-v1", "rom-create-hook.json"
    out = args.output.resolve()
    out.mkdir(exist_ok=False)
    # BLE import is confined to this explicitly selected hardware entry point.
    from whip import capture
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
              "warning": "CD bookkeeping side effects; sampled identity is not full attestation"})
        reader = client = None
        try:
            # Includes discovery/connect/DIS/cleanup. The collection has a
            # separate deadline; a timeout is terminal, never a retry trigger.
            async with asyncio.timeout(240 if integration else 180):
                device = await capture.find_ring(address=args.address)
                async with capture.connected(device) as client:
                    async with asyncio.timeout(180 if integration else 120):
                        info = await capture.read_device_info(client, device)
                        emit({"kind": "device", **info.as_dict()})
                        if (info.address != args.address or info.hardware != "RT02CR_V3.1"
                                or info.firmware != "RT02CR_3.12.07_260514"
                                or not protocol.is_expected_ring(info.name)):
                            raise RuntimeError("unexpected device/firmware; no diagnostic command sent")
                        reader_class = rr.ROMInternalsReader if internals else rr.ROMTimerReader
                        if hooks: reader_class = rr.ROMHookReader
                        if boot: reader_class = br.BootReferenceReader
                        if integration: reader_class = ir.IntegrationReader
                        if timer_resume: reader_class = tr.ResumeCodeReader
                        if support: reader_class = sr.SupportReader
                        if create_hook: reader_class = hr.CreateHookReader
                        reader = reader_class(client, emit)
                        await client.start_notify(protocol.UART_TX_CHAR_UUID, reader.notify)
                        try:
                            if create_hook:
                                captured = await hr.collect(reader, base, candidate, symbols, out.name,
                                                            prior, prior_resume, prior_integration, prior_support)
                            elif support:
                                captured = await sr.collect(reader, base, candidate, symbols, out.name,
                                                            prior, prior_resume, prior_integration)
                            elif timer_resume:
                                captured = await tr.collect(reader, base, candidate, symbols, out.name, prior)
                            elif integration:
                                captured = await ir.collect(reader, base, candidate, symbols, out.name)
                            elif boot:
                                captured = await br.collect_boot_reference(
                                    reader, base, candidate, symbols, out.name, boot_reference)
                            elif hooks:
                                captured = await rr.collect_rom_hooks(
                                    reader, base, candidate, symbols, out.name, prior, prior_internals)
                            elif internals:
                                captured = await rr.collect_rom_internals(
                                    reader, base, candidate, symbols, out.name, prior)
                            else:
                                captured = await rr.collect_rom_timers(reader, base, candidate, symbols, out.name)
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
            emit({"kind": "completed", "requests": requests,
                  "rom_bytes": (hr.TOTAL_ROM_BYTES if create_hook else
                                sr.TOTAL_ROM_BYTES + sr.TOTAL_KNOWN_BYTES if support else
                                tr.TOTAL_NEW_BYTES + rr.TIMER_WINDOW[1] if timer_resume else
                                ir.TOTAL_BYTES if integration else (0 if boot else rr.TIMER_WINDOW[1])),
                  "flash_authorized": False,
                  "boot_code_bytes": 528 if boot else 0,
                  "nonsecret_boot_header_bytes": 52 if boot else 0,
                  "additional_rom_bytes": 180 if internals else 0,
                  "hook_slot_bytes": 8 if hooks else 0,
                  **({"new_rom_bytes": sr.TOTAL_ROM_BYTES,
                      "timer_state_snapshot_bytes": sr.TOTAL_STATE_BYTES} if support else {}),
                  **({"new_rom_bytes": 128, "new_ram_code_bytes": 256,
                      "nonsecret_patch_header_bytes": 52} if create_hook else {}),
                  "capture_sha256": hashlib.sha256((out / capture_name).read_bytes()).hexdigest()})
            print(f"Saved fixed code read: {out}. Disconnected; no flash or sensor command.")
            return 0
        except BaseException as exc:
            if reader is not None:
                reader.closed = True
            # The context manager has already attempted teardown. Record the
            # backend's state even on failure; never reconnect to investigate.
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
    selected = p.add_mutually_exclusive_group()
    selected.add_argument("--timer-internals", action="store_true",
                   help="separate fixed plan: repeat known wrappers, read two literals and bounded default code")
    selected.add_argument("--timer-hook-state", action="store_true",
                   help="repeat prior ROM captures, read only the fixed eight-byte timer-hook slot window")
    selected.add_argument("--boot-reference", action="store_true",
                   help="read a fixed 52-byte non-secret boot prefix, then 528 code bytes only if prefix matches")
    selected.add_argument("--integration-code", action="store_true",
                   help="fixed ROM code for RAM/boot, timer queue/barriers and OTA header validation; no pointer following")
    selected.add_argument("--timer-resume-code", action="store_true",
                   help="read fixed create/start/restart ROM code and literals; does NOT run any timer operation")
    selected.add_argument("--support-code", action="store_true",
                   help="fixed ROM support code/literals and 17 non-secret timer-state bytes; no pointer following or execution")
    selected.add_argument("--timer-create-hook", action="store_true",
                   help="fixed non-secret patch prefix and bounded create-hook/comparator code; no pointer following or execution")
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
