# M2 calibration corpus

The corpus of coding questions shown during labeling sessions (M3). Each item
exists to answer one question: **on one specific axis of model behavior, which
class does this coder actually want?** The ring gesture -- `flag`, `approve`, or
nothing -- is the label.

This document is to M2 what `docs/COLLECTION.md` is to M1: decide everything
here before running a session, because every choice is cheap now and expensive
after four sessions of labels are in the bag.

**This document covers layer 1 only** -- what a single response looks like.
How the model *works with you* across a run (autonomy, narration, when it
stops, whether it proves its work) is layer 2: see `docs/AGENCY.md`. Layer 2
shares this document's presentation model, session protocol, confound
discipline and tooling, and adds situation-conditioned items so a preference
comes out as a policy rather than a constant.

---

## Why curated contrasts, not mined repo data

The original plan was to pull interaction history from the FDD pipeline and
AsyncWorld repos. **Replaced 2026-09-15** with a curated contrastive corpus, for
four reasons:

- **Credit assignment.** A mined response differs from its alternatives on many
  axes at once, and there is no counterfactual to compare against. A flag on a
  real interaction says "something here was wrong" without saying *which*
  property -- unsolvable at calibration volume. A contrast pair that differs on
  exactly one axis makes the gesture identify the axis by construction.
- **Correctness confounds taste.** Most real dislikes are bugs. A reward model
  trained on mined flags learns "the coder dislikes bugs", which a context file
  states in one line -- leaving no weights-vs-context gap to measure. Calibration
  items hold correctness equal so the label carries taste only.
- **Coverage.** Mined data covers dimensions in proportion to how often they
  occurred, not how much they matter. Rare axes get no labels at all -- the same
  lesson as the 2% of loud negatives in `whip/sampling.py`: what the objective
  never sees, it cannot learn.
- **Comparability across arms.** M6 compares preferences-in-weights against
  preferences-in-context. Both arms must derive from the *same* measurement, or
  the comparison measures the corpus difference instead of the mechanism.

Naturalistic labels from live wear are still wanted -- they are Phase B, exactly
as M1 splits prompted blocks (volume) from naturalistic blocks (honesty).
Calibration establishes the classes first; live wear then supplies volume that
can be interpreted.

---

## Presentation model

A presentation is **one prompt plus one complete model response**, read on
screen, answered with one gesture:

| Gesture | Label |
|---|---|
| single flick | `flag` -- I dislike this behavior |
| double flick | `approve` -- I want this behavior |
| nothing | `none` -- no reaction either way |

**The keyboard is the primary label source; the ring is secondary.** That is
measured, not provisional: on held-out data the gesture model recalls ~58% of
flicks (95% CI 45-69), so a presenter that waited on the ring would stall on
four slots in ten. `python -m probe.label run` takes `f` / `a` / Enter per
slot and appends a record immediately (crash-safe, resumable). It never shows
the dimension or pole -- see "dimension blocking" below.

The ring is joined afterwards, offline, from the gesture platform's event log
(`python -m probe.label join`). The contract, from that platform:

| Rule | Why |
|---|---|
| join on `wall` (epoch seconds), never `t_s` | `t_s` is the engine's stream clock; not comparable across processes |
| use `action`, not the gesture name | `data/app_config.json` maps flick->flag, double_flick->approve; snap/wave/clap carry `action: null`. Every ambient false positive observed so far was unmapped, so filtering on action keeps them out |
| direction is recorded, never routed on | it is available and 93-96% accurate, and mapping keys may be direction-qualified, but the label vocabulary is three states -- two gestures plus silence already cover it, so a qualifier would only add a second way for a ring label to be wrong. Stored per record so the direction *habit* per action is observable; it cannot be scored here, as the labeler is never asked for a direction |
| window = [shown, key label + 2.0 s] | measured gesture-end-to-event latency is ~1.3 s |
| a slot with no mapped event is `missing`, never skipped | the missed count *is* the recall number |

Each label record carries `source` (`key` or `ring`) and, once joined, the
ring's `wall`, `confidence`, and status (`ok` / `missing` / `ambiguous`), so
**ring-vs-key agreement is computed per session** as an acceptance check --
broken down as matched / mismatched / missed on gesture slots and silent /
spurious on none slots, so recall and false positives stay separate numbers.
Once the ring's recall clears ~90% it can become primary; the presenter then
needs an explicit no-gesture-arrived path (re-prompt, then key), never a
silent skip.

Pairing exists only in analysis. The two variants of an item are shown as two
separate ordinary presentations, never side by side, at least 4 slots apart --
because deployment is single-response and labels collected comparatively do not
transfer to it. `none` is a first-class outcome, not a skip: a reward model that
never sees indifference invents a preference on every axis.

**Pair reading**, with `approve` = +1, `none` = 0, `flag` = -1, preference =
score(a) − score(b), range [-2, +2]:

| a, b | Reading |
|---|---|
| approve, flag | strong preference for a's pole |
| approve, none / none, flag | weak preference for a's pole |
| none, none | indifferent -- real signal, train the RM flat here |
| approve, approve | both acceptable -- indifferent-positive |
| flag, flag | item defective or axis mis-posed; route to review, **not** training |

---

## The taxonomy

Twelve dimensions, each a binary choice between two defensible poles. Machine
readable in `corpus/taxonomy.json`, which also carries a one-sentence
`context_statement` per pole -- the exact text that enters the context-file arm
if that pole wins calibration.

| Dimension | Pole A | Pole B |
|---|---|---|
| `scope` | minimal -- touch only what was asked | opportunistic -- clean up adjacent code while there |
| `verbosity` | terse -- answer, then stop | explanatory -- teach the why alongside |
| `comments` | sparse -- constraints only | narrated -- comment each step |
| `abstraction` | concrete -- inline, direct | generalized -- helpers, patterns, extensibility |
| `defensiveness` | trusting -- happy path, let it crash | defensive -- validate inputs, handle errors |
| `dependencies` | handroll -- stdlib and own code | library -- pull the established package |
| `initiative` | ask-first on ambiguity | act-first with stated assumptions |
| `proactivity` | exact -- do the ask, stop | collateral -- add tests/docs/types unasked |
| `idiom` | conform -- match surrounding style | modernize -- impose current best practice |
| `hedging` | committed -- plain claims from evidence | cautious -- caveats and qualifiers |
| `cleverness` | explicit -- plain imperative code | dense -- idiomatic one-liners |
| `testing` | focused -- few representative cases | exhaustive -- parameterized edge-case suites |

These are classes, not scores. Calibration decides, per dimension: pole A,
pole B, or *indifferent*. A dimension where more than ~60% of pairs read
indifferent is **dropped from the context file and trained flat in the RM** --
do not bake in a preference that was never expressed. (The M1 analog: a model
cannot reject what it has never seen; here, a preference file must not assert
what was never felt.)

---

## Item design rules

Every item must survive all five, and the validator enforces what it can:

1. **One axis.** The two variants differ on the item's dimension and nothing
   else the labeler could plausibly react to.
2. **Both defensible.** No strawmen. If a competent engineer would never write
   variant B, a flag on B is a correctness judgment, not a taste measurement.
3. **Correctness held equal.** Both variants work. Both would pass the same
   tests. Review this before the session; a bug found after labeling voids the
   item's labels.
4. **Readable in under 40 seconds.** Prompt plus response fits on one screen,
   responses ≤ ~25 lines. Fatigue is a measurement error, not a stamina test.
5. **Grounded.** Tasks come from this coder's actual world -- Python tooling,
   C++ daemons, ML training, firmware, backends, scripts -- not puzzle-bank
   abstractions.

## Confounds

| Confound | How it bites | Fix |
|---|---|---|
| Correctness leak | one variant subtly buggy; label measures bugs, not taste | both variants reviewed correct before any session |
| Length leak | the pole is guessable from response length alone | balance which pole is longer across items within each dimension; validator flags a dimension whose longer-pole is constant. Exempt: dimensions marked `length_constitutive` in the taxonomy (verbosity, comments, testing, scope, proactivity, abstraction, defensiveness), where the poles differ in length *by definition* -- reacting to length there is reacting to the axis. For the rest (cleverness, dependencies, idiom, initiative, hedging) the balance is enforceable and required -- e.g. the dense `cleverness` variant should usually be the *shorter* one |
| Order / anchoring | second member of a pair judged relative to the first | members ≥ 4 slots apart; which pole shows first is balanced exactly 50/50 per session |
| Dimension blocking | consecutive same-axis items teach the labeler the axis; they start answering the *policy* question instead of reacting | round-robin dimensions; no two same-dimension pairs adjacent |
| Domain leak | a dimension always arrives in one language/domain | cross domains within every dimension |
| Fatigue drift | reactions at minute 55 differ from minute 5 | sentinel items repeated early and late; gate on agreement |
| Single-sitting oracle | one session measures that day's mood, not a preference | 4+ sessions on different days; a pole "wins" only if consistent across sessions |
| Demand effect | knowing it is a preference study inflates reactions | `none` is legitimate and expected; indifference rate is reported per dimension, not treated as failure |

The session-oracle and blocking rules are the same discipline as M1's
"interleave classes within every session" and "split by session, never by
window" -- same failure modes, different substrate.

---

## Sizing

One presentation ≈ 30-40 s to read and react. A one-hour session at ~85%
utilization holds ~85-90 presentations:

- **40 pairs** = 80 presentations
- **2 sentinels** repeated early and late = 4 more

So a session covers 40 pairs ≈ 3-4 items per dimension. Four sessions across
different days ≈ **160 pair-labels, ~13 per dimension** -- enough to call a
direction per dimension (10-of-13 one way excludes chance at 95%), and 320+
single-presentation labels for reward-model training on top of that.

Corpus: **60 gold items, 5 per dimension**, in `corpus/gold/`. Four 40-pair
sessions draw 160 pair-slots from those 60 items, so each item appears ~2-3
times across the campaign. That repetition is deliberate, not a shortage: the
cross-session gate requires test-retest agreement on repeated items, which
only repeats can supply. Within a single session no item appears twice except
sentinels.

Growing the corpus further (new `-06`, `-07`... items per dimension) is always
allowed and never blocks a session: write the item following any same-dimension
exemplar, run `python -m probe.calibrate validate`, and have both variants
reviewed for rule 3 (correctness held equal) before first use.

---

## Session protocol

1. `python -m probe.calibrate plan --session N --pairs 40 --seed <fixed>` emits
   the presentation order. The seed is fixed per session and recorded; the plan
   is deterministic and reproducible.
2. Sessions on **different days**. Ring worn, gestures as labels; keyboard
   fallback keys record through the same pipeline with a `source` tag so ring
   and keypress labels can be compared later.
3. No discussion of the taxonomy during a session. React, don't deliberate --
   the deliberated answer is the policy question, and it is exactly what the
   context-file arm already gets to have.
4. Log anything unusual in session notes, as with M1.

### Per-session acceptance checks

- **Sentinel agreement ≥ 80%** (same stimulus early vs late). Below that, the
  back half of the session is fatigue noise; keep the front half only.
- **Reaction coverage** -- a session that is >85% `none` measured boredom, not
  indifference; review item difficulty before blaming the coder.
- **First-shown balance** actually 50/50 in the emitted plan (the sampler
  enforces it; verify in the artifact).
- **Every dimension present** -- 40 pairs must cover all 12 dimensions.

`python -m probe.label score` computes all of these from the label file and
exits 2 on a rejected session.

### Cross-session gate (the M2 exit criterion)

- Per dimension: direction consistent across sessions, or declared indifferent.
  No dimension left "contested" -- a contested dimension means the items
  disagree with each other, which is an item defect to fix, not a preference.
- Test-retest on repeated items across days ≥ 70%.
- Output artifact: `data/calibration/preferences.json` from
  `python -m probe.label aggregate` -- per dimension, the winning pole,
  `indifferent`, `contested`, or `unmeasured`, with margin and per-session
  vote counts, plus the ready-to-use `context_file` statements ordered by
  margin. A pole wins only if it holds the majority overall *and* in every
  session where the dimension had two or more decided pairs; a dimension a
  later session flips is `contested` and goes back to item review.

---

## Feeding M4-M6

- **M4 reward model** trains on (prompt, response, label) and pairwise
  (prompt, response_a, response_b, preference). Split by **item**, never by
  presentation -- the two showings of one variant, and the two variants of one
  item, stay on the same side of the split (the M1 window-overlap leak, exactly).
  Hold out one full session (day) as well.
- **M5 LoRA** trains against the M4 reward model.
- **M6 context arm** is generated mechanically: for each non-indifferent
  dimension, the winning pole's `context_statement` from `corpus/taxonomy.json`
  goes into the preferences file, ordered by margin. Both arms thereby derive
  from the same measurement, and the three-arm eval (baseline / context /
  weights) compares mechanisms, not corpora.
