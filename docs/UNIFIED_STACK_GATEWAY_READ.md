# Fixed stack-gateway diagnostic: completed

2026-09-24/25. The guarded preflight was followed by one freshly coordinated
physical read on 2026-09-25. It completed all **122** fixed requests, saved the
two repeated windows, and confirmed disconnect. No sensor command, flash,
binary change, production attachment or release-gate change occurred.

## Purpose and hard boundary

The [control-ingress audit](UNIFIED_CONTROL_INGRESS.md) needs actual stack
callback ownership/disconnect-ordering evidence. This first bounded discovery
read can identify the gateway entry and one named slot; it cannot by itself
prove callback drain, target semantics or the complete dispatch path.

`whip/fwstack_gateway.py` and the separate `probe/stack_gateway_read.py` prepare
exactly these new windows, each twice:

| Window | Address | Bytes | Meaning before capture |
|---|---:|---:|---|
| ROM entry cap | `0x4926` | 32 | Fixed prefix at the exported Thumb entry, not a function-length claim |
| Upper Stack entry slot | `0x2011d4` | 4 | Uninterpreted data; never followed or executed |

The pinned symbol map names `SystemCall_Stack=0x4927`, `upperstack_entry`, and
adjacent application slots. The 32-byte cap need not contain only instructions;
the next exported symbol does not establish intervening ownership. Reading
exactly four bytes excludes the adjacent `app_pre_main` and `app_main` slots.
The original25Hz/V2 wrapper at file `0x15518` independently corroborates selector
`0x107` and the call to `0x4926`. Their instruction/literal witnesses at files
`0x6d4`, `0x6d8` and `0x804` corroborate the named slot. These are local reference
checks, not extra device reads or full installed-image attestation. Stock3.12.02's
wrapper is at a different file offset (`0x156bc`); it is not transplanted.

## Fixed transaction sequence

1. Existing critical-site/diagnostic-path V2 fingerprint, idle byte, exact repeated
   configuration and bank0 descriptor, with postchecks: **91 requests**.
2. Known application ROM identifier twice: **4 requests**.
3. Previously captured 72-byte ROM STOP/delete window twice, requiring exact
   prior-capture equality before new access: **12 requests**.
4. New 32-byte cap twice: **6 requests**; four-byte slot twice: **2 requests**.
5. Exact configuration and idle postchecks: **7 requests**.

Total **122 requests**, at most 14 data bytes per request. The 36 new unique
bytes do not authorize following any returned address, widening the cap,
reading neighboring slots, MMIO, OTP, keys, another bank or another plan.
Each phase admits only its exact new chunks. Any mismatch, malformed/duplicate/
foreign notification, timeout or cancellation closes the one-use reader and
poisons it. There is no retry or reconnect. Returned slot values including
MMIO/OTP-looking pointers remain data and never become requests.

The standalone CLI requires literal fresh confirmation before loading references
or importing the hardware layer, a specific BLE identifier, exact device info,
and a new output directory. It owns the client before awaiting connection setup,
so failed or cancelled setup also reaches cleanup. The operation has a 180-second
deadline and collection a 120-second deadline, in addition to per-request limits.
Cleanup has separate budgets: up to three seconds for attempted notification
unsubscribe, then up to ten seconds for a disconnect attempt even if unsubscribe
fails. It checks the
exact request count and late-traffic poison after confirmed disconnect; only
then may it save a successful capture. A failed/uncertain disconnect is not
reported as success. A disconnect that throws, times out or is cancelled is
not confirmed even if the backend property already says disconnected. Repeated
cancellation is recorded as uncertain; no background retry is launched. These
are software bounds, not a promise that an operating system/backend can always
recover a physical connection within a deadline.

**CD01 is a data read with firmware bookkeeping side effects**, not a harmless
capability probe. No stream, DFU or other ring client may be active. The command
does not start/stop sensors or flash. Internal goal continuation, test success,
or an old idle confirmation is not new device authorization.

## Physical result and bounded interpretation

The successful capture is archived at
`firmware/research/2026-09-25/stack-gateway/`. The two reads of each new window
matched exactly:

| Window | Captured value | SHA-256 |
|---|---|---|
| ROM entry cap | `0fb410b5784803a90268002a01d00298904710bc08bc04b01847f7b5044684b0` | `7f67ae203ee1252bbb7ff9c50d694f0b17ea31d90bdc44b807d8f88cd07f377b` |
| Upper Stack entry slot | `01e48000` | `83ce321535edbf205c8337b34faef3b84e473ff54cb0b981cb36535c6fa523ee` |

The ROM cap contains the complete small exported gateway through its return,
followed by the next prologue. In Thumb terms it saves `r0..r3`, loads the
named slot, skips the call if it is null, otherwise restores the original `r0`,
passes a pointer to the remaining stacked arguments in `r1`, and performs
`blx` through the slot. This establishes a real indirect ROM-to-Upper-Stack
boundary for the sampled installed state; it does not establish what the target
does, callback task context, retention or disconnect draining.

The slot decodes little-endian as the Thumb pointer `0x0080e401`, whose even
target is `0x0080e400`. That equals both execution-address words in the already
captured, repeated ring Upper Stack header. It is also exactly `0x400` after the
declared Upper Stack partition start `0x0080e000`, consistent with the payload
entry rather than arbitrary RAM or a neighboring application slot. The reader
did not follow or execute it. A different-board public system blob cannot supply
the ring-specific target semantics because its Upper Stack hash and length are
already measured to differ.

The saved capture SHA-256 is
`c8ea5af0fb5ae5a820b71b2e86fbeafac3c1e3e36105bb0c860370347ab96604`;
the transcript SHA-256 is
`91d350563a167869c1a145c34e1eed644b7242a7c4519935f817947b6122071e`.
The transcript ends with exactly 122 requests, a confirmed disconnect and a
completed record. Sampled equality is not full installed-image attestation.

## Guarded preflight evidence

`firmware/unified/research-20260925-stack-gateway-preflight-v2/` records
**444 passed in 3.71 seconds**, zero failures/errors/skips/xfails: 150 new
gateway cases and 294 existing ROM/configuration-reader cases. The new cases
include all four new chunks through original25Hz/V2 CD instructions in three
bookkeeping states (24 cases), with explicit source-memory/copy boundaries.
They do not execute the sampled gateway bytes or a returned pointer. The final
31 cases exercise setup, notification and disconnect failures/timeouts/cancellation,
including a second cancellation during cleanup and an optimistic backend flag.

Collection/execution agree on 444 identities and 1332 passing phases. The
manifest pins **1285 content hashes** (1219 inputs, 63 artifacts, three reports)
and four tools. Supplement SHA-256:
`b6afabcc24688284b11ef4d3aeb4d5aa002523c792cda1d113c330c222e1ffdf`.
Launcher: `/tmp/whip-stack-gateway-v2-proof.LJC5LJ/run.py`; fresh output paths are
required for a rerun. The prior 107-case ingress checkpoint remains unchanged.
This is not a rerun of the full firmware suite or a new whole-image link.

The retained v1 run passed 413 cases, but independent review reproduced an
inherited `capture.connected()` gap: it did not attempt disconnect when connect
failed/cancelled before yielding. The original fixture always yielded and missed
that boundary. The new CLI now owns its client and cleanup directly; the shared
capture helper and prior firmware proofs were not edited. V1's 1218 hashes were
independently verified before this correction; its CLI/test source pins are now
historical, not current-source verification. V2 pins the retained v1 manifest,
reports and synthetic artifacts as well as the corrected sources.

Independent v2 review found no blocking defect within this scope and verified
all 1285 content hashes, four tool/launcher pins, ordered identities/JUnit and
1332 passing phases. It rechecked the prior 107 checkpoint's 1178 unchanged
content hashes and the 36 retained v1 manifest/report/artifact pins. Root also
rechecked every current v2 hash after handoff edits. This does not promote any
synthetic result into physical memory, callback or disconnect evidence.

**Every preflight transport artifact under `synthetic-test-output/` is fake**, including
files that deliberately exercise the production `device_capture` serialization
schema. They are not ring measurements. New ROM bytes/slot values are invented
test data. Physical accessibility, actual slot meaning, callback lifetime,
recovery, complete identity and flash authorization all remain unproved.

The completed physical capture still requires a separately bounded plan before
any target bytes are read; this session did not authorize one. It is not a
shortcut to final firmware or flash approval. The whole-28 lower
bound remains 10798/9520 bytes, six strong bindings are absent and all six
[release gates](UNIFIED_READINESS.md) remain open.
