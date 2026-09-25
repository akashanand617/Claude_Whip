# Unified stock-motion implementation and bounded execution proof

Status: 2026-09-22 research session. **Offline components built; no installable
unified image, no ring/phone access, no flash, no physical health claim.**
Health remains the intended default. Gesture mode is temporary; actual optical
health measurements cannot remain continuous while their emitters are disabled.
This work concerns sharing motion samples, not restoring optical measurements.

Later integration and expanded evidence are in
[UNIFIED_WORKFLOW.md](UNIFIED_WORKFLOW.md): the runtime now links at artificial
test addresses and the guarded suite passes 234 tests. The original component
counts below remain historical; none of these artifacts is stock-linked/OTA.

## What was implemented

- `firmware/unified/sample_tap.{c,h}`: a separate 32-sample copy queue, no heap,
  no stock-memory pointer, no NVM, no sensor/timer operation. Session IDs cannot
  be reused during a boot. Acquisition IDs must advance by exactly one, allowing
  uint32 wrap. Failed/unverified I2C, lost/out-of-order batches, queue overflow
  and output-sequence exhaustion invalidate Gesture and discard pending output.
  Late callbacks from an earlier session cannot invalidate a newer session.
  The real adapter must react to a current-session fault with controller cleanup;
  the queue itself cannot acknowledge physical STOP or resume Health.
- `whip/fwcontinuity.py`: executes original, unmodified stock Thumb instructions
  for FIFO append, raw reads, active Health consumption and the active wake
  path. Unreviewed execution/unmapped access/instruction-budget exhaustion fails.
  Health algorithm calls are observed, not evaluated. No BLE dependencies.
- `whip/fwunified.py`: fingerprint-bound stock motion addresses and the newly
  identified stock DFU timer. Unknown/mutated stock images receive no map.
  The unconditional OTA construction refusal remains intact.
- `probe/unified_build.py`: repeatable ARMv6-M objects, ELF inspection, stack
  reports, input hashes and a test manifest. Builds each object twice and demands
  byte equality. **Does not link into stock or generate an OTA container.**

## Exact stock identity and addresses

Input: `firmware/rt02cr-stock-3.12.02.bin`, 138016 bytes; SHA-256
`b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0`.
Runtime address = file offset + `0x825fb0`. Do not apply these offsets to V2,
the 25 Hz base, or any other image. The archived `fwmap.py` helped navigation;
its heuristic function boundaries were not treated as proof.

| Meaning | Stock file offset / RAM address |
|---|---|
| Driver state | RAM `0x20bd98` |
| Sample-state block | RAM `0x20bdc8` |
| Producer byte cursor | RAM `0x20bdd0` (sample state +8) |
| Health byte cursor | RAM `0x20bdd2` (sample state +10) |
| Sample buffer | RAM `0x20bdd4`, 492 bytes / 82 six-byte samples |
| FIFO drain and buffer append | file `0xc280` |
| Producer cursor publication | file `0xc4e8` |
| Raw reader | file `0xcc32` |
| Active Health consumer | file `0xcd60` |
| Health algorithm sample feed | file `0x1d9d8` |
| Normal wake | file `0xcb5e` |
| Wake discards pending health backlog | file `0xcbaa` |
| Stock DFU reassembly timer — preserve | file `0x80f8`, bytes `7d21c900` |

The STK ID `0x23` path reads FIFO status register `0x0c` then sample data from
`0x3f`, capped at 32 samples per drain. These are code-observed accesses; the
test fixture is not a complete STK8321 peripheral model. The Health consumer
passes signed `(second word, first word, third word)` to the algorithm. It skips
samples whose third word is zero or -1; tests retain, not change, that behavior.
These are driver words, **not an allocation of the future BLE wire axis order**.

Stock main-loop calls at `0x1366` / `0x136e` reach the command dispatcher and
Health consumer. Merely finding these calls does not prove serialization with
the driver task, timer callbacks, interrupts or DMA.

## Findings reproduced with actual stock instructions

1. **Raw reads do not consume the separate Health cursor.** FIFO appends and
   raw output copies preserve pending Health samples, including buffer wrap.
   Health receives the same sample sequence as the no-Gesture baseline in eight
   randomized batch schedules. This covers initialized, active, serialized
   operation with less than 82 samples pending; not arbitrary scheduler delay.
2. **Do not wake an already-active sensor on every transition.** Stock wake
   `0xcba8–0xcbaa` assigns the producer cursor to the Health cursor, even when
   the timer is already active. A five-sample backlog then disappears. The
   future ownership adapter needs an active-state guard and reviewed idle veto,
   not unconditional reuse of the normal wake routine.
3. **Raw success is not freshness.** An active raw read can return status 20
   and repeated cached values without a new sensor sample. The inactive path
   also repeats the last sample, returning zero. Ten empty FIFO reads take the
   stock chip-probe/reinitialization path, which the bounded harness refuses
   to fake. Do not drive a rapid timer from this cached reader.
4. **A full buffer lap aliases to empty.** 32 + 32 + 18 samples without Health
   consuming produces equal head/tail indices and no Health inputs. Therefore
   the pending bound is strictly **less than 82**, not less than or equal.
   These byte cursors alone cannot prove no overrun. Real scheduling/source
   counters and physical FIFO overflow handling still need review.
5. **A failed FIFO data read can still publish samples.** Stock clears scratch
   memory, calls the data-read helper, then ignores its result at `0xc39e`.
   Injected read failure advances the producer cursor and exposes zero samples.
   The Health third-word filter drops those samples. A changed producer cursor
   alone must not mint a valid Gesture sequence: the acquisition hook must
   independently establish I2C success and known sensor state/cadence.
6. **An independent Gesture copy can fail without changing Health delivery.**
   An observer at the actual stock publication instruction feeds the compiled
   native C tap. Across 120 batches / 2,400 samples, Health receives the same
   sequence whether Gesture consumes everything or fills its queue and faults.
   This is stock ARM execution plus a **host-native C observer**, not a linked
   ARM hardware adapter or a proof of zero timing overhead.

## Tests and build measurements

Combined run: **95 passed, 0 failed, 0 skipped**:

- 40 selected-stock execution tests (20 cursor/batch combinations, eight
  interleavings, cached output, wake/backlog loss, full-lap loss, signed-axis
  filtering, I2C faults, strict execution guards and two C-observer scenarios).
- 52 existing controller/stock-gate tests, including native ASan/UBSan stress
  with 1,280,000 randomized events, 20,000 entry/return cycles and token exhaustion.
- Three sample-tap/build tests: native ASan/UBSan exercises 10,000 sessions and
  over three million samples, counter wrap, stale callbacks, queue overflow,
  malformed acquisition and cleanup ordering; both C modules compile for M0+.

Apple Clang 21, `--target=armv6m-none-eabi -mcpu=cortex-m0plus -mthumb -Oz`:

| Object | `.text` | `.ARM.exidx` | Largest reported local stack frame |
|---|---:|---:|---:|
| mode controller | 590 bytes | 72 bytes | 24 bytes |
| sample tap | 340 bytes | 40 bytes | 40 bytes |

Both objects rebuilt byte-identically. They still contain relocations and
unresolved `__aeabi_memclr4` / `__aeabi_memcpy` dependencies. The tap structure
is 404 bytes in the native test ABI, **not a reservation of ring RAM**. Local
stack frames do not include call-chain, ROM, RTOS or interrupt stack costs.

Final passing artifact directory:
`firmware/unified/build-20260922-continuity/` (ARM objects, stack reports,
manifest and JUnit report; build output is gitignored). This run includes the
additional mock-RAM and exact producer-store guards. An earlier passing build
also exists at `/tmp/whip-unified-build.m1E9lk/offline-build/`.
Build artifacts are disposable; source and reproduction instructions are the
durable record. Later proof reruns must use a new directory and their own
manifest; do not treat an old manifest as a certificate for changed source.

Broader existing firmware/container/identity/optical-build/DFU/protocol tests,
plus controller and sample-tap tests: **223 passed**. This overlaps the 95-test
proof suite; the totals must not be added as distinct tests. `git diff --check`
also passes. No iOS source or deployed model was changed in this build pass.

```sh
# In an isolated Python environment:
python -m pip install -r requirements-firmware-proof.txt
python -m probe.unified_build --output /tmp/whip-unified-offline-new-directory
```

The emulator is pinned to Unicorn 2.1.4, ARM M-class/M0 mode. On this Mac the
JIT traps during initialization inside the sandbox; the approved outside-sandbox
run succeeds. This permission is for host execution, not hardware access.

## Deliberate proof limits and remaining integration work

The emulator initializes copied stock data and synthetic active-driver state;
it does **not** execute full boot. It models successful/failing synchronous I2C,
ROM memcpy/memclr, an unplugged predicate, a sample-feed observation point and
a downstream aggregate boundary. It does not implement optical hardware,
step/sleep algorithms, wear state, timers, charging transitions, interrupts,
RTOS races or NVM. Its test RAM/stack/output addresses are arbitrary mock space,
never proposed real allocations. No numerical step/sleep accuracy was measured.

Before an installable image can be constructed:

1. Establish exact code/RAM/stack/heap ownership and ABI. Stock startup calls
   `update_ram_layout` at file `0x6ee` with `0x7000` / `0x7400`; their meaning is
   not yet established. Scatter-copy boundaries, unused-looking padding and a
   small object size do not establish safe space. Obtain the matching vendor
   memory/linker information or independently prove the entire relevant map.
2. Implement the real serialized ownership/idle adapter. Preserve the stock
   Health acquisition cadence, calibration, cursor and consumer servicing;
   prove the 25 Hz Gesture path without repurposing cached raw packets or
   starving Health. The new copy queue is **not a resampler**. Accelerometer
   always-active operation may itself change sleep behavior; investigate it.
3. Fence all optical and indicator start paths, cancel delayed work, and restore
   the current Health settings on exit. Prove step/sleep algorithm and storage
   continuity across transitions and day boundaries, not just sample delivery.
4. Allocate a collision-free command namespace after both queued and fast BLE
   dispatchers are audited. The queued dispatcher alone does not establish an
   unused opcode. Do not send speculative A1 commands to a legacy image.
5. Link and independently execute the actual candidate, audit every changed byte
   and protected range, then validate recovery and Health-first behavior on a
   matching spare with explicit flash approval. These 95 tests do not replace
   that gate or justify flashing the daily ring.
