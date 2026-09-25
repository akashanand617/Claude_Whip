"""Unattached read-only identification; actual ARM encoder and Swift decoder.

No capability authorization, BLE read callback, boot-ID generator or RAM owner.
The bounded view borrows caller-owned immutable bytes; it is not a ROM lifetime
proof. Existing firmware, main manifests and production source lists stay fixed.
"""
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import struct
import subprocess

from elftools.elf.elffile import ELFFile
import pytest

from whip.fwproof_guard import InputSnapshot
from whip.fwstock_link import inspect_elf
from whip.fwthumb import RuntimeThumb

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def discovery_build(tmp_path_factory):
    clang = shutil.which("clang")
    zig = shutil.which(os.environ.get("WHIP_ZIG", "zig"))
    swift = os.environ.get("WHIP_SWIFTC") or shutil.which("swiftc")
    assert clang and zig and swift, "Clang, reviewed Zig and Swift required; never skip"
    assert subprocess.check_output([zig, "version"], text=True).strip() == "0.15.2"
    directory = tmp_path_factory.mktemp("unified-discovery")
    paths = [Path(__file__), ROOT / "whip/fwthumb.py", ROOT / "whip/fwproof_guard.py",
             ROOT / "whip/fwstock_link.py", ROOT / "tests/native/arm_proof.ld",
             ROOT / "ios/R02Ring/Health/UnifiedDiscovery.swift",
             *(ROOT / f"firmware/unified/{name}.{ext}"
               for name in ("discovery", "wire") for ext in ("c", "h")),
             ROOT / "firmware/unified/compiler_runtime.c"]
    inputs = InputSnapshot({str(p.relative_to(ROOT)): p for p in paths})
    tools = InputSnapshot({"clang": Path(clang), "zig": Path(zig), "swift": Path(swift)})
    flags = ["--target=armv6m-none-eabi", "-mcpu=cortex-m0plus", "-mthumb",
             "-ffreestanding", "-fno-builtin", "-Oz", "-std=c11", "-Wall", "-Wextra",
             "-Werror", "-fstack-usage", "-I", str(ROOT / "firmware/unified")]
    objects, snapshots = [], []
    for name in ("discovery", "wire", "compiler_runtime"):
        pair = [directory / (name + suffix) for suffix in (".o", "-repeat.o")]
        for obj in pair:
            subprocess.run([clang, *flags, "-c", str(ROOT / f"firmware/unified/{name}.c"),
                            "-o", str(obj)], check=True)
            snapshots.append(InputSnapshot({p.name: p for p in (obj, obj.with_suffix(".su"))}))
        assert pair[0].read_bytes() == pair[1].read_bytes()
        objects.append(str(pair[0]))
    abi = directory / "abi.o"
    subprocess.run([clang, *flags, "-x", "c", "-c", "-", "-o", str(abi)],
                   input='#include "discovery.h"\n#include <stddef.h>\n'
                         '_Static_assert(sizeof(wdi_span)==8,"ARM span ABI");\n'
                         '_Static_assert(offsetof(wdi_span,length)==4,"length ABI");\n'
                         'void wr_init(void) {}\nunsigned proof_runtime_size(void) { return 64; }\n',
                   text=True, check=True)
    snapshots.append(InputSnapshot({p.name:p for p in (abi, abi.with_suffix(".su"))}))
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(directory / "cache"),
               ZIG_LOCAL_CACHE_DIR=str(directory / "local"))
    command = [zig, "cc", "-target", "thumb-freestanding-eabi", "-mcpu=cortex_m0plus",
               "-nostdlib", "-Wl,-T," + str(ROOT / "tests/native/arm_proof.ld"),
               "-Wl,-e,wr_init", "-Wl,--build-id=none", "-Wl,--no-undefined"]
    elfs = [directory / name for name in ("discovery-ARTIFICIAL-NOT-INSTALLABLE.elf", "repeat.elf")]
    for path in elfs:
        subprocess.run([*command, "-o", str(path), *objects, str(abi)], env=env, check=True)
        snapshots.append(InputSnapshot({path.name:path}))
    assert elfs[0].read_bytes() == elfs[1].read_bytes()
    main = directory / "main.swift"
    main.write_text('''import Foundation
let cases = try JSONSerialization.jsonObject(with: FileHandle.standardInput.readDataToEndOfFile()) as! [[Int]]
let result: [Any] = cases.map { value in
    do {
        let decoded = try UnifiedDiscovery.decode(value.map { UInt8($0) })
        return ["boot": String(decoded.bootID), "build": String(decoded.buildTag)]
    } catch { return NSNull() }
}
FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: result))
''')
    snapshots.append(InputSnapshot({main.name:main}))
    binary = directory / "discovery-swift"
    swift_flags = [swift, "-module-cache-path", str(directory / "modules")]
    if os.environ.get("WHIP_SWIFT_SDKROOT"):
        swift_flags += ["-sdk", os.environ["WHIP_SWIFT_SDKROOT"]]
    subprocess.run([*swift_flags, str(ROOT / "ios/R02Ring/Health/UnifiedDiscovery.swift"),
                    str(main), "-o", str(binary)], check=True)
    snapshots.append(InputSnapshot({binary.name:binary}))
    for s in (inputs, tools, *snapshots): s.verify()
    return {"elf":elfs[0].read_bytes(), "directory":directory, "swift":binary,
            "inputs":inputs, "tools":tools, "snapshots":snapshots}


@pytest.fixture
def arm(discovery_build):
    return RuntimeThumb(discovery_build["elf"])


def encode(h, boot, build, pointer=None):
    return h.call("wdi_encode", h.CONTEXT + 4 if pointer is None else pointer,
                  boot & 0xFFFFFFFF, boot >> 32, build & 0xFFFFFFFF, build >> 32)


def test_artificial_candidate_reproduces_and_never_passes_production_placement(discovery_build):
    with pytest.raises(ValueError):
        inspect_elf(discovery_build["elf"], (ROOT / "firmware/rt02cr-stock-3.12.02.bin").read_bytes(),
                    (ROOT / "firmware/research/2026-09-23/bank0-descriptor/configuration.json").read_bytes())
    obj = ELFFile(BytesIO((discovery_build["directory"] / "discovery.o").read_bytes()))
    assert not any(s["sh_size"] and s["sh_flags"] & 3 == 3 for s in obj.iter_sections())
    assert {s.name for s in obj.get_section_by_name(".symtab").iter_symbols()
            if s["st_info"]["type"] == "STT_FUNC"} == {"wdi_encode", "wdi_read"}


@pytest.mark.parametrize("alignment", range(4))
def test_encoder_exact_bytes_unaligned_output_and_unchanged_neighbors(arm, alignment):
    boot, build = 0xFEDCBA9876543210, 0x1020304050607080
    pointer = arm.CONTEXT + 4 + alignment
    assert encode(arm, boot, build, pointer)
    expected = b"WI\1\0" + struct.pack("<QQ", boot, build)
    assert bytes(arm.uc.mem_read(arm.CONTEXT, 64)) == b"\xa5" * (4 + alignment) + expected + b"\xa5" * (40 - alignment)


@pytest.mark.parametrize("boot,build", [(0, 1), (1, 0), (0, 0)])
def test_zero_identifiers_do_not_publish_partial_value(arm, boot, build):
    assert not encode(arm, boot, build)
    assert bytes(arm.uc.mem_read(arm.CONTEXT, 64)) == b"\xa5" * 64


def test_null_encoder_output_never_dereferences_null(arm):
    assert not encode(arm, 1, 2, 0)


@pytest.mark.parametrize("offset", [0, 1, 19, 20, 21, 0x10000, 0xFFFF0000, 0xFFFFFFFF])
def test_read_view_full_width_offset_and_borrowed_lifetime_contract(arm, offset):
    assert encode(arm, 1, 2)
    before = bytes(arm.uc.mem_read(arm.CONTEXT + 4, 20))
    view = arm.CONTEXT + 32
    assert bool(arm.call("wdi_read", arm.CONTEXT + 4, offset, view)) == (offset == 0)
    pointer, size = struct.unpack("<IH", arm.uc.mem_read(view, 6))
    assert (pointer, size) == ((arm.CONTEXT + 4, 20) if offset == 0 else (0, 0))
    assert bytes(arm.uc.mem_read(view + 6, 2)) == b"\xa5\xa5"
    assert bytes(arm.uc.mem_read(arm.CONTEXT + 4, 20)) == before


def test_null_view_input_clears_fields_and_null_output_is_rejected(arm):
    view = arm.CONTEXT + 32
    assert not arm.call("wdi_read", 0, 0, view)
    assert bytes(arm.uc.mem_read(view, 6)) == bytes(6)
    assert not arm.call("wdi_read", 0xDEAD0000, 0, 0)


def test_swift_decodes_actual_arm_values_and_rejects_malformed_identity(arm, discovery_build):
    rng = random.Random(0x5749)
    pairs = [(1, 1), (2**64-1, 2**64-1), (2**32, 2**32),
             *[(rng.randrange(1, 2**64), rng.randrange(1, 2**64)) for _ in range(128)]]
    cases, expected = [], []
    for boot, build in pairs:
        assert encode(arm, boot, build)
        raw = bytes(arm.uc.mem_read(arm.CONTEXT + 4, 20))
        assert raw == b"WI\1\0" + struct.pack("<QQ", boot, build)
        cases.append(list(raw)); expected.append({"boot":str(boot),"build":str(build)})
    good = b"WI\1\0" + struct.pack("<QQ", 1, 2)
    invalid = [good[:n] for n in range(20)] + [good + b"\0", good[:4] + bytes(8) + good[12:], good[:12] + bytes(8)]
    for i in range(4):
        mutant = bytearray(good); mutant[i] ^= 1; invalid.append(bytes(mutant))
    cases += [list(v) for v in invalid]; expected += [None] * len(invalid)
    got = json.loads(subprocess.check_output([str(discovery_build["swift"])], input=json.dumps(cases), text=True))
    assert got == expected
    for s in (discovery_build["inputs"], discovery_build["tools"], *discovery_build["snapshots"]): s.verify()
