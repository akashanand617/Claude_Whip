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
    tied = [name for name, _, cv in ranking if cv < 0.01]
    assert len(tied) > 1, "expected a single orientation to be ambiguous"

    six_orientations = []
    for gx, gy, gz in [(1024, 0, 0), (-1024, 0, 0), (0, 1024, 0), (0, -1024, 0), (0, 0, 1024), (0, 0, -1024)]:
        for i in range(50):
            wobble = int(math.sin(i / 10) * 3)
            six_orientations.append(make_accel_payload(x=gx + wobble, y=gy + wobble, z=gz))

    ranking = accel.score_unpackers(six_orientations)
    assert ranking[0][0] == "reference"
    assert ranking[0][2] < 0.02
    assert ranking[1][2] > ranking[0][2] * 2, "the runner up should be clearly worse"
