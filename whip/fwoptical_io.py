"""Exact-stock OFFLINE two-call-site plan; never emits an image or touches BLE.

The two replacements are tested in emulator memory only. A structural plan is
not placement/recovery, lifecycle/source provenance or flash authorization.
"""
from dataclasses import dataclass
import hashlib
import struct

from whip.fwstock_link import inspect_elf

BIAS = 0x825FB0
SIGNATURE = bytes.fromhex('2d990122087004a9fe20fdf7c7f90526f643401c0fd03a460ba9ff20fdf7a2f9401c08d0')
SITES = ((0x11A80, bytes.fromhex('fdf7c7f9')), (0x11A92, bytes.fromhex('fdf7a2f9')))


def _bl(source, thumb_target):
    if source & 1 or not thumb_target & 1:
        raise ValueError('aligned instruction and Thumb target required')
    offset = (thumb_target & ~1) - (source + 4)
    if not -(1 << 24) <= offset < (1 << 24) or offset & 1:
        raise ValueError('Thumb BL range exceeded')
    bits = offset & 0x1FFFFFF
    sign, i1, i2 = (bits >> 24) & 1, (bits >> 23) & 1, (bits >> 22) & 1
    hi = 0xF000 | (sign << 10) | ((bits >> 12) & 0x3FF)
    lo = 0xD000 | ((1 ^ i1 ^ sign) << 13) | ((1 ^ i2 ^ sign) << 11) | ((bits >> 1) & 0x7FF)
    return struct.pack('<HH', hi, lo)


@dataclass(frozen=True)
class CallEdit:
    file_offset: int
    before: bytes
    after: bytes
    target: int


def sample_io_plan(stock, component_elf, descriptor):
    """Two fixed BL edits bound to exact stock and checked actual-address ELF.

    Does not refresh container fields, append code, write files, build OTA or
    qualify hooks. The unmodified reader still needs wop_read/original lifetime,
    owned objects, serialized source/RTOS and all physical/integration gates.
    """
    report = inspect_elf(component_elf, stock, descriptor)
    if stock[0x11A76:0x11A9A] != SIGNATURE:
        raise ValueError('optical sample call-site signature mismatch')
    target = report['functions']['woi_samples_io']
    return tuple(CallEdit(site, before, _bl(BIAS + site, target), target) for site, before in SITES)


def sample_io_report(stock, component_elf, descriptor):
    edits = sample_io_plan(stock, component_elf, descriptor)
    return {
        'schema': 'whip.optical-io-call-plan.v1',
        'stock_sha256': hashlib.sha256(stock).hexdigest(),
        'component_elf_sha256': hashlib.sha256(component_elf).hexdigest(),
        'descriptor_sha256': hashlib.sha256(descriptor).hexdigest(),
        'edits': [{'file_offset': e.file_offset, 'runtime_address': BIAS + e.file_offset,
                   'before_hex': e.before.hex(), 'after_hex': e.after.hex(),
                   'thumb_target': e.target} for e in edits],
        'replacement_instruction_bytes': 8,
        'stock_file_modified': False, 'stock_hooks_attached': False, 'flashable': False,
        'scope': 'two fixed BL instructions for emulator execution; not an OTA image or approval',
        'requirements': 'both edits plus original lifetime, owned buffers, serialized RTOS/source, '
                        'all result fences, complete fit, physical validation and recovery remain required',
    }
