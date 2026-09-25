"""Fixed ROM plan: fake transport and selected CD instructions, no hardware."""
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import sys
from types import SimpleNamespace

import pytest

import whip
from probe import rom_read
from tests.test_fwcapacity_read import BASE, V2, ROOT, DescriptorFake
from whip import fwcapacity, fwcapacity_read as cr, fwrom_read as rr, protocol

SYMBOLS = (ROOT / "firmware/research/2026-09-22/rom_symbol_gcc.axf").read_bytes()
ARCHIVE = json.loads((ROOT / "firmware/research/2026-09-23/bank0-descriptor/configuration.json").read_text())


class ROMFake(DescriptorFake):
    def __init__(self, image=V2):
        super().__init__(image)
        self.events = []
        self.reader = rr.ROMTimerReader(self, self.events.append, timeout=0.01, spacing=0)
        self.config[cr.BANK0_DESCRIPTOR_WINDOW[0]] = bytes.fromhex(ARCHIVE["windows"][-1]["data_hex"])
        self.config[rr.UUID_WINDOW[0]] = rr.ROM_UUID
        self.config[rr.TIMER_WINDOW[0]] = bytes(range(rr.TIMER_WINDOW[1]))  # Invented ROM bytes.
        self.timer_reads = self.uuid_reads = 0
        self.timer_fault = self.change = None

    def memory(self, address, length):
        if rr.TIMER_WINDOW[0] <= address < sum(rr.TIMER_WINDOW):
            self.timer_reads += 1
        if rr.UUID_WINDOW[0] <= address < sum(rr.UUID_WINDOW):
            self.uuid_reads += 1
        raw = super().memory(address, length)
        mutate = ((self.change == "uuid_repeat" and address == rr.UUID_WINDOW[0] and self.uuid_reads > 2)
                  or (self.change == "timer_repeat" and address == rr.TIMER_WINDOW[0] and self.timer_reads > 6)
                  or (self.change == "config_after" and self.timer_reads and address == cr.CONFIG_WINDOWS[0][0]))
        if self.change == "idle_after" and self.timer_reads and address == cr.IDLE_WINDOW[0]:
            return b"\x04"
        return bytes([raw[0] ^ 1]) + raw[1:] if mutate else raw

    async def write_gatt_char(self, uuid, packet, response):
        address = int.from_bytes(packet[3:7], "big")
        if rr.TIMER_WINDOW[0] <= address < sum(rr.TIMER_WINDOW) and self.timer_fault:
            self.bad = self.timer_fault
        await super().write_gatt_char(uuid, packet, response)


def collect(f, symbols=SYMBOLS):
    return asyncio.run(rr.collect_rom_timers(f.reader, BASE, V2, symbols, "fake-rom-only"))


def test_fixed_plan_has_exactly_114_reads_no_pointer_following_and_closes():
    f = ROMFake()
    result = collect(f)
    assert len(f.writes) == rr.EXPECTED_TRANSACTIONS == 114
    expected_tail = (list(cr.chunks(*rr.UUID_WINDOW)) * 2
                     + list(cr.chunks(*rr.TIMER_WINDOW)) * 2
                     + [chunk for window in cr.CONFIG_WINDOWS for chunk in cr.chunks(*window)]
                     + [cr.IDLE_WINDOW])
    assert f.writes[91:] == expected_tail
    assert (f.uuid_reads, f.timer_reads) == (4, 12)
    assert result["schema"] == rr.SCHEMA and result["repeated_equal"]
    assert bytes.fromhex(result["timer_code"]["data_hex"]) == bytes(range(72))
    assert result["timer_code"]["sha256"] == hashlib.sha256(bytes(range(72))).hexdigest()
    assert not any(result[k] for k in ("full_image_attestation", "callback_drain_verified",
                                       "recovery_verified", "flash_authorized"))
    assert f.reader.closed and not f.reader.poisoned and f.reader._rom_phase is None
    for a, n in (cr.IDLE_WINDOW, cr.chunks(*rr.TIMER_WINDOW)[0]):
        with pytest.raises(ValueError): asyncio.run(f.reader.read(a, n))
    with pytest.raises(RuntimeError, match="already used"): collect(f)
    assert len(f.writes) == 114


@pytest.mark.parametrize("window", [rr.UUID_WINDOW, rr.TIMER_WINDOW])
def test_new_windows_are_locked_before_prerequisites(window):
    f = ROMFake()
    for chunk in cr.chunks(*window):
        with pytest.raises(ValueError): asyncio.run(f.reader.read(*chunk))
    assert f.writes == []


@pytest.mark.parametrize("address,length", [(0x136BA, 2), (0x13704, 2), (0x136BC, 15),
    (0x136BD, 14), (0x201258, 14), (0x201644, 4), (0x200414, 4), (0x40015000, 1),
    (0x84A198, 14), (0x1000198, 14), (True, 1), (0x136BC, True)])
def test_even_timer_phase_cannot_read_adjacent_rom_ram_keys_mmio_or_banks(address, length):
    f = ROMFake()
    f.reader._rom_phase = "timers"  # Explicit fault injection, not plan entry.
    with pytest.raises(ValueError): asyncio.run(f.reader.read(address, length))
    assert f.writes == []


@pytest.mark.parametrize("bad", ["timeout", "write_timeout", "checksum", "short", "stream", "duplicate"])
def test_timer_transport_fault_closes_and_never_retries(bad):
    f = ROMFake()
    f.timer_fault = bad
    with pytest.raises((RuntimeError, TimeoutError)): collect(f)
    assert len(f.writes) == 96 and f.reader.closed and f.reader.poisoned
    assert f.reader._rom_phase is None and not f.reader._descriptor_phase
    with pytest.raises(RuntimeError): collect(f)
    assert len(f.writes) == 96


@pytest.mark.parametrize("bad", ["symbol_map", "image", "base_identity", "diagnostic", "idle", "ram", "descriptor", "uuid"])
def test_prerequisite_failure_never_reads_timer_code(bad):
    f = ROMFake(BASE if bad == "base_identity" else V2)
    if bad == "image": f.image = V2[:0x21D6] + bytes([V2[0x21D6] ^ 1]) + V2[0x21D7:]
    if bad == "diagnostic": f.image = V2[:0x564A] + bytes([V2[0x564A] ^ 1]) + V2[0x564B:]
    if bad == "idle": f.raw = 4
    if bad in ("ram", "descriptor", "uuid"):
        address = {"ram": cr.CONFIG_WINDOWS[0][0], "descriptor": cr.BANK0_DESCRIPTOR_WINDOW[0],
                   "uuid": rr.UUID_WINDOW[0]}[bad]
        raw = f.config[address]
        f.config[address] = bytes([raw[0] ^ 1]) + raw[1:]
    with pytest.raises((ValueError, RuntimeError)):
        collect(f, SYMBOLS + b"\n" if bad == "symbol_map" else SYMBOLS)
    assert not f.timer_reads and f.reader.closed and f.reader.poisoned
    if bad == "symbol_map": assert not f.writes


@pytest.mark.parametrize("change", ["uuid_repeat", "timer_repeat", "config_after", "idle_after"])
def test_repeated_or_postcondition_change_aborts(change):
    f = ROMFake()
    f.change = change
    with pytest.raises(RuntimeError): collect(f)
    assert f.reader.closed and f.reader.poisoned and len(f.writes) <= 114
    if change == "uuid_repeat": assert not f.timer_reads


def test_wrong_reader_or_local_image_refused_before_transport():
    f = DescriptorFake()
    with pytest.raises(ValueError):
        asyncio.run(rr.collect_rom_timers(f.reader, BASE, V2, SYMBOLS, "fake"))
    assert not f.writes
    f = ROMFake()
    with pytest.raises(ValueError):
        asyncio.run(rr.collect_rom_timers(f.reader, BASE, V2[:-1], SYMBOLS, "fake"))
    assert not f.writes and f.reader.closed


@pytest.mark.parametrize("image", [BASE, V2], ids=["original25hz", "v2"])
@pytest.mark.parametrize("state", [0, 2, 3])
@pytest.mark.parametrize("address,length", cr.chunks(*rr.UUID_WINDOW) + cr.chunks(*rr.TIMER_WINDOW)
                         + cr.chunks(*rr.LITERAL_WINDOW) + cr.chunks(*rr.DEFAULT_WINDOW)
                         + cr.chunks(*rr.HOOK_WINDOW))
def test_actual_cd_instructions_copy_fixed_low_rom_addresses_without_execution(image, state, address, length):
    # Real hash-pinned dispatch/prelude/CD/checksum; synthetic ROM bytes and a
    # bounded memcpy mock. This proves addressing/copy semantics, not physical
    # ROM accessibility, ROM implementation, radio delivery or timer behavior.
    class FixedCopy(fwcapacity.CDReadHarness):
        def _code(self, uc, pc, size, user):
            if pc == 0x3F848:
                r0, r1, r2 = [uc.reg_read(r) for r in (self.a.UC_ARM_REG_R0,
                    self.a.UC_ARM_REG_R1, self.a.UC_ARM_REG_R2)]
                assert (r0, r1, r2) == (self.STACK - 31, address, length)
                uc.mem_write(r0, bytes(uc.mem_read(r1, r2)))
                self._return(r0)
                return
            super()._code(uc, pc, size, user)

    h = FixedCopy(image)
    h.uc.mem_write(rr.TIMER_WINDOW[0], bytes(range(72)))
    # Distinct source bytes make a wrong source/offset observable, including in
    # the separately reviewed follow-up windows. These are NOT captured code.
    h.uc.mem_write(address, bytes((address + i * 17) & 255 for i in range(length)))
    before = bytes(h.uc.mem_read(rr.TIMER_WINDOW[0], rr.TIMER_WINDOW[1]))
    expected = bytes(h.uc.mem_read(address, length))
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
    assert bytes(h.uc.mem_read(rr.TIMER_WINDOW[0], 72)) == before
    assert bytes(h.uc.mem_read(address, length)) == expected
    assert h.writes == [(0x20A664, 1)]  # Existing CD bookkeeping, not source writes.
    assert h.calls == ([0x7ECA, 0x9276] if state in (2, 3) else [])


@pytest.fixture
def transport(monkeypatch):
    f = ROMFake()
    f.connected = f.disconnected = f.notifying = f.stopped_notify = False
    f.is_connected = False
    f.info = dict(name="R02_CC07", hardware="RT02CR_V3.1", firmware="RT02CR_3.12.07_260514",
                  address="fake-device")
    f.fail_disconnect = f.late_traffic = False

    async def find_ring(*, address):
        assert address == "fake-device"
        return SimpleNamespace(name=f.info["name"])

    @asynccontextmanager
    async def connected(device):
        f.connected = f.is_connected = True
        try: yield f
        finally:
            f.disconnected = True
            f.is_connected = f.fail_disconnect

    async def info(client, device):
        return SimpleNamespace(**f.info, as_dict=lambda: dict(f.info))

    async def start_notify(uuid, callback):
        assert uuid == protocol.UART_TX_CHAR_UUID
        f.reader = callback.__self__
        f.reader.spacing, f.reader.timeout = 0, 0.01
        f.notifying = True

    async def stop_notify(uuid):
        assert uuid == protocol.UART_TX_CHAR_UUID
        f.stopped_notify = True
        if f.late_traffic:
            f.reader.notify(None, bytes(protocol.make_packet(0xCD)))

    f.start_notify, f.stop_notify = start_notify, stop_notify
    fake = SimpleNamespace(find_ring=find_ring, connected=connected, read_device_info=info)
    monkeypatch.setitem(sys.modules, "whip.capture", fake)
    monkeypatch.setattr(whip, "capture", fake, raising=False)
    return f


def arguments(tmp_path):
    return SimpleNamespace(address="fake-device", output=tmp_path / "new-rom",
                           confirmed_idle_clients=True)


def test_cli_success_only_after_disconnect_preserves_transcript(transport, tmp_path):
    args = arguments(tmp_path)
    assert asyncio.run(rom_read.run(args)) == 0
    assert transport.disconnected and transport.stopped_notify and not transport.is_connected
    rows = [json.loads(line) for line in (args.output / "transcript.jsonl").read_text().splitlines()]
    assert [r["kind"] for r in rows[-2:]] == ["disconnected", "completed"]
    assert rows[-1]["requests"] == 114 and not rows[-1]["flash_authorized"]
    assert rows[-1]["capture_sha256"] == hashlib.sha256((args.output / "rom-timers.json").read_bytes()).hexdigest()


@pytest.mark.parametrize("bad", ["confirmation", "existing_output", "device", "address", "timeout", "disconnect", "late_traffic"])
def test_cli_failure_never_declares_success_or_retries(transport, tmp_path, bad):
    args = arguments(tmp_path)
    if bad == "confirmation": args.confirmed_idle_clients = False
    if bad == "existing_output": args.output.mkdir()
    if bad == "device": transport.info["hardware"] = "other"
    if bad == "address": transport.info["address"] = "other"
    if bad == "timeout": transport.timer_fault = "timeout"
    if bad == "disconnect": transport.fail_disconnect = True
    if bad == "late_traffic": transport.late_traffic = True
    with pytest.raises((ValueError, RuntimeError, FileExistsError, TimeoutError)):
        asyncio.run(rom_read.run(args))
    assert not (args.output / "rom-timers.json").exists()
    if bad in ("confirmation", "existing_output"):
        assert not transport.connected
    else:
        assert transport.disconnected
        rows = [json.loads(line) for line in (args.output / "transcript.jsonl").read_text().splitlines()]
        assert rows[-1]["kind"] == "aborted" and not rows[-1]["retry"]
        assert rows[-1]["disconnect_confirmed"] is (bad != "disconnect")


PRIOR = (ROOT / "firmware/research/2026-09-23/rom-timers/rom-timers.json").read_bytes()


def install_internal_fixture(f):
    f.config[rr.TIMER_WINDOW[0]] = rr.validate_prior_capture(PRIOR)
    # Deliberately unsafe pointer values: these must be archived as bytes only.
    f.config[rr.LITERAL_WINDOW[0]] = bytes.fromhex("0000004014042000")
    f.config[rr.DEFAULT_WINDOW[0]] = bytes(range(rr.DEFAULT_WINDOW[1]))


class InternalsFake(ROMFake):
    def __init__(self):
        super().__init__()
        self.reader = rr.ROMInternalsReader(self, self.events.append, timeout=0.01, spacing=0)
        install_internal_fixture(self)
        self.internal_reads = {phase: 0 for phase, _ in rr.INTERNAL_WINDOWS}
        self.internal_fault = self.internal_change = None

    def memory(self, address, length):
        raw = super().memory(address, length)
        for phase, (start, size) in rr.INTERNAL_WINDOWS:
            if start <= address < start + size:
                self.internal_reads[phase] += 1
                if (self.internal_change == phase and address == start
                        and self.internal_reads[phase] > len(cr.chunks(start, size))):
                    return bytes([raw[0] ^ 1]) + raw[1:]
        return raw

    async def write_gatt_char(self, uuid, packet, response):
        address = int.from_bytes(packet[3:7], "big")
        if self.internal_fault:
            phase, bad = self.internal_fault
            start, size = dict(rr.INTERNAL_WINDOWS)[phase]
            if start <= address < start + size:
                self.bad = bad
        await super().write_gatt_char(uuid, packet, response)


def collect_internals(f, prior=PRIOR):
    return asyncio.run(rr.collect_rom_internals(f.reader, BASE, V2, SYMBOLS, "fake-internals", prior))


def test_fixed_internal_plan_142_transactions_and_no_pointer_following():
    f = InternalsFake()
    result = collect_internals(f)
    expected = (list(cr.chunks(*rr.UUID_WINDOW)) * 2 + list(cr.chunks(*rr.TIMER_WINDOW)) * 2
                + [c for _, window in rr.INTERNAL_WINDOWS for c in list(cr.chunks(*window)) * 2]
                + [c for w in cr.CONFIG_WINDOWS for c in cr.chunks(*w)] + [cr.IDLE_WINDOW])
    assert len(f.writes) == rr.INTERNAL_TRANSACTIONS == 142
    assert f.writes[91:] == expected
    assert f.internal_reads == {"literals": 2, "defaults": 26}
    assert result["schema"] == rr.INTERNAL_SCHEMA
    for phase, (address, _) in rr.INTERNAL_WINDOWS:
        entry = result["internal_windows"][phase]
        assert entry["address"] == address and bytes.fromhex(entry["data_hex"]) == f.config[address]
        assert entry["sha256"] == hashlib.sha256(f.config[address]).hexdigest()
    assert not any(result[k] for k in ("callback_drain_verified", "recovery_verified", "flash_authorized",
        "pointer_following", "target_execution", "actual_hook_state_read", "complete_implementations_verified"))
    assert f.reader.closed and not f.reader.poisoned
    with pytest.raises(RuntimeError): collect_internals(f)
    assert len(f.writes) == 142


@pytest.mark.parametrize("reader_class", [rr.ROMTimerReader, rr.ROMInternalsReader])
@pytest.mark.parametrize("phase,window", rr.INTERNAL_WINDOWS)
def test_internal_windows_closed_before_prerequisites_and_old_plan_never_admits_them(reader_class, phase, window):
    f = InternalsFake()
    f.reader = reader_class(f, f.events.append, spacing=0)
    if reader_class is rr.ROMTimerReader:
        f.reader._rom_phase = phase
    for chunk in cr.chunks(*window):
        with pytest.raises(ValueError): asyncio.run(f.reader.read(*chunk))
    assert not f.writes


@pytest.mark.parametrize("phase,window", rr.INTERNAL_WINDOWS)
def test_internal_phase_does_not_allow_other_phase_adjacent_bytes_or_pointer_targets(phase, window):
    f = InternalsFake()
    f.reader._rom_phase = phase
    for address, length in ((window[0]-2, 2), (sum(window), 2), (window[0]+1, 4),
                            (0x40000000, 4), (0x200414, 4), (0x201644, 4),
                            cr.chunks(*dict(rr.INTERNAL_WINDOWS)["defaults" if phase == "literals" else "literals"])[0]):
        with pytest.raises(ValueError): asyncio.run(f.reader.read(address, length))
    assert not f.writes


@pytest.mark.parametrize("phase", ["literals", "defaults"])
@pytest.mark.parametrize("bad", ["timeout", "write_timeout", "checksum", "short", "stream", "duplicate"])
def test_internal_transport_fault_aborts_without_retry(phase, bad):
    f = InternalsFake()
    f.internal_fault = phase, bad
    with pytest.raises((RuntimeError, TimeoutError)): collect_internals(f)
    assert len(f.writes) == (108 if phase == "literals" else 110)
    assert f.reader.closed and f.reader.poisoned and f.reader._rom_phase is None
    with pytest.raises(RuntimeError): collect_internals(f)


@pytest.mark.parametrize("bad", ["prior", "missing_prior", "wrappers", "literals", "defaults", "config_after", "idle_after"])
def test_internal_mismatches_fail_closed(bad):
    f = InternalsFake()
    prior = PRIOR + b"\n" if bad == "prior" else PRIOR
    if bad == "missing_prior": prior = None
    if bad == "wrappers": f.config[rr.TIMER_WINDOW[0]] = bytes(range(72))
    if bad in ("literals", "defaults"): f.internal_change = bad
    if bad in ("config_after", "idle_after"): f.change = bad
    with pytest.raises((ValueError, RuntimeError)): collect_internals(f, prior)
    assert f.reader.closed and f.reader.poisoned and len(f.writes) <= 142
    if bad in ("prior", "missing_prior", "wrappers"): assert not any(f.internal_reads.values())
    if bad in ("prior", "missing_prior"): assert not f.writes


def test_internal_cli_success_has_distinct_capture_and_budget(transport, tmp_path):
    install_internal_fixture(transport)
    args = arguments(tmp_path)
    args.timer_internals = True
    assert asyncio.run(rom_read.run(args)) == 0
    assert not transport.is_connected and transport.disconnected
    rows = [json.loads(s) for s in (args.output / "transcript.jsonl").read_text().splitlines()]
    assert rows[0]["plan"] == "rom-timer-internals-v1" and rows[0]["max_transactions"] == 142
    assert rows[-1]["requests"] == 142 and rows[-1]["additional_rom_bytes"] == 180
    assert not (args.output / "rom-timers.json").exists()
    assert json.loads((args.output / "rom-timer-internals.json").read_text())["schema"] == rr.INTERNAL_SCHEMA


@pytest.mark.parametrize("bad", ["confirmation", "existing_output", "device", "address", "timeout", "disconnect", "late_traffic"])
def test_internal_cli_failure_never_declares_success(transport, tmp_path, bad):
    install_internal_fixture(transport)
    args = arguments(tmp_path)
    args.timer_internals = True
    if bad == "confirmation": args.confirmed_idle_clients = False
    if bad == "existing_output": args.output.mkdir()
    if bad == "device": transport.info["hardware"] = "other"
    if bad == "address": transport.info["address"] = "other"
    if bad == "timeout": transport.timer_fault = "timeout"
    if bad == "disconnect": transport.fail_disconnect = True
    if bad == "late_traffic": transport.late_traffic = True
    with pytest.raises((ValueError, RuntimeError, FileExistsError, TimeoutError)):
        asyncio.run(rom_read.run(args))
    assert not (args.output / "rom-timer-internals.json").exists()
    assert not transport.connected if bad in ("confirmation", "existing_output") else transport.disconnected


PRIOR_INTERNALS = (ROOT / "firmware/research/2026-09-23/rom-timer-internals/rom-timer-internals.json").read_bytes()


def install_hook_fixture(f):
    install_internal_fixture(f)
    actual = rr.validate_internal_capture(PRIOR_INTERNALS)
    for phase, window in rr.INTERNAL_WINDOWS: f.config[window[0]] = actual[phase]
    # Deliberately invalid targets are data only; neither follows nor calls them.
    f.config[rr.HOOK_WINDOW[0]] = bytes.fromhex("0100004001042000")


class HookFake(InternalsFake):
    def __init__(self):
        super().__init__()
        install_hook_fixture(self)
        self.reader = rr.ROMHookReader(self, self.events.append, timeout=0.01, spacing=0)
        self.hook_reads = 0
        self.hook_fault = None
        self.change_hook = False

    def memory(self, address, length):
        raw = super().memory(address, length)
        if address == rr.HOOK_WINDOW[0]:
            self.hook_reads += 1
            if self.change_hook and self.hook_reads > 1:
                return bytes([raw[0] ^ 1]) + raw[1:]
        return raw

    async def write_gatt_char(self, uuid, packet, response):
        if int.from_bytes(packet[3:7], "big") == rr.HOOK_WINDOW[0] and self.hook_fault:
            self.bad = self.hook_fault
        await super().write_gatt_char(uuid, packet, response)


def collect_hooks(f, prior=PRIOR_INTERNALS):
    return asyncio.run(rr.collect_rom_hooks(f.reader, BASE, V2, SYMBOLS, "fake-hooks", PRIOR, prior))


def test_hook_plan_144_reads_and_untrusted_pointer_contents_never_followed():
    f = HookFake()
    result = collect_hooks(f)
    assert len(f.writes) == rr.HOOK_TRANSACTIONS == 144
    assert f.writes[135:137] == [rr.HOOK_WINDOW] * 2 and f.hook_reads == 2
    assert result["schema"] == rr.HOOK_SCHEMA and result["actual_hook_state_read"]
    assert bytes.fromhex(result["hook_slots"]["data_hex"]) == f.config[rr.HOOK_WINDOW[0]]
    assert not any(result[k] for k in ("callback_drain_verified", "flash_authorized", "recovery_verified",
                                      "pointer_following", "target_execution"))
    assert f.reader.closed and not f.reader.poisoned
    with pytest.raises(RuntimeError): collect_hooks(f)


@pytest.mark.parametrize("reader_class", [rr.ROMTimerReader, rr.ROMInternalsReader, rr.ROMHookReader])
def test_hook_slots_require_separate_reader_and_closed_phase(reader_class):
    f = HookFake()
    f.reader = reader_class(f, lambda _: None)
    if reader_class is not rr.ROMHookReader: f.reader._rom_phase = "hook_slots"
    with pytest.raises(ValueError): asyncio.run(f.reader.read(*rr.HOOK_WINDOW))
    assert not f.writes


@pytest.mark.parametrize("window", [(0x20164C, 4), (0x201658, 4), (0x201650, 4), (0x201654, 4),
                                     (0x40000001, 4), (0x200401, 4), rr.LITERAL_WINDOW, (True, 8)])
def test_hook_phase_rejects_adjacent_partial_and_returned_pointer_targets(window):
    f = HookFake()
    f.reader._rom_phase = "hook_slots"
    with pytest.raises(ValueError): asyncio.run(f.reader.read(*window))
    assert not f.writes


@pytest.mark.parametrize("bad", ["timeout", "write_timeout", "checksum", "short", "stream", "duplicate"])
def test_hook_fault_stops_after_one_request_no_retry(bad):
    f = HookFake()
    f.hook_fault = bad
    with pytest.raises((RuntimeError, TimeoutError)): collect_hooks(f)
    assert len(f.writes) == 136 and f.reader.poisoned and f.reader.closed
    with pytest.raises(RuntimeError): collect_hooks(f)


@pytest.mark.parametrize("bad", ["prior", "missing_prior", "literals", "defaults", "repeat", "config_after", "idle_after"])
def test_hook_prerequisite_or_postcondition_failure(bad):
    f = HookFake()
    prior = (None if bad == "missing_prior" else (PRIOR_INTERNALS + b"\n" if bad == "prior" else PRIOR_INTERNALS))
    if bad in ("literals", "defaults"):
        address = dict(rr.INTERNAL_WINDOWS)[bad][0]
        raw = f.config[address]
        f.config[address] = bytes([raw[0] ^ 1]) + raw[1:]
    if bad == "repeat": f.change_hook = True
    if bad in ("config_after", "idle_after"): f.change = bad
    with pytest.raises((ValueError, RuntimeError)): collect_hooks(f, prior)
    assert f.reader.closed and f.reader.poisoned
    if bad in ("prior", "missing_prior", "literals", "defaults"): assert not f.hook_reads


def test_hook_cli_success_separate_capture(transport, tmp_path):
    install_hook_fixture(transport)
    args = arguments(tmp_path)
    args.timer_hook_state = True
    assert asyncio.run(rom_read.run(args)) == 0
    assert transport.disconnected and not transport.is_connected
    rows = [json.loads(s) for s in (args.output / "transcript.jsonl").read_text().splitlines()]
    assert rows[0]["plan"] == "rom-timer-hooks-v1" and rows[-1]["requests"] == 144
    assert rows[-1]["hook_slot_bytes"] == 8
    assert json.loads((args.output / "rom-timer-hooks.json").read_text())["schema"] == rr.HOOK_SCHEMA
    assert not (args.output / "rom-timer-internals.json").exists()


@pytest.mark.parametrize("bad", ["confirmation", "existing_output", "device", "address", "timeout", "disconnect", "late_traffic"])
def test_hook_cli_failure_never_declares_success(transport, tmp_path, bad):
    install_hook_fixture(transport)
    args = arguments(tmp_path)
    args.timer_hook_state = True
    if bad == "confirmation": args.confirmed_idle_clients = False
    if bad == "existing_output": args.output.mkdir()
    if bad == "device": transport.info["hardware"] = "other"
    if bad == "address": transport.info["address"] = "other"
    if bad == "timeout": transport.timer_fault = "timeout"
    if bad == "disconnect": transport.fail_disconnect = True
    if bad == "late_traffic": transport.late_traffic = True
    with pytest.raises((ValueError, RuntimeError, FileExistsError, TimeoutError)):
        asyncio.run(rom_read.run(args))
    assert not (args.output / "rom-timer-hooks.json").exists()
    assert not transport.connected if bad in ("confirmation", "existing_output") else transport.disconnected
