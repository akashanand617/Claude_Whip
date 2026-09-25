"""Prepared one-use122-read gateway diagnostic. Fresh coordination REQUIRED.

Only32 fixed ROM bytes and one fixed4-byte slot beyond existing prerequisites.
No returned-pointer following, target execution, retry, reconnect, sensors or
firmware operation. CD01 still touches connection/timer bookkeeping.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import time

from whip import fwstack_gateway as gr, fwrom_read as rr, protocol

ROOT = Path(__file__).resolve().parents[1]


async def run(args):
    if getattr(args, 'confirmed_idle_clients', False) is not True:
        raise ValueError('fresh idle/exclusive-session confirmation is required')
    base = (ROOT / 'firmware/rt02cr-25hz.bin').read_bytes()
    candidate = (ROOT / 'firmware/rt02cr-25hz-optical-off-v2-experimental.bin').read_bytes()
    symbols = (ROOT / 'firmware/research/2026-09-22/rom_symbol_gcc.axf').read_bytes()
    prior = (ROOT / 'firmware/research/2026-09-23/rom-timers/rom-timers.json').read_bytes()
    rr.validate_references(base, candidate, symbols)
    gr.validate_symbols(symbols)
    gr.validate_callers(base, candidate)
    rr.validate_prior_capture(prior)
    out = args.output.resolve()
    out.mkdir(exist_ok=False)
    # Import/access hardware only after explicit fresh confirmation and all
    # local reference checks. Tests replace this module with fake transport.
    from whip import capture
    with (out / 'transcript.jsonl').open('x') as stream:
        requests = 0

        def emit(item):
            nonlocal requests
            if item['kind'] == 'request':
                requests += 1
                if requests > gr.EXPECTED_TRANSACTIONS:
                    raise RuntimeError('fixed gateway transaction budget exceeded')
            stream.write(json.dumps(item) + '\n')
            stream.flush()

        emit({'kind': 'header', 'wall': time.time(), 'plan': 'stack-gateway-v1',
              'max_transactions': gr.EXPECTED_TRANSACTIONS, 'flashing': False,
              'sensor_commands': False, 'target_execution': False, 'pointer_following': False,
              'warning': 'CD bookkeeping side effects; sampled identity is not full attestation'})
        reader = client = None
        notify_attempted = False
        disconnect_completed = False
        try:
            try:
                async with asyncio.timeout(180):
                    device = await capture.find_ring(address=args.address)
                    # Own the client BEFORE awaiting connect. The shared
                    # connected() helper only enters its cleanup after connect
                    # succeeds; a partial/cancelled setup also needs cleanup.
                    client = capture.BleakClient(device, timeout=capture.CONNECT_TIMEOUT_S)
                    await client.connect()
                    async with asyncio.timeout(120):
                        info = await capture.read_device_info(client, device)
                        emit({'kind': 'device', **info.as_dict()})
                        if (info.address != args.address or info.hardware != 'RT02CR_V3.1'
                                or info.firmware != 'RT02CR_3.12.07_260514'
                                or not protocol.is_expected_ring(info.name)):
                            raise RuntimeError('unexpected device/firmware; no diagnostic command sent')
                        reader = gr.StackGatewayReader(client, emit)
                        notify_attempted = True
                        await client.start_notify(protocol.UART_TX_CHAR_UUID, reader.notify)
                        result = await gr.collect(reader, base, candidate, symbols, out.name, prior)
            finally:
                if reader is not None:
                    reader.closed = True
                if client is not None:
                    # Cleanup has its own small budget, even after the main
                    # operation times out/cancels. Always attempt disconnect,
                    # including failed connect or failed notification setup.
                    try:
                        if notify_attempted:
                            async with asyncio.timeout(3):
                                await client.stop_notify(protocol.UART_TX_CHAR_UUID)
                    finally:
                        async with asyncio.timeout(10):
                            await client.disconnect()
                        disconnect_completed = True
            if client.is_connected:
                raise RuntimeError('disconnect not confirmed; no successful capture declared')
            emit({'kind': 'disconnected', 'confirmed': True})
            if reader.poisoned or requests != gr.EXPECTED_TRANSACTIONS:
                raise RuntimeError('ambiguous traffic or transaction count; no successful capture')
            target = out / 'stack-gateway.json'
            with target.open('x') as saved:
                json.dump(result, saved, indent=2)
                saved.write('\n')
            emit({'kind': 'completed', 'requests': requests, 'new_rom_cap_bytes': 32,
                  'entry_slot_bytes': 4, 'known_rom_bytes': 72, 'flash_authorized': False,
                  'capture_sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
            print(f'Saved bounded stack-gateway diagnostic: {out}. Disconnected; no flash or sensor command.')
            return 0
        except BaseException as exc:
            if reader is not None: reader.closed = True
            disconnected = None
            if client is not None:
                try: disconnected = disconnect_completed and not client.is_connected
                except Exception: pass
            emit({'kind': 'aborted', 'error': str(exc), 'retry': False,
                  'error_type': type(exc).__name__,
                  'disconnect_completed': disconnect_completed,
                  'disconnect_confirmed': disconnected})
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--address', required=True, help='specific BLE identifier, never a memory address')
    parser.add_argument('--output', type=Path, required=True, help='new evidence directory; never overwrite')
    parser.add_argument('--confirmed-idle-clients', action='store_true',
                        help='fresh confirmation: all other clients closed, no stream or DFU')
    args = parser.parse_args()
    if not args.confirmed_idle_clients:
        parser.error('fresh idle/exclusive-session confirmation is required')
    try:
        return asyncio.run(run(args))
    except (RuntimeError, ValueError, TimeoutError) as exc:
        print(f'Gateway diagnostic aborted without retry: {exc}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
