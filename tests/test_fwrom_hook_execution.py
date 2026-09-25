"""Execute the separately captured create hook/comparator OFFLINE only.

The wrapper, RAM hook, ROM default, divider and native allocator are actual
captured instructions. Pool/list/critical-section state remains synthetic;
the unread failure handler at 0x111a6 is NEVER substituted with success.
Header-field equality is not authentication, boot recovery or flash approval.
"""
import hashlib
import json
from pathlib import Path
import struct

import pytest

from tests.test_fwrom_hook_archive import ARCHIVE, HASHES
from tests.test_fwrom_resume_execution import ResumeHarness, kernel_create_harness, SLOT, TIMER, BITMAP
from tests.test_fwrom_support_execution import install_support
from whip.fwrom_execution import ROMBoundaryError, ROMAssertion
from whip.fwrom_hook import NEW_WINDOWS

HOOK, COMPARE, FAILED = 0x205C00, 0x8E24, 0x111A6
RESULT, LEFT, RIGHT = 0x300200, 0x300400, 0x300600
UUID = bytes.fromhex("f94c6b7e11c5eb118282f74a0c0cef5b")
ROOT = Path(__file__).resolve().parents[1]


def install_new_bodies(h, *, hook=False, comparator=False):
    raw = (ARCHIVE / "rom-create-hook.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == HASHES["rom-create-hook.json"]
    saved = json.loads(raw)
    assert saved["repeated_equal"] and saved["final_state_header_equal"]
    assert not saved["target_execution"] and not saved["flash_authorized"]
    chosen = {"create_hook_ram_cap": (HOOK, HOOK + 48, HOOK + 52),
              "header_compare_rom_cap": (COMPARE, COMPARE + 34, COMPARE + 34)}
    for name, address, size in NEW_WINDOWS:
        w = saved["windows"][name]; data = bytes.fromhex(w["data_hex"])
        assert w["address"] == address and len(data) == size
        assert hashlib.sha256(data).hexdigest() == w["sha256"]
        if name not in chosen or not (hook if address == HOOK else comparator):
            continue
        lo, code_end, readable_end = chosen[name]
        assert address == lo
        h.uc.mem_write(address, data)
        h.windows[address] = data
        # Do not admit adjacent functions just because they share a read cap.
        h.readable.append((lo, readable_end))
        h.select(lo, code_end)
    if hook:
        # RAM code needs execute permission, unlike ordinary synthetic state.
        # Only this page is RX; the instruction hook still restricts it to the
        # 48-byte body, and all writes to this page remain forbidden.
        h.uc.mem_protect(0x205000, 0x1000, h.u.UC_PROT_READ | h.u.UC_PROT_EXEC)
    return h


def create_harness(*, free=True, allocated=False, period=17, reload=1,
                   existing=0, callback=0x47101, inhibit=None):
    h, original, _ = kernel_create_harness(free=free, allocated=allocated)
    install_support(h)
    install_new_bodies(h, hook=True)
    h.fixture(SLOT, struct.pack("<I", existing), writable=True)
    if inhibit is not None:
        h.fixture(0x20037D, bytes([inhibit]))  # Explicit counterfactual, not captured state.
    assert h.word(0x201644) == HOOK | 1
    return h, original, (SLOT, 0x12345678, 0x9ABCDEF0, period, reload, callback)


@pytest.mark.parametrize("period", [1, 8, 9, 10, 17, 32, 1000, 0xFFFFFFF6])
@pytest.mark.parametrize("reload", [0, 1, 2, 0xFFFFFFFF])
def test_actual_wrapper_hook_default_and_allocator_create_fresh_inactive_identity(period, reload):
    h, original, args = create_harness(period=period, reload=reload)
    assert h.call(0x13634, *args) == 1
    expected = bytearray(original)
    struct.pack_into("<I", expected, 0, args[1])
    struct.pack_into("<III", expected, 0x18, (period + 9) // 10, args[2], args[5])
    expected[0x28] = 4 if reload else 0
    assert bytes(h.uc.mem_read(TIMER, 48)) == expected
    assert h.word(SLOT) == TIMER and h.word(BITMAP) == 1
    assert h.word(0x201480) == h.word(0x201484) == 0
    assert int.from_bytes(h.uc.mem_read(0x201474, 2), "little") == 1
    assert {c.address for c in h.calls} <= {0x110C4, 0x110E0, 0x1105E, 0x11080, 0xE89A, 0x5E6A, 0x5AA8}
    assert [c.registers[0] for c in h.calls if c.address == 0xE89A] == [TIMER + 4]
    assert h.word(0x201644) == HOOK | 1 and not h.synthetic_literals
    # No mocked hook/default/division and no START or callback execution.


@pytest.mark.parametrize("reason", ["empty_pool", "marked_free_head", "zero_period", "null_callback"])
def test_actual_failure_path_stops_at_unread_failed_hook_without_inventing_recovery(reason):
    h, original, args = create_harness(free=reason != "empty_pool",
        allocated=reason == "marked_free_head", period=0 if reason == "zero_period" else 17,
        callback=0 if reason == "null_callback" else 0x47101)
    before = bytes(h.uc.mem_read(0x201474, 0x28))
    h.fixture(RESULT, b"\xa5", writable=True)
    with pytest.raises(ROMBoundaryError, match="unreviewed or uncaptured instruction at 0x111a6"):
        h.call(HOOK, *args, RESULT)
    assert h.uc.reg_read(h.a.UC_ARM_REG_PC) == FAILED
    assert bytes(h.uc.mem_read(RESULT, 1)) == b"\0"  # Failure stored before unread call.
    assert h.word(SLOT) == 0 and h.word(BITMAP) == int(reason == "marked_free_head")
    assert bytes(h.uc.mem_read(TIMER, 48)) == original
    assert bytes(h.uc.mem_read(0x201474, 0x28)) == before
    assert not h.returned and FAILED not in h.mocks
    assert not any(c.address in (0xE89A, 0x108E0) for c in h.calls)


def test_actual_wrapper_does_not_fall_back_when_real_hook_enters_unread_failure_body():
    h, _, args = create_harness(free=False)
    with pytest.raises(ROMBoundaryError, match="0x111a6"):
        h.call(0x13634, *args)
    assert h.word(SLOT) == h.word(BITMAP) == 0 and not h.returned


def test_occupied_slot_returns_failure_preserves_handle_and_does_not_call_failed_hook():
    h, original, args = create_harness(existing=TIMER)
    assert h.call(0x13634, *args) == 0
    assert h.word(SLOT) == TIMER and h.word(BITMAP) == 0
    assert bytes(h.uc.mem_read(TIMER, 48)) == original
    assert not h.calls and not h.writes


@pytest.mark.parametrize("inhibit", [1, 3, 255, 2, 254])
def test_only_inhibit_bit_zero_blocks_create_and_suppresses_failure_call(inhibit):
    h, _, args = create_harness(inhibit=inhibit)
    assert h.call(0x13634, *args) == int(not (inhibit & 1))
    assert h.word(SLOT) == (0 if inhibit & 1 else TIMER)
    assert h.word(BITMAP) == int(not (inhibit & 1))
    if inhibit & 1:
        assert not h.calls and not h.writes


def test_null_handle_slot_is_dereferenced_by_hook_after_default_rejects_it():
    h, _, args = create_harness()
    h.fixture(RESULT, b"\xa5", writable=True)
    with pytest.raises(ROMBoundaryError, match="read outside admitted evidence/fixtures at 0x0"):
        h.call(HOOK, 0, *args[1:], RESULT)
    assert bytes(h.uc.mem_read(RESULT, 1)) == b"\0"
    assert h.word(BITMAP) == 0 and not h.calls
    # What an actual read at zero would return is not admitted or inferred.


@pytest.mark.parametrize("period", [0xFFFFFFF7, 0xFFFFFFFF])
def test_actual_hook_path_retains_wrap_assertion_after_consuming_allocation(period):
    h, _, args = create_harness(period=period)
    h.fixture(RESULT, b"\xa5", writable=True)
    with pytest.raises(ROMAssertion):
        h.call(HOOK, *args, RESULT)
    assert h.word(SLOT) == 0 and h.word(BITMAP) == 1
    assert h.word(0x201480) == h.word(0x201484) == 0
    assert bytes(h.uc.mem_read(RESULT, 1)) == b"\xa5"  # Default never returns.
    assert h.word(TIMER + 0x20) == 0xA5A5A5A5  # Fresh callback not installed.
    assert not any(c.address in (0xE89A, 0x108E0, FAILED) for c in h.calls)


@pytest.mark.parametrize("result", [0, 1, 255, 256])
def test_hook_handled_result_is_distinct_from_operation_byte_under_explicit_default_fixture(result):
    h = install_new_bodies(install_support(ResumeHarness()), hook=True)
    h.fixture(SLOT, struct.pack("<I", TIMER))  # Prevent unread failure branch.
    h.fixture(RESULT, b"\xa5", writable=True)
    args = (SLOT, 0x12345678, 0x9ABCDEF0, 17, 1, 0x47101)

    def default(cpu, regs):
        assert regs == args[:4]
        sp = cpu.uc.reg_read(cpu.a.UC_ARM_REG_SP)
        assert (cpu.word(sp), cpu.word(sp + 4)) == args[4:]
        cpu.return_value(result)

    h.mock(0x13F9E, "isolated default-result ABI fixture, NOT the real default", default)
    assert h.call(HOOK, *args, RESULT) == 1
    assert bytes(h.uc.mem_read(RESULT, 1)) == bytes([result & 255])
    assert h.call(0x13634, *args) == result & 255
    assert [c.address for c in h.calls] == [0x13F9E, 0x13F9E]  # No duplicate fallback.


def comparator_harness():
    return install_new_bodies(ResumeHarness(), comparator=True)


@pytest.mark.parametrize("length", [0, 1, 2, 15, 16, 17, 64, 255])
def test_actual_comparator_exact_length_equality_and_no_mocks(length):
    h = comparator_harness()
    data = bytes((i * 37) & 255 for i in range(length))
    if length:
        h.fixture(LEFT, data); h.fixture(RIGHT, data)
    assert h.call(COMPARE, LEFT, RIGHT, length) == 1
    assert not h.calls and not h.writes


@pytest.mark.parametrize("index", range(16))
def test_actual_comparator_rejects_every_uuid_byte_mismatch(index):
    h = comparator_harness()
    bad = bytearray(UUID); bad[index] ^= 1
    h.fixture(LEFT, UUID); h.fixture(RIGHT, bad)
    assert h.call(COMPARE, LEFT, RIGHT, 16) == 0
    assert not h.calls and not h.writes


def test_comparator_does_not_short_circuit_after_first_mismatch():
    h = comparator_harness()
    h.fixture(LEFT, b"\x01"); h.fixture(RIGHT, b"\x02")
    with pytest.raises(ROMBoundaryError, match="read outside admitted evidence/fixtures at 0x300401"):
        h.call(COMPARE, LEFT, RIGHT, 2)
    assert not h.calls and not h.writes


@pytest.mark.parametrize("image_id,error_at", [(0x2792, 0x200062), (0x2793, 0x200063)])
@pytest.mark.parametrize("mismatch", [None, *range(16)])
def test_actual_header_checker_and_comparator_accept_uuid_or_write_exact_error(image_id, error_at, mismatch):
    h = install_new_bodies(install_support(ResumeHarness(), state=False), comparator=True)
    h.select(0x8A82, 0x8AE2); h.select(0x4C7A, 0x4C90)
    header = bytearray(52); header[0] = 12
    struct.pack_into("<H", header, 4, image_id)
    header[12:28] = UUID
    if mismatch is not None: header[12 + mismatch] ^= 1
    h.fixture(LEFT, header)
    h.fixture(0x200050, b"\xa5" * 32, writable=True)
    # Captured helper adds (image_id - 0x2790) to error array 0x200060.
    assert h.call(0x8A82, LEFT, image_id) == int(mismatch is None)
    assert h.writes == ([] if mismatch is None else [(error_at, 1, 0x15)])
    assert not h.calls
    # This checker does not verify payload length/checksum/SHA or bootability.


@pytest.mark.parametrize("filename,digest,expected", [
    ("rt02cr-stock-3.12.02.bin", "b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0", 0),
    ("rt02cr-25hz.bin", "f13e63d3fdef3b10aa20fd4e0672077b66f60bb19c689ef64053840e4d35d3d9", 1),
    ("rt02cr-25hz-optical-off-v2-experimental.bin", "0d18a0fa860d58ab8f984b5f542f45dac105241f47bf1c2af41321eb0431e14c", 1),
])
def test_exact_local_image_prefixes_use_real_checker_without_mutating_image(filename, digest, expected):
    raw = (ROOT / "firmware" / filename).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == digest
    h = install_new_bodies(install_support(ResumeHarness(), state=False), comparator=True)
    h.select(0x8A82, 0x8AE2); h.select(0x4C7A, 0x4C90)
    h.fixture(LEFT, raw[0x50:0x84])
    h.fixture(0x200050, b"\xa5" * 32, writable=True)
    assert h.call(0x8A82, LEFT, 0x2793) == expected
    assert h.writes == ([] if expected else [(0x200063, 1, 0x13)])
    assert not h.calls
    # Stock's source container still has not_ready set. No image was modified.
    # Acceptance of an original/V2 prefix is NOT an authenticated boot proof.


def test_captured_nonsecret_patch_prefix_passes_only_selected_header_field_check():
    raw = (ARCHIVE / "rom-create-hook.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == HASHES["rom-create-hook.json"]
    prefix = bytes.fromhex(json.loads(raw)["windows"]["nonsecret_patch_header"]["data_hex"])
    h = install_new_bodies(install_support(ResumeHarness(), state=False), comparator=True)
    h.select(0x8A82, 0x8AE2)
    h.fixture(LEFT, prefix)
    assert h.call(0x8A82, LEFT, 0x2792) == 1
    assert not h.calls and not h.writes
    # No payload, key field, checksum, copy or physical flash route is admitted.


@pytest.mark.parametrize("field,error", [("ic", 0x11), ("not_ready", 0x13), ("image_id", 0x14)])
def test_header_early_rejections_do_not_require_comparator_execution(field, error):
    h = install_support(ResumeHarness(), state=False)
    h.select(0x8A82, 0x8AE2); h.select(0x4C7A, 0x4C90)
    prefix = bytearray(28); prefix[0] = 12
    struct.pack_into("<H", prefix, 4, 0x2793); prefix[12:28] = UUID
    prefix[{"ic": 0, "not_ready": 2, "image_id": 4}[field]] ^= 0x80 if field == "not_ready" else 1
    h.fixture(LEFT, prefix)
    h.fixture(0x200050, b"\xa5" * 32, writable=True)
    assert h.call(0x8A82, LEFT, 0x2793) == 0
    assert h.writes == [(0x200063, 1, error)] and not h.calls


@pytest.mark.parametrize("entry", [HOOK + 48, HOOK + 52, COMPARE + 34, COMPARE + 36, FAILED])
def test_caps_do_not_authorize_literals_neighbors_or_unread_failure_code(entry):
    h = install_new_bodies(ResumeHarness(), hook=True, comparator=True)
    with pytest.raises(ROMBoundaryError, match="unreviewed or uncaptured"):
        h.call(entry)
    assert not h.calls and not h.writes
