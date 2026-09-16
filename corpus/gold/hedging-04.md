---
id: hedging-04
dimension: hedging
status: gold
domain: embedded
sentinel: false
---

# Task

Why do BLE drops spike when I walk away from the desk? Seated it's 0.24%
loss, walking to the kitchen it's 10.9%.

# Context

Both responses rest on the same measurements, all on the `#4` image: seated
at the desk 0.24% loss; walking to the kitchen 10.9%. Two follow-up
captures: walking in place at the desk reads 0.3%, and standing still across
the room (~8 m, two walls) reads 9.8%.

## A (committed)

Distance and body attenuation, not motion. The two follow-ups separate the
variables cleanly: walking in place at the desk costs nothing (0.3%, same as
seated), while standing still across the room costs almost exactly what
walking there does (9.8% vs 10.9%). Loss tracks where the ring is, not
whether it's moving — at 2.4 GHz, two walls plus your body between ring and
Mac eat the link margin. Nothing here points at the firmware; the fix is
receiver placement. Keep the Mac in the same room during captures, or accept
that walk-away segments are lossy and mark them.

## B (cautious)

The pattern fits distance and body attenuation best: walking in place at the
desk reads 0.3% while standing still across the room reads 9.8%, so
position, not motion, carries the effect. Two alternatives could produce the
same split, each with a cheap discriminating check before treating the map
as settled. Interference: the kitchen path may cross the Wi-Fi router or
microwave, so repeat the ~8 m capture in the opposite direction — if loss
stays high, it's the distance, not that path. Antenna orientation: arm
posture across the room differs from at the desk, so re-measure seated with
the ring rotated 90° — walking in place already suggests orientation
changes are cheap, but that check closes it. If both come back consistent,
the conclusion is the same: receiver placement, not firmware.

# Notes

Identical four measurements, identical diagnosis (attenuation with
distance/body, motion innocent), identical recommendation (receiver
placement; no firmware change). A states it as what the numbers show; B
names two alternative mechanisms with a discriminating check for each. The
alternatives are genuinely unexcluded by the data given, so B is not
inventing doubt, and A claims only what the follow-ups directly demonstrate.
