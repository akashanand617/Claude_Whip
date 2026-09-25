"""Read-only audit and hard construction gate for the STOCK-based unified image.

This intentionally cannot emit an OTA image. A successful container audit does
not establish spare flash/RAM, stock hooks, shared-sensor ownership or recovery.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass

from whip import fwbuild

STOCK_SHA256 = "b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0"
STOCK_SIZE = 138016
HARDWARE = "RT02CR_V3.1"
BLOCKERS = (
    "stock code placement, actual OTA bank capacity and branch/literal/relocation ranges unproven",
    "reserved RAM, stack budget and RTOS serialization unproven",
    "optical/indicator adapter cancellation, physical stop and result-publication fencing unproven",
    "stock steps/sleep continuity, verified 25 Hz source and shared accelerometer serialization unproven",
    "remaining stock DFU, boot, storage and calibration protected ranges incomplete",
    "collision-free command namespace and image identity not allocated",
    "independent Thumb execution/fault-injection of stock-linked candidate not performed (test ELF is artificial)",
    "reviewed physical validation/recovery plan not completed; daily-ring tests require specific risk review",
)


@dataclass(frozen=True)
class StockAudit:
    sha256: str
    size: int
    hardware: str
    vendor_not_ready: bool
    vendor_payload_sha_matches: bool
    errors: tuple[str, ...]
    startup_layout: dict | None
    motion_layout: dict | None
    construction_blockers: tuple[str, ...] = BLOCKERS

    def as_dict(self) -> dict:
        return asdict(self)


def audit_stock(data: bytes) -> StockAudit:
    digest = hashlib.sha256(data).hexdigest()
    errors = []
    hardware = data[0x30:0x50].split(b"\0", 1)[0].decode("ascii", errors="replace")
    if digest != STOCK_SHA256:
        errors.append("not the pinned vendor stock image; never transplant V2 offsets")
    if len(data) != STOCK_SIZE:
        errors.append("unexpected stock image length")
    if data[:4] != bytes.fromhex("e5c3bd81"):
        errors.append("invalid RT02CR container magic")
    if hardware != HARDWARE:
        errors.append("hardware mismatch")
    actual = fwbuild.read_fields(data)
    expected = fwbuild.expected_fields(data)
    if actual.body_sum != expected.body_sum:
        errors.append("body checksum mismatch")
    if actual.payload_length != expected.payload_length:
        errors.append("payload length mismatch")
    layout = None
    motion = None
    if digest == STOCK_SHA256:
        # Independently inspected stock startup 0x4a0: two memcpy calls then
        # __rt_memclr. Literal pool 0x768, not the different 25 Hz image layout.
        words = [int.from_bytes(data[i:i + 4], "little") for i in range(0x768, 0x788, 4)]
        assert words == [0x8B0, 0x846C78, 0x207C00, 0x4E0, 0x847528, 0x2084B0, 0x5DA4, 0x208990]
        layout = {
            "runtime_minus_file": 0x825FB0,
            "startup_function_file": 0x4A0,
            "ram_code_copy": {"file_start": 0x20CC8, "file_end_exclusive": 0x21578,
                              "ram_start": 0x207C00, "ram_end_exclusive": 0x2084B0},
            "data_copy": {"file_start": 0x21578, "file_end_exclusive": 0x21A58,
                          "ram_start": 0x2084B0, "ram_end_exclusive": 0x208990},
            "bss_clear": {"ram_start": 0x208990, "ram_end_exclusive": 0x20E734},
            "boot_overlay": {"file_start": 0x21A58, "file_end_exclusive": 0x21B20,
                             "ram_start": 0x20E734, "ram_end_exclusive": 0x20E7FC,
                             "descriptor_file": 0x21578, "loader_file": 0xA34},
            "unclassified_file_tail_bytes": 0,
            "safe_controller_allocation": None,
            "warning": "copy/clear and boot overlay boundaries; NOT an approved free-space or stack/heap ownership map",
        }
        # Stock-only anchors, backed by the separately run bounded Thumb tests.
        # Recording anchors here does not assert those tests ran or clear a gate.
        assert data[0x80F8:0x80FC] == bytes.fromhex("7d21c900")
        assert data[0xCBA8:0xCBAE] == bytes.fromhex("20896081e570")
        motion = {
            "driver_ram": 0x20BD98,
            "sample_state_ram": 0x20BDC8,
            "producer_cursor_ram": 0x20BDD0,
            "health_cursor_ram": 0x20BDD2,
            "sample_buffer_ram": 0x20BDD4,
            "capacity_samples": 82,
            "bytes_per_sample": 6,
            "fifo_drain_file": 0xC280,
            "producer_publish_file": 0xC4E8,
            "raw_reader_file": 0xCC32,
            "health_consumer_file": 0xCD60,
            "health_algorithm_feed_file": 0x1D9D8,
            "wake_file": 0xCB5E,
            "wake_discards_pending_health_file": 0xCBAA,
            "protected_dfu_timer_file": 0x80F8,
            "warning": "serialized data-path evidence only; not health accuracy, RTOS or safe allocation proof",
        }
    # Vendor not_ready/stale SHA are recorded, not 'fixed' in a read-only audit.
    return StockAudit(digest, len(data), hardware, actual.not_ready,
                      actual.sha256 == expected.sha256, tuple(errors), layout, motion)


def build(data: bytes) -> bytes:
    audit = audit_stock(data)
    raise ValueError("Unified OTA construction blocked: " + "; ".join(audit.errors + BLOCKERS))
