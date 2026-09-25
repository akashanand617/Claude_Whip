# Fixed timer create/start/restart code capture

2026-09-23. After fresh confirmation that all other ring clients were closed,
the unchanged prepared plan completed **180 matching CD01 transactions**.
All 452 new ROM bytes matched their repeats, as did the known 72-byte STOP code
and configuration/idle postchecks. Disconnect was verified. The request/reply
interval was 24.477 seconds, excluding connection/disconnection.

No sensor-start, flash, clock/settings, target-execution, key-field, MMIO/FIFO
or new hook-state RAM operation occurred. No returned pointer was followed.
CD01 retains its known connection/timer/activity bookkeeping effects; this was
not a zero-side-effect operation. Sampled V2 identity is not full attestation.
This completed session does not authorize another read or firmware trial.

Originals: `data/rom-timer-resume-20260923-idle-v1/`. The two archived copies are
byte-identical. SHA-256 values are recorded in `SHA256SUMS`.

| Fixed window, end exclusive | Bytes | SHA-256 |
|---|---:|---|
| `0x13634..0x136bc` | 136 | `90281b50000d2f81082e8d7738fbf85e5f5e88d4687c27c0a22e494ce2edc09b` |
| `0x137ec..0x137f8` | 12 | `31bce15290497565cafe4f2858a6087c7d94d39d0250fc08bdb2bf2f38655aae` |
| `0x13f9e..0x140ce` | 304 | `6cf0d3a9841ae669e2de287e020adcacc9684e9336ae69202d081cf6b453512b` |

Preflight: 540 selected offline tests passed; all 209 hashes from the existing
2049-test guarded build matched before connection. The new standalone archive
regression validates checksums, exact requests and order, replays every reply
through the fixed reader, reproduces the saved result and retains all evidence
limitations. It is not part of that earlier build's manifest or test count.
No firmware source, compiler flags, image bytes or construction gate changed.

The subsequent guarded `build-20260923-resume-execution-v1/` includes this
archive/transcript and the replay plus 79 actual-code execution cases: 2129
tests pass, zero skips/failures, with all 213 hashes verified. Both ARM ELFs are
unchanged. The new tests distinguish proved native allocation/argument behavior
from conditional conversion fixtures; they do not establish hardware resume.

The capture identifies hook-slot addresses, not their current values. Missing
callee bodies, configuration values, restart literals, lifetime/serialization
and physical evidence remain unresolved. See
[the diagnostic record](../../../../docs/UNIFIED_TIMER_RESUME_READ.md).
