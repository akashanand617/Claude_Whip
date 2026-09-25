"""Link unified components at the exact STOCK append address; never emit OTA.

No BLE imports, container writer, arbitrary addresses or RAM allocation. Bounds
come from pinned stock and the archived descriptor, not caller-supplied values.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from probe.unified_build import SOURCES
from whip.fwproof_guard import InputSnapshot
from whip.fwstock_link import validate_inputs, inspect_elf

ROOT = Path(__file__).resolve().parents[1]
STOCK = "firmware/rt02cr-stock-3.12.02.bin"
DESCRIPTOR = "firmware/research/2026-09-23/bank0-descriptor/configuration.json"
LINKER = "firmware/unified/stock_append.ld"


def build(output, zig):
    compiler = shutil.which("clang")
    zig = shutil.which(str(zig))
    if not compiler or not zig: raise ValueError("Clang and explicit Zig required")
    if subprocess.check_output([zig, "version"], text=True).strip() != "0.15.2":
        raise ValueError("requires reviewed Zig 0.15.2")
    units = [f"firmware/unified/{name}.c" for name in (*SOURCES, "compiler_runtime")]
    paths = [STOCK, DESCRIPTOR, LINKER, "probe/stock_link.py", "probe/unified_build.py",
             "whip/fwstock_link.py", "whip/fwproof_guard.py", "whip/fwplacement.py", "whip/fwunified.py",
             "whip/fwcapacity.py", "whip/fwidentity.py", "whip/fwbuild.py", "whip/fwoptical.py",
             "whip/protocol.py",
             *units, *(f"firmware/unified/{name}.h" for name in SOURCES)]
    inputs = InputSnapshot({p: ROOT / p for p in paths})
    toolchain = InputSnapshot({"clang": Path(compiler), "zig": Path(zig)})
    stock, descriptor = (ROOT / STOCK).read_bytes(), (ROOT / DESCRIPTOR).read_bytes()
    validate_inputs(stock, descriptor)
    output = Path(output).resolve()
    output.mkdir(exist_ok=False)
    flags = ["--target=armv6m-none-eabi", "-mcpu=cortex-m0plus", "-mthumb", "-ffreestanding",
             "-fno-builtin", "-Oz", "-std=c11", "-Wall", "-Wextra", "-Werror", "-fstack-usage",
             "-I", str(ROOT / "firmware/unified")]
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(output / "cache"), ZIG_LOCAL_CACHE_DIR=str(output / "local"))
    linkflags = ["cc", "-target", "thumb-freestanding-eabi", "-mcpu=cortex_m0plus", "-nostdlib",
                 "-Wl,-T," + str(ROOT / LINKER), "-Wl,-e,wd_init", "-Wl,--build-id=none", "-Wl,--no-undefined",
                 "-Wl,-z,max-page-size=4"]

    def compile_to(directory):
        objects = []
        for source in units:
            target = directory / (Path(source).stem + ".o")
            subprocess.run([compiler, *flags, "-c", str(ROOT / source), "-o", str(target)], check=True)
            objects.append(target)
        target = directory / "stock-append-NOT-INSTALLABLE.elf"
        subprocess.run([zig, *linkflags, "-o", str(target), *map(str, objects)], env=env, check=True)
        return objects, target

    objects, elf = compile_to(output)
    inputs.verify(); toolchain.verify()
    with tempfile.TemporaryDirectory(prefix="whip-stock-relink-") as tmp:
        repeated, second = compile_to(Path(tmp))
        if any(a.read_bytes() != b.read_bytes() for a, b in zip([*objects, elf], [*repeated, second], strict=True)):
            raise RuntimeError("non-reproducible stock-address compile/link")
    inputs.verify(); toolchain.verify()
    report = inspect_elf(elf.read_bytes(), stock, descriptor)
    artifacts = InputSnapshot({p.name: p for p in [*objects, elf, *(p.with_suffix('.su') for p in objects)]})
    report.update(inputs_sha256=inputs.hashes, toolchain_sha256=toolchain.hashes,
                  artifacts_sha256=artifacts.hashes, identical_second_build=True,
                  tests_run=False, scope="link/structure only; execution tests are separate")
    inputs.verify(); toolchain.verify(); artifacts.verify()
    with (output / "link-report.json").open("x") as stream:
        stream.write(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--zig", required=True, type=Path)
    args = parser.parse_args()
    report = build(args.output, args.zig)
    print(f"Linked {report['occupied_append_bytes']} bytes at {report['append_address']:#x}; "
          f"{report['configured_remaining_bytes']} configured bytes remain. NOT INSTALLABLE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
