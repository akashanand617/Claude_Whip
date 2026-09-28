import json

import numpy as np
import pytest

from whip import dataset, ring_profile


def signed16_payload(x: int, y: int, z: int) -> bytes:
    payload = bytearray(16)
    payload[0:2] = bytes([0xA1, 0x03])
    payload[2:4] = y.to_bytes(2, "big", signed=True)
    payload[4:6] = z.to_bytes(2, "big", signed=True)
    payload[6:8] = x.to_bytes(2, "big", signed=True)
    payload[-1] = sum(payload[:-1]) & 0xFF
    return bytes(payload)


def test_family_profiles_apply_the_same_proper_rotation_as_the_ios_app():
    xyz = (11, 22, 33)
    assert ring_profile.RT02CR.canonical_xyz(xyz) == (11, 22, 33)
    assert ring_profile.RT12COL.canonical_xyz(xyz) == (11, 33, -22)
    matrix = np.zeros((3, 3))
    for row, (source, sign) in enumerate(zip(ring_profile.RT12COL.sources,
                                             ring_profile.RT12COL.signs)):
        matrix[row, source] = sign
    assert np.linalg.det(matrix) == 1, "the family adapter must rotate, never mirror"


def test_transfer_contract_pins_physical_scale_timing_and_observed_encoding():
    rt02, rt12 = ring_profile.RT02_TRANSFER, ring_profile.RT12_TRANSFER
    rt02.validate()
    rt12.validate()
    assert rt02.sensor == "STK8321" and rt12.sensor == "LIS2DW12"
    assert rt02.full_scale_g == rt12.full_scale_g == 4
    assert rt02.nominal_packet_counts_per_g == rt12.nominal_packet_counts_per_g == 8192
    assert (rt02.meaningful_bits, rt02.meaningful_lsb_packet_counts) == (12, 16)
    assert (rt12.meaningful_bits, rt12.meaningful_lsb_packet_counts) == (14, 4)
    assert (rt02.source_odr_hz, rt02.fifo_sensor_decimation) == (100, 4)
    assert (rt12.source_odr_hz, rt12.fifo_sensor_decimation) == (200, 1)
    assert rt02.delivered_hz == rt12.delivered_hz == 25
    assert rt02.observed_payload_quantum_counts == 1
    assert rt12.observed_payload_quantum_counts == 4


def test_identity_routes_rt12_by_hardware_or_firmware_and_defaults_legacy_to_rt02():
    assert ring_profile.for_identity("RT12COL_V1.0", None) is ring_profile.RT12COL
    assert ring_profile.for_identity(None, "RT12COL_1.00.01_260927") is ring_profile.RT12COL
    assert ring_profile.for_identity("RT02CR_V3.1", None) is ring_profile.RT02CR
    assert ring_profile.for_identity(None, None) is ring_profile.RT02CR
    with pytest.raises(ring_profile.UnsupportedRingFamily):
        ring_profile.for_identity("SOME_NEW_BOARD", "SOME_NEW_FIRMWARE")


def test_only_measured_25hz_images_are_admitted_for_collection():
    assert ring_profile.supports_gesture_stream("RT02CR_3.12.07_260514")
    assert ring_profile.supports_gesture_stream("RT12COL_1.00.01_260927")
    assert ring_profile.supports_gesture_stream("RT12COL_1.00.02_260927")
    assert ring_profile.supports_gesture_stream("RT12COL_1.00.03_260927")
    assert ring_profile.supports_gesture_stream("RT12COL_1.00.06_260927")
    assert ring_profile.supports_gesture_stream("RT12COL_1.00.07_260927")
    assert not ring_profile.supports_gesture_stream("RT12COL_1.00.00_260520")
    assert not ring_profile.supports_gesture_stream("something-new")


def test_only_exact_lease_safe_builds_request_host_lease_renewal():
    assert ring_profile.gesture_lease_renewal_interval(
        "RT12COL_1.00.06_260927") == 8.0
    assert ring_profile.gesture_lease_renewal_interval(
        "RT12COL_1.00.07_260927") == 8.0
    assert ring_profile.gesture_lease_renewal_interval(
        "RT12COL_1.00.03_260927") is None
    assert ring_profile.gesture_lease_renewal_interval(
        "RT02CR_3.12.07_260514") is None


def test_signal_adapters_match_ios_mg_grid_rotation_and_rt02_rails():
    decoded = (11, 22, 33)
    assert ring_profile.SignalAdapter(ring_profile.RT02CR).model_counts(decoded) \
        == pytest.approx(decoded)
    assert ring_profile.SignalAdapter(ring_profile.RT12COL).model_counts(decoded) \
        == pytest.approx((11, 33, -22))

    adapter = ring_profile.SignalAdapter(ring_profile.RT12COL)
    mg = adapter.canonical_mg((32_767, -32_768, 4))
    assert mg == pytest.approx((
        ring_profile.RT02_MAX_MG,
        4 * ring_profile.RT02_MG_PER_COUNT,
        ring_profile.RT02_MAX_MG,
    ))

    # The adapter preserves decoded values; it does not manufacture an RT02
    # quantizer from the STK8321's nominal ADC resolution.
    fractional = adapter.model_counts((1.25, 2.5, 3.75))
    assert fractional == pytest.approx((1.25, 3.75, -2.5))


def test_per_ring_calibration_is_loaded_from_capture_and_finally_clipped():
    header = {"device": {
        "hardware": "RT12COL_V1.0",
        "firmware": "RT12COL_1.00.03_260927",
        "signal_calibration": {
            "offset_mg": [1, 2, 3],
            "gain": [2, 1, 0.5],
        },
    }}
    adapter = ring_profile.adapter_for_capture_header(header)
    grid = ring_profile.RT02_MG_PER_COUNT
    assert adapter.canonical_mg((800, 1_600, 2_400)) == pytest.approx((
        (800 * grid - 1) * 2,
        2_400 * grid - 2,
        (-1_600 * grid - 3) * 0.5,
    ))
    saturated = ring_profile.SignalAdapter(
        ring_profile.RT02CR,
        ring_profile.SensorCalibration(gain=(2, 2, 2)),
    )
    assert saturated.canonical_mg((32_767, -32_768, 0)) == pytest.approx((
        ring_profile.RT02_MAX_MG, ring_profile.RT02_MIN_MG, 0,
    ))
    with pytest.raises(ValueError):
        ring_profile.adapter_for_capture_header({"device": {
            "hardware": "RT12COL_V1.0",
            "signal_calibration": {"offset_mg": [0, 0], "gain": [1, 1, 1]},
        }})


def test_dataset_rotates_rt12_before_windowing(tmp_path):
    capture = tmp_path / "rt12.jsonl"
    header = {"kind": "header", "device": {
        "hardware": "RT12COL_V1.0", "firmware": "RT12COL_1.00.01_260927"}}
    lines = [json.dumps(header)]
    # Vary every source axis so the centred waveform proves the mapping too.
    for i in range(150):
        payload = signed16_payload(x=100 + i, y=1000 + 2 * i, z=-500 + 3 * i)
        lines.append(json.dumps({"t": i / 25, "p": payload.hex()}))
    capture.write_text("\n".join(lines) + "\n")
    window = dataset.windows_from_session(capture, declared_negative=True)[0]
    axes = np.asarray(window.axes)
    # canonical RT12 = [source x, source z, -source y]
    slopes = np.array([np.polyfit(np.arange(50), row, 1)[0] for row in axes])
    assert slopes[0] > 0 and slopes[1] > slopes[0] and slopes[2] < 0
    assert abs(slopes[1] / slopes[0] - 3) < 0.01
    assert abs(slopes[2] / slopes[0] + 2) < 0.01
