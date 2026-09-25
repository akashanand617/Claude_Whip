# Unified hooks: bounded task-context map

2026-09-24/25, entirely off-ring. Only this document was added. No firmware,
production source, tests, probes, device state or release gate was changed.

## Decision

The stock Health consumer and minute scheduler execute in **qc_app**, not the
separate BLE-event task named **app**. Selected motion acquisition and optical
processing execute in **hub**. Captured timer-daemon code directly invokes timer
and deferred callbacks in **Tmr Svc**. These are distinct execution domains.

No existing task is yet an approved serialized unified owner. In particular,
qc_app's indefinite semaphore wait and unbounded/unmeasured service latency
provide **no periodic supervisor or deadline guarantee** for `wd_tick` or the
coordinator. Its proximity to Health state does not satisfy the requirement
that one task own every adapter/lifecycle operation. Message handoff, complete
producer admission/drain, clock and worst-case latency remain missing bindings.

## Evidence and address convention

Stock code below means file offsets in `firmware/rt02cr-stock-3.12.02.bin`,
138016 bytes, SHA-256
`b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0`.
Its flash runtime address is offset plus `0x825fb0`. RAM and explicitly marked
ROM addresses are absolute. These addresses must not be transplanted to V2.

The SDK-derived `os_task_create` declaration supplies the argument order
`handle, name, entry, parameter, stack_bytes, priority`; stock registers,
stack arguments and name literals match it. The source is the Realtek/Realsil
copyrighted public mirror at commit
`49301d9b75816ccde1cc9657b827fdadf5736937`, not the ring application's source
or proof of its SDK release. Its complete ROM-symbol text matches the archived
`firmware/research/2026-09-22/rom_symbol_gcc.axf`, SHA-256
`6f5a59f6444c01328808ac148b9c60771410196ab3b57e08fc8ff90525934247`.
See the qualified [memory/source audit](UNIFIED_MEMORY_AUDIT.md).

Timer code comes from
`firmware/research/2026-09-23/rom-integration/rom-integration.json`, SHA-256
`d02cc3582a789d933e1be09fa1bbec05ade7a193508418149f145dc12df3b05b`.
Its `timer_queue` window is ROM `0x105c8..0x10fb8`, SHA-256
`2083493e9a074bf2cb1fd9bc83f4b103ea96985becb59a7c9338fad2a3155e7a`.
This review rechecked those hashes and selected instructions. This is captured
installed-V2 ROM plus stock callers, not a live stock scheduling trace or proof
that all ROM/patch dispatch behavior is interchangeable.

## Task creation and queue ownership

| Task | Creation call / entry / name literal | Requested stack / priority | Established receiving boundary |
|---|---|---|---|
| app | `0x8e2` / `0x854` / `0x948` | 1024 bytes / 2 | Event queue slot `0x208994`, 64 one-byte entries; message queue slot `0x208998`, 32 eight-byte entries |
| qc_app | `0x13e6` / `0x131e` / `0x1418` | 3584 bytes / 1 | Semaphore slot `0x208c90`; software command ring at `0x209d50` |
| hub | `0x14b6` / `0x1466` / `0x14ec` | 2560 bytes / 2 | Queue slot `0x208ca8`, 32 eight-byte entries |

All three creation calls target declared ROM `os_task_create`, `0x13468`.
Their task-handle output slots are respectively `0x208990`, `0x208c8c` and
`0x208ca4`. Creation requests and code bodies establish intended contexts,
not successful live allocation or a complete scheduler execution proof.

The [stack archive](UNIFIED_STACK_EVIDENCE.md) independently observes V2 task
names, matching priorities and size-consistent allocations. It does not turn
stock output slots into V2 addresses, prove stock Health's peak workload or
identify the seventh unread TCB. The name `UpperStac` does not by itself assign
GATT callbacks to that task.

## Finite hook-to-context relationships

| Proposed boundary | Checked stock path | Context established for this path / limit |
|---|---|---|
| GATT discovery read or RX write | app waits at `0x89c`; non-2 event calls `0x156bc` at `0x8ac`; that wrapper calls ROM `SystemCall_Stack` `0x4926` with selector `0x107` | BLE events enter ROM from app. The unread ROM-to-GATT callback dispatch may execute inline or hand off; callback task, reentrancy and retention are **not established** |
| Existing queued RX command | Write callback `0x7ace` → `0x5c22` → fast dispatch `0x5882`; selected commands enqueue through `0x4cbc`, wake through `0x1178`; qc_app calls consumer `0x657c` at `0x1366` | Selected queued handler runs in qc_app. Fast handlers remain in the unproved callback context; this is not a unified queue/owner binding |
| Normal motion FIFO acquisition | Timer callback `0xcd46` posts type 0 through `0x14bc`; hub `0x1466` → `0x1420` → `0xd024` → `0xcab8`; selected drain call at `0xcb4e` → `0xc280` | Normal queued acquisition is hub work, not inline timer work |
| Health motion consumer | qc_app call `0x136e` → `0xcd60` → selected algorithm feed `0x1d9d8` | Consumer is qc_app, separately scheduled from hub publication; this does not prove algorithm timing or steps/sleep continuity |
| Selected optical sample worker | Type-3/subtype-0 hub dispatch `0xdd38` → `0xf7a8` → `0xf774` → `0xf308`; selected acquisition reaches `0x10610` → `0x11994` | This worker/read path is hub work. A proposed `wop_read` call inherits that context only if attached to this path; not every possible reader/producer is closed |
| Ordinary optical enable/disable | Post wrappers `0xdd04` / `0xdcea` → `0x14bc`; hub → `0xdd38` → `0xf824` / `0xf8da` | Hub consumes `(3,1/2,mask)` asynchronously. Producer, queue acceptance, bus write and physical completion are different boundaries |
| Checked unified STOP | Candidate `wb_stock_stop_writes` uses existing bus mutex; stock reference `0x10eaa` → `0x12496` → `0xee12` → `0xdbca` → `0xdb42` | No actual unified caller task is bound. STOP may block/poll with interrupts enabled; neither ISR execution nor a whole-operation interrupt mask is allowed |
| Current-settings fresh resume | qc_app call `0x137a` → scheduler `0x1202` → selected original job starts | Natural selected starts originate in qc_app. No preservation-safe fresh-job preparation/resume callback or serialized settings revision owner is implemented |

The existing app event value 2 instead drains its eight-byte message queue and
calls `0x6e9a` at `0x8c8`. That separate branch does not close the ROM callback
edge either. Read-callback ABI and GATT registration/resource ownership are
separate audits; no capability is inferred from their table or pointer shapes.

The shared FIFO reader is **not exclusively hub-owned**: direct calls to
`0xc280` also occur from configuration `0xc538` and raw reader `0xcc32` at
`0xcc46`. The latter is used by raw timer reporting and ordinary optical motion
work (`0xee50`). Emulator-only raw retirement does not remove those entries
from installed stock, and shared Health readers remain preserved. The bus
mutex does not serialize an entire FIFO operation, all cursor mutations or
the separately scheduled Health consumer. See [motion](UNIFIED_STOCK_MOTION.md),
[FIFO](UNIFIED_FIFO_EVIDENCE.md) and [raw retirement](UNIFIED_RAW_RETIREMENT.md).

## Timer context, optical START producers and consumers

Captured ROM task creation `0x10b14` calls `xTaskCreate` at `0x10b3a`, supplying
entry `0x10a96`, name literal `Tmr Svc` at `0x10f04`, priority 6 and output slot
`0x20147c`. Its stack argument is configuration halfword `[0x200364+0x2e] >> 2`;
this code alone does not supply that live configuration or prove 1024 bytes.

That entry calls timer-expiry processing `0x10e4e` at `0x10aa8`, then command
processing `0x1099e` at `0x10aac`. The selected expiry path calls the timer's
stored callback directly at `0x10ef2`. A negative deferred message calls its
stored function with stored context/ticket directly at `0x109b2`. These visible
call chains establish timer-daemon context for those selected invocations;
queue/list internals, scheduling latency and complete lifetime/drain semantics
are not thereby proved. Existing [captured-ROM witnesses](UNIFIED_STOCK_INTEGRATION.md)
execute selected marshalling/dispatch with explicit RTOS boundary substitutes.

The optical producer domains are distinct from the hub consumer:

- **qc_app scheduled producer:** `0x1202` calls HR start `0xe420` and the other
  reviewed job starts. HR posts enable through `0xdd04` at `0xe458`, then uses
  `0x3e04` at `0xe468` for its timer. This is not an inline hub start or physical
  RUN completion. Job-state writes occur in the producer before/after posting.
- **Timer producer:** registered realtime callback `0x4722` selects `0x4518`
  for mode 6; its delayed branch at `0x45d6` posts enable through `0xdd04`.
  Thus a late timer callback can produce another hub RUN request independently
  of qc_app's initial request. Scheduled Health callbacks also mutate working
  state, cancel and publish; they are not merely timer acknowledgments.
- **Direct timer-side bypass:** registered brightness callback `0x3ac4` calls
  `0xf812` at `0x3af4/0x3b06`, reaching lower optical driver `0x11246` outside
  normal hub ownership. Retiring the initial command alone does not fence an
  already-dispatched callback. This is a stock path; retirement is not installed.
- **Other producer boundaries:** fast GATT handlers can post enable from their
  unknown callback context. GPIO/software producers `0xd8f0/0xd9f8` post
  untagged `(3,0,0)` work. Their complete interrupt registration/priority and
  every indirect caller are not closed by this map.

Ordinary hub enable `0xf824` and remaining-owner disable `0xf8da` can invoke
normal start request `0xf128`. Neither a timer barrier nor a cleared ownership
mask fences all these domains. The queued message lacks original job identity;
assigning the current ticket at dequeue mislabels old work. Existing witnesses
show late enable after STOP and late subtype-zero result stores, under explicit
bus/algorithm fixtures. See [lifecycle](UNIFIED_HEALTH_LIFECYCLE.md),
[optical dispatch](UNIFIED_OPTICAL_DISPATCH.md) and
[producer inventory](UNIFIED_HEALTH_ADAPTER.md).

## qc_app cadence is not a supervisor guarantee

Initialization `0x13ce` creates semaphore `0x208c90` with count arguments 1/1.
At `0x1356..0x135c`, qc_app supplies `0xffffffff` to declared `os_sem_take`
ROM `0x13360`. On success it processes commands, Health samples, bookkeeping,
minute scheduling and other work, then returns to the same indefinite wait.
There is no periodic timeout or unconditional delay in the loop itself.

Wake helper `0x1178` loads that same handle and calls declared `os_sem_give`
ROM `0x13388` at `0x1182`. Concrete callers include command enqueue `0x4ce4`
and the normal hub acquisition continuation `0xcb58`. Selected clock/event
code `0x19d2` adds `60 - (scheduler_seconds % 60)` to pending time `0x209cac`
and signals at `0x1a00`; this is not evidence of a 1-second supervisor wake.
No selected signal proves a maximum interval when traffic or motion is absent.

Service time after wake is also unqualified:

- Command consumer `0x657c` repeatedly compares its read cursor with the live
  producer cursor at `0x66a4..0x66b2`, without a fixed per-pass quota. A ten-slot
  ring is not a bounded drain duration while other contexts continue posting.
- Selected queued mode change `0x6650` → `0x162a` calls `os_delay(100)` at
  `0x1644` and can repeat a delay at `0x1676`, comparing a clock delta with 1000.
  Those concrete waits disprove treating every handler as a short leaf; they
  do not establish a physical worst-case bound or a qualified clock conversion.
- `0xcd60` snapshots producer/consumer cursors for its local sample loop, but
  calls algorithm and other stock code. A finite loop under valid cursor
  invariants is not a measured worst-case execution time for all its callees.
- `0x1202` consumes pending seconds, reconciles time and calls optical and
  non-optical work. Existing tests substitute clock, timer, queue and other
  boundaries; neither whole-loop latency nor absence of deeper blocking is
  proved. It does not replay every skipped due minute after a delayed delta.

`wd_tick` checks the 1000 ms wire receive/reply expiry and advances adapter
timeouts; the mode controller uses 3000 ms action deadlines. They only act when
called with a valid current clock. Calling them once per qc_app iteration, or
only on GATT traffic, supplies no expiry-service bound while idle or blocked.
Moving blocking STOP into Tmr Svc would delay other timer callbacks and still
would not meet `wc_owner`'s one-owner contract. No such move is proposed.

## Owner selection and finite next work

qc_app is a reasonable **candidate to evaluate**, because selected scheduling
and Health consumption already occur there. It is not an approved choice.
app has an unresolved ROM callback edge; hub does not own settings, timer
callbacks or Health consumption; Tmr Svc is shared and has no demonstrated
budget for blocking unified orchestration. No one task already serializes them.

The smallest remaining owner decision needs: a finite ROM-to-GATT context/
lifetime contract; an explicit bounded handoff for commands, disconnects,
charging and immutable original receipts; actual wake/deadline servicing and
worst-case blocking analysis; and admission/result/settings synchronization
across qc_app, hub, timer and interrupt domains. Candidate coordinator entries
require thread mode with interrupts enabled, including after blocking callees.
Do not invoke the entire minute scheduler as a resume helper or hold PRIMASK
across STOP. Fresh current-settings preparation and monotonic revision ownership
remain separate obligations, as the [writer audit](UNIFIED_SETTINGS_WRITERS.md)
and [coordinator contract](UNIFIED_COORDINATOR.md) explain.

Finally, sampled A5 paint is neither a strict historical SP-depth bound nor
future headroom. The V2 optics-off samples cannot budget stock Health plus
new callbacks, their nested ROM callees, interrupts or DLPS/reset lifetime.
No task stack, persistent allocation, supervisor or release gate is approved.

## Bounded checks performed

Read-only Capstone checks verified 18 selected stock BL targets, all three task
name literals, captured timer-task entry/name and selected callback instructions.
The stock/capture/window hashes above matched. Eight existing focused ARM tests
passed in 0.11 s: hub creation, asynchronous post/receive, late enable after
STOP, failed-bus disable, subtype-3 no-op, selected real job starts, stateful
minute dispatch and delayed-time non-replay. These exercise explicit RTOS/
hardware fixtures, not a live scheduler or elapsed-time bound; this is not a
full regression run. No generic analysis framework or executable file was added.

The eight existing node IDs, relative to `tests/`, are:

```text
test_fwstock_binding.py::test_hub_creation_records_real_queue_and_task_priority
test_fwstock_binding.py::test_actual_post_then_receive_then_dispatch_is_not_inline
test_fwstock_binding.py::test_actual_late_enable_after_stop_restarts_without_generation
test_fwstock_binding.py::test_actual_hub_stop_can_clear_flags_with_failed_i2c
test_fwstock_binding.py::test_optical_hub_subtype_three_is_noop_not_completion
test_stock_schedule_settings.py::test_whole_minute_dispatcher_is_stateful_not_a_resume_or_capability_probe
test_stock_schedule_settings.py::test_stock_tick_does_not_replay_due_minutes_skipped_by_a_late_elapsed_delta
test_stock_schedule_settings.py::test_real_start_paths_use_real_current_enable_bits_not_boolean_fixtures
```
