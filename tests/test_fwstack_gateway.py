"""Fixed gateway preflight using fake transport and selected CD instructions.

No test discovers/connects a ring. New code/slot contents are invented DATA;
copying them proves neither physical accessibility nor callback ordering.
"""
import asyncio
import hashlib
import json
import struct
import sys

import pytest

from probe import stack_gateway_read
from tests import test_fwrom_read as rt
from tests.test_fwrom_read import BASE, V2, SYMBOLS, PRIOR, ROMFake, arguments, transport as base_transport
from whip import fwcapacity, fwcapacity_read as cr, fwrom_read as rr, fwstack_gateway as gr
from whip.fwplacement import _bl_destination


@pytest.fixture
def transport(base_transport, monkeypatch):
    """Keep the established fake protocol, but explicitly own client lifetime."""
    f = base_transport
    f.client_constructions = f.connect_calls = f.disconnect_calls = 0
    fake_capture = sys.modules['whip.capture']
    fake_capture.CONNECT_TIMEOUT_S = 90.0

    def client(device, *, timeout):
        assert device.name == f.info['name'] and timeout == 90.0
        f.client_constructions += 1
        return f

    async def connect():
        f.connect_calls += 1
        f.connected = f.is_connected = True

    async def disconnect():
        f.disconnect_calls += 1
        f.disconnected = True
        f.is_connected = f.fail_disconnect

    def forbidden_context(*args, **kwargs):
        raise AssertionError('gateway must own cleanup before connect can fail')

    f.connect, f.disconnect = connect, disconnect
    monkeypatch.setattr(fake_capture, 'BleakClient', client, raising=False)
    monkeypatch.setattr(fake_capture, 'connected', forbidden_context)
    return f


def install(f, pointer=0x40015001):
    f.config[rr.TIMER_WINDOW[0]] = rr.validate_prior_capture(PRIOR)
    f.config[gr.GATEWAY_WINDOW[0]] = bytes((i * 17 + 3) & 255 for i in range(32))
    f.config[gr.ENTRY_SLOT_WINDOW[0]] = struct.pack('<I', pointer)


class GatewayFake(ROMFake):
    def __init__(self):
        super().__init__()
        self.reader = gr.StackGatewayReader(self, self.events.append, timeout=0.01, spacing=0)
        self.new_reads = 0
        self.gateway_change = self.gateway_fault = None
        self.injected = False
        install(self)

    def memory(self, address, length):
        raw = super().memory(address, length)
        if any(a <= address < a + n for _, a, n in gr.WINDOWS):
            self.new_reads += 1
        if self.gateway_change is not None:
            target, occurrence = self.gateway_change
            if address == target and sum(a == address for a, _ in self.writes) == occurrence:
                self.injected = True
                return bytes([raw[0] ^ 1]) + raw[1:]
        return raw

    async def write_gatt_char(self, uuid, packet, response):
        if self.gateway_fault and self.reader._gateway_phase == self.gateway_fault[0]:
            self.bad = self.gateway_fault[1]
            self.injected = True
        await super().write_gatt_char(uuid, packet, response)


def collect(f, *, base=BASE, candidate=V2, symbols=SYMBOLS, prior_stop=PRIOR):
    return asyncio.run(gr.collect(f.reader, base, candidate, symbols, 'fake-gateway-only', prior_stop))


def assert_closed(f, *, poisoned):
    assert f.reader.closed and f.reader.poisoned is poisoned
    assert f.reader._gateway_phase is None and not f.reader._descriptor_phase
    assert not f.reader._allowed_reads() and f.reader.pending is None


@pytest.mark.parametrize('image', [BASE, V2], ids=['original25hz', 'v2'])
def test_local_installed_lineage_wrapper_and_slot_store_are_exact_witnesses(image):
    gr.validate_callers(BASE, V2)
    assert image[0x15518:0x15526] == bytes.fromhex('014610b5ff200830c9f729da10bd')
    assert _bl_destination(image, 0x15520) + fwcapacity.BIAS == 0x4926
    # This is the installed-lineage wrapper, NOT stock3.12.02 file0x156bc.
    assert image[0x6D4:0x6DA] == bytes.fromhex('4b4900220860')
    instruction, = struct.unpack_from('<H', image, 0x6D4)
    assert instruction & 0xF800 == 0x4800 and (instruction >> 8) & 7 == 1
    literal = ((0x6D4 + 4) & ~3) + (instruction & 255) * 4
    assert literal == 0x804
    assert struct.unpack_from('<I', image, literal)[0] == 0x2011D4
    # str r0,[r1] establishes the slot address, not the meaning of its stored value.
    assert image[0x6D8:0x6DA] == bytes.fromhex('0860')


@pytest.mark.parametrize('which', ['base', 'candidate'])
@pytest.mark.parametrize('offset', [0x15518, 0x15520, 0x6D4, 0x6D8, 0x804])
def test_each_local_caller_witness_rejects_direct_mutation(which, offset):
    pair = {'base': BASE, 'candidate': V2}
    image = pair[which]
    pair[which] = image[:offset] + bytes([image[offset] ^ 1]) + image[offset + 1:]
    with pytest.raises(ValueError, match='local caller witness'):
        gr.validate_callers(pair['base'], pair['candidate'])


def test_exact_122_request_order_repeats_and_one_use_closure():
    assert gr.SCHEMA == 'whip.stack-gateway.capture.v1'
    assert gr.GATEWAY_WINDOW == (0x4926, 32)
    assert gr.ENTRY_SLOT_WINDOW == (0x2011D4, 4)
    assert gr.WINDOWS == (('gateway_entry_cap', 0x4926, 32),
                          ('upperstack_entry_slot', 0x2011D4, 4))
    # Independently execute only the established descriptor prefix on a fake.
    prefix = ROMFake()
    asyncio.run(cr.collect_bank0_descriptor(prefix.reader, BASE, V2, 'fake-prefix'))
    assert len(prefix.writes) == 91
    tail = (list(cr.chunks(*rr.UUID_WINDOW)) * 2
            + list(cr.chunks(*rr.TIMER_WINDOW)) * 2
            + [chunk for _, a, n in gr.WINDOWS for chunk in cr.chunks(a, n) * 2]
            + [chunk for window in cr.CONFIG_WINDOWS for chunk in cr.chunks(*window)]
            + [cr.IDLE_WINDOW])
    f = GatewayFake()
    result = collect(f)
    assert f.writes == prefix.writes + tail
    assert len(f.writes) == gr.EXPECTED_TRANSACTIONS == 122
    assert (f.uuid_reads, f.timer_reads, f.new_reads) == (4, 12, 8)
    assert result['schema'] == gr.SCHEMA
    assert result['known_code_repeated_equal'] and result['repeated_equal']
    assert set(result['windows']) == {name for name, _, _ in gr.WINDOWS}
    for name, a, n in gr.WINDOWS:
        window = result['windows'][name]
        assert window == {'address': a, 'data_hex': f.config[a].hex(),
                          'sha256': hashlib.sha256(f.config[a]).hexdigest()}
        assert len(bytes.fromhex(window['data_hex'])) == n
    assert not any(result[k] for k in ('pointer_following', 'target_execution', 'keys_read',
        'entry_pointer_semantics_verified', 'callback_drain_verified', 'complete_dispatch_verified',
        'full_image_attestation', 'recovery_verified', 'flash_authorized'))
    assert_closed(f, poisoned=False)
    for request in (cr.IDLE_WINDOW, *cr.chunks(*gr.GATEWAY_WINDOW), gr.ENTRY_SLOT_WINDOW):
        with pytest.raises(ValueError): asyncio.run(f.reader.read(*request))
    with pytest.raises(RuntimeError, match='already used'): collect(f)
    assert len(f.writes) == 122


@pytest.mark.parametrize('pointer', [0, 1, 0xFFFFFFFF, 0x40015000, 0x40015001,
                                    0x200414, 0x80D034, 0x80E001])
def test_slot_value_is_archived_verbatim_and_never_used_as_an_address(pointer):
    f = GatewayFake()
    install(f, pointer)
    result = collect(f)
    assert bytes.fromhex(result['windows']['upperstack_entry_slot']['data_hex']) == struct.pack('<I', pointer)
    assert not any(a in (pointer, pointer & ~1) for a, _ in f.writes)
    assert len(f.writes) == 122 and not result['entry_pointer_semantics_verified']


def test_each_phase_excludes_other_new_windows_and_all_unreviewed_neighbors():
    f = GatewayFake()
    phases = {'identifier': rr.UUID_WINDOW, 'known_stop': rr.TIMER_WINDOW,
              **{name: (a, n) for name, a, n in gr.WINDOWS}}
    forbidden = [(0x4924, 2), (0x4946, 2), (0x4927, 14), (0x4926, 15),
                 (0x4934, 13), (0x2011D0, 4), (0x2011D8, 4), (0x2011D4, 8),
                 (0x2011D4, 1), (0x2011D5, 3), (0x136BA, 2), (0x13704, 2),
                 (0x200414, 4), (0x80D034, 14), (0x40015000, 1),
                 (0x84A198, 14), (0x1000198, 14), (True, 1), (0x4926, True)]
    for phase in (None, 'unknown', *phases):
        f.reader._gateway_phase = phase  # Deliberate phase injection, not plan entry.
        for name, window in phases.items():
            for request in cr.chunks(*window):
                assert (request in f.reader._allowed_reads()) is (phase == name)
                if phase != name:
                    with pytest.raises(ValueError): asyncio.run(f.reader.read(*request))
        for request in forbidden:
            with pytest.raises(ValueError): asyncio.run(f.reader.read(*request))
    assert not f.writes
    f.reader.closed = True
    for phase in phases:
        f.reader._gateway_phase = phase
        assert not f.reader._allowed_reads()


@pytest.mark.parametrize('line', [b'SystemCall_Stack = 0x00004927 ;',
    b'update_ram_layout = 0x00004a79 ;', b'app_pre_main = 0x002011d0 ;',
    b'upperstack_entry = 0x002011d4 ;', b'app_main = 0x002011d8 ;'])
def test_symbol_boundaries_are_checked_in_addition_to_the_map_hash(monkeypatch, line):
    assert line in SYMBOLS.splitlines()
    altered = SYMBOLS.replace(line, line.replace(b' = ', b' = 0 + '), 1)
    # Bypass only the hash gate in this negative test to exercise exact names/bounds.
    monkeypatch.setattr(rr, 'SYMBOLS_SHA256', hashlib.sha256(altered).hexdigest())
    f = GatewayFake()
    with pytest.raises(ValueError, match='symbol boundary'): collect(f, symbols=altered)
    assert not f.writes
    assert_closed(f, poisoned=True)


@pytest.mark.parametrize('bad', ['base', 'candidate', 'symbols', 'prior_stop'])
def test_invalid_local_references_refused_without_transport(bad):
    f = GatewayFake()
    value = dict(base=BASE, candidate=V2, symbols=SYMBOLS, prior_stop=PRIOR)[bad]
    with pytest.raises(ValueError): collect(f, **{bad: value + b'\n'})
    assert not f.writes
    assert_closed(f, poisoned=True)


def test_wrong_reader_refused_without_widening_its_plan():
    f = ROMFake()
    with pytest.raises(ValueError): collect(f)
    assert not f.writes
    for _, a, n in gr.WINDOWS:
        for chunk in cr.chunks(a, n):
            with pytest.raises(ValueError): asyncio.run(f.reader.read(*chunk))


@pytest.mark.parametrize('bad', ['base_identity', 'identity', 'diagnostic', 'idle',
                                'ram', 'flash', 'descriptor', 'uuid'])
def test_live_prerequisite_failure_prevents_every_new_window(bad):
    f = GatewayFake()
    if bad == 'base_identity': f.image = BASE
    if bad in ('identity', 'diagnostic'):
        pos = 0x21D6 if bad == 'identity' else 0x564A
        f.image = V2[:pos] + bytes([V2[pos] ^ 1]) + V2[pos + 1:]
    if bad == 'idle': f.raw = 4
    if bad in ('ram', 'flash', 'descriptor', 'uuid'):
        a = {'ram': cr.CONFIG_WINDOWS[0][0], 'flash': cr.CONFIG_WINDOWS[1][0],
             'descriptor': cr.BANK0_DESCRIPTOR_WINDOW[0], 'uuid': rr.UUID_WINDOW[0]}[bad]
        f.config[a] = bytes([f.config[a][0] ^ 1]) + f.config[a][1:]
    with pytest.raises((RuntimeError, ValueError)): collect(f)
    assert not f.new_reads and not f.timer_reads
    assert_closed(f, poisoned=True)


@pytest.mark.parametrize('address,length', cr.chunks(*rr.TIMER_WINDOW))
@pytest.mark.parametrize('occurrence', [1, 2])
def test_every_known_stop_chunk_must_match_on_both_reads_before_new_access(address, length, occurrence):
    f = GatewayFake()
    f.gateway_change = address, occurrence
    with pytest.raises(RuntimeError, match='known ROM code differs'): collect(f)
    assert f.injected and not f.new_reads
    assert_closed(f, poisoned=True)


@pytest.mark.parametrize('address,length', cr.chunks(*rr.UUID_WINDOW))
def test_second_identifier_read_mismatch_prevents_even_known_stop(address, length):
    f = GatewayFake()
    f.gateway_change = address, 2
    with pytest.raises(RuntimeError, match='identifier differs'): collect(f)
    assert f.injected and not f.timer_reads and not f.new_reads
    assert_closed(f, poisoned=True)


@pytest.mark.parametrize('address,length', [c for _, a, n in gr.WINDOWS for c in cr.chunks(a, n)])
def test_each_new_chunk_repeat_mismatch_cannot_produce_capture(address, length):
    f = GatewayFake()
    f.gateway_change = address, 2
    with pytest.raises(RuntimeError, match='changed across repeats'): collect(f)
    assert f.injected and f.new_reads
    assert_closed(f, poisoned=True)
    if address < 0x10000:
        assert not any(a == gr.ENTRY_SLOT_WINDOW[0] for a, _ in f.writes)


@pytest.mark.parametrize('phase,count', [('gateway_entry_cap', 108), ('upperstack_entry_slot', 114)])
@pytest.mark.parametrize('fault', ['timeout', 'write_timeout', 'checksum', 'short', 'stream', 'duplicate'])
def test_new_phase_transport_fault_is_terminal_without_retry(phase, count, fault):
    f = GatewayFake()
    f.gateway_fault = phase, fault
    with pytest.raises((RuntimeError, TimeoutError)): collect(f)
    assert f.injected and len(f.writes) == count
    assert_closed(f, poisoned=True)
    with pytest.raises(RuntimeError): collect(f)
    assert len(f.writes) == count


@pytest.mark.parametrize('address', [cr.CONFIG_WINDOWS[0][0], cr.CONFIG_WINDOWS[1][0], cr.IDLE_WINDOW[0]])
def test_final_postcondition_change_is_terminal(address):
    f = GatewayFake()
    f.gateway_change = address, 4
    with pytest.raises(RuntimeError): collect(f)
    assert f.injected and f.new_reads == 8
    assert_closed(f, poisoned=True)


def test_cancelling_a_stalled_new_write_closes_pending_request_and_all_phases():
    f = GatewayFake()
    f.reader.timeout = 60  # Cancellation, not a real minute-long wait.
    f.gateway_fault = 'gateway_entry_cap', 'write_timeout'

    async def scenario():
        entered, cancelled = asyncio.Event(), asyncio.Event()
        original = f.write_gatt_char

        async def write(*args, **kwargs):
            if f.reader._gateway_phase == 'gateway_entry_cap': entered.set()
            try:
                await original(*args, **kwargs)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        f.write_gatt_char = write
        task = asyncio.create_task(gr.collect(f.reader, BASE, V2, SYMBOLS, 'fake-cancel', PRIOR))
        try:
            await asyncio.wait_for(entered.wait(), 3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
            assert cancelled.is_set()
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())
    assert len(f.writes) == 108
    assert_closed(f, poisoned=True)


def test_cli_success_requires_exact_budget_both_deadlines_and_verified_disconnect(transport, tmp_path, monkeypatch):
    install(transport)
    args = arguments(tmp_path)
    deadlines = []
    original = asyncio.timeout

    def timeout(seconds):
        deadlines.append(seconds)
        return original(seconds)

    monkeypatch.setattr(stack_gateway_read.asyncio, 'timeout', timeout)
    assert asyncio.run(stack_gateway_read.run(args)) == 0
    assert deadlines[:2] == [180, 120]
    assert deadlines[-2:] == [3, 10]
    assert (transport.client_constructions, transport.connect_calls, transport.disconnect_calls) == (1, 1, 1)
    assert transport.disconnected and transport.stopped_notify and not transport.is_connected
    assert len(transport.writes) == 122
    rows = [json.loads(line) for line in (args.output / 'transcript.jsonl').read_text().splitlines()]
    assert rows[0]['plan'] == 'stack-gateway-v1' and rows[0]['max_transactions'] == 122
    assert rows[-2] == {'kind': 'disconnected', 'confirmed': True}
    assert rows[-1]['kind'] == 'completed' and rows[-1]['requests'] == 122
    assert (rows[-1]['new_rom_cap_bytes'], rows[-1]['entry_slot_bytes'], rows[-1]['known_rom_bytes']) == (32, 4, 72)
    assert not rows[-1]['flash_authorized']
    target = args.output / 'stack-gateway.json'
    assert rows[-1]['capture_sha256'] == hashlib.sha256(target.read_bytes()).hexdigest()
    assert json.loads(target.read_text())['schema'] == gr.SCHEMA


@pytest.mark.parametrize('confirmation', [False, None, 0, 1, 'yes'])
def test_cli_requires_literal_fresh_confirmation_before_references_or_connection(transport, tmp_path, monkeypatch, confirmation):
    args = arguments(tmp_path)
    args.confirmed_idle_clients = confirmation

    def forbidden(*args):
        raise AssertionError('local references reached before confirmation')

    monkeypatch.setattr(rr, 'validate_references', forbidden)
    with pytest.raises(ValueError, match='confirmation'): asyncio.run(stack_gateway_read.run(args))
    assert not transport.connected and not args.output.exists()


def test_cli_local_caller_validation_failure_precedes_output_and_connection(transport, tmp_path, monkeypatch):
    args = arguments(tmp_path)

    def invalid(*unused):
        raise ValueError('local caller witness mismatch')

    monkeypatch.setattr(gr, 'validate_callers', invalid)
    with pytest.raises(ValueError, match='local caller witness'):
        asyncio.run(stack_gateway_read.run(args))
    assert not transport.connected and not args.output.exists()


def assert_aborted_without_capture(args, expected_type, disconnect_completed, confirmed):
    assert not (args.output / 'stack-gateway.json').exists()
    rows = [json.loads(line) for line in (args.output / 'transcript.jsonl').read_text().splitlines()]
    assert not any(row['kind'] in ('completed', 'disconnected') for row in rows)
    assert rows[-1]['kind'] == 'aborted' and rows[-1]['retry'] is False
    assert rows[-1]['error_type'] == expected_type.__name__
    assert rows[-1]['disconnect_completed'] is disconnect_completed
    assert rows[-1]['disconnect_confirmed'] is confirmed
    return rows


@pytest.mark.parametrize('setup', ['exception', 'timeout', 'cancel'])
@pytest.mark.parametrize('cleanup', ['ok', 'exception', 'stall', 'still_connected'])
@pytest.mark.parametrize('partially_connected', [False, True])
def test_setup_failure_always_attempts_bounded_disconnect_before_any_cd(
        transport, tmp_path, monkeypatch, setup, cleanup, partially_connected):
    args = arguments(tmp_path)
    deadlines = []
    original_timeout = asyncio.timeout

    def timeout(seconds):
        deadlines.append(seconds)
        # Exercise the actual operation/cleanup timeout cancellation paths,
        # without spending 180 or 10 wall-clock seconds in a fake transport.
        shortened = seconds == 10 or (seconds == 180 and setup == 'timeout')
        return original_timeout(0.01 if shortened else seconds)

    monkeypatch.setattr(stack_gateway_read.asyncio, 'timeout', timeout)

    async def scenario():
        entered, connect_cancelled, cleanup_cancelled = (asyncio.Event() for _ in range(3))

        async def connect():
            transport.connect_calls += 1
            transport.connected = True
            transport.is_connected = partially_connected
            entered.set()
            if setup == 'exception': raise RuntimeError('fake setup failed')
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                connect_cancelled.set()
                raise

        async def disconnect():
            transport.disconnect_calls += 1
            transport.disconnected = True
            if cleanup == 'exception': raise RuntimeError('fake cleanup failed')
            if cleanup == 'stall':
                try:
                    await asyncio.Future()
                except asyncio.CancelledError:
                    cleanup_cancelled.set()
                    raise
            transport.is_connected = cleanup == 'still_connected'

        transport.connect, transport.disconnect = connect, disconnect
        expected = (RuntimeError if cleanup == 'exception' or
                    (cleanup != 'stall' and setup == 'exception') else
                    TimeoutError if cleanup == 'stall' or setup == 'timeout' else asyncio.CancelledError)
        task = asyncio.create_task(stack_gateway_read.run(args))
        try:
            await asyncio.wait_for(entered.wait(), 3)
            if setup == 'cancel': task.cancel()
            with pytest.raises(expected): await task
            assert connect_cancelled.is_set() is (setup != 'exception')
            assert cleanup_cancelled.is_set() is (cleanup == 'stall')
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        return expected

    expected = asyncio.run(scenario())
    assert deadlines == [180, 10]
    assert (transport.client_constructions, transport.connect_calls, transport.disconnect_calls) == (1, 1, 1)
    assert transport.disconnected and not transport.writes and not transport.notifying
    assert not transport.stopped_notify
    rows = assert_aborted_without_capture(args, expected,
        cleanup in ('ok', 'still_connected'), cleanup == 'ok')
    assert not any(row['kind'] == 'request' for row in rows)


@pytest.mark.parametrize('failure', ['exception', 'timeout', 'cancel'])
def test_notification_setup_failure_still_stops_and_disconnects_before_any_cd(
        transport, tmp_path, failure):
    args = arguments(tmp_path)

    async def scenario():
        entered, cancelled = asyncio.Event(), asyncio.Event()
        original = transport.start_notify

        async def start(*values):
            # A backend can partly subscribe, then fail or be cancelled.
            await original(*values)
            entered.set()
            if failure == 'exception': raise RuntimeError('fake notify setup failed')
            if failure == 'timeout': raise TimeoutError('fake notify setup timed out')
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        transport.start_notify = start
        task = asyncio.create_task(stack_gateway_read.run(args))
        expected = {'exception': RuntimeError, 'timeout': TimeoutError, 'cancel': asyncio.CancelledError}[failure]
        try:
            await asyncio.wait_for(entered.wait(), 3)
            if failure == 'cancel': task.cancel()
            with pytest.raises(expected): await task
            assert cancelled.is_set() is (failure == 'cancel')
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        return expected

    expected = asyncio.run(scenario())
    assert not transport.writes and transport.notifying and transport.stopped_notify
    assert transport.reader.closed and transport.reader.pending is None
    assert not transport.reader._allowed_reads()
    assert transport.disconnect_calls == 1 and not transport.is_connected
    assert_aborted_without_capture(args, expected, True, True)


@pytest.mark.parametrize('failure', ['exception', 'timeout', 'cancel'])
def test_notification_cleanup_failure_still_disconnects_and_never_saves(
        transport, tmp_path, monkeypatch, failure):
    install(transport)
    args = arguments(tmp_path)
    deadlines = []
    original_timeout = asyncio.timeout

    def timeout(seconds):
        deadlines.append(seconds)
        return original_timeout(0.01 if seconds == 3 else seconds)

    monkeypatch.setattr(stack_gateway_read.asyncio, 'timeout', timeout)

    async def scenario():
        entered, cancelled = asyncio.Event(), asyncio.Event()
        original = transport.stop_notify

        async def stop(*values):
            await original(*values)
            entered.set()
            if failure == 'exception': raise RuntimeError('fake notify cleanup failed')
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        transport.stop_notify = stop
        task = asyncio.create_task(stack_gateway_read.run(args))
        expected = {'exception': RuntimeError, 'timeout': TimeoutError, 'cancel': asyncio.CancelledError}[failure]
        try:
            await asyncio.wait_for(entered.wait(), 3)
            if failure == 'cancel': task.cancel()
            with pytest.raises(expected): await task
            assert cancelled.is_set() is (failure != 'exception')
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        return expected

    expected = asyncio.run(scenario())
    assert deadlines[:2] == [180, 120] and deadlines[-2:] == [3, 10]
    assert len(transport.writes) == 122 and transport.stopped_notify and transport.reader.closed
    assert transport.disconnect_calls == 1 and transport.disconnected and not transport.is_connected
    assert_aborted_without_capture(args, expected, True, True)


def test_second_cancellation_during_disconnect_never_claims_confirmation(transport, tmp_path):
    args = arguments(tmp_path)

    async def scenario():
        connect_entered, disconnect_entered = asyncio.Event(), asyncio.Event()

        async def connect():
            transport.connect_calls += 1
            transport.connected = True
            # Deliberately optimistic backend property: not completion evidence.
            transport.is_connected = False
            connect_entered.set()
            await asyncio.Future()

        async def disconnect():
            transport.disconnect_calls += 1
            transport.disconnected = True
            disconnect_entered.set()
            await asyncio.Future()

        transport.connect, transport.disconnect = connect, disconnect
        task = asyncio.create_task(stack_gateway_read.run(args))
        try:
            await asyncio.wait_for(connect_entered.wait(), 3)
            task.cancel()
            await asyncio.wait_for(disconnect_entered.wait(), 3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())
    assert transport.connect_calls == transport.disconnect_calls == 1
    assert not transport.writes and not transport.is_connected
    assert_aborted_without_capture(args, asyncio.CancelledError, False, False)


@pytest.mark.parametrize('bad', ['existing_output', 'device', 'address', 'firmware', 'name',
                                'timeout', 'disconnect', 'late_traffic'])
def test_cli_failure_never_saves_success_or_retries(transport, tmp_path, bad):
    install(transport)
    args = arguments(tmp_path)
    if bad == 'existing_output': args.output.mkdir()
    if bad in ('device', 'address', 'firmware', 'name'):
        transport.info['hardware' if bad == 'device' else bad] = 'other'
    if bad == 'timeout': transport.timer_fault = 'timeout'
    if bad == 'disconnect': transport.fail_disconnect = True
    if bad == 'late_traffic': transport.late_traffic = True
    with pytest.raises((ValueError, RuntimeError, TimeoutError, FileExistsError)):
        asyncio.run(stack_gateway_read.run(args))
    assert not (args.output / 'stack-gateway.json').exists()
    if bad == 'existing_output':
        assert not transport.connected
    else:
        assert transport.disconnected
        rows = [json.loads(line) for line in (args.output / 'transcript.jsonl').read_text().splitlines()]
        assert rows[-1]['kind'] == 'aborted' and rows[-1]['retry'] is False
        assert rows[-1]['disconnect_confirmed'] is (bad != 'disconnect')
        assert not any(row['kind'] == 'completed' for row in rows)
        if bad in ('device', 'address', 'firmware', 'name'): assert not transport.writes


def test_cli_budget_stops_123rd_request_before_transport(transport, tmp_path, monkeypatch):
    install(transport)
    args = arguments(tmp_path)

    async def over_budget(reader, *unused):
        for _ in range(123): await reader.read(*cr.IDLE_WINDOW)
        raise AssertionError('transaction bound was not enforced')

    monkeypatch.setattr(gr, 'collect', over_budget)
    with pytest.raises(RuntimeError, match='budget exceeded'): asyncio.run(stack_gateway_read.run(args))
    assert len(transport.writes) == 122 and transport.disconnected and transport.stopped_notify
    assert not (args.output / 'stack-gateway.json').exists()


def test_cli_cancelled_stalled_write_unsubscribes_disconnects_and_never_saves(transport, tmp_path):
    install(transport)
    args = arguments(tmp_path)

    async def scenario():
        entered, cancelled = asyncio.Event(), asyncio.Event()
        original = transport.write_gatt_char
        start_notify = transport.start_notify

        async def start(*values):
            await start_notify(*values)
            transport.reader.timeout = 60

        async def write(*values, **kwargs):
            if transport.reader._gateway_phase == 'gateway_entry_cap':
                transport.bad = 'write_timeout'
                entered.set()
            try:
                await original(*values, **kwargs)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        transport.start_notify, transport.write_gatt_char = start, write
        task = asyncio.create_task(stack_gateway_read.run(args))
        try:
            await asyncio.wait_for(entered.wait(), 3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
            assert cancelled.is_set()
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())
    assert len(transport.writes) == 108 and transport.disconnected and transport.stopped_notify
    assert not transport.is_connected and transport.reader.closed and transport.reader.poisoned
    assert transport.reader.pending is None
    assert not (args.output / 'stack-gateway.json').exists()
    rows = [json.loads(line) for line in (args.output / 'transcript.jsonl').read_text().splitlines()]
    assert rows[-1]['kind'] == 'aborted' and rows[-1]['disconnect_confirmed'] is True
    assert rows[-1]['retry'] is False


@pytest.mark.parametrize('flag', ['--memory-address', '--length', '--retry', '--timer-hook-state'])
def test_cli_has_no_arbitrary_memory_retry_or_other_plan_switch(tmp_path, monkeypatch, flag):
    monkeypatch.setattr(sys, 'argv', ['stack_gateway_read', '--address', 'fake-device',
        '--output', str(tmp_path / 'unused'), '--confirmed-idle-clients', flag])
    with pytest.raises(SystemExit) as stopped: stack_gateway_read.main()
    assert stopped.value.code == 2 and not (tmp_path / 'unused').exists()


@pytest.mark.parametrize('address,length', [c for _, a, n in gr.WINDOWS for c in cr.chunks(a, n)])
@pytest.mark.parametrize('image', [BASE, V2], ids=['original25hz', 'v2'])
@pytest.mark.parametrize('state', [0, 2, 3])
def test_actual_cd_instructions_only_copy_each_fixed_new_chunk(image, state, address, length):
    # Existing strict hash-pinned dispatcher/CD/checksum witness, synthetic ROM/
    # RAM bytes and bounded memcpy boundary. No execution of the sampled data.
    rt.test_actual_cd_instructions_copy_fixed_low_rom_addresses_without_execution(
        image, state, address, length)
