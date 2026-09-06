import math

from probe.simulate import make_accel_payload
from whip import accel


def test_axis_offsets_match_the_working_implementation():
    """
    Byte order in the notification is Y, Z, X -- not X, Y, Z. Getting this wrong
    produces plausible-looking data that is silently mislabelled, which would be
    invisible until the classifier failed for no apparent reason.
    """
    assert accel.AXIS_OFFSETS == {"y": 2, "z": 4, "x": 6}


def test_decode_round_trips_through_the_reference_unpacker():
    payload = make_accel_payload(x=100, y=1024, z=-40)
    sample = accel.decode(payload, "reference")
    assert (sample.x, sample.y, sample.z) == (100, 1024, -40)


def test_signed12_is_coherent_twos_complement():
    # 0x800 is the most negative 12 bit value.
    assert accel.UNPACKERS["signed12"](0x80, 0x00) == -2048
    assert accel.UNPACKERS["signed12"](0x7F, 0x0F) == 2047
    assert accel.UNPACKERS["signed12"](0x00, 0x00) == 0


def test_reference_and_signed12_disagree():
    """
    The reference unpacker tests bit 3 of the high byte but subtracts 1 << 11,
    which is not a coherent 12 bit decode. We keep both precisely because we do
    not yet know which is right, and real stationary data will tell us.
    """
    assert accel.UNPACKERS["reference"](0x08, 0x00) != accel.UNPACKERS["signed12"](0x08, 0x00)


def test_magnitude():
    sample = accel.AccelSample(3, 4, 0)
    assert sample.magnitude == 5.0


def test_decode_rejects_short_payload():
    try:
        accel.decode(b"\x00" * 4)
    except ValueError:
        return
    raise AssertionError("expected ValueError on a truncated payload")


def test_score_unpackers_needs_multiple_orientations_to_discriminate():
    """
    A single orientation is not enough to identify the unpacker. If gravity sits
    on one axis and every value is positive, several decodes produce an equally
    constant magnitude and the ranking is a coin flip.

    Six orientations, including the negative direction of each axis, force the
    sign handling to matter -- which is the part the candidates disagree about.
    """
    one_orientation = [make_accel_payload(x=50 + int(math.sin(i / 10) * 3), y=1024, z=30) for i in range(200)]
    ranking = accel.score_unpackers(one_orientation)
    tied = [name for name, _, spread, _ in ranking if spread < 0.01]
    assert len(tied) > 1, "expected a single orientation to be ambiguous"

    six_orientations = []
    for gx, gy, gz in [(1024, 0, 0), (-1024, 0, 0), (0, 1024, 0), (0, -1024, 0), (0, 0, 1024), (0, 0, -1024)]:
        for i in range(50):
            wobble = int(math.sin(i / 10) * 3)
            six_orientations.append(make_accel_payload(x=gx + wobble, y=gy + wobble, z=gz))

    ranking = accel.score_unpackers(six_orientations)
    # The fixture encodes with the reference scheme, so reference must win here.
    assert ranking[0][0] == "reference"
    assert ranking[0][3] == 1.0, "the correct decode should reconcile every sample"
    assert ranking[0][2] < 0.02


def test_raw_axes_is_decoder_independent():
    """Stationarity must not be judged with the decoder under test."""
    payload = make_accel_payload(x=100, y=1024, z=-40)
    assert accel.raw_axes(payload) == (
        (payload[6] << 4) | (payload[7] & 0x0F),
        (payload[2] << 4) | (payload[3] & 0x0F),
        (payload[4] << 4) | (payload[5] & 0x0F),
    )


def test_stationary_windows_discards_motion():
    still = [(i * 0.02, make_accel_payload(50, 1024, 30)) for i in range(50)]
    moving = [(1.0 + i * 0.02, make_accel_payload(50 + i * 40, 1024 - i * 30, 30)) for i in range(50)]

    kept = accel.stationary_windows(still + moving)
    assert len(kept) == 1, "the moving window should be discarded"
    assert len(kept[0]) == 50


def test_count_orientations_distinguishes_attitudes():
    def block(t0, x, y, z):
        return [(t0 + i * 0.02, make_accel_payload(x, y, z)) for i in range(50)]

    one = accel.stationary_windows(block(0.0, 1000, 0, 0))
    assert accel.count_orientations(one) == 1

    three = accel.stationary_windows(block(0.0, 1000, 0, 0) + block(1.0, 0, 1000, 0) + block(2.0, 0, 0, 1000))
    assert accel.count_orientations(three) == 3


def test_ranking_prefers_coverage_over_a_tight_but_partial_fit():
    """
    A decoder right in some orientations and wrong in others yields a tight
    cluster plus outliers, and wins on spread alone once the outliers are
    dropped. On the real capture that put the worst candidate top by discarding
    40% of the data. Coverage has to dominate.
    """
    payloads = []
    for gx, gy, gz in [(1024, 0, 0), (-1024, 0, 0), (0, 1024, 0), (0, -1024, 0), (0, 0, 1024), (0, 0, -1024)]:
        payloads += [make_accel_payload(x=gx, y=gy, z=gz) for _ in range(50)]

    ranking = accel.score_unpackers(payloads)
    best = ranking[0]
    assert best[3] >= 0.99, "winner must reconcile essentially all the data"
    for _, _, _, coverage in ranking[1:]:
        assert coverage <= best[3]


def test_default_unpacker_is_the_one_the_data_chose():
    assert accel.DEFAULT_UNPACKER == "signed16_be"
    assert 7500 < accel.COUNTS_PER_G < 8500
