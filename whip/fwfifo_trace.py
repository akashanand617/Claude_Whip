"""Offline evidence extraction and exact-image FIFO/I2C execution witnesses.

No BLE dependencies, firmware writes, qualified profiles, invented acquisition
timestamps or model-input export. MMIO responses/ROM mutexes are EXPLICIT mocks;
the transaction, polling, status masking and publication code executes unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
from pathlib import Path

STOCK_SHA256 = "b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0"
V2_SHA256 = "0d18a0fa860d58ab8f984b5f542f45dac105241f47bf1c2af41321eb0431e14c"
BIAS = 0x825FB0

# Reviewed exact-image sites; none is an approved patch or free-space allocation.
MAPS = {
    STOCK_SHA256: dict(read=0xBC6A, bus=0xDCCE, transfer=0xDC40, cleanup=0xDAF0,
        target=0xDFE4, flags=0xDFF8, receive=0x1371E, abort=0x1360A,
        drain=0xC280, publish=0xC4E8, watchdog=0xC25A,
        mutex=0x208C98, busy=0x208544, state=0x20C010, poll=0x2085C8,
        driver=0x20BD98, samples=0x20BDC8, poll_file=0x21690),
    V2_SHA256: dict(read=0xBC12, bus=0xDC66, transfer=0xDBD8, cleanup=0xDA88,
        target=0xDF52, flags=0xDF66, receive=0x1357A, abort=0x13466,
        drain=0xC228, publish=0xC490, watchdog=0xC202,
        mutex=0x208C94, busy=0x208541, state=0x20C00C, poll=0x2085C4,
        driver=0x20BD94, samples=0x20BDC4, poll_file=0x214AC),
}
MAPS[STOCK_SHA256].update(encoder=0x1F18, encoder_tail=0x1F70, checksum=0x3FE8, notify=0x7E30)
MAPS[V2_SHA256].update(encoder=0x1ECC, encoder_tail=0x1F28, checksum=0x3EEC, notify=0x7C0C)


def image_map(image: bytes) -> dict:
    digest = hashlib.sha256(image).hexdigest()
    if digest not in MAPS:
        raise ValueError("FIFO audit requires exact pinned stock or V2 SHA-256")
    m = dict(MAPS[digest])
    m.update(image_sha256=digest, load_bias=BIAS,
             initialized_poll_limit=struct.unpack_from("<I", image, m["poll_file"])[0])
    return m


def _packet(value: object) -> bytes | None:
    if not isinstance(value, str):
        return None
    try:
        packet = bytes.fromhex(value)
    except ValueError:
        return None
    return packet if len(packet) == 16 and sum(packet[:15]) % 256 == packet[15] else None


def native_to_model_counts(frame: bytes) -> tuple[int, int, int]:
    """Exact six-byte FIFO frame -> existing Python/iOS XYZ counts, no rescale.

    Legacy stock encodes native words(w0,w1,w2) as BE fields at2,4,6; both
    model decoders select offsets6,2,4. Do not confuse this with Health's
    (w1,w0,w2) algorithm feed or fabricate a new unified wire packet.
    """
    if not isinstance(frame, bytes) or len(frame) != 6:
        raise ValueError("one complete six-byte native FIFO frame required")
    w0, w1, w2 = struct.unpack("<hhh", frame)
    return w2, w0, w1


def audit_capture(path: str | Path) -> dict:
    """Consume actual existing JSONL formats; never upgrade host time to sensor time.

    The artifact digest identifies the exact input bytes, NOT the installed
    firmware. Reported identity claims retain their original limited scope.
    FIFO status from a sensor diagnostic is a snapshot, not a drain receipt.
    """
    path = Path(path)
    data = path.read_bytes()
    samples: dict[str, list[tuple[float, bytes]]] = {}
    statuses, identities, registers, errors = [], [], set(), []
    rows = 0
    for line_number, line in enumerate(data.splitlines(), 1):
        try:
            row = json.loads(line)
        except (UnicodeError, ValueError) as exc:
            raise ValueError(f"invalid JSON at line {line_number}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"record at line {line_number} is not an object")
        rows += 1
        kind = row.get("kind", row.get("type"))
        if kind == "identity":
            identities.append({key: row[key] for key in ("classification", "scope", "image_sha256") if key in row})
        if kind == "packet":
            raw = row.get("p", row.get("data"))
            p = _packet(raw)
            if p is None:
                errors.append({"line": line_number, "reason": "invalid_packet"})
                continue
            if p[:2] != b"\xa1\x03":
                continue
            t = row.get("t")
            if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t):
                errors.append({"line": line_number, "reason": "missing_host_time"})
                continue
            samples.setdefault(str(row.get("phase", "unlabelled")), []).append((float(t), p[2:8]))
        if kind == "sensor_read":
            req, reply = _packet(row.get("request")), _packet(row.get("reply"))
            if req is None or reply is None or req[:2] != b"\xce\x01" or reply[0] != 0xCE:
                errors.append({"line": line_number, "reason": "invalid_sensor_record"})
                continue
            if req[2] != 0x1F:  # Other sensor snapshots are not STK evidence.
                continue
            reg, length = req[3], req[4]
            if length > 14 or row.get("register") != reg or row.get("length") != length:
                errors.append({"line": line_number, "reason": "sensor_metadata_mismatch"})
                continue
            registers.add(reg)
            if reg == 0x0C and length == 1:
                statuses.append({"line": line_number, "host_t": row.get("t"),
                    "status": reply[1], "count": reply[1] & 0x7F,
                    "overflow": bool(reply[1] & 0x80), "phase": row.get("phase")})
    phases = []
    for phase, records in sorted(samples.items()):
        records.sort(key=lambda item: item[0])  # Archives can flush packets after later diagnostics.
        span = records[-1][0] - records[0][0]
        gaps = [b[0] - a[0] for a, b in zip(records, records[1:])]
        phases.append({"phase": phase, "packets": len(records),
            "distinct_xyz": len({xyz for _, xyz in records}), "host_span_s": span,
            "host_delivery_hz": (len(records) - 1) / span if span > 0 else None,
            "maximum_host_gap_s": max(gaps) if gaps else None})
    return {"schema": "whip.fifo-evidence-audit.v1", "capture_sha256": hashlib.sha256(data).hexdigest(),
        "record_count": rows, "identity_claims": identities, "host_delivery": phases,
        "sensor_register_snapshots": sorted(registers), "fifo_status_snapshots": statuses,
        "errors": errors, "qualified": False, "physical_period_ms": None,
        "model_validation": "blocked_no_physical_acquisition_trace",
        "missing_evidence": ["per-drain full status and status-read success",
            "per-burst byte completion and transport result", "physical frame acquisition-time bounds",
            "complete drain/configuration/overrun ordering", "proven serialized observation",
            "Health baseline timing and sample continuity"],
        "scope": "archived host notifications/register snapshots, not sensor acquisition receipts"}


class FifoProofError(RuntimeError):
    """Execution departed from the exact code/fixture/peripheral boundary."""


class StockFifoHarness:
    """Run real stock/V2 STK read/drain code with scripted I2C0 MMIO.

    Synthetic controller readiness, incoming bytes, ROM mutex/delay and ROM
    memory-copy semantics. No emulated sensor timing, physical byte acceptance,
    RTOS preemption or real Health algorithm. Instruction counts are NOT time.
    """
    STOP, DELAY, STACK, OUTPUT = 0x3FFF0, 0x3FFD0, 0x22F000, 0x221020
    I2C = 0x40015000

    def __init__(self, image: bytes):
        self.map = m = image_map(image)
        self.image_end = BIAS + len(image)
        import unicorn as u
        from unicorn import arm_const as a
        self.u, self.a = u, a
        self.uc = u.Uc(u.UC_ARCH_ARM, u.UC_MODE_THUMB | u.UC_MODE_MCLASS)
        self.uc.ctl_set_cpu_model(a.UC_CPU_ARM_CORTEX_M0)
        self.uc.mem_map(0, 0x40000, u.UC_PROT_READ | u.UC_PROT_EXEC)
        self.uc.mem_map(0x820000, 0x30000, u.UC_PROT_READ | u.UC_PROT_EXEC)
        self.uc.mem_write(BIAS, image)
        self.uc.mem_map(0x200000, 0x30000, u.UC_PROT_READ | u.UC_PROT_WRITE)
        self.uc.mem_map(self.I2C, 0x1000, u.UC_PROT_READ | u.UC_PROT_WRITE)
        self.uc.mem_write(m["mutex"], struct.pack("<I", 0x1234))
        self.uc.mem_write(0x20011C, struct.pack("<I", self.DELAY | 1))
        self.uc.mem_write(m["driver"], b"\x23")
        self.uc.mem_write(m["samples"], b"\x01\x01\x01\0\0\0\0\0")
        self.uc.mem_write(m["poll"], struct.pack("<I", 4))  # Bounded synthetic timeout, not stock's 0xfffff.
        self.payloads = {0x0C: b"\0", 0x3F: b""}
        self.fail_after: dict[int, int] = {}
        self.abort_bits = 0
        self.mutex_ok = True
        self.tx_empty, self.master_busy = True, False
        self.transactions, self.publications, self.events = [], [], []
        self.current = None
        self.requests = self.reads = self.destination_writes = 0
        self.delay_calls = self.unready_reads = 0
        self.executed = set()
        self.returned = False
        self.encoding = False
        self.encoded_packet = None
        self.stack_low = self.STACK
        self.uc.hook_add(u.UC_HOOK_CODE, self._code)
        self.uc.hook_add(u.UC_HOOK_MEM_READ, self._read)
        self.uc.hook_add(u.UC_HOOK_MEM_WRITE, self._write)

    def _regs(self):
        return [self.uc.reg_read(getattr(self.a, f"UC_ARM_REG_R{i}")) for i in range(4)]

    def _return(self, result=0):
        self.uc.reg_write(self.a.UC_ARM_REG_R0, result)
        self.uc.reg_write(self.a.UC_ARM_REG_PC, self.uc.reg_read(self.a.UC_ARM_REG_LR))

    def _ready(self):
        if not self.current:
            return False
        reg = self.current["register"]
        return self.reads < self.requests and self.reads < len(self.payloads[reg]) and \
            self.reads < self.fail_after.get(reg, 0x10000)

    def _read(self, uc, access, address, size, value, _):
        if self.I2C <= address < self.I2C + 0x1000:
            if size != 4 or address - self.I2C not in (4, 0x10, 0x54, 0x70, 0x80):
                raise FifoProofError("unreviewed MMIO read")
            reg = address - self.I2C
            if reg == 0x70:
                value = 2 | (4 if self.tx_empty else 0) | (0x20 if self.master_busy else 0) | (8 if self._ready() else 0)
            elif reg == 0x80:
                failed = self.current and self.reads >= self.fail_after.get(self.current["register"], 0x10000)
                value = self.abort_bits if failed else 0
            elif reg == 0x10:
                if self._ready():
                    value = self.payloads[self.current["register"]][self.reads]
                    self.reads += 1
                else:
                    self.unready_reads += 1
                    value = 0xEE
            else:
                return
            uc.mem_write(address, struct.pack("<I", value))
            return
        m = self.map
        if BIAS <= address <= address + size <= self.image_end or \
            self.STACK - 4096 <= address <= address + size <= self.STACK or \
            self.OUTPUT <= address <= address + size <= self.OUTPUT + 192 or \
            any(start <= address <= address + size <= end for start, end in (
                (m["mutex"], m["mutex"] + 4), (m["poll"], m["poll"] + 4),
                (m["state"], m["state"] + 5), (m["busy"], m["busy"] + 1),
                (m["driver"], m["driver"] + 0x30 + 12 + 492), (0x20011C, 0x200120))):
            return
        raise FifoProofError(f"unreviewed memory read {address:#x}+{size}")

    def _write(self, uc, access, address, size, value, _):
        m = self.map
        if self.I2C <= address < self.I2C + 0x1000:
            if size != 4 or address - self.I2C not in (4, 0x10):
                raise FifoProofError("unreviewed MMIO write")
            if address == self.I2C + 0x10:
                if value & 0x100:
                    self.requests += 1
                elif not self.current or value != self.current["register"]:
                    raise FifoProofError("unexpected register-address write")
            return
        if self.current and self.current["destination"] <= address < self.current["destination"] + self.current["requested"]:
            if size == 1:
                self.destination_writes += 1
        if address == m["samples"] + 8:
            if size != 2 or uc.reg_read(self.a.UC_ARM_REG_PC) != BIAS + m["publish"] or value >= 492 or value % 6:
                raise FifoProofError("unexpected producer publication")
            self.publications.append(value)
        if address == m["driver"] + 3 and size == 1 and \
            uc.reg_read(self.a.UC_ARM_REG_PC) - BIAS in (
                m["watchdog"] + 0x0A, m["watchdog"] + 0x14, m["watchdog"] + 0x1A):
            return  # Actual empty-drain watchdog reset/increment, not arbitrary driver RAM.
        if self.STACK - 4096 <= address <= address + size <= self.STACK or \
            self.OUTPUT <= address <= address + size <= self.OUTPUT + 192 or \
            any(start <= address <= address + size <= end for start, end in (
                (m["state"], m["state"] + 5), (m["busy"], m["busy"] + 1),
                (m["samples"], m["samples"] + 8),
                (m["samples"] + 8, m["samples"] + 10),
                (m["samples"] + 12, m["samples"] + 12 + 492))):
            return
        raise FifoProofError(f"unreviewed memory write {address:#x}+{size}")

    def _code(self, uc, address, size, _):
        m, (r0, r1, r2, _) = self.map, self._regs()
        self.stack_low = min(self.stack_low, uc.reg_read(self.a.UC_ARM_REG_SP))
        if self.encoding and address == BIAS + m["notify"]:
            if r0 != self.STACK - 60:
                raise FifoProofError("unexpected raw packet address")
            self.encoded_packet = bytes(uc.mem_read(r0, 16))
            self.returned = True
            uc.emu_stop()  # Observe the send boundary; do not execute transport.
            return
        if address == self.STOP:
            self.returned = True
            uc.emu_stop()
            return
        if address in (0x133F4, 0x1341C):  # ROM OS mutex stubs, not RTOS scheduling.
            if r0 != 0x1234 or (address == 0x133F4 and r1 != 100):
                raise FifoProofError("unexpected mutex arguments")
            if uc.reg_read(self.a.UC_ARM_REG_SP) % 8:
                raise FifoProofError("unaligned public ROM mutex call")
            self.events.append("mutex_take" if address == 0x133F4 else "mutex_give")
            self._return(int(self.mutex_ok))
            return
        if address == self.DELAY:
            if r0 != 10:
                raise FifoProofError("unexpected delay argument")
            self.delay_calls += 1
            self._return()
            return
        if address in (0x3F848, 0x3F918):
            length = r2 if address == 0x3F848 else r1
            if length > 492:
                raise FifoProofError("unexpected memory helper length")
            self._write(uc, 0, r0, length, 0, None)
            if address == 0x3F848:
                self._read(uc, 0, r1, length, 0, None)
                data = bytes(uc.mem_read(r1, length))
            else:
                data = bytes(length)
            uc.mem_write(r0, data)
            self._return(r0)
            return
        offset = address - BIAS
        ranges = ((m["read"], m["read"] + 52), (m["bus"], m["bus"] + 28),
                  (m["transfer"] - 4, m["transfer"] + 142), (m["cleanup"], m["cleanup"] + 82),
                  (m["target"], m["target"] + 20), (m["flags"], m["flags"] + 14),
                  (m["receive"], m["receive"] + 188), (m["abort"], m["abort"] + 64),
                  (m["watchdog"], m["drain"] + 0x27A))
        if self.encoding:
            ranges += ((m["encoder"], m["encoder"] + 42),
                       (m["encoder_tail"], m["encoder_tail"] + 14),
                       (m["checksum"], m["checksum"] + 26))
        if not any(lo <= offset < hi for lo, hi in ranges):
            raise FifoProofError(f"unreviewed execution {offset:#x}")
        self.executed.add(offset)
        if offset == m["read"]:
            if r0 not in self.payloads or not 0 < r2 <= 192:
                raise FifoProofError("unreviewed sensor transaction")
            self.current = dict(register=r0, destination=r1, requested=r2)
            self.reads = self.requests = self.destination_writes = 0
            self.events.append(f"read_{r0:02x}_begin")
        elif offset == m["read"] + 46:  # pop, after final mov r0,r4
            transaction = dict(self.current, result=r0, cpu_bytes_written=self.destination_writes,
                peripheral_bytes_read=self.reads,
                data=bytes(uc.mem_read(self.current["destination"], self.current["requested"])).hex())
            self.transactions.append(transaction)
            self.events.append(f"read_{self.current['register']:02x}_end")
            self.current = None

    def call(self, offset: int, *args: int, budget=100_000) -> int:
        if len(args) > 4:
            raise ValueError("at most four register arguments")
        for i, value in enumerate((*args, 0, 0, 0, 0)[:4]):
            self.uc.reg_write(getattr(self.a, f"UC_ARM_REG_R{i}"), value)
        saved = [0xA0000000 + i for i in range(4, 12)]
        for i, value in enumerate(saved, 4):
            self.uc.reg_write(getattr(self.a, f"UC_ARM_REG_R{i}"), value)
        self.uc.reg_write(self.a.UC_ARM_REG_SP, self.STACK)
        self.uc.reg_write(self.a.UC_ARM_REG_LR, self.STOP | 1)
        self.returned = False
        self.uc.emu_start((BIAS + offset) | 1, 0xFFFFFFFF, count=budget)
        if not self.returned:
            raise FifoProofError("instruction budget exhausted")
        if self.uc.reg_read(self.a.UC_ARM_REG_SP) != self.STACK or \
            any(self.uc.reg_read(getattr(self.a, f"UC_ARM_REG_R{i}")) != value for i, value in enumerate(saved, 4)):
            raise FifoProofError("callee-saved registers or stack not restored")
        return self.uc.reg_read(self.a.UC_ARM_REG_R0)

    def read(self, register: int, payload: bytes) -> dict:
        if register not in self.payloads or not 0 < len(payload) <= 192:
            raise ValueError("supported test register/length only")
        self.payloads[register] = payload
        self.uc.mem_write(self.OUTPUT - 16, b"\xa5" * (len(payload) + 32))
        self.call(self.map["read"], register, self.OUTPUT, len(payload))
        if bytes(self.uc.mem_read(self.OUTPUT - 16, 16)) != b"\xa5" * 16 or \
            bytes(self.uc.mem_read(self.OUTPUT + len(payload), 16)) != b"\xa5" * 16:
            raise FifoProofError("read output overrun")
        return self.transactions[-1]

    def drain(self, status: int, payload: bytes) -> dict:
        if not 0 <= status <= 255 or len(payload) > 192:
            raise ValueError("invalid synthetic status/payload")
        self.payloads = {0x0C: bytes([status]), 0x3F: payload}
        before = len(self.transactions)
        self.call(self.map["drain"])
        producer, health = struct.unpack("<HH", self.uc.mem_read(self.map["samples"] + 8, 4))
        return {"transactions": self.transactions[before:], "producer": producer, "health": health,
                "buffer": bytes(self.uc.mem_read(self.map["samples"] + 12, producer)).hex(),
                "scope": "synthetic MMIO plus unmodified image instructions, NOT physical acquisition"}

    def encode_raw(self, frame: bytes) -> bytes:
        """Execute stock encoder/checksum only, from native words in caller stack.

        Does NOT call raw acquisition or send/queue notifications. This slice is
        not a complete function, so only its unchanged stack is asserted here.
        """
        native_to_model_counts(frame)  # Exact-size/type check, no interpretation changes.
        w0, w1, w2 = struct.unpack("<HHH", frame)
        sp = self.STACK - 64
        self.uc.mem_write(sp, bytes(64))
        self.uc.mem_write(sp + 4, b"\xa1")
        for at, value in ((0x18, w0), (0x1C, w1), (0x14, w2)):
            self.uc.mem_write(sp + at, struct.pack("<H", value))
        self.uc.reg_write(self.a.UC_ARM_REG_SP, sp)
        self.uc.reg_write(self.a.UC_ARM_REG_R6, 0)
        self.encoding, self.returned, self.encoded_packet = True, False, None
        try:
            self.uc.emu_start((BIAS + self.map["encoder"]) | 1, 0xFFFFFFFF, count=2000)
            if not self.returned or self.uc.reg_read(self.a.UC_ARM_REG_SP) != sp or not self.encoded_packet:
                raise FifoProofError("encoder did not reach packet boundary with restored stack")
            return self.encoded_packet
        finally:
            self.encoding = False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captures", nargs="+", type=Path)
    args = parser.parse_args(argv)
    print(json.dumps([audit_capture(path) for path in args.captures], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
