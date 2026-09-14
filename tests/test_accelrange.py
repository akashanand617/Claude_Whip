import pytest

capstone = pytest.importorskip("capstone")

from probe import accelrange


def thumb(*halfwords):
    out = bytearray()
    for h in halfwords:
        out += h.to_bytes(2, "little")
    return bytes(out)


def movs(reg, imm):
    return 0x2000 | (reg << 8) | imm


def bl(site, target):
    """
    Encode `bl target` at `site`.

    The delta has to be computed per site: BL is PC-relative, so a *constant*
    delta sends every call to a different absolute address and the grouping --
    which is the whole detection mechanism -- never fires.
    """
    imm = (target - (site + 4)) >> 1
    return (0xF000 | ((imm >> 11) & 0x7FF), 0xF800 | (imm & 0x7FF))


def driver_sequence(writes, base=None, helper=None):
    """A run of `movs r1,#value; movs r0,#register; bl helper` at known addresses."""
    base = accelrange.APP_PAYLOAD_OFFSET if base is None else base
    helper = base + 0x400 if helper is None else helper
    out = bytearray(b"\x00" * base)
    for i, (register, value) in enumerate(writes):
        site = base + i * 8 + 4          # the bl is two halfwords after the movs pair
        hi, lo = bl(site, helper)
        out += thumb(movs(1, value), movs(0, register), hi, lo)
    return bytes(out)


def test_finds_a_run_of_register_writes_through_one_helper():
    code = driver_sequence([(0x14, 0xB6), (0x0F, 0x05), (0x10, 0x0A),
                            (0x11, 0x80), (0x3E, 0xC8)])
    found = accelrange.register_write_sequences(code, min_run=4)
    assert found, "a run of movs/movs/bl through one helper should be detected"
    writes = next(iter(found.values()))
    assert (0x0F, 0x05) in [(r, v) for _, r, v in writes]
    assert (0x14, 0xB6) in [(r, v) for _, r, v in writes]


def test_a_short_run_is_not_a_driver():
    """Two register-shaped calls are a coincidence, not a peripheral init."""
    code = driver_sequence([(0x0F, 0x05), (0x10, 0x0A)])
    assert accelrange.register_write_sequences(code, min_run=4) == {}


def test_the_reported_offset_points_at_the_value_immediate():
    """
    The verdict is "change this one byte", so the offset has to be the byte that
    actually holds the value, not the start of the triple.
    """
    code = driver_sequence([(0x0F, 0x05)])
    found = accelrange.register_write_sequences(code, min_run=1)
    offset, reg, val = next(iter(found.values()))[0]
    assert reg == 0x0F and val == 0x05
    # `movs r1,#5` is loaded first, so its immediate is the low byte at `offset`
    assert code[offset] == 0x05


def test_register_and_value_are_not_swapped():
    """r0 carries the register and r1 the value, whichever order they load in."""
    code = driver_sequence([(0x14, 0xB6), (0x0F, 0x08), (0x10, 0x0A), (0x11, 0x80)])
    writes = next(iter(accelrange.register_write_sequences(code, min_run=4).values()))
    pairs = [(r, v) for _, r, v in writes]
    assert (0x0F, 0x08) in pairs and (0x08, 0x0F) not in pairs


def test_known_range_values_cover_the_parts_datasheet():
    assert accelrange.RANGE_VALUES[0x05].startswith("+/-4 g")
    assert accelrange.RANGE_VALUES[0x08] == "+/-8 g"
    assert accelrange.RANGE_REGISTER == 0x0F
