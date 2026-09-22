---
id: narration-01
dimension: narration
layer: agency
status: gold
domain: embedded
situation: small
sentinel: false
---

# Task

The I2C driver keeps returning the last good reading after a bus error. Fix it.

# Context

One driver file and its header, maybe four minutes of work. A stale value after
a NACK is a small, contained bug in code that is a few hundred lines long.

## A (silent)

*(four minutes, nothing sent)*

`i2c_read_reg()` returns the cached `last_value` when the transfer NACKs --
`i2c.c:141` assigns into the cache before checking the status register, so a
failed read overwrites nothing and the caller sees the previous sample with a
zero return code.

Moved the status check ahead of the cache write and made the failure path
return `-EIO` rather than 0. The one caller that ignored the return code,
`sensor_poll()` at `sensor.c:88`, now skips the sample instead of publishing it.

Reproduced by holding SDA low mid-transfer: before, the same value repeats
indefinitely; after, the read returns `-EIO` and the poller logs a skip.

Unit tests 22 passed, plus one new case for the NACK path.

## B (running)

Reading `i2c.c` and `i2c.h` now.

Found it -- `i2c.c:141` writes into the cache before it checks the status
register. Looking at who ignores the return code.

One caller does, `sensor_poll()`. Patching both, then I will reproduce it on
the bench by holding SDA low.

Reproduced and fixed; running the unit tests.

---

`i2c_read_reg()` returns the cached `last_value` when the transfer NACKs --
`i2c.c:141` assigns into the cache before checking the status register, so a
failed read overwrites nothing and the caller sees the previous sample with a
zero return code.

Moved the status check ahead of the cache write and made the failure path
return `-EIO` rather than 0. The one caller that ignored the return code,
`sensor_poll()` at `sensor.c:88`, now skips the sample instead of publishing it.

Reproduced by holding SDA low mid-transfer: before, the same value repeats
indefinitely; after, the read returns `-EIO` and the poller logs a skip.

Unit tests 22 passed, plus one new case for the NACK path.

# Notes

The final report is word-for-word identical in both variants, which is the
control: this axis is about output produced *while* working, not about how much
detail lands at the end. Same diagnosis, same patch, same caller fix, same
bench reproduction, same test count. B's interim lines add no information the
report lacks; they only arrive earlier. Neither is a strawman -- A is not
hiding, it simply has nothing finished to say yet, and B is not padding, since
each line marks a real transition in the work. On four minutes of work the
running commentary has little dead time to fill, which is the condition under
which it may read as noise. Pairs with `narration-02`, the same axis on work
that runs for the better part of an hour.
