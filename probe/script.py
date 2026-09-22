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
DECODER_GAP_S = events.QUIET_S   # what the live decoder needs between movements to keep them apart

# What each gesture looks like as stretches above 1 g, measured over the 476
# valid impulsive gestures in the corpus (p10..p90 of count and duration, p90
# of the widest gap INSIDE one gesture) and widened a little. Cutting a block
# at its widest gaps is wrong precisely because of the last column: a double
# clap's own internal gap reaches 1.25 s, wider than a brisk pause between
# two gestures, so the widest gap in a block is often inside a gesture rather
# than between two.
TEMPLATES = {
    #                count      duration        widest internal gap
    "snap":         ((1, 1),   (0.00, 0.12),   0.10),
    "double_clap":  ((2, 4),   (0.20, 1.45),   1.30),
    "flick":        ((1, 3),   (0.05, 1.15),   0.90),
    "double_flick": ((1, 4),   (0.55, 1.65),   0.80),
}
MARGIN_OK = 1.0          # cost a second-best cut must exceed the best by for the block to be trusted


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


def _fit_cost(label: str, ons, offs, part: list[int]) -> float:
    """
    How unlike `label` this group of stretches is: 0.0 is a textbook example.
    Violations are measured in units of the template's own width, so the four
    gestures are scored on one scale.
    """
    (n_lo, n_hi), (d_lo, d_hi), gap_hi = TEMPLATES[label]
    n = len(part)
    dur = float(offs[part[-1]] - ons[part[0]])
    gaps = [float(ons[part[k + 1]] - offs[part[k]]) for k in range(n - 1)]
    cost = max(0, n_lo - n) + max(0, n - n_hi)
    width = max(d_hi - d_lo, 0.1)
    cost += (max(0.0, d_lo - dur) + max(0.0, dur - d_hi)) / width
    if gaps:
        cost += max(0.0, max(gaps) - gap_hi) / max(gap_hi, 0.1)
    return cost


def cut_block(ons, offs, peaks, members: list[int], want: list[tuple[str, str]]) -> tuple[list[dict] | None, float]:
    """
    Split one block's stretches into exactly len(want) movements, IN ORDER,
    choosing the split that best fits what each gesture is supposed to look
    like (`TEMPLATES`). Returns (parts, margin), margin being how much worse
    the best alternative split is -- near zero means the cut is a guess.

    A fast run leaves no reliable quiet between gestures (measured: gaps
    between gestures ran 0.2-1.5 s while a double clap's own internal gap
    reaches 1.25 s), so the script's knowledge of WHAT each gesture is has to
    do the separating, not the gaps alone.
    """
    n = len(want)
    m = len(members)
    if m < n:
        return None, 0.0
    INF = float("inf")
    # best[g][i] = cost of assigning gestures g.. to stretches i.., with the
    # runner-up kept so the margin is a real second-best, not a re-cut.
    best = [[INF] * (m + 1) for _ in range(n + 1)]
    second = [[INF] * (m + 1) for _ in range(n + 1)]
    choice = [[0] * (m + 1) for _ in range(n + 1)]
    best[n][m] = 0.0
    for g in range(n - 1, -1, -1):
        label = want[g][0]
        for i in range(m - 1, -1, -1):
            for take in range(1, m - i + 1):
                if best[g + 1][i + take] == INF:
                    continue
                c = _fit_cost(label, ons, offs, members[i:i + take]) + best[g + 1][i + take]
                if c < best[g][i]:
                    second[g][i] = best[g][i]; best[g][i] = c; choice[g][i] = take
                elif c < second[g][i]:
                    second[g][i] = c
    if best[0][0] == INF:
        return None, 0.0
    parts = []
    i = 0
    for g in range(n):
        take = choice[g][i]; part = members[i:i + take]
        parts.append({"on_s": float(ons[part[0]]), "off_s": float(offs[part[-1]]),
                      "peak_g": float(peaks[part].max()), "n_strokes": take,
                      "fit": round(_fit_cost(want[g][0], ons, offs, part), 2)})
        i += take
    margin = (second[0][0] - best[0][0]) if second[0][0] < INF else INF
    return parts, margin


def align(script: list[list[tuple[str, str]]], ons, offs, peaks, blocks: list[list[int]],
          margin_ok: float = MARGIN_OK) -> tuple[list[dict], list[str], dict]:
    """Marks for every block that fits its script confidently; a report line per block; tempo facts."""
    marks: list[dict] = []
    report: list[str] = []
    index = 0
    gaps_all: list[float] = []
    for k, want in enumerate(script):
        names = " ".join(f"{l}/{d}" if d != "none" else l for l, d in want)
        members = blocks[k] if k < len(blocks) else []
        parts, margin = cut_block(ons, offs, peaks, members, want)
        if parts is None:
            report.append(f"block {k + 1:2d}: {len(members)} stretches, fewer than the {len(want)} gestures -> SKIPPED (redo: {names})")
            continue
        worst = max(p["fit"] for p in parts)
        if margin < margin_ok or worst > 1.0:
            why = (f"the next-best split costs only {margin:.2f} more" if margin < margin_ok
                   else f"one movement fits its gesture badly (cost {worst:.2f})")
            shape = ", ".join(f"{l}:{p['n_strokes']}x{p['off_s'] - p['on_s']:.2f}s" for (l, _), p in zip(want, parts))
            report.append(f"block {k + 1:2d}: cut is not trustworthy -- {why} -> SKIPPED (redo: {names})   [{shape}]")
            continue
        for (label, direction), part in zip(want, parts):
            marks.append({"index": index, "label": label, "direction": direction, "amplitude": "", "windup": "",
                          "posture": "", "tempo": "", "cue_at": round(part["on_s"] - CUE_LEAD_S, 3),
                          "onset_s": round(part["on_s"], 3), "peak_g": round(part["peak_g"], 2),
                          "duration_s": round(part["off_s"] - part["on_s"], 3), "strokes": part["n_strokes"]})
            index += 1
        gaps = [round(n["on_s"] - p["off_s"], 2) for p, n in zip(parts, parts[1:])]
        gaps_all += gaps
        report.append(f"block {k + 1:2d}: {len(parts)} movements labelled; gaps {gaps} s; margin {margin:.2f}, worst fit {worst:.2f}")
    if len(blocks) > len(script):
        report.append(f"{len(blocks) - len(script)} extra block(s) after the script's end, ignored")
    return marks, report, {"gaps": gaps_all, "under_decoder": sum(1 for g in gaps_all if g < DECODER_GAP_S)}


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
