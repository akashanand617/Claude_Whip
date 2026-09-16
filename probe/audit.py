"""
Audit a prompted session's gestures against its own stream.

    python -m probe.audit prompted_20260915_184744
    python -m probe.audit --all
    python -m probe.audit --all --write        # write <session>.audit.json for the exporter

Prints one line per flagged gesture and a session summary: verdict counts,
how many gestures carry each flag, the doubles' stroke spacing and amplitude
ratio, and whether the amplitude and tempo prompts changed anything. Exit 2
when any gesture is invalid, so a session is looked at before it is exported
rather than discovered as a held-out miss weeks later.

With --write the verdicts land in `<session>.audit.json`; `whip.dataset` then
drops every window touching a gesture that is not valid (suspect AND invalid:
uncertain data is made up next session, not trained on) and `probe.rollout`
does not score it. The final "to re-record, corpus-wide" line is what
`probe.collect --fill` will cue: enough of each class to match the largest.
Without --write nothing changes on disk.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from whip import audit

SESSIONS = Path("data/sessions")


def report(session_id: str, verbose: bool, write: bool) -> bool:
    cap, notes = SESSIONS / f"{session_id}.jsonl", SESSIONS / f"{session_id}.notes.json"
    if not notes.exists():
        print(f"{session_id}: no notes, nothing to audit")
        return True
    audits = audit.audit_session(cap, notes)
    if not audits:
        print(f"{session_id}: no impulsive marks")
        return True
    s = audit.summary(audits)
    v = s["by_verdict"]
    print(f"=== {session_id}: {s['n']} gestures  valid {v['valid']}  suspect {v['suspect']}  INVALID {v['invalid']}   " +
          "  ".join(f"{k}:{n}" for k, n in sorted(s["by_flag"].items())))
    for a in audits:
        if a.flags or verbose:
            strokes = ", ".join(f"{t:+.2f}s {g:.1f}g" for t, g in a.strokes) or "-"
            print(f"  #{a.index:3d} {a.label:13s} {a.direction:5s} {a.amplitude:4s} {a.tempo:10s} "
                  f"peak {a.peak_g:4.1f}g onset {'  -  ' if a.onset_s is None else f'{a.onset_s:+.2f}s'} "
                  f"vert {'-' if a.vertical_frac is None else f'{a.vertical_frac:.2f}'}  strokes [{strokes}]  "
                  f"{a.verdict.upper() if a.verdict != 'valid' else ''} {' '.join(a.flags)}")
    if "double_gap_s" in s:
        g, r = s["double_gap_s"], s["double_ratio"]
        print(f"  doubles: stroke gap p5/50/95 {g['p5']:.2f}/{g['p50']:.2f}/{g['p95']:.2f} s (range {audit.DOUBLE_GAP_RANGE_S})   "
              f"2nd/1st peak p5/50/95 {r['p5']:.2f}/{r['p50']:.2f}/{r['p95']:.2f} (range {audit.DOUBLE_RATIO_RANGE})")
    if "peak_by_amplitude" in s:
        print("  amplitude prompt -> median peak: " + "  ".join(f"{k} {v:.1f}g" for k, v in s["peak_by_amplitude"].items()))
    if "double_gap_by_tempo" in s:
        med = s["double_gap_by_tempo"]
        line = "  tempo prompt -> median double stroke gap: " + "  ".join(f"{k} {v:.2f}s" for k, v in med.items())
        if max(med.values()) - min(med.values()) < 0.08:
            line += "   (NO EFFECT: the tempo words did not change execution)"
        print(line)
    hr = audit.hand_rule(cap, notes)
    fr = audit.frame_path(cap); frame = json.loads(fr.read_text())["rotation"] if fr.exists() else "identity"
    verdict = "-" if hr["agrees"] is None else ("matches the sensor-below wearing" if hr["agrees"] else "WORN THE OTHER WAY ROUND -- set a frame")
    print(f"  ring frame: {frame}; hand rule on left/right windows: left +{hr['left'][0]}/-{hr['left'][1]}, right +{hr['right'][0]}/-{hr['right'][1]} -> {verdict}")
    short = audit.shortfall(audits)
    if short:
        print(f"  excluded in this session ({sum(short.values())}): " + "  ".join(f"{k}:{n}" for k, n in short.items()))
    if write:
        print(f"  wrote {audit.write_audit(cap, audits)}")
    return v["invalid"] == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("session", nargs="*", help="session id(s), e.g. prompted_20260915_184744")
    parser.add_argument("--all", action="store_true", help="every prompted session in data/sessions")
    parser.add_argument("-v", "--verbose", action="store_true", help="print every gesture, not just flagged ones")
    parser.add_argument("--write", action="store_true", help="write <session>.audit.json with the verdicts")
    parser.add_argument("--auto-frame", action="store_true",
                        help="if the hand rule says a session was worn the other way round, write its frame file "
                             "(a half-turn about the palm normal) so the exporter corrects it")
    parser.add_argument("--reanchor", action="store_true",
                        help="move the cue of each late-but-clean gesture to its measured onset (keeps "
                             "cue_at_original on the mark), then re-audit")
    parser.add_argument("--exclude", type=int, nargs="+", metavar="INDEX",
                        help="mark these gesture indices excluded (wearer's call, e.g. a redo); with one session id")
    parser.add_argument("--reason", default="excluded by the wearer", help="recorded with --exclude")
    args = parser.parse_args()
    ids = list(args.session)
    if args.all:
        ids += sorted(p.stem for p in SESSIONS.glob("prompted_*.jsonl"))
    if not ids:
        parser.error("give a session id or --all")
    if args.exclude:
        if len(ids) != 1:
            parser.error("--exclude takes exactly one session id")
        done = audit.exclude_marks(SESSIONS / f"{ids[0]}.notes.json", args.exclude, args.reason)
        print(f"excluded marks {done} in {ids[0]} ({args.reason})")
    if args.auto_frame:
        for sid in ids:
            cap, notes = SESSIONS / f"{sid}.jsonl", SESSIONS / f"{sid}.notes.json"
            if not notes.exists() or audit.frame_path(cap).exists():
                continue
            hr = audit.hand_rule(cap, notes)
            if hr["agrees"] is False:
                audit.set_frame(cap, "flip_axis0", evidence=f"hand rule: left +{hr['left'][0]}/-{hr['left'][1]}, right +{hr['right'][0]}/-{hr['right'][1]}")
                print(f"{sid}: worn the other way round -> frame flip_axis0 written")
    if args.reanchor:
        for sid in ids:
            cap, notes = SESSIONS / f"{sid}.jsonl", SESSIONS / f"{sid}.notes.json"
            if notes.exists():
                moved = audit.reanchor(notes, audit.audit_session(cap, notes))
                if moved:
                    print(f"re-anchored marks {moved} in {sid} to their measured onset")
    ok = True
    for sid in ids:
        ok = report(sid, args.verbose, args.write) and ok
    counts = audit.valid_counts(SESSIONS)
    if counts:
        print("\nvalid per class: " + "  ".join(f"{k}:{n}" for k, n in sorted(counts.items())))
    corpus = audit.corpus_shortfall(SESSIONS)
    if corpus:
        print(f"to re-record, corpus-wide (bring every class up to the median, {sum(corpus.values())} gestures): "
              + "  ".join(f"{k}:{n}" for k, n in corpus.items()) + "\n  -> python -m probe.collect --fill   (or --target N to grow every class to N)")
    elif counts:
        print("no class is below the median; use `probe.collect --fill --target N` to grow every class to N")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
