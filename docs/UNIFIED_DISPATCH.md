# Unified command dispatcher — offline integration

2026-09-23. Continues the [shared codec](UNIFIED_WIRE_CODEC.md) toward the full
Health-default, temporary-Gesture firmware. **No ring access, phone deployment,
service registration, stock linkage or installable image.** Physical gates stay
closed; passing these tests does not establish flash readiness or zero risk.

Later follow-up: [exact-stock transport evidence](UNIFIED_STOCK_TRANSPORT.md)
adds an unattached ARM registration/send shim and executed legacy queue failures.
The latest guarded build passes 936 tests, zero skips; no actual service or
dispatch-to-stack attachment exists. Results below retain this turn's scope.

The preceding goal turn made concrete progress by implementing the C/Swift
codec. This continuation connects decoded commands to the existing guarded
adapter and owns their replies; it does not redefine the goal as software-only.

## What is implemented

`firmware/unified/dispatch.{c,h}` owns one `wa_adapter` and one control exchange.
It calls the real portable adapter, not a replacement that fabricates success.
No allocator, RTOS call, sensor access, UUID, address patch or flash write is
added. It belongs to one proven serialization domain together with **all**
physical receipts, source observations, transport enqueues and lifecycle events.

| Command | Condition for successful reply |
|---|---|
| Status | A snapshot of the current state; Entering/Returning/Fault remain explicit |
| Gesture | Adapter has committed Gesture after optical quiescence, preservation-safe hold and the first validated source delivery |
| Health | Adapter has committed Health, with its measurement admission open; a queued resume or `WH_READY` is insufficient |
| Renew | Correct active session and genuinely advancing sequence already accepted by the motion transport |

These are software obligations. The hardware binding must still establish that
every receipt is true. Tests supply clearly synthetic receipts and a synthetic
source profile; neither is an approved physical configuration. Boot initialization
must occur only after actual stock Health initialized successfully. An unavailable
inventory/profile refuses Gesture without quiescing ordinary Health.

## Ownership and failure rules

- Initialize once per boot with a nonzero 64-bit boot identity. The dispatcher
  does not create entropy, attest a build or authorize service admission.
- `wd_open` accepts a new nonzero, strictly increasing connection generation only
  while closed. No active-owner replacement, wrap or generation reuse. Physical
  old-connection work must already be fenced before opening its successor.
- Request IDs strictly increase per connection; the first accepted fragment
  reserves its ID. Both correlated, validated fragments must arrive before any
  command dispatch. Wrong boot, order, checksum, length, type, reserved bits or
  request identity closes the current control owner.
- One exchange at a time: an overlapping request also closes the owner and
  initiates cleanup. There is no silent queue or re-execution/retry cache. The
  app's existing operation gate must serialize calls; to cancel a pending enter,
  close the connection rather than interleave a second request. A richer
  preemption protocol is not implemented or assumed here.
- Old-connection callbacks cannot mutate a newly admitted exchange. Reply-send
  receipts additionally require the exact request ID, fragment index and an
  outstanding offer. Captured identities must never be replaced at callback time.
- Fragment receive and reply ownership expire after 1000 ms, including when no
  further callback arrives. Whole transitions are additionally bounded by
  10000 ms; the existing per-action 3000 ms deadlines remain independently active.
  Time is unsigned monotonic milliseconds; periodic ticks remain mandatory.
- A reply is held until completion, then offered one fragment at a time. Only a
  matching positive enqueue receipt releases the next fragment. Enqueue success
  is not remote delivery or model processing. Motion lease renewal remains a
  separate advancing-progress check.
- Mode/session/charging changes invalidate a pending reply, including between
  its two fragments. Failure, corruption or timeout cannot finish an obsolete
  success reply or rewrite its second half into a different snapshot.
- Closing calls adapter link-loss cleanup, never claims Health has already
  resumed, and keeps adapter deadlines running even while closed. Fault remains
  explicit; recovery requires Health on a newly admitted connection and the
  full physical stop/release/current-settings-resume chain.

The binding must actually disconnect and fence previously offered/enqueued work
when this owner closes. A software flag cannot retract an in-flight hardware
operation. Actual enqueue and final ownership revalidation must share the same
serialized operation. This is particularly important for a success frame already
copied into a BLE driver's queue. No stock queue is asserted to meet this contract.

## Evidence

`tests/test_unified_dispatch.py` runs the same integration scenarios in native C
and compiled Cortex-M0 instructions under the strict existing emulator. Expected
wire bytes use independent Python CRC framing. Physical completion helpers call
actual `wa_*` APIs with explicit synthetic postconditions, never arbitrary direct
mode assignments. Scoped run: **81 passed, zero skips**, including:

- no effects after only the first request fragment;
- no Gesture success before the first validated source delivery;
- no Health success at READY or after settings change before commit;
- entry/resume failures and action timeouts produce errors, not success;
- unavailable inventory/profile, zero boot identity and charging restrictions;
- corrupted, out-of-order, duplicate, overlapping and replayed requests;
- request/connection exhaustion, clock wrap and silent receive/send timeout;
- stale callbacks after reconnect and mismatched/duplicate send receipts;
- charging or source expiry between success-reply fragments;
- renew refusal before send acceptance or for repeated progress;
- cleanup continuing after transport closure and explicit recovery from Fault.

The sanitizer executable in `tests/native/dispatch_stress.c` exercises **20,000
connections**: 13,334 corrupt-frame rejections and 6,666 complete two-fragment
request/reply exchanges. ASan/UBSan halt on error. With deliberately unavailable
inventory, every iteration retains ordinary Health and zero sensor-action tokens.
This is bounded software stress, not long-duration BLE or health validation.

During test setup, an unconfigured scoped invocation skipped ARM-dependent cases;
that was not accepted as validation. After providing the pinned toolchain, a
test-driver field initially shadowed the emulator's ARM-register namespace.
Renaming only that test field fixed the harness; all native and ARM cases then
passed. No product assertion, memory guard or required test was removed.

## Completed guarded build

`firmware/unified/build-20260923-dispatch-v1/` passed **874 tests in 92.80 s**,
zero failures, errors or skips. Ordered collected/executed identities and phase
outcomes agree. Nine components and four support units were double-compiled and
the artificial-address test ELF double-linked identically. All **114 hashes**
were independently rechecked: 84 source/evidence inputs, 27 artifacts and three
proof reports. `flashable`, `stock_linked` and `hardware_access` remain false.

- Manifest SHA-256:
  `11f6af3e43ac6c6d461a672c57c0c90e51017dc0fe1f4cf74b3aedea5ca0de7d`.
- Test ELF SHA-256:
  `db18bc447f7620a8b49df2325e9ec299d5153e0b6d74d4f6b8a1efa341dee3df`.
- Dispatcher `.text`: 1280 bytes; nine components total 8066 before stock hooks,
  transport, helpers, alignment and metadata. This is not final fit or placement
  approval. The configured 9520-byte stock margin is still not approved space.
- Actual ARM context: 1016 bytes including the existing 924-byte adapter; the
  dispatcher adds 92 bytes. No RAM location is approved. Reported local function
  stacks are 0–72 bytes, excluding callees; this is not a complete stack budget.
- `git diff --check` passed. No production code calls this dispatcher. No Swift
  source changed; the previous 58-test full simulator result was not rerun here.

Reproduce with the pinned proof dependencies/toolchain and a new output directory:

```sh
python -m probe.unified_build --zig /path/to/zig-0.15.2 \
  --output /new/path/to/offline-proof
```

The prior wire-only manifest remains a historical record of its inputs, not the
current builder/test source. This run does not include the separately recorded
194 legacy regressions from workflow 3. No commit or push was performed.

## Remaining end-state work

The next software boundary is the real service registration/notification adapter
and app transport, including approved-build discovery, boot identity and callback
ownership. No legacy UART command is allocated or sent by this dispatcher.

The larger release gates remain: safe flash/RAM placement and recovery; a closed
producer/result inventory and actual serialized hardware bindings; physical FIFO
timing/completion/overflow and new-source model qualification; optical STOP and
current-settings resume; genuine steps/sleep continuity. See
[workflow 3](UNIFIED_WORKFLOW_3.md). The installed image remains V2 optical-off,
not unified, and no physical health restoration occurred in this continuation.
