"""Fixed consolidated ROM DATA plan, fake radio only; no real connection."""
import asyncio
import json

import pytest

from probe import rom_read
from tests import test_fwrom_read as rt
from tests.test_fwrom_read import BASE, V2, SYMBOLS, ROMFake, arguments, transport
from whip import fwrom_integration as ir, fwcapacity_read as cr, fwrom_read as rr


class IntegrationFake(ROMFake):
    def __init__(self):
        super().__init__()
        self.reader = ir.IntegrationReader(self, self.events.append, timeout=0.01, spacing=0)
        self.code_reads = 0
        self.fault = self.code_change = None
        for _, a, n in ir.WINDOWS:
            self.config[a] = bytes((a + i * 17) & 255 for i in range(n))  # Synthetic, not captured ROM.

    def memory(self, a, n):
        raw = super().memory(a, n)
        for name, start, size in ir.WINDOWS:
            if start <= a < start + size:
                self.code_reads += 1
                if self.code_change == name and a == start:
                    count = sum(address == start for address, _ in self.writes)
                    if count == 2: return bytes([raw[0] ^ 1]) + raw[1:]
        if self.code_reads and self.code_change == "idle_after" and a == cr.IDLE_WINDOW[0]: return b"\x04"
        if self.code_reads and self.code_change == "config_after" and a == cr.CONFIG_WINDOWS[0][0]:
            return bytes([raw[0] ^ 1]) + raw[1:]
        return raw

    async def write_gatt_char(self, uuid, packet, response):
        if self.fault and self.reader._code_phase == self.fault[0]: self.bad = self.fault[1]
        await super().write_gatt_char(uuid, packet, response)


def collect(f, symbols=SYMBOLS):
    return asyncio.run(ir.collect(f.reader, BASE, V2, symbols, "fake-only"))


def test_exact_fixed_code_bounds_order_and_one_use():
    f = IntegrationFake()
    result = collect(f)
    assert ir.TOTAL_BYTES == 6076 and ir.EXPECTED_TRANSACTIONS == 974
    assert len(f.writes) == 974
    assert f.writes[91:] == (list(cr.chunks(*rr.UUID_WINDOW)) * 2 +
        [chunk for _, a, n in ir.WINDOWS for chunk in cr.chunks(a, n) * 2] +
        [chunk for w in cr.CONFIG_WINDOWS for chunk in cr.chunks(*w)] + [cr.IDLE_WINDOW])
    assert sum(len(bytes.fromhex(w["data_hex"])) for w in result["windows"].values()) == 6076
    assert result["repeated_equal"] and result["schema"] == ir.SCHEMA
    assert not any(result[k] for k in ("keys_read", "pointer_following", "target_execution",
                                      "full_image_attestation", "recovery_verified", "flash_authorized"))
    assert f.reader.closed and not f.reader.poisoned
    with pytest.raises(RuntimeError): collect(f)
    with pytest.raises(ValueError): asyncio.run(f.reader.read(*cr.IDLE_WINDOW))
    assert len(f.writes) == 974


def test_only_current_explicit_code_phase_can_read_its_chunks():
    f = IntegrationFake()
    for phase in [None, "identifier", *(name for name, _, _ in ir.WINDOWS)]:
        f.reader._code_phase = phase
        for name, a, n in ir.WINDOWS:
            if phase == name: continue
            for chunk in cr.chunks(a, n):
                with pytest.raises(ValueError): asyncio.run(f.reader.read(*chunk))
        for a, n in ((0x200414, 4), (0x40015000, 1), (0x80D034, 14), (0, 14),
                     (0x53A4, 1), (0x81A0, 2), (0x8C72, 2), (0x10FB8, 2), (0x111A6, 2)):
            with pytest.raises(ValueError): asyncio.run(f.reader.read(a, n))
    assert not f.writes


@pytest.mark.parametrize("bad", ["symbols", "identity", "diagnostic", "base", "idle", "config", "descriptor", "uuid"])
def test_prerequisite_failures_prevent_all_new_rom_reads(bad):
    f = IntegrationFake()
    if bad == "base": f.image = BASE
    if bad in ("identity", "diagnostic"):
        i = 0x21D6 if bad == "identity" else 0x564A
        f.image = V2[:i] + bytes([V2[i] ^ 1]) + V2[i + 1:]
    if bad == "idle": f.raw = 4
    if bad in ("config", "descriptor", "uuid"):
        a = {"config": cr.CONFIG_WINDOWS[0][0], "descriptor": cr.BANK0_DESCRIPTOR_WINDOW[0], "uuid": rr.UUID_WINDOW[0]}[bad]
        raw = f.config[a]
        f.config[a] = bytes([raw[0] ^ 1]) + raw[1:]
    with pytest.raises((ValueError, RuntimeError)): collect(f, SYMBOLS + b"\n" if bad == "symbols" else SYMBOLS)
    assert not f.code_reads and f.reader.closed and f.reader.poisoned
    if bad == "symbols": assert not f.writes


@pytest.mark.parametrize("name", [name for name, _, _ in ir.WINDOWS])
@pytest.mark.parametrize("fault", ["timeout", "write_timeout", "checksum", "short", "stream", "duplicate"])
def test_each_phase_fault_is_terminal_and_never_retries(name, fault):
    f = IntegrationFake()
    f.fault = name, fault
    with pytest.raises((RuntimeError, TimeoutError)): collect(f)
    before = len(f.writes)
    assert f.reader.closed and f.reader.poisoned and f.reader._code_phase is None
    with pytest.raises(RuntimeError): collect(f)
    assert len(f.writes) == before < 974


@pytest.mark.parametrize("change", [*(name for name, _, _ in ir.WINDOWS), "config_after", "idle_after"])
def test_changed_code_repeat_or_postcheck_aborts(change):
    f = IntegrationFake()
    f.code_change = change
    with pytest.raises(RuntimeError): collect(f)
    assert f.reader.closed and f.reader.poisoned and len(f.writes) <= 974


@pytest.mark.parametrize("failure", [None, "confirmation", "conflict", "device", "disconnect", "late_traffic"])
def test_cli_budget_evidence_and_disconnect(transport, tmp_path, failure):
    args = arguments(tmp_path)
    args.integration_code = True
    for _, a, n in ir.WINDOWS: transport.config[a] = bytes((i * 17) & 255 for i in range(n))
    if failure == "confirmation": args.confirmed_idle_clients = False
    if failure == "conflict": args.boot_reference = True
    if failure == "device": transport.info["hardware"] = "other"
    if failure == "disconnect": transport.fail_disconnect = True
    if failure == "late_traffic": transport.late_traffic = True
    if failure:
        with pytest.raises((ValueError, RuntimeError)): asyncio.run(rom_read.run(args))
        assert not (args.output / "rom-integration.json").exists()
        if failure in ("confirmation", "conflict"): assert not transport.connected
        else:
            assert transport.disconnected
            rows = [json.loads(s) for s in (args.output / "transcript.jsonl").read_text().splitlines()]
            assert rows[-1]["kind"] == "aborted" and not rows[-1]["retry"]
            assert rows[-1]["disconnect_confirmed"] is (failure != "disconnect")
    else:
        assert asyncio.run(rom_read.run(args)) == 0
        assert transport.disconnected and not transport.is_connected
        rows = [json.loads(s) for s in (args.output / "transcript.jsonl").read_text().splitlines()]
        assert rows[-2] == {"kind": "disconnected", "confirmed": True}
        assert rows[-1]["requests"] == 974 and rows[-1]["rom_bytes"] == 6076


@pytest.mark.parametrize("window", ir.WINDOWS)
@pytest.mark.parametrize("image", [BASE, V2], ids=["original25hz", "v2"])
@pytest.mark.parametrize("state", [0, 2, 3])
def test_actual_cd_boundaries_for_every_new_window(window, image, state):
    _, a, n = window
    for address, length in (cr.chunks(a, n)[0], cr.chunks(a, n)[-1]):
        rt.test_actual_cd_instructions_copy_fixed_low_rom_addresses_without_execution(image, state, address, length)
