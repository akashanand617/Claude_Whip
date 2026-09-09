"""
Record a gesture collection session.

    python -m probe.collect --prompts 40                 # prompted block
    python -m probe.collect --kind negative --minutes 30 # negatives, no prompts
    python -m probe.collect --kind naturalistic --minutes 20

Prompted mode cues each gesture with a countdown and records the cue timestamp,
so **there is no marking motion in the signal at all** -- the thing that would
otherwise contaminate every labelled window.

The capture is continuous and unsegmented; marks live in a sidecar JSON. Windowing
and label-coverage decisions happen offline against the stored stream, because
those decisions have already changed once and will change again.

Run `python -m probe.checkup <session>` afterwards before trusting the data.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import random
import time
from pathlib import Path

from whip import capture, protocol, session

DATA_DIR = Path("data/sessions")

# Two seconds is enough to get set once the prompt has already been read. The
# prompt is shown at the *start* of the preceding gap, so reading time overlaps
# the settle time instead of stacking on top of it.
COUNTDOWN_S = 2


async def run_prompts(rec: capture.Capture, notes: session.SessionNotes,
                      schedule: list[session.Prompt], gap_lo: float, gap_hi: float,
                      rng: random.Random) -> None:
    """
    Cue each gesture, recording when the cue fired. Runs alongside the stream.

    Gaps are randomised, for two reasons. A gesture reaches 1.4 s and the window
    is 2.0 s, so anything under ~3.4 s cue-to-cue lets one window span two
    gestures -- a window with no defined label. And a *constant* gap teaches a
    rhythm: "quiet then motion" becomes correlated with the label, which is the
    windup leak in another form. In use, gestures emerge from ongoing activity.
    """
    await asyncio.sleep(1.5)
    print()
    for i, prompt in enumerate(schedule):
        # Show it, give a short countdown, cue, then settle -- and during the
        # settle, show the next one so it is already read by the time its
        # countdown starts.
        print(f"  [{prompt.index + 1}/{len(schedule)}]  {prompt.spoken()}", flush=True)
        for n in range(COUNTDOWN_S, 0, -1):
            print(f"        {n}...", end="\r", flush=True)
            await asyncio.sleep(1.0)

        cue = time.perf_counter() - rec.notes["stream_t0"]
        notes.add_mark(prompt, cue)
        print("        >>> NOW                              ", flush=True)

        await asyncio.sleep(rng.uniform(gap_lo, gap_hi))
    print("\n  schedule complete, letting the stream run out\n", flush=True)


async def run(args: argparse.Namespace) -> int:
    device = await capture.find_ring(address=args.address, timeout=args.timeout)

    schedule: list[session.Prompt] = []
    if args.kind == "prompted":
        schedule = (session.build_structured_schedule(seed=args.seed) if args.structured
                    else session.build_schedule(args.prompts, seed=args.seed))
        mean_gap = (args.gap_min + args.gap_max) / 2
        duration = 2.0 + len(schedule) * (COUNTDOWN_S + mean_gap) + 8.0
    elif args.cues:
        motions = [m.strip() for m in args.cues.split(",") if m.strip()]
        duration = 2.0 + len(motions) * args.cue_seconds + 5.0
    else:
        duration = args.minutes * 60.0

    stamp = time.strftime("%Y%m%d_%H%M%S")
    session_id = f"{args.kind}_{stamp}"
    sink = DATA_DIR / f"{session_id}.jsonl"
    notes_path = DATA_DIR / f"{session_id}.notes.json"

    async with capture.connected(device) as client:
        info = await capture.read_device_info(client, device)
        battery = await capture.read_battery(client)

        notes = session.SessionNotes(
            session_id=session_id,
            started_wall=time.time(),
            kind=args.kind,
            hand=args.hand,
            ring_position=args.ring_position,
            note=args.note,
        )

        rec = capture.Capture(
            device=info, started_wall=time.time(), param=protocol.RAW_ENABLE_ALL,
            label=session_id,
            notes={"battery_before": battery[0] if battery else None,
                   "session_kind": args.kind, "hand": args.hand,
                   "ring_position": args.ring_position, "stream_t0": 0.0},
        )

        print(f"session     {session_id}")
        print(f"device      {info.name}  fw {info.firmware}")
        if battery:
            print(f"battery     {battery[0]}%")
        print(f"hand        {args.hand}   ring {args.ring_position}")
        print(f"duration    {duration / 60:.1f} min -> {sink}")
        if schedule:
            flags = sum(1 for p in schedule if p.label == "flag")
            print(f"schedule    {len(schedule)} prompts ({flags} flag / {len(schedule) - flags} approve), interleaved")
            print(f"pacing      {args.gap_min:.1f}-{args.gap_max:.1f}s randomised gaps")
        elif args.cues:
            print(f"motions     {len([m for m in args.cues.split(',') if m.strip()])} x {args.cue_seconds:.0f}s, all labelled `none`")
        else:
            print(f"mode        {args.kind}: no prompts, everything unmarked is `none`")

        tasks = []
        if schedule:
            rng = random.Random(args.seed)
            tasks.append(asyncio.create_task(
                run_prompts(rec, notes, schedule, args.gap_min, args.gap_max, rng)))
        elif args.cues:
            motions = [m.strip() for m in args.cues.split(",") if m.strip()]
            tasks.append(asyncio.create_task(run_cues(notes, motions, args.cue_seconds)))
        else:
            tasks.append(asyncio.create_task(_tick(duration)))

        try:
            await capture.stream(client, duration, sink=sink, capture=rec)
        finally:
            for t in tasks:
                t.cancel()

        battery_after = await capture.read_battery(client)
        if battery and battery_after:
            print(f"battery     {battery[0]}% -> {battery_after[0]}%")

    notes.write(notes_path)
    print(f"\ncapture     {sink}")
    print(f"notes       {notes_path}  ({len(notes.marks)} marks)")
    print(f"\nnow run:    python -m probe.checkup {session_id}")
    return 0


async def _tick(duration: float) -> None:
    start = time.perf_counter()
    while True:
        await asyncio.sleep(30.0)
        left = duration - (time.perf_counter() - start)
        print(f"  {left / 60:.1f} min left", flush=True)


async def run_cues(notes: session.SessionNotes, motions: list[str], seconds: float) -> None:
    """Cycle through named motions on a timer, recording when each began."""
    await asyncio.sleep(2.0)
    print()
    start = time.perf_counter()
    for i, motion in enumerate(motions):
        at = time.perf_counter() - start
        print(f"  [{i + 1}/{len(motions)}]  >>> {motion.upper()}  ({seconds:.0f}s)", flush=True)
        await asyncio.sleep(seconds)
        notes.add_cue(motion, at, time.perf_counter() - start)
    print("\n  motions complete\n", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Record a gesture collection session")
    parser.add_argument("--kind", default="prompted",
                        choices=("prompted", "naturalistic", "negative", "probe"))
    parser.add_argument("--prompts", type=int, default=40, help="prompted mode: gestures to cue")
    parser.add_argument("--gap-min", type=float, default=session.MIN_GAP_S,
                        help="minimum quiet after a cue; below this a window can span two gestures")
    parser.add_argument("--gap-max", type=float, default=session.MAX_GAP_S,
                        help="maximum quiet after a cue; randomised so no rhythm is learnable")
    parser.add_argument("--minutes", type=float, default=20.0, help="non-prompted modes: length")
    parser.add_argument("--cues", help="comma-separated motions to cycle through, e.g. 'wave,snap,wobble'")
    parser.add_argument("--cue-seconds", type=float, default=20.0, help="seconds per cued motion")
    parser.add_argument("--hand", default="left", help="which hand wears the ring")
    parser.add_argument("--ring-position", default="index",
                        help="finger and rough rotation, e.g. 'index, logo up'")
    parser.add_argument("--note", default="", help="anything unusual about this session")
    parser.add_argument("--seed", type=int, help="schedule seed; omit for a fresh draw")
    parser.add_argument("--structured", action="store_true",
                        help="blocked design: 10 soft + 15 hard per class per direction")
    parser.add_argument("--preview", action="store_true",
                        help="print the schedule and exit, without touching the ring")
    parser.add_argument("--address")
    parser.add_argument("--timeout", type=float, default=25.0)
    args = parser.parse_args()

    if args.preview:
        schedule = (session.build_structured_schedule(seed=args.seed) if args.structured
                    else session.build_schedule(args.prompts, seed=args.seed))
        flags = sum(1 for p in schedule if p.label == "flag")
        for p in schedule:
            print(f"  [{p.index + 1:>3}]  {p.spoken()}")
        pace = COUNTDOWN_S + (args.gap_min + args.gap_max) / 2
        print(f"\n  {len(schedule)} prompts ({flags} flag / {len(schedule) - flags} approve)")
        print(f"  ~{pace:.1f}s each -> ~{len(schedule) * pace / 60:.0f} min")
        print("  (no ring needed; re-run without --preview to record)")
        return 0

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    try:
        return asyncio.run(run(args))
    except RuntimeError as exc:
        print(f"error: {exc}")
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted -- partial capture and marks are on disk")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
