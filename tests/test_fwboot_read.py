"""Fixed boot comparison: fake transport and selected CD code, no hardware."""
import asyncio
import hashlib
import json

import pytest

from probe import rom_read
from tests.test_fwrom_read import BASE, V2, ROOT, SYMBOLS, ROMFake, arguments, transport
from whip import fwboot_read as br, fwcapacity, fwcapacity_read as cr, fwrom_read as rr, protocol

REFERENCE = (ROOT / "firmware/research/2026-09-23/reference-boot/rtl8762e-sdk-boot.json").read_bytes()
HEADER, BODY = br.validate_reference(REFERENCE)


class BootFake(ROMFake):
    def __init__(self):
        super().__init__()
        self.reader = br.BootReferenceReader(self, self.events.append, timeout=0.01, spacing=0)
        self.config.update({br.HEADER_WINDOW[0]: HEADER, br.BODY_WINDOW[0]: BODY})
        self.header_reads = self.body_reads = 0
        self.boot_fault = self.boot_change = None

    def memory(self, address, length):
        if br.HEADER_WINDOW[0] <= address < sum(br.HEADER_WINDOW): self.header_reads += 1
        if br.BODY_WINDOW[0] <= address < sum(br.BODY_WINDOW): self.body_reads += 1
        raw = super().memory(address, length)
        mutate = ((self.boot_change == "header_repeat" and address == br.HEADER_WINDOW[0] and self.header_reads > 4)
                  or (self.boot_change == "body_repeat" and address == br.BODY_WINDOW[0] and self.body_reads > 38)
                  or (self.boot_change == "config_after" and self.body_reads and address == cr.CONFIG_WINDOWS[0][0]))
        if self.boot_change == "idle_after" and self.body_reads and address == cr.IDLE_WINDOW[0]: return b"\x04"
        return bytes([raw[0] ^ 1]) + raw[1:] if mutate else raw

    async def write_gatt_char(self, uuid, packet, response):
        if self.boot_fault:
            phase, fault = self.boot_fault
            if self.reader._boot_phase == phase: self.bad = fault
        await super().write_gatt_char(uuid, packet, response)


def collect(f, reference=REFERENCE):
    return asyncio.run(br.collect_boot_reference(f.reader, BASE, V2, SYMBOLS, "fake-only", reference))


def test_exact_plan_excludes_keys_and_closes_after_182_transactions():
    f = BootFake()
    result = collect(f)
    assert len(f.writes) == br.EXPECTED_TRANSACTIONS == 182
    assert f.writes[91:] == (list(cr.chunks(*br.HEADER_WINDOW)) * 2 + list(cr.chunks(*br.BODY_WINDOW)) * 2
        + [c for w in cr.CONFIG_WINDOWS for c in cr.chunks(*w)] + [cr.IDLE_WINDOW])
    assert (f.header_reads, f.body_reads) == (8, 76)
    assert result["schema"] == br.SCHEMA and result["body_matches_reference"] and result["repeated_equal"]
    assert bytes.fromhex(result["body"]["data_hex"]) == BODY
    assert result["body"]["sha256"] == hashlib.sha256(BODY).hexdigest()
    assert not any(result[k] for k in ("keys_read", "pointer_following", "target_execution",
                                      "full_image_attestation", "recovery_verified", "flash_authorized"))
    assert not any(a < 0x80D400 and a + n > 0x80D034 for a, n in f.writes)
    assert f.reader.closed and not f.reader.poisoned and f.reader._boot_phase is None
    for c in (cr.IDLE_WINDOW, cr.chunks(*br.HEADER_WINDOW)[0], cr.chunks(*br.BODY_WINDOW)[0]):
        with pytest.raises(ValueError): asyncio.run(f.reader.read(*c))
    with pytest.raises(RuntimeError, match="already used"): collect(f)
    assert len(f.writes) == 182


def test_no_boot_or_rom_reads_without_explicit_correct_phase():
    f = BootFake()
    for phase in (None, "header", "body"):
        f.reader._boot_phase = phase
        f.reader._rom_phase = "timers"  # Cannot inherit the separate ROM plan.
        for window in (br.HEADER_WINDOW, br.BODY_WINDOW, rr.TIMER_WINDOW):
            if (phase, window) in (("header", br.HEADER_WINDOW), ("body", br.BODY_WINDOW)): continue
            for chunk in cr.chunks(*window):
                with pytest.raises(ValueError): asyncio.run(f.reader.read(*chunk))
    assert not f.writes


@pytest.mark.parametrize("phase", ["header", "body"])
def test_even_active_phase_cannot_read_keys_metadata_adjacent_bytes_or_returned_pointers(phase):
    f = BootFake()
    f.reader._boot_phase = phase
    for a, n in ((0x80D034, 14), (0x80D033, 2), (0x80D044, 14), (0x80D3F2, 14),
                 (0x80D610, 1), (0x80CFFE, 2), (0x214000, 14), (0x200414, 4),
                 (0x40000000, 4), (br.HEADER_WINDOW[0], 15), (True, 1)):
        with pytest.raises(ValueError): asyncio.run(f.reader.read(a, n))
    assert not f.writes


@pytest.mark.parametrize("bad", ["reference", "base_image", "identity", "diagnostic", "idle", "ram", "descriptor", "header"])
def test_prerequisite_failure_never_reads_body(bad):
    f = BootFake()
    if bad == "base_image": f.image = BASE
    if bad in ("identity", "diagnostic"):
        offset = 0x21D6 if bad == "identity" else 0x564A
        f.image = V2[:offset] + bytes([V2[offset] ^ 1]) + V2[offset + 1:]
    if bad == "idle": f.raw = 4
    if bad in ("ram", "descriptor", "header"):
        address = {"ram": cr.CONFIG_WINDOWS[0][0], "descriptor": cr.BANK0_DESCRIPTOR_WINDOW[0],
                   "header": br.HEADER_WINDOW[0]}[bad]
        raw = f.config[address]
        f.config[address] = bytes([raw[0] ^ 1]) + raw[1:]
    with pytest.raises((ValueError, RuntimeError)): collect(f, REFERENCE + b"\n" if bad == "reference" else REFERENCE)
    assert not f.body_reads and f.reader.closed and f.reader.poisoned
    if bad != "header": assert not f.header_reads
    if bad == "reference": assert not f.writes


@pytest.mark.parametrize("phase", ["header", "body"])
@pytest.mark.parametrize("fault", ["timeout", "write_timeout", "checksum", "short", "stream", "duplicate"])
def test_transport_fault_closes_without_retry(phase, fault):
    f = BootFake()
    f.boot_fault = phase, fault
    with pytest.raises((RuntimeError, TimeoutError)): collect(f)
    assert len(f.writes) == (92 if phase == "header" else 100)
    assert f.reader.closed and f.reader.poisoned and f.reader._boot_phase is None
    with pytest.raises(RuntimeError): collect(f)
    assert len(f.writes) == (92 if phase == "header" else 100)


@pytest.mark.parametrize("change", ["header_repeat", "body_repeat", "config_after", "idle_after"])
def test_changed_repeat_or_postcheck_never_declares_success(change):
    f = BootFake()
    f.boot_change = change
    with pytest.raises(RuntimeError): collect(f)
    assert f.reader.closed and f.reader.poisoned and len(f.writes) <= 182
    if change == "header_repeat": assert not f.body_reads


def test_repeated_different_code_is_preserved_as_comparison_not_recovery():
    f = BootFake()
    f.config[br.BODY_WINDOW[0]] = bytes([BODY[0] ^ 1]) + BODY[1:]
    result = collect(f)
    assert result["repeated_equal"] and not result["body_matches_reference"]
    assert not result["recovery_verified"] and not result["flash_authorized"]


def test_wrong_reader_is_rejected_before_any_transaction():
    f = ROMFake()
    with pytest.raises(ValueError): collect(f)
    assert not f.writes


@pytest.mark.parametrize("failure", [None, "confirmation", "conflicting_plan", "device", "address", "header", "disconnect", "late_traffic"])
def test_cli_disconnect_and_fail_closed(transport, tmp_path, failure):
    args = arguments(tmp_path)
    args.boot_reference = True
    transport.config.update({br.HEADER_WINDOW[0]: HEADER, br.BODY_WINDOW[0]: BODY})
    if failure == "confirmation": args.confirmed_idle_clients = False
    if failure == "conflicting_plan": args.timer_internals = True
    if failure == "device": transport.info["hardware"] = "other"
    if failure == "address": transport.info["address"] = "other"
    if failure == "header": transport.config[br.HEADER_WINDOW[0]] = b"\0" * 52
    if failure == "disconnect": transport.fail_disconnect = True
    if failure == "late_traffic": transport.late_traffic = True
    if failure:
        with pytest.raises((ValueError, RuntimeError)): asyncio.run(rom_read.run(args))
        assert not (args.output / "boot-reference.json").exists()
        if failure in ("confirmation", "conflicting_plan"):
            assert not transport.connected and not args.output.exists()
        else:
            assert transport.disconnected
            rows = [json.loads(s) for s in (args.output / "transcript.jsonl").read_text().splitlines()]
            assert rows[-1]["kind"] == "aborted"
        return
    assert asyncio.run(rom_read.run(args)) == 0
    assert transport.disconnected and transport.stopped_notify and not transport.is_connected
    rows = [json.loads(s) for s in (args.output / "transcript.jsonl").read_text().splitlines()]
    assert [r["kind"] for r in rows[-2:]] == ["disconnected", "completed"]
    assert rows[-1]["requests"] == 182 and rows[-1]["boot_code_bytes"] == 528
    assert rows[-1]["nonsecret_boot_header_bytes"] == 52 and rows[-1]["rom_bytes"] == 0
    assert rows[-1]["capture_sha256"] == hashlib.sha256((args.output / "boot-reference.json").read_bytes()).hexdigest()


def test_bad_reference_stops_cli_before_connect_or_output(monkeypatch, transport, tmp_path):
    args = arguments(tmp_path)
    args.boot_reference = True
    def reject(raw): raise ValueError("unreviewed external boot reference")
    monkeypatch.setattr(br, "validate_reference", reject)
    with pytest.raises(ValueError): asyncio.run(rom_read.run(args))
    assert not transport.connected and not args.output.exists()


# Boundary chunks exercise both ends of each window, including shortened tails.
@pytest.mark.parametrize("address,length", [cr.chunks(*w)[i] for w in (br.HEADER_WINDOW, br.BODY_WINDOW) for i in (0, -1)])
@pytest.mark.parametrize("image", [BASE, V2], ids=["original25hz", "v2"])
@pytest.mark.parametrize("state", [0, 2, 3])
def test_actual_cd_copies_boot_boundaries_without_execution_or_key_access(address, length, image, state):
    class FixedCopy(fwcapacity.CDReadHarness):
        def _code(self, uc, pc, size, user):
            if pc == 0x3F848:
                r0, r1, r2 = [uc.reg_read(r) for r in (self.a.UC_ARM_REG_R0, self.a.UC_ARM_REG_R1, self.a.UC_ARM_REG_R2)]
                assert (r0, r1, r2) == (self.STACK - 31, address, length)
                uc.mem_write(r0, bytes(uc.mem_read(r1, r2)))
                self._return(r0)
                return
            super()._code(uc, pc, size, user)
    h = FixedCopy(image)
    import unicorn as u
    h.uc.mem_map(0x80D000, 0x1000, u.UC_PROT_READ | u.UC_PROT_EXEC)
    expected = bytes((address + 17 * i) & 255 for i in range(length))
    h.uc.mem_write(address, expected)  # Synthetic source; never execute it.
    packet = bytes(protocol.make_packet(0xCD, bytes([1, length]) + address.to_bytes(4, "big")))
    h.uc.mem_write(h.PACKET, packet)
    h.uc.mem_write(0x20BBF0, bytes([state]))
    h.uc.mem_write(0x20A664, b"\0")
    h.uc.mem_write(h.STACK - 128, b"\xA5" * 128)
    h.uc.reg_write(h.a.UC_ARM_REG_R0, h.PACKET)
    h.uc.reg_write(h.a.UC_ARM_REG_SP, h.STACK)
    h.uc.reg_write(h.a.UC_ARM_REG_LR, h.STOP | 1)
    h.uc.emu_start((fwcapacity.BIAS + 0x564A) | 1, 0, count=1000)
    assert h.returned and h.reply == bytes(protocol.make_packet(0xCD, expected))
    assert h.uc.reg_read(h.a.UC_ARM_REG_SP) == h.STACK
    assert bytes(h.uc.mem_read(address, length)) == expected
    assert h.writes == [(0x20A664, 1)]
    assert h.calls == ([0x7ECA, 0x9276] if state in (2, 3) else [])
