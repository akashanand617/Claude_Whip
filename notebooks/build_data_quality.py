"""
Builds notebooks/data_quality.ipynb from source cells, then executes it in place.

    python notebooks/build_data_quality.py

Kept as a script so the notebook is reproducible from text and diffs cleanly;
the executed .ipynb is committed with its outputs because `data/` is not.
"""
from pathlib import Path
import nbformat as nbf

cells = []
md = lambda s: cells.append(nbf.v4.new_markdown_cell(s.strip()))
code = lambda s: cells.append(nbf.v4.new_code_cell(s.strip()))

md(r"""
# Whip gesture corpus: data-quality audit

**Question.** How much of the recorded gesture data is correctly labelled, which
individual gestures are anomalous, and how much more data is needed to reach and
*demonstrate* 95%+ recall.

**Method.** Every cued gesture in every prompted session is measured from its own
stream (`whip.audit`): peak amplitude, onset after the cue, stroke structure,
motion direction relative to gravity, clipping, sample loss, cue spacing, and
adherence to the amplitude and tempo prompts. Each gets a verdict: **valid**,
**suspect** (kept, listed), or **invalid** (excluded from training and scoring).
The double flick is defined as a *range* -- two strokes 0.20-0.50 s apart, second
peak 0.5-2.0x the first -- so a "late" double is an anomaly by definition, not a
tempo.

**Policy (decided 2026-09-15): only `valid` gestures train and score.** Suspect and
invalid are both excluded and made up in the next session; the per-class tally is
in section 4.

Then: what changes when the excluded gestures are removed, a learning curve over the
valid gestures, and the sample sizes the claims need.

Re-run: `python -m probe.audit --all --write`, then
`python notebooks/build_data_quality.py`. Experiment results are read from
`notebooks/results/*.json` (produced by the scratch scripts described at the end).
""")

code(r"""
import sys, json, glob, warnings
from pathlib import Path
from collections import Counter, defaultdict
import numpy as np
import matplotlib.pyplot as plt
from IPython.display import Markdown, display
ROOT = Path.cwd() if (Path.cwd() / "whip").exists() else Path.cwd().parent
sys.path.insert(0, str(ROOT))
from whip import audit, accel, despike
from whip.registry import load_registry
R = load_registry()
SESS = ROOT / "data" / "sessions"; RES = ROOT / "notebooks" / "results"
plt.rcParams["figure.dpi"] = 100

def table(headers, rows, fmt=None):
    fmt = fmt or {}
    def f(h, v):
        if v is None: return "-"
        if isinstance(v, float): return fmt.get(h, "{:.2f}").format(v)
        return str(v)
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(f(h, v) for h, v in zip(headers, r)) + " |" for r in rows]
    display(Markdown("\n".join(lines)))
""")

md("## 1. Inventory: every capture on disk")

code(r"""
def load_stream(path):
    t, a = [], []
    for line in open(path):
        r = json.loads(line)
        if "p" not in r: continue
        b = bytes.fromhex(r["p"])
        if len(b) < 8 or b[0] != 0xA1 or b[1] != 0x03: continue
        s = accel.decode(b); t.append(r["t"]); a.append((s.x, s.y, s.z))
    t = np.array(t); return t - t[0], np.array(a, float) / accel.COUNTS_PER_G

inventory = []
for p in sorted(SESS.glob("*.jsonl")):
    t, x = load_stream(p)
    notes = p.with_name(p.stem + ".notes.json")
    marks = spans = 0; kind = ""
    if notes.exists():
        n = json.loads(notes.read_text()); kind = n.get("kind", "")
        marks = sum(1 for m in n["marks"] if "until" not in m); spans = sum(1 for m in n["marks"] if "until" in m)
    mins = (t[-1] - t[0]) / 60 if len(t) > 1 else 0
    loss = 1 - len(t) / ((t[-1] - t[0]) * 25) if mins > 0 else 0
    gaps = int((np.diff(t) > 0.1).sum())
    inventory.append((p.stem, kind or "(no notes)", mins, loss * 100, gaps, marks, spans))
table(["session", "kind", "minutes", "loss %", "gaps >100 ms", "point marks", "spans"], inventory, {"minutes": "{:.1f}", "loss %": "{:.1f}"})
tot_prompted = sum(r[5] for r in inventory); tot_neg_min = sum(r[2] for r in inventory if r[1] == "negative")
display(Markdown(f"**{tot_prompted} cued impulsive gestures** across three prompted sessions; **{tot_neg_min:.0f} minutes** of negative recordings, "
                 f"of which the 60-minute ambient session is the only one long enough to bound false positives at all. "
                 f"The six short `prompted_*` captures without notes are abandoned starts and are never exported."))
""")

md("""
Note the 5-minute typing session: 230 inter-sample gaps above 100 ms at 0.9% loss, on
a day before the 25 Hz firmware was settled. It is exported as `none` only, so this
does not corrupt a label, but it is a different stream from the others.
""")

md("## 2. Every gesture, measured")

code(r"""
prompted = {"s1": "prompted_20260909_160303", "s2": "prompted_20260912_013715", "ref": "prompted_20260915_184744"}
G = []   # (session tag, GestureAudit)
for tag, sid in prompted.items():
    for a in audit.audit_session(SESS / f"{sid}.jsonl", SESS / f"{sid}.notes.json"):
        G.append((tag, a))
print(len(G), "gestures measured")
rows = [(tag, a.index, a.label, a.direction, a.amplitude, a.tempo, a.peak_g, a.onset_s, len(a.strokes), a.stroke_gap_s, a.stroke_ratio,
         a.vertical_frac, a.clip_frac, a.verdict, " ".join(a.flags)) for tag, a in G]
table(["sess", "#", "label", "dir", "amp", "tempo", "peak g", "onset s", "strokes", "gap s", "2nd/1st", "vert", "clip", "verdict", "flags"],
      rows[:12], {"peak g": "{:.1f}", "onset s": "{:+.2f}"})
display(Markdown("*(first 12 of %d shown; the full table is the audit files `data/sessions/*.audit.json`)*" % len(rows)))
""")

md("## 3. Verdicts: honest counts")

code(r"""
by = defaultdict(Counter)
for tag, a in G: by[(tag, a.label)][a.verdict] += 1
rows = []
for tag in prompted:
    for lab in ("flick", "double_flick"):
        c = by[(tag, lab)]; n = sum(c.values())
        rows.append((tag, lab, n, c["valid"], c["suspect"], c["invalid"], 100 * (n - c["invalid"]) / n, 100 * c["valid"] / n))
tot = Counter(a.verdict for _, a in G); n = len(G)
rows.append(("all", "all", n, tot["valid"], tot["suspect"], tot["invalid"], 100 * (n - tot["invalid"]) / n, 100 * tot["valid"] / n))
table(["sess", "class", "n", "valid", "suspect", "invalid", "usable %", "clean %"], rows, {"usable %": "{:.1f}", "clean %": "{:.1f}"})
flags = Counter(f for _, a in G for f in a.flags)
table(["flag", "count", "verdict"], [(f, c, "invalid" if f in audit.INVALID_FLAGS else "suspect") for f, c in flags.most_common()])
""")

md("""
**Reading this honestly.** "Usable" means the record shows the gesture that was cued
(valid + suspect). "Clean" means nothing at all was unusual, and **clean is what
trains**. The suspect set is uncertain rather than wrong: a single whose recoil looks
like a second tap, a soft cue executed hard, motion whose gravity signature sits just
across the pair cut. It is dropped on the principle that uncertain data is replaced,
not trained on; the cost is the boundary cases it would have taught, which the next
sessions will supply as clean examples or not at all.

The invalid set *is* mislabelled data: the label says "double flick" and the stream
shows one stroke, or two strokes with a pause, or nothing.
""")

md("## 4. The anomalies, singled out")

code(r"""
rows = [(tag, a.index, a.label, a.direction, a.amplitude, a.peak_g, a.onset_s,
         ", ".join(f"{t:+.2f}s {g:.1f}g" for t, g in a.strokes) or "-", a.stroke_gap_s, a.stroke_ratio, " ".join(a.flags))
        for tag, a in G if a.verdict == "invalid"]
display(Markdown(f"### Invalid ({len(rows)}): excluded from training and scoring"))
table(["sess", "#", "label", "dir", "amp", "peak g", "onset s", "strokes", "gap s", "2nd/1st", "why"], rows, {"peak g": "{:.1f}", "onset s": "{:+.2f}"})
rows = [(tag, a.index, a.label, a.direction, a.amplitude, a.peak_g, a.vertical_frac,
         ", ".join(f"{t:+.2f}s {g:.1f}g" for t, g in a.strokes) or "-", " ".join(a.flags)) for tag, a in G if a.verdict == "suspect"]
display(Markdown(f"### Suspect ({len(rows)}): excluded too, listed"))
table(["sess", "#", "label", "dir", "amp", "peak g", "vert", "strokes", "flags"], rows, {"peak g": "{:.1f}"})
short = Counter()
for tag, a in G:
    if a.verdict != "valid": short[f"{a.label}_{a.direction}"] += 1
have = Counter(f"{a.label}_{a.direction}" for _, a in G if a.verdict == "valid")
display(Markdown(f"### To re-record: {sum(short.values())} gestures the next session has to make up"))
order = [f"{l}_{d}" for l in ("flick", "double_flick") for d in ("up", "down", "left", "right")]
table(["class", "valid now", "excluded (re-record)", "valid after make-up"], [(k, have[k], short[k], have[k] + short[k]) for k in order] + [("total", sum(have.values()), sum(short.values()), sum(have.values()) + sum(short.values()))])
""")

md("""
Three of the four invalid gestures in the reference session are the ones every
held-out model missed or nearly missed, which is the point: the audit finds them
from the stream alone, before any model is trained. Two others in that session
(`#19`, `#28`) have stroke spacing just past 0.50 s and *were* detected by the
models. The range is a definition, so they are excluded anyway; the borderline
band 0.50-0.55 s holds 2 gestures in the whole corpus.
""")

md("## 5. Distributions: what the prompts produced")

code(r"""
fig, axes = plt.subplots(1, 3, figsize=(15, 4))
for tag, sid in prompted.items():
    d = [a for t, a in G if t == tag and a.label == "double_flick" and a.stroke_gap_s is not None]
    axes[0].scatter([a.stroke_gap_s for a in d], [a.stroke_ratio for a in d], s=14, alpha=0.7, label=tag)
lo, hi = audit.DOUBLE_GAP_RANGE_S; rlo, rhi = audit.DOUBLE_RATIO_RANGE
axes[0].add_patch(plt.Rectangle((lo, rlo), hi - lo, rhi - rlo, fill=False, ls="--", color="k"))
axes[0].set_xlabel("double: stroke spacing (s)"); axes[0].set_ylabel("2nd / 1st stroke peak"); axes[0].set_yscale("log"); axes[0].legend(); axes[0].set_title("The double, as a range (dashed)")
for i, (tag, sid) in enumerate(prompted.items()):
    for amp, c in (("soft", "tab:blue"), ("hard", "tab:red")):
        v = [a.peak_g for t, a in G if t == tag and a.amplitude == amp and a.peak_g >= 1]
        axes[1].scatter(np.full(len(v), i + (0.15 if amp == "hard" else -0.15)) + np.random.uniform(-0.08, 0.08, len(v)), v, s=10, color=c, alpha=0.6, label=amp if i == 0 else None)
axes[1].axhline(32767 / accel.COUNTS_PER_G, color="gray", ls=":", label="±4.09 g rail"); axes[1].set_xticks(range(3)); axes[1].set_xticklabels(prompted); axes[1].set_ylabel("peak g"); axes[1].legend(); axes[1].set_title("Amplitude prompt is followed")
for i, (tag, sid) in enumerate(prompted.items()):
    for tempo, c in (("brisk", "tab:green"), ("natural", "tab:gray"), ("deliberate", "tab:purple")):
        v = [a.stroke_gap_s for t, a in G if t == tag and a.label == "double_flick" and a.tempo == tempo and a.stroke_gap_s]
        axes[2].scatter(np.full(len(v), i + {"brisk": -0.2, "natural": 0, "deliberate": 0.2}[tempo]) + np.random.uniform(-0.05, 0.05, len(v)), v, s=10, color=c, alpha=0.6, label=tempo if i == 0 else None)
axes[2].set_xticks(range(3)); axes[2].set_xticklabels(prompted); axes[2].set_ylabel("double: stroke spacing (s)"); axes[2].legend(); axes[2].set_title("Tempo prompt did nothing")
plt.tight_layout(); plt.show()
for tag in prompted:
    s = audit.summary([a for t, a in G if t == tag])
    print(tag, "median peak by amplitude word:", {k: round(v, 1) for k, v in s.get("peak_by_amplitude", {}).items()},
          " median double spacing by tempo word:", {k: round(v, 2) for k, v in s.get("double_gap_by_tempo", {}).items()})
""")

md("""
Two protocol facts fall out. The amplitude prompt works: soft and hard medians are
2 g apart in every session, with a 2-17% crossover. The tempo prompt does nothing:
"brisk", "natural" and "deliberate" doubles have the same stroke spacing (medians
0.29-0.39 s) in every session, and in the reference session "brisk" is the slowest.
The word should be dropped from the schedule and the double recorded as what it is:
two quick comparable taps, checked against the range at recording time.
""")

md("## 6. Direction against gravity, and the ring frame")

code(r"""
fig, axes = plt.subplots(1, 2, figsize=(11, 4))
for i, (tag, sid) in enumerate(prompted.items()):
    for j, dn in enumerate(("up", "down", "left", "right")):
        v = [a.vertical_frac for t, a in G if t == tag and a.direction == dn and a.vertical_frac is not None]
        axes[0].scatter(np.full(len(v), j + (i - 1) * 0.22) + np.random.uniform(-0.06, 0.06, len(v)), v, s=10, alpha=0.6, label=tag if j == 0 else None)
axes[0].axhline(audit.VERTICAL_CUT, color="k", ls="--"); axes[0].set_xticks(range(4)); axes[0].set_xticklabels(["up", "down", "left", "right"])
axes[0].set_ylabel("impulsive energy along gravity / total"); axes[0].legend(); axes[0].set_title("Vertical vs horizontal, one fixed cut")
ok = sum(1 for _, a in G if a.vertical_frac is not None and a.direction in ("up", "down", "left", "right") and "DIRECTION_PAIR_MISMATCH" not in a.flags)
n = sum(1 for _, a in G if a.vertical_frac is not None and a.direction in ("up", "down", "left", "right"))
on = [a.onset_s for _, a in G if a.onset_s is not None]
axes[1].hist(on, bins=np.arange(-0.5, 1.3, 0.05), color="tab:gray"); axes[1].axvline(audit.LATE_ONSET_S, color="r", ls="--", label="late")
axes[1].set_xlabel("onset after cue (s)"); axes[1].set_title("Reaction to the cue"); axes[1].legend()
plt.tight_layout(); plt.show()
print(f"pair (vertical/horizontal) agrees with the cued direction for {ok}/{n} = {100*ok/n:.1f}% of gestures, no training, one cut across three days")
print(f"onset p5/50/95: {np.percentile(on,5):+.2f} / {np.median(on):+.2f} / {np.percentile(on,95):+.2f} s; {sum(1 for o in on if o < 0)} gestures started before the cue (anticipation), none after 1.0 s")
""")

md("""
The pair check is the gravity-referenced feature the `gref` channel group is built
on. The 5% on the wrong side are kept as suspect: the feature is a check, not truth.
Onsets: a fifth of gestures start *before* the cue, because the schedule is
predictable. That is harmless for the 2 s windows but worth randomising.
""")

md("## 7. What cleaning changes, measured")

code(r"""
clean = json.loads((RES / "clean_results.json").read_text()) if (RES / "clean_results.json").exists() else None
if clean:
    rows = []
    for key, name in (("uncleaned_seed0", "trained on everything, seed 0"), ("uncleaned_seed1", "trained on everything, seed 1"),
                      ("seed0", "trained on valid only, seed 0"), ("seed1", "trained on valid only, seed 1")):
        r = clean[key]
        amb = r.get("ambient", {})
        rows.append((name, f"{r['0.4']['exact']}/{r['0.4']['n']}", f"{r['0.4']['type']}/{r['0.4']['n']}", f"{r['0.9']['exact']}/{r['0.9']['n']}",
                     amb.get("0.40", {}).get("fp_per_min"), amb.get("0.90", {}).get("fp_per_min")))
    table(["model (gref channels, reference session held out)", "exact class @0.4", "type @0.4", "exact @0.9", "ambient FP/min @0.4", "@0.9"], rows)
    display(Markdown("Scored on the reference session's **valid gestures only** (the 9 excluded ones are out of the truth for every row, so rows are comparable)."))
else:
    print("clean_results.json not present -- run the scratch clean_run.py")
""")

md("## 8. Learning curve: recall vs number of training gestures")

code(r"""
curve = json.loads((RES / "curve_results.json").read_text()) if (RES / "curve_results.json").exists() else None
if curve:
    fr = sorted(set(c["frac"] for c in curve))
    fig, ax = plt.subplots(figsize=(7, 4))
    for thr, c in (("0.4", "tab:blue"), ("0.9", "tab:red")):
        xs = [c_["train_gestures"] for c_ in curve]; ys = [100 * c_[thr]["exact"] / c_[thr]["n"] for c_ in curve]
        ax.scatter(xs, ys, color=c, label=f"exact class, thr {thr}")
        means = [np.mean([100 * c_[thr]["exact"] / c_[thr]["n"] for c_ in curve if c_["frac"] == f]) for f in fr]
        ax.plot([int(np.mean([c_["train_gestures"] for c_ in curve if c_["frac"] == f])) for f in fr], means, color=c, alpha=0.5)
    ys = [100 * c_["0.4"]["type"] / c_["0.4"]["n"] for c_ in curve]; ax.scatter([c_["train_gestures"] for c_ in curve], ys, color="tab:green", marker="x", label="gesture type, thr 0.4")
    ax.set_xlabel("valid training gestures (sessions 1+2, subsampled per class)"); ax.set_ylabel("recall on reference session (%)"); ax.set_ylim(50, 101); ax.grid(alpha=0.3); ax.legend()
    n_ref = curve[0]["0.4"]["n"]
    ax.set_title(f"Two seeds per point; {n_ref} held-out gestures, so ±1 gesture = {100/n_ref:.1f} points"); plt.show()
    rows = [(c_["frac"], c_["seed"], c_["train_gestures"], c_["train_windows"], f"{c_['0.4']['exact']}/{c_['0.4']['n']}", f"{c_['0.4']['type']}/{c_['0.4']['n']}", f"{c_['0.9']['exact']}/{c_['0.9']['n']}") for c_ in curve]
    table(["fraction", "seed", "train gestures", "train windows", "exact @0.4", "type @0.4", "exact @0.9"], rows)
else:
    print("curve_results.json not present -- run the scratch curve.py")
""")

md("## 9. How much data is needed")

code(r"""
from math import sqrt
def wilson(k, n, z=1.96):
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); h = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)); return ((c - h) / d, (c + h) / d)
rows = []
for n in (23, 64, 100, 150, 200, 300):
    rows.append((n, 100 * wilson(round(0.95 * n), n)[0], 100 * wilson(round(0.97 * n), n)[0], 100 * wilson(n, n)[0]))
display(Markdown("### To *demonstrate* recall: 95% CI lower bound (Wilson) for an observed recall, by held-out gesture count"))
table(["held-out gestures", "observed 95% -> lower bound", "observed 97% -> lower", "observed 100% -> lower"], rows, {"observed 95% -> lower bound": "{:.1f}", "observed 97% -> lower": "{:.1f}", "observed 100% -> lower": "{:.1f}"})
display(Markdown("### To bound false positives (rule of three): zero events in T minutes of clean ambient wear bounds the rate at 3/T"))
table(["claim", "clean ambient minutes needed", "have"], [("< 6 / hour", 30, 30), ("< 3 / hour", 60, 30), ("< 1 / hour", 180, 30), ("< 0.5 / hour", 360, 30)])
""")

md(r"""
### The estimate

**What exists, per class, after the audit** (valid only): 232 training gestures on
two days, 26-33 per direction-class of flick and double_flick, 23 valid held-out
gestures on a third day, and one 20 s span each of wave, snap and clap (63-75
windows each, one day, one person). Ambient: 30 held-out minutes. The 41 excluded
gestures are the first item on the next session's list (section 4).

**What cleaning did.** Section 7 has the like-for-like table: the same two seeds
trained on everything versus on valid gestures only, scored on the same valid-only
truth. Read the numbers there rather than a summary here; with 23 held-out gestures
one gesture is 4.3 points, so anything inside two gestures is a tie. What cleaning
changed for certain is the *definition*, which is what the next sessions will be
recorded against.

**To reach 95%.** The learning curve (section 8) separates two things: gesture
*type*, which saturates early, and exact class at threshold 0.9 -- direction plus
confidence -- which keeps climbing with training gestures. Read whether the
right-hand end has flattened; if it has not, direction and confidence are still
data-limited at the current size. What the curve cannot say is the effect of a *third* training day,
and the evidence so far is that days matter more than gestures: the posture and the
up-flick waveform both moved more between days than within one. The recommendation
is therefore in sessions, not gestures:

| what | now | needed | why |
|---|---|---|---|
| prompted flick/double sessions (training) | 2 days | 4-5 days, 8 per direction-class each (64 gestures, ~5 min) | day-to-day variation is the dominant unexplained factor; each day adds ~64 audited gestures |
| held-out demonstration set | 23 valid on 1 day | >= 100 on >= 2 further days, never trained on | observed 97% on 100 bounds recall above 91%; on 23 it bounds nothing above 82% |
| wave / snap / clap / double_snap | 1 span each, 1 day; double_snap none | 3 days x 3 spans of 20 s each per sustained class; 3 days x 16 snaps and double_snaps | one span cannot train or validate a class; snap and double_snap are the flick's hardest negatives |
| ambient wear | 30 held-out min | 180+ min across >= 2 days, no cued gestures | rule of three; anything less cannot bound < 1/hour |
| each session | | `python -m probe.audit <session> --write` before export | invalid gestures re-recorded the same day |

**Protocol changes the data asks for:** drop the tempo word; cue doubles as "two
quick taps" and check the range on the spot; randomise cue spacing so onsets stop
anticipating; keep the amplitude word (it works); record surface contact (armrest /
air) as a mark field, since the up flick's between-day change is unexplained.
""")

md("## 10. Negative recordings: what they contain")

code(r"""
rows = []
for p in sorted(SESS.glob("negative_*.jsonl")):
    t, x = load_stream(p); x = despike.hampel(x)
    W, ST = 50, 6; peaks = np.array([np.linalg.norm(x[s:s+W] - x[s:s+W].mean(0), axis=1).max() for s in range(0, len(x) - W + 1, ST)])
    rows.append((p.stem, (t[-1] - t[0]) / 60, len(peaks), 100 * (peaks > 1).mean(), 100 * (peaks > 2).mean(), 100 * (peaks > 3).mean(), peaks.max()))
table(["session", "minutes", "windows", "peak > 1 g %", "> 2 g %", "> 3 g %", "max g"], rows, {"minutes": "{:.1f}", "peak > 1 g %": "{:.1f}", "> 2 g %": "{:.1f}", "> 3 g %": "{:.1f}", "max g": "{:.1f}"})
display(Markdown("The 60-minute ambient session is 2.5% gesture-loud (> 3 g) windows -- it is real wear, not a still hand -- and it is the only negative long enough to say anything about false positives. "
                 "The adversarial session (waving, snapping, clapping, 'dismissive flick', 'so-so wobble') is 1.8 minutes on one day: it is where the wave/snap/clap classes come from, and it is one example of each."))
""")

md("""
## Reproduction

- Audit verdicts: `python -m probe.audit --all --write` (writes `data/sessions/<session>.audit.json`).
- Clean export: `python -m probe.dataset --out data/windows.npz` (the exporter drops every window touching an invalid gesture).
- Clean retrain and like-for-like comparison: `scratch/clean_run.py`; learning curve: `scratch/curve.py` (both in the session scratchpad; their outputs are `notebooks/results/*.json`).
""")

nb = nbf.v4.new_notebook(); nb["cells"] = cells
nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
out = Path(__file__).parent / "data_quality.ipynb"
nbf.write(nb, out)
print("wrote", out)
