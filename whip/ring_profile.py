"""Hardware-family signal routing for the gesture pipeline.

The two supported R02 boards expose the same three physical acceleration axes
in different packet coordinates. Models and the recorded RT02 corpus use one
canonical coordinate system, so every live or recorded RT12 sample must be
rotated before calibration, feature extraction, or inference.

This module intentionally contains no guessed amplitude correction. RT02's
12-bit STK8321 and RT12COL's 14-bit LIS2DW12 both encode nominally 8192 packet
counts/g at +/-4 g: the meaningful sensor words are left-aligned by 4 and 2
bits respectively. The corpus uses the measured common value, 8005 counts/g.
RT02 packets empirically use all low bits, whereas RT12 packets are multiples
of four, so nominal ADC resolution is metadata rather than a license to round
either stream. V6 raises the RT12 physical source to 200 Hz, selects low-power
mode 2 and clears SLEEP_ON only while Gesture owns raw mode; both families still
deliver the newest FIFO sample at 25 Hz.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from whip import accel


MG_PER_G = 1_000.0
RT02_COUNTS_PER_G = accel.COUNTS_PER_G
RT02_MG_PER_COUNT = MG_PER_G / RT02_COUNTS_PER_G
RT02_MIN_MG = -32_768 * RT02_MG_PER_COUNT
RT02_MAX_MG = 32_767 * RT02_MG_PER_COUNT


RT02_GESTURE_FIRMWARE = frozenset({
    "RT02CR_3.12.07_260514",
    "RT02CR_3.12.00_251205",
})
RT12_GESTURE_FIRMWARE = frozenset({
    "RT12COL_1.00.01_260927",
    "RT12COL_1.00.02_260927",
    "RT12COL_1.00.03_260927",
    "RT12COL_1.00.06_260927",
    "RT12COL_1.00.07_260927",
})

# V6 deliberately expires Gesture after 250 delivered callbacks (nominally
# ten seconds).  Renew early enough to leave two seconds of scheduling/link
# margin.  Repeating A1 04 is safe only on the exact lease-only build; older
# RT12 candidates can rerun sensor setup or restart the producer.
GESTURE_LEASE_RENEWAL_INTERVAL_S = 8.0
LEASE_ONLY_GESTURE_FIRMWARE = frozenset({
    "RT12COL_1.00.06_260927",
    "RT12COL_1.00.07_260927",
})


class UnsupportedRingFamily(ValueError):
    pass


@dataclass(frozen=True)
class SensorCalibration:
    """Per-device gain/zero correction in the canonical RT02 mg frame."""

    offset_mg: tuple[float, float, float] = (0.0, 0.0, 0.0)
    gain: tuple[float, float, float] = (1.0, 1.0, 1.0)

    def validate(self) -> None:
        if len(self.offset_mg) != 3 or len(self.gain) != 3 \
                or any(not math.isfinite(v) or abs(v) > 1_000 for v in self.offset_mg) \
                or any(not math.isfinite(v) or not 0.5 <= v <= 2.0 for v in self.gain):
            raise ValueError("invalid per-ring sensor calibration")

    def apply(self, canonical_mg) -> tuple[float, float, float]:
        self.validate()
        values = tuple(float(v) for v in canonical_mg)
        if len(values) != 3 or any(not math.isfinite(v) for v in values):
            raise ValueError("invalid three-axis mg sample")
        return tuple((values[i] - self.offset_mg[i]) * self.gain[i] for i in range(3))

    @classmethod
    def from_mapping(cls, value: dict | None) -> "SensorCalibration":
        if not value:
            return cls()
        calibration = cls(
            offset_mg=tuple(float(v) for v in value.get("offset_mg", ())),
            gain=tuple(float(v) for v in value.get("gain", ())),
        )
        calibration.validate()
        return calibration


@dataclass(frozen=True)
class SensorTransferContract:
    """Pinned acquisition facts; descriptive metadata, never a fitted transform."""

    sensor: str
    full_scale_g: float
    meaningful_bits: int
    meaningful_lsb_packet_counts: int
    nominal_packet_counts_per_g: float
    source_odr_hz: float
    fifo_sensor_decimation: int
    delivered_hz: float
    widest_bandwidth_hz: float
    observed_payload_quantum_counts: int
    sample_selection: str

    def validate(self) -> None:
        if self.full_scale_g != 4 or self.meaningful_bits not in (12, 14) \
                or self.meaningful_lsb_packet_counts not in (4, 16) \
                or self.nominal_packet_counts_per_g != 8192 \
                or self.source_odr_hz <= 0 or self.fifo_sensor_decimation <= 0 \
                or self.delivered_hz != 25 or self.widest_bandwidth_hz <= 0 \
                or self.observed_payload_quantum_counts <= 0 \
                or not self.sample_selection:
            raise ValueError("invalid gesture sensor transfer contract")


@dataclass(frozen=True)
class GestureSignalProfile:
    family: str
    # canonical[i] = source[sources[i]] * signs[i]
    sources: tuple[int, int, int]
    signs: tuple[int, int, int]
    transfer: SensorTransferContract
    counts_per_g: float = accel.COUNTS_PER_G

    def canonical_xyz(self, xyz) -> tuple[float, float, float]:
        values = tuple(xyz)
        self.transfer.validate()
        if len(values) != 3 or sorted(self.sources) != [0, 1, 2] \
                or any(sign not in (-1, 1) for sign in self.signs):
            raise ValueError("invalid three-axis gesture signal profile")
        return tuple(values[source] * sign for source, sign in zip(self.sources, self.signs))

    def canonical_sample(self, sample: accel.AccelSample) -> accel.AccelSample:
        return SignalAdapter(self).model_sample(sample)


@dataclass(frozen=True)
class SignalAdapter:
    """Counts -> mg -> common range -> rotation/calibration -> model counts.

    Sample order is preserved. BLE receipt timestamps are transport timing and
    must never be used here to interpolate a supposedly physical 25 Hz signal.
    """

    profile: GestureSignalProfile
    calibration: SensorCalibration = SensorCalibration()

    def canonical_mg(self, xyz) -> tuple[float, float, float]:
        values = tuple(float(v) for v in xyz)
        if len(values) != 3 or any(not math.isfinite(v) for v in values):
            raise ValueError("invalid three-axis count sample")
        source = [v * MG_PER_G / self.profile.counts_per_g for v in values]
        source = [min(RT02_MAX_MG, max(RT02_MIN_MG, v)) for v in source]
        canonical = self.profile.canonical_xyz(source)
        canonical = tuple(min(RT02_MAX_MG, max(RT02_MIN_MG, v)) for v in canonical)
        calibrated = self.calibration.apply(canonical)
        # Calibration corrects zero/gain mismatch; it must not manufacture a
        # value outside the RT02 model's physically representable contract.
        return tuple(min(RT02_MAX_MG, max(RT02_MIN_MG, v)) for v in calibrated)

    def model_counts(self, xyz) -> tuple[float, float, float]:
        return tuple(v / RT02_MG_PER_COUNT for v in self.canonical_mg(xyz))

    def model_sample(self, sample: accel.AccelSample) -> accel.AccelSample:
        return accel.AccelSample(*self.model_counts((sample.x, sample.y, sample.z)))


RT02_TRANSFER = SensorTransferContract(
    sensor="STK8321",
    full_scale_g=4,
    meaningful_bits=12,
    meaningful_lsb_packet_counts=16,
    nominal_packet_counts_per_g=8192,
    source_odr_hz=100,
    fifo_sensor_decimation=4,
    delivered_hz=25,
    widest_bandwidth_hz=1000,
    # Real packets use every low-bit residue. Do not erase those bits merely
    # because the ADC itself is documented as 12-bit.
    observed_payload_quantum_counts=1,
    sample_selection="FIFO keeps every fourth source frame; callback returns newest",
)
RT12_TRANSFER = SensorTransferContract(
    sensor="LIS2DW12",
    full_scale_g=4,
    meaningful_bits=14,
    meaningful_lsb_packet_counts=4,
    nominal_packet_counts_per_g=8192,
    source_odr_hz=200,
    fifo_sensor_decimation=1,
    delivered_hz=25,
    widest_bandwidth_hz=720,
    observed_payload_quantum_counts=4,
    sample_selection="FIFO keeps every source frame; callback drains and returns newest",
)

RT02CR = GestureSignalProfile("rt02cr", (0, 1, 2), (1, 1, 1), RT02_TRANSFER)
# Measured with physical fingers-forward and fingertips-at-the-floor poses.
# This is a proper rotation (determinant +1), not a mirror.
RT12COL = GestureSignalProfile(
    "rt12col", (0, 2, 1), (1, 1, -1), RT12_TRANSFER
)


def for_identity(hardware: str | None, firmware: str | None) -> GestureSignalProfile:
    """Choose the signal profile from DIS identity, hardware first."""
    hw = (hardware or "").strip().upper()
    fw = (firmware or "").strip().upper()
    if hw.startswith("RT12COL_") or fw.startswith("RT12COL_"):
        return RT12COL
    if hw.startswith("RT02CR_") or fw.startswith("RT02CR_"):
        return RT02CR
    # Historical captures predate hardware-version recording and are all RT02.
    # Preserve their established interpretation, but live callers still reject
    # an unknown firmware before recording.
    if not hw and not fw:
        return RT02CR
    raise UnsupportedRingFamily(
        f"no gesture signal profile for hardware {hardware!r}, firmware {firmware!r}")


def for_capture_header(header: dict) -> GestureSignalProfile:
    device = header.get("device") or {}
    return for_identity(device.get("hardware"), device.get("firmware"))


def adapter_for_identity(hardware: str | None, firmware: str | None,
                         calibration: SensorCalibration | None = None) -> SignalAdapter:
    return SignalAdapter(for_identity(hardware, firmware), calibration or SensorCalibration())


def adapter_for_capture_header(header: dict) -> SignalAdapter:
    device = header.get("device") or {}
    calibration = SensorCalibration.from_mapping(device.get("signal_calibration"))
    return adapter_for_identity(device.get("hardware"), device.get("firmware"), calibration)


def supports_gesture_stream(firmware: str | None) -> bool:
    fw = (firmware or "").strip()
    return fw in RT02_GESTURE_FIRMWARE or fw in RT12_GESTURE_FIRMWARE


def gesture_lease_renewal_interval(firmware: str | None) -> float | None:
    """Host renewal cadence for exact firmware with a verified A1 04 lease path."""
    fw = (firmware or "").strip()
    return GESTURE_LEASE_RENEWAL_INTERVAL_S if fw in LEASE_ONLY_GESTURE_FIRMWARE else None
