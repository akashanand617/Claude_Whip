"""Saved physical comparison replay plus captured boot code with explicit mocks.

The synthetic factory/OEM data, ROM header resolver, SHA, memcmp, logging and
unidentified failure helper are NOT further device reads or recovery evidence.
"""
import asyncio
import hashlib
import json
import struct
from itertools import product

import pytest

from tests.test_fwboot_read import BASE, V2, ROOT, SYMBOLS, REFERENCE, HEADER, BODY
from whip import fwboot_read as br, protocol

ARCHIVE = ROOT / "firmware/research/2026-09-23/boot-reference"


def test_exact_archive_hashes_and_physical_transactions_replay():
    expected = {"boot-reference.json": "f9798ed89e9d2e5b055a2fd5f930be635621e7ec7f35e0e0ada6bd82e36b8aed",
                "transcript.jsonl": "e5391cc14ccb75d3f196316bf05af54d26b685a5ecd39d1e142118c7b23d1925"}
    for name, digest in expected.items():
        assert hashlib.sha256((ARCHIVE / name).read_bytes()).hexdigest() == digest
    saved = json.loads((ARCHIVE / "boot-reference.json").read_text())
    rows = [json.loads(s) for s in (ARCHIVE / "transcript.jsonl").read_text().splitlines()]
    assert rows[0]["plan"] == "boot-reference-v1"
    assert rows[-2] == {"kind": "disconnected", "confirmed": True}
    assert rows[-1]["kind"] == "completed" and rows[-1]["requests"] == 182
    pairs = [r for r in rows if r["kind"] in ("request", "reply")]
    assert len(pairs) == 364
    for request, reply in zip(pairs[::2], pairs[1::2], strict=True):
        assert (request["kind"], reply["kind"]) == ("request", "reply")
        assert (request["address"], request["length"]) == (reply["address"], reply["length"])
        assert request["monotonic"] < reply["monotonic"]
        for row in (request, reply):
            p = bytes.fromhex(row["packet"])
            assert len(p) == 16 and p[-1] == protocol.checksum(p[:-1])
        p = bytes.fromhex(request["packet"])
        assert p[:2] == b"\xcd\x01" and p[2] == request["length"]
        assert int.from_bytes(p[3:7], "big") == request["address"]
        assert not (request["address"] < 0x80D400 and request["address"] + request["length"] > 0x80D034)

    class Replay:
        index = 0

        async def write_gatt_char(self, uuid, packet, *, response):
            assert uuid == protocol.UART_RX_CHAR_UUID and response is False
            assert bytes(packet).hex() == pairs[self.index]["packet"]
            self.reader.notify(None, bytes.fromhex(pairs[self.index + 1]["packet"]))
            self.index += 2

    client = Replay()
    client.reader = br.BootReferenceReader(client, lambda _: None, spacing=0)
    actual = asyncio.run(br.collect_boot_reference(client.reader, BASE, V2, SYMBOLS, saved["session_id"], REFERENCE))
    assert actual == saved and client.index == 364
    assert bytes.fromhex(actual["header"]["data_hex"]) == HEADER
    assert bytes.fromhex(actual["body"]["data_hex"]) == BODY
    assert actual["body_matches_reference"] and client.reader.closed and not client.reader.poisoned


@pytest.mark.parametrize("ft_valid,oem_valid", tuple(product(product((False, True), repeat=2), repeat=2)))
def test_captured_boot_selects_synthetic_factory_and_oem_config_not_app_recovery(ft_valid, oem_valid):
    import unicorn as u
    from unicorn import arm_const as a

    body = bytes.fromhex(json.loads((ARCHIVE / "boot-reference.json").read_text())["body"]["data_hex"])
    assert hashlib.sha256(body).hexdigest() == br.BODY_SHA256
    # The matched non-secret header declares SRAM execution, not XIP at 80d400.
    assert struct.unpack_from("<III", HEADER, 28) == (0x214000, 0x80D400, 528)
    uc = u.Uc(u.UC_ARCH_ARM, u.UC_MODE_THUMB | u.UC_MODE_MCLASS)
    uc.ctl_set_cpu_model(a.UC_CPU_ARM_CORTEX_M0)
    for address, size, permissions in ((0, 0x40000, u.UC_PROT_READ | u.UC_PROT_EXEC),
            (0x214000, 0x1000, u.UC_PROT_READ | u.UC_PROT_EXEC),
            (0x200000, 0x2000, u.UC_PROT_READ | u.UC_PROT_WRITE),
            (0x300000, 0x4000, u.UC_PROT_READ),
            (0x310000, 0x2000, u.UC_PROT_READ | u.UC_PROT_WRITE)):
        uc.mem_map(address, size, permissions)
    uc.mem_write(0x214000, body)
    ft_addresses, oem_addresses = (0x300200, 0x302900), (0x300400, 0x302800)
    for addresses, valid, length in ((ft_addresses, ft_valid, 480), (oem_addresses, oem_valid, 96)):
        for address, ok in zip(addresses, valid, strict=True):
            payload = bytes((i * 13 + 7) & 255 for i in range(length))
            digest = hashlib.sha256(payload).digest()
            if not ok: digest = bytes([digest[0] ^ 1]) + digest[1:]
            uc.mem_write(address, payload + digest)
    globals_ = {0x2011DC: 1, 0x200110: 4, 0x200114: 4, 0x2011DD: 1, 0x2011EA: 1}
    for address, size in globals_.items(): uc.mem_write(address, b"\xA5" * size)
    sp, stop, returned, calls, writes = 0x312000, 0x3FFF0, [], [], []
    preserved = (a.UC_ARM_REG_R4, a.UC_ARM_REG_R5)
    for i, register in enumerate(preserved): uc.reg_write(register, 0xABC000 + i)

    def ret(value=0):
        uc.reg_write(a.UC_ARM_REG_R0, value)
        uc.reg_write(a.UC_ARM_REG_PC, uc.reg_read(a.UC_ARM_REG_LR))

    def code(cpu, pc, size, _):
        if pc == stop:
            returned.append(True)
            cpu.emu_stop()
            return
        if 0x214000 <= pc < 0x214000 + len(body): return
        r0, r1, r2 = [cpu.reg_read(r) for r in (a.UC_ARM_REG_R0, a.UC_ARM_REG_R1, a.UC_ARM_REG_R2)]
        calls.append((pc, r0, r1, r2))
        if pc in (0x37EC, 0x5A06): ret()  # Unread UART init/logging.
        elif pc == 0x8AE2:
            assert r0 in (0x278D, 0x278E)
            ret({0x278D: 0x300000, 0x278E: 0x302000}[r0])  # Synthetic resolver.
        elif pc == 0x3F5D4:
            assert (r0, r1) in [(p, n) for addresses, n in ((ft_addresses, 480), (oem_addresses, 96)) for p in addresses]
            assert sp - 64 <= r2 <= sp - 32
            cpu.mem_write(r2, hashlib.sha256(bytes(cpu.mem_read(r0, r1))).digest())
            ret()
        elif pc == 0x3F7A8:
            assert r2 == 32
            ret(0 if bytes(cpu.mem_read(r0, r2)) == bytes(cpu.mem_read(r1, r2)) else 1)
        elif pc == 0x4C7A:
            assert (r0, r1) == (0x278D, 0x16)
            ret()  # Unidentified failure helper; its real side effects unknown.
        else: pytest.fail(f"unreviewed execution at {pc:#x}")

    def write(cpu, access, address, size, value, _):
        if sp - 64 <= address and address + size <= sp: return
        assert globals_.get(address) == size
        writes.append((address, size))

    uc.hook_add(u.UC_HOOK_CODE, code)
    uc.hook_add(u.UC_HOOK_MEM_WRITE, write)
    uc.reg_write(a.UC_ARM_REG_SP, sp)
    uc.reg_write(a.UC_ARM_REG_LR, stop | 1)
    uc.emu_start(0x214001, 0, count=2000)
    assert returned and uc.reg_read(a.UC_ARM_REG_R0) == 1
    assert uc.reg_read(a.UC_ARM_REG_SP) == sp
    assert [uc.reg_read(r) for r in preserved] == [0xABC000, 0xABC001]
    assert bool(uc.mem_read(0x2011DC, 1)[0]) == any(ft_valid)
    if not any(ft_valid):
        assert not any(address in (0x200110, 0x200114, 0x2011DD, 0x2011EA) for address, _ in writes)
        return
    chosen_ft = ft_addresses[0 if ft_valid[0] else 1] + 0x96
    chosen_oem = oem_addresses[0 if oem_valid[0] else 1]
    assert struct.unpack("<I", uc.mem_read(0x200110, 4))[0] == chosen_ft
    assert struct.unpack("<I", uc.mem_read(0x200114, 4))[0] == chosen_oem
    assert bool(uc.mem_read(0x2011DD, 1)[0]) == any(oem_valid)
    assert bytes(uc.mem_read(0x2011EA, 1)) == b"\0"
    assert bytes(uc.mem_read(0x214000, len(body))) == body
