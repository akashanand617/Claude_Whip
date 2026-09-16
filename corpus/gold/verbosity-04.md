---
id: verbosity-04
dimension: verbosity
status: gold
domain: embedded
sentinel: false
---

# Task

The 1 kHz tick ISR misses ticks whenever `DEBUG_LOG` is enabled. With it off,
the sample clock is perfect. Why?

# Context

Cortex-M0 firmware, 64 MHz core. The tick ISR advances the sample clock and,
under `DEBUG_LOG`, calls `log_dbg("tick %lu", ticks)`, which formats and
writes over a blocking UART at 115200 baud.

## A (terse)

The UART log call blocks for several tick periods, so ticks arriving while
the ISR is still running coalesce into one pending interrupt and the rest
are lost. Log from the main loop instead:

```c
 void SysTick_Handler(void) {
     ticks++;
-    log_dbg("tick %lu", ticks);
+    log_tick_pending = 1;
 }

 /* main loop */
+    if (log_tick_pending) { log_tick_pending = 0; log_dbg("tick %lu", ticks); }
```

## B (explanatory)

The budget: at 64 MHz and a 1 kHz tick, the ISR has 64,000 cycles per tick.
The cost: `log_dbg` writes ~24 characters over a blocking UART at 115200
baud — 10 bits on the wire per character is about 87 µs each, so ~2.1 ms
per call, roughly 134,000 cycles. One log call therefore spans two full
tick periods with the handler still on the stack.

Ticks that fire during that window don't queue up: the pending bit for an
interrupt source is a single flag, so the second tick pends and the third
lands on an already-set bit and vanishes. That is exactly a missed tick,
and it happens on every logged tick, not occasionally.

The fix is to keep only the cycle-cheap work in the ISR and move the UART
onto the main loop's time:

```c
 void SysTick_Handler(void) {
     ticks++;
-    log_dbg("tick %lu", ticks);
+    log_tick_pending = 1;
 }

 /* main loop */
+    if (log_tick_pending) { log_tick_pending = 0; log_dbg("tick %lu", ticks); }
```

The ISR is back to a few cycles, and the log line still appears — delayed by
at most one loop iteration, which debug output can tolerate.

# Notes

Identical diagnosis and byte-identical fix; the axis is whether the latency
arithmetic (cycles per log call vs cycles per tick, the single pending bit)
is wanted alongside the answer. B's numbers are consistent with the stated
clock and baud rate, so the extra content is correct, not padding.
