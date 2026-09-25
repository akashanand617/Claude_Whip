"""RAM-ownership read plan: fake transport only, never a real device."""
import asyncio
import json
import struct

import pytest

from tests.test_fwcapacity_read import BASE, V2, ROOT, DescriptorFake
from whip import fwcapacity_read as cr, fwram, fwram_read as mr, fwrom_read as rr, protocol

SYMBOLS = (ROOT / "firmware/research/2026-09-22/rom_symbol_gcc.axf").read_bytes()
ARCHIVE = json.loads((ROOT / "firmware/research/2026-09-23/bank0-descriptor/configuration.json").read_text())
GAP_SECRET = bytes((7 * i + 3) & 0xFF or 1 for i in range(fwram.GAP_WINDOW_V2[1]))  # invented


class RAMFake(DescriptorFake):
    def __init__(self):
        super().__init__(V2)
        self.events = []
        self.reader = mr.RAMOwnershipReader(self, self.events.append, timeout=0.01, spacing=0)
        self.config[cr.BANK0_DESCRIPTOR_WINDOW[0]] = bytes.fromhex(ARCHIVE["windows"][-1]["data_hex"])
        self.config[rr.UUID_WINDOW[0]] = rr.ROM_UUID
        # Invented fixtures, not ring measurements.
        self.config[mr.PRE_MAIN_SLOT_WINDOW[0]] = struct.pack("<I", mr.EXPECTED_PRE_MAIN)
        self.config[fwram.HEAP_WINDOW[0]] = struct.pack("<15I", 5000, 3000, 4000, 2000,
                                                        29000, 14000, *([0] * 9))
        self.config[fwram.HEAP_BASE_WINDOW[0]] = struct.pack("<II", 0, 0x80000040)
        self.config[fwram.GAP_WINDOW_V2[0]] = GAP_SECRET
        self.mutate_gap_after_sleep = False
        self.slept = False

    def memory(self, address, length):
        raw = super().memory(address, length)
        if self.mutate_gap_after_sleep and self.slept and address == fwram.GAP_WINDOW_V2[0]:
            raw = bytes([raw[0] ^ 0xFF]) + raw[1:]
        return raw

    async def sleep(self, seconds):
        assert seconds == mr.GAP_INTERVAL_S
        self.slept = True


def run(f, **kwargs):
    return asyncio.run(mr.collect(f.reader, BASE, V2, SYMBOLS, "fake-ram-only", sleep=f.sleep, **kwargs))


def test_exact_budget_order_and_closure():
    f = RAMFake()
    result = run(f)
    assert len(f.writes) == mr.EXPECTED_TRANSACTIONS == 268
    tail = f.writes[mr.PREREQUISITE_TRANSACTIONS:]
    order = list(mr.WINDOWS)
    expected = ([c for n in order for c in cr.chunks(*mr.WINDOWS[n])]
                + [c for n in reversed(order) for c in cr.chunks(*mr.WINDOWS[n])]
                + [c for w in cr.CONFIG_WINDOWS for c in cr.chunks(*w)] + [cr.IDLE_WINDOW])
    assert tail == expected
    assert f.reader.closed and not f.reader.poisoned
    assert result["pre_main_slot_matches_image"] is True
    assert result["heap_decoded"][0]["data_heap_peak_used"] == 29000 - 4000
    assert result["heap_base_signature"][0]["allocated_header_shape"] is True
    assert result["gap"]["comparison"]["writer_proven"] is False
    assert not result["flash_authorized"] and not result["allocation_approved"]


def test_no_raw_window_overlaps_the_gap():
    gap = range(*[fwram.GAP_WINDOW_V2[0], sum(fwram.GAP_WINDOW_V2)])
    for name, (address, length) in mr.WINDOWS.items():
        if name != "gap":
            assert not set(range(address, address + length)) & set(gap), name


def test_gap_bytes_never_stored_or_logged():
    f = RAMFake()
    result = run(f)
    text = json.dumps(result) + json.dumps(f.events)
    for chunk in (GAP_SECRET[i:i + 14] for i in range(0, len(GAP_SECRET), 14)):
        assert chunk.hex() not in text
    gap_replies = [e for e in f.events if e["kind"] == "reply" and fwram.GAP_WINDOW_V2[0] <= e["address"]
                   < sum(fwram.GAP_WINDOW_V2)]
    assert len(gap_replies) == 2 * len(cr.chunks(*fwram.GAP_WINDOW_V2))
    assert all(e["packet"] is None and e["redacted"] for e in gap_replies)


def test_gap_change_is_reported_as_writer():
    f = RAMFake()
    f.mutate_gap_after_sleep = True
    comparison = run(f)["gap"]["comparison"]
    assert comparison["writer_proven"] and comparison["changed_block_offsets"] == [0]


def test_windows_closed_before_and_after_plan():
    f = RAMFake()
    for window in mr.WINDOWS.values():
        with pytest.raises(ValueError):
            asyncio.run(f.reader.read(*cr.chunks(*window)[0]))
    run(f)
    with pytest.raises(ValueError):
        asyncio.run(f.reader.read(*cr.chunks(*fwram.HEAP_WINDOW)[0]))
    with pytest.raises(RuntimeError):
        run(f)


def test_foreign_packet_during_wait_aborts_without_retry():
    f = RAMFake()

    async def noisy(seconds):
        f.reader.notify(None, bytes(protocol.make_packet(0x73, b"\x01")))
    with pytest.raises(RuntimeError):
        asyncio.run(mr.collect(f.reader, BASE, V2, SYMBOLS, "fake", sleep=noisy))
    assert f.reader.poisoned and f.reader.closed
    # No request after the poisoned wait: exactly the prerequisites + first pass.
    first_pass = sum(len(cr.chunks(*w)) for w in mr.WINDOWS.values())
    assert len(f.writes) == mr.PREREQUISITE_TRANSACTIONS + first_pass


def test_unexpected_slot_value_is_recorded_not_followed():
    f = RAMFake()
    f.config[mr.PRE_MAIN_SLOT_WINDOW[0]] = struct.pack("<I", 0x20E735)
    result = run(f)
    assert result["pre_main_slot_matches_image"] is False
    assert not any(a == 0x20E734 for a, _ in f.writes)


def test_wrong_rom_identifier_stops_before_ram_windows():
    f = RAMFake()
    f.config[rr.UUID_WINDOW[0]] = bytes(16)
    with pytest.raises(RuntimeError, match="ROM identifier"):
        run(f)
    assert not any(any(a == w[0] for w in mr.WINDOWS.values()) for a, _ in f.writes)


# --- Entry point with a fake BLE capture module (never a real device) ---
import functools
import hashlib
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace

import whip
from probe import ram_read


@pytest.fixture
def transport(monkeypatch):
    f = RAMFake()
    f.is_connected = f.disconnected = f.stopped_notify = False
    f.info = dict(name="R02_CC07", hardware="RT02CR_V3.1", firmware="RT02CR_3.12.07_260514",
                  address="fake-device")
    f.fail_disconnect = False

    async def find_ring(*, address, timeout):
        assert address == "fake-device" and timeout == 60.0
        return SimpleNamespace(name=f.info["name"])

    @asynccontextmanager
    async def connected(device):
        f.is_connected = True
        try: yield f
        finally:
            f.disconnected = True
            f.is_connected = f.fail_disconnect

    async def info(client, device):
        return SimpleNamespace(**f.info, as_dict=lambda: dict(f.info))

    async def start_notify(uuid, callback):
        f.reader = callback.__self__
        f.reader.spacing, f.reader.timeout = 0, 0.01

    async def stop_notify(uuid):
        f.stopped_notify = True

    f.start_notify, f.stop_notify = start_notify, stop_notify
    fake = SimpleNamespace(find_ring=find_ring, connected=connected, read_device_info=info)
    monkeypatch.setitem(sys.modules, "whip.capture", fake)
    monkeypatch.setattr(whip, "capture", fake, raising=False)
    monkeypatch.setattr(mr, "collect", functools.partial(mr.collect, sleep=f.sleep))
    return f


def arguments(tmp_path):
    return SimpleNamespace(address="fake-device", output=tmp_path / "new-ram", confirmed_idle_clients=True)


def test_cli_success_only_after_verified_disconnect(transport, tmp_path):
    args = arguments(tmp_path)
    assert asyncio.run(ram_read.run(args)) == 0
    assert transport.disconnected and transport.stopped_notify and not transport.is_connected
    rows = [json.loads(line) for line in (args.output / "transcript.jsonl").read_text().splitlines()]
    assert rows[0]["flashing"] is False and rows[0]["gap_bytes_logged"] is False
    assert [r["kind"] for r in rows[-2:]] == ["disconnected", "completed"]
    assert rows[-1]["requests"] == mr.EXPECTED_TRANSACTIONS and not rows[-1]["flash_authorized"]
    saved = (args.output / "ram-ownership.json").read_bytes()
    assert rows[-1]["capture_sha256"] == hashlib.sha256(saved).hexdigest()
    text = saved.decode() + (args.output / "transcript.jsonl").read_text()
    assert all(GAP_SECRET[i:i + 14].hex() not in text for i in range(0, len(GAP_SECRET), 14))


@pytest.mark.parametrize("bad", ["confirmation", "device", "firmware", "disconnect"])
def test_cli_failure_never_declares_success(transport, tmp_path, bad):
    args = arguments(tmp_path)
    if bad == "confirmation": args.confirmed_idle_clients = False
    if bad == "device": transport.info["hardware"] = "other"
    if bad == "firmware": transport.info["firmware"] = "RT02CR_3.12.02_260824"
    if bad == "disconnect": transport.fail_disconnect = True
    with pytest.raises((RuntimeError, ValueError)):
        asyncio.run(ram_read.run(args))
    assert not (args.output / "ram-ownership.json").exists()
    if bad in ("device", "firmware"):
        assert transport.writes == []


# --- Exact offline replay of the 2026-09-24 device capture (no device) ---
ARCHIVE_DIR = ROOT / "firmware/research/2026-09-24/ram-ownership"
CAPTURE_SHA = "bb16aaecd2c2ae30cb110521b3f754c4bb44b2065dbb00cf27ca86ecaca65473"
TRANSCRIPT_SHA = "d59d2ee3eadc60081733239ceacd04312902220a2aaed7c74b75b941ae68472a"


def _archive():
    raw = (ARCHIVE_DIR / "ram-ownership.json").read_bytes()
    log = (ARCHIVE_DIR / "transcript.jsonl").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == CAPTURE_SHA
    assert hashlib.sha256(log).hexdigest() == TRANSCRIPT_SHA
    return json.loads(raw), [json.loads(line) for line in log.decode().splitlines()]


def test_archive_transcript_is_exact_plan_with_verified_disconnect():
    capture, rows = _archive()
    kinds = [r["kind"] for r in rows]
    assert kinds[0] == "header" and rows[0]["flashing"] is False
    assert kinds[-2:] == ["disconnected", "completed"] and rows[-1]["requests"] == 268
    requests = [r for r in rows if r["kind"] == "request"]
    replies = [r for r in rows if r["kind"] == "reply"]
    assert len(requests) == len(replies) == mr.EXPECTED_TRANSACTIONS
    assert [(r["address"], r["length"]) for r in requests] == [(r["address"], r["length"]) for r in replies]
    assert "unexpected_notification" not in kinds and "aborted" not in kinds
    for r in replies:
        if r.get("redacted"):
            assert r["packet"] is None and fwram.GAP_WINDOW_V2[0] <= r["address"] < sum(fwram.GAP_WINDOW_V2)
        else:
            p = bytes.fromhex(r["packet"])
            assert p[0] == 0xCD and len(p) == 16 and protocol.checksum(p[:-1]) == p[-1]
    assert sum(bool(r.get("redacted")) for r in replies) == 2 * len(cr.chunks(*fwram.GAP_WINDOW_V2))
    assert capture["gap"]["raw_stored"] is False


def test_archive_windows_replay_from_transcript_and_decode():
    capture, rows = _archive()
    replies = [r for r in rows if r["kind"] == "reply" and not r.get("redacted")]

    def rebuild(window, occurrence):
        chunks = cr.chunks(*window)
        got = [r for r in replies if (r["address"], r["length"]) in set(chunks)]
        per = len(chunks)
        part = got[occurrence * per:(occurrence + 1) * per]
        return b"".join(bytes.fromhex(r["packet"])[1:1 + r["length"]] for r in part)

    for key, window in (("pre_main_slot", mr.PRE_MAIN_SLOT_WINDOW), ("heap_window", fwram.HEAP_WINDOW),
                        ("heap_base_window", fwram.HEAP_BASE_WINDOW)):
        for i in (0, 1):
            assert rebuild(window, i).hex() == capture[key][i]["data_hex"]
    heap = fwram.decode_heap_window(bytes.fromhex(capture["heap_window"][0]["data_hex"]))
    assert (heap["total"], heap["free"], heap["minimum_ever_free"]) == ([29688, 14440], [264, 3680], [104, 3680])
    assert heap["total"] == [0x7400 - 8, 0x3870 - 8]
    # 264 includes the (assumed) block header; +8 is the heap end marker.
    assert heap["start_list_words"][0] == 0x215EF0 and 0x215EF0 + 264 + 8 == fwram.VENDOR_DATA_RAM[1]
    base = fwram.heap_base_signature(bytes.fromhex(capture["heap_base_window"][0]["data_hex"]))
    assert base["allocated_header_shape"] and base["header_size_word"] == 0x80000058
    assert capture["pre_main_slot_matches_image"] is True
    comparison = fwram.compare_gap_digests(capture["gap"]["first"], capture["gap"]["second"])
    assert comparison == capture["gap"]["comparison"]
    assert comparison["writer_proven"] is False and comparison["unused_proven"] is False
    assert comparison["zero_blocks"] == 0 and len(capture["gap"]["second"]) == 67


# --- Follow-up plan (fake transport; the real prior capture is the baseline) ---
VECTORS = struct.pack("<16I", 0x203800, 0x1235, *range(0x301, 0x301 + 28, 2))  # invented


class FollowupFake(RAMFake):
    def __init__(self):
        super().__init__()
        self.events = []
        self.reader = mr.RAMFollowupReader(self, self.events.append, timeout=0.01, spacing=0)
        self.config[mr.ROM_VECTOR_WINDOW[0]] = VECTORS


def followup(f, prior=None):
    prior = prior if prior is not None else (ARCHIVE_DIR / "ram-ownership.json").read_bytes()
    return asyncio.run(mr.collect_followup(f.reader, BASE, V2, SYMBOLS, "fake-followup", prior))


def test_followup_exact_budget_and_vectors_not_followed():
    f = FollowupFake()
    result = followup(f)
    assert len(f.writes) == mr.FOLLOWUP_TRANSACTIONS == 274
    tail = f.writes[mr.PREREQUISITE_TRANSACTIONS:]
    one = [c for w in mr.FOLLOWUP_WINDOWS.values() for c in cr.chunks(*w)]
    assert tail == one + one + [c for w in cr.CONFIG_WINDOWS for c in cr.chunks(*w)] + [cr.IDLE_WINDOW]
    vec = result["rom_vectors_decoded"]
    assert (vec["initial_sp"], vec["reset"], vec["reset_in_rom"], vec["followed"]) == (0x203800, 0x1235, True, False)
    assert not any(a == 0x1234 for a, _ in f.writes)
    assert result["rom_vectors_repeated_equal"] and f.reader.closed and not f.reader.poisoned


def test_followup_compares_gap_with_prior_and_never_stores_it():
    f = FollowupFake()
    result = followup(f)
    assert result["gap"]["within_session"]["writer_proven"] is False
    assert result["gap"]["versus_prior_session"]["writer_proven"] is True   # invented bytes differ
    text = json.dumps(result) + json.dumps(f.events)
    assert all(GAP_SECRET[i:i + 14].hex() not in text for i in range(0, len(GAP_SECRET), 14))


def test_followup_refuses_unreviewed_prior_and_closed_windows():
    f = FollowupFake()
    with pytest.raises(ValueError, match="prior"):
        followup(f, prior=b"{}")
    assert f.writes == []
    g = FollowupFake()
    with pytest.raises(ValueError):
        asyncio.run(g.reader.read(*cr.chunks(*mr.ROM_VECTOR_WINDOW)[0]))


def test_cli_followup_success_after_verified_disconnect(transport, tmp_path):
    transport.config[mr.ROM_VECTOR_WINDOW[0]] = VECTORS
    args = arguments(tmp_path)
    args.followup = True
    assert asyncio.run(ram_read.run(args)) == 0
    rows = [json.loads(line) for line in (args.output / "transcript.jsonl").read_text().splitlines()]
    assert rows[0]["plan"] == "ram-ownership-followup-v1" and rows[0]["max_transactions"] == 274
    assert [r["kind"] for r in rows[-2:]] == ["disconnected", "completed"] and rows[-1]["requests"] == 274
    assert (args.output / "ram-ownership-followup.json").exists()


FOLLOWUP_DIR = ROOT / "firmware/research/2026-09-24/ram-ownership-followup"


def test_followup_archive_replay_retention_and_vectors():
    raw = (FOLLOWUP_DIR / "ram-ownership-followup.json").read_bytes()
    log = (FOLLOWUP_DIR / "transcript.jsonl").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "f038f9ad7e716617d8e5ac82867d1760cbe4ca77cc7a28de71dfac42973a681f"
    assert hashlib.sha256(log).hexdigest() == "2230112b8575d2b5eb8d1b1369142cab4c7a7e09c9ee0fd3d9a28b49b444d286"
    capture = json.loads(raw)
    rows = [json.loads(line) for line in log.decode().splitlines()]
    assert [r["kind"] for r in rows[-2:]] == ["disconnected", "completed"] and rows[-1]["requests"] == 274
    assert "unexpected_notification" not in [r["kind"] for r in rows]
    assert capture["prior_capture_sha256"] == mr.PRIOR_CAPTURE_SHA256
    prior = json.loads((ARCHIVE_DIR / "ram-ownership.json").read_bytes())
    assert rows[0]["wall"] - json.loads((ARCHIVE_DIR / "transcript.jsonl").read_text().splitlines()[0])["wall"] > 4 * 3600
    for reading in capture["gap"]["reads"]:
        assert fwram.compare_gap_digests(prior["gap"]["second"], reading)["changed_block_offsets"] == []
    v = mr.decode_vectors(bytes.fromhex(capture["rom_vectors"][0]["data_hex"]))
    assert (v["initial_sp"], v["reset"]) == (0x203800, fwram.ROM_RESET_HANDLER | 1)
    assert fwram.ROM_WINDOW[0] <= fwram.ROM_RESET_HANDLER < sum(fwram.ROM_WINDOW)
    assert capture["heap_decoded"][0]["minimum_ever_free"] == [104, 3680]


# --- Resume-pointer plan (fake transport) ---
HOOKS = struct.pack("<4I", 0x8D01, 0, 0xD2A1, 0)   # invented pointers
PRE_BOOT = struct.pack("<I", 0x3001)


class ResumeFake(RAMFake):
    def __init__(self):
        super().__init__()
        self.events = []
        self.reader = mr.RAMResumeReader(self, self.events.append, timeout=0.01, spacing=0)
        self.config[mr.BOOT_HOOK_WINDOW[0]] = HOOKS
        self.config[mr.PRE_BOOT_HOOK_WINDOW[0]] = PRE_BOOT


def test_resume_pointer_plan_budget_and_no_following():
    f = ResumeFake()
    result = asyncio.run(mr.collect_resume_pointers(f.reader, BASE, V2, SYMBOLS, "fake-resume"))
    assert len(f.writes) == mr.RESUME_TRANSACTIONS == 108
    one = [c for w in mr.RESUME_WINDOWS.values() for c in cr.chunks(*w)]
    assert f.writes[mr.PREREQUISITE_TRANSACTIONS:] == one + one + [
        c for w in cr.CONFIG_WINDOWS for c in cr.chunks(*w)] + [cr.IDLE_WINDOW]
    d = result["decoded"]
    assert (d["resume_pointer_0x2000f8"], d["first_boot_hook_0x2000f0"], d["followed"]) == (0xD2A1, 0x8D01, False)
    assert not any(a in (0xD2A0, 0x8D00, 0x3000) for a, _ in f.writes)
    assert result["repeated_equal"] and f.reader.closed


def test_resume_windows_closed_outside_phase():
    f = ResumeFake()
    for w in mr.RESUME_WINDOWS.values():
        with pytest.raises(ValueError):
            asyncio.run(f.reader.read(*cr.chunks(*w)[0]))


def test_cli_resume_plan(transport, tmp_path):
    transport.config[mr.BOOT_HOOK_WINDOW[0]] = HOOKS
    transport.config[mr.PRE_BOOT_HOOK_WINDOW[0]] = PRE_BOOT
    args = arguments(tmp_path)
    args.resume_pointers = True
    assert asyncio.run(ram_read.run(args)) == 0
    rows = [json.loads(line) for line in (args.output / "transcript.jsonl").read_text().splitlines()]
    assert rows[0]["plan"] == "ram-ownership-resume-pointers-v1" and rows[-1]["requests"] == 108
    assert (args.output / "resume-pointers.json").exists()


RESUME_DIR = ROOT / "firmware/research/2026-09-24/ram-ownership-resume-pointers"


def test_resume_pointer_archive_replay():
    raw = (RESUME_DIR / "resume-pointers.json").read_bytes()
    log = (RESUME_DIR / "transcript.jsonl").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "7f5190fd069874aa4869d629f36a060f4eb05799a7937074ff3154d6f5db8a02"
    assert hashlib.sha256(log).hexdigest() == "01f4310bbd3a52d4fd9cfe8982cbde6de276a506d7b35f40ada6d05eca6f2870"
    capture = json.loads(raw)
    rows = [json.loads(line) for line in log.decode().splitlines()]
    assert [r["kind"] for r in rows[-2:]] == ["disconnected", "completed"] and rows[-1]["requests"] == 108
    d = capture["decoded"]
    assert (d["resume_pointer_0x2000f8"], d["first_boot_hook_0x2000f0"], d["pre_boot_hook_0x20014c"]) == (0xD22D, 0x40EB, 0xB9B3)
    assert capture["repeated_equal"] and not d["followed"]


# --- Resume-code plan (fake transport) ---
FAKE_CODE = bytes((i * 5 + 1) & 0xFF for i in range(512))  # invented ROM bytes


class ResumeCodeFake(RAMFake):
    def __init__(self, pointer=0xD22D):
        super().__init__()
        self.events = []
        self.reader = mr.RAMResumeCodeReader(self, self.events.append, timeout=0.01, spacing=0)
        self.config[mr.RESUME_POINTER_WINDOW[0]] = struct.pack("<I", pointer)
        self.config[mr.RESUME_CODE_WINDOW[0]] = FAKE_CODE


def resume_code(f, archive=None):
    archive = archive if archive is not None else (RESUME_DIR / "resume-pointers.json").read_bytes()
    return asyncio.run(mr.collect_resume_code(f.reader, BASE, V2, SYMBOLS, "fake-code", archive))


def test_resume_code_plan_budget_and_order():
    f = ResumeCodeFake()
    result = resume_code(f)
    assert len(f.writes) == mr.RESUME_CODE_TRANSACTIONS == 178
    p, code = cr.chunks(*mr.RESUME_POINTER_WINDOW), list(cr.chunks(*mr.RESUME_CODE_WINDOW))
    assert f.writes[mr.PREREQUISITE_TRANSACTIONS:] == list(p) * 2 + code * 2 + [
        c for w in cr.CONFIG_WINDOWS for c in cr.chunks(*w)] + [cr.IDLE_WINDOW]
    assert bytes.fromhex(result["resume_code"]["data_hex"]) == FAKE_CODE
    assert not result["target_execution"] and f.reader.closed


def test_resume_code_refuses_changed_pointer_before_code():
    f = ResumeCodeFake(pointer=0xD231)
    with pytest.raises(RuntimeError, match="resume pointer changed"):
        resume_code(f)
    assert not any(a == mr.RESUME_CODE_WINDOW[0] for a, _ in f.writes)


def test_resume_code_refuses_unreviewed_archive():
    f = ResumeCodeFake()
    with pytest.raises(ValueError):
        resume_code(f, archive=b"{}")
    assert f.writes == []


def test_cli_resume_code_plan(transport, tmp_path):
    transport.config[mr.RESUME_POINTER_WINDOW[0]] = struct.pack("<I", 0xD22D)
    transport.config[mr.RESUME_CODE_WINDOW[0]] = FAKE_CODE
    args = arguments(tmp_path)
    args.resume_code = True
    assert asyncio.run(ram_read.run(args)) == 0
    rows = [json.loads(line) for line in (args.output / "transcript.jsonl").read_text().splitlines()]
    assert rows[0]["plan"] == "ram-ownership-resume-code-v1" and rows[-1]["requests"] == 178


def test_resume_code_archive_replay():
    d = ROOT / "firmware/research/2026-09-24/ram-ownership-resume-code"
    raw, log = (d / "resume-code.json").read_bytes(), (d / "transcript.jsonl").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "fbff5caa62754c03b7d7bdda0f0da11378baddca43e3337bbdf6651690d26851"
    assert hashlib.sha256(log).hexdigest() == "e6fa3d00963d211d23fe8bc44ba00b4093de0d7ac3550016bdf27086c9c9199d"
    rows = [json.loads(line) for line in log.decode().splitlines()]
    assert [r["kind"] for r in rows[-2:]] == ["disconnected", "completed"] and rows[-1]["requests"] == 178
    capture = json.loads(raw)
    assert capture["resume_pointer"] == mr.EXPECTED_RESUME_POINTER and capture["repeated_equal"]
    assert capture["pointer_archive_sha256"] == mr.RESUME_POINTER_ARCHIVE_SHA256


# --- Stack plan stage 1 (fake transport) ---
def _msp(touched_words):
    words = [mr.PAINT_WORD] * (mr.MSP_PAINT_WINDOW[1] // 4)
    for i in range(len(words) - touched_words, len(words)):
        words[i] = 0x12345678 + i       # invented stack residue at the top of the paint
    return struct.pack(f"<{len(words)}I", *words)


HANDLES = struct.pack("<64I", 0x20F000, 0x20F200, *([0] * 62))   # invented


class StacksFake(RAMFake):
    def __init__(self, touched=3):
        super().__init__()
        self.events = []
        self.reader = mr.RAMStacksReader(self, self.events.append, timeout=0.01, spacing=0)
        self.msp = _msp(touched)
        self.config[mr.MSP_PAINT_WINDOW[0]] = self.msp
        self.config[mr.CURRENT_TCB_WINDOW[0]] = struct.pack("<I", 0x20F000)
        self.config[mr.TASK_HANDLES_WINDOW[0]] = HANDLES


def test_stacks_plan_budget_redaction_and_paint_bound():
    f = StacksFake(touched=3)
    result = asyncio.run(mr.collect_stacks(f.reader, BASE, V2, SYMBOLS, "fake-stacks"))
    assert len(f.writes) == mr.STACKS_TRANSACTIONS == 198
    p = result["msp_paint"][0]
    assert p["intact_words"] == 93 and p["untouched_bottom_bytes"] == 93 * 4
    assert p["max_depth_bound_bytes"] == mr.MSP_TOP - (mr.MSP_PAINT_WINDOW[0] + 93 * 4)
    assert result["nonzero_handles"] == [0x20F000, 0x20F200] and not result["pointer_following"]
    text = json.dumps(result) + json.dumps(f.events)
    assert all(f.msp[i:i + 14].hex() not in text for i in range(0, len(f.msp), 14))
    msp_replies = [e for e in f.events if e["kind"] == "reply" and
                   mr.MSP_PAINT_WINDOW[0] <= e["address"] < sum(mr.MSP_PAINT_WINDOW)]
    assert msp_replies and all(e["redacted"] and e["packet"] is None for e in msp_replies)
    assert not any(a in (0x20F000, 0x20F200) for a, _ in f.writes)


def test_intact_paint_bounds_depth_by_unpainted_region():
    p = mr.paint_profile(_msp(0))
    assert p["all_paint_intact"] and p["max_depth_bound_bytes"] == mr.MSP_TOP - sum(mr.MSP_PAINT_WINDOW) == 1152


def test_cli_stacks_plan(transport, tmp_path):
    transport.config[mr.MSP_PAINT_WINDOW[0]] = _msp(0)
    transport.config[mr.CURRENT_TCB_WINDOW[0]] = struct.pack("<I", 0x20F000)
    transport.config[mr.TASK_HANDLES_WINDOW[0]] = HANDLES
    args = arguments(tmp_path)
    args.stacks = True
    assert asyncio.run(ram_read.run(args)) == 0
    rows = [json.loads(line) for line in (args.output / "transcript.jsonl").read_text().splitlines()]
    assert rows[0]["plan"] == "ram-ownership-stacks-v1" and rows[-1]["requests"] == 198


# --- Stack plan stage 2 (fake transport) ---
STACKS_ARCHIVE = ROOT / "firmware/research/2026-09-24/ram-ownership-stacks/stacks.json"


class TCBFake(RAMFake):
    def __init__(self):
        super().__init__()
        self.events = []
        self.reader = mr.RAMTCBReader(self, self.events.append, timeout=0.01, spacing=0)
        self.config[mr.HANDLE_TABLE_WINDOW[0]] = bytes(128)
        for a in mr.TCB_CANDIDATES:
            self.config[a] = bytes((a + i) & 0xFF for i in range(mr.TCB_HEADER_BYTES))  # invented


def test_tcb_candidates_rederive_from_archive_and_budget():
    assert tuple(mr.tcb_candidates_from_lists(STACKS_ARCHIVE.read_bytes())) == mr.TCB_CANDIDATES
    f = TCBFake()
    result = asyncio.run(mr.collect_tcbs(f.reader, BASE, V2, SYMBOLS, "fake-tcb", STACKS_ARCHIVE.read_bytes()))
    assert len(f.writes) == mr.TCB_TRANSACTIONS == 194
    assert set(result["windows"]) == set(mr.TCB_WINDOWS) and all(result["repeated_equal"].values())


def test_tcb_plan_refuses_other_archive_and_closed_windows():
    f = TCBFake()
    with pytest.raises(ValueError):
        asyncio.run(mr.collect_tcbs(f.reader, BASE, V2, SYMBOLS, "fake", b"{}"))
    assert f.writes == []
    for w in mr.TCB_WINDOWS.values():
        with pytest.raises(ValueError):
            asyncio.run(TCBFake().reader.read(*cr.chunks(*w)[0]))


# --- Stack plan stage 3 (fake transport) ---
TCB_ARCHIVE = ROOT / "firmware/research/2026-09-24/ram-ownership-tcbs/tcbs.json"


def _stack(length, used_top_bytes):
    words = [mr.PAINT_WORD] * (length // 4)
    for i in range(len(words) - used_top_bytes // 4, len(words)):
        words[i] = 0x0BAD0000 + i         # invented residue
    return struct.pack(f"<{len(words)}I", *words)


class WatermarkFake(RAMFake):
    def __init__(self, used=64):
        super().__init__()
        self.events = []
        self.windows = mr.stack_windows_from_tcbs(TCB_ARCHIVE.read_bytes())
        self.reader = mr.RAMWatermarkReader(self, self.events.append, self.windows, timeout=0.01, spacing=0)
        self.stacks = {}
        for name, (address, length) in self.windows.items():
            self.stacks[name] = _stack(length, used if length >= 512 else 0)
            self.config[address] = self.stacks[name]


def test_watermark_windows_derive_from_tcb_archive_and_stay_inside_stacks():
    table = mr.tcb_table(TCB_ARCHIVE.read_bytes())
    assert {t: v["stack_bytes"] for t, v in table.items()} == {
        "UpperStac": 3072, "app": 1024, "qc_app": 3584, "hub": 2560, "IDLE": 1024, "Tmr Svc": 1024}
    windows = mr.stack_windows_from_tcbs(TCB_ARCHIVE.read_bytes())
    for task, n in mr.STACK_READS.items():
        start, length = windows[f"stack_{task.replace(' ', '_')}"]
        assert start == table[task]["pxStack"] and length == n <= table[task]["stack_bytes"]
    assert mr.watermark_transactions(windows) == 454


def test_watermark_plan_hash_only_and_headroom_bounds():
    f = WatermarkFake(used=64)
    result = asyncio.run(mr.collect_watermarks(f.reader, BASE, V2, SYMBOLS, "fake-wm", TCB_ARCHIVE.read_bytes()))
    assert len(f.writes) == 454
    assert result["profiles"]["app"]["untouched_bottom_bytes"] == 1024 - 64
    assert result["profiles"]["IDLE"]["whole_read_painted"] is True
    text = json.dumps(result) + json.dumps(f.events)
    for data in f.stacks.values():
        assert all(data[i:i + 14].hex() not in text for i in range(0, len(data), 14))
    assert not result["raw_stored"] and not result["pointer_following"]


def test_watermark_reader_must_use_offline_windows():
    f = WatermarkFake()
    f.reader = mr.RAMWatermarkReader(f, f.events.append, {"stack_app": (0x213360, 16)}, timeout=0.01, spacing=0)
    with pytest.raises(ValueError):
        asyncio.run(mr.collect_watermarks(f.reader, BASE, V2, SYMBOLS, "fake", TCB_ARCHIVE.read_bytes()))
    assert f.writes == []


def test_cli_watermark_plan(transport, tmp_path):
    for name, (address, length) in mr.stack_windows_from_tcbs(TCB_ARCHIVE.read_bytes()).items():
        transport.config[address] = _stack(length, 0)
    args = arguments(tmp_path)
    args.watermarks = True
    assert asyncio.run(ram_read.run(args)) == 0
    rows = [json.loads(line) for line in (args.output / "transcript.jsonl").read_text().splitlines()]
    assert rows[0]["plan"] == "ram-ownership-stack-watermarks-v1" and rows[-1]["requests"] == 454


@pytest.mark.parametrize("folder, capture, capture_sha, transcript_sha, requests", [
    ("ram-ownership-stacks", "stacks.json",
     "9cc0038e7bd1233898acfad16f613ec7d20a5c14a37794716b4249c6b4b9ed9f",
     "88617ba26c8286d42217eb1e728605fed9789d9ed472651574a1791bb7471584", 198),
    ("ram-ownership-tcbs", "tcbs.json",
     "45f5f16b8f13da5f3f3e3907a0abe2bcb4b61604eb8001f8e24f438c8439557e",
     "c974f0bde7fa724615b160ef71553a9292471d1104d87e24b7725ae6b57c86c4", 194),
    ("ram-ownership-stack-watermarks", "stack-watermarks.json",
     "1101efed9615fa8961ac430fd08341be5d59938daa01aa11ff472a4dc8459405",
     "65ac6388f77b530f35b4ff90a7650ff62b35455708063ad03f78cc353f958baf", 454),
])
def test_stack_archives_replay(folder, capture, capture_sha, transcript_sha, requests):
    d = ROOT / "firmware/research/2026-09-24" / folder
    raw, log = (d / capture).read_bytes(), (d / "transcript.jsonl").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == capture_sha
    assert hashlib.sha256(log).hexdigest() == transcript_sha
    rows = [json.loads(line) for line in log.decode().splitlines()]
    assert [r["kind"] for r in rows[-2:]] == ["disconnected", "completed"] and rows[-1]["requests"] == requests
    assert "unexpected_notification" not in [r["kind"] for r in rows]


def test_stack_watermark_results():
    r = json.loads((ROOT / "firmware/research/2026-09-24/ram-ownership-stack-watermarks/stack-watermarks.json").read_text())
    p = r["profiles"]
    assert (p["app"]["untouched_bottom_bytes"], p["Tmr Svc"]["untouched_bottom_bytes"]) == (192, 504)
    assert all(p[t]["whole_read_painted"] for t in ("hub", "qc_app", "IDLE", "UpperStac"))
    msp = json.loads((ROOT / "firmware/research/2026-09-24/ram-ownership-stacks/stacks.json").read_text())["msp_paint"]
    assert all(m["all_paint_intact"] and m["max_depth_bound_bytes"] == 1152 for m in msp)
    assert r["raw_stored"] is False


# --- GATT resources plan (fake transport) ---
class GATTFake(RAMFake):
    def __init__(self):
        super().__init__()
        self.events = []
        self.reader = mr.GATTResourcesReader(self, self.events.append, timeout=0.01, spacing=0)
        for name, (address, length) in mr.GATT_WINDOWS.items():
            self.config[address] = bytes((address + i) & 0xFF for i in range(length))  # invented


def test_gatt_plan_budget_windows_and_no_following():
    f = GATTFake()
    result = asyncio.run(mr.collect_gatt(f.reader, BASE, V2, SYMBOLS, "fake-gatt"))
    assert len(f.writes) == mr.GATT_TRANSACTIONS == 172
    one = [c for w in mr.GATT_WINDOWS.values() for c in cr.chunks(*w)]
    assert f.writes[mr.PREREQUISITE_TRANSACTIONS:] == one + one + [
        c for w in cr.CONFIG_WINDOWS for c in cr.chunks(*w)] + [cr.IDLE_WINDOW]
    assert all(result["repeated_equal"].values()) and not result["pointer_following"]
    # OTP window stays inside the SDK's "upper" block, away from other OTP fields.
    lo, n = mr.GATT_WINDOWS["upper_otp_config"]
    assert 0x2002BC <= lo and lo + n <= 0x200334


def test_gatt_windows_closed_outside_phase():
    for w in mr.GATT_WINDOWS.values():
        with pytest.raises(ValueError):
            asyncio.run(GATTFake().reader.read(*cr.chunks(*w)[0]))


def test_cli_gatt_plan(transport, tmp_path):
    for name, (address, length) in mr.GATT_WINDOWS.items():
        transport.config[address] = bytes(length)
    args = arguments(tmp_path)
    args.gatt_resources = True
    assert asyncio.run(ram_read.run(args)) == 0
    rows = [json.loads(line) for line in (args.output / "transcript.jsonl").read_text().splitlines()]
    assert rows[0]["plan"] == "gatt-resources-v1" and rows[-1]["requests"] == 172


def test_gatt_archive_replay_and_build_mismatch():
    d = ROOT / "firmware/research/2026-09-24/gatt-resources"
    raw, log = (d / "gatt-resources.json").read_bytes(), (d / "transcript.jsonl").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "27922eb7ab369b67b1d1c48bf8e471f48b04e848a81e952eb7740400e67736d9"
    assert hashlib.sha256(log).hexdigest() == "1583b495b2ee1533dcbce161320f251a15d05e15e89a805367d55a026847d790"
    rows = [json.loads(line) for line in log.decode().splitlines()]
    assert [r["kind"] for r in rows[-2:]] == ["disconnected", "completed"] and rows[-1]["requests"] == 172
    capture = json.loads(raw)
    header = bytes.fromhex(capture["windows"]["upperstack_header"][0]["data_hex"])
    ic, _, flags, image_id, _, payload = struct.unpack_from("<BBHHHI", header)
    assert (ic, flags, image_id) == (0x0C, 0x0901, 0x279A) and header[12:28] == rr.ROM_UUID
    assert payload == 0x16C3C            # the public mirror's Upper Stack is 0x214cc: different build
    assert all(capture["repeated_equal"].values())
