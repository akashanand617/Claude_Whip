"""Pinned, OFFLINE FEE7 AD-element removal plan; no image or BLE writer.

Only the 16-bit service-list element is removed. The existing opaque
manufacturer element, including its FE E7 bytes, is deliberately preserved.
The two callers use stock GAP parameter 0x262; no public SDK value is assumed.
This is not advertising success, full boot execution or reclamation approval.
"""
from dataclasses import dataclass
import hashlib

from whip.fwunified import STOCK_SHA256


@dataclass(frozen=True)
class AdvertisingEdit:
    file_offset: int
    before: bytes
    after: bytes


_EDITS = (
    (0x749C, "2070", "00bf"), (0x749E, "6070", "00bf"),
    (0x74A2, "a570", "00bf"), (0x74A6, "e670", "00bf"),
    (0x74B6, "2071", "2070"), (0x74BA, "6071", "6070"),
    (0x74BE, "a071", "a070"), (0x74C2, "e071", "e070"),
    (0x74C6, "2672", "2671"), (0x74C8, "0a21", "0621"),
    (0x74CA, "6572", "6571"), (0x74E6, "1f21", "0c21"),
    (0x75FE, "1f21", "0c21"),
)


def advertising_plan(stock: bytes) -> tuple[AdvertisingEdit, ...]:
    """Return 13 fixed, size-neutral Thumb edits for emulator memory only.

    No arbitrary address/UUID/length is accepted. Both submission lengths must
    accompany the packed builder: bytes beyond its 12-byte result are not
    assumed zero. Exact stock identity is mandatory, including untouched code.
    """
    if hashlib.sha256(stock).hexdigest() != STOCK_SHA256:
        raise ValueError("FEE7 advertising plan requires exact pinned stock")
    result = tuple(AdvertisingEdit(o, bytes.fromhex(a), bytes.fromhex(b))
                   for o, a, b in _EDITS)
    for edit in result:
        if stock[edit.file_offset:edit.file_offset + 2] != edit.before:
            raise ValueError("FEE7 advertising instruction mismatch")
    if stock[0x7774:0x777C] != bytes.fromhex("61020000219e2000"):
        raise ValueError("FEE7 advertising parameter/buffer literal mismatch")
    return result


def advertising_report(stock: bytes) -> dict:
    edits = advertising_plan(stock)
    return {
        "schema": "whip.wechat-advertising-plan.v1",
        "stock_sha256": hashlib.sha256(stock).hexdigest(),
        "edits": [{"file_offset": e.file_offset, "before_hex": e.before.hex(),
                   "after_hex": e.after.hex()} for e in edits],
        "instruction_edit_bytes": 26, "added_flash_bytes": 0,
        "added_ram_bytes": 0, "gap_parameter": 0x262,
        "buffer_address": 0x209E21, "submitted_length": 12,
        "manufacturer_data_preserved": True,
        "stock_file_modified": False, "stock_hooks_attached": False,
        "flashable": False,
        "limits": "Fixed builder and two submission slices only; source MAC, "
                  "other boot work and ROM GAP result are explicit fixtures. "
                  "No full path closure, physical advertising, app discovery, "
                  "Health continuity, resource ownership or recovery proof.",
    }
