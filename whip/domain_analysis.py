"""Cross-ring waveform and decoder analysis.

The production model was trained on RT02CR recordings. This module compares a
prompted RT12COL phone capture against that corpus without silently changing the
production preprocessing. Scale, coordinate rotation, and notification timing
are evaluated as separate hypotheses. Candidate ranking is diagnostic only: a
short prompted capture and a 30-second ambient tail cannot approve a model.
"""

from __future__ import annotations

import itertools
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from whip import accel, audit, capture, ring_profile
from whip.dataset import stream_g
from whip.realtime import Engine, GestureEvent
from whip.registry import Registry, load_registry


@dataclass(frozen=True)
class WaveformMetrics:
    peak_g: float
    active_s: float
    axis_energy: tuple[float, float, float]
    peak_axis_abs: tuple[float, float, float]
    clipping_fraction: float
    duplicate_fraction: float


@dataclass(frozen=True)
class MarkWaveform:
    label: str
    repetition: int
    cue_at: float
    metrics: WaveformMetrics
    template: np.ndarray  # (3, 41), peak-aligned and peak-normalized


def canonical_mark_label(mark: dict, registry: Registry | None = None) -> str | None:
    registry = registry or load_registry()
    spec = registry.resolve(mark.get("label", "none"))
    if spec is None:
        return None
    direction = mark.get("direction", "none")
    if spec.split_by_direction and direction in ("up", "down", "left", "right"):
        return f"{spec.name}_{direction}"
    return spec.name


def _mark_waveform(times: np.ndarray, xyz_g: np.ndarray, mark: dict,
                   registry: Registry) -> MarkWaveform | None:
    label = canonical_mark_label(mark, registry)
    spec = registry.resolve(mark.get("label", "none"))
    if label is None or spec is None:
        return None
    cue = float(mark["cue_at"])
    pre = (times >= cue - 0.6) & (times < cue - 0.08)
    region = (times >= cue - 0.20) & (times <= cue + max(1.6, spec.duration_s + 0.5))
    if pre.sum() < 4 or region.sum() < 8:
        return None
    gravity = np.median(xyz_g[:, pre], axis=1, keepdims=True)
    dynamic = xyz_g[:, region] - gravity
    magnitude = np.linalg.norm(dynamic, axis=0)
    peak_i = int(np.argmax(magnitude))
    peak = float(magnitude[peak_i])
    if peak <= 1e-6:
        return None
    energy = np.sum(dynamic * dynamic, axis=1)
    energy = energy / max(float(energy.sum()), 1e-12)
    peak_axis = np.abs(dynamic[:, peak_i]) / peak
    threshold = max(0.5, 0.20 * peak)
    active_s = float(np.count_nonzero(magnitude >= threshold) / 25.0)
    full_scale_g = 32767.0 / accel.COUNTS_PER_G
    clipped = float(np.mean(np.any(np.abs(xyz_g[:, region]) >= 0.98 * full_scale_g, axis=0)))
    segment = xyz_g[:, region]
    duplicate = float(np.mean(np.all(np.diff(segment, axis=1) == 0, axis=0))) if segment.shape[1] > 1 else 0.0

    peak_t = times[region][peak_i]
    relative = np.linspace(-0.4, 1.2, 41)
    template = np.vstack([
        np.interp(peak_t + relative, times, xyz_g[axis], left=xyz_g[axis, 0], right=xyz_g[axis, -1])
        for axis in range(3)
    ]) - gravity
    template /= max(float(np.linalg.norm(template, axis=0).max()), 1e-6)
    return MarkWaveform(
        label=label, repetition=int(mark.get("repetition", 0)), cue_at=cue,
        metrics=WaveformMetrics(
            peak_g=peak, active_s=active_s,
            axis_energy=tuple(float(v) for v in energy),
            peak_axis_abs=tuple(float(v) for v in peak_axis),
            clipping_fraction=clipped, duplicate_fraction=duplicate,
        ),
        template=template,
    )


def mark_waveforms(capture_path: Path, notes_path: Path | None = None,
                   registry: Registry | None = None) -> list[MarkWaveform]:
    registry = registry or load_registry()
    notes_path = notes_path or capture_path.with_name(capture_path.stem + ".notes.json")
    notes = json.loads(notes_path.read_text())
    times, xyz_g = stream_g(capture_path)
    excluded = audit.excluded_cues(capture_path)
    out = []
    for mark in notes.get("marks", []):
        if "cue_at" not in mark or "until" in mark:
            continue
        if any(abs(float(mark["cue_at"]) - float(cue)) < 1e-6 for cue in excluded):
            continue
        waveform = _mark_waveform(times, xyz_g, mark, registry)
        if waveform is not None:
            out.append(waveform)
    return out


def rt02_reference_waveforms(sessions_dir: Path = Path("data/sessions"),
                             registry: Registry | None = None) -> list[MarkWaveform]:
    registry = registry or load_registry()
    out: list[MarkWaveform] = []
    for notes_path in sorted(sessions_dir.glob("*.notes.json")):
        capture_path = sessions_dir / (notes_path.name.removesuffix(".notes.json") + ".jsonl")
        if not capture_path.exists():
            continue
        try:
            header, _ = capture.load_capture(capture_path)
            if ring_profile.for_capture_header(header).family != "rt02cr":
                continue
            out.extend(mark_waveforms(capture_path, notes_path, registry))
        except (ValueError, OSError, json.JSONDecodeError):
            continue
    return out


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    x = np.asarray(a, dtype=float).ravel(); y = np.asarray(b, dtype=float).ravel()
    x -= x.mean(); y -= y.mean()
    denom = float(np.linalg.norm(x) * np.linalg.norm(y))
    return float(np.dot(x, y) / denom) if denom > 1e-12 else 0.0


def _nearest_similarity(target: list[MarkWaveform], reference: list[MarkWaveform]) -> tuple[float, float]:
    if not target or not reference:
        return float("nan"), float("nan")
    signed = []; magnitude = []
    for item in target:
        signed.append(max(_corr(item.template, ref.template) for ref in reference))
        target_mag = np.linalg.norm(item.template, axis=0)
        magnitude.append(max(_corr(target_mag, np.linalg.norm(ref.template, axis=0)) for ref in reference))
    return float(np.median(signed)), float(np.median(magnitude))


def _summary(items: list[MarkWaveform]) -> dict:
    if not items:
        return {"n": 0}
    metrics = [item.metrics for item in items]
    return {
        "n": len(items),
        "peak_g_median": float(np.median([m.peak_g for m in metrics])),
        "peak_g_p10_p90": [float(v) for v in np.percentile([m.peak_g for m in metrics], [10, 90])],
        "active_s_median": float(np.median([m.active_s for m in metrics])),
        "axis_energy_median": [float(v) for v in np.median([m.axis_energy for m in metrics], axis=0)],
        "peak_axis_abs_median": [float(v) for v in np.median([m.peak_axis_abs for m in metrics], axis=0)],
        "clipping_fraction_median": float(np.median([m.clipping_fraction for m in metrics])),
        "duplicate_fraction_median": float(np.median([m.duplicate_fraction for m in metrics])),
    }


def compare_waveforms(target: list[MarkWaveform], reference: list[MarkWaveform]) -> dict:
    labels = sorted({item.label for item in target})
    result = {}
    for label in labels:
        ours = [item for item in target if item.label == label]
        refs = [item for item in reference if item.label == label]
        signed, magnitude = _nearest_similarity(ours, refs)
        target_summary = _summary(ours); reference_summary = _summary(refs)
        peak_ratio = float("nan")
        if target_summary.get("n") and reference_summary.get("n") and reference_summary["peak_g_median"] > 0:
            peak_ratio = target_summary["peak_g_median"] / reference_summary["peak_g_median"]
        result[label] = {
            "target": target_summary, "rt02_reference": reference_summary,
            "peak_ratio": peak_ratio, "nearest_signed_waveform_correlation": signed,
            "nearest_magnitude_waveform_correlation": magnitude,
        }
    return result


def uniform_resample(times: np.ndarray, xyz_g: np.ndarray, hz: float = 25.0,
                     collapse_short_duplicate_runs: bool = False) -> tuple[np.ndarray, np.ndarray]:
    times = np.asarray(times, dtype=float); xyz_g = np.asarray(xyz_g, dtype=float)
    if len(times) < 2 or xyz_g.shape != (3, len(times)):
        raise ValueError("expected increasing times and a (3, N) stream")
    if np.any(np.diff(times) <= 0):
        raise ValueError("sample times must be strictly increasing")
    source_times = times; source = xyz_g
    if collapse_short_duplicate_runs:
        keep = np.ones(len(times), dtype=bool)
        start = 0
        while start < len(times):
            end = start + 1
            while end < len(times) and np.array_equal(xyz_g[:, end], xyz_g[:, start]):
                end += 1
            length = end - start
            if 1 < length <= 4:
                keep[start + 1:end] = False
            elif length > 4:
                keep[start + 1:end - 1] = False
            start = end
        source_times = times[keep]; source = xyz_g[:, keep]
    grid = np.arange(times[0], times[-1] + 0.5 / hz, 1.0 / hz)
    resampled = np.vstack([np.interp(grid, source_times, source[axis]) for axis in range(3)])
    return grid, resampled


def proper_axis_rotations() -> list[tuple[str, np.ndarray]]:
    rotations = []
    for permutation in itertools.permutations(range(3)):
        for signs in itertools.product((-1.0, 1.0), repeat=3):
            matrix = np.zeros((3, 3), dtype=float)
            for row, (column, sign) in enumerate(zip(permutation, signs)):
                matrix[row, column] = sign
            if round(float(np.linalg.det(matrix))) == 1:
                name = "rot_" + "".join(str(v) for v in permutation) + "_" + "".join("p" if v > 0 else "m" for v in signs)
                rotations.append((name, matrix))
    return rotations


def _event_key(event: GestureEvent) -> str:
    if event.name in ("flick", "double_flick") and event.direction != "none":
        return f"{event.name}_{event.direction}"
    return event.name


def replay(times: np.ndarray, xyz_g: np.ndarray, checkpoint: Path) -> list[GestureEvent]:
    engine = Engine.from_checkpoint(checkpoint)
    engine.auto_frame = False
    out: list[GestureEvent] = []
    for time_s, sample in zip(times, xyz_g.T):
        out.extend(engine.feed_sample(float(time_s), sample * accel.COUNTS_PER_G))
    out.extend(engine.finish())
    return out


def score_events(events: list[GestureEvent], marks: list[dict], registry: Registry | None = None) -> dict:
    registry = registry or load_registry()
    remaining = list(events)
    hits = []
    confusions: dict[str, int] = {}
    for mark in sorted((m for m in marks if "cue_at" in m and "until" not in m), key=lambda m: m["cue_at"]):
        expected = canonical_mark_label(mark, registry)
        if expected is None:
            continue
        cue = float(mark["cue_at"])
        nearby = [event for event in remaining if -0.5 <= event.t_s - cue <= 2.0]
        exact = [event for event in nearby if _event_key(event) == expected]
        match = min(exact, key=lambda event: abs(event.t_s - cue), default=None)
        if match is not None:
            remaining.remove(match); hit = True; observed = expected
        else:
            nearest = min(nearby, key=lambda event: abs(event.t_s - cue), default=None)
            if nearest is not None:
                remaining.remove(nearest); observed = _event_key(nearest)
                confusions[f"{expected}->{observed}"] = confusions.get(f"{expected}->{observed}", 0) + 1
            else:
                observed = "miss"
            hit = False
        hits.append({"expected": expected, "observed": observed, "hit": hit,
                     "repetition": int(mark.get("repetition", 0))})
    dev = [row["hit"] for row in hits if row["repetition"] not in (0, 3)]
    validation = [row["hit"] for row in hits if row["repetition"] == 3]
    return {
        "hits": sum(row["hit"] for row in hits), "total": len(hits),
        "recall": sum(row["hit"] for row in hits) / len(hits) if hits else float("nan"),
        "development_recall": sum(dev) / len(dev) if dev else float("nan"),
        "validation_recall": sum(validation) / len(validation) if validation else float("nan"),
        "confusions": confusions, "details": hits,
    }


def evaluate_candidates(times: np.ndarray, xyz_g: np.ndarray, marks: list[dict], checkpoint: Path) -> list[dict]:
    last_cue = max((float(mark["cue_at"]) for mark in marks if "cue_at" in mark), default=times[-1])
    candidates: list[tuple[str, np.ndarray, np.ndarray]] = [("baseline", times, xyz_g)]
    candidates.append(("uniform_25hz", *uniform_resample(times, xyz_g)))
    candidates.append(("dedup_short_runs_25hz", *uniform_resample(times, xyz_g, collapse_short_duplicate_runs=True)))
    for factor in (0.75, 1.25, 1.5):
        candidates.append((f"scale_{factor:g}", times, xyz_g * factor))
    for name, matrix in proper_axis_rotations():
        if np.array_equal(matrix, np.eye(3)):
            continue
        candidates.append((name, times, matrix @ xyz_g))

    results = []
    for name, candidate_times, candidate_xyz in candidates:
        detected = replay(candidate_times, candidate_xyz, checkpoint)
        score = score_events(detected, marks)
        ambient = [event for event in detected if event.t_s >= last_cue + 3.0]
        score.update(name=name, ambient_events=len(ambient))
        results.append(score)
    return sorted(results, key=lambda row: (
        -(row["validation_recall"] if math.isfinite(row["validation_recall"]) else -1),
        -(row["development_recall"] if math.isfinite(row["development_recall"]) else -1),
        row["ambient_events"], row["name"],
    ))


def analyse(capture_path: Path, checkpoint: Path = Path("data/model.pt"),
            sessions_dir: Path = Path("data/sessions")) -> dict:
    notes_path = capture_path.with_name(capture_path.stem + ".notes.json")
    notes = json.loads(notes_path.read_text())
    header, records = capture.load_capture(capture_path)
    adapter = ring_profile.adapter_for_capture_header(header)
    profile = adapter.profile
    times, xyz_g = stream_g(capture_path)
    target = mark_waveforms(capture_path, notes_path)
    reference = rt02_reference_waveforms(sessions_dir)
    accel_packets = [payload for _, payload in records if len(payload) >= 8 and payload[:2] == bytes((0xA1, 0x03))]
    decoded = [adapter.model_counts((s.x, s.y, s.z)) for s in map(accel.decode, accel_packets)]
    duplicate = float(np.mean([decoded[i] == decoded[i - 1] for i in range(1, len(decoded))])) if len(decoded) > 1 else 0.0
    rate = float((len(times) - 1) / (times[-1] - times[0])) if len(times) > 1 else 0.0
    candidates = evaluate_candidates(times, xyz_g, notes.get("marks", []), checkpoint)
    return {
        "capture": capture_path.name, "family": profile.family,
        "samples": len(times), "notification_rate_hz": rate,
        "consecutive_duplicate_fraction": duplicate,
        "waveforms": compare_waveforms(target, reference),
        "candidate_results": candidates,
        "limitations": [
            "Three prompted repetitions per class are an exploratory domain check, not a production training set.",
            "The 30-second ambient tail cannot establish the false-positive budget; zero events would still have a 360/hour rule-of-three upper bound.",
            "Candidate rotations are ranked on the same small capture and require confirmation on a separately recorded session.",
        ],
    }


def markdown_report(report: dict) -> str:
    lines = [
        "# Cross-ring waveform analysis", "",
        f"Capture: `{report['capture']}` · family `{report['family']}` · "
        f"{report['samples']} samples at {report['notification_rate_hz']:.2f} Hz · "
        f"duplicates {100 * report['consecutive_duplicate_fraction']:.1f}%", "",
        "## Waveform comparison", "",
        "| Gesture | n | RT02 n | peak ratio | signed corr | magnitude corr | duplicate |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for label, row in report["waveforms"].items():
        target = row["target"]; ref = row["rt02_reference"]
        lines.append(
            f"| {label} | {target.get('n', 0)} | {ref.get('n', 0)} | {row['peak_ratio']:.2f} | "
            f"{row['nearest_signed_waveform_correlation']:.2f} | {row['nearest_magnitude_waveform_correlation']:.2f} | "
            f"{100 * target.get('duplicate_fraction_median', 0):.1f}% |"
        )
    lines += ["", "## Candidate preprocessing", "",
              "| Candidate | dev recall | held-out repetition | ambient events |",
              "|---|---:|---:|---:|"]
    for row in report["candidate_results"][:12]:
        lines.append(f"| {row['name']} | {row['development_recall']:.1%} | {row['validation_recall']:.1%} | {row['ambient_events']} |")
    lines += ["", "## Limits", ""] + [f"- {item}" for item in report["limitations"]]
    return "\n".join(lines) + "\n"


def json_ready(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {key: json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    return value
