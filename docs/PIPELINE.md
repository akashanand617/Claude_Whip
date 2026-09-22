# M4-M6: reward model, adapter, three-arm eval

Architecture decided before any of it is built, so the three milestones are
designed against each other rather than discovered in sequence. Nothing here
is measured yet; every number is a budget or a threshold to be met, and each
section ends with what would falsify its design.

The chain: `preferences.json` (M3) -> pole classifier + preference weights
(M4) -> DPO/GRPO LoRA (M5) -> adherence-vs-context-fill curves for three arms
(M6). The corpus gives every stage its supervision, and both eval arms derive
from the same measurement, so M6 compares mechanisms, not corpora.

---

## Inputs, fixed by M2/M3

| Artifact | Shape | Volume after 4 sessions |
|---|---|---|
| per-presentation labels | `(prompt, response, label in {flag, none, approve}, source)` | ~320 |
| pair preferences | `(prompt, response_a, response_b, preference in [-2, 2])` | ~160, ~13 per dimension |
| `preferences.json` | per dimension: winning pole / indifferent / contested, margin | 12 rows |
| corpus itself | 60 items x 2 variants, **each variant labeled with its pole by construction** | 120 pole-labeled responses |

The last row is the one that makes M4 tractable. A generic reward model
trained on 160 pairs is thin. But the corpus already says which pole every
variant exhibits -- that is a free supervised signal, 120 examples across 12
binary tasks, that needs no labeling session at all. Calibration only has to
supply *which pole the coder wants*, ~13 labels per dimension, which four
sessions provide.

---

## M4: a factored reward model

**Reward = pole classifier x preference weights**, not a monolithic scalar
head.

```
r(prompt, response) = sum over dimensions d of  w_d * s_d(prompt) * (2 * p_d(response) - 1)

  p_d      pole classifier: P(response exhibits pole A of dimension d | prompt)
  s_d(.)   +1 if the coder's winning pole is A, -1 if B, 0 if indifferent/contested
  w_d      margin from preferences.json (0 for indifferent -> the RM is flat there by construction)
```

**The direction term is a function of the prompt, not a constant.** That is the
agency layer's consequence (`docs/AGENCY.md`): a preference that flips with the
situation -- large autonomous steps when the work is undoable, small ones when
it is not -- cannot be scored by a fixed sign. For a dimension that
`preferences.json` marks `conditional`, `s_d` reads the situation off the
prompt and returns the sign for that level.

That needs a second classifier, over **prompts** rather than responses: given a
task, which level of each situation factor is it? Five binary factors, and the
corpus supplies free supervision for them exactly as it does for poles -- every
item is authored with its situation levels recorded in frontmatter. The same
LLM-judge-first approach applies, held to the same >= 90% bar, and a factor
below it forces every dimension conditioned on it back to its unconditional
default rather than guessing.

The factored form is what makes this tractable: a monolithic scalar head would
have to learn the interaction from the handful of pairs that straddle it.

**Why factored.** Three reasons, each a lesson from M1:

- *Credit assignment survives.* A monolithic RM trained on 160 pairs learns a
  blend of the 12 axes it cannot separate. The factored form keeps each axis
  a separate, inspectable number -- a response can be scored per dimension,
  and a wrong reward is attributable to a wrong pole call or a wrong weight.
- *Indifference is structural, not learned.* "Train the RM flat on
  indifferent dimensions" becomes `w_d = 0`, guaranteed, instead of hoping a
  scalar head learns to ignore an axis from a handful of `none, none` pairs.
- *Supervision comes from construction.* The pole classifiers train on the
  corpus's own variant labels (120 examples), held out **by item**: both
  variants of an item stay on the same side of the split, or the classifier
  learns the item's prompt rather than the pole (the M1 window-overlap leak).

**Pole classifier implementation, in order of preference:**

1. **LLM-judge with the taxonomy's `question` and pole `summary` text** as the
   rubric -- zero training, and its accuracy on the 120 held-out-by-item
   variants is measured before use. Threshold: >= 90% per dimension. A
   dimension below that is not scorable and the RM is flat there until it is.
2. If a dimension fails the judge: a small trained head (embeddings + logistic
   regression, or a LoRA'd classifier on the base model) on the same 120
   examples, same by-item holdout.

**Baseline to beat: Bradley-Terry.** Base model + linear value head on the
last token, LoRA, pairwise loss on the ~160 pairs with `|preference|` as the
margin, `preference = 0` pairs dropped. Reported side by side with the
factored RM on held-out pairs (by item, and one held-out session-day). The
factored RM is the design; BT is the check that factoring did not throw away
signal. If BT wins on held-out pairwise accuracy by more than its bootstrap
interval, the factoring assumption -- that taste decomposes along the 12
axes -- is wrong and the taxonomy needs revisiting, not the RM.

**Validation gates.** Pairwise accuracy on held-out pairs (both RMs); per
dimension pole-classifier accuracy; the RM's score on the two variants of a
held-out item must order them in the direction of `preferences.json` for
every non-indifferent dimension. Report bootstrap CIs (`whip/evaluate.py`'s
rules apply: calibrate on data you do not report on, both variances).

**Falsifier.** Factored RM pairwise accuracy at chance on held-out items while
BT is above chance -> the axes are not separable in the base model's eyes and
the corpus contrasts are being read as something other than their dimension.

---

## M5: the adapter

**Base model:** the locally served coding model the daemon already targets --
an open-weights instruct coder in the 7-14B class, served by llama.cpp or
vLLM. Fixed for all three arms of M6; its hash goes in every adapter's
metadata.

**Two stages, the second optional and measured against the first:**

1. **DPO on the calibration pairs**, offline. Chosen/rejected from
   `preference` sign, `preference = 0` pairs dropped, `|preference| = 2` pairs
   weighted double. LoRA rank 16 on attention + MLP projections, 2-4 epochs, a
   KL-anchored beta chosen by held-out pairwise win-rate under the M4 RM --
   not by the DPO loss, which is not the quantity of interest.
   Also run **KTO** on the ~320 single-presentation labels (desirable =
   approve, undesirable = flag, `none` dropped) as an ablation: it uses
   labels DPO cannot, and if it matches DPO the paired design was not
   load-bearing for training (it remains load-bearing for *measurement*).
2. **GRPO with the factored RM** on a broader prompt pool -- coding tasks from
   this repo's own history and generic prompts per dimension, never the eval
   prompts. This is where the RM earns its keep: DPO can only reinforce the
   60 corpus contrasts, GRPO can shape behavior on prompts the corpus never
   contained. Gate: held-out pairwise win-rate must not fall from stage 1,
   and correctness (see M6) must not degrade.

**Over-optimization guards.** A KL budget against the base; RM score on a
fixed held-out prompt set checked every N steps for the reward-hacking
signature (score rising while the pole classifiers' *agreement with a human
spot-check* falls); a functional-correctness canary (a small set of prompts
with executable tests) that must stay at the base model's pass rate.

**Adapter metadata, self-describing like M1 checkpoints:** base model hash,
corpus version, `preferences.json` hash, training stage, config, held-out
win-rate. A consumer must be able to tell which preferences an adapter
encodes without asking.

**Falsifier.** Stage-1 DPO fails to move held-out win-rate above the base
model's by more than the bootstrap interval -> 160 pairs are too few to move
a 7B model through LoRA, and the honest next step is more sessions or
Phase B naturalistic labels, not a bigger adapter.

---

## M6: three arms against context fill

**Arms, same base model, same decoding, same prompts:**

| Arm | Preference carrier |
|---|---|
| A base | none |
| B context | preferences file in the system prompt, generated **mechanically** from `preferences.json`'s `context_file` list (winning poles' `context_statement`s, ordered by margin). No hand-editing -- a tuned prompt would measure prompt engineering |
| C weights | the M5 adapter, no preferences file |

**Independent variable: context fill.** Neutral filler is prepended between
the system prompt and the task at 0, 8k, 32k, 64k, and the largest level the
base model's window allows. Filler is drawn from a fixed, published source
that is *style-neutral with respect to the 12 axes* (documentation prose and
data tables, not code -- code exhibiting a pole primes the model toward that
pole and contaminates the arm comparison). The preferences file sits at the
top so fill pushes it away from the generation point, which is the realistic
failure mode being tested.

**Prompts.** Held-out corpus items (never in DPO/GRPO training) plus fresh
prompts per dimension written to the same rules, so adherence is scored on
prompts the adapter has not seen. Several samples per prompt at fixed
temperature; results reported per dimension and pooled.

**Metrics, in order of authority:**

1. **Adherence** -- fraction of responses whose pole classifier call matches
   the coder's winning pole, per non-indifferent dimension. The primary curve
   is adherence against fill, one line per arm.
2. **Human blind spot-check** on a stratified sample of responses, labeled by
   the same keypress presenter with arm and fill hidden -- the check that the
   pole classifier still means what it did on the corpus.
3. **Correctness** -- the functional canary from M5 at every fill level, so
   an arm cannot win adherence by getting worse at the task.
4. BT RM score as a secondary, cross-checking metric 1.

**The research question, as a measurement.** Two quantities: the B-C gap at
zero fill (do weights and context start equal?) and the *slopes* of B and C
against fill (does context degrade faster than weights?). Bootstrap CIs on
both; per-dimension breakdown, because the honest result may be "weights
hold for style axes and context holds for behavioral ones", which pooling
would hide.

**Confounds to control:**

- pole classifier trained on corpus wording overfits to corpus style ->
  human spot-check is mandatory, not optional
- adapter degrades capability -> correctness canary at every point
- context-file arm advantaged by prompt tuning -> mechanical generation only
- filler primes a pole -> neutral filler, same filler for every arm
- base model already leans toward a pole -> arm A is the baseline every
  adherence number is reported *relative to*, per dimension

**Falsifier.** All three curves within each other's intervals at every fill
level -> either the base model already does what the coder wants (arm A
adherence high) or neither carrier works; in both cases there is no
weights-vs-context question to answer on this corpus, and that is the
result.

---

## Components, and what is already built

M6's harness came first, against fixtures, because a flaw in the eval design
found after four labeling sessions and an adapter is the expensive failure.
Everything pure is built and tested now; everything blocked is blocked only on
a model, a GPU, or real labels -- never on a design decision.

| Module | Holds | State |
|---|---|---|
| `whip/reward.py` | rubric generation, `direction`/`wanted_pole`, the factored `reward`, judge validation and the trust gate, DPO/KTO builders, `split_by_item` | built, tested |
| `whip/arms.py` | mechanical context file, the three arms, fill assembly, `adherence`, `slope`, `sweep_summary` | built, tested |
| `whip/persona.py` | synthetic labeler, arm simulator, oracle judge -- fixtures only | built, tested |
| `probe/pipeline.py` | `dryrun`, `contextfile`, `judgecheck` | built |
| pole + situation judges | the LLM-judge backends behind the `PoleJudge` / `SituationJudge` protocols | blocked: needs a model. Injected, so swapping one in changes no other file |
| DPO / KTO / GRPO training | the actual fine-tuning | blocked: needs a GPU and the base model. Datasets are built and split already |
| generation | producing responses per arm per fill level | blocked: needs the base model. `simulate_response` stands in |

Judges and generations are injected everywhere, so the arithmetic, the metrics
and the splits are all exercised today with no model in the loop.

### The dry run

```sh
python -m probe.pipeline dryrun --layer agency --sessions 4
```

Plants a known preference in a synthetic persona -- including two conditional
axes -- then runs sessions -> labels -> `preferences.json` -> context file ->
reward -> three-arm sweep, and exits non-zero unless four things hold: the
planted preferences come back, the planted conditionals are detected, the base
arm's slope is flat, and the context arm degrades faster than the weights arm.

**It proves the chain wires together and that the metrics can see an effect of
the shape M6 hypothesises. It is not evidence about anyone's preferences and
not a result about weights versus context** -- the arms are simulated by a
function written to contain the effect. Same standing as `probe/simulate.py`,
which fabricates captures to exercise the M0 pipeline without a ring.

### What the dry run already changed

Two design faults surfaced before any real data existed, which is the entire
argument for building the harness first:

- **The base arm's slope was not flat.** At low sampling it drifted, which
  would have read as context-independent degradation in a real run and
  contaminated both other arms. It is now a precondition the dry run asserts,
  not something to notice afterwards in a plot.
- **The per-dimension conditional prediction needs far more samples than the
  pooled comparison.** Measured across 12 seeds: at ~48 samples per dimension
  per fill level the conditional-versus-unconditional slope comparison inverts
  on 1 seed in 12; at **160 it is stable 12 out of 12**, and more buys
  nothing. The pooled arm comparison is reliable well below that. So the
  headline result and its most interesting breakdown have different sample
  budgets, and the breakdown sets the real cost of the sweep. Budget 160+
  generations per dimension per fill level per arm.

A third constraint comes from the corpus rather than the harness: detecting a
conditional needs four decided pairs at each level of the factor, so an axis
has to recur across the campaign. Under-sampled, the aggregator reports the
main effect and claims no flip -- the honest failure, and it is tested.

## Build order

1. **Judges.** Wire a real backend behind `PoleJudge` and validate with
   `probe.pipeline judgecheck` against the corpus's own variants, held out by
   item. Any axis under 90% reverts to weight 0 rather than contributing
   noise. This is also M6's metric, so it gates everything downstream.
2. **Situation judge**, same shape, over prompts -- required before any
   conditional axis can be scored at all.
3. **Generation**, replacing `simulate_response`, which turns the dry run into
   a real arm-A measurement with no adapter needed. Arm A alone already
   answers "does the base model already do what the coder wants", and if
   adherence there is high there may be no question left to ask.
4. **M5 training**, once M3 has produced real labels.
5. **The full sweep.**

Steps 1-3 need no labels and no adapter. Only 4 waits on M3.
