"""
Look for the accelerometer range setting in the firmware. Read-only.

    python -m probe.accelrange
    python -m probe.accelrange --image firmware/rt02cr-stock-3.12.02.bin

**This tool does not patch or flash anything.** The ring M1 depends on is not
worth risking, and the LED hunt already showed what this class of work costs: a
call graph of ~5100 sites, a load base that would not resolve, and days spent.
The question here is narrower and bounded -- *is the range register write even
locatable* -- and the answer is worth having before anyone decides to spend more.

**Why it matters.** Hard flicks saturate. Measured counts-per-g is 8005, so full
scale is +/-4.09 g, and gesture peaks reach 6-7 g. The waveform is therefore
flat-topped exactly where shape carries the discrimination, and the top fifth of
the amplitude information does not exist. The STK8321 supports +/-8 g and +/-16 g;
selecting one would recover it.

**What is searched.** The STK8321 range register is `RANGESEL` at 0x0F:

    0x03  +/-2 g        0x05  +/-4 g  (current)
    0x08  +/-8 g        0x0C  +/-16 g

A driver configuring it writes the register address and the value. Two forms are
looked for: the pair appearing as adjacent bytes in a table, and the Thumb
`movs rN, #imm` idiom loading them into registers near each other. `movs` encodes
as `0010 0rrr iiiiiiii`, so in little-endian memory `movs r0, #0x0F` is the byte
pair `0F 20`.

The mitigation that ships regardless is `model.to_model_input`'s `saturation`
channel, which at least tells the network which windows are clipped.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from whip import fwimage

# Where the Realtek application code begins. `fwimage.PAYLOAD_OFFSETS` gives the
# nested *header* at 0x50; the ARM Thumb the ring actually executes starts here.
APP_PAYLOAD_OFFSET = 0x450

RANGE_REGISTER = 0x0F

RANGE_VALUES = {0x03: "+/-2 g", 0x05: "+/-4 g (current)", 0x08: "+/-8 g", 0x0C: "+/-16 g"}

# Other STK8321 registers, used as corroboration. A hit for the range register
# surrounded by these is far more likely to be the real driver than a coincidence.
NEIGHBOURING_REGISTERS = {
    0x00: "CHIPID", 0x02: "XOUT1", 0x03: "XOUT2", 0x0A: "POWMODE",
    0x10: "BWSEL", 0x11: "POWMODE2", 0x14: "SWRST", 0x3E: "FIFO_CONFIG",
}

# How close two `movs` have to be to plausibly configure the same write.
PROXIMITY_BYTES = 32

# Far more distinctive than a register number. A driver almost always reads
# CHIPID and compares it against the expected value before configuring anything,
# and the I2C slave address has to appear somewhere. If none of these are
# present, the search above is finding arithmetic, not a driver.
#
# 0x0F and 0x05 are among the most common immediates in any ARM program -- 0x0F
# alone appears 141 times, and in this image many of those are `movs r1, #0x0f`
# followed by `mov r0, sp; bl`, which is a 15-byte buffer call, i.e. a packet
# length. Without a distinctive anchor the candidate list is noise.
DISTINCTIVE = {
    0x86: "STK8321 chip ID",
    0x23: "STK8323 chip ID",
    0x18: "STK832x I2C address (SDO low)",
    0x1C: "STK832x I2C address (SDO high)",
    0xB6: "SWRST magic",
}


def register_write_sequences(data: bytes, min_run: int = 4) -> dict[int, list[tuple[int, int, int]]]:
    """
    Find `movs rA,#x; movs rB,#y; bl helper` runs -- a register-write sequence.

    This is what actually locates the driver, and it works without resolving the
    image's load base: a peripheral init is a *run* of such triples all calling
    the same helper, which is a far more distinctive signature than any single
    immediate. Counting occurrences of 0x0F alone found 141 sites and settled
    nothing.

    Returns {helper_target: [(file_offset, register, value), ...]}, keeping only
    helpers called at least `min_run` times in sequence.
    """
    import capstone

    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
    md.detail = False
    sequences: dict[int, list[tuple[int, int, int]]] = {}

    # Disassemble from the code, not from byte zero: the container header is not
    # instructions, and capstone stops at the first thing it cannot decode -- so
    # starting at 0 yielded nothing at all. Data islands inside the code do the
    # same, hence the resync loop.
    instructions = []
    position = APP_PAYLOAD_OFFSET
    while position < len(data) - 4:
        decoded = list(md.disasm(data[position:], position))
        if not decoded:
            position += 2
            continue
        instructions.extend(decoded)
        position = decoded[-1].address + decoded[-1].size + 2
    for i in range(len(instructions) - 2):
        a, b, c = instructions[i], instructions[i + 1], instructions[i + 2]
        if a.mnemonic != "movs" or b.mnemonic != "movs" or c.mnemonic != "bl":
            continue
        try:
            areg, aval = [p.strip() for p in a.op_str.split(",")]
            breg, bval = [p.strip() for p in b.op_str.split(",")]
            first, second = int(aval.lstrip("#"), 0), int(bval.lstrip("#"), 0)
            target = int(c.op_str.lstrip("#"), 0)
        except (ValueError, IndexError):
            continue
        # r0 carries the register, r1 the value, whichever order they are loaded.
        reg, val = (second, first) if breg == "r0" else (first, second)
        sequences.setdefault(target, []).append((a.address, reg, val))

    return {t: w for t, w in sequences.items() if len(w) >= min_run}


def cmp_immediate_sites(payload: bytes, immediate: int) -> list[int]:
    """
    Offsets of every `cmp rN, #immediate`, encoded `0010 1rrr iiiiiiii`.

    A chip-ID check is a comparison, not a load, so this is the form it takes.
    """
    return [
        i for i in range(0, len(payload) - 1, 2)
        if payload[i] == immediate and 0x28 <= payload[i + 1] <= 0x2F
    ]


def movs_pairs(payload: bytes, immediate: int) -> list[int]:
    """Offsets of every `movs rN, #immediate` in the payload."""
    return [
        i for i in range(0, len(payload) - 1, 2)
        if payload[i] == immediate and 0x20 <= payload[i + 1] <= 0x27
    ]


def adjacent_byte_hits(payload: bytes, register: int, value: int) -> list[int]:
    """Offsets where the register and value sit next to each other, either order."""
    hits = []
    for i in range(len(payload) - 1):
        pair = (payload[i], payload[i + 1])
        if pair in ((register, value), (value, register)):
            hits.append(i)
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description="Search firmware for the accelerometer range setting")
    parser.add_argument("--image", type=Path, default=Path("firmware/rt02cr-25hz.bin"))
    parser.add_argument("--context", type=int, default=16, help="bytes of context to print")
    args = parser.parse_args()

    if not args.image.exists():
        print(f"no image at {args.image}")
        return 1

    image = fwimage.inspect(args.image)
    payload = args.image.read_bytes()[APP_PAYLOAD_OFFSET:]
    print(f"{args.image.name}   fw {image.firmware_string}   "
          f"code {len(payload):,} bytes from 0x{APP_PAYLOAD_OFFSET:04x}\n")

    print("Measured full scale is +/-4.09 g (8005 counts/g), so the current setting")
    print(f"is 0x{0x05:02X}. Looking for where it is written.\n")

    # --- find the write helper by structure, not by immediate ----------------
    whole = args.image.read_bytes()
    sequences = register_write_sequences(whole)
    print(f"register-write helpers (movs/movs/bl runs): {len(sequences)}\n")

    SWRST_MAGIC = 0xB6
    driver = None
    for target, writes in sorted(sequences.items(), key=lambda kv: -len(kv[1])):
        regs = {r for _, r, _ in writes}
        # The decisive anchor: a soft reset writing 0xB6 to register 0x14 is the
        # documented STK832x reset, and no unrelated code writes that pair.
        reset = [(o, r, v) for o, r, v in writes if r == 0x14 and v == SWRST_MAGIC]
        print(f"  helper 0x{target:06x}   {len(writes):>4} write(s), "
              f"{len(regs):>3} distinct register(s)"
              f"{'   <- writes the STK832x soft-reset magic' if reset else ''}")
        if reset and driver is None:
            driver = (target, writes)

    if driver is None:
        print("\n  No helper writes 0x14 <- 0xB6, so the accelerometer driver was not")
        print("  identified. Ship the saturation channel and leave the firmware alone.")
        return 0

    target, writes = driver
    print(f"\n  Driver found: helper 0x{target:06x}\n")
    print(f"  {'file':>10}  {'register':>10}  {'value':>6}   meaning")
    for offset, reg, val in writes:
        name = NEIGHBOURING_REGISTERS.get(reg, "")
        if reg == RANGE_REGISTER:
            name = f"RANGESEL -> {RANGE_VALUES.get(val, f'unknown 0x{val:02X}')}"
        elif reg == 0x14 and val == SWRST_MAGIC:
            name = "SWRST (soft reset)"
        print(f"  0x{offset:08x}  0x{reg:02X}{'':>8}  0x{val:02X}    {name}")

    range_writes = [(o, r, v) for o, r, v in writes if r == RANGE_REGISTER]
    print("\n" + "=" * 72)
    if not range_writes:
        print("  The driver never writes 0x0F, so the range is left at its reset default")
        print("  and there is nothing to patch.")
        return 0

    offset, _, value = range_writes[0]
    # The immediate is the low byte of the `movs` that loads the value.
    imm_offset = next(o for o in (offset, offset + 2) if whole[o] == value)
    print(f"  VERDICT: locatable, and it is a single byte.")
    print()
    print(f"  File offset 0x{imm_offset:06x} holds 0x{value:02X}, the immediate of the")
    print(f"  `movs` feeding write_register(0x0F, ...). Current value selects "
          f"{RANGE_VALUES.get(value, '?')}.")
    print()
    print("     0x08  ->  +/-8 g    doubles headroom; gesture peaks reach 6-7 g")
    print("     0x0C  ->  +/-16 g   more than needed, and halves resolution again")
    print()
    print("  Changing it also changes counts-per-g, so accel.COUNTS_PER_G and every")
    print("  amplitude threshold derived from it would need re-measuring, and the")
    print("  whole corpus would need re-recording to be comparable. That is the real")
    print("  cost, not the flash.")
    print()
    print("  NOT PATCHED AND NOT FLASHED -- investigation only, by decision.")
    print("  whip/fwbuild.py already knows how to rebuild a valid image if that changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
