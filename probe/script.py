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
BRIDGE_S = 0.08          # sub-1 g dips of two samples or less are inside a stroke
MIN_CUT_GAP_S = 0.12     # a gesture boundary must be at least this much below 1 g
DECODER_GAP_S = events.QUIET_S   # what the live decoder needs between movements to keep them apart
EXPECT_S = {"snap": (0.0, 0.6), "double_clap": (0.15, 1.3), "flick": (0.08, 1.4), "double_flick": (0.45, 2.0)}


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


def stretches(raw_path: Path):
    """(onsets, offsets, peaks) of every stretch at or above ONSET_G (two-sample gaps bridged), frame applied, plus the calibration time to skip."""
    _, records = capture.load_capture(raw_path)
    t, a = [], []
    for ts, payload in records:
        if len(payload) >= 8 and payload[0] == 0xA1 and payload[1] == 0x03:
            s = accel.decode(payload); t.append(ts); a.append((s.x, s.y, s.z))
    t = np.asarray(t, dtype="float64"); x = (np.asarray(a, dtype="float64") / accel.COUNTS_PER_G).T
    x = audit.frame_for(raw_path) @ x
    mags = events.impulsive_magnitude(x)
    idx = np.where(mags >= events.ONSET_G)[0]
    runs: list[list[int]] = []
    for i in idx:
        if runs and t[i] - t[runs[-1][1]] <= BRIDGE_S:
            runs[-1][1] = i
        else:
            runs.append([i, i])
    skip = 0.0
    fp = audit.frame_path(raw_path)
    if fp.exists():
        m = re.search(r"at ([0-9.]+) s", json.loads(fp.read_text()).get("evidence", ""))
        if m:
            skip = float(m.group(1)) + 1.0     # the calibration pose and the lift out of it
    runs = [r for r in runs if t[r[0]] >= skip]
    ons = np.array([t[r[0]] for r in runs]); offs = np.array([t[r[1]] for r in runs])
    peaks = np.array([mags[r[0]:r[1] + 1].max() for r in runs])
    return ons, offs, peaks, skip


def group_blocks(ons, offs, gap_s: float = BLOCK_GAP_S) -> list[list[int]]:
    """Indices of stretches per block: a still of `gap_s` between stretches starts a new block."""
    blocks: list[list[int]] = []
    for i in range(len(ons)):
        if blocks and ons[i] - offs[blocks[-1][-1]] < gap_s:
            blocks[-1].append(i)
        else:
            blocks.append([i])
    return blocks


def cut_block(ons, offs, peaks, members: list[int], n: int) -> list[dict] | None:
    """
    Split one block's stretches into exactly `n` movements at the n-1 widest
    gaps. Fast runs leave no quiet between gestures (measured: 150 of 203
    gaps under 0.2 s), so the live decoder's quiet rule cannot separate them;
    the script's count can. None when the block has fewer stretches than
    gestures, or a chosen gap is narrower than MIN_CUT_GAP_S.
    """
    if len(members) < n:
        return None
    gaps = [(ons[members[k + 1]] - offs[members[k]], k) for k in range(len(members) - 1)]
    chosen = sorted(gaps, reverse=True)[:n - 1]
    if chosen and min(g for g, _ in chosen) < MIN_CUT_GAP_S:
        return None
    margin = (min(g for g, _ in chosen) - max((g for g, _ in sorted(gaps, reverse=True)[n - 1:]), default=0.0)) if chosen else None
    cuts = sorted(k for _, k in chosen)
    out = []; start = 0
    for k in cuts + [len(members) - 1]:
        part = members[start:k + 1]
        out.append({"on_s": float(ons[part[0]]), "off_s": float(offs[part[-1]]), "peak_g": float(peaks[part].max()),
                    "margin_s": margin})
        start = k + 1
    return out


def align(script: list[list[tuple[str, str]]], ons, offs, peaks, blocks: list[list[int]]) -> tuple[list[dict], list[str], dict]:
    """Marks for every block that cuts cleanly into its script count; a report line per block; tempo facts."""
    marks: list[dict] = []
    report: list[str] = []
    index = 0
    gaps_all: list[float] = []
    for k, want in enumerate(script):
        names = " ".join(f"{l}/{d}" if d != "none" else l for l, d in want)
        members = blocks[k] if k < len(blocks) else []
        parts = cut_block(ons, offs, peaks, members, len(want))
        if parts is None:
            report.append(f"block {k + 1:2d}: {len(members)} stretches, cannot cut into {len(want)} movements -> SKIPPED (redo: {names})")
            continue
        odd = []
        for (label, direction), part in zip(want, parts):
            dur = part["off_s"] - part["on_s"]; lo, hi = EXPECT_S[label]
            if not lo <= dur <= hi:
                odd.append(f"{label} {dur:.2f}s")
            marks.append({"index": index, "label": label, "direction": direction, "amplitude": "", "windup": "",
                          "posture": "", "tempo": "", "cue_at": round(part["on_s"] - CUE_LEAD_S, 3),
                          "onset_s": round(part["on_s"], 3), "peak_g": round(part["peak_g"], 2), "duration_s": round(dur, 3)})
            index += 1
        gaps = [round(n["on_s"] - p["off_s"], 2) for p, n in zip(parts, parts[1:])]
        gaps_all += gaps
        margin = parts[0]["margin_s"]
        report.append(f"block {k + 1:2d}: {len(parts)} movements labelled; gaps {gaps} s; cut margin {margin:.2f} s"
                      + (f"; odd durations: {', '.join(odd)}" if odd else ""))
    if len(blocks) > len(script):
        report.append(f"{len(blocks) - len(script)} extra block(s) after the script's end, ignored")
    tempo = {"gaps": gaps_all, "under_decoder": sum(1 for g in gaps_all if g < DECODER_GAP_S)}
    return marks, report, tempo


def label(args) -> int:
    script = load_script(args.script)
    ons, offs, peaks, skip = stretches(args.raw)
    blocks = group_blocks(ons, offs)
    marks, report, tempo = align(script, ons, offs, peaks, blocks)
    print(f"{args.raw}: {len(ons)} stretches above 1 g after {skip:.1f} s, in {len(blocks)} blocks; script has {len(script)} blocks, {sum(map(len, script))} gestures")
    for line in report:
        print("  " + line)
    if tempo["gaps"]:
        g = np.array(tempo["gaps"])
        print(f"  tempo: gap between labelled gestures median {np.median(g):.2f} s, p90 {np.percentile(g, 90):.2f} s; "
              f"{tempo['under_decoder']} of {len(g)} under the live decoder's {DECODER_GAP_S:.1f} s quiet rule "
              f"(those pairs would merge live; the labels here come from the script, not the decoder)")
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
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.command == "show":
        return show(args)
    if args.raw is None:
        ap.error("label needs the raw stream path")
    return label(args)


if __name__ == "__main__":
    sys.exit(main())
