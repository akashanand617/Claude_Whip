# Optical event lifetime and result-commit boundaries

2026-09-24. **Off-ring evidence, not an installed guard or safe pause/resume
adapter.** No connection, sensor operation, firmware transfer or production
capability change. Installed V2 optical-off remains unchanged; unified Health
is still required at boot/default, with temporary opt-in Gesture.

This closes a specific missing path in the [Health inventory](UNIFIED_HEALTH_ADAPTER.md):
optical GPIO/service events are not ordinary enable requests or scheduled
timer callbacks. STOP and timer cancellation alone cannot fence their deferred
result writes. The new witnesses use the actual pinned stock instructions,
not a different SDK patch or transplanted V2 offsets.

Subsequent [HR commit implementation](UNIFIED_HR_RESULT_COMMIT.md) adds an
unattached compiled guard around only the four positive HR result stores. Its
bounded check/store section closes that selected ordinary-interrupt race,
not the producer identity, other result sinks or physical lifecycle gaps here.
The evidence/build record below remains this earlier audit's own snapshot.

The later [optical read audit](UNIFIED_OPTICAL_ACQUISITION.md) executes selected
status/parser/classification and mutex/RX paths formerly substituted here. Read
failures can be lost before the top-level return/flags, and completion's `0xedda`
operation is a register **read**, correcting this harness's former control-write
label. Algorithms, cached readiness and peripheral outcomes remain fixtures.

Stock image SHA-256:
`b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0`.
All file offsets below use runtime bias `0x825fb0`.
Implementation: `whip/fwoptical_dispatch.py`; tests:
`tests/test_fwoptical_dispatch.py`. **32 new cases**; focused run with existing
Health adapter/lifecycle tests: **143 passed in 2.47 seconds**, zero skips.

## The additional producer and publication path

| Stage | Actual stock code / state | Executed finding |
|---|---|---|
| GPIO-event producer | `0xd8f0`, pin argument `0x21` | GPIO helpers surround a hub post of exactly `(type=3, subtype=0, payload=0)`; controls are restored even if queue submission fails |
| Software-event producer | `0xd9f8` | Posts the same eight-byte message, with no generation, job ID, sample timestamp or result provenance |
| Hub dispatch | task `0x1466` → `0x1420` → `0xdd38` | Subtype zero calls `0xf7a8`, not ordinary owner enable `0xf824` |
| Processing entry | `0xf7a8` → `0xf774` → `0xf308` | Sets/consumes a pending flag and calls the optical processor; owner mask zero does not reject the event |
| Acquisition helper | `0x10f56` | Can return `0xffffffff` before buffer parsing when cached status bit `0x10` is set, or `0xfffffffe` for missing backing state |
| Caller handling | `0xf31c..0xf338` | Does not branch on that return; continues through classification and cached-ready tests |
| HR result commit | `0xf446..0xf462` | Writes optical state 2 and HR cache bytes at `0x20c01e` / `0x20c028`, plus auxiliary halfword at `0x20c022` |
| SpO₂ result commit | `0xf5f4..0xf60c` → `0xe094` | Updates optical state and SpO₂ working result at `0x20c0a8` |
| Completion | `0x11216` | Clears four lower status/readiness bytes; does not erase the published HR cache |

The GPIO helpers, physical transfers, optical classification/algorithms, motion
assistance, notification transport and scheduling remain explicitly substituted.
The physical cause of status bit `0x10` is **not established as an I2C failure**.
What is executed is the resulting early return and the caller's lack of a
return-value guard. Synthetic ready/error coexistence is an input witness,
not proof that this state combination was observed on the ring.

Static local reference inspection also finds `0xd942` servicing the GPIO
condition, `0xd97e` calling `0xd8f0`, a tail wrapper at `0xd986`, and its pointer
at file `0x1f700`. That is not a complete IRQ registration, interrupt-priority
or callback-lifetime proof. No claim that every subtype-zero message originates
in one execution context follows. The software poster has no direct BL caller
in the reviewed XIP scan; absence of a direct caller is not dead-code proof.

## Negative witnesses that change the binding requirements

### A late event can repopulate result state after STOP

The test executes the real disable-post, hub delivery and stock full STOP
path. With successful bus fixtures, RESET and STOP are submitted, ownership
becomes zero and optical state becomes zero. A subsequent old event executes
the real processing entry with cached-ready state and the early acquisition
return above. Under explicit algorithm fixtures it writes HR 72 or SpO₂ 98
and sets optical state back to 2, **without an enable request or additional
RUN write**. This establishes a missing software fence, not physical sensor
operation after STOP or a real medical result.

The SpO₂ witness continues through an unchanged delayed scheduled callback at
`0xe104`: 98 reaches intercepted aggregation `0xe0c6` and another disable post.
Aggregation/storage are not executed. This is a concrete chain from late event
to cache to later publication intent; gating only the final scheduled callback
would leave cache mutation and other publication paths unresolved.

### There are immediate publication sinks as well

With one synthetic cached buffer element and the exact report selector at
`0x208c47`, the same late processing path reaches packet helper `0x4766` with
command `0xc5` and an 11-byte payload. With the separate raw-report predicate
fixture enabled, it also reaches `0x6828` with 12 bytes. Both are intercepted;
no real packet is transmitted or saved. These happen independently of later
scheduled aggregation. Existing/queued transport packets still require their
own retirement policy and ownership proof.

After processing, the real completion routine clears readiness/status bytes
at the synthetic lower-state pointer +`0x18..0x1b`. The real HR getter `0xf74c`
continues returning 72. Neither zero readiness nor a plausible getter value is
an acquisition-freshness or current-job receipt.

### Entry checking and current-ticket relabeling are insufficient

The emulator can intercept `0xf7a8` with the compiled C `wh_result_allowed`
predicate. These are deliberately **boundary experiments**, not an installed
trampoline, a production inventory assignment or source qualification:

- Keeping the original synthetic ticket rejects the event while QUIESCING,
  PAUSED, and after a completed resume with a new job. The positive current-
  Health control still executes. Source-validity and lifecycle receipts in
  these tests are explicit fixtures, not inferred from stock state.
- Taking a new ticket at dequeue after resume accepts the old untagged event.
  The original queue bytes are unchanged; no implementation may silently
  relabel them with the current generation/serial.
- Injecting pause at `0xf432`, after entry admission but before HR result
  commits, still permits the original direct result stores. The C predicate
  would now reject the ticket, but the unmodified stock stores never call it.
  An entry-only check cannot replace common serialization/final commit fencing.

Thus a correct binding must either carry origin identity through deferred work
and all commits, or prove that old work cannot survive/reappear when admission
reopens. A hub-empty observation is not that proof. Timer-daemon fencing alone
does not cover this hub/event path, and the hub alone does not serialize all
scheduled/realtime result consumers.

## Scope, closed boundaries and next implementation work

Only normal HR/SpO₂ processing selections 0 and 1 are arranged by this harness.
The actual switch helper executes; its embedded table and the literal pool
are not admitted as instructions. Unknown indirect algorithm callbacks and
the physical status-read routine `0x1174c` stop the proof. A null-backing-state
test continues only under intercepted algorithm fixtures and explicitly does
not prove the real algorithm's null handling. Peripheral, queue and algorithm
fixtures must not become success receipts in production.

Next binding work must cover:

1. Origin tagging or proved retirement for GPIO/software events, including
   deferred posting, queued work, in-flight processor work and device-latched
   status. Cancellation must not flush unrelated motion hub messages.
2. A concrete shared serialization domain for mode changes and each actual
   result/RUN commit. Blocking bus work must not run under broad PRIMASK masking.
3. All direct cache, scheduled aggregation, realtime, pointer-writing and
   immediate/queued notification sinks. The new HR/SpO₂ path is not a complete
   inventory, and it assigns no real `inventory_proven=true` mask.
4. Fresh current-settings Health resume, including buffer/result lifetime, the
   unread timer-create failure handler and valid scheduler admission. Do not
   replay old handles, masks or subtype-zero events as fresh jobs.

The separate physical STOP, RAM/stack ownership, geometry/recovery, fresh FIFO/
model and steps/sleep gates remain open. Firmware C, compiler flags, stock
bytes and installed firmware are unchanged. No final OTA image is produced.

## Build record

`firmware/unified/build-20260924-optical-dispatch-v2/`: **2645 tests passed in
162.99 seconds**, zero skips/failures/errors/xfails; all **230 hashes** checked
(160 inputs, 67 artifacts, three reports). The 32 new cases are included.
Manifest SHA-256:
`ba6ba322e00ca6b4efd422668c53324a0ba8e00e89432194898f46c1cb41b9d1`.
Both ARM ELFs match the preceding hook-execution build byte-for-byte. Test ELF:
`2e66a8133a753103ff412dd959d42d7e39bb177fc2c2120aaa344b9426a67b7e`;
actual-address ELF:
`2c75d78867394ac4c9beb9ca18b3e4f5dca58c701884b64b92a65ac5720013e6`.
Components remain 9272 configured bytes, 248 remaining; combined state is
796 bytes, without approved ownership or complete integration fit.

The v1 offline build was deliberately interrupted before completion to tighten
the fixture terminology: `error_bit_set` names the observed branch condition
without claiming a proven physical transfer failure. It is retained as an
incomplete run (480 passed before interruption), not a passing gate or new
physical failure. The v2 build uses the corrected terminology and unchanged
stock/firmware behavior.
