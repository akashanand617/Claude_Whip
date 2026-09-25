"""Prepared fixed gateway/entry-slot DATA diagnostic; never follow or call it.

Requires fresh exclusive-idle coordination. CD01 changes bookkeeping. The
32-byte ROM cap is not a function boundary or a complete callback-dispatch
implementation. The named four-byte slot is read as uninterpreted data only.
No BLE connection, MMIO, OTP, key, sensor, flash or target-execution API here.
"""
import hashlib

from whip import fwcapacity, fwcapacity_read as cr, fwrom_read as rr

SCHEMA = 'whip.stack-gateway.capture.v1'
# Public pinned ROM map supplies Thumb entry0x4927. Use its even byte address.
# This intentionally small cap stays below next named update_ram_layout0x4a78;
# that next symbol establishes neither the intervening ownership nor size.
# It is NOT evidence that all32 bytes are instructions or a whole function.
GATEWAY_WINDOW = (0x4926, 32)
# The pinned map names this one word; adjacent app_pre_main/app_main excluded.
ENTRY_SLOT_WINDOW = (0x2011D4, 4)
WINDOWS = (('gateway_entry_cap', *GATEWAY_WINDOW),
           ('upperstack_entry_slot', *ENTRY_SLOT_WINDOW))
EXPECTED_TRANSACTIONS = 91 + 4 + 12 + 8 + 7


def validate_callers(base, candidate):
    """Local image witnesses, not additional on-device read/attestation sites.

    V2/original25Hz wrapper differs in file position from stock3.12.02. Never
    transplant stock156bc into the installed-lineage diagnostic's local proof.
    These constants corroborate known entry/slot addresses, not gateway logic.
    """
    for image in (base, candidate):
        for offset, expected in (
                (0x15518, bytes.fromhex('014610b5ff200830c9f729da10bd')),
                (0x6D4, bytes.fromhex('4b4900220860')),
                (0x804, bytes.fromhex('d4112000'))):
            if image[offset:offset + len(expected)] != expected:
                raise ValueError('gateway/entry-slot local caller witness mismatch')


def validate_symbols(symbols):
    if hashlib.sha256(symbols).hexdigest() != rr.SYMBOLS_SHA256:
        raise ValueError('unreviewed gateway symbol map')
    for line in (b'SystemCall_Stack = 0x00004927 ;',
                 b'update_ram_layout = 0x00004a79 ;',
                 b'app_pre_main = 0x002011d0 ;',
                 b'upperstack_entry = 0x002011d4 ;',
                 b'app_main = 0x002011d8 ;'):
        if line not in symbols.splitlines():
            raise ValueError('gateway/entry-slot symbol boundary mismatch')


class StackGatewayReader(cr.DescriptorReader):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._gateway_phase = None
        self._started = self.closed = False

    def _allowed_reads(self):
        if self.closed:
            return frozenset()
        allowed = super()._allowed_reads()
        phases = {name: (a, n) for name, a, n in WINDOWS}
        phases.update(identifier=rr.UUID_WINDOW, known_stop=rr.TIMER_WINDOW)
        if self._gateway_phase in phases:
            allowed |= frozenset(cr.chunks(*phases[self._gateway_phase]))
        return allowed


async def collect(reader, base, candidate, symbols, session_id, prior_stop):
    if not isinstance(reader, StackGatewayReader):
        raise ValueError('separate fixed stack-gateway reader required')
    if reader._started or reader.closed:
        raise RuntimeError('stack-gateway session already used; no retry')
    reader._started = True
    try:
        rr.validate_references(base, candidate, symbols)
        validate_symbols(symbols)
        validate_callers(base, candidate)
        known_stop = rr.validate_prior_capture(prior_stop)
        config = await cr.collect_bank0_descriptor(reader, base, candidate, session_id)
        descriptor = next(w for w in config['windows'] if w['address'] == cr.BANK0_DESCRIPTOR_WINDOW[0])
        if hashlib.sha256(bytes.fromhex(descriptor['data_hex'])).hexdigest() != rr.DESCRIPTOR_SHA256:
            raise RuntimeError('unreviewed descriptor; no gateway read')
        reader._gateway_phase = 'identifier'
        for _ in range(2):
            if await reader.window(*rr.UUID_WINDOW) != rr.ROM_UUID:
                raise RuntimeError('application ROM identifier differs; no gateway read')
        reader._gateway_phase = 'known_stop'
        for _ in range(2):
            if await reader.window(*rr.TIMER_WINDOW) != known_stop:
                raise RuntimeError('known ROM code differs; no gateway read')
        windows = {}
        for name, address, length in WINDOWS:
            reader._gateway_phase = name
            first = await reader.window(address, length)
            repeated = await reader.window(address, length)
            reader._gateway_phase = None
            if first != repeated:
                raise RuntimeError('gateway code/slot changed across repeats: ' + name)
            windows[name] = {'address': address, 'data_hex': first.hex(),
                             'sha256': hashlib.sha256(first).hexdigest()}
        for address, length in cr.CONFIG_WINDOWS:
            expected = cr.EXPECTED_RAM_CONFIG if address == fwcapacity.RAM_CONFIG_ADDRESS else cr.EXPECTED_FLASH_CONFIG
            if await reader.window(address, length) != expected:
                raise RuntimeError('configuration changed during gateway read')
        if await reader.read(*cr.IDLE_WINDOW) != b'\0':
            raise RuntimeError('raw mode changed during gateway read')
        reader.emit({'kind': 'stack_gateway', 'new_rom_cap_bytes': 32, 'entry_slot_bytes': 4,
                     'known_rom_bytes': 72, 'repeated_equal': True,
                     'pointer_following': False, 'target_execution': False})
        return {'schema': SCHEMA, 'evidence_kind': 'device_capture', 'session_id': session_id,
                'prerequisite_capture': config, 'symbols_sha256': rr.SYMBOLS_SHA256,
                'prior_stop_sha256': rr.PRIOR_CAPTURE_SHA256,
                'app_rom_identifier': rr.ROM_UUID.hex(), 'known_code_repeated_equal': True,
                'windows': windows, 'repeated_equal': True,
                'pointer_following': False, 'target_execution': False, 'keys_read': False,
                'entry_pointer_semantics_verified': False, 'callback_drain_verified': False,
                'complete_dispatch_verified': False, 'full_image_attestation': False,
                'recovery_verified': False, 'flash_authorized': False}
    except BaseException:
        reader.poisoned = True
        raise
    finally:
        reader._gateway_phase = None
        reader._descriptor_phase = False
        reader.closed = True
