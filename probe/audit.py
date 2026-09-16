"""
Audit a prompted session's gestures against its own stream.

    python -m probe.audit prompted_20260915_184744
    python -m probe.audit --all

Prints one line per flagged gesture and a session summary: how many gestures
carry each flag, the doubles' stroke spacing and amplitude ratio, and whether
the amplitude and tempo prompts changed anything. Exit 2 when any gesture has
NO_MOTION or a cued double shows a single stroke, so a session can be
re-recorded before it is exported rather than discovered as a held-out miss
weeks later. Stroke counts are reported, not judged: a recoil and a weak second
tap are the same size at 25 Hz.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from whip import audit

SESSIONS = Path("data/sessions")
HARD_FLAGS = ("NO_MOTION", "DOUBLE_WITH_ONE_STROKE")


def report(session_id: str, verbose: bool) -> bool:
    cap, notes = SESSIONS / f"{session_id}.jsonl", SESSIONS / f"{session_id}.notes.json"
    if not notes.exists():
        print(f"{session_id}: no notes, nothing to audit")
        return True
    audits = audit.audit_session(cap, notes)
    if not audits:
        print(f"{session_id}: no impulsive marks")
        return True
    s = audit.summary(audits)
    print(f"=== {session_id}: {s['n']} gestures, {s['flagged']} flagged  " +
          "  ".join(f"{k}:{v}" for k, v in sorted(s["by_flag"].items())))
    for a in audits:
        if a.flags or verbose:
            strokes = ", ".join(f"{t:+.2f}s {g:.1f}g" for t, g in a.strokes) or "-"
            print(f"  #{a.index:3d} {a.label:13s} {a.direction:5s} {a.amplitude:4s} {a.tempo:10s} "
                  f"peak {a.peak_g:4.1f}g onset {'  -  ' if a.onset_s is None else f'{a.onset_s:+.2f}s'}  strokes [{strokes}]  {' '.join(a.flags)}")
    if "double_gap_s" in s:
        g, r = s["double_gap_s"], s["double_ratio"]
        print(f"  doubles: stroke gap p5/50/95 {g['p5']:.2f}/{g['p50']:.2f}/{g['p95']:.2f} s   "
              f"2nd/1st peak p5/50/95 {r['p5']:.2f}/{r['p50']:.2f}/{r['p95']:.2f}")
    if "peak_by_amplitude" in s:
        print("  amplitude prompt -> median peak: " + "  ".join(f"{k} {v:.1f}g" for k, v in s["peak_by_amplitude"].items()))
    if "double_gap_by_tempo" in s:
        med = s["double_gap_by_tempo"]
        line = "  tempo prompt -> median double stroke gap: " + "  ".join(f"{k} {v:.2f}s" for k, v in med.items())
        if max(med.values()) - min(med.values()) < 0.08:
            line += "   (NO EFFECT: the tempo words did not change execution)"
        print(line)
    return not any(f in HARD_FLAGS for a in audits for f in a.flags)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("session", nargs="*", help="session id(s), e.g. prompted_20260915_184744")
    parser.add_argument("--all", action="store_true", help="every prompted session in data/sessions")
    parser.add_argument("-v", "--verbose", action="store_true", help="print every gesture, not just flagged ones")
    args = parser.parse_args()
    ids = list(args.session)
    if args.all:
        ids += sorted(p.stem for p in SESSIONS.glob("prompted_*.jsonl"))
    if not ids:
        parser.error("give a session id or --all")
    ok = True
    for sid in ids:
        ok = report(sid, args.verbose) and ok
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
