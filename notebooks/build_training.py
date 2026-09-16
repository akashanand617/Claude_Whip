"""
Builds notebooks/training.ipynb -- the whole training pipeline in one place,
plain enough to change and re-run: load the audited export, make a gesture
table, split it with scikit-learn, train the CNN in a few dozen lines of
PyTorch, score it the way the live engine fires events, save a checkpoint.

    python notebooks/build_training.py          # writes and executes the notebook
"""
from pathlib import Path
import nbformat as nbf

cells = []
md = lambda s: cells.append(nbf.v4.new_markdown_cell(s.strip()))
code = lambda s: cells.append(nbf.v4.new_code_cell(s.strip()))

md(r"""
# Whip gesture model: training, end to end

Everything needed to train and test the gesture classifier, in one notebook,
using the project's library for the parts that must match the live engine
(channels, augmentation, event detection) and plain scikit-learn / PyTorch for
the parts you will want to change (the split, the training loop, the metrics).

**Inputs.** `data/windows.npz` -- the audited export (`scripts/rerun.sh` or
`python -m probe.dataset --out data/windows.npz` after `python -m probe.audit --all --write`).
Every window is 2 s at 25 Hz, gravity removed, plus its gravity vector, label,
session and start time. Only audit-valid gestures are labelled.

**The one rule that is not negotiable:** windows overlap 88%, so a split is made
over *gestures*, never over windows, and a window that would straddle two parts
is dropped. `whip.split` does that bookkeeping; you choose the assignment.

Sections: 1 load · 2 gesture table · 3 split (sklearn) · 4 channels · 5 train ·
6 score · 7 threshold sweep · 8 sklearn baseline · 9 save checkpoint.

*Environment note:* in the conda base env, importing scikit-learn pulls in
pandas, whose compiled helpers (`numexpr`, `bottleneck`) were built against
NumPy 1.x and print a long notice. It is harmless and everything runs;
`pip install -U numexpr bottleneck` in that env makes it go away.
""")

code(r"""
import sys, json, time, math
from pathlib import Path
from collections import Counter, defaultdict
import numpy as np
import torch, torch.nn as nn
ROOT = Path.cwd() if (Path.cwd() / "whip").exists() else Path.cwd().parent
sys.path.insert(0, str(ROOT))
from whip import split as sp, evaluate, events, dataset
from whip import model as gm
from whip.registry import load_registry
R = load_registry()
SESS = ROOT / "data" / "sessions"
d = np.load(ROOT / "data" / "windows.npz", allow_pickle=True)
dataset.check_format_version(d)
X, y, GRAV, SESSION, START = d["X"], d["y"], d["gravity"], d["session"], d["start_s"]
LABELS = [str(s) for s in d["labels"]]
print(f"{len(X)} windows, {len(LABELS)} classes: {LABELS}")
print("windows per class:", dict(Counter(np.array(LABELS)[y].tolist())))
""")

md("## 2. The gesture table\nOne row per audit-valid cued gesture: where it is and what it is. This is what gets split.")

code(r"""
spans = {s: (float(START[SESSION == s].min()), float(START[SESSION == s].max()) + 2.0) for s in set(SESSION.tolist())}
units = sp.gesture_units(SESS, spans.keys(), R)          # (session, cue_at, class)
posture = {}
for s in spans:
    p = SESS / f"{s}.notes.json"
    if p.exists():
        for m in json.loads(p.read_text()).get("marks", []):
            if "until" not in m: posture[(s, round(m["cue_at"], 3))] = m.get("posture", "as you are")
table = [{"session": s, "cue_at": c, "cls": k, "posture": posture.get((s, round(c, 3)), "?")} for s, c, k in units]
print(len(table), "gestures")
print("per class:", dict(sorted(Counter(r["cls"] for r in table).items())))
print("per session:", dict(sorted(Counter(r["session"] for r in table).items())))
""")

md(r"""
## 3. Split with scikit-learn

`train_test_split` over the gesture table, stratified by class, seeded. Then
`whip.split.resolve` turns the assignment into time intervals per session
(gesture intervals meet midway between cues; the non-gesture timeline is dealt
in 20 s chunks; the wave span likewise) and `part_of_window` maps every window
to a part or drops it at a boundary. Change `SEED` or the fractions and re-run;
`STRATIFY_BY = "cls"` keeps the class mix equal across parts.
""")

code(r"""
import contextlib, io
with contextlib.redirect_stderr(io.StringIO()):      # a compiled optional dependency in this env prints a NumPy-2 notice on import; harmless
    from sklearn.model_selection import train_test_split
SEED = 0
TEST, VAL = 0.20, 0.15                     # of all gestures
idx = np.arange(len(table)); strat = [r["cls"] for r in table]
tr_idx, te_idx = train_test_split(idx, test_size=TEST, random_state=SEED, stratify=strat)
tr_idx, va_idx = train_test_split(tr_idx, test_size=VAL / (1 - TEST), random_state=SEED, stratify=[strat[i] for i in tr_idx])
assignment = {}
for part, ids in (("train", tr_idx), ("val", va_idx), ("test", te_idx)):
    for i in ids: assignment[(table[i]["session"], table[i]["cue_at"])] = part
plan = sp.resolve(sp.Plan(seed=SEED, fractions=[1 - TEST - VAL, VAL, TEST], chunk_s=20.0), SESS, spans, R, assignment=assignment)
part = np.array([sp.part_of_window(plan, s, float(t)) or "" for s, t in zip(SESSION, START)])
print("windows per part:", dict(Counter(part.tolist())), "('' = dropped at a boundary)")
cnt = defaultdict(Counter)
for i in idx: cnt[table[i]["cls"]][assignment[(table[i]["session"], table[i]["cue_at"])]] += 1
print(f"{'class':20s} train  val test")
for k in [l for l in LABELS if l in cnt]: print(f"{k:20s} {cnt[k]['train']:5d} {cnt[k]['val']:4d} {cnt[k]['test']:4d}")
""")

md(r"""
## 4. Channels

`gm.to_model_input` derives the model's input from a raw window and its gravity
vector. The default set: three unit-amplitude waveform channels, log peak
amplitude, the clipped fraction, and the three **room-frame** channels
(impulsive motion along gravity, along gravity x finger, forward) -- the ones
that make direction a room direction in any hand posture.
""")

code(r"""
CHANNELS = ("shape", "scale", "saturation", "room")
def features(sel):
    return gm.to_model_input(X[sel], CHANNELS, gravity=GRAV[sel]).astype("float32")
print("input shape per window:", features(np.arange(2)).shape[1:], "=", gm.n_channels_for(CHANNELS), "channels x 50 samples")
""")

md(r"""
## 5. Train

The training loop, in full. Per batch: a random spin of the ring frame about
the finger (windows and gravity together), then the channels, then the usual
amplitude/noise augmentation. Class-weighted cross-entropy because `none` is
most of the data. Fixed seed. `EPOCHS = 60` matches `probe.train`; drop it to
20 for a quick look.
""")

code(r"""
def train_model(train_sel, seed=0, epochs=60, batch=128, lr=3e-3, weight_decay=1e-3, spin_deg=180.0, log_every=10):
    torch.manual_seed(seed); np.random.seed(seed); rng = np.random.default_rng(seed)
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    Xtr, Gtr, ytr = X[train_sel], GRAV[train_sel], y[train_sel]
    counts = np.bincount(ytr, minlength=len(LABELS))
    weights = torch.tensor(len(ytr) / (len(LABELS) * np.maximum(counts, 1)), dtype=torch.float32, device=device)
    net = gm.GestureNet(n_channels=gm.n_channels_for(CHANNELS), n_classes=len(LABELS)).to(device)
    opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=weight_decay)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)
    loss_fn = nn.CrossEntropyLoss(weight=weights)
    yt = torch.tensor(ytr, device=device)
    t0 = time.time()
    for epoch in range(epochs):
        net.train(); perm = np.random.permutation(len(ytr)); total = 0.0
        for i in range(0, len(perm), batch):
            ii = perm[i:i + batch]
            frames = gm.random_frames(len(ii), rng, flips=False, spin_deg=spin_deg)      # spin about the finger, never front-to-back
            xr, gr = gm.rotate_frame(Xtr[ii], Gtr[ii], frames)
            xb = torch.tensor(gm.to_model_input(xr, CHANNELS, gravity=gr), device=device)
            xb = gm.augment(xb, rotation_deg=0.0)                                          # amplitude + noise; spin already applied
            opt.zero_grad(); loss = loss_fn(net(xb), yt[ii]); loss.backward(); opt.step(); total += float(loss) * len(ii)
        sched.step()
        if (epoch + 1) % log_every == 0: print(f"  epoch {epoch + 1:3d}  loss {total / len(ytr):.4f}  {time.time() - t0:.0f}s")
    net.eval(); return net.cpu()

model = train_model(part == "train", seed=SEED, epochs=60)
""")

md(r"""
## 6. Score, the way the live engine fires

Per window: softmax, then a class call only if the winning gesture's
probability clears the threshold. Per session: consecutive same-class windows
form a run; a run of 3-14 windows is one event (the incremental `RunTracker`
that the live engine also uses, and it ends a run at any hole in the stream).
An event within 0.75 s of a cued gesture, with the right class, is a hit.
Ambient: events in the part's negative chunks, per hour of those chunks.
""")

code(r"""
def score(model, part_name, threshold=0.7, verbose=True):
    cn = R.collapsed_names(LABELS)
    per = defaultdict(lambda: [0, 0, 0]); conf = Counter(); fp_min = 0.0; fp = Counter()
    truth_by = defaultdict(list)
    for r in table:
        if assignment[(r["session"], r["cue_at"])] == part_name: truth_by[r["session"]].append((r["cue_at"] + 0.6, r["cls"]))
    for s in sorted(spans):
        sel = (SESSION == s) & (part == part_name)
        if not sel.any(): continue
        order = np.where(sel)[0][np.argsort(START[sel])]; starts = START[order]
        with torch.no_grad(): probs = torch.softmax(model(torch.tensor(features(order))), 1).numpy()
        ev = events.detect(evaluate.labels_at(probs, LABELS, threshold), starts.tolist(), policies=R.policies(LABELS))
        truth = truth_by.get(s, [])
        if not truth:
            if not s.startswith("prompted_"):
                fp_min += len(starts) * events.STRIDE_S / 60
                for e in ev: fp[R.collapse(e.label)[0]] += 1
            continue
        hx = evaluate.gesture_hits(ev, truth)
        evc = events.detect(evaluate.labels_at(R.collapse_probabilities(probs, LABELS), cn, threshold), starts.tolist(), policies=R.policies(cn))
        ht = evaluate.gesture_hits(evc, [(t, R.collapse(k)[0]) for t, k in truth])
        for (t, k), a, b in zip(truth, hx, ht):
            per[k][0] += 1; per[k][1] += a; per[k][2] += b
            if not a:
                fired = [e.label for e in ev if abs(e.centre_s - t) <= 0.75]; conf[(k, fired[0] if fired else "-")] += 1
    n = sum(v[0] for v in per.values()); ex = sum(v[1] for v in per.values()); ty = sum(v[2] for v in per.values())
    fph = 60 * sum(fp.values()) / fp_min if fp_min else float("nan")
    if verbose:
        print(f"{part_name} @ thr {threshold}: exact {ex}/{n} ({100*ex/n:.1f}%)  type {ty}/{n}  ambient {sum(fp.values())} events in {fp_min:.1f} min = {fph:.1f}/h {dict(fp)}")
        for k in [l for l in LABELS if l in per]: v = per[k]; print(f"   {k:20s} n={v[0]:3d}  exact {v[1]:3d}  type {v[2]:3d}")
        print("   misses (truth -> fired):", dict(conf))
    return ex, n, fph

_ = score(model, "val", 0.7)
""")

md("## 7. Threshold sweep on val, then one look at test\nChoose the threshold on val. Score test once, at that threshold, and do not go back and forth.")

code(r"""
print("val:")
for thr in (0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
    ex, n, fph = score(model, "val", thr, verbose=False); print(f"  thr {thr}: exact {ex}/{n} ({100*ex/n:.1f}%)  ambient {fph:.1f}/h")
THRESHOLD = 0.7
print("\ntest, once:")
_ = score(model, "test", THRESHOLD)
""")

md(r"""
## 8. A scikit-learn baseline on hand features

Not the model -- a sanity check on the representation. Per window: peak
amplitude, the room-frame energy fractions, the first-stroke signs, stroke
count and spacing. If a random forest on these gets direction right, the
information is in the frame, not in the network.
""")

code(r"""
with contextlib.redirect_stderr(io.StringIO()):
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import classification_report
from whip.model import _moving_average, GRAVITY_WINDOW, FINGER_AXIS
def hand_features(sel):
    out = []
    for i in sel:
        x = X[i]; g = GRAV[i] / max(np.linalg.norm(GRAV[i]), 1e-6); f = np.zeros(3); f[FINGER_AXIS] = 1
        l = np.cross(g, f); l = l / max(np.linalg.norm(l), 1e-6); fw = np.cross(l, g)
        lin = x - _moving_average(x, GRAVITY_WINDOW); mag = np.linalg.norm(lin, axis=0)
        v, h, w = g @ lin, l @ lin, fw @ lin; E = max((lin ** 2).sum(), 1e-9)
        above = np.where(mag > 1.0)[0]; k0 = above[0] if len(above) else 0
        peaks = [k for k in range(1, 49) if mag[k] > 1.0 and mag[k] >= mag[k - 1] and mag[k] > mag[k + 1]]
        out.append([mag.max(), (v ** 2).sum() / E, (h ** 2).sum() / E, (w ** 2).sum() / E,
                    v[k0:k0 + 5].sum(), h[k0:k0 + 5].sum(), w[k0:k0 + 5].sum(), len(peaks),
                    (peaks[1] - peaks[0]) / 25 if len(peaks) > 1 else 0.0, (mag > 1.0).sum() / 25])
    return np.array(out)
gest = y != 0
tr = np.where((part == "train") & gest)[0]; te = np.where((part == "test") & gest)[0]
rf = RandomForestClassifier(n_estimators=300, random_state=SEED).fit(hand_features(tr), y[tr])
pred = rf.predict(hand_features(te))
print("window-level, gesture windows only, test part:")
print(classification_report(y[te], pred, labels=sorted(set(y[te])), target_names=[LABELS[k] for k in sorted(set(y[te]))], zero_division=0))
""")

md("## 9. Save a checkpoint the live engine can load\nSelf-describing: labels, channels, what it trained on. `python -m probe.serve` and `probe.live` read the vocabulary from it.")

code(r"""
out = ROOT / "data" / "work" / "notebook_model.pt"
gm.save(model, out, trained_on=sorted({r['session'] for r in table if assignment[(r['session'], r['cue_at'])] == 'train'}),
        held_out=sorted({r['session'] for r in table if assignment[(r['session'], r['cue_at'])] == 'test'}),
        labels=LABELS, channels=CHANNELS, direction_trained=False)
print("saved", out, "-- copy to data/model.pt to deploy, or train on train+val first:")
print("   model_all = train_model(np.isin(part, ['train', 'val']), seed=SEED)")
""")

nb = nbf.v4.new_notebook(); nb["cells"] = cells
nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
out = Path(__file__).parent / "training.ipynb"
nbf.write(nb, out)
print("wrote", out)
