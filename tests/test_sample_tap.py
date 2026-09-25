"""Portable copy-only component tests, not a linked stock adapter."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_sample_tap_native_sanitizers(tmp_path):
    compiler = shutil.which("clang")
    if not compiler:
        pytest.skip("Clang sanitizer support required")
    binary = tmp_path / "tap-stress"
    subprocess.run([
        compiler, "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
        "-I", str(ROOT / "firmware/unified"),
        str(ROOT / "tests/native/sample_tap_stress.c"),
        str(ROOT / "firmware/unified/sample_tap.c"),
        str(ROOT / "firmware/unified/mode_controller.c"), "-o", str(binary),
    ], check=True)
    run = subprocess.run([str(binary)], text=True, capture_output=True)
    assert run.returncode == 0, run.stdout + run.stderr
    result = json.loads(run.stdout)
    assert result["sessions"] == 10000 and result["delivered"] > 3_000_000
    assert result["interleaved"] == 100000
    assert result["tap_bytes"] == 212  # Same capacity; NOT reserved ring RAM
    assert not run.stderr


@pytest.mark.parametrize("source", ["sample_tap.c", "mode_controller.c", "runtime.c"])
def test_cortex_m0plus_freestanding_objects_compile(tmp_path, source):
    compiler = shutil.which("clang")
    if not compiler:
        pytest.skip("Clang ARM backend required")
    out = tmp_path / (source + ".o")
    subprocess.run([
        compiler, "--target=armv6m-none-eabi", "-mcpu=cortex-m0plus", "-mthumb",
        "-ffreestanding", "-fno-builtin", "-Oz", "-std=c11", "-Wall", "-Wextra", "-Werror",
        "-c", str(ROOT / "firmware/unified" / source), "-o", str(out),
    ], check=True)
    assert out.read_bytes()[:4] == b"\x7fELF"
