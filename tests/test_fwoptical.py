import hashlib
from pathlib import Path

import pytest

from probe import build_optical_off
from whip import fwbuild, fwoptical

BASE = Path(__file__).resolve().parent.parent / "firmware" / "rt02cr-25hz.bin"
pytestmark = pytest.mark.skipif(not BASE.exists(), reason="25 Hz firmware archive not present")


@pytest.fixture(scope="module")
def base():
    return BASE.read_bytes()


@pytest.fixture(scope="module")
def patched(base):
    return fwoptical.build(base)


def test_build_changes_only_reviewed_payload_bytes_and_derived_fields(base, patched):
    result = patched
    assert len(result) == len(base)
    assert fwbuild.verify(result) == []
    changed = {i for i, (a, b) in enumerate(zip(base, result)) if a != b}
    reviewed = {
        0xF68C: bytes.fromhex("7047"),
        0xF690: bytes.fromhex(
            "06480078042805d105480078022801d100207047a0790028704700bfac9c2000099e2000"
        ),
        0xCAD2: bytes.fromhex("02f0ddfd"),
        0x21DC: bytes.fromhex("042038700af091fc"),
        0x691E: bytes.fromhex("08f0c9fe"),
        0xF6B4: bytes.fromhex("10b5f7f7c4fc054c2078042805d10020207020461030f4f735fb10bdac9c2000"),
        0x1231A: bytes.fromhex("0020"),
    }
    payload_changes = {
        offset + i for offset, replacement in reviewed.items()
        for i, value in enumerate(replacement) if base[offset + i] != value
    }
    assert fwoptical.PAYLOAD_CHANGE_ALLOWLIST == {
        offset + i for offset, replacement in reviewed.items() for i in range(len(replacement))
    }
    for offset, replacement in reviewed.items():
        assert result[offset:offset + len(replacement)] == replacement
    assert {i for i in changed if i >= fwbuild.PAYLOAD_START} == payload_changes
    derived = set(range(fwbuild.BODY_SUM_OFFSET, fwbuild.BODY_SUM_OFFSET + 4))
    derived.update(range(fwbuild.SHA256_OFFSET, fwbuild.SHA256_OFFSET + fwbuild.SHA256_LEN))
    assert changed <= payload_changes | derived
    assert result[0xF68C:0xF68E] == bytes.fromhex("7047")  # bx lr
    assert result[0x1231A:0x1231C] == bytes.fromhex("0020")  # movs r0,#0
    assert result[0x2248:0x224E] == base[0x2248:0x224E] == bytes.fromhex("04220123d200")
    assert result[0xBF0A:0xBF0E] == base[0xBF0A:0xBF0E]  # accel range
    assert result[0x7ED4:0x7EE0] == base[0x7ED4:0x7EE0]  # DFU timer
    assert fwoptical.build(base) == result


@pytest.mark.parametrize("offset", [
    0xF68C, 0xF68E, 0xF690, 0xF6A7, 0xF6AC, 0xF6B3, 0xF6B6,
    0xF6CE, 0xF6D3, 0xF6D6, 0x691C, 0x691E, 0x6922, 0x7042, 0x3D38,
    0xCAD0, 0xCAD2, 0xCAD6, 0x21D6, 0x21DC, 0x21E0, 0x21E4,
    0x1231A, 0x12326,
])
def test_refuses_changed_instruction_or_surrounding_signature(base, offset):
    changed = fwbuild.patch(base, {offset: base[offset] ^ 1})
    with pytest.raises(ValueError, match="instruction signature mismatch"):
        fwoptical.build(changed)


def test_refuses_other_consistent_base(base):
    changed = fwbuild.patch(base, {0x2248: 3})
    assert fwbuild.verify(changed) == []
    with pytest.raises(ValueError, match="unrecognized base SHA-256"):
        fwoptical.build(changed)


def test_rejects_an_unreviewed_output_change_even_with_valid_container(base, monkeypatch):
    original_patch = fwbuild.patch

    def unexpected_edit(data, edits):
        return original_patch(data, {**edits, 0x2248: 3})

    monkeypatch.setattr(fwbuild, "patch", unexpected_edit)
    with pytest.raises(ValueError, match="outside the reviewed patch"):
        fwoptical.build(base)


def test_refuses_inconsistent_container(base):
    changed = bytearray(base)
    changed[0x2248] = 3
    with pytest.raises(ValueError, match="base container is inconsistent"):
        fwoptical.build(bytes(changed))


def test_refuses_wrong_hardware(base):
    changed = bytearray(base)
    changed[0x30:0x50] = b"RT02CR_V3.2".ljust(32, b"\0")
    with pytest.raises(ValueError, match="expected hardware"):
        fwoptical.build(fwbuild.refresh(bytes(changed)))


def test_refuses_truncated_or_wrong_container(base):
    with pytest.raises(ValueError, match="expected .* bytes"):
        fwoptical.build(base[:-1])
    with pytest.raises(ValueError, match="container magic"):
        fwoptical.build(b"\0\0\0\0" + base[4:])


def _thumb_path(data, pc, stops, registers, memory):
    """Execute the Thumb instructions used by the guard, wake and cleanup paths.

    Memory contains individual bytes. Only the ROM timer APIs are stubbed;
    cb06, original disconnect cleanup 7042, and null-safe timer helper 3d38
    execute intact. Unknown instructions fail rather than act as no-ops.
    """
    zero = False
    calls = []

    def read(address, size):
        return sum(memory[address + i] << (8 * i) for i in range(size))

    def write(address, value, size):
        for i in range(size):
            memory[address + i] = (value >> (8 * i)) & 255

    def signed(value, bits):
        return value - (1 << bits) if value & (1 << (bits - 1)) else value

    for _ in range(120):
        if pc in stops:
            return pc, zero, calls
        at = pc
        instruction = int.from_bytes(data[pc:pc + 2], "little")
        pc += 2
        if instruction & 0xF800 == 0x4800:  # ldr low_register,[pc,#imm8*4]
            address = ((at + 4) & ~3) + (instruction & 255) * 4
            registers[(instruction >> 8) & 7] = int.from_bytes(data[address:address + 4], "little")
        elif instruction & 0xF800 == 0x6800:  # ldr low_register,[base,#imm5*4]
            address = registers[(instruction >> 3) & 7] + ((instruction >> 6) & 31) * 4
            registers[instruction & 7] = read(address, 4)
        elif instruction & 0xFF00 == 0x4600:  # mov register,register
            destination = (instruction & 7) | ((instruction >> 4) & 8)
            registers[destination] = registers[(instruction >> 3) & 15]
        elif instruction & 0xF800 == 0x7800:  # ldrb low_register,[base,#imm5]
            address = registers[(instruction >> 3) & 7] + ((instruction >> 6) & 31)
            registers[instruction & 7] = read(address, 1)
        elif instruction & 0xF800 == 0x7000:  # strb low_register,[base,#imm5]
            address = registers[(instruction >> 3) & 7] + ((instruction >> 6) & 31)
            write(address, registers[instruction & 7], 1)
        elif instruction & 0xF800 in (0x8800, 0x8000):  # ldrh/strh
            address = registers[(instruction >> 3) & 7] + ((instruction >> 6) & 31) * 2
            if instruction & 0x0800:
                registers[instruction & 7] = read(address, 2)
            else:
                write(address, registers[instruction & 7], 2)
        elif instruction & 0xF800 == 0x2000:  # movs low_register,#imm8
            registers[(instruction >> 8) & 7] = instruction & 255
            zero = (instruction & 255) == 0
        elif instruction & 0xF800 == 0x2800:  # cmp low_register,#imm8
            zero = registers[(instruction >> 8) & 7] == (instruction & 255)
        elif instruction & 0xF800 == 0x3000:  # adds low_register,#imm8
            reg = (instruction >> 8) & 7
            registers[reg] = (registers[reg] + (instruction & 255)) & 0xFFFFFFFF
            zero = registers[reg] == 0
        elif instruction & 0xF800 == 0:  # lsls low_register,low_register,#imm5
            value = registers[(instruction >> 3) & 7] << ((instruction >> 6) & 31)
            registers[instruction & 7] = value & 0xFFFFFFFF
            zero = registers[instruction & 7] == 0
        elif instruction & 0xFF00 in (0xD000, 0xD100):  # beq/bne
            if zero == (instruction & 0xFF00 == 0xD000):
                pc = at + 4 + signed(instruction & 255, 8) * 2
        elif instruction & 0xF800 == 0xE000:  # b signed_imm11
            pc = at + 4 + signed(instruction & 2047, 11) * 2
        elif instruction & 0xF800 == 0xF000:  # Thumb BL, including ROM target
            second = int.from_bytes(data[pc:pc + 2], "little")
            assert second & 0xD000 == 0xD000
            sign = (instruction >> 10) & 1
            i1 = 1 ^ ((second >> 13) & 1) ^ sign
            i2 = 1 ^ ((second >> 11) & 1) ^ sign
            delta = (sign << 24) | (i1 << 23) | (i2 << 22)
            delta |= ((instruction & 1023) << 12) | ((second & 2047) << 1)
            target = (at + 4 + signed(delta, 25)) & 0xFFFFFFFF
            registers[14] = (at + 4) | 1
            calls.append((target, memory[0x209CAC]))
            assert registers[13] % 8 == 0
            if target == 0xFF7ED6E4:  # os_timer_restart
                assert registers[0:2] == [0x20BDA4, 800]
                registers[:4] = [0xA000 + i for i in range(4)]  # caller-saved may change
                pc = at + 4
            elif target in (0xFF7ED70C, 0xFF7ED730):  # os_timer_stop/delete
                assert registers[0] == 0x209CBC  # address of handle slot, not its value
                assert read(0x209CBC, 4) != 0
                registers[:4] = [0xB000 + i for i in range(4)]
                pc = at + 4
            else:
                pc = target
        elif instruction & 0xFE00 == 0xB400:  # push low_registers[,lr]
            saved = [i for i in range(8) if instruction & (1 << i)]
            if instruction & 0x100:
                saved.append(14)
            registers[13] -= len(saved) * 4
            for i, reg in enumerate(saved):
                write(registers[13] + i * 4, registers[reg], 4)
        elif instruction & 0xFE00 == 0xBC00:  # pop low_registers[,pc]
            restored = [i for i in range(8) if instruction & (1 << i)]
            if instruction & 0x100:
                restored.append(15)
            for i, reg in enumerate(restored):
                registers[reg] = read(registers[13] + i * 4, 4)
            registers[13] += len(restored) * 4
            if 15 in restored:
                pc = registers[15] & ~1
        elif instruction == 0x4770:  # bx lr
            pc = registers[14] & ~1
        elif instruction != 0xBF00:  # nop
            pytest.fail(f"unexpected instruction {instruction:#06x} at {at:#x}")
    pytest.fail("Thumb path did not reach the expected continuation")


@pytest.mark.parametrize("idle_request", [0, 1, 255])
@pytest.mark.parametrize("state_address", [0x20BDC4, 0x210040])
@pytest.mark.parametrize("connection", [0, 1, 2, 3])
def test_idle_guard_executes_all_modes_and_preserves_nonraw_behavior(
    base, patched, idle_request, state_address, connection,
):
    for mode in range(256):
        registers = [0x1000 + i for i in range(16)]
        registers[4] = state_address
        registers[13] = 0x210000
        original = registers.copy()
        memory = {0x209CAC: mode, 0x209E09: connection, state_address + 6: idle_request}
        before = memory.copy()
        pc, zero, calls = _thumb_path(patched, 0xCAD2, {0xCAD8, 0xCAF6}, registers, memory)
        holding = mode == 4 and connection == 2
        expected = 0 if holding else idle_request
        assert registers[0] == expected
        assert zero == (expected == 0)
        assert pc == (0xCAF6 if expected == 0 else 0xCAD8)
        assert registers[1:14] == original[1:14]  # including r4 and SP
        assert memory == before  # pending request is retained, not cleared
        assert calls == [(0xF690, mode)]
        if not holding:
            original_pc, original_zero, _ = _thumb_path(
                base, 0xCAD2, {0xCAD8, 0xCAF6}, original, before,
            )
            assert (pc, zero, registers[0]) == (original_pc, original_zero, original[0])


@pytest.mark.parametrize("timer_running", [0, 1])
@pytest.mark.parametrize("initial_mode", [0, 4])  # repeated starts must still request wake
def test_raw_start_sets_mode_before_existing_wake_and_preserves_stack(patched, timer_running, initial_mode):
    registers = [0x1000 + i for i in range(16)]
    registers[7] = 0x209CAC  # raw handler's existing mode pointer
    registers[13] = 0x210000
    original = registers.copy()
    memory = {
        0x209CAC: initial_mode, 0x209E09: 2,
        0x20BD94: 0x23,  # STK8321 chip ID selects present-sensor path
        0x20BDC6: timer_running, 0x20BDC7: 0,  # timer flag and wake request
        0x20BDCC: 0x42, 0x20BDCD: 0x01,  # FIFO producer index
    }
    _, _, calls = _thumb_path(patched, 0x21DC, {0x2246}, registers, memory)
    assert calls[0] == (0xCB06, 4)  # mode set BEFORE wake, not just on return
    assert memory[0x209CAC] == 4
    assert memory[0x20BDC7] == 1  # existing driver's asynchronous wake request
    assert memory[0x20BDC6] == 1
    assert (memory[0x20BDCE], memory[0x20BDCF]) == (0x42, 0x01)
    assert registers[4:14] == original[4:14]  # cb06 restores r4-r6 and SP; r7 untouched
    assert len(calls) == (1 if timer_running else 2)


def test_stop_releases_deferred_idle_without_a_persistent_hold_flag(patched):
    # A1 05 and A1 02 both converge here: clear the same mode byte, then stop
    # the producer timer. The guard has no second flag for either stop to clear.
    assert patched[0x21F2:0x21F4] == bytes.fromhex("3e70")  # strb r6,[r7], r6=0
    registers = [0] * 16
    registers[4] = 0x20BDC4
    registers[13] = 0x210000
    memory = {0x209CAC: 4, 0x209E09: 2, 0x20BDCA: 1}
    assert _thumb_path(patched, 0xCAD2, {0xCAD8, 0xCAF6}, registers, memory)[0] == 0xCAF6
    memory[0x209CAC] = 0
    assert _thumb_path(patched, 0xCAD2, {0xCAD8, 0xCAF6}, registers, memory)[0] == 0xCAD8


def test_connection_guard_releases_idle_before_disconnect_cleanup(patched):
    registers = [0] * 16
    registers[4] = 0x20BDC4
    registers[13] = 0x210000
    memory = {0x209CAC: 4, 0x209E09: 2, 0x20BDCA: 1, 0x20BDC7: 0}
    assert _thumb_path(patched, 0xCAD2, {0xCAD8, 0xCAF6}, registers, memory)[0] == 0xCAF6
    memory[0x209E09] = 0  # disconnect clears connection before our cleanup hook
    assert _thumb_path(patched, 0xCAD2, {0xCAD8, 0xCAF6}, registers, memory)[0] == 0xCAD8
    assert memory[0x209CAC] == 4
    assert memory[0x20BDCA] == 1
    memory[0x209E09] = 2
    assert _thumb_path(patched, 0xCAD2, {0xCAD8, 0xCAF6}, registers, memory)[0] == 0xCAF6
    assert memory[0x20BDC7] == 0  # reconnect/guard does not request wake; A1 04 does


@pytest.mark.parametrize("timer_handle", [0, 0x200500])
def test_disconnect_hook_preserves_cleanup_and_stops_only_raw_mode_four(patched, timer_handle):
    for mode in range(256):
        registers = [0x1000 + i for i in range(16)]
        registers[13] = 0x210000
        original = registers.copy()
        memory = {
            0x209CAC: mode, 0x209E09: 0,
            0x20CC32: 17, 0x20CC33: 23,  # existing cleanup's two flags
            0x209CAD: 41, 0x209CAE: 43,  # adjacent raw state must remain untouched
        }
        for i, value in enumerate(timer_handle.to_bytes(4, "little")):
            memory[0x209CBC + i] = value
        _, _, calls = _thumb_path(patched, 0x691E, {0x6922}, registers, memory)
        destinations = [target for target, _ in calls]
        assert destinations[:4] == [0xF6B4, 0x7042, 0xD43E, 0x6FBE]
        assert destinations.count(0x7042) == 1
        assert (memory[0x20CC32], memory[0x20CC33]) == (0, 0)
        assert (memory[0x209CAD], memory[0x209CAE]) == (41, 43)
        assert registers[4:14] == original[4:14]  # callee-saved and SP intact
        if mode == 4:
            assert memory[0x209CAC] == 0
            assert calls[4] == (0x3D38, 0)  # raw mode cleared before timer shutdown
            assert destinations[5:] == ([0xFF7ED70C, 0xFF7ED730] if timer_handle else [])
        else:
            assert memory[0x209CAC] == mode
            assert len(calls) == 4  # no timer operation for any other mode


def test_disconnect_cleanup_leaves_reconnect_stopped_until_new_raw_start(patched):
    registers = [0] * 16
    registers[4] = 0x20BDC4
    registers[13] = 0x210000
    memory = {0x209CAC: 4, 0x209E09: 0, 0x20BDCA: 1, 0x20BDC7: 0}
    memory.update({0x209CBC + i: 0 for i in range(4)})
    _thumb_path(patched, 0x691E, {0x6922}, registers, memory)
    memory[0x209E09] = 2
    assert memory[0x209CAC] == 0
    assert _thumb_path(patched, 0xCAD2, {0xCAD8, 0xCAF6}, registers, memory)[0] == 0xCAD8
    assert memory[0x20BDC7] == 0


def _control_write(data, operation):
    """Execute the small Thumb control function, stopping at its I2C call.

    Decode the actual instructions without a disassembler dependency. This
    checks branch destinations and register/stack payload construction, rather
    than assuming the patched immediate is what reaches the peripheral.
    """
    registers = [operation, 0, 0, 0]
    stack = {}
    sp = 0x210000
    pc = 0x122FE
    zero = False
    for _ in range(40):
        instruction = int.from_bytes(data[pc:pc + 2], "little")
        pc += 2
        if instruction == 0xB508:  # push {r3,lr}
            sp -= 8
        elif instruction == 0xBD08:  # pop {r3,pc}: no write
            return None
        elif instruction & 0xF800 == 0x2000:  # movs low_register,#imm8
            registers[(instruction >> 8) & 7] = instruction & 255
        elif instruction == 0x466A:  # mov r2,sp
            registers[2] = sp
        elif instruction == 0x4669:  # mov r1,sp
            registers[1] = sp
        elif instruction & 0xF800 == 0x7000:  # strb low_register,[base,#imm5]
            address = registers[(instruction >> 3) & 7] + ((instruction >> 6) & 31)
            stack[address] = registers[instruction & 7] & 255
        elif instruction & 0xF800 == 0x2800:  # cmp low_register,#imm8
            zero = registers[(instruction >> 8) & 7] == instruction & 255
        elif instruction & 0xFF00 == 0xD000:  # beq signed_imm8
            immediate = instruction & 255
            if zero:
                pc += 2 + (immediate if immediate < 128 else immediate - 256) * 2
        elif instruction & 0xF800 == 0xE000:  # b signed_imm11
            immediate = instruction & 2047
            pc += 2 + (immediate if immediate < 1024 else immediate - 2048) * 2
        elif instruction == 0xF7FC:
            assert data[pc:pc + 2] == bytes.fromhex("dbfc")  # bl 0xece2
            return registers[0], stack[registers[1]], registers[2]
        else:
            pytest.fail(f"unexpected instruction {instruction:#06x} at {pc - 2:#x}")
    pytest.fail("control function did not return or write")


@pytest.mark.parametrize("operation,original,patched", [
    (0, (0x7B, 0x00, 1), (0x7B, 0x00, 1)),
    (1, (0x7B, 0x5A, 1), (0x7B, 0x00, 1)),
    (2, (0x7B, 0xA5, 1), (0x7B, 0xA5, 1)),
    (3, None, None),
    (255, None, None),
])
def test_control_run_becomes_stop_without_changing_stop_reset_or_invalid(base, operation, original, patched):
    assert _control_write(base, operation) == original
    assert _control_write(fwoptical.build(base), operation) == patched


def test_cli_builds_explicit_experimental_output(base, tmp_path, capsys):
    output = tmp_path / "experimental.bin"
    assert build_optical_off.main(["--base", str(BASE), "--out", str(output)]) == 0
    assert output.read_bytes() == fwoptical.build(base)
    printed = capsys.readouterr().out
    assert "EXPERIMENTAL" in printed
    assert "HARDWARE UNVALIDATED" in printed
    assert "stop or disconnect restores idle eligibility" in printed
    assert "including after reconnect" in printed
    assert "Disconnect clears raw mode 4 and stops its timer" in printed
    assert "No flash performed" in printed
    assert hashlib.sha256(output.read_bytes()).hexdigest() in printed


def test_cli_requires_output_and_never_overwrites(base, tmp_path):
    with pytest.raises(SystemExit) as missing:
        build_optical_off.main([])
    assert missing.value.code == 2
    output = tmp_path / "existing.bin"
    output.write_bytes(b"keep")
    with pytest.raises(SystemExit) as existing:
        build_optical_off.main(["--out", str(output)])
    assert existing.value.code == 2
    assert output.read_bytes() == b"keep"
    with pytest.raises(SystemExit):
        build_optical_off.main(["--base", str(BASE), "--out", str(BASE)])
    assert BASE.read_bytes() == base
