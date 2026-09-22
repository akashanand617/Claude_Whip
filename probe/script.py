"""
Label a scripted free run: gestures done fast, in a known order, with no cues.

    python -m probe.script show  --script data/scripts/interleave_01.txt
    python -m probe.script label data/live/console_<stamp>.jsonl --script data/scripts/interleave_01.txt

Cues leave ~3 s between gestures, which is exactly what a corpus of
gestures-in-the-flow must not have. So the wearer performs a fixed script
as fast as they like, holding still for 3 s between blocks, and the labels
come from the ORDER: the stream is segmented into movements by the same
burst rule the live decoder uses (`events.BurstTracker`, no model), the
movements are grouped into blocks by the 3 s stills, and each block's
movements are labelled by the script's block, in order. A block whose
movement count does not match the script is reported and skipped -- it is
redone, not guessed at.

The result is an ordinary session in data/sessions (capture, notes with
one mark per movement at its onset, frame file), so the audit, exporter,
split and trainer treat it like any cued session.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

from whip import accel, audit, capture, events, session

TOKENS = {
    "F^": ("flick", "up"), "Fv": ("flick", "down"), "F<": ("flick", "left"), "F>": ("flick", "right"),
    "D^": ("double_flick", "up"), "Dv": ("double_flick", "down"), "D<": ("double_flick", "left"), "D>": ("double_flick", "right"),
    "S": ("snap", "none"), "C": ("double_clap", "none"),
}
BLOCK_GAP_S = 2.0        # a still of at least this between movements separates blocks (the script says 3 s)
CUE_LEAD_S = 0.25        # the mark sits this far before the onset, where a cue would have been
MIN_PEAK_G = 2.0         # movements under this are stray (a knuckle on the desk), not script gestures


def load_script(path: Path) -> list[list[tuple[str, str]]]:
    blocks: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            if current:
                blocks.append(current); current = []
            continue
        for tok in line.split():
            if tok not in TOKENS:
                raise SystemExit(f"unknown token {tok!r} in {path}; known: {' '.join(TOKENS)}")
            current.append(TOKENS[tok])
    if current:
        blocks.append(current)
    return blocks


def movements(raw_path: Path, min_peak_g: float = MIN_PEAK_G) -> tuple[list[events.Burst], float]:
    """Bursts of the raw stream (frame applied), and the calibration time to skip."""
    _, records = capture.load_capture(raw_path)
    t, a = [], []
    for ts, payload in records:
        if len(payload) >= 8 and payload[0] == 0xA1 and payload[1] == 0x03:
            s = accel.decode(payload); t.append(ts); a.append((s.x, s.y, s.z))
    t = np.asarray(t, dtype="float64"); x = (np.asarray(a, dtype="float64") / accel.COUNTS_PER_G).T
    x = audit.frame_for(raw_path) @ x
    mags = events.impulsive_magnitude(x)
    tracker = events.BurstTracker()
    for ts, m in zip(t, mags):
        tracker.feed_sample(float(ts), float(m))
    tracker.finish()
    skip = 0.0
    fp = audit.frame_path(raw_path)
    if fp.exists():
        m = re.search(r"at ([0-9.]+) s", json.loads(fp.read_text()).get("evidence", ""))
        if m:
            skip = float(m.group(1)) + 1.0     # the calibration pose and the lift out of it
    return [b for b in tracker.bursts if b.on_s >= skip and b.peak_g >= min_peak_g], skip


def group_blocks(bursts: list[events.Burst], gap_s: float = BLOCK_GAP_S) -> list[list[events.Burst]]:
    blocks: list[list[events.Burst]] = []
    for b in bursts:
        if blocks and b.on_s - blocks[-1][-1].off_s < gap_s:
            blocks[-1].append(b)
        else:
            blocks.append([b])
    return blocks


def align(script: list[list[tuple[str, str]]], found: list[list[events.Burst]]) -> tuple[list[dict], list[str]]:
    """Marks for every block whose movement count matches its script block; a report line per block."""
    marks: list[dict] = []
    report: list[str] = []
    index = 0
    for k, want in enumerate(script):
        got = found[k] if k < len(found) else []
        names = " ".join(f"{l}/{d}" if d != "none" else l for l, d in want)
        if len(got) != len(want):
            report.append(f"block {k + 1:2d}: script {len(want)} movements, recorded {len(got)} -> SKIPPED (redo this block: {names})")
            continue
        for (label, direction), b in zip(want, got):
            marks.append({"index": index, "label": label, "direction": direction, "amplitude": "", "windup": "",
                          "posture": "", "tempo": "", "cue_at": round(b.on_s - CUE_LEAD_S, 3),
                          "onset_s": round(b.on_s, 3), "peak_g": round(b.peak_g, 2), "duration_s": round(b.duration_s, 3)})
            index += 1
        gaps = [round(n.on_s - p.off_s, 2) for p, n in zip(got, got[1:])]
        report.append(f"block {k + 1:2d}: {len(got)} movements labelled, gaps between them {gaps} s")
    if len(found) > len(script):
        report.append(f"{len(found) - len(script)} extra block(s) after the script's end, ignored")
    return marks, report


def label(args) -> int:
    script = load_script(args.script)
    bursts, skip = movements(args.raw, args.min_peak)
    blocks = group_blocks(bursts)
    marks, report = align(script, blocks)
    print(f"{args.raw}: {len(bursts)} movements after {skip:.1f} s, in {len(blocks)} blocks; script has {len(script)} blocks, {sum(map(len, script))} gestures")
    for line in report:
        print("  " + line)
    if not marks:
        print("nothing labelled"); return 2
    stamp = time.strftime("%Y%m%d_%H%M%S")
    sid = f"prompted_{stamp}"
    out = Path("data/sessions") / f"{sid}.jsonl"
    if args.dry_run:
        print(f"dry run: would write {out} with {len(marks)} marks"); return 0
    shutil.copy(args.raw, out)
    notes = session.SessionNotes(session_id=sid, started_wall=time.time(), kind="prompted", hand=args.hand,
                                 ring_position="sensor below", note=f"scripted free run, no cues: {args.script.name}; labels by script order; source {args.raw.name}",
                                 marks=marks)
    notes.write(out.with_suffix(".notes.json"))
    fp = audit.frame_path(args.raw)
    if fp.exists():
        audit.set_frame(out, json.loads(fp.read_text())["rotation"], evidence=f"copied from {args.raw.name} (console calibration pose)")
    print(f"wrote {out} ({len(marks)} marks) -- next: python -m probe.audit {sid} --write, then scripts/rerun.sh")
    return 0


def show(args) -> int:
    script = load_script(args.script)
    print(f"{args.script}: {len(script)} blocks, {sum(map(len, script))} gestures. Hold still 3 s between blocks.\n")
    for k, block in enumerate(script):
        print(f"  {k + 1:2d}.  " + "   ".join(f"{l.replace('_', ' ')} {d}" if d != "none" else l.replace("_", " ") for l, d in block))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("show", "label"))
    ap.add_argument("raw", nargs="?", type=Path, help="raw stream (data/live/console_<stamp>.jsonl) for `label`")
    ap.add_argument("--script", type=Path, default=Path("data/scripts/interleave_01.txt"))
    ap.add_argument("--hand", default="left")
    ap.add_argument("--min-peak", type=float, default=MIN_PEAK_G)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.command == "show":
        return show(args)
    if args.raw is None:
        ap.error("label needs the raw stream path")
    return label(args)


if __name__ == "__main__":
    sys.exit(main())
