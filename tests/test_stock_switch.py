"""One off-ring Health -> Gesture -> Health sequence, not a device emulator.

Actual-address C shares RAM with original stock optical reader/clear/bus and
motion drain/Health-consumer and notification-wrapper instructions. Only the
two reviewed optical BLs are replaced. All missing receipts are named fixtures, never inferred from
stock return values. No production job inventory/profile is supplied here.
"""
from io import BytesIO
import struct

import pytest
from elftools.elf.elffile import ELFFile

from tests.test_fwstock_link import linked  # noqa: F401
from tests.test_unified_thumb import elf  # noqa: F401
from tests.test_stock_optical_io import IOThumb
from tests.test_stock_optical_work import HEALTH, TICKET, REJECTED, BUFFER, STATUS
from whip.fwthumb import RuntimeThumb
from whip.fwcontinuity import FIFO_DRAIN, StockMotionHarness, BIAS
from tests.test_fwstock_link import STOCK
from tests.test_unified_wire import BOOT, frames, request, reply

HEALTH_MODE, ENTERING, GESTURE, RETURNING, FAULT = range(5)
NONE, QUIESCE, HOLD, START, STOP, RELEASE, RESUME = range(7)
SCRATCH = 0x225000  # generous emulator-only storage, NOT allocated ring RAM
TX_FRAME = SCRATCH + 512  # must not alias receipt or pending XYZ input


@pytest.fixture(scope='module')
def layout(elf):
    h = RuntimeThumb(elf)
    actual = tuple(h.call('proof_switch_layout', i) for i in range(6))
    assert actual == (408, 60, 288, 31, 223, 24)
    assert h.call('proof_switch_layout', 6) == 64
    assert h.call('proof_adapter_size') == 672
    return actual


class SwitchThumb(IOThumb):
    """Serialized host-driven calls into one persistent ARM address space.

    This runner is the coordinator; there is NO installed coordinator, real
    IRQ/hub fence, hardware STOP detector, source clock, GATT or resume binding.
    """
    def __init__(self, raw, layout, *, inventory=True, actual=True):
        super().__init__(raw, actual=actual)
        self.base = HEALTH - layout[0]
        self.fixtures = []
        self.observation_stack = []
        self.gatt_result = 1
        self.gatt_sends = []
        self.gatt_wrappers = 0
        for s in ELFFile(BytesIO(raw)).get_section_by_name('.symtab').iter_symbols():
            if s['st_info']['type'] == 'STT_FUNC' and s['st_size']:
                lo = s['st_value'] & ~1
                self.spans.append((lo, lo + s['st_size']))
        # Already reviewed stock server_send_data wrapper; NOT the legacy
        # queue, service registration, or ROM Bluetooth-stack implementation.
        self.spans.append((BIAS + 0x158EE, BIAS + 0x15918))
        # The wrapper shares this reviewed stack/pop return tail with the
        # earlier wrapper. No intervening registration path is admitted.
        self.spans.append((BIAS + 0x1584C, BIAS + 0x15850))
        self.adapter('wd_init', 1, int(inventory), BOOT & 0xFFFFFFFF, BOOT >> 32)
        # Numerically valid but invented physical evidence; never stock default.
        profile = struct.pack('<II32sIIHH6B2x', 1, 2, b'\xee' + bytes(31),
                              101, 2000, 20, 20, 0, 0x23, 5, 15, 0x74, 0xC8)
        self.uc.mem_write(SCRATCH, profile)
        self.fixture('inventory and physical profile', inventory)
        assert self.adapter('wa_prepare', SCRATCH)
        assert self.adapter('wd_open', 7, 0, 0)
        self.original = self.new_job() if inventory else None
        self.set_controls((5, 0x1F, 3, 1))

    def _code(self, uc, address, size, opaque):
        if address == BIAS + 0x158EE:
            self.gatt_wrappers += 1
        if address == 0x4926:  # explicit ROM SystemCall_Stack boundary
            r0, connection, service, attribute = [uc.reg_read(r) for r in self.registers]
            assert r0 == 0x3108 and attribute == 4
            assert (connection, service) == (3, 6)  # synthetic dedicated admission
            assert uc.reg_read(self.a.UC_ARM_REG_PRIMASK) == 0
            assert uc.reg_read(self.a.UC_ARM_REG_IPSR) == 0
            sp = uc.reg_read(self.a.UC_ARM_REG_SP)
            data, length, kind, result = struct.unpack('<4I', uc.mem_read(sp, 16))
            assert (data, length, kind) == (TX_FRAME, 20, 1)
            assert self.STACK - 512 <= result < self.STACK
            self.gatt_sends.append((connection, service, attribute, bytes(uc.mem_read(data, length))))
            uc.mem_write(result, bytes([self.fixture('ROM notification submission status', self.gatt_result)]))
            self._return(0xD00DFEED)  # actual wrapper must use the output byte
            return
        super()._code(uc, address, size, opaque)

    def fixture(self, name, value):
        self.fixtures.append((name, value))
        return value

    def adapter(self, name, *args):
        return self.function(name, self.base, *args)

    def mode(self, offset=0):
        return struct.unpack('<I', self.uc.mem_read(self.base + offset, 4))[0]

    @property
    def token(self): return self.mode(12)

    @property
    def session(self): return self.mode(16)

    def new_job(self):
        assert self.invoke('wh_job_begin', 0, TICKET)
        return struct.unpack('<IIB3x', self.uc.mem_read(TICKET, 12))

    def set_controls(self, values):
        for address, value in zip((0x208AAC, 0x208AAD, 0x208C44, 0x208C46), values, strict=True):
            self.uc.mem_write(address, bytes([value]))

    def controls(self): return self.function('wss_read_controls')

    def command(self, operation, request_id, now):
        for packet in frames(1, request_id, request(operation)):
            self.uc.mem_write(SCRATCH, packet)
            assert self.adapter('wd_receive', SCRATCH, len(packet), 7, now)

    def reply(self, operation, request_id, now):
        expected = frames(2, request_id, reply(operation, 0, self.mode(), 0, session=self.session))
        for part, packet in enumerate(expected):
            assert self.adapter('wd_reply_next', 7, SCRATCH, now)
            assert bytes(self.uc.mem_read(SCRATCH, 20)) == packet
            accepted = self.submit20(packet)
            assert self.adapter('wd_reply_sent', 7, request_id, part, accepted, now)

    def submit20(self, packet):
        # Caller serialization/admission/lifetime remain this runner's fixture,
        # not installed binding code. ROM acceptance is not radio delivery or
        # a proof the stack copied the buffer before returning.
        assert len(packet) == 20
        self.uc.mem_write(TX_FRAME, packet)
        return self.function('wg_stock_notify20', 3, 6, 4, TX_FRAME)

    def submit_motion(self, now):
        assert self.adapter('wa_next', self.session, SCRATCH, now)
        sequence, *xyz = struct.unpack('<Ihhh', self.uc.mem_read(SCRATCH, 10))
        assert self.function('ww_pack_motion', self.session, sequence, SCRATCH + 4, TX_FRAME)
        packet = bytes(self.uc.mem_read(TX_FRAME, 20))
        accepted = self.submit20(packet)
        assert self.adapter('wa_sent', self.session, sequence, accepted, now)
        return sequence, tuple(xyz), packet, accepted

    def physical(self, proof, now):
        self.uc.mem_write(SCRATCH, struct.pack('<6I', self.token, self.session,
                                              self.mode(4), proof, 1, 2))
        return self.adapter('wa_physical_done', SCRATCH, now)

    def commit(self, ticket, *, measured=True):
        # Algorithm value/source-to-job provenance remain a fixture, NOT derived
        # from wop_read's zero or from the plausible value 72.
        return self.function('wrc_commit_hr', HEALTH, *ticket,
                             self.fixture('measured optical provenance', int(measured)), 72, 0x1234)

    def stop_writes(self):
        return self.function('wb_stock_stop_writes', SCRATCH)

    def quiet_with_fixtures(self, now):
        quiesce_token = self.token
        assert self.fixture('all original jobs cancelled/drained', True)
        assert self.adapter('wa_cancelled', self.token, self.word(4), 1, now)
        assert self.fixture('IRQ/hub/RUN/publication fence', True)
        assert self.adapter('wa_fenced', self.token, self.word(4), now)
        assert self.stop_writes()  # real C -> original stock TX -> peripheral fixture
        assert self.mode(4) == QUIESCE  # writes alone MUST NOT change the mode
        assert self.adapter('wa_optics_stopped', self.token, self.word(4),
                            self.fixture('physical optics stopped', True), now)
        assert self.mode(4) == HOLD and self.word(0) == 2
        # HOLD has a newer controller token; retirement still names the Health
        # pause that actually completed. Never relabel it with current mode token.
        assert self.token != quiesce_token
        assert not self.retire(self.token)
        assert self.retire(quiesce_token)  # real C -> stock software clear

    def enter(self, now=1, *, requested=False):
        if not requested:
            assert self.adapter('wa_request', 1, now)
        assert (self.mode(), self.mode(4)) == (ENTERING, QUIESCE)
        self.quiet_with_fixtures(now)
        assert self.physical(self.fixture('held/preserved/configured/serialized source', 0x0F), now)
        assert (self.mode(), self.mode(4)) == (ENTERING, START)

    def observe(self, sample, now=1, *, fault=0, session=None, transaction=1):
        receipt = bytearray(288)
        session = self.session if session is None else session
        struct.pack_into('<6IHHBBB', receipt, 0, session, 1, 2, transaction,
                         now, now, 6, 6 if fault != 1 else 0,
                         0x81 if fault == 2 else 1, int(fault == 3), 1)
        struct.pack_into('<hhh', receipt, 31, *sample)
        # Bounds equal status time: checked C encoder supplies exact zero ages.
        self.uc.mem_write(SCRATCH, bytes(receipt))
        assert self.function('ws_set_bounds', SCRATCH, 0, now, now)
        self.fixture('physical acquisition time/completion/overflow', (now, fault))
        prior_low = self.stack_low
        self.stack_low = self.STACK
        result = self.adapter('wa_observe', SCRATCH, now)
        self.observation_stack.append(self.STACK - self.stack_low)
        self.stack_low = min(prior_low, self.stack_low)
        return result

    def drain_motion(self, samples):
        # Original stock drain/consumer, no raw-reader wake or gesture drain.
        self.fifo.extend(samples)
        self.call(FIFO_DRAIN)
        return self.consume_health()

    def to_resume(self, now=2):
        if self.mode() != RETURNING:
            assert self.adapter('wa_request', 0, now)
        assert self.mode(4) == STOP
        assert self.physical(self.fixture('source/callback/transport drained', 0x70), now)
        assert self.mode(4) == RELEASE
        assert self.physical(self.fixture('accel released without disturbing Health', 0x82), now)
        assert (self.mode(), self.mode(4)) == (RETURNING, RESUME)

    def resume_ready(self, revision=17, now=2):
        assert self.adapter('wa_begin_resume', self.token, revision, now)
        assert self.adapter('wa_resume_ready', self.token, self.word(4), revision,
                            self.fixture('non-optical Health state preserved', True),
                            self.fixture('fresh scheduler rebound to current settings', True), now)
        assert not self.adapter('wa_health_allowed', 0)


def test_same_arm_context_runs_stock_reads_switch_motion_and_fresh_health_job(linked, layout):
    h = SwitchThumb(linked, layout)
    baseline = StockMotionHarness(STOCK)
    initial_controls = h.controls()
    assert h.mode() == HEALTH_MODE and h.adapter('wa_health_allowed', 0)
    assert h.read() == 0 and h.commit(h.original)
    old = h.original
    batches = [[(10, -20, 8005), (11, -21, 8006)],
               [(30, -40, 8010)], [(50, -60, 8020)]]
    baseline.fifo.extend(batches[0]); baseline.call(FIFO_DRAIN)
    assert h.drain_motion(batches[0]) == baseline.consume_health()
    h.command(3, 1, 1)
    assert not h.adapter('wd_reply_next', 7, SCRATCH, 1)
    h.enter(requested=True)
    assert not h.adapter('wd_reply_next', 7, SCRATCH, 1)
    assert h.read() == REJECTED and not h.commit(old)
    assert h.controls() == initial_controls
    # Same original batch reaches Health's consumer and Gesture's copy. Only
    # the receipt timing/completion metadata is simulated, not two drain calls.
    baseline.fifo.extend(batches[1]); baseline.call(FIFO_DRAIN)
    assert h.drain_motion(batches[1]) == baseline.consume_health()
    assert h.observe(batches[1][0]) == 2
    assert h.observation_stack[-1] <= 244  # full observed path, external receipt excluded
    assert h.mode() == GESTURE and not h.adapter('wa_health_allowed', 0)
    h.reply(3, 1, 1)
    sequence, xyz, motion_packet, accepted = h.submit_motion(1)
    assert sequence == 1 and xyz == batches[1][0] and accepted
    assert h.adapter('wa_renew', h.session, 1, 1)
    old_session = h.session
    h.command(2, 2, 2)
    h.to_resume()
    h.set_controls((60, 0x04, 3, 1))  # user changed current settings during Gesture
    changed = h.controls()
    assert changed != initial_controls
    h.resume_ready()
    assert not h.adapter('wd_reply_next', 7, SCRATCH, 2)
    assert not h.commit(old)
    assert h.adapter('wa_commit_health', h.token, 17, 2)
    assert h.mode() == HEALTH_MODE and h.adapter('wa_health_allowed', 0)
    h.reply(2, 2, 2)
    assert h.controls() == changed  # no restored cached settings, clock or history
    assert h.observe(batches[1][0], now=2, session=old_session) == 0
    assert not h.commit(old) and h.read(ticket=old) == REJECTED
    new = h.new_job()
    assert new[0] > old[0] and new[1] > old[1]
    h.configure_samples()  # simulated fresh hardware job setup, not resume code
    h.fixture('fresh optical acquisition configuration', True)
    assert h.read(ticket=new) == 0 and h.commit(new)
    baseline.fifo.extend(batches[2]); baseline.call(FIFO_DRAIN)
    assert h.drain_motion(batches[2]) == baseline.consume_health()
    assert h.health_inputs == baseline.health_inputs
    assert h.cursor(health=True) == baseline.cursor(health=True)
    assert h.transfers == [b'\xfe\0', b'\x7b\xa5', b'\x7b\0', b'\xfe\0']
    assert not h.allocations and not h.timer_calls
    assert h.gatt_wrappers == len(h.gatt_sends) == 5  # two replies + one motion
    assert h.gatt_sends[2] == (3, 6, 4, motion_packet)
    # Explicitly NOT a closed integration: each missing binding stays visible.
    assert len(h.fixtures) >= 12


@pytest.mark.parametrize('status', [0, 2, 255])
@pytest.mark.parametrize('part', [0, 1])
def test_original_notify_refusal_closes_control_and_starts_health_cleanup(linked, layout, status, part):
    h = SwitchThumb(linked, layout)
    h.command(3, 1, 1); h.enter(requested=True)
    assert h.observe((1, 2, 8005)) == 2
    for i in range(part + 1):
        assert h.adapter('wd_reply_next', 7, SCRATCH, 1)
        packet = bytes(h.uc.mem_read(SCRATCH, 20))
        h.gatt_result = status if i == part else 1
        accepted = h.submit20(packet)
        assert bool(h.adapter('wd_reply_sent', 7, 1, i, accepted, 1)) == (i != part)
    assert h.gatt_wrappers == len(h.gatt_sends) == part + 1
    assert (h.mode(), h.mode(4)) == (RETURNING, STOP)
    assert not h.adapter('wd_reply_next', 7, SCRATCH, 1)
    assert not h.adapter('wa_next', h.session, SCRATCH, 1)
    assert not h.adapter('wa_health_allowed', 0)  # cleanup is NOT restored Health
    assert h.drain_motion([(9, 10, 8005)]) == [(10, 9, 8005)]
    h.to_resume(); h.resume_ready()
    assert h.adapter('wa_commit_health', h.token, 17, 2)
    assert h.adapter('wa_health_allowed', 0)


@pytest.mark.parametrize('status', [0, 2, 255])
def test_original_notify_refusal_never_renews_motion_lease(linked, layout, status):
    h = SwitchThumb(linked, layout); h.enter()
    assert h.observe((1, 2, 8005)) == 2
    h.gatt_result = status
    sequence, _, _, accepted = h.submit_motion(1)
    assert not accepted and h.gatt_wrappers == 1
    assert (h.mode(), h.mode(4)) == (RETURNING, STOP)
    assert not h.adapter('wa_renew', h.session, sequence, 1)
    assert not h.adapter('wa_next', h.session, SCRATCH, 1)
    assert not h.adapter('wa_health_allowed', 0)


@pytest.mark.parametrize('status', [0, 2, 255])
@pytest.mark.parametrize('part', [0, 1])
def test_notify_refusal_after_health_commit_does_not_undo_default_health(linked, layout, status, part):
    h = SwitchThumb(linked, layout); h.enter()
    assert h.observe((1, 2, 8005)) == 2
    h.command(2, 1, 2)
    h.to_resume(); h.resume_ready()
    assert h.adapter('wa_commit_health', h.token, 17, 2)
    for i in range(part + 1):
        assert h.adapter('wd_reply_next', 7, SCRATCH, 2)
        h.gatt_result = status if i == part else 1
        accepted = h.submit20(bytes(h.uc.mem_read(SCRATCH, 20)))
        assert bool(h.adapter('wd_reply_sent', 7, 1, i, accepted, 2)) == (i != part)
    assert h.gatt_wrappers == len(h.gatt_sends) == part + 1
    assert (h.mode(), h.mode(4)) == (HEALTH_MODE, NONE)
    assert h.adapter('wa_health_allowed', 0)
    assert not h.adapter('wd_reply_next', 7, SCRATCH, 2)
    assert not h.adapter('wa_next', h.session, SCRATCH, 2)
    assert not h.commit(h.original)
    assert h.drain_motion([(9, 10, 8005)]) == [(10, 9, 8005)]


def test_old_successful_submission_receipt_cannot_cross_disconnect_generation(linked, layout):
    h = SwitchThumb(linked, layout)
    h.command(3, 1, 1); h.enter(requested=True)
    assert h.observe((1, 2, 8005)) == 2
    assert h.adapter('wd_reply_next', 7, SCRATCH, 1)
    accepted = h.submit20(bytes(h.uc.mem_read(SCRATCH, 20)))
    assert accepted
    assert h.adapter('wd_close', 7, 1)
    h.to_resume(); h.resume_ready()
    assert h.adapter('wa_commit_health', h.token, 17, 2)
    h.fixture('old physical sends/callbacks drained before new admission', True)
    assert h.adapter('wd_open', 8, 0, 2)
    before = bytes(h.uc.mem_read(h.base, 764))
    assert not h.adapter('wd_reply_sent', 7, 1, 0, accepted, 2)
    assert bytes(h.uc.mem_read(h.base, 764)) == before
    assert h.mode() == HEALTH_MODE and h.adapter('wa_health_allowed', 0)
    # The old packet was submitted. This test does not claim to recall it or
    # prove physical drain; it verifies that a late software receipt is ignored.
    assert len(h.gatt_sends) == 1


def test_unknown_inventory_leaves_health_passthrough_and_never_touches_bus(linked, layout):
    h = SwitchThumb(linked, layout, inventory=False)
    before = bytes(h.uc.mem_read(h.base, 672))
    assert not h.adapter('wa_request', 1, 1)
    assert bytes(h.uc.mem_read(h.base, 672)) == before
    assert h.adapter('wa_health_allowed', 0) and h.adapter('wa_health_passthrough')
    assert not h.transfers and not h.receives


def test_successful_stop_writes_are_not_quiescence_or_physical_stop(linked, layout):
    h = SwitchThumb(linked, layout)
    assert h.adapter('wa_request', 1, 1)
    before = bytes(h.uc.mem_read(h.base, 672))
    assert h.stop_writes()
    assert bytes(h.uc.mem_read(h.base, 672)) == before
    assert not h.retire(h.token)
    assert (h.mode(), h.mode(4), h.word(0)) == (ENTERING, QUIESCE, 1)


@pytest.mark.parametrize('fault', [1, 2, 3])
def test_bad_motion_receipt_returns_toward_health_without_consuming_health_backlog(linked, layout, fault):
    h = SwitchThumb(linked, layout); h.enter()
    before = (h.cursor(), h.cursor(health=True), h.controls())
    assert h.observe((1, 2, 8005), fault=fault) == 3
    assert (h.mode(), h.mode(4)) == (RETURNING, STOP)
    assert (h.cursor(), h.cursor(health=True), h.controls()) == before
    assert not h.adapter('wa_next', h.session, SCRATCH, 1)
    h.to_resume(); h.resume_ready()
    assert h.adapter('wa_commit_health', h.token, 17, 2)


def test_read_io_failure_reaches_top_level_fault_not_false_health_status(linked, layout):
    h = SwitchThumb(linked, layout); h.release_results[0] = False
    assert h.read() == 0xFFFFFFFA
    h.adapter('wa_tick', 1)
    assert h.mode() == FAULT and not h.adapter('wa_health_allowed', 0)
    assert not h.adapter('wa_request', 1, 1)
    assert not h.commit(h.original)


def test_changed_settings_revision_cannot_commit_prepared_resume(linked, layout):
    h = SwitchThumb(linked, layout); h.enter()
    assert h.observe((1, 2, 8005)) == 2
    h.to_resume(); h.resume_ready()
    h.set_controls((10, 1, 3, 1))
    # This monotonic revision is a fixture; raw settings bits alone cannot
    # detect ABA and are deliberately NOT used as the revision.
    assert not h.adapter('wa_commit_health', h.token, 18, 2)
    assert (h.mode(), h.mode(4)) == (RETURNING, RESUME)
    assert not h.adapter('wa_health_allowed', 0)
    assert not h.commit(h.original)


@pytest.mark.parametrize('failure', ['reset', 'stop', 'release'])
def test_failed_shutdown_io_cannot_advance_the_switch(linked, layout, failure):
    h = SwitchThumb(linked, layout)
    assert h.adapter('wa_request', 1, 1)
    assert h.adapter('wa_cancelled', h.token, h.word(4), 1, 1)
    assert h.adapter('wa_fenced', h.token, h.word(4), 1)
    if failure == 'release': h.release_results[0] = False
    else: h.transfer_results.extend((1, 0) if failure == 'reset' else (0, 1))
    assert not h.stop_writes()
    assert h.transfers == [b'\x7b\xa5', b'\x7b\0']  # STOP attempted after failed RESET
    assert (h.mode(), h.mode(4)) == (ENTERING, QUIESCE)
    assert not h.retire(h.token)
    assert h.adapter('wa_action_failed', h.token, h.session, QUIESCE, 1)
    assert (h.mode(), h.mode(4)) == (RETURNING, STOP)
    assert not h.adapter('wa_health_allowed', 0)


@pytest.mark.parametrize('trigger', ['disconnect', 'charging', 'stale_source'])
def test_gesture_exit_triggers_keep_stock_health_motion_consumer_alive(linked, layout, trigger):
    h = SwitchThumb(linked, layout); h.enter()
    assert h.observe((1, 2, 8005)) == 2
    if trigger == 'disconnect': assert h.adapter('wd_close', 7, 2)
    elif trigger == 'charging': assert h.adapter('wd_charging', 7, 1, 2)
    else: h.adapter('wa_tick', 252)
    assert (h.mode(), h.mode(4)) == (RETURNING, STOP)
    assert not h.commit(h.original)
    assert h.drain_motion([(9, 10, 8005)]) == [(10, 9, 8005)]
    assert not h.adapter('wa_next', h.session, SCRATCH, 252)


def test_original_health_consumer_runs_during_each_optical_transition_phase(linked, layout):
    h = SwitchThumb(linked, layout)
    baseline = StockMotionHarness(STOCK)
    index = 0

    def feed():
        nonlocal index
        index += 1
        values = [(index, -index, 8005)]
        baseline.fifo.extend(values); baseline.call(FIFO_DRAIN)
        assert h.drain_motion(values) == baseline.consume_health()
        assert h.health_inputs == baseline.health_inputs

    feed()  # Health
    assert h.adapter('wa_request', 1, 1); feed()  # quiescing
    h.quiet_with_fixtures(1); feed()  # paused / HOLD
    assert h.physical(0x0F, 1); feed()  # START pending
    assert h.observe((1, 2, 8005)) == 2; feed()  # Gesture
    h.to_resume(); feed()  # RESUME pending
    h.resume_ready(); feed()  # READY, still no optical result permission
    assert h.adapter('wa_commit_health', h.token, 17, 2); feed()
    assert len(h.health_inputs) == 8
