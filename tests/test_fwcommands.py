"""Offline witnesses from actual fingerprinted stock branch/store bytes."""

from pathlib import Path

import pytest

from whip.fwcommands import StockWireAudit


BASE = Path(__file__).resolve().parent.parent / "firmware" / "rt02cr-stock-3.12.02.bin"
pytestmark = pytest.mark.skipif(not BASE.exists(), reason="stock firmware archive not present")


@pytest.fixture(scope="module")
def audit():
    return StockWireAudit(BASE.read_bytes())


def test_all_256_fast_routes_against_reviewed_map(audit):
    enqueued = set(bytes.fromhex("01 05 08 0e 15 18 37 38 39 3a 3b 43 72 77 7a 81 a1 c6 c7 ff"))
    silent = set(bytes.fromhex("14 b0 c1 c2 c9 cc f0 f1"))
    inline = {0x50: 0x5AFC, 0xC3: 0x5BC4, 0xC5: 0x5BFC, 0xC8: 0x5BEE, 0xFE: 0x59DA}
    direct = {
        0x02: (0x5A2E, 0x554A), 0x03: (0x5A56, 0x4AA0), 0x04: (0x5A5E, 0x54A6),
        0x0A: (0x5A3E, 0x480C), 0x0C: (0x5AAA, 0x4FDC), 0x0D: (0x5ABA, 0xE7AE),
        0x10: (0x5A36, 0x47F4), 0x16: (0x5A92, 0x50BA), 0x19: (0x5A4E, 0x54F8),
        0x1E: (0x5ADE, 0x4E4A), 0x21: (0x5AC6, 0x4ED6), 0x25: (0x5ACE, 0x4EC6),
        0x26: (0x5AD6, 0x4E9A), 0x27: (0x5A0A, 0x5742), 0x28: (0x5A16, 0x5706),
        0x2B: (0x5A46, 0x48A0), 0x2C: (0x5A9A, 0x5062), 0x36: (0x5AA2, 0x5010),
        0x3C: (0x5A26, 0x5582), 0x48: (0x5AE6, 0x4D76), 0x51: (0x59EA, 0x580E),
        0x52: (0x59FA, 0x57B6), 0x60: (0x5AF6, 0x4CEA), 0x61: (0x5AEE, 0x4D34),
        0x69: (0x5A66, 0x52A0), 0x6A: (0x5A8A, 0x5138), 0x7B: (0x5A1E, 0x55CC),
        0x7C: (0x5A02, 0x5756), 0x90: (0x5B36, 0x1B8C), 0x91: (0x5B3E, 0x1BA8),
        0x92: (0x5B46, 0x1BCE), 0x93: (0x5B4E, 0x1CFA), 0x94: (0x5B56, 0x1BE8),
        0x95: (0x5B5E, 0x1C0E), 0x96: (0x5B66, 0x1C36), 0x97: (0x5B6E, 0x1C5E),
        0x98: (0x5B76, 0x1C7C), 0x99: (0x5B7E, 0x1C80), 0x9A: (0x5B86, 0x1C82),
        0x9B: (0x5B8E, 0x1C86), 0x9C: (0x5B96, 0x1CB4), 0x9E: (0x5B9E, 0x1D78),
        0x9F: (0x5BAE, 0x1BD0), 0xA0: (0x5BA6, 0x1DCA), 0xBF: (0x5BB6, 0x48C6),
        0xC0: (0x5BBE, 0x4924), 0xC4: (0x5BE8, 0xA864), 0xCD: (0x5C14, 0x4C36),
        0xCE: (0x5C1C, 0x4B02),
    }
    assert len(enqueued | silent | inline.keys() | direct.keys()) == 82
    for opcode in range(256):
        route = audit.fast_route(opcode)
        assert route.prelude == (opcode not in (0x43, 0x48))
        if opcode in enqueued:
            assert (route.kind, route.site, route.target) == ("enqueue", 0x5C0C, 0x4CBC)
        elif opcode in silent:
            assert (route.kind, route.site, route.target) == ("silent", 0x5990, None)
        elif opcode in inline:
            assert (route.kind, route.site, route.target) == ("inline", inline[opcode], None)
        elif opcode in direct:
            assert (route.kind, route.site, route.target) == ("call", *direct[opcode])
        else:
            assert (route.kind, route.site, route.target) == ("nak", 0x59CE, 0x4ADE)


def test_all_256_queued_routes_and_fast_queue_disagreement(audit):
    targets = {
        0x01: 0x4966, 0x15: 0x6278, 0x18: 0x5FE2, 0x37: 0x5D68, 0x38: 0x5D16,
        0x39: 0x5C9C, 0x3A: 0x5F8A, 0x3B: 0x5E8E, 0x43: 0x634A, 0x72: 0x3F8E,
        0x77: 0x613C, 0x7A: 0x5DE2, 0x7C: 0x64F6, 0x81: 0x60DC, 0xA1: 0x2104,
        0xC7: 0xCBD0, 0xFF: 0x6118,
    }
    for opcode in range(256):
        route = audit.queued_route(opcode)
        if opcode in (0x08, 0xC6):
            assert route.kind == "inline"
            assert route.site == {0x08: 0x663E, 0xC6: 0x6656}[opcode]
        elif opcode in targets:
            assert (route.kind, route.target) == ("call", targets[opcode])
        else:
            assert (route.kind, route.site, route.target) == ("discard", 0x6694, None)
    for opcode in (0x05, 0x0E):
        assert audit.fast_route(opcode).kind == "enqueue"
        assert audit.queued_route(opcode).kind == "discard"
    assert audit.fast_route(0x7C).target == 0x5756
    assert audit.queued_route(0x7C).target == 0x64F6


def test_negative_witness_unknown_outer_commands_are_stateful(audit):
    for state in range(256):
        calls, writes = audit.prelude_slice(state)
        assert writes == {0x20A66C: 1}
        assert calls == ([(0x8124, 0x80EE), (0x812C, 0x948A)] if state in (2, 3) else [])
    for opcode in range(256):
        if audit.fast_route(opcode).kind == "nak":
            assert audit.fast_route(opcode).prelude
            assert audit.queued_route(opcode).kind == "discard"


def test_negative_witness_unknown_a1_clears_legacy_state(audit):
    for subcommand in range(256):
        site, writes = audit.unknown_a1_slice(subcommand)
        if 1 <= subcommand <= 8:
            assert site != 0x214A and writes == {}
        else:
            assert site == 0x214A
            assert writes == {0x209CB1: 0, 0x209CB2: 0}


def test_actual_length_state_gate(audit):
    for length in (0, 1, 15, 16, 17, 20, 255, 65535):
        for state in range(256):
            assert audit.length_gate(length, state) == (length == 16 and state != 1)


def test_exact_stock_identity_required():
    original = BASE.read_bytes()
    for offset in (0, 0x588A, 0x58A8, 0x5944, 0x657C, 0x8112, 0x1A378):
        changed = bytearray(original)
        changed[offset] ^= 1
        with pytest.raises(ValueError, match="unrecognized stock"):
            StockWireAudit(bytes(changed))
    with pytest.raises(ValueError, match="unrecognized stock"):
        StockWireAudit(original[:-1])


def test_registration_and_switch_helper_anchors(audit):
    data = audit.data
    pointers = tuple(int.from_bytes(data[at:at + 4], "little")
                     for at in (0x1F304, 0x1F308, 0x1F30C))
    assert pointers == (0x82DA55, 0x82DA7F, 0x82DAD3)
    assert data[0x1F24C:0x1F25C] == bytes.fromhex("9ecadc240ee5a9e093f3a3b5f0ff406e")
    assert data[0x1A378:0x1A392] == bytes.fromhex(
        "30b47446641e2578641cab4200d21d46635d5b00e31830bc1847"
    )
    assert data[0x5C22:0x5C32] == bytes.fromhex("fe4a1278012a02d0102900d128e67047")


@pytest.mark.parametrize("opcode", [-1, 256, "a1", None])
def test_bad_opcode_rejected(audit, opcode):
    with pytest.raises(ValueError, match="opcode must be one byte"):
        audit.fast_route(opcode)
    with pytest.raises(ValueError, match="opcode must be one byte"):
        audit.queued_route(opcode)
