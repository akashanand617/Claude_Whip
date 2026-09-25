# Completed support-code/state diagnostic

2026-09-23. The user requested testing after the separate battery-only session
successfully connected and reported 99%, not charging. One newly coordinated
`probe.rom_read --support-code` attempt completed and disconnected; no retry or
follow-up address read occurred within this session.

Original evidence: `data/rom-support-20260923-idle-v2/`. Both archived files are
byte-identical copies, pinned in `SHA256SUMS`. The earlier discovery failure
remains separately archived in `../rom-support-not-found/`.

Exactly 284 matching CD01 request/reply pairs: the first 181 prerequisites and
known-code comparisons, then 96 fixed new-window reads and seven postchecks.
All checksums, repeated values, known-code comparisons and final idle/config
checks passed; disconnect was verified before the success file was saved.
First-request to last-reply interval: 38.679958166 seconds, excluding connection
and disconnect. Collection covered 616 new ROM bytes and 17 fixed non-secret
state bytes. No sensor, flash, reset, settings/clock, key/MMIO/FIFO, pointer-
following or inspected-code execution operation occurred. CD bookkeeping
effects still apply; this was not a zero-side-effect protocol.

| Fixed state window | Repeated observed value |
|---|---|
| Timer inhibit at `0x20037d` | `00` |
| Timer rate configuration at `0x200484` | `100` (little-endian word) |
| Create/start/restart hooks at `0x201644/48/4c` | `0x205c01`, zero, zero |

The **create hook is nonzero**. Its target code was not captured or followed;
do not substitute the ROM create default for the actual live wrapper path.
The separate repeated state windows are neither an atomic snapshot nor proof
that these values remain unchanged. Rate configuration is not physical timing.

The ROM window includes the unsigned arithmetic helper and context selector;
their exact semantics are checked off-ring, separately from capture replay.
Flash/OTA literal values are constants, not physical chip geometry, successful
OTA/power-loss behavior or a recovery route. No construction gate opens.

Before connection all 215 prior-build hashes matched and 134 selected preflight
tests passed in 2.37 seconds. No firmware C, diagnostic implementation or image
was changed for this session. Further device access needs renewed coordination.

Subsequent guarded offline build:
`firmware/unified/build-20260923-support-execution-v1/`, 2323 passed in 163.21 s,
zero skips/failures/errors; all 219 hashes checked. This includes the exact
archive replay and 59 new captured-code cases. Both ARM ELFs are unchanged.
Manifest SHA-256:
`88d44cd1317cd44f891b4b1f1739d9cd85e7549fb4f2d5907070e4263c2d0c2f`.
It is not flashable and does not qualify physical continuity or recovery.
