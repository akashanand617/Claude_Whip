"""Actual C dispatcher + adapter; synthetic physical receipts, no device I/O."""
import ctypes as c
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

import pytest

from tests.test_unified_thumb import elf  # noqa: F401
from tests.test_unified_wire import BOOT, frames, request, reply, seal
from tests.test_unified_adapter import (quiet, physical, observe,
    HELD_PROOF, STOP_PROOF, RELEASE_PROOF, HEALTH, ENTERING, GESTURE, RETURNING, FAULT,
    QUIESCE, START, STOP, RESUME, WH_READY)
from whip.fwthumb import RuntimeThumb

ROOT = Path(__file__).resolve().parents[1]
CLOSED, IDLE, RECEIVING, WAITING, REPLY = range(5)
MODULES = ("mode_controller", "sample_tap", "runtime", "health_adapter", "fresh_source",
           "adapter", "wire", "dispatch")
DISPATCH_SOURCE = Path(os.environ.get(
    "WHIP_DISPATCH_SOURCE", ROOT / "firmware/unified/dispatch.c"
)).resolve()


def module_sources():
    """Allow an explicitly named dispatcher experiment to face this whole suite."""
    return [DISPATCH_SOURCE if m == "dispatch" else ROOT / f"firmware/unified/{m}.c"
            for m in MODULES]


class AdapterView:
    def __init__(self, d): self.d = d
    def call(self, op, *args): return self.d.invoke_words("proof_adapter_call", op, args)
    def get(self, key): return self.d.invoke("proof_adapter_get", key)


class Driver:
    def call(self, op, *args): return self.invoke_words("proof_dispatch_call", op, args)
    def get(self, key): return self.invoke("proof_dispatch_get", key)
    def send(self, operation=1, id=1, session=0, sequence=0, now=0, connection=7):
        for p in frames(1, id, request(operation, session=session, sequence=sequence)):
            assert self.feed(p, connection, now)

    def response(self, operation=1, id=1, mode=HEALTH, result=0, session=0, charging=0, now=0):
        packets = frames(2, id, reply(operation, result, mode, charging, session=session))
        assert self.get(0) == REPLY
        for part, packet in enumerate(packets):
            assert self.call(5, 7, now)
            assert self.output() == packet
            assert not self.call(5, 7, now)  # Only one send can be owned at once.
            assert self.call(6, 7, id, part, 1, now)
        assert self.get(0) == IDLE


class ARM(Driver, RuntimeThumb):
    CONTEXT_SIZE_SYMBOL = "proof_dispatch_size"
    CONTEXT_MAX_BYTES = 4096

    def __init__(self, image):
        RuntimeThumb.__init__(self, image)
        self.out = self.CONTEXT + RuntimeThumb.call(self, "proof_dispatch_output_offset")
        assert RuntimeThumb.call(self, "proof_dispatch_adapter_offset") == 0
        self.adapter_view = AdapterView(self)

    # RuntimeThumb.invoke calls self.call, so leave call dispatch by type.
    def call(self, op, *args):
        if isinstance(op, str): return RuntimeThumb.call(self, op, *args)
        return Driver.call(self, op, *args)

    def invoke_words(self, symbol, op, args):
        ptr = self.raw_input(struct.pack("<12I", *args, *([0] * (12-len(args)))))
        return self.invoke(symbol, op, ptr)

    def feed(self, packet, connection=7, now=0):
        return self.invoke("wd_receive", self.raw_input(packet or b"\0"), len(packet), connection, now)

    def output(self): return bytes(self.uc.mem_read(self.out, 20))


@pytest.fixture(scope="module")
def native(tmp_path_factory):
    compiler = shutil.which("clang")
    if not compiler: pytest.skip("Clang required")
    target = tmp_path_factory.mktemp("dispatch") / "dispatch.so"
    subprocess.run([compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC",
                    "-I", str(ROOT / "firmware/unified"),
                    *map(str, module_sources()),
                    str(ROOT / "tests/native/adapter_proof.c"),
                    str(ROOT / "tests/native/dispatch_proof.c"), "-o", str(target)], check=True)
    lib = c.CDLL(str(target))
    for name in ("proof_dispatch_size", "proof_dispatch_output_offset", "proof_dispatch_adapter_offset"):
        getattr(lib, name).argtypes, getattr(lib, name).restype = [], c.c_uint32
    for name in ("proof_dispatch_get", "proof_adapter_get"):
        getattr(lib, name).argtypes = [c.c_void_p, c.c_uint32]
        getattr(lib, name).restype = c.c_uint32
    for name in ("proof_dispatch_call", "proof_adapter_call"):
        getattr(lib, name).argtypes = [c.c_void_p, c.c_uint32, c.POINTER(c.c_uint32)]
        getattr(lib, name).restype = c.c_uint32
    lib.wd_receive.argtypes = [c.c_void_p, c.c_void_p, c.c_uint32, c.c_uint32, c.c_uint32]
    lib.wd_receive.restype = c.c_bool
    return lib


class Native(Driver):
    def __init__(self, lib):
        self.lib = lib
        size = lib.proof_dispatch_size()
        assert 0 < size <= 4096 and lib.proof_dispatch_adapter_offset() == 0
        self.context = (c.c_uint64 * ((size + 7)//8))()
        self.out = c.addressof(self.context) + lib.proof_dispatch_output_offset()
        self.adapter_view = AdapterView(self)

    def invoke(self, name, *args): return getattr(self.lib, name)(self.context, *args)
    def invoke_words(self, name, op, args): return self.invoke(name, op, (c.c_uint32 * 12)(*args))
    def feed(self, packet, connection=7, now=0):
        return self.invoke("wd_receive", c.create_string_buffer(packet), len(packet), connection, now)
    def output(self): return c.string_at(self.out, 20)


@pytest.fixture(params=["native", "arm"])
def d(request):
    obj = (Native(request.getfixturevalue("native")) if request.param == "native"
           else ARM(request.getfixturevalue("elf")))
    assert obj.call(0, 3, 1, 1, BOOT & 0xFFFFFFFF, BOOT >> 32)
    assert obj.call(1, 7, 0, 0)
    return obj


def enter(d):
    d.send(3)
    assert d.get(0) == WAITING and d.adapter_view.get(0) == ENTERING
    quiet(d.adapter_view)
    assert physical(d.adapter_view, HELD_PROOF)
    assert d.adapter_view.get(1) == START
    assert observe(d.adapter_view) == 2
    d.call(3, 0)
    d.response(3, mode=GESTURE, session=d.adapter_view.get(3))


def test_no_effect_before_complete_request_and_no_premature_success(d):
    packets = frames(1, 1, request(3))
    assert d.feed(packets[0])
    assert d.get(0) == RECEIVING and d.adapter_view.get(0) == HEALTH and d.adapter_view.get(2) == 0
    assert not d.call(5, 7, 0)
    assert d.feed(packets[1])
    assert d.get(0) == WAITING and d.adapter_view.get(1) == QUIESCE
    quiet(d.adapter_view)
    assert physical(d.adapter_view, HELD_PROOF)
    d.call(3, 0)
    assert d.get(0) == WAITING and not d.call(5, 7, 0)
    assert observe(d.adapter_view) == 2
    d.call(3, 0)
    d.response(3, mode=GESTURE, session=d.adapter_view.get(3))


def test_health_success_waits_for_current_settings_commit(d):
    enter(d)
    d.send(2, id=2)
    assert d.get(0) == WAITING and d.adapter_view.get(1) == STOP
    assert physical(d.adapter_view, STOP_PROOF) and physical(d.adapter_view, RELEASE_PROOF)
    assert d.adapter_view.get(1) == RESUME
    token = d.adapter_view.get(2)
    assert d.adapter_view.call(11, token, 17, 0)
    quiet(d.adapter_view)
    assert d.adapter_view.call(12, token, d.adapter_view.get(5), 17, 1, 1, 0)
    assert d.adapter_view.get(4) == WH_READY
    d.call(3, 0)
    assert d.get(0) == WAITING and not d.call(5, 7, 0)
    assert not d.adapter_view.call(13, token, 18, 0)
    d.call(3, 0)
    assert d.get(0) == WAITING
    assert d.adapter_view.call(12, token, d.adapter_view.get(5), 18, 1, 1, 0)
    assert d.adapter_view.call(13, token, 18, 0)
    d.call(3, 0)
    d.response(2, id=2, session=d.adapter_view.get(3))


@pytest.mark.parametrize("stage", [QUIESCE, START])
def test_entry_failure_cannot_acknowledge_gesture(d, stage):
    d.send(3)
    if stage == START:
        quiet(d.adapter_view)
        assert physical(d.adapter_view, HELD_PROOF)
    assert d.adapter_view.call(9, d.adapter_view.get(2), d.adapter_view.get(3), stage, 0)
    d.call(3, 0)
    d.response(3, result=4, mode=RETURNING, session=d.adapter_view.get(3))


@pytest.mark.parametrize("missing", ["inventory", "profile", "boot", "charging"])
def test_unqualified_capability_cannot_start_quiescence(d, missing):
    assert d.call(2, 7, 0)
    assert d.call(0, 3, missing != "inventory", missing != "profile",
                  0 if missing == "boot" else BOOT & 0xFFFFFFFF,
                  0 if missing == "boot" else BOOT >> 32)
    if missing == "boot":
        assert not d.call(1, 7, 0, 0)
        return
    assert d.call(1, 7, missing == "charging", 0)
    d.send(3)
    assert d.adapter_view.get(0) == HEALTH and d.adapter_view.get(2) == 0 and d.adapter_view.get(9)
    d.response(3, result=2 if missing == "charging" else 1, charging=int(missing == "charging"))


@pytest.mark.parametrize("fault", ["crc", "kind", "version", "short", "long", "reserved", "boot",
                                  "order", "duplicate", "id", "unknown_operation"])
def test_bad_current_exchange_closes_without_sensor_action(d, fault):
    body = request(0 if fault == "unknown_operation" else 3, boot=BOOT ^ (fault == "boot"))
    if fault == "reserved": body = body[:-1] + b"\1"
    first, second = frames(1, 1, body)
    if fault == "crc": first = first[:-1] + bytes([first[-1] ^ 1])
    if fault == "kind": first = seal(first[:2] + b"\2" + first[3:18])
    if fault == "version": first = seal(first[:1] + b"\2" + first[2:18])
    if fault == "short": first = first[:-1]
    if fault == "long": first += b"\0"
    if fault == "order": first, second = second, first
    if fault == "duplicate": second = first
    if fault == "id": second = frames(1, 2, body)[1]
    d.feed(first)
    assert not d.feed(second)
    assert d.get(0) == CLOSED and d.adapter_view.get(0) == HEALTH and d.adapter_view.get(2) == 0
    assert not d.call(1, 7, 0, 0)  # New generation, never reuse.
    assert d.call(1, 8, 0, 0)


def test_monotonic_request_ids_and_exhaustion(d):
    d.send(id=0xFFFFFFFF)
    d.response(id=0xFFFFFFFF)
    assert not d.feed(frames(1, 1, request())[0])
    assert d.get(0) == CLOSED
    assert d.call(1, 8, 0, 0)
    assert not d.call(1, 9, 0, 0)  # Never replace an active owner.
    d.send(id=1, connection=8)
    assert d.get(0) == REPLY


@pytest.mark.parametrize("pending", ["fragment", "transition", "reply", "offered"])
def test_concurrent_request_fails_closed_and_cancels_entry(d, pending):
    if pending == "fragment": assert d.feed(frames(1, 1, request(3))[0])
    else:
        d.send(3 if pending == "transition" else 1)
        if pending == "offered": assert d.call(5, 7, 0)
    assert not d.feed(frames(1, 2, request(2))[0])
    assert d.get(0) == CLOSED
    assert d.adapter_view.get(0) == (RETURNING if pending == "transition" else HEALTH)


@pytest.mark.parametrize("phase", ["fragment", "reply", "offered"])
def test_no_next_callback_timeout_and_clock_wrap(d, phase):
    start = 0xFFFFFFF0
    if phase == "fragment": assert d.feed(frames(1, 1, request())[0], now=start)
    else:
        d.send(now=start)
        if phase == "offered": assert d.call(5, 7, start)
    d.call(3, (start + 1000) & 0xFFFFFFFF)
    assert d.get(0) != CLOSED
    d.call(3, (start + 1001) & 0xFFFFFFFF)
    assert d.get(0) == CLOSED


def test_stale_callbacks_do_not_touch_reconnected_exchange(d):
    d.send()
    assert d.call(5, 7, 0)
    assert d.call(2, 7, 0) and d.call(1, 8, 0, 0)
    d.send(connection=8)
    assert not d.feed(frames(1, 2, request(3))[0], connection=7)
    assert not d.call(6, 7, 1, 0, 0, 0)
    assert not d.call(2, 7, 0) and not d.call(4, 7, 1, 0)
    assert d.get(0) == REPLY and d.get(3) == 1 and d.adapter_view.get(0) == HEALTH


@pytest.mark.parametrize("part", [0, 1])
def test_send_failure_or_drift_cannot_finish_stale_success(d, part):
    d.send()
    assert d.call(5, 7, 0)
    if part:
        assert d.call(6, 7, 1, 0, 1, 0)
        assert d.call(5, 7, 0)
    assert not d.call(6, 7, 1, part, 0, 0)
    assert d.get(0) == CLOSED


def test_charging_between_reply_fragments_cancels_gesture_success(d):
    d.send(3)
    quiet(d.adapter_view)
    assert physical(d.adapter_view, HELD_PROOF) and observe(d.adapter_view) == 2
    d.call(3, 0)
    assert d.call(5, 7, 0) and d.call(6, 7, 1, 0, 1, 0)
    assert d.call(4, 7, 1, 0)
    assert d.get(0) == CLOSED and d.adapter_view.get(0) == RETURNING
    assert not d.call(5, 7, 0)


def test_reply_receipt_must_match_request_part_and_owned_offer(d):
    d.send()
    assert not d.call(6, 7, 1, 0, 1, 0)
    assert d.call(5, 7, 0)
    assert not d.call(6, 7, 2, 0, 1, 0)
    assert not d.call(6, 7, 1, 1, 1, 0)
    assert d.get(4) == 0 and d.get(5) == 1
    assert d.call(6, 7, 1, 0, 1, 0)
    assert not d.call(6, 7, 1, 0, 1, 0)
    assert d.call(5, 7, 0) and d.call(6, 7, 1, 1, 1, 0)
    assert d.get(0) == IDLE


def test_renew_only_actually_sent_advancing_motion(d):
    enter(d)
    session = d.adapter_view.get(3)
    d.send(4, id=2, session=session, sequence=1, now=20)
    d.response(4, id=2, result=3, mode=GESTURE, session=session, now=20)
    assert d.adapter_view.get(29) == 30000
    assert d.adapter_view.call(14, session, 20) == 1
    assert d.adapter_view.call(15, session, 1, 1, 20)
    d.send(4, id=3, session=session, sequence=1, now=40)
    d.response(4, id=3, mode=GESTURE, session=session, now=40)
    assert d.adapter_view.get(29) == 30040
    d.send(4, id=4, session=session, sequence=1, now=60)
    d.response(4, id=4, result=3, mode=GESTURE, session=session, now=60)
    assert d.adapter_view.get(29) == 30040


def test_closed_transport_still_runs_cleanup_deadlines(d):
    enter(d)
    assert d.call(2, 7, 0)
    assert d.adapter_view.get(0) == RETURNING
    d.call(3, 3000)
    assert d.get(0) == CLOSED and d.adapter_view.get(0) == FAULT
    assert d.call(1, 8, 0, 3000)
    d.send(2, id=1, now=3000, connection=8)
    assert d.get(0) == WAITING and d.adapter_view.get(1) == STOP


def test_completed_request_replay_cancels_active_gesture(d):
    enter(d)
    assert not d.feed(frames(1, 1, request(3))[0])
    assert d.get(0) == CLOSED and d.adapter_view.get(0) == RETURNING
    assert d.adapter_view.get(1) == STOP


def test_status_while_transitioning_is_not_transition_success(d):
    assert d.adapter_view.call(3, 1, 0)
    d.send()
    d.response(mode=ENTERING, session=d.adapter_view.get(3))
    assert d.adapter_view.get(1) == QUIESCE


def test_entry_action_timeout_becomes_error_not_success(d):
    d.send(3)
    d.call(3, 3000)
    assert d.adapter_view.get(0) == RETURNING
    d.response(3, result=4, mode=RETURNING, session=d.adapter_view.get(3), now=3000)


def test_health_resume_failure_does_not_claim_health(d):
    enter(d)
    d.send(2, id=2)
    assert physical(d.adapter_view, STOP_PROOF) and physical(d.adapter_view, RELEASE_PROOF)
    assert d.adapter_view.call(9, d.adapter_view.get(2), d.adapter_view.get(3), RESUME, 0)
    d.call(3, 0)
    d.response(2, id=2, result=4, mode=FAULT, session=d.adapter_view.get(3))


def test_reply_source_expiry_and_disconnected_adapter_invalidate_offer(d):
    d.send(3)
    quiet(d.adapter_view)
    assert physical(d.adapter_view, HELD_PROOF) and observe(d.adapter_view) == 2
    d.call(3, 0)
    assert d.call(5, 7, 0)
    assert not d.call(6, 7, 1, 0, 1, 251)
    assert d.get(0) == CLOSED and d.adapter_view.get(0) == RETURNING
    # Explicit new owner; legacy-style link callback still cannot leave a
    # control owner able to answer after underlying link disappearance.
    assert d.call(1, 8, 0, 251)
    assert d.adapter_view.call(2, 0, 0, 251)
    d.call(3, 251)
    assert d.get(0) == CLOSED


def test_connection_exhaustion_and_null_input(d):
    assert d.call(2, 7, 0) and d.call(1, 0xFFFFFFFF, 0, 0)
    assert d.call(2, 0xFFFFFFFF, 0)
    assert not d.call(1, 0, 0, 0) and not d.call(1, 1, 0, 0)


def test_sanitized_corruption_and_connection_stress(tmp_path):
    compiler = shutil.which("clang")
    if not compiler: pytest.skip("Clang sanitizer runtime required")
    output = tmp_path / "dispatch-stress"
    subprocess.run([compiler, "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                    "-I", str(ROOT / "firmware/unified"),
                    *map(str, module_sources()),
                    str(ROOT / "tests/native/dispatch_stress.c"), "-o", str(output)], check=True)
    result = subprocess.run([str(output)], capture_output=True, text=True, check=True,
                            env=dict(os.environ, ASAN_OPTIONS="detect_leaks=0:halt_on_error=1",
                                     UBSAN_OPTIONS="halt_on_error=1"))
    summary = json.loads(result.stdout)
    assert summary["connections"] == 20000
    assert summary["corrupted_rejected"] == 13334 and summary["completed"] == 6666
    assert 0 < summary["context_bytes"] <= 4096
