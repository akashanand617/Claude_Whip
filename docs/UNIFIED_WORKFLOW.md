# Unified firmware workflow — 2026-09-22–23

This is the first, wholly off-ring workflow. The subsequent
[capacity/source/adapter follow-up](UNIFIED_WORKFLOW_2.md) records additional
component integration and a separately coordinated idle configuration read.

## Outcome and safety boundary

The Health-default runtime is now compiled, linked and executed as Cortex-M0
Thumb code in an emulator. Parallel audits also execute selected original stock
instructions and trace command dispatch. **This is still not an installable
unified firmware image.** No ring/phone connection, BLE command, deployment,
flash, allowlist change, commit or push was performed by this workflow.

Health remains the boot/default mode. Gesture is temporary and explicitly
requested. Genuine optical health measurements are allowed in Health; decorative
and raw-debug flashes are denied. Dark Gesture sessions cannot honestly promise
uninterrupted optical health acquisition. Steps/sleep continuity is the design
requirement, not yet a measured hardware result.

## Implemented and independently checked

`firmware/unified/runtime.{c,h}` now joins the asynchronous mode controller and
copy-only sample tap. It keeps one pending notification, rejects session/sequence
replay, requires successful transport acceptance before crediting a phone's
processed sequence, and clears queued output as soon as Gesture ends. Sampling,
queue or transport failure initiates the full stop/release/resume sequence;
it does not publish Health before cleanup completes.

Independent review found that draining an old backlog could otherwise renew
Gesture after the physical source stopped. The fix checks both source age and
the acquisition age of each queued/pending sample. `wr_offer` requires the
oldest physical acquisition timestamp in its batch; a later callback timestamp
is not acceptable. Age must be below 250 ms, matching the app's bounded-freshness
contract. This number is a software requirement, **not a measurement of stock
FIFO cadence**. A real adapter must provide the timestamp and timely ticking.

The linked proof uses code address `0x01000000` and synthetic RAM; those are
deliberately not ring placement choices. `whip/fwthumb.py` runs the actual
compiled code, validates ELF/Thumb identity, checks callee-saved registers,
stack restoration, context canaries, permitted code/read/write spans and
instruction budgets. Test-only memory helpers are compiled implementations,
not substituted ROM results. Randomized tests explicitly enter Gesture and
assert active sample/send/renew/exit coverage; merely visiting idle states does
not count as integration coverage.

## What the parallel audits established

| Area | Established evidence | Still needed |
|---|---|---|
| Stock memory | Last 200 file bytes are a relocated boot/vector overlay, not padding. Startup reserves 28 KiB for app state/code; 1028 nominal bytes follow the last mapped overlay byte. | Exact live OTP/ROM-patch ownership, indirect-write closure, stack/heap reserve and actual OTA-bank capacities. No space approved. |
| Health motion | Stock health front end consumes each valid FIFO frame; selected raw reads preserve its cursor, while wake can discard backlog. | Actual sensor/FIFO cadence, reliable acquisition timestamps and serialized acquisition without changing algorithm timing/calibration. |
| Optics | Ownership changes can restart a remaining owner. Stock can clear state despite failed physical STOP writes. An uncancelled SpO2 timeout can synthesize a fallback value. | Cancel/drain timers and publication, fence all late starts, verify physical STOP and restore genuine measurements from current settings. |
| Command/transport | Unknown UART commands are not harmless probes; shared dispatch has stateful side effects. Unknown A1 parameters reset state. Stock TX queue has overwrite/drop paths. | Dedicated collision-free capability/control surface, reliable bounded transport, exact image/session/status correlation and hardware-work fencing. |

Detailed evidence and explicit mock boundaries:

- [Stock motion](UNIFIED_STOCK_MOTION.md)
- [Memory, overlays and SDK/ROM ABI](UNIFIED_MEMORY_AUDIT.md)
- [Health/optical lifecycle and false-measurement witness](UNIFIED_HEALTH_LIFECYCLE.md)
- [Command dispatch and transport](UNIFIED_WIRE_AUDIT.md)

Do not infer a 75 Hz physical stream or implement 3:1 decimation: the stock
accelerometer configuration includes FIFO subsampling and an unresolved mode
interpretation. An immediate `12` or `25` passed to the stock algorithm is a
clamped candidate-event parameter, not proof of acquisition frequency.

The fallback-value witness executes original stock timeout instructions with a
mock PRNG and aggregation boundary. It demonstrates values can reach that
boundary without a sensor result; it does **not** establish that those values
were ever saved or shown by this user's ring/app.

## Reproducible proof workflow

```sh
python -m probe.unified_build --zig /path/to/zig-0.15.2/zig \
  --output /path/to/new-output-directory
```

Use an isolated environment with `requirements-firmware-proof.txt`. The official
[Zig release index](https://ziglang.org/download/index.json) supplies
the linker. The macOS ARM64 archive used here has SHA-256
`3cc2bab367e185cdfb27501c4b30b1b0653c28d9f73df8dc91488e66ece5fa6b`.
On this Mac, Unicorn's JIT requires a scoped execution permission outside the
sandbox. This is local emulator permission, not hardware authorization.

The builder:

1. Fingerprints source, tests, stock input and tool executables before compiling.
2. Compiles every runtime/test-support object twice and links the artificial
   test ELF twice, requiring byte-identical outputs.
3. Snapshots artifacts before their next stage and rechecks between stages.
4. Clears inherited pytest/Python options, ignores repository test configuration
   and explicitly collects every test in the required suites.
5. Executes exactly those ordered test identities. Missing, deselected, skipped,
   xfailed or failed setup/call/teardown phases invalidate the run.
6. Records input/artifact/report hashes, complete test identities, stack-frame
   reports and explicit non-flashable status in an exclusively created manifest.

Snapshot ordering was independently reviewed and hardened: each object is bound
before linking, and execution reports are bound before parsing/validation.
These are content-drift checks, not a filesystem lock or hermetic toolchain.
They do not validate the correctness of every assertion or model actual ROM,
sensor timing, RTOS preemption, interrupts, retention or complete boot.

All three integrated guarded runs passed **234 tests, 0 failures, 0 skips** each.
The final run also supplied deliberately inherited `-k` selection and a missing
plugin: neither filtered or corrupted the workflow. A separate existing
firmware/protocol regression suite passed **206 tests**. Exact evidence is
recorded in the [safety-test follow-up](UNIFIED_SAFETY_TESTS.md).

Earlier manifests are historical evidence for their recorded input hashes, not
evidence for subsequently edited sources. Build folders are local/git-ignored;
the source workflow and tests are the reproducible deliverable. No `.bin` output
or option bypassing `whip.fwunified.build`'s construction refusal exists here.

## Remaining completion sequence

1. Resolve actual ring-specific bank configuration and RAM ownership. Use exact
   image/ROM identity, not another device's SDK flash map or apparent padding.
   The memory audit identifies configuration-data addresses for a future
   coordinated inspection; the existing UART memory-read transaction has
   dispatch side effects and must not be described as wholly non-mutating.
2. Establish the fresh 25 Hz producer without changing stock Health sampling.
   Prove successful I2C acquisition, timestamps, FIFO overflow behavior and
   serialization across hub/main/timer tasks.
3. Implement and prove the actual stock lifecycle/transport adapter, including
   cancellation/publication fencing and failure handling. Do not equate queue
   acceptance, a cleared software flag or a callback token with physical STOP.
4. Only with approved placement/hooks, build a stock-linked candidate, verify
   every changed byte and protected range, and execute its real integration
   under fault injection. Re-run stock Health and offline DFU regressions.
5. Request explicit approval for the reviewed candidate on a matching spare,
   with a tested restore path. Then validate Health first, mode toggles, fresh
   Gesture data, charging/disconnect, actual steps/sleep/optical acquisition and
   long-duration battery behavior. Receipt/checksum success is not boot safety.

The daily ring has not been used as a firmware-debugging target. The app's
production unified transport remains unattached and its capability lock remains
closed. A workflow pass is progress toward completion, not permission to flash.
