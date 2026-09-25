"""Unattached table bytes and exact stock registration ABI; OFF-RING only.

ROM admission is a fixture. No callback, physical GATT discovery, UUID activation,
identity/capability declaration, service-slot allocation or stock write occurs.
"""
from io import BytesIO
import os
from pathlib import Path
import shutil
import struct
import subprocess
from uuid import UUID

import pytest
from elftools.elf.elffile import ELFFile

from probe.unified_build import SOURCES, UNLINKED_CANDIDATES, object_info, object_stack_report
from whip.fwproof_guard import InputSnapshot
from whip.fwstock_link import inspect_elf
from whip.fwtransport import StockTransportHarness, DATA, UART_TABLE, UART_CALLBACKS

ROOT = Path(__file__).resolve().parents[1]
STOCK = ROOT / "firmware/rt02cr-stock-3.12.02.bin"
DESCRIPTOR = ROOT / "firmware/research/2026-09-23/bank0-descriptor/configuration.json"
SERVICE = "33cdf03c-77d9-458b-aedf-12a7a189ef20"


@pytest.fixture(scope="module")
def service_build(tmp_path_factory):
    compiler = shutil.which("clang")
    zig = shutil.which(os.environ.get("WHIP_ZIG", "zig"))
    if not compiler or not zig:
        pytest.skip("reviewed Clang/Zig required")
    assert subprocess.check_output([zig, "version"], text=True).strip() == "0.15.2"
    assert "stock_service" not in SOURCES
    assert "stock_service" in UNLINKED_CANDIDATES
    output = tmp_path_factory.mktemp("stock-service")
    inputs = {str(p.relative_to(ROOT)): p for p in (
        Path(__file__), ROOT / "probe/unified_build.py", ROOT / "whip/fwtransport.py",
        ROOT / "whip/fwcontinuity.py", ROOT / "whip/fwproof_guard.py",
        ROOT / "tests/native/arm_proof.ld", STOCK, DESCRIPTOR,
        *(ROOT / f"firmware/unified/{n}.{ext}"
          for n in ("stock_service", "stock_transport") for ext in ("c", "h")))}
    snapshot = InputSnapshot(inputs)
    toolchain = InputSnapshot({"clang": Path(compiler), "zig": Path(zig)})
    flags = ["--target=armv6m-none-eabi", "-mcpu=cortex-m0plus", "-mthumb",
             "-ffreestanding", "-fno-builtin", "-Oz", "-std=c11", "-Wall", "-Wextra",
             "-Werror", "-fstack-usage", "-I", str(ROOT / "firmware/unified")]
    objects = []
    for name in ("stock_transport", "stock_service"):
        obj = output / (name + ".o")
        subprocess.run([compiler, *flags, "-c", str(ROOT / f"firmware/unified/{name}.c"),
                        "-o", str(obj)], check=True)
        repeated = output / (name + "-repeat.o")
        subprocess.run([compiler, *flags, "-c", str(ROOT / f"firmware/unified/{name}.c"),
                        "-o", str(repeated)], check=True)
        assert obj.read_bytes() == repeated.read_bytes()
        objects.append(str(obj))
    entry = output / "entry.o"
    # Harness-required name only; not called, not a production initializer.
    subprocess.run([compiler, *flags, "-x", "c", "-c", "-", "-o", str(entry)],
                   input="void wr_init(void) {}\n", text=True, check=True)
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(output / "cache"),
               ZIG_LOCAL_CACHE_DIR=str(output / "local"))
    link = [zig, "cc", "-target", "thumb-freestanding-eabi", "-mcpu=cortex_m0plus",
            "-nostdlib", "-Wl,-T," + str(ROOT / "tests/native/arm_proof.ld"),
            "-Wl,-e,wr_init", "-Wl,--build-id=none", "-Wl,--no-undefined"]
    elfs = [output / n for n in ("service-NOT-INSTALLABLE.elf", "repeat.elf")]
    for path in elfs:
        subprocess.run([*link, "-o", str(path), *objects, str(entry)], env=env, check=True)
    assert elfs[0].read_bytes() == elfs[1].read_bytes()
    snapshot.verify(); toolchain.verify()
    raw = elfs[0].read_bytes()
    elf = ELFFile(BytesIO(raw))
    symbols = {s.name: (s["st_value"], s["st_size"])
               for s in elf.get_section_by_name(".symtab").iter_symbols() if s.name}

    def read(address, size):
        for segment in elf.iter_segments():
            if (segment["p_type"] == "PT_LOAD" and
                    segment["p_vaddr"] <= address <= address + size <=
                    segment["p_vaddr"] + segment["p_filesz"]):
                offset = address - segment["p_vaddr"]
                return segment.data()[offset:offset + size]
        raise AssertionError("read outside linked bytes")

    return dict(raw=raw, symbols=symbols, read=read, directory=output,
                object=object_info(output / "stock_service.o"))


def entries(build):
    table, size = build["symbols"]["wgd_database"]
    assert size == 8 * 28 and table % 4 == 0
    raw = build["read"](table, size)
    return [struct.unpack_from("<H16sHII", raw, i * 28) for i in range(8)]


def test_exact_eight_entry_shape_permissions_zero_defaults_and_uuid_order(service_build):
    b = service_build
    rows = entries(b)
    pointer, size = b["symbols"]["wgd_service_uuid"]
    assert size == 16
    assert b["read"](pointer, size) == UUID(SERVICE).bytes[::-1]
    expected = [
        (0x800, b"\x00\x28" + bytes(14), 16, pointer, 1),
        (2, b"\x03\x28\x0c" + bytes(13), 1, 0, 1),
        (5, UUID(SERVICE[:-1] + "1").bytes[::-1], 0, 0, 0x10),
        (2, b"\x03\x28\x10" + bytes(13), 1, 0, 1),
        (5, UUID(SERVICE[:-1] + "2").bytes[::-1], 0, 0, 0x100),
        (0x12, b"\x02\x29" + bytes(14), 2, 0, 0x11),
        (2, b"\x03\x28\x02" + bytes(13), 1, 0, 1),
        (5, UUID(SERVICE[:-1] + "3").bytes[::-1], 0, 0, 1),
    ]
    assert rows == expected
    assert len({b["read"](pointer, 16), *(rows[n][1] for n in (2, 4, 7))}) == 4
    # There is NO identity or capability snapshot embedded here: read is APPL.
    assert rows[7][2:] == (0, 0, 1)


def test_first_six_rows_differ_from_exact_stock_only_at_three_uuid_locations(service_build):
    image = STOCK.read_bytes()
    h = StockTransportHarness(image)  # requires the complete pinned stock hash
    stock = [struct.unpack_from("<H16sHII", h.image, UART_TABLE + i * 28) for i in range(6)]
    rows = entries(service_build)
    for index in range(6):
        expected = list(stock[index])
        if index == 0:
            expected[3] = service_build["symbols"]["wgd_service_uuid"][0]
        if index in (2, 4):
            expected[1] = rows[index][1]
        assert rows[index] == tuple(expected)


def test_discovery_shape_matches_stock_dynamic_read_pattern(service_build):
    image = StockTransportHarness(STOCK.read_bytes()).image
    rows = entries(service_build)
    for index in (1, 3, 5, 7):
        declaration = struct.unpack_from("<H16sHII", image, 0x1F080 + index * 28)
        value = struct.unpack_from("<H16sHII", image, 0x1F080 + (index + 1) * 28)
        assert declaration == rows[6]
        assert value[0] == 4 and value[2:] == (0, 0, 1)
        # Discovery adds only the already observed 128-bit UUID flag.
        assert rows[7][0] == value[0] | 1 and rows[7][2:] == value[2:]


def test_service_object_is_exactly_240_read_only_bytes_not_an_executable_or_ram_owner(service_build):
    info = service_build["object"]
    assert info["allocated_section_bytes"] == {".text": 0, ".rodata": 240}
    assert not info["unresolved_symbols"]
    assert not (service_build["directory"] / "stock_service.su").exists()
    with pytest.raises(ValueError):
        inspect_elf(service_build["raw"], STOCK.read_bytes(), DESCRIPTOR.read_bytes())


def test_only_data_only_objects_may_lack_a_compiler_stack_report(service_build, tmp_path):
    directory = service_build["directory"]
    assert object_stack_report(directory / "stock_service.o") is None
    assert object_stack_report(directory / "stock_transport.o") == directory / "stock_transport.su"
    missing_report = tmp_path / "transport-without-report.o"
    missing_report.write_bytes((directory / "stock_transport.o").read_bytes())
    with pytest.raises(ValueError, match="missing stack report for executable"):
        object_stack_report(missing_report)


class ServiceTableHarness(StockTransportHarness):
    """Admit only the loaded, read-only table span to the existing ROM mock."""
    def __init__(self, build):
        super().__init__(STOCK.read_bytes())
        self.load_shim(build["raw"])
        self.table, self.table_size = build["symbols"]["wgd_database"]

    def _read_bytes(self, address, length):
        if (hasattr(self, "table") and length == self.table_size and
                address == self.table):
            return bytes(self.uc.mem_read(address, length))
        return super()._read_bytes(address, length)


@pytest.mark.parametrize("result,assigned", [(1, 0), (1, 5), (1, 254), (1, 255),
                                              (0, 5), (2, 5), (255, 5)])
def test_eight_rows_reach_original_stock_wrapper_without_registering_on_hardware(service_build, result, assigned):
    h = ServiceTableHarness(service_build)
    # Callback values are original reviewed pointers ONLY for ABI comparison.
    # They are not valid unified callbacks and are never invoked in this test.
    callbacks = struct.unpack_from("<III", h.image, UART_CALLBACKS)
    h.uc.mem_write(DATA, b"\xa5" * 64)
    h.uc.mem_write(DATA + 32, struct.pack("<III", *callbacks))
    h.registration_results.append((result, assigned))
    accepted = result == 1 and assigned != 255
    assert h.call_shim("wg_stock_add", DATA, h.table, 8, DATA + 32) == accepted
    assert bytes(h.uc.mem_read(DATA, 16)) == bytes([assigned if accepted else 255]) + b"\xa5" * 15
    assert h.registrations == [(h.table, service_build["read"](h.table, 224), callbacks)]
    assert 0x15824 in h.executed
    assert h.stack_calls[0][0] == 0x3102
    assert not h.sends and not h.legacy_receives
    # A returned ID5 here is explicitly SIMULATED, not a spare sixth slot.


def test_original_setup_still_declares_only_five_service_slots(service_build):
    h = ServiceTableHarness(service_build)
    h.call(0x76B8)
    assert h.stack_calls[0][:2] == (0x3100, 5)
    assert len(h.registrations) == 5
    assert all(pointer != h.table for pointer, _, _ in h.registrations)
