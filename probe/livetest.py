"""
Live, continuous test of the deployed model on the ring, with a scoreboard.

    python -m probe.livetest                       # cue a mixed schedule of every class, score live
    python -m probe.livetest --rounds 3            # 3 of each class (11 classes -> 33 cues)
    python -m probe.livetest --gestures flick,snap --rounds 5
    python -m probe.livetest --free                # no cues: just watch events for --minutes
    python -m probe.livetest --report data/live/livetest_<stamp>.jsonl   # summarise a finished run

Same engine, same checkpoint, same event logic as `probe.serve` and
`probe.live`: BLE packets -> Engine.feed -> events. On top: a cue schedule
(flicks spoken with a direction, others plain), each cue scored against the
events that arrive in its window (cue .. cue + WINDOW_S, which covers the
~1.3 s event latency), events outside any cue window counted as spurious,
and a running scoreboard printed as it goes. Everything lands in
data/live/livetest_<stamp>.jsonl: one record per cue, one per event, and a
final summary line -- so a run can be read back without having watched it.

Ring guards are the collector's: wrong unit or stock firmware is refused,
and no cue is given until motion packets are arriving.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import logging
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from whip import capture, protocol, session
from whip.realtime import Engine, EventLog, RouterConfig
from whip.registry import load_registry

LIVE_DIR = Path("data/live")
# The raw stream and the cues are ALSO written as an ordinary prompted
# session, so a live run can be replayed offline through the exporter and
# scored by the same tools -- the only real parity check between the live
# engine and the offline pipeline on identical bytes.
SESSIONS_DIR = Path("data/sessions")
COUNTDOWN_S = 3
# An event for a cue must land in this window after the cue: the gesture
# takes up to ~1.5 s and the engine reports ~1.3 s after it ends.
WINDOW_S = 3.5
GAP_S = (1.0, 2.0)


# ------------------------------------------------------------------ scoring

@dataclass
class CueResult:
    index: int
    cue_at: float
    expected: str            # "flick_up", "snap", ...
    fired: list[dict] = field(default_factory=list)   # events inside the window
    verdict: str = "pending"  # hit | wrong | miss
    latency_s: float | None = None


def score_cue(expected: str, events: list[dict], cue_at: float, window_s: float = WINDOW_S) -> tuple[str, float | None, list[dict]]:
    """
    Verdict for one cue from the events in its window. `expected` is
    `<gesture>_<direction>` for directed gestures, else the gesture name.
    The FIRST event in the window decides: hit if it matches, wrong if it is
    another gesture or direction, miss if nothing arrived.
    """
    inside = [e for e in events if cue_at <= e["t_s"] <= cue_at + window_s]
    if not inside:
        return "miss", None, []
    first = inside[0]
    got = f"{first['name']}_{first['direction']}" if first.get("direction", "none") != "none" else first["name"]
    return ("hit" if got == expected else "wrong"), round(first["t_s"] - cue_at, 2), inside


def summarize(cues: list[CueResult], events: list[dict], minutes: float) -> dict:
    by_class: dict[str, dict] = {}
    for c in cues:
        d = by_class.setdefault(c.expected, {"n": 0, "hit": 0, "wrong": 0, "miss": 0, "latency": []})
        d["n"] += 1; d[c.verdict] += 1
        if c.latency_s is not None:
            d["latency"].append(c.latency_s)
    cue_windows = [(c.cue_at, c.cue_at + WINDOW_S) for c in cues]
    spurious = [e for e in events if not any(lo <= e["t_s"] <= hi for lo, hi in cue_windows)]
    for d in by_class.values():
        d["latency_s"] = round(sum(d["latency"]) / len(d["latency"]), 2) if d["latency"] else None
        del d["latency"]
    n = len(cues); hits = sum(c.verdict == "hit" for c in cues)
    return {"cues": n, "hits": hits, "wrong": sum(c.verdict == "wrong" for c in cues), "miss": sum(c.verdict == "miss" for c in cues),
            "recall": round(hits / n, 3) if n else None, "spurious_events": len(spurious),
            "spurious_per_hour": round(60 * len(spurious) / minutes, 1) if minutes else None,
            "minutes": round(minutes, 2), "by_class": by_class}


def expected_name(prompt: session.Prompt, registry) -> str:
    spec = registry.resolve(prompt.label)
    name = spec.name if spec else prompt.label
    return f"{name}_{prompt.direction}" if prompt.direction not in ("any", "none", "") else name


# ------------------------------------------------------------------ schedule

def build_schedule(args, registry) -> list[session.Prompt]:
    names = [g.strip() for g in args.gestures.split(",") if g.strip()] if args.gestures else \
        [g.name for g in registry.gestures if g.kind == "impulsive"]
    rng = random.Random(args.seed)
    prompts: list[session.Prompt] = []
    for _ in range(args.rounds):
        block = []
        for name in names:
            spec = registry.resolve(name)
            if spec is None:
                raise SystemExit(f"unknown gesture {name!r}; vocabulary: {', '.join(registry.names)}")
            dirs = list(session.DIRECTIONS) if spec.split_by_direction else ["any"]
            for d in dirs:
                block.append((spec.name, d))
        rng.shuffle(block)
        for name, d in block:
            prompts.append(session.Prompt(index=len(prompts), label=name, direction=d, amplitude="hard",
                                          windup="natural", posture="as you are", tempo="natural"))
    return prompts


# ------------------------------------------------------------------ the run

def accel_xyz(payload: bytes):
    if len(payload) < 8 or payload[0] != protocol.CMD_RAW_SENSOR or payload[1] != protocol.SUBTYPE_ACCEL:
        return None
    from whip import accel
    s = accel.decode(payload); return (s.x, s.y, s.z)


async def run(args: argparse.Namespace) -> int:
    from probe.collect import check_ring, wait_for_data

    registry = load_registry()
    config = RouterConfig.load()
    threshold = args.threshold if args.threshold is not None else config.threshold
    engine = Engine.from_checkpoint(args.checkpoint, threshold=threshold)
    schedule = [] if args.free else build_schedule(args, registry)
    LIVE_DIR.mkdir(parents=True, exist_ok=True); SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out = LIVE_DIR / f"livetest_{stamp}.jsonl"
    session_id = f"livetest_{stamp}"
    sink = SESSIONS_DIR / f"{session_id}.jsonl"
    notes = session.SessionNotes(session_id=session_id, started_wall=time.time(), kind="prompted",
                                 hand="left", ring_position="index", note="live test; cues scored against live events")
    log = EventLog()
    fh = out.open("w")
    fh.write(json.dumps({"kind": "header", "checkpoint": str(args.checkpoint), "threshold": threshold,
                         "classes": engine.labels, "cues": len(schedule), "started": stamp}) + "\n"); fh.flush()

    print(f"model       {args.checkpoint}  {len(engine.labels)} classes, threshold {threshold:.2f}")
    print(f"schedule    {'free monitoring, ' + str(args.minutes) + ' min' if args.free else f'{len(schedule)} cues, {WINDOW_S:.1f} s window each'}")
    print(f"log         {out}\n")

    device = await capture.find_ring(address=args.address, timeout=args.timeout)
    stop = asyncio.Event()
    queue: collections.deque = collections.deque()
    events: list[dict] = []
    cues: list[CueResult] = []
    t0_holder = {"t0": None}

    def stream_clock() -> float:
        return time.perf_counter() - t0_holder["t0"]

    async def consume() -> None:
        while not stop.is_set():
            drained = False
            while queue:
                t, payload = queue.popleft(); drained = True
                for ev in engine.feed(t, payload):
                    action = config.action_for(ev); log.write(ev, action)
                    rec = {"kind": "event", "t_s": round(ev.t_s, 3), "name": ev.name, "direction": ev.direction,
                           "confidence": round(ev.confidence, 3), "action": action}
                    events.append(rec); fh.write(json.dumps(rec) + "\n"); fh.flush()
                    print(f"      event  {ev.name:<13} dir={ev.direction:<6} conf={ev.confidence:.2f} @{ev.t_s:7.2f}s", flush=True)
            if not drained:
                await asyncio.sleep(0.03)

    async def cue_all(rec) -> None:
        await wait_for_data(rec)
        t0_holder["t0"] = rec.notes["stream_t0"]
        rng = random.Random(args.seed)
        # Calibration pose: the ring may be worn either way round; two seconds
        # with the fingers pointing at the floor tells the engine which.
        print("\n  ---- CALIBRATE: let your arm hang, fingers pointing at the floor, hold still (3 s) ----", flush=True)
        await asyncio.sleep(3.0)
        recent = [accel_xyz(p) for _, p in list(rec.records)[-60:]]
        recent = [r for r in recent if r is not None]
        got = engine.calibrate(recent, stream_clock())
        print(f"       frame: {got or 'pose not held -- keeping ' + engine.frame_name}"
              + ("  (ring is on the other way round; corrected)" if got == "flip_axis0" else ""), flush=True)
        fh.write(json.dumps({"kind": "frame", "t_s": round(stream_clock(), 3), "frame": engine.frame_name, "from_pose": got}) + "\n"); fh.flush()
        if args.free:
            end = stream_clock() + args.minutes * 60
            while stream_clock() < end and not stop.is_set():
                await asyncio.sleep(30)
                print(f"  ... {stream_clock()/60:.1f} min, {len(events)} events", flush=True)
            stop.set(); return
        await asyncio.sleep(2.0)
        for prompt in schedule:
            exp = expected_name(prompt, registry)
            print(f"  [{prompt.index + 1}/{len(schedule)}]  {prompt.spoken()}", flush=True)
            for n in range(COUNTDOWN_S, 0, -1):
                print(f"        {n}...", end="\r", flush=True); await asyncio.sleep(1.0)
            cue_at = stream_clock(); print("        >>> NOW                       ", flush=True)
            notes.add_mark(prompt, cue_at)
            cues.append(CueResult(index=prompt.index, cue_at=cue_at, expected=exp))
            await asyncio.sleep(WINDOW_S)
            c = cues[-1]; c.verdict, c.latency_s, c.fired = score_cue(exp, events, cue_at)
            fh.write(json.dumps({"kind": "cue", "index": c.index, "cue_at": round(cue_at, 3), "expected": exp, "verdict": c.verdict,
                                 "latency_s": c.latency_s, "fired": [f"{e['name']}/{e['direction']}" for e in c.fired]}) + "\n"); fh.flush()
            hits = sum(x.verdict == "hit" for x in cues)
            mark = {"hit": "HIT ", "wrong": "WRONG", "miss": "MISS"}[c.verdict]
            got = f" got {c.fired[0]['name']}/{c.fired[0]['direction']}" if c.verdict == "wrong" else ""
            print(f"        {mark}{got}   latency {c.latency_s if c.latency_s is not None else '-'} s     score {hits}/{len(cues)}", flush=True)
            await asyncio.sleep(rng.uniform(*GAP_S))
        await asyncio.sleep(2.0); stop.set()

    async with capture.connected(device) as client:
        info = await capture.read_device_info(client, device)
        check_ring(info, None if args.any_ring else protocol.EXPECTED_RING, False)
        battery = await capture.read_battery(client)
        print(f"connected   {info.name}  fw {info.firmware}" + (f"  battery {battery[0]}%" if battery else ""))
        rec = capture.Capture(device=info, started_wall=time.time(), param=protocol.RAW_ENABLE_ALL, label=session_id,
                              notes={"session_kind": "prompted", "hand": "left", "ring_position": "index", "stream_t0": 0.0})
        consumer = asyncio.create_task(consume()); cuer = asyncio.create_task(cue_all(rec))
        started = time.perf_counter()
        try:
            await capture.stream(client, duration=0, stop=stop, param=protocol.RAW_ENABLE_ALL, on_record=queue.append, capture=rec, sink=sink)
        finally:
            stop.set(); cuer.cancel()
            if not args.free:
                notes.write(SESSIONS_DIR / f"{session_id}.notes.json")
            if engine.frame_name != "identity":
                from whip import audit
                audit.set_frame(sink, engine.frame_name, evidence="live calibration pose / auto-frame")
            for t_c, name in engine.frame_changes:
                fh.write(json.dumps({"kind": "frame_change", "t_s": round(t_c, 3), "frame": name}) + "\n")
            await consumer
            for ev in engine.finish():
                log.write(ev, config.action_for(ev))
            log.close()
            minutes = (time.perf_counter() - started) / 60
            summary = summarize(cues, events, minutes)
            fh.write(json.dumps({"kind": "summary", **summary}) + "\n"); fh.close()
            print_summary(summary, out)
            if not args.free:
                print(f"  replay offline: python -m probe.audit {session_id} && python -m probe.livetest --replay {session_id}")
    return 0


def print_summary(s: dict, path: Path) -> None:
    print(f"\n=== live test summary ({path})")
    if s["cues"]:
        print(f"  cues {s['cues']}  hits {s['hits']}  wrong {s['wrong']}  miss {s['miss']}  recall {100*s['recall']:.1f}%")
        for k, d in s["by_class"].items():
            print(f"    {k:20s} {d['hit']}/{d['n']}  wrong {d['wrong']}  miss {d['miss']}  latency {d['latency_s']}")
    print(f"  spurious events {s['spurious_events']} in {s['minutes']:.1f} min = {s['spurious_per_hour']}/h")


def replay(session_id: str, checkpoint: Path, threshold: float | None) -> int:
    """
    Score the saved live session OFFLINE: exporter windows -> the same
    checkpoint -> the same event logic -> the same cue scoring. If this
    agrees with the live summary, the live engine is faithful; if it does
    not, the difference is in the engine's stream handling, not the model.
    """
    import numpy as np, torch
    from whip import dataset, evaluate, events
    from whip import model as gm
    registry = load_registry()
    cap, notes_path = SESSIONS_DIR / f"{session_id}.jsonl", SESSIONS_DIR / f"{session_id}.notes.json"
    ws = dataset.windows_from_session(cap, notes_path, registry=registry)
    X = np.array([w.axes for w in ws], dtype="float32"); G = np.array([w.gravity for w in ws], dtype="float32"); starts = np.array([w.start_s for w in ws])
    model, meta = gm.load(checkpoint); model.eval(); labels = meta["labels"]
    thr = threshold if threshold is not None else RouterConfig.load().threshold
    with torch.no_grad(): probs = torch.softmax(model(torch.tensor(gm.to_model_input(X, meta["channels"], gravity=G))), 1).numpy()
    ev = events.detect(evaluate.labels_at(probs, labels, thr), starts.tolist(), policies=registry.policies(labels))
    evs = [{"t_s": float(e.centre_s), "name": registry.collapse(e.label)[0], "direction": registry.collapse(e.label)[1], "confidence": 1.0} for e in ev]
    marks = json.loads(notes_path.read_text())["marks"]
    cues = []
    for m in marks:
        p = session.Prompt(index=m["index"], label=m["label"], direction=m["direction"], amplitude=m.get("amplitude", ""), windup="", posture="", tempo="")
        c = CueResult(m["index"], m["cue_at"], expected_name(p, registry)); c.verdict, c.latency_s, c.fired = score_cue(c.expected, evs, c.cue_at); cues.append(c)
    minutes = (starts[-1] - starts[0]) / 60 if len(starts) > 1 else 0
    print(f"offline replay of {session_id} with {checkpoint} at thr {thr} ({len(ws)} windows):")
    print_summary(summarize(cues, evs, minutes), cap)
    for c in cues:
        if c.verdict != "hit": print(f"    #{c.index:3d} {c.expected:20s} {c.verdict:5s} fired {[f'{e['name']}/{e['direction']}' for e in c.fired]}")
    return 0


def report(path: Path) -> int:
    recs = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    summ = next((r for r in recs if r.get("kind") == "summary"), None)
    if summ is None:
        cues = [CueResult(r["index"], r["cue_at"], r["expected"], [], r["verdict"], r["latency_s"]) for r in recs if r.get("kind") == "cue"]
        events = [r for r in recs if r.get("kind") == "event"]
        minutes = (max([r["t_s"] for r in events] + [c.cue_at for c in cues]) / 60) if (events or cues) else 0
        summ = summarize(cues, events, minutes); print("(run did not finish; summary reconstructed)")
    print_summary(summ, path)
    for r in recs:
        if r.get("kind") == "cue" and r["verdict"] != "hit":
            print(f"    #{r['index']:3d} {r['expected']:20s} {r['verdict']:5s} fired {r['fired']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--checkpoint", type=Path, default=Path("data/model.pt"))
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--gestures", default=None, help="comma-separated subset; default every impulsive gesture")
    parser.add_argument("--rounds", type=int, default=2, help="how many of each (direction-)class to cue")
    parser.add_argument("--free", action="store_true", help="no cues, just watch events")
    parser.add_argument("--minutes", type=float, default=5.0, help="with --free: how long")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--report", type=Path, default=None, help="summarise a finished log instead of running")
    parser.add_argument("--replay", default=None, metavar="SESSION_ID", help="score a saved live session offline through the exporter")
    parser.add_argument("--address"); parser.add_argument("--timeout", type=float, default=25.0)
    parser.add_argument("--any-ring", action="store_true")
    args = parser.parse_args()
    if args.report:
        return report(args.report)
    if args.replay:
        return replay(args.replay, args.checkpoint, args.threshold)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nstopped -- partial log is on disk; python -m probe.livetest --report <log> summarises it")
        return 0
    except RuntimeError as exc:
        print(f"error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
