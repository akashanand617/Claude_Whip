---
id: initiative-03
dimension: initiative
status: gold
domain: cpp-daemon
sentinel: false
---

# Task

Make the daemon reconnect automatically when the ring drops.

# Context

The daemon streams accelerometer data over BLE. Drops happen two ways:
walking out of range during a wear session, and deliberately, when the ring
reboots to apply a firmware image over DFU. The request fixes neither the
give-up policy nor the DFU interaction, and both change the design.

## A (ask-first)

The reconnect loop itself is mechanical; two policy choices change the
design, and I'd rather not guess them:

1. **Should it ever give up?**
   - (a) retry forever with backoff — right for wear sessions where you walk
     back into range, but a dead ring battery means the daemon spins
     silently for hours looking healthy;
   - (b) give up after N minutes and exit nonzero — a supervisor or the
     session log then notices, but a long coffee break kills the session.
2. **What happens during a firmware flash?** The ring reboots on DFU END by
   design. A reconnect storm right then can grab the link while the
   bootloader is up. I can suspend reconnection while a DFU is in flight,
   or we keep the convention that the daemon is stopped during flashing.

Pick one from each and it's about 40 lines either way, with the choice
behind a flag so we can revisit.

## B (act-first)

Done — reconnect with exponential backoff: 1 s doubling to a 60 s cap, with
jitter. Three policy choices I made, each stated and reversible:

- **never gives up** (a `--max-retry-mins` flag exists to change that) —
  wear sessions resume when you walk back into range;
- **suspends while a DFU is in flight**, since the ring reboots deliberately
  on DFU END and a reconnect storm could grab the bootloader's link;
- on reconnect it **re-sends the stream start command** and stamps a gap
  marker in the capture, so analysis sees the hole instead of a silent seam.

Forced a drop at the desk to test: reconnected in ~3 s, stream resumed.

# Notes

Both variants surface the same two policy risks — silent infinite retry
against a dead ring, and reconnect attempts colliding with a DFU reboot —
and the same design consequences. A lays the options out and blocks on a
choice; B picks defensible defaults, flags them, and reports a test. The
ask-first variant is the longer one here; the analysis quality is equal.
