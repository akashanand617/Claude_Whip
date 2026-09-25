"""Exact stock GATT/queue code and compiled call shim; no Bluetooth stack/device."""
from pathlib import Path
import struct

import pytest

pytest.importorskip('unicorn', reason='requires requirements-firmware-proof.txt')
from tests.test_unified_thumb import elf  # noqa: F401, E402
from whip.fwcontinuity import BIAS, ProofError  # noqa: E402
from whip.fwtransport import (  # noqa: E402
    StockTransportHarness, DATA, UART_TABLE, UART_CALLBACKS, UART_APP_CB,
    SMALL_QUEUE, APP_MESSAGE_QUEUE, APP_EVENT_QUEUE,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def h():
    return StockTransportHarness((ROOT / 'firmware/rt02cr-stock-3.12.02.bin').read_bytes())


def test_whole_image_identity_and_unreviewed_execution_fail_closed(h):
    altered = bytearray(h.image); altered[-1] ^= 1
    with pytest.raises(ValueError, match='SHA-256'): StockTransportHarness(altered)
    with pytest.raises(ProofError, match='unreviewed transport'): h.call(0x2104)


@pytest.mark.parametrize('success,assigned', [(0, 0), (1, 0), (1, 4), (1, 254)])
def test_stock_registration_passes_callback_struct_by_value_and_propagates_result(h, success, assigned):
    callback = BIAS + 0x6F29
    h.registration_results.append((success, assigned))
    before = bytes(h.uc.mem_read(UART_APP_CB, 4))
    assert h.call(0x7B40, callback) == (assigned if success else 255)
    assert h.registrations == [(BIAS + UART_TABLE, h.image[UART_TABLE:UART_TABLE + 168],
                               struct.unpack_from('<III', h.image, UART_CALLBACKS))]
    assert bytes(h.uc.mem_read(UART_APP_CB, 4)) == (struct.pack('<I', callback) if success else before)
    assert {0x7B40, 0x15824}.issubset(h.executed)
    assert h.stack_calls[0][0] == 0x3102


def test_setup_reserves_exactly_five_services_and_uses_all_five(h):
    h.call(0x76B8)
    assert h.stack_calls[0][:2] == (0x3100, 5)
    assert len(h.registrations) == 5
    assert bytes(h.uc.mem_read(0x209E1B, 5)) == bytes(range(5))
    assert [entry[0] for entry in h.stack_calls].count(0x3102) == 5
    assert (0x3104, BIAS + 0x6F29) in [x[:2] for x in h.stack_calls]
    assert [x[0] for x in h.setup_boundaries] == [0x1484A, 0x7F10]


@pytest.mark.parametrize('failed_index', range(5))
def test_existing_setup_continues_after_individual_registration_failure(h, failed_index):
    h.registration_results.extend((0 if index == failed_index else 1, index) for index in range(5))
    h.call(0x76B8)
    expected = bytearray(range(5)); expected[failed_index] = 255
    assert bytes(h.uc.mem_read(0x209E1B, 5)) == bytes(expected)
    assert len(h.registrations) == 5


@pytest.mark.parametrize('stored_length,offset', [(0, 0), (1, 0), (10, 0), (10, 8)])
def test_legacy_read_branch_is_not_a_bounded_discovery_descriptor(h, stored_length, offset):
    h.uc.mem_write(0x208526, bytes([stored_length]))
    h.uc.mem_write(DATA, b'\xa5' * 16)
    assert h.call(0x7AA4, 3, 4, 7, offset, DATA, DATA + 4) == 0
    assert struct.unpack('<H', h.uc.mem_read(DATA, 2))[0] == (stored_length - 1) & 0xFFFF
    assert struct.unpack('<I', h.uc.mem_read(DATA + 4, 4))[0] == 0x208528
    assert bytes(h.uc.mem_read(DATA + 2, 2)) == b'\xa5' * 2
    # Index 7 is outside this UART's registered six-entry database. This only
    # executes the dormant callback branch, never claims it can be read by BLE.


@pytest.mark.parametrize('index,length,write_type,pointer,expected', [
    (2, 16, 0, DATA, 0), (2, 20, 1, DATA, 0), (2, 0, 3, DATA, 0),
    (7, 20, 0, DATA, 0), (4, 16, 0, DATA, 0x40A), (2, 16, 0, 0, 0x40D)])
def test_stock_uart_write_callback_stack_abi_and_ignored_write_type(h, index, length, write_type, pointer, expected):
    h.uc.mem_write(DATA, bytes(range(20)))
    assert h.call(0x7ACE, 3, 4, index, write_type, length, pointer, DATA + 128) == expected
    assert len(h.legacy_receives) == int(index == 2 and pointer != 0)
    if h.legacy_receives:
        assert h.legacy_receives[0] == (DATA, length, bytes(range(min(length, 20))))
    # We stop BEFORE legacy dispatch, not a claim these requests are harmless.


@pytest.mark.parametrize('bits', [0, 1, 2, 3, 0xFFFF])
def test_stock_uart_cccd_callback_only_logs_not_subscription_gate(h, bits):
    before = bytes(h.uc.mem_read(0x208000, 0x5000))
    h.call(0x7B22, 3, 4, 5, bits)
    assert len(h.logs) == 1 and not h.stack_calls and not h.messages
    assert bytes(h.uc.mem_read(0x208000, 0x5000)) == before


@pytest.mark.parametrize('status', [0, 1, 2, 255])
def test_low_level_notify_uses_stack_output_byte_not_syscall_return(h, status):
    h.uc.mem_write(DATA, bytes(range(20)))
    h.send_results.append(status)
    assert h.call(0x7DC4, DATA, 20) == status
    assert h.sends == [(3, 4, 4, bytes(range(20)), 1)]
    assert {0x7DC4, 0x158EE}.issubset(h.executed)


def enqueue(h, value):
    h.uc.mem_write(DATA, bytes([value % 256]) * 16)
    h.call(0x7E30, DATA)


def test_actual_uart_queue_wrap_aliases_full_to_empty_and_overwrites(h):
    for value in range(128): enqueue(h, value)
    assert h.queue_cursors() == (0, 0)
    assert len(h.messages) == 2  # only first wake; flag is never an occupancy bound
    h.call(0x7E64)
    assert not h.sends
    enqueue(h, 128)
    assert h.queue_cursors() == (0, 1)
    h.call(0x7E64)
    assert h.sends == [(3, 4, 4, bytes([128]) * 16, 1)]
    assert h.queue_cursors() == (1, 1)


def test_disconnected_uart_enqueue_silently_discards(h):
    h.uc.mem_write(0x209E11, b'\0')
    enqueue(h, 10)
    assert h.queue_cursors() == (0, 0) and not h.messages and not h.sends


@pytest.mark.parametrize('failure', ['message', 'event'])
def test_failed_wake_keeps_busy_latched_and_blocks_next_wake(h, failure):
    h.message_results.extend([False] if failure == 'message' else [True, False])
    enqueue(h, 10)
    assert bytes(h.uc.mem_read(SMALL_QUEUE, 1)) == b'\1'
    assert h.queue_cursors() == (0, 1)
    attempts = len(h.messages)
    enqueue(h, 11)
    h.call(0x7DFE)  # even send-complete wake sees busy and returns
    assert len(h.messages) == attempts and not h.sends
    assert h.queue_cursors() == (0, 2)
    assert [m[0] for m in h.messages] == ([APP_MESSAGE_QUEUE] if failure == 'message'
                                         else [APP_MESSAGE_QUEUE, APP_EVENT_QUEUE])


@pytest.mark.parametrize('result', [0, 2, 255])
def test_21st_failed_drain_discards_queue_and_does_not_retry_forever(h, result):
    enqueue(h, 10); enqueue(h, 11)
    h.default_send_result = result
    for _ in range(20): h.call(0x7E64)
    assert h.queue_cursors() == (0, 2) and len(h.delays) == 20
    h.call(0x7E64)
    assert h.queue_cursors() == (2, 2) and len(h.sends) == 21 and len(h.delays) == 20


def test_legacy_queue_has_no_connection_generation_binding(h):
    enqueue(h, 10)
    # Simulate a different connected link before old data is drained. The code
    # reads current globals; there is no retained original connection identity.
    h.uc.mem_write(0x209E12, b'\x09')
    h.call(0x7E64)
    assert h.sends == [(9, 4, 4, bytes([10]) * 16, 1)]


@pytest.mark.parametrize('cause,wakes', [(0, True), (1, False), (0x1234, False)])
def test_stock_general_send_callback_reads_short_enum_cause_at_offset_eight(h, cause, wakes):
    h.uc.mem_write(SMALL_QUEUE + 2, struct.pack('<HH', 0, 1))
    # event byte, pad, credits u16, conn u8, service u8, attr u16, cause u16.
    event = struct.pack('<BBHBBHH', 1, 0, 12, 99, 88, 77, cause)
    h.uc.mem_write(DATA, event)
    assert h.call(0x6F28, 255, DATA) == 0
    assert bool(h.messages) == wakes
    # Wrong conn/service/attribute still causes the same global wake: this is
    # NOT a correlation receipt for the new service or a particular packet.


def test_four_byte_enum_callback_layout_is_incompatible_with_stock(h):
    h.uc.mem_write(SMALL_QUEUE + 2, struct.pack('<HH', 0, 1))
    # Naive default-enum layout moves cause to +10. Stock instead reads attr +8.
    h.uc.mem_write(DATA, struct.pack('<IHBBHH', 1, 12, 3, 4, 0, 9))
    assert h.call(0x6F28, 255, DATA) == 0
    assert h.messages  # Treats the failed cause9 event as successful cause0.


@pytest.fixture
def bound(h, elf):
    h.load_shim(elf)
    return h


def add_inputs(h):
    h.uc.mem_write(DATA, b'\xa5' * 160)
    callbacks = struct.unpack_from('<III', h.image, UART_CALLBACKS)
    h.uc.mem_write(DATA + 32, struct.pack('<III', *callbacks))
    return callbacks


@pytest.mark.parametrize('status,assigned,accepted', [(0, 0, False), (1, 7, True),
                                                    (1, 255, False), (2, 7, False)])
def test_compiled_add_shim_matches_original_by_value_abi(bound, status, assigned, accepted):
    callbacks = add_inputs(bound)
    bound.registration_results.append((status, assigned))
    assert bound.call_shim('wg_stock_add', DATA, BIAS + UART_TABLE, 6, DATA + 32) == accepted
    assert bytes(bound.uc.mem_read(DATA, 1)) == bytes([assigned if accepted else 255])
    assert bytes(bound.uc.mem_read(DATA + 1, 15)) == b'\xa5' * 15
    assert bound.registrations == [(BIAS + UART_TABLE, bound.image[UART_TABLE:UART_TABLE + 168], callbacks)]
    assert 0x15824 in bound.executed


@pytest.mark.parametrize('failure', ['output', 'table', 'callbacks', 'zero_count', 'overflow_count',
                                    'even_read', 'even_write', 'even_cccd'])
def test_compiled_add_rejects_bad_syntax_without_calling_stack(bound, failure):
    callbacks = list(add_inputs(bound))
    for index, name in enumerate(('even_read', 'even_write', 'even_cccd')):
        if failure == name: callbacks[index] &= ~1
    bound.uc.mem_write(DATA + 32, struct.pack('<III', *callbacks))
    assert not bound.call_shim('wg_stock_add', 0 if failure == 'output' else DATA,
                              0 if failure == 'table' else BIAS + UART_TABLE,
                              0 if failure == 'zero_count' else 2341 if failure == 'overflow_count' else 6,
                              0 if failure == 'callbacks' else DATA + 32)
    assert not bound.stack_calls


@pytest.mark.parametrize('status', [0, 1, 2, 255])
def test_compiled_notify_shim_uses_separate_service_and_fixed_twenty_bytes(bound, status):
    packet = bytes(range(20))
    bound.uc.mem_write(DATA, packet)
    bound.send_results.append(status)
    assert bound.call_shim('wg_stock_notify20', 2, 5, 7, DATA) == (status == 1)
    assert bound.sends == [(2, 5, 7, packet, 1)]
    assert 0x158EE in bound.executed and 0x7E30 not in bound.executed
    assert not bound.messages and bytes(bound.uc.mem_read(DATA, 20)) == packet


@pytest.mark.parametrize('connection,service,attribute,pointer', [
    (255, 5, 7, DATA), (2, 255, 7, DATA), (2, 5, 0, DATA), (2, 5, 7, 0)])
def test_compiled_notify_rejects_invalid_arguments_without_stack(bound, connection, service, attribute, pointer):
    assert not bound.call_shim('wg_stock_notify20', connection, service, attribute, pointer)
    assert not bound.stack_calls
