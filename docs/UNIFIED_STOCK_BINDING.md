# Exact-stock lifecycle binding work — 2026-09-23

**OFFLINE only. No device access, flash, installed hooks or completed physical
adapter.** This extends [the health adapter](UNIFIED_HEALTH_ADAPTER.md) with
actual queue/timer/I2C instructions and a compiled heap-free shutdown-write
shim. It does not turn a successful write into a physical-STOP receipt.

Subsequent [optical event/commit witnesses](UNIFIED_OPTICAL_DISPATCH.md) execute
hub subtype zero through actual HR/SpO₂ result writes. Late work can restore
result state after STOP under synthetic cached-ready/algorithm fixtures.
The current shim and timer barrier do not fence that path. Current resource/
test counts are maintained in [the resource handoff](UNIFIED_RESOURCE_BUDGET.md).

The subsequent [acquisition audit](UNIFIED_OPTICAL_ACQUISITION.md) executes the
parallel optical read wrapper `0xedda` and bus RX path. Lower read failures can
be lost before parser/status flags and the top-level return; those are not
freshness receipts. Completion's register operation is RX, not a STOP write.

All file offsets target stock 3.12.02, SHA-256
`b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0`;
runtime = file + `0x825fb0`. No V2 offsets were transplanted. The current ring's
sampled V2 identity is not authorization to call these stock entry points.

Later evidence: a separately coordinated [ROM-code diagnostic](UNIFIED_ROM_DIAGNOSTIC.md)
captured the stop/delete ROM wrappers and exercised those bytes offline. The
wrappers can delegate to optional hooks or default implementations. Follow-up
captures added their literals/default bodies and read both hook slots as zero
twice in the idle snapshot. The defaults call the timer-command API; delete
clears the handle on nonzero return. The subsequent
[captured-ROM execution](UNIFIED_STOCK_INTEGRATION.md#captured-rom-execution-and-null-queue-guard)
executes generic STOP/DELETE and the timer-pend/callback-dispatch paths. It
exposes deliberate null writes for invalid handles and a null-queue assertion
in the pend API, now guarded in the unattached C binding. Kernel queue/list,
allocation and scheduling boundaries remain explicit substitutes. Neither
physical callback drain nor a completed hardware adapter is proved.

## Implemented evidence

`whip/fwstock_binding.py` executes selected unchanged Thumb instructions for:

- hub creation, posting, receiving and dispatch;
- timer creation/restart/stop/delete wrappers;
- optical control through the actual mutex, allocation, bus packaging and
  error-return chain;
- indicator cancellation followed by a late brightness callback;
- realtime callback dispatch, delayed restart, result publication and failure
  cancellation masks;
- activity start/stop and their algorithm-parameter/persistence boundaries.

`firmware/unified/stock_binding.{c,h}` adds one real-address ABI component:
`wb_stock_stop_writes`. Its compiled ARM executes against original stock bus
instructions in the same emulator. It remains unattached to the runtime.
The test suite is `tests/test_fwstock_binding.py`; standalone operation needs
the isolated proof environment and pinned Zig 0.15.2 via `WHIP_ZIG`. A guarded
builder supplies its hashed `WHIP_UNIFIED_TEST_ELF` instead of compiling a
separate untracked artifact. Only the added shim's function is admitted from
that ELF; unrelated component functions are not executable in this harness.
Final scoped verification passed **168 tests, zero skips**: 57 new stock-binding
tests, 46 corrected lifecycle tests, and 65 health-adapter tests. The compiled
shim tests used the corrected vendor `bool`/opaque-handle mutex signatures.
`git diff --check` passed. The whole guarded build is recorded separately by
the workflow owner; these scoped counts are not an additional hardware gate.

## Correct optical-write ABI and new failure witness

The full executed stock chain is:

```
0x12496 control(op)
  -> 0xee12 write(register, buffer, length)
      -> ROM os_mutex_take(handle, 100)
      -> 0xdbca package(slave=0x33, register, buffer, length)
          -> 0x12948 allocate(length+11)
          -> ROM memcpy
          -> 0xdb42 transmit(slave, caller_buffer, count)
          -> 0xdaf0 stock error bookkeeping/recovery
          -> 0x129f4 free
      -> ROM os_mutex_give(handle)
```

| Control input | Register transaction | Return meaning |
|---|---|---|
| 0 | `0x7b = 0x00`, STOP | 0 when the bus path reports success |
| 1 | `0x7b = 0x5a`, RUN | same zero-success convention |
| 2 | `0x7b = 0xa5`, RESET | same zero-success convention |
| Other | no transaction | 1 |

Mutex acquisition failure or any nonzero bus status becomes `UINT32_MAX` at
`0xee12` and `0x12496`. The original lifecycle harness previously mocked this
boundary using boolean-success polarity; that mock and its assertions were
corrected after this deeper witness. The earlier conclusion that `0x10eaa`
ignores RESET/STOP errors still holds with the corrected polarity: it always
returns zero after both calls. The hub disable path still clears ownership/state
after failed bus writes. `0xee12` also ignores mutex-release failure.

**New executable failure:** the control write allocates 12 bytes for a one-byte
register write. `0xdbca` immediately stores the register number through the
returned pointer, without a NULL check. A NULL allocation produces an invalid
write before bus submission, free, or mutex release. Calling `0x12496` directly
is therefore not a recoverable shutdown implementation under allocation failure.

## Heap-free shim: what it does and does not promise

`wb_stock_stop_writes(report)`:

1. Initializes a caller-provided report; NULL report or absent mutex fails
   without any bus operation.
2. Takes the existing mutex from RAM `0x208c98` once, using ROM `0x133f5`.
3. Calls stock caller-buffer transmitter `0x833af3` (file `0xdb42`) with two
   stack bytes `[0x7b,0xa5]`, then `[0x7b,0x00]`. STOP is attempted even if
   RESET returns a bus error.
4. Releases that mutex once using ROM `0x1341d`.
5. Returns true only when both stock bus results are zero and release succeeds.
   The report preserves both bus statuses and normalized mutex booleans.

The mutex function pointer types match the vendor declarations exactly:
`bool (void *, uint32_t)` for take and `bool (void *)` for give. They are not
integer-status substitutes. See the pinned
[vendor os_sync.h](https://raw.githubusercontent.com/atc1441/ATC_RTL_BLE_OEPL/49301d9b75816ccde1cc9657b827fdadf5736937/ATC_RTL_BLE_OEPL_8762ESL/sdk/inc/os/os_sync.h).
Actual ROM implementation/patch identity and live handle validity remain
deployment requirements; mocks do not prove them.

The selected `0xdb42` paths return:

| Result | App-code branch |
|---|---|
| 0 | downstream transfer reports zero |
| 1 | downstream transfer reports nonzero |
| 2 | readiness polling exhausted |
| 3 | activity/busy polling exhausted |

Each tested polling timeout makes 501 calls to the existing indirect delay
target with argument 10. This is an instruction-count witness, **not a measured
wall-clock bound**. The actual delay implementation, bus completion semantics,
task interference and watchdog servicing must be validated before deployment.

The shim does not allocate, retry the whole operation, run `0xdaf0`'s recovery
side effects, change optical ownership/state, cancel timers, alter settings,
clear health history, or call `wh_stopped`. Bypassing the stock error-recovery
helper is deliberate: failure is returned to a future reviewed cleanup path,
not allowed to trigger hidden peripheral reconfiguration. Stock `0xdb42` still
writes its normal I2C diagnostic bytes and busy bookkeeping (`0x20c010+2..4`,
`0x208544`); this is not a side-effect-free function.

Caller obligations remain substantial: correct task context; live mutex;
fenced old RUN requests; lifecycle serialization; sensor identity; and approved
code/stack placement. **Do not hold an interrupt-disabling critical section
around this blocking mutex/polling sequence.** Admission fencing and bus
serialization need separate, proven scopes. A successful report establishes
only reported bus-write completion. Physical darkness, power-down, current draw,
and the absence of later RUN remain unproved.

## Queue and timer behavior now executed

Hub initialization `0x148c` requests a 32-entry queue of eight-byte messages,
then a task with 2560 stack bytes and priority 2. The queue slot is `0x208ca8`.
Actual task `0x1466` receives with infinite-wait argument `0xffffffff`, then
calls dispatcher `0x1420`; type 3 reaches `0xdd38`. Subtype 1 enables optics,
subtype 2 disables, and subtype 3 calls `0xf934`, which is simply `bx lr`.
That subtype is not a completion acknowledgment or a reserved future barrier.

The mock receive primitive stops the test at its next empty-queue wait. That
test stopping condition is **not a real RTOS fence**. Executed witnesses show a
completed disable followed by a late enable message restarts the optical owner.
The original eight-byte messages contain no generation or job identity.

| Wrapper | Executed semantics | Why it cannot certify cancellation |
|---|---|---|
| `0x3e04`, empty timer slot | create, then start without checking create status | start can be attempted after failed creation |
| `0x3e04`, nonzero slot | restart with new period only | new callback/repeat arguments do not replace existing timer identity |
| `0x3e30`, nonzero slot | stop then delete without checking stop status | visible return is only delete result; no callback-drain acknowledgment |
| `0x3e30`, zero slot | returns zero without ROM calls | zero is not a cancellation-completion receipt |

The tests deliberately leave mocked timer-handle storage unchanged on delete;
that demonstrates only that the app wrapper does not clear it itself. Whether
the real ROM clears a handle or drains callbacks requires separate evidence.

The official [RTL8762E SDK User Guide v1.0, pp. 19–20](https://www.realmcu.com/img/ipd/en_637839320584437719.pdf)
documents a priority-6 timer task and priority-based preemption. Together with
the stock hub's priority-2 creation, this supports a potential timer-preempts-hub
race under the documented setup. It is not a measurement of this ring's live
ROM/OTP task configuration. No bus mutex or FIFO queue ordering alone proves
all producers, consumers and timer callbacks share one execution context.

## Remaining producer paths: new executable witnesses

- Indicator cancel `0x3cac` requests cancellation for slots `0x209d10` and
  `0x209d14`, clears pattern state, and requests optical STOP. A manually invoked
  already-dispatched brightness callback `0x3ac4` still calls `0xf812` and the
  lower driver entry `0x11246`. That callback does not check a lifecycle ticket.
- Realtime timer callback is `0x4722`. Mode 6 reaches `0x4518`; other modes reach
  `0x40d6`. A mode-6 restart state posts a fresh owner-1 enable at `0x45d6`.
  Another executed path perturbs a cached getter using PRNG modulo 3 minus 1
  and emits a `69` result through `0x7e30`, without sensor acquisition in the
  fixture. Positive-looking realtime values are not provenance evidence.
- Early realtime failure branches execute distinct disable masks for modes
  1, 3, 8, 9, 10, 11 and 12: respectively 1, `0x20`, `0x200`, `0x400`, `0x100`,
  `0x1000`, `0x1301`; they request timer stop at `0x209d40` and publish a failure
  packet. This does not establish all successful/combined-mode result branches.
- Activity entry `0xa88a` clears working state, initializes counters, restarts
  timer `0x20bc54`, calls algorithm-parameter setter `0x1dd6c` and enables owner
  1. Stop `0xaa00` requests timer stop/owner disable, calls activity aggregation,
  resets algorithm parameters to `(0,0)` and clears activity state. These are
  **not** preservation-safe generic pause/resume routines.
- Wear/probe's two deferred pointer writes and all five scheduled callbacks
  remain covered by the preceding 65-test health suite. A scheduler-only or
  aggregator-only hook does not cover those sinks.

## Inventory and installation remain open

The direct call lists and selected instruction paths are now more complete,
but **all indirect/ROM producers and result sinks are not closed**. Absence of
literal pointers to an entry point does not rule out computed calls, relocated
tables, ROM patch callbacks or direct peripheral writes. This work does not set
`inventory_proven=true` for a production binding.

Still needed before installed mode switching:

1. Complete low-level RUN/write/IRQ and result-sink closure, actual timer-service
   cancellation/drain semantics, and generation capture before deferred work
   becomes independently scheduled. No old callback may be stamped with a new
   job ticket at dequeue time.
2. An audited admission barrier covering timer/main/hub/interrupt contexts;
   finite queue and callback lifetimes; failure handling if cancellation or
   enqueue fails. Preserve transport backpressure and unrelated hub traffic.
3. Physical stop evidence on a matching spare/instrumented board: bus decode
   and ACK/completion timing, independent optical/current observation, delayed
   RUN fault injection, and recovery with stuck bus/mutex/timeout cases. No
   such hardware experiment was performed here.
4. Resume from current scheduler eligibility/settings, not activity reset or
   saved ownership-mask replay. Preserve acquisition cursors, algorithm history,
   timestamps and persistent records. The STOP shim alone cannot verify steps
   or sleep continuity, overnight rollover or valid resumed optical results.
5. Approved placement, stack budget including stock/ROM callees, exact ROM/patch
   identity, boot/recovery and reviewed hooks before constructing an image.

Unresolved capability stays unavailable while ordinary stock Health remains
untouched. The new C shim is a bounded implementation advance, not a declaration
that the unified firmware is safe to flash.
