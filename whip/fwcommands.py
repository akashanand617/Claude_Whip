"""Read-only, exact-stock command-dispatch audit. This is NOT a wire codec.

No opcode is allocated here; no BLE, patching, or image generation is provided.
The bounded walker follows original Thumb comparisons/branches and the two
compiler switch tables. It stops at handler entry, not after executing handlers.
Stack/ABI, ROM, scheduler and hardware behavior are outside this audit.
"""

from dataclasses import dataclass
import hashlib


STOCK_SHA256 = "b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0"
STOCK_SIZE = 138016
RUNTIME_BIAS = 0x825FB0
_PACKET = 0x300000  # Synthetic test memory, not a reservation of ring RAM.


@dataclass(frozen=True)
class Route:
    kind: str
    site: int
    target: int | None
    prelude: bool = False


def _signed(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


class StockWireAudit:
    """Decode only the fingerprinted stock image; reject every other image."""

    def __init__(self, data: bytes):
        if len(data) != STOCK_SIZE or hashlib.sha256(data).hexdigest() != STOCK_SHA256:
            raise ValueError("unrecognized stock image SHA-256/length")
        self.data = bytes(data)

    def _walk(self, pc, registers, memory, stops, passthrough=()):
        """Small branch/data-flow slice, NOT a general CPU emulator.

        Starts after a reviewed prologue, stops before epilogue/handler work.
        Only explicitly listed calls are abstracted as returning; their effects
        are not claimed absent. Unknown instructions and accesses fail closed.
        """
        calls, writes = [], {}
        compared = None
        for _ in range(100):
            if pc in stops:
                return pc, None, calls, writes
            at = pc
            ins = int.from_bytes(self.data[pc:pc + 2], "little")
            pc += 2
            if ins & 0xF800 == 0xF000:  # Thumb BL, including signed backward calls.
                low = int.from_bytes(self.data[pc:pc + 2], "little")
                if low & 0xF800 != 0xF800:
                    raise ValueError(f"unsupported wide instruction at {at:#x}")
                target = (at + 4 + _signed(((ins & 0x7FF) << 12) | ((low & 0x7FF) << 1), 23)) & 0xFFFFFFFF
                pc += 2
                if target == 0x1A378:
                    # Actual helper 1a378..1a390: LR-1 is max/default byte;
                    # entries immediately follow, offsets are unsigned * 2.
                    maximum = self.data[pc]
                    entry = pc + 1
                    index = min(registers[3], maximum)
                    pc = (entry + 2 * self.data[entry + index]) & ~1
                elif target in passthrough:
                    calls.append((at, target))
                else:
                    return at, target, calls, writes
            elif ins & 0xF800 == 0xE000:
                pc = at + 4 + _signed(ins & 0x7FF, 11) * 2
            elif ins & 0xF000 == 0xD000:
                if compared is None:
                    raise ValueError("branch without modeled comparison")
                left, right = compared
                sl, sr = _signed(left, 32), _signed(right, 32)
                conditions = {0: left == right, 1: left != right,
                              2: left >= right, 3: left < right,
                              10: sl >= sr, 11: sl < sr,
                              12: sl > sr, 13: sl <= sr}
                condition = (ins >> 8) & 15
                if condition not in conditions:
                    raise ValueError(f"unsupported condition at {at:#x}")
                if conditions[condition]:
                    pc = at + 4 + _signed(ins & 255, 8) * 2
            elif ins & 0xF800 == 0x2800:
                compared = (registers[(ins >> 8) & 7], ins & 255)
            elif ins & 0xFC00 == 0x4400 and (ins >> 8) & 3 == 2:
                registers[(ins & 7) | ((ins >> 4) & 8)] = registers[(ins >> 3) & 15]
            elif ins & 0xF800 == 0x0000:  # lsls (including movs rD,rS alias).
                registers[ins & 7] = (registers[(ins >> 3) & 7] << ((ins >> 6) & 31)) & 0xFFFFFFFF
            elif ins & 0xF800 == 0x2000:
                registers[(ins >> 8) & 7] = ins & 255
            elif ins & 0xF800 == 0x3800:
                reg = (ins >> 8) & 7
                registers[reg] = (registers[reg] - (ins & 255)) & 0xFFFFFFFF
            elif ins & 0xF800 == 0x1800 and ins & 0x400:  # adds/subs imm3.
                value = (ins >> 6) & 7
                if ins & 0x200:
                    value = -value
                registers[ins & 7] = (registers[(ins >> 3) & 7] + value) & 0xFFFFFFFF
            elif ins & 0xF800 == 0x4800:
                address = ((at + 4) & ~3) + (ins & 255) * 4
                registers[(ins >> 8) & 7] = int.from_bytes(self.data[address:address + 4], "little")
            elif ins & 0xF800 == 0x7800:
                address = registers[(ins >> 3) & 7] + ((ins >> 6) & 31)
                registers[ins & 7] = memory[address]
            elif ins & 0xF800 == 0x7000:
                address = registers[(ins >> 3) & 7] + ((ins >> 6) & 31)
                memory[address] = registers[ins & 7] & 255
                writes[address] = memory[address]
            else:
                raise ValueError(f"unsupported instruction {ins:04x} at {at:#x}")
        raise ValueError("dispatch audit instruction budget exhausted")

    @staticmethod
    def _packet(opcode):
        if not isinstance(opcode, int) or not 0 <= opcode <= 255:
            raise ValueError("opcode must be one byte")
        return {_PACKET: opcode}

    def fast_route(self, opcode: int) -> Route:
        """Follow the opcode tree; stop before any subcommand-dependent leaf."""
        inline = {0x59DA, 0x5AFC, 0x5BC4, 0x5BEE, 0x5BFC}
        site, target, calls, _ = self._walk(
            0x5884, {0: _PACKET}, self._packet(opcode), inline | {0x5990}, (0x8112,),
        )
        kind = ("inline" if site in inline else "silent" if site == 0x5990
                else "enqueue" if target == 0x4CBC else "nak" if target == 0x4ADE else "call")
        return Route(kind, site, target, bool(calls))

    def queued_route(self, opcode: int) -> Route:
        """Tree-only entry after dequeue; does not pretend every opcode enqueues."""
        inline = {0x663E, 0x6656}
        site, target, _, _ = self._walk(
            0x658A, {0: _PACKET, 1: opcode}, self._packet(opcode), inline | {0x6694},
        )
        kind = "inline" if site in inline else "discard" if site == 0x6694 else "call"
        return Route(kind, site, target)

    def prelude_slice(self, state: int):
        """Execute after 96e0 returned state; observe stores and further calls.

        80ee/948a are recorded, not executed. Their timer/state effects are an
        additional reason the prelude is not a harmless capability probe.
        """
        if not 0 <= state <= 255:
            raise ValueError("state must be one byte")
        _, _, calls, writes = self._walk(0x8118, {0: state}, {}, {0x8138}, (0x80EE, 0x948A))
        return calls, writes

    def unknown_a1_slice(self, subcommand: int):
        """Noncharging entry after prologue; observe unknown-subcommand stores."""
        memory = self._packet(subcommand)
        memory[_PACKET] = 0xA1
        memory[_PACKET + 1] = subcommand
        known = {0x2166, 0x21D8, 0x2214, 0x2220, 0x2238, 0x221A, 0x221C, 0x221E}
        site, _, _, writes = self._walk(
            0x2122, {5: _PACKET, 6: 0, 7: 0x209CB0}, memory, known | {0x214A},
        )
        return site, writes

    def length_gate(self, length: int, blocked_state: int) -> bool:
        """Execute the callback's final gate; True means fast-dispatch entry."""
        site, _, _, _ = self._walk(
            0x5C22, {1: length & 0xFFFFFFFF}, {0x208C44: blocked_state}, {0x5882, 0x5C30},
        )
        return site == 0x5882
