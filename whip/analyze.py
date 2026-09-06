"""
Offline analysis of a capture. This is where the M0 gate is decided.

The gate from the build spec:
  - sustained accelerometer stream at >= 25 Hz
  - packet loss below 2%

Note on packet loss: the ring's notifications carry no sequence number, so true
loss is not directly observable. What we can measure is gap-implied loss -- given
the modal inter-arrival interval, how many expected sample slots produced no
packet. That is a lower bound on loss and it is the honest number to report.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from whip import accel, protocol

# A gesture window is 1.5s. A gap longer than this destroys a whole window.
GESTURE_WINDOW_S = 1.5
GATE_MIN_RATE_HZ = 25.0
GATE_MAX_LOSS = 0.02


@dataclass
class SubtypeStats:
    subtype: int
    name: str
    count: int
    rate_hz: float
    share: float


@dataclass
class StreamStats:
    duration_s: float
    total_packets: int
    subtypes: list[SubtypeStats] = field(default_factory=list)

    accel_count: int = 0
    accel_rate_hz: float = 0.0
    interval_median_ms: float = 0.0
    interval_mean_ms: float = 0.0
    jitter_ms: float = 0.0
    gap_p95_ms: float = 0.0
    gap_max_ms: float = 0.0
    implied_loss: float = 0.0
    windows_total: int = 0
    windows_contaminated: int = 0
    unknown_packets: int = 0

    @property
    def passes_rate(self) -> bool:
        return self.accel_rate_hz >= GATE_MIN_RATE_HZ

    @property
    def passes_loss(self) -> bool:
        return self.implied_loss < GATE_MAX_LOSS

    @property
    def passes_gate(self) -> bool:
        return self.passes_rate and self.passes_loss


def split_by_subtype(records: list[tuple[float, bytes]]) -> dict[int, list[tuple[float, bytes]]]:
    """Group 0xA1 notifications by their subtype byte. Non-0xA1 traffic goes to key -1."""
    groups: dict[int, list[tuple[float, bytes]]] = {}
    for t, payload in records:
        if len(payload) >= 2 and payload[0] == protocol.CMD_RAW_SENSOR:
            key = payload[1]
        else:
            key = -1
        groups.setdefault(key, []).append((t, payload))
    return groups


def analyze(records: list[tuple[float, bytes]], duration_s: float | None = None) -> StreamStats:
    """Compute every number the hardware gate needs from a raw capture."""
    if not records:
        return StreamStats(duration_s=duration_s or 0.0, total_packets=0)

    span = duration_s if duration_s is not None else records[-1][0] - records[0][0]
    span = max(span, 1e-9)

    stats = StreamStats(duration_s=span, total_packets=len(records))
    groups = split_by_subtype(records)

    for subtype in sorted(groups):
        entries = groups[subtype]
        if subtype == -1:
            stats.unknown_packets = len(entries)
            continue
        stats.subtypes.append(
            SubtypeStats(
                subtype=subtype,
                name=protocol.SUBTYPE_NAMES.get(subtype, f"unknown_0x{subtype:02x}"),
                count=len(entries),
                rate_hz=len(entries) / span,
                share=len(entries) / len(records),
            )
        )

    accel_records = groups.get(protocol.SUBTYPE_ACCEL, [])
    stats.accel_count = len(accel_records)
    stats.accel_rate_hz = len(accel_records) / span

    if len(accel_records) < 2:
        return stats

    times = [t for t, _ in accel_records]
    intervals = [(times[i + 1] - times[i]) * 1000 for i in range(len(times) - 1)]
    intervals.sort()

    stats.interval_median_ms = statistics.median(intervals)
    stats.interval_mean_ms = statistics.fmean(intervals)
    stats.jitter_ms = statistics.pstdev(intervals) if len(intervals) > 1 else 0.0
    stats.gap_p95_ms = intervals[int(len(intervals) * 0.95)]
    stats.gap_max_ms = intervals[-1]

    # Gap-implied loss: every interval longer than 1.5x the modal spacing is
    # assumed to have swallowed whole samples.
    nominal = stats.interval_median_ms
    if nominal > 0:
        missing = sum(max(0, round(gap / nominal) - 1) for gap in intervals)
        expected = missing + len(accel_records)
        stats.implied_loss = missing / expected if expected else 0.0

    # How many 1.5s gesture windows contain a gap big enough to break them.
    stats.windows_total = max(1, int(span / GESTURE_WINDOW_S))
    broken_window_starts = set()
    for i in range(len(times) - 1):
        if (times[i + 1] - times[i]) > (GESTURE_WINDOW_S / 3):
            broken_window_starts.add(int(times[i] / GESTURE_WINDOW_S))
    stats.windows_contaminated = len(broken_window_starts)

    return stats


def format_report(stats: StreamStats, header: dict | None = None, payloads: list[bytes] | None = None) -> str:
    """Human readable report. This is what gets pasted into docs/HARDWARE.md."""
    lines: list[str] = []
    add = lines.append

    add("=" * 62)
    add("  WHIP M0 -- ACCELEROMETER STREAM REPORT")
    add("=" * 62)

    if header:
        device = header.get("device", {})
        add(f"  device      {device.get('name')} ({device.get('address')})")
        add(f"  firmware    {device.get('firmware')}   hardware {device.get('hardware')}")
        add(f"  captured    {header.get('started_iso')}   label {header.get('label')!r}")
        add(f"  param       0x{header.get('param', 0):02x}")
        add("")

    add(f"  duration          {stats.duration_s:8.1f} s")
    add(f"  packets total     {stats.total_packets:8d}")
    if stats.unknown_packets:
        add(f"  non-0xA1 packets  {stats.unknown_packets:8d}")
    add("")

    add("  channel breakdown")
    for sub in stats.subtypes:
        add(f"    {sub.name:<16} {sub.count:7d}   {sub.rate_hz:7.2f} Hz   {sub.share * 100:5.1f}% of bandwidth")
    add("")

    add("  accelerometer")
    add(f"    rate            {stats.accel_rate_hz:8.2f} Hz")
    add(f"    interval median {stats.interval_median_ms:8.2f} ms")
    add(f"    interval mean   {stats.interval_mean_ms:8.2f} ms")
    add(f"    jitter (sd)     {stats.jitter_ms:8.2f} ms")
    add(f"    gap p95         {stats.gap_p95_ms:8.2f} ms")
    add(f"    gap max         {stats.gap_max_ms:8.2f} ms")
    add(f"    implied loss    {stats.implied_loss * 100:8.2f} %")
    add(f"    windows hit     {stats.windows_contaminated} of {stats.windows_total} " "(1.5s windows containing a stall)")
    add("")

    if payloads:
        add("  unpacker ranking (only meaningful for a STATIONARY capture)")
        add("  the correct decode holds gravity's magnitude constant")
        ranking = accel.score_unpackers(payloads)
        for i, (name, mean, cv) in enumerate(ranking):
            marker = "  <-- best" if i == 0 else ""
            add(f"    {name:<18} mean |a| {mean:9.1f}   spread {cv * 100:6.2f}%{marker}")
        add("")

    add("  GATE")
    rate_mark = "PASS" if stats.passes_rate else "FAIL"
    loss_mark = "PASS" if stats.passes_loss else "FAIL"
    add(f"    rate >= {GATE_MIN_RATE_HZ:.0f} Hz     [{rate_mark}]  measured {stats.accel_rate_hz:.2f} Hz")
    add(f"    loss <  {GATE_MAX_LOSS * 100:.0f}%       [{loss_mark}]  measured {stats.implied_loss * 100:.2f} %")
    add("")
    add(f"    OVERALL: {'PASS' if stats.passes_gate else 'FAIL'}")

    if not stats.passes_gate:
        add("")
        accel_share = next((s.share for s in stats.subtypes if s.subtype == protocol.SUBTYPE_ACCEL), 1.0)
        total_rate = stats.total_packets / max(stats.duration_s, 1e-9)

        # Rate fine, loss high, no long gaps: the firmware is producing faster
        # than the link delivers. That is link saturation, not a stream with
        # holes in it, and the fix is the opposite of the usual one -- slow the
        # producer down rather than speed anything up.
        if stats.passes_rate and stats.windows_contaminated == 0 and stats.gap_max_ms < GESTURE_WINDOW_S * 1000 / 4:
            add("  diagnosis: rate clears the gate and no gesture window contains a stall,")
            add("  yet implied loss is high. That combination means the firmware produces")
            add("  faster than BLE delivers -- samples drop evenly, not in bursts.")
            add("  Lowering the firmware timer so production matches the link would give a")
            add("  cleaner stream that still clears 25 Hz.")
            add("")

        add("  next steps on failure, cheapest first:")

        # Only blame bandwidth when there is enough traffic for bandwidth to be
        # the thing that binds. At a few packets per second the limit is a
        # firmware refresh timer, and freeing up channel capacity buys nothing.
        if total_rate < 10.0:
            add(f"    1. total traffic is only {total_rate:.1f} packets/s across all channels.")
            add("       That is a firmware refresh timer, not a bandwidth limit, so an")
            add("       accel-only mode would not help. Skip the sweep.")
        elif accel_share < 0.9:
            headroom = stats.accel_rate_hz / max(accel_share, 1e-9)
            add(f"    1. accel is only {accel_share * 100:.0f}% of traffic. An accel-only mode would")
            add(f"       give roughly {headroom:.0f} Hz. Run probe/sweep.py to look for one.")
        add("    2. flash a FasterRawValues-style firmware -- but check the lineage first.")
        add("       The published mod targets R02_3.00.06; a different base version")
        add("       is a brick risk. Buy a spare ring before trying.")
        add("    3. fall back to the ESP32-S3 + MPU6050 build.")

    add("=" * 62)
    return "\n".join(lines)
