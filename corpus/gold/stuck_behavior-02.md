---
id: stuck_behavior-02
dimension: stuck_behavior
layer: agency
status: gold
domain: cpp-daemon
situation: large
sentinel: false
---

# Task

Port the preprocessing chain to the C++ daemon and get it matching the Python
reference to 1e-5 on the golden vectors.

# Context

A multi-stage port: decode, despike, windowing, channel construction, then
the network itself, each with its own golden vectors. Four stages reproduce;
one does not, and the daemon is a scratch build that nothing depends on yet.

## A (persist)

Trunk parity is there, the filter is not, and it took the afternoon.

Conv blocks, pooling and the head reproduce the golden vectors to 3e-7. The
despike stage did not -- max abs diff 4.1e-2, concentrated in the first
twelve samples of every window.

In order:

1. Checked the MAD scale factor: 1.4826 both sides already.
2. Swapped `nth_element` for a full sort, in case of median tie-breaking:
   byte-identical output, so not that.
3. Diffed the intermediate buffers sample by sample. Divergence starts at
   sample 0 and decays across the window -- an edge signature, not
   arithmetic.
4. Reread the reference: it pads by reflection before the rolling median, and
   the port clamps to the first value. Changed the port to reflect.

    golden vectors, all stages: max abs diff 6.2e-7 over 240 windows
    worst stage: despike, 6.2e-7

Under the bar. Two notes: the reflection rule now exists in two languages with
nothing but the golden vectors tying them together, and this is all float32 --
quantisation is untouched.

## B (surface)

Trunk parity is there, the filter is not, and I would rather show you the
shape of it than keep going alone.

Conv blocks, pooling and the head reproduce the golden vectors to 3e-7. The
despike stage does not -- max abs diff 4.1e-2, concentrated in the first
twelve samples of every window.

Two things checked before stopping. The MAD scale factor is 1.4826 on both
sides already. Swapping `nth_element` for a full sort changes nothing, so it
is not median tie-breaking. And the divergence starts at sample 0 and decays
across the window, which reads like edge handling rather than arithmetic.

What I have not done: walked the reference's padding line by line, or tried
each edge convention in the port to see which one closes the gap.

If you already know what the reference does at the window edge, that is one
sentence from you against maybe an hour from me. Otherwise say so and I will
work through the conventions.

# Notes

Identical measurements, identical narrowing to an edge-handling signature,
same register, and the same two cheap checks done before either variant
speaks. The axis is where the report lands: A carries on through the
remaining hypotheses and reports a chain that meets the bar, B returns with a
localised failure and the specific question that would collapse the search. B
is not helpless -- it has narrowed the fault to one stage and one
characteristic -- and A is not silent for the sake of it, since every step it
took is listed. Size is the flipped factor against `stuck_behavior-01`.
