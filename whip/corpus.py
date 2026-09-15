"""
The M2 calibration corpus: load, validate, and schedule taste-contrast items.

Each item is a coding prompt with two complete responses that differ on exactly
one axis of model behavior -- the item's dimension. Both variants are correct;
the label a gesture assigns therefore carries taste, not correctness. The
dimensions and their poles live in corpus/taxonomy.json; fully written items in
corpus/gold/*.md; spec'd items awaiting authoring in corpus/specs.jsonl.
Design rationale and confound table: docs/CALIBRATION.md.

Presentation is single-response: one prompt plus one variant per screen, one
gesture (flag / approve / none). Pairing exists only in analysis, so the
session planner's job is anti-leak scheduling -- pair members far apart, which
pole shows first balanced exactly 50/50, dimensions interleaved so the labeler
never sees the axis coming, and sentinels repeated early and late to measure
fatigue drift.

Everything here is deterministic given (seed, session): a session plan must be
reproducible from its recorded seed, and nothing may depend on the wall clock.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parent.parent / "corpus"
TAXONOMY_PATH = CORPUS_DIR / "taxonomy.json"
GOLD_DIR = CORPUS_DIR / "gold"
SPECS_PATH = CORPUS_DIR / "specs.jsonl"

# Minimum slots between the two members of a pair. Closer than this, the
# second member is judged relative to the first (anchoring) instead of on its
# own -- and deployment only ever shows one response at a time.
MIN_SEPARATION = 4

# How many sentinel items repeat within one session. Each contributes one
# extra showing of the same variant in the first quarter and one in the last;
# disagreement between the two showings is fatigue, not preference.
MAX_SENTINELS = 2

LABELS = ("flag", "none", "approve")
_SCORE = {"flag": -1, "none": 0, "approve": 1}


@dataclass(frozen=True)
class Pole:
    key: str
    summary: str
    context_statement: str


@dataclass(frozen=True)
class Dimension:
    key: str
    question: str
    poles: tuple[Pole, Pole]
    # True where the poles differ in length by construction (an explanatory
    # answer IS longer than a terse one) -- reacting to length there is
    # reacting to the axis, so the length-leak check does not apply.
    length_constitutive: bool = False

    def pole_keys(self) -> tuple[str, str]:
        return (self.poles[0].key, self.poles[1].key)


@dataclass(frozen=True)
class Variant:
    pole: str
    text: str  # a full response for gold items, an authoring spec otherwise


@dataclass(frozen=True)
class Item:
    id: str
    dimension: str
    status: str  # "gold" | "spec"
    domain: str
    sentinel: bool
    task: str
    context: str
    a: Variant
    b: Variant
    notes: str

    def variant(self, key: str) -> Variant:
        return self.a if key == "a" else self.b


def load_taxonomy(path: Path = TAXONOMY_PATH) -> dict[str, Dimension]:
    raw = json.loads(Path(path).read_text())
    dims = {}
    for d in raw["dimensions"]:
        poles = tuple(
            Pole(key=k, summary=v["summary"],
                 context_statement=v["context_statement"])
            for k, v in d["poles"].items()
        )
        dims[d["key"]] = Dimension(
            key=d["key"], question=d["question"], poles=poles,
            length_constitutive=bool(d.get("length_constitutive", False)))
    return dims


_FRONT_KEY = re.compile(r"^([a-z_]+):\s*(.*)$")
_VARIANT_HEAD = re.compile(r"^## ([AB]) \((.+)\)\s*$")
_SECTION_HEAD = re.compile(r"^# (Task|Context|Notes)\s*$")


def _parse_gold(text: str, source: str) -> Item:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{source}: missing frontmatter")
    front: dict[str, str] = {}
    i = 1
    while i < len(lines) and lines[i].strip() != "---":
        m = _FRONT_KEY.match(lines[i])
        if m:
            front[m.group(1)] = m.group(2).strip()
        i += 1
    i += 1  # past the closing ---

    sections: dict[str, list[str]] = {}
    poles: dict[str, str] = {}
    current: str | None = None
    for line in lines[i:]:
        m = _SECTION_HEAD.match(line)
        if m:
            current = m.group(1).lower()
            sections[current] = []
            continue
        m = _VARIANT_HEAD.match(line)
        if m:
            current = m.group(1).lower()
            poles[current] = m.group(2).strip()
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)

    def body(key: str) -> str:
        return "\n".join(sections.get(key, [])).strip()

    for required in ("task", "a", "b"):
        if not body(required):
            raise ValueError(f"{source}: empty or missing section '{required}'")

    return Item(
        id=front.get("id", ""),
        dimension=front.get("dimension", ""),
        status=front.get("status", "gold"),
        domain=front.get("domain", ""),
        sentinel=front.get("sentinel", "false").lower() == "true",
        task=body("task"),
        context=body("context"),
        a=Variant(pole=poles.get("a", ""), text=body("a")),
        b=Variant(pole=poles.get("b", ""), text=body("b")),
        notes=body("notes"),
    )


def _parse_spec(record: dict) -> Item:
    return Item(
        id=record["id"],
        dimension=record["dimension"],
        status=record.get("status", "spec"),
        domain=record.get("domain", ""),
        sentinel=bool(record.get("sentinel", False)),
        task=record["task"],
        context=record.get("context", ""),
        a=Variant(pole=record["a_pole"], text=record["a_spec"]),
        b=Variant(pole=record["b_pole"], text=record["b_spec"]),
        notes=record.get("notes", ""),
    )


def load_items(gold_dir: Path = GOLD_DIR,
               specs_path: Path = SPECS_PATH) -> list[Item]:
    items = []
    for path in sorted(Path(gold_dir).glob("*.md")):
        items.append(_parse_gold(path.read_text(), str(path)))
    specs = Path(specs_path)
    if specs.exists():
        for line in specs.read_text().splitlines():
            if line.strip():
                items.append(_parse_spec(json.loads(line)))
    return items


def validate(taxonomy: dict[str, Dimension], items: list[Item]) -> list[str]:
    """Every string returned is a defect. An empty list is the pass."""
    problems = []
    seen: set[str] = set()
    for it in items:
        where = it.id or "<missing id>"
        if not it.id:
            problems.append(f"{where}: missing id")
        elif it.id in seen:
            problems.append(f"{where}: duplicate id")
        seen.add(it.id)
        if it.dimension not in taxonomy:
            problems.append(f"{where}: unknown dimension {it.dimension!r}")
            continue
        if not it.id.startswith(it.dimension + "-"):
            problems.append(f"{where}: id does not start with its dimension")
        expected = set(taxonomy[it.dimension].pole_keys())
        got = {it.a.pole, it.b.pole}
        if got != expected:
            problems.append(f"{where}: poles {sorted(got)} != {sorted(expected)}")
        if it.status not in ("gold", "spec"):
            problems.append(f"{where}: bad status {it.status!r}")
        if not it.a.text or not it.b.text:
            problems.append(f"{where}: empty variant text")
        if not it.domain:
            problems.append(f"{where}: missing domain")

    # Length leak: within a dimension, if the longer response always belongs to
    # the same pole, response length alone predicts the pole and the labeler
    # can react to length instead of the axis. Only decidable with enough gold,
    # and only meaningful where length is incidental to the axis -- dimensions
    # marked length_constitutive are exempt because their poles differ in
    # length by definition.
    by_dim: dict[str, list[Item]] = {}
    for it in items:
        if it.status == "gold" and it.dimension in taxonomy:
            by_dim.setdefault(it.dimension, []).append(it)
    for dim, gold in by_dim.items():
        if len(gold) < 4 or taxonomy[dim].length_constitutive:
            continue
        longer = {it.a.pole if len(it.a.text) > len(it.b.text) else it.b.pole
                  for it in gold}
        if len(longer) == 1:
            problems.append(
                f"dimension {dim}: pole {longer.pop()!r} is longer in all "
                f"{len(gold)} gold items -- length predicts the pole")
    return problems


def label_pair(a_label: str, b_label: str) -> dict:
    """
    Read one pair's two labels as a preference.

    preference = score(a) - score(b) with approve=+1, none=0, flag=-1, so the
    range is [-2, +2], positive meaning a's pole is preferred. flag on both
    variants means the item itself is suspect (both poles disliked, or the task
    annoyed the labeler) -- routed to review, never into training.
    """
    for label in (a_label, b_label):
        if label not in _SCORE:
            raise ValueError(f"unknown label {label!r}")
    return {
        "preference": _SCORE[a_label] - _SCORE[b_label],
        "review": a_label == "flag" and b_label == "flag",
    }


def _select_pairs(items: list[Item], n_pairs: int,
                  rng: random.Random) -> list[Item]:
    """Round-robin across dimensions so every session covers all of them."""
    gold = [it for it in items if it.status == "gold"]
    if n_pairs > len(gold):
        raise ValueError(f"asked for {n_pairs} pairs, only {len(gold)} gold items")
    by_dim: dict[str, list[Item]] = {}
    for it in gold:
        by_dim.setdefault(it.dimension, []).append(it)
    for pool in by_dim.values():
        rng.shuffle(pool)
    selected = []
    dims = sorted(by_dim)
    while len(selected) < n_pairs:
        rng.shuffle(dims)
        # No dimension twice in a row across the cycle boundary.
        if selected and len(dims) > 1 and dims[0] == selected[-1].dimension:
            dims.append(dims.pop(0))
        for dim in dims:
            if len(selected) >= n_pairs:
                break
            if by_dim[dim]:
                selected.append(by_dim[dim].pop())
        if not any(by_dim[d] for d in dims):
            break
    return selected


def _order_presentations(pairs: list[Item], rng: random.Random) -> list[Item]:
    """
    Two entries per pair, members >= MIN_SEPARATION slots apart and no two
    consecutive slots on the same dimension. Constraint-checked shuffle with a
    deterministic fallback (all first members, then all second members, which
    satisfies both constraints whenever pairs are dimension-interleaved).
    """
    entries = list(pairs) + list(pairs)

    def ok(order: list[Item]) -> bool:
        first_pos: dict[str, int] = {}
        for pos, it in enumerate(order):
            if it.id in first_pos:
                if pos - first_pos[it.id] < MIN_SEPARATION:
                    return False
            else:
                first_pos[it.id] = pos
            if pos and order[pos - 1].dimension == it.dimension:
                return False
        return True

    for _ in range(200):
        rng.shuffle(entries)
        if ok(entries):
            return entries
    return list(pairs) + list(pairs)


def plan_session(taxonomy: dict[str, Dimension], items: list[Item],
                 session: int, n_pairs: int, seed: int) -> dict:
    """
    Deterministic presentation schedule for one labeling session.

    Returns a JSON-serializable plan the labeling UI replays verbatim:
    {"session", "seed", "n_pairs", "presentations": [{"slot", "item",
    "variant", "pole", "dimension", "task", "sentinel_phase"}]}.
    """
    if n_pairs < MIN_SEPARATION:
        raise ValueError(
            f"n_pairs must be >= {MIN_SEPARATION}; fewer pairs cannot keep "
            f"pair members {MIN_SEPARATION} slots apart")
    rng = random.Random(f"whip-m2:{seed}:{session}")
    pairs = _select_pairs(items, n_pairs, rng)
    order = _order_presentations(pairs, rng)

    # Which pole shows first is balanced exactly, not just in expectation: for
    # a shuffled half of the pairs 'a' takes the earlier slot, for the rest 'b'.
    a_first = set(it.id for it in rng.sample(pairs, len(pairs) // 2))
    seen_once: set[str] = set()
    presentations = []
    for it in order:
        if it.id not in seen_once:
            variant = "a" if it.id in a_first else "b"
            seen_once.add(it.id)
        else:
            variant = "b" if it.id in a_first else "a"
        presentations.append({"item": it, "variant": variant,
                              "sentinel_phase": None})

    sentinels = [it for it in pairs if it.sentinel]
    rng.shuffle(sentinels)
    for it in sentinels[:MAX_SENTINELS]:
        variant = rng.choice(("a", "b"))
        quarter = max(1, len(presentations) // 4)
        early = {"item": it, "variant": variant, "sentinel_phase": "early"}
        late = {"item": it, "variant": variant, "sentinel_phase": "late"}
        presentations.insert(rng.randrange(0, quarter), early)
        presentations.insert(rng.randrange(len(presentations) - quarter + 1,
                                           len(presentations) + 1), late)

    out = []
    for slot, p in enumerate(presentations):
        it: Item = p["item"]
        out.append({
            "slot": slot,
            "item": it.id,
            "variant": p["variant"],
            "pole": it.variant(p["variant"]).pole,
            "dimension": it.dimension,
            "task": it.task,
            "sentinel_phase": p["sentinel_phase"],
        })
    return {"session": session, "seed": seed, "n_pairs": n_pairs,
            "presentations": out}
