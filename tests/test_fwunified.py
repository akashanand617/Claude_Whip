"""Native C policy tests; these are NOT ROM/RTOS or Thumb execution evidence."""
import ctypes as c
import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from whip import fwunified

ROOT = Path(__file__).resolve().parents[1]
HEALTH, ENTERING, GESTURE, RETURNING, FAULT = range(5)
NONE, QUIESCE, HOLD, START, STOP, RELEASE, RESUME = range(7)


class Controller(c.Structure):
    _fields_ = [(s, c.c_int) for s in ("state", "action", "reason")] + [
        (s, c.c_uint32) for s in ("token", "session", "deadline", "lease", "sequence")
    ] + [(s, c.c_bool) for s in ("connected", "charging", "have_sequence")]


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    compiler = shutil.which("clang") or shutil.which("cc")
    if not compiler:
        pytest.skip("C compiler required for native controller tests")
    out = tmp_path_factory.mktemp("controller") / "controller.so"
    subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC",
                    str(ROOT / "firmware/unified/mode_controller.c"), "-o", str(out)], check=True)
    lib = c.CDLL(str(out))
    ptr = c.POINTER(Controller)
    for name, args, result in [
        ("init", [ptr], None), ("link", [ptr, c.c_bool, c.c_bool, c.c_uint32], None),
        ("request", [ptr, c.c_bool, c.c_uint32], c.c_bool),
        ("complete", [ptr, c.c_uint32, c.c_bool, c.c_uint32], c.c_bool),
        ("renew", [ptr, c.c_uint32, c.c_uint32, c.c_uint32], c.c_bool),
        ("tick", [ptr, c.c_uint32], None), ("optics_allowed", [ptr], c.c_bool),
        ("optical_start_allowed", [ptr, c.c_int], c.c_bool),
    ]:
        func = getattr(lib, "wm_" + name)
        func.argtypes, func.restype = args, result
    return lib


def ready(api, now=0):
    ctl = Controller()
    api.wm_init(ctl)
    assert ctl.state == HEALTH and api.wm_optics_allowed(ctl)
    api.wm_link(ctl, True, False, now)
    return ctl


def complete(api, ctl, now=0):
    assert api.wm_complete(ctl, ctl.token, True, now)


def enter(api, ctl, now=0):
    assert api.wm_request(ctl, True, now)
    for action in (QUIESCE, HOLD, START):
        assert ctl.action == action and not api.wm_optics_allowed(ctl)
        complete(api, ctl, now)
    assert ctl.state == GESTURE


def health(api, ctl, now=0):
    for action in (STOP, RELEASE, RESUME):
        assert ctl.action == action and not api.wm_optics_allowed(ctl)
        complete(api, ctl, now)
    assert ctl.state == HEALTH and api.wm_optics_allowed(ctl)


@pytest.mark.parametrize("cause", ["user", "disconnect", "charge", "lease"])
def test_normal_return_and_late_callback(api, cause):
    ctl = ready(api)
    enter(api, ctl)
    old = ctl.token
    now = 30000 if cause == "lease" else 5
    if cause == "user": api.wm_request(ctl, False, now)
    elif cause == "disconnect": api.wm_link(ctl, False, False, now)
    elif cause == "charge": api.wm_link(ctl, True, True, now)
    else: api.wm_tick(ctl, now)
    assert ctl.state == RETURNING
    assert not api.wm_complete(ctl, old, True, now)
    health(api, ctl, now)


@pytest.mark.parametrize("step", range(3))
@pytest.mark.parametrize("failure", ["queue", "timeout", "disconnect", "charge", "cancel"])
def test_entry_interruption_cleans_up_in_order(api, step, failure):
    ctl = ready(api)
    api.wm_request(ctl, True, 0)
    for _ in range(step): complete(api, ctl)
    old = ctl.token
    now = 3000 if failure == "timeout" else 1
    if failure == "queue": api.wm_complete(ctl, old, False, now)
    elif failure == "timeout": api.wm_complete(ctl, old, True, now)
    elif failure == "disconnect": api.wm_link(ctl, False, False, now)
    elif failure == "charge": api.wm_link(ctl, True, True, now)
    else: api.wm_request(ctl, False, now)
    assert ctl.state == RETURNING
    assert not api.wm_complete(ctl, old, True, now)
    health(api, ctl, now)


@pytest.mark.parametrize("step", range(3))
@pytest.mark.parametrize("timeout", [True, False])
def test_failed_return_never_claims_health(api, step, timeout):
    ctl = ready(api)
    enter(api, ctl)
    api.wm_request(ctl, False, 0)
    for _ in range(step): complete(api, ctl)
    if timeout: api.wm_tick(ctl, 3000)
    else: api.wm_complete(ctl, ctl.token, False, 0)
    assert ctl.state == FAULT and not api.wm_optics_allowed(ctl)
    assert not api.wm_request(ctl, True, 3000)
    assert api.wm_request(ctl, False, 3000)
    health(api, ctl, 3000)


def test_lease_freshness_and_clock_wrap(api):
    now = 0xfffff000
    ctl = ready(api, now)
    enter(api, ctl, now)
    assert api.wm_renew(ctl, ctl.session, 0xfffffffe, now + 1)
    assert not api.wm_renew(ctl, ctl.session, 0xfffffffe, now + 2)
    assert not api.wm_renew(ctl, ctl.session + 1, 0xffffffff, now + 2)
    assert api.wm_renew(ctl, ctl.session, 1, now + 3)
    api.wm_tick(ctl, now + 30002)
    assert ctl.state == GESTURE
    assert not api.wm_renew(ctl, ctl.session, 2, now + 30003)
    assert ctl.state == RETURNING


def test_idempotence_and_no_entry_on_charger(api):
    ctl = ready(api)
    enter(api, ctl)
    token = ctl.token
    lease = ctl.lease
    assert api.wm_request(ctl, True, 10)
    assert ctl.token == token and ctl.lease == lease
    api.wm_link(ctl, True, True, 11)
    health(api, ctl, 11)
    assert not api.wm_request(ctl, True, 12)


def test_health_allows_measurements_but_never_decorative_flashing(api):
    ctl = ready(api)
    for state in (HEALTH, ENTERING, GESTURE, RETURNING, FAULT):
        ctl.state = state
        assert api.wm_optical_start_allowed(ctl, 0) == (state == HEALTH)
        for purpose in (1, 2, 99):
            assert not api.wm_optical_start_allowed(ctl, purpose)


def test_randomized_events_never_open_optics_outside_health(api):
    for seed in range(40):
        rng = random.Random(seed)
        ctl = ready(api)
        now = 0
        for _ in range(1000):
            now += rng.randrange(500)
            event = rng.randrange(6)
            if event == 0: api.wm_request(ctl, rng.choice([True, False]), now)
            elif event == 1: api.wm_link(ctl, rng.choice([True, False]), rng.choice([True, False]), now)
            elif event == 2: api.wm_complete(ctl, ctl.token, rng.random() > .1, now)
            elif event == 3: api.wm_complete(ctl, max(0, ctl.token - 1), True, now)
            elif event == 4: api.wm_renew(ctl, ctl.session, now, now)
            else: api.wm_tick(ctl, now)
            assert api.wm_optics_allowed(ctl) == (ctl.state == HEALTH)
            assert (ctl.action == NONE) == (ctl.state in (HEALTH, GESTURE, FAULT))
            if ctl.state == GESTURE:
                assert ctl.connected and not ctl.charging


def test_pinned_stock_and_unconditional_construction_gate():
    data = (ROOT / "firmware/rt02cr-stock-3.12.02.bin").read_bytes()
    audit = fwunified.audit_stock(data)
    assert not audit.errors and audit.vendor_not_ready and not audit.vendor_payload_sha_matches
    assert audit.startup_layout["bss_clear"]["ram_end_exclusive"] == 0x20E734
    assert audit.startup_layout["unclassified_file_tail_bytes"] == 0
    assert audit.startup_layout["boot_overlay"]["ram_end_exclusive"] == 0x20E7FC
    assert audit.startup_layout["safe_controller_allocation"] is None
    assert audit.motion_layout["capacity_samples"] == 82
    assert audit.motion_layout["health_cursor_ram"] == 0x20BDD2
    assert audit.motion_layout["protected_dfu_timer_file"] == 0x80F8
    with pytest.raises(ValueError, match="construction blocked"):
        fwunified.build(data)
    assert fwunified.audit_stock(data[:-1]).errors
    assert fwunified.audit_stock(b"").errors


def test_native_address_and_undefined_behavior_sanitizers(tmp_path):
    compiler = shutil.which("clang")
    if not compiler:
        pytest.skip("Clang with AddressSanitizer/UBSan required")
    binary = tmp_path / "controller-stress"
    subprocess.run([
        compiler, "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
        "-fno-omit-frame-pointer", "-I", str(ROOT / "firmware/unified"),
        str(ROOT / "tests/native/mode_controller_stress.c"),
        str(ROOT / "firmware/unified/mode_controller.c"), "-o", str(binary),
    ], check=True)
    run = subprocess.run([str(binary)], text=True, capture_output=True)
    assert run.returncode == 0, run.stdout + run.stderr
    result = json.loads(run.stdout)
    assert result["random_events"] == 1_280_000
    assert result["complete_sessions"] == 20_000
    assert all(result["state_visits"])
    assert not run.stderr
    print(run.stdout.strip())


@pytest.mark.parametrize("offset", [0, 0xC, 0x10, 0x30, 0x52, 0x58, 0x1C4,
                                   0x450, 0x768, 0x20CC8, 0x21578, 138015])
def test_stock_mutations_never_produce_layout_or_image(offset):
    data = bytearray((ROOT / "firmware/rt02cr-stock-3.12.02.bin").read_bytes())
    data[offset] ^= 1
    audit = fwunified.audit_stock(bytes(data))
    assert audit.errors
    assert audit.startup_layout is None
    assert audit.motion_layout is None
    with pytest.raises(ValueError, match="construction blocked"):
        fwunified.build(bytes(data))


@pytest.mark.parametrize("length", [0, 1, 4, 15, 0x50, 0x1C4, 0x450, 138015, 138017])
def test_truncated_or_extended_stock_fails_closed(length):
    stock = (ROOT / "firmware/rt02cr-stock-3.12.02.bin").read_bytes()
    data = (stock + b"\0")[:length]
    assert fwunified.audit_stock(data).errors
    with pytest.raises(ValueError, match="construction blocked"):
        fwunified.build(data)
