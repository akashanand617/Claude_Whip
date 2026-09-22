# The agency layer: preferences as policies

Layer 1 (`docs/CALIBRATION.md`, `corpus/taxonomy.json`) measures what a single
response looks like -- how verbose, how commented, how defensive. This layer
measures **how the model works with you**: how much it does before checking in,
what makes it stop, whether it narrates, whether it proves its work.

Two things separate it from layer 1, and both were the point of building it.

---

## 1. The unit is a trajectory, not a response

A response can only show you a response. Autonomy, narration, stuck-behaviour
and scope renegotiation are properties of a *run* -- they live in the shape of
what the model did across many steps, which no single answer exhibits.

Full transcripts do not fit the 40-second labeling budget. **Compressed action
logs do**:

> **"The uploader times out on big files."**
>
> *A:* Read three files. Cause: the whole-file PUT uses one 30 s timeout
> regardless of size. Switched to chunked upload, 8 MB parts, retry per chunk,
> config knob. Two tests updated, one added. 17 passed. A 40 MB file now goes
> up in about 30 s.
>
> *B:* Read one file. Same cause. Scaled the timeout with file size -- two
> lines, your file goes through, 17 passed. Still dies north of 200 MB;
> chunked upload is the real answer, about 40 lines. Carry on?

Same diagnosis, same words for it, same register, both correct, both shipping
working code. The only difference is how far the model went before returning.
That is `step_size`, and it reads in well under 40 seconds.

The presenter, the plan format, the ring join and the aggregation are all
unchanged from layer 1. Only the item content differs.

---

## 2. A preference is a policy, not a constant

The failure this layer exists to avoid: deciding someone is "the hands-off
type" and baking that in. Nobody is one archetype all the time. The same coder
wants large autonomous steps on a scratch branch and small ones on a migration,
and calling that an inconsistency loses the only interesting part.

So items declare a **situation**, and each axis declares which situation
factors might flip it. Whether they actually do is measured, never assumed.

| Factor | Levels | What it asks |
|---|---|---|
| `reversibility` | reversible / irreversible | can the work be undone cheaply? |
| `familiarity` | familiar / foreign | can you check the output at a glance? |
| `ambiguity` | determined / underdetermined | one right answer, or a genuine fork? |
| `mode` | exploring / shipping | a spike, or something others will run? |
| `size` | small / large | one file, or many steps? |

An axis that declares a conditioner must have gold items at **both** levels, or
the flip it claims is untestable -- `probe.calibrate validate` enforces this
once the axis has four items, the same threshold the length-leak check uses.
An axis with no conditioner (`register`) asserts the preference is
unconditional, which is a real and useful claim.

### The axes

| Axis | Poles | Conditioners |
|---|---|---|
| `step_size` | increments / stretches | reversibility, familiarity |
| `stop_trigger` | surface_early / resolve_alone | ambiguity, reversibility |
| `plan_exposure` | plan_first / execute_direct | size |
| `narration` | silent / running | size |
| `reasoning_exposure` | conclusion_only / alternatives_shown | ambiguity |
| `register` | curt / composed | none |
| `verification` | asserted / demonstrated | reversibility, familiarity |
| `provisionality` | sketch / finished | mode |
| `scope_renegotiation` | deliver_asked / deliver_needed | size, reversibility |
| `pushback_handling` | defer / hold | ambiguity |
| `stuck_behavior` | persist / surface | size |

Near-neighbours are kept apart deliberately, because they come apart in
practice: `step_size` is how much work happens between check-ins,
`stop_trigger` is what causes one, `plan_exposure` is whether the intent is
announced first. A coder can want a plan up front and then no interruptions at
all. Layer 1's `initiative` is the same instinct applied to the *initial*
request; these apply mid-run.

**Dropped during design:** `uncertainty_surfacing` (flagging which parts of the
work are shaky) -- too close to layer 1's `hedging` for a labeler to react to
them separately. If a distinction cannot be felt in 40 seconds it is not an
axis.

---

## Guardrails are not axes

Some behaviour has a right answer: do not leak secrets, do not delete data on
your own initiative, do not push to main, do not deploy unasked. Those are
constants, trained in regardless, and they are **never** put on screen. Putting
one in the corpus invites approving reckless behaviour and records a preference
nobody holds.

The operational rule, which item review enforces: **in an irreversible
situation, both variants stop at the same safety line.** The axis is how much
is prepared before returning, never whether the dangerous thing gets done. The
`step_size` items at the irreversible level all follow this -- neither variant
touches production, and the `# Notes` block says so.

If one pole is wrong, it is not a dimension.

---

## What comes out

`probe.label aggregate` reports one of five results per axis, and which one
appears is itself a finding:

| Result | Meaning |
|---|---|
| a pole | unconditional preference |
| `conditional` | the preferred pole differs by situation |
| `indifferent` | > 60% of pairs read indifferent; weight 0, trained flat |
| `contested` | sessions disagree and no situation explains it -- item review |
| `unmeasured` | not enough decided pairs |

**Conditionals are detected before the main effect is judged.** A preference
that flips cleanly cancels itself out in aggregate -- four votes each way --
and the earlier code dismissed exactly that case as `contested`, which was
backwards: a perfect flip is the most informative result available, not a
failure to decide. A flip needs four decided pairs at each level, each level
lopsided on its own, so the design detects **flips, not gradients**. A
preference that merely weakens with stakes reads as unconditional, which is the
honest call at this sample size.

The context statement composes into a policy:

> When the work is easy to undo, take the task as far as you can in one go and
> report when it is finished. When the action cannot be cheaply undone, work in
> small increments and come back after each one.

A clean flip has **no default pole** and gets one clause per situation. An axis
with a default and an exception gets "default, Exception: when X, other". Pole
statements are written imperative and never open with "When" or "If", or the
composition produces "When X, when you hit Y, do Z"; the validator checks this.

---

## Why this is where the research question lives

"Be terse" is a local constraint on every output -- a context file states it
once and each response either obeys or does not. A conditional policy has to
*fire at the right moment*: the model must recognise, at a decision point
buried deep in a filled context, that this particular action cannot be undone,
and switch behaviour accordingly.

That is a much harder thing to carry in a prompt than a style rule, and it
predicts a sharper M6 result: **the context arm should degrade fastest on
conditional axes and slowest on unconditional ones.** That is a per-dimension
prediction the three-arm eval can test directly, and it would be invisible in
a pooled adherence number.

Layer 1 remains the warm-up that validates the pipeline end to end. This layer
is the experiment.

---

## Sessions

One layer per session -- 23 axes cannot each get enough pairs in one sitting:

```sh
python -m probe.calibrate plan --session 5 --pairs 40 --seed 11 --layer agency
python -m probe.label run --plan data/sessions/plan_s5.json
```

Everything downstream is identical to layer 1. `probe.calibrate stats` shows
per-axis situation coverage, marking any conditioner missing a level with `!`.

**Current state: 28 items across all 11 axes.** `step_size` is built out to a
full 2x2 (8 items, two per cell), the minimum that can detect a flip on either
of its conditioners. Every other axis has one pair at each level of its
*primary* conditioner -- enough to fix the format, not yet enough to detect a
flip.

Expansion, in priority order:

1. **Four items per level** on any axis whose policy matters. That is the
   detection threshold; below it the aggregator reports the main effect and
   claims no flip, which is the honest call, not a bug.
2. **Second conditioners are declared but unprobed** on three axes --
   `stop_trigger` and `scope_renegotiation` on `reversibility`, `verification`
   on `familiarity`. `probe.calibrate stats` marks these `!`, and the
   validator starts demanding them once the axis passes four items. Either
   write the items or drop the conditioner from `agency.json`; leaving a
   declared conditioner unprobed asserts a flip nobody measured.
3. **Sentinels.** The agency layer has none yet. Two items should be marked
   `sentinel: true` before the first session, or the fatigue check silently
   does not run on layer-2 sessions.
