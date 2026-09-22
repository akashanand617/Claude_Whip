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


def schedule_for(args) -> list[session.Prompt]:
    """
    The one place a schedule is built.

    Preview and record previously built it separately, and drifted: --soft/--hard
    reached the preview but not the recording, so the preview promised 104
    prompts and the session ran 200. A preview that disagrees with the run is
    worse than either number being wrong.
    """
    if getattr(args, "matrix", False):
        names = [g.strip() for g in (args.gestures or "flick").split(",") if g.strip()]
        return session.build_matrix_schedule(tuple(names), reps=args.reps, seed=args.seed)
    if getattr(args, "fill", False):
        from whip import audit

        short = audit.corpus_shortfall(DATA_DIR, target=args.target)
        if args.classes:
            wanted = {c.strip() for c in args.classes.split(",") if c.strip()}
            short = {k: n for k, n in short.items() if k in wanted or k.rsplit("_", 1)[0] in wanted}
        if not short:
            raise SystemExit("nothing to fill: no class is below the median (or below --target); "
                             f"audit files are read from {DATA_DIR} (run `python -m probe.audit --all --write` first)")
        if getattr(args, "blocked", False):
            return session.build_blocked_fill_schedule(short, seed=args.seed)
        return session.build_fill_schedule(short, seed=args.seed)
    if args.gestures:
        names = [g.strip() for g in args.gestures.split(",") if g.strip()]
        from whip.registry import load_registry

        registry = load_registry()
        unknown = [n for n in names if registry.resolve(n) is None]
        if unknown:
            raise SystemExit(f"unknown gesture(s): {', '.join(unknown)} -- "
                             f"declared vocabulary: {', '.join(registry.names)}")
        canonical = [registry.canonical(n) for n in names]
        if getattr(args, "blocked", False):
            return session.build_blocked_schedule(canonical, args.prompts // len(canonical), seed=args.seed)
        return session.build_gesture_schedule(canonical, args.prompts, seed=args.seed)
    if args.structured:
        return session.build_structured_schedule(
            {"soft": args.soft, "hard": args.hard}, seed=args.seed
        )
    return session.build_schedule(args.prompts, seed=args.seed)


POSTURE_PAUSE_S = 5.0
# The stream must be delivering accelerometer packets before the first cue.
# Without this, a session against a ring that never streamed cued 48 gestures
# into an empty capture.
DATA_WAIT_S = 8.0
DATA_MIN_PACKETS = 20


class WrongRing(SystemExit):
    pass


def check_ring(info, expected_name: str | None, allow_stock: bool) -> None:
    """
    Refuse to record from a unit that is not ours, or from stock firmware
    (which streams motion at 1 Hz and answers A1 04 with an error). Pure, so
    it is testable without a ring.
    """
    from whip import flashing

    if expected_name and not protocol.is_expected_ring(info.name, expected_name):
        raise WrongRing(f"connected to {info.name!r} at {info.address}, not {expected_name!r}. "
                        "Another ring is advertising and ours is not (asleep, bonded, or in the "
                        "charger). Wake ours, or pass --any-ring to record from this one anyway.")
    mode = flashing.detect_mode(info.firmware)
    if mode != "gesture" and not allow_stock:
        raise WrongRing(f"{info.name} runs firmware {info.firmware!r} ({mode}); it will not stream motion at "
                        "25 Hz. Flash the gesture firmware (python -m probe.serve), or pass --allow-stock.")


POSE_S = 3.0


async def frame_witness(rec, sink: Path) -> str | None:
    """
    Cue the fingers-at-the-floor pose and record which way round the ring is.

    Three snap/clap sessions were recorded turned around relative to the
    flick sessions and nothing in them could show it (no left/right flicks,
    no hanging arm), so the model trained on two frames at once. Every
    session now opens with a 3 s pose whose gravity sign fixes the frame;
    the verdict is written as the session's frame file so the exporter
    rotates it into the canonical wearing. Returns the frame name, or None
    if the pose was not held (the session then carries no witness and the
    audit will say so).
    """
    from whip import audit
    from whip.realtime import Engine

    print(f"\n  ---- FRAME: let your arm hang, fingers pointing at the floor, hold still ({POSE_S:.0f} s) ----", flush=True)
    await asyncio.sleep(POSE_S)
    recent = []
    for _, p in list(rec.records)[-int(POSE_S * 25 * 0.8):]:
        if len(p) >= 8 and p[0] == protocol.CMD_RAW_SENSOR and p[1] == protocol.SUBTYPE_ACCEL:
            s_ = accel_decode(p); recent.append((s_.x, s_.y, s_.z))
    name = Engine.frame_from_pose(recent)
    if name is None:
        print("       pose not held -- no frame witness for this session (the audit will flag it); carry on", flush=True)
        return None
    audit.set_frame(sink, name, evidence=f"fingers-down pose at session start ({len(recent)} samples)")
    print(f"       frame: {name}" + ("  (ring is on the other way round; the exporter will correct it)" if name != "identity" else "  (canonical wearing)"), flush=True)
    return name


def accel_decode(payload: bytes):
    from whip import accel
    return accel.decode(payload)


async def wait_for_data(rec, seconds: float = DATA_WAIT_S, min_packets: int = DATA_MIN_PACKETS) -> None:
    """Block until the capture has accelerometer packets, or abort the session."""
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        n = sum(1 for _, p in rec.records
                if len(p) >= 2 and p[0] == protocol.CMD_RAW_SENSOR and p[1] == protocol.SUBTYPE_ACCEL)
        if n >= min_packets:
            return
        await asyncio.sleep(0.25)
    raise SystemExit(f"no accelerometer data after {seconds:.0f}s ({len(rec.records)} packets, none motion). "
                     "The ring is not streaming: charger-tap it and retry. Nothing was cued.")


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
    await wait_for_data(rec)
    await frame_witness(rec, rec.sink)
    rec._witnessed = True
    await asyncio.sleep(1.5)
    print()
    for i, prompt in enumerate(schedule):
        # A posture change (matrix schedules) gets an announcement and a
        # pause: reorienting the hand is not a 3-second job, and a gesture
        # done while still turning the wrist would be labelled as if still.
        if prompt.posture not in ("", "as you are") and (i == 0 or schedule[i - 1].posture != prompt.posture):
            what = prompt.posture.upper().replace("BLOCK: ", "next block: ").replace("_", " ")
            label = what if prompt.posture.startswith("block:") else f"hand: {what}"
            print(f"\n  ---- {label} -- get set ({POSTURE_PAUSE_S:.0f} s) ----", flush=True)
            await asyncio.sleep(POSTURE_PAUSE_S)
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
    motions = cue_motions(args)
    if args.gestures or getattr(args, "matrix", False) or getattr(args, "fill", False):
        args.kind = "prompted"
    duration = 2.0
    if args.kind == "prompted":
        schedule = schedule_for(args)
        mean_gap = (args.gap_min + args.gap_max) / 2
        # Posture blocks (matrix schedules) each add a spoken "get set" pause;
        # the first --matrix run ended one block early because this did not
        # count them, and the last four gestures were never cued.
        posture_changes = sum(1 for i, p in enumerate(schedule)
                              if p.posture not in ("", "as you are") and (i == 0 or schedule[i - 1].posture != p.posture))
        duration += len(schedule) * (COUNTDOWN_S + mean_gap) + posture_changes * POSTURE_PAUSE_S + 8.0
    if motions:
        # Point gestures and sustained spans in ONE session: the prompts run
        # first, then the spans, each on the stream clock.
        duration += 2.0 + len(motions) * (args.cue_seconds + CUE_SETTLE_S) + 5.0
    if not schedule and not motions:
        duration = args.minutes * 60.0

    stamp = time.strftime("%Y%m%d_%H%M%S")
    session_id = f"{args.kind}_{stamp}"
    sink = DATA_DIR / f"{session_id}.jsonl"
    notes_path = DATA_DIR / f"{session_id}.notes.json"

    async with capture.connected(device) as client:
        info = await capture.read_device_info(client, device)
        check_ring(info, None if args.any_ring else args.ring, args.allow_stock)
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
            from collections import Counter
            mix = Counter(p.label for p in schedule)
            counts = " / ".join(f"{n} {lab}" for lab, n in sorted(mix.items()))
            print(f"schedule    {len(schedule)} prompts ({counts}), interleaved")
            print(f"pacing      {args.gap_min:.1f}-{args.gap_max:.1f}s randomised gaps")
        if motions:
            print(f"spans       {len(motions)} x {args.cue_seconds:.0f}s after the prompts: {', '.join(motions)}")
        if not schedule and not motions:
            print(f"mode        {args.kind}: no prompts, everything unmarked is `none`")

        rec.sink = sink
        tasks = []
        if schedule or motions:
            async def cue_everything():
                if schedule:
                    await run_prompts(rec, notes, schedule, args.gap_min, args.gap_max, random.Random(args.seed))
                if motions:
                    await run_cues(notes, motions, args.cue_seconds, rec)
            tasks.append(asyncio.create_task(cue_everything()))
        else:
            tasks.append(asyncio.create_task(_tick(duration, rec)))

        try:
            await capture.stream(client, duration, sink=sink, capture=rec)
        finally:
            for t in tasks:
                t.cancel()
            # The notes are the labels. Write them the moment the stream ends,
            # before anything else that can fail: a 60-minute ambient session
            # once lost its notes file because the ring dropped the link during
            # the battery read that followed.
            notes.write(notes_path)

        try:
            battery_after = await capture.read_battery(client)
        except Exception as exc:  # the link often drops right at the end; the data is already on disk
            print(f"WARNING: could not read battery after the session: {exc}")
            battery_after = None
        if battery and battery_after:
            print(f"battery     {battery[0]}% -> {battery_after[0]}%")

    notes.write(notes_path)
    print(f"\ncapture     {sink}")
    print(f"notes       {notes_path}  ({len(notes.marks)} marks)")
    print(f"\nnow run:    python -m probe.checkup {session_id}")
    return 0


async def _tick(duration: float, rec=None) -> None:
    if rec is not None:
        await wait_for_data(rec)
        await frame_witness(rec, rec.sink)
    start = time.perf_counter()
    while True:
        await asyncio.sleep(30.0)
        left = duration - (time.perf_counter() - start)
        print(f"  {left / 60:.1f} min left", flush=True)


CUE_SETTLE_S = 3.0


def cue_motions(args) -> list[str]:
    """The span list: --cues, repeated --cue-reps times, motions interleaved (wave, clap, wave, clap, ...)."""
    if not getattr(args, "cues", None):
        return []
    base = [m.strip() for m in args.cues.split(",") if m.strip()]
    return base * max(1, getattr(args, "cue_reps", 1))


async def run_cues(notes: session.SessionNotes, motions: list[str], seconds: float, rec=None) -> None:
    """
    Cycle through named motions on a timer, recording when each began and
    ended ON THE STREAM CLOCK -- the same origin the prompt cues use. (The
    first version stamped spans from its own start, ~2 s after the stream's;
    harmless alone, wrong the moment spans follow prompts in one session.)
    A settle gap between spans keeps one motion's tail out of the next span.
    """
    if rec is not None:
        await wait_for_data(rec)
        if not getattr(rec, "_witnessed", False):
            await frame_witness(rec, rec.sink)
    await asyncio.sleep(2.0)
    print()
    clock = lambda: time.perf_counter() - (rec.notes["stream_t0"] if rec is not None else 0.0)
    for i, motion in enumerate(motions):
        print(f"  [{i + 1}/{len(motions)}]  get ready: {motion.upper()} in {CUE_SETTLE_S:.0f}s", flush=True)
        await asyncio.sleep(CUE_SETTLE_S)
        at = clock()
        print(f"           >>> {motion.upper()}  keep going for {seconds:.0f}s", flush=True)
        await asyncio.sleep(seconds)
        notes.add_cue(motion, at, clock())
        print("           stop", flush=True)
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
    parser.add_argument("--gestures",
                        help="prompted mode over arbitrary registry gestures, "
                             "e.g. 'snap,double_snap' -- how a new class gets data")
    parser.add_argument("--blocked", action="store_true",
                        help="one block per class (all the snaps, then all the double snaps, ...) instead of "
                             "interleaving; with --gestures the --prompts are split evenly, with --fill each "
                             "class's block is exactly its shortfall")
    parser.add_argument("--matrix", action="store_true",
                        help="posture x direction matrix: every hand orientation (palm down/up/left/right) "
                             "x every flick direction, --reps each, for --gestures (default flick); the "
                             "posture is spoken and the schedule pauses when it changes")
    parser.add_argument("--reps", type=int, default=1, help="with --matrix: repetitions per cell")
    parser.add_argument("--fill", action="store_true",
                        help="cue exactly what brings every class up to the median class's valid count "
                             "(or to --target), interleaved; needs probe.audit --all --write")
    parser.add_argument("--classes", default=None,
                        help="with --fill: only these classes (e.g. snap,double_snap,clap,double_clap; a gesture "
                             "name covers all its directions)")
    parser.add_argument("--target", type=int, default=None,
                        help="with --fill: valid gestures per class to aim for (default: the largest class)")
    parser.add_argument("--cues", help="comma-separated motions to cycle through, e.g. 'wave,snap,wobble'")
    parser.add_argument("--cue-seconds", type=float, default=20.0, help="seconds per cued motion")
    parser.add_argument("--cue-reps", type=int, default=1, help="how many times to cycle through --cues")
    parser.add_argument("--hand", default="left", help="which hand wears the ring")
    parser.add_argument("--ring-position", default="index",
                        help="finger and rough rotation, e.g. 'index, logo up'")
    parser.add_argument("--note", default="", help="anything unusual about this session")
    parser.add_argument("--seed", type=int, help="schedule seed; omit for a fresh draw")
    parser.add_argument("--structured", action="store_true",
                        help="blocked design, one direction at a time")
    parser.add_argument("--soft", type=int, default=5,
                        help="soft gestures per class per direction")
    parser.add_argument("--hard", type=int, default=8,
                        help="hard gestures per class per direction")
    parser.add_argument("--preview", action="store_true",
                        help="print the schedule and exit, without touching the ring")
    parser.add_argument("--address")
    parser.add_argument("--ring", default=protocol.EXPECTED_RING,
                        help="the unit to record from (advertised name suffix); any other ring is refused")
    parser.add_argument("--any-ring", action="store_true", help="record from whatever ring connects")
    parser.add_argument("--allow-stock", action="store_true",
                        help="record even on stock firmware (1 Hz motion; useless for gestures)")
    parser.add_argument("--timeout", type=float, default=25.0)
    args = parser.parse_args()

    if args.preview:
        schedule = schedule_for(args)
        from collections import Counter
        mix = Counter(p.label for p in schedule)
        for p in schedule:
            print(f"  [{p.index + 1:>3}]  {p.spoken()}")
        pace = COUNTDOWN_S + (args.gap_min + args.gap_max) / 2
        counts = " / ".join(f"{n} {lab}" for lab, n in sorted(mix.items()))
        print(f"\n  {len(schedule)} prompts ({counts})")
        print(f"  ~{pace:.1f}s each -> ~{len(schedule) * pace / 60:.0f} min")
        motions = cue_motions(args)
        if motions:
            span_min = len(motions) * (args.cue_seconds + CUE_SETTLE_S) / 60
            print(f"  then {len(motions)} spans of {args.cue_seconds:.0f}s ({', '.join(motions)}) -> ~{span_min:.0f} min more")
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
