# Timer resume prerequisites and completed fixed code read

2026-09-23. **The separately coordinated fixed code read completed.**
Health remains the unified boot/default, Gesture opt-in, installed V2 unchanged.
No sensor-start, flash, deployment, commit or push. CD01 bookkeeping effects
remain; the single diagnostic connection ended with verified disconnect.
This work does not complete health resume or authorize a firmware image.

## Completed capture and off-ring review

Fresh user confirmation preceded the one prepared read. It completed **180
matching CD01 transactions**: 452 new bytes twice, known STOP code twice,
identity/configuration/idle prerequisites and postchecks. Disconnect verified;
no unexpected traffic or retry. Request/reply time was 24.477 seconds, excluding
connection/disconnection. Raw evidence is archived under
[`rom-timer-resume/`](../firmware/research/2026-09-23/rom-timer-resume/README.md).

- Capture SHA-256: `b09002f65a8b1ff4dbe1ba0aea54c79e2043a4f0ebd0683921229a731ae74064`.
- Transcript SHA-256: `7c09280e5ae252dbe3fdeee392268bc3fb6865b8f0e4a1964b993c0b8d1e5ddb`.

The standalone `tests/test_fwrom_resume_archive.py` verifies raw hashes and
packet checksums/order, replays all 180 exact requests/replies through the
unchanged reader, and reproduces the saved capture. This new evidence/test is
outside the preceding 2049-test build manifest. All 209 prior-build hashes were
checked again before the read; 540 selected preflight tests passed. Firmware
sources, both ARM ELFs and construction gates are unchanged.

Initial disassembly findings below were **off-ring code inspection**. The later
execution section distinguishes what is now executed from explicit substitutes;
no timer operation was performed on the ring.

| Captured code | New evidence and limits |
|---|---|
| Create wrapper `0x13634`; start `0x13670`; restart `0x13694` | Captured literals at `0x137ec/f0/f4` point to optional hook slots `0x201644/48/4c`. A nonzero handled result returns a separate result byte; otherwise the wrapper calls its default. No new hook slot was read. The older zero STOP/DELETE hooks do not establish these values. |
| Create default `0x13f9e` | Checks the output-slot pointer, callback, nonzero period, an external inhibit bit and an initially empty slot; calls `xTimerCreate` at `0x10b5c`, stores its returned handle, and reports success only for nonzero. Object allocation/lifetime and callback freshness are not proved. |
| Embedded data `0x14028..0x14034` | Words are `0xe000ed00`, `0x200364`, `0x200464`, not executable instructions. Create/start read the inhibit byte at `0x20037d`; create also reads the word at `0x200484`. Neither data location was read on the ring. |
| Start default `0x13ff6` | A selector at unread `0x14238` chooses symbol-mapped task tick + command 1, or ISR tick + command 6 with a wake flag. Queue wait is zero; only result exactly 1 succeeds. Selector/tick bodies and the later wake-register literal remain unread. |
| Restart default `0x1405e` | Uses the same unread selector and command 4 or 9, not START/RESET. It does not independently reject a zero requested period. It contains two calls to unread `0x3f97a` and wrapping add/subtract instructions; missing config literals at `0x1424c/50`, live configuration and callee semantics prevent a verified milliseconds-to-ticks conversion. |

The two calls at create/restart are consistent with a round-up conversion if
`0x3f97a` implements unsigned division, as earlier synthetic fixtures assumed;
that assumption is **not newly proven by this capture**. Do not promote it to a
measured tick rate or assume overflow/zero requests are safely handled. The
restart default's missing literal bytes must not be filled in by analogy with
create. Kernel rearm hazards described below still apply.

No returned pointer was followed. Missing bodies/literals, current hook/config
values, owned timer lifetime, serialized fresh-job admission and real physical
STOP/resume remain evidence gaps, alongside memory/recovery and motion/steps/
sleep continuity. The user may reopen clients; this session is finished. Any
further device action needs a separate bounded plan and fresh coordination.

## Captured creation/start/restart execution — subsequent off-ring work

`tests/test_fwrom_resume_execution.py` now executes the captured wrappers and
default bodies with the previously captured native allocator/creation code.
The original archive is pinned by hash; unknown data and instructions are
rejected unless a test explicitly admits a named substitute. No firmware C,
installed image, timer API or hardware hook is changed by these tests.

### What the instructions establish

- All three optional-hook wrappers preserve their incoming arguments for the
  fallback, including all six create arguments and the stack arguments. Tests
  deliberately clobber caller-saved registers in a declining hook. A handled
  hook returns its separate byte (including 255), not the hook's handled flag.
  These are synthetic hook contents, not current live hook-state observations.
- Create's captured default rejects null output/callback, zero requested
  period, the inhibit bit and an occupied output slot. The occupied-slot check
  occurs **after** the two conversion calls. A null native result remains a
  failed create; no successful handle is fabricated.
- Native allocator `0x10774` removes the free-list head and marks its allocation
  bitmap/count. It refuses an empty free list or an already-marked head. This
  behavior uses synthetic, mutually consistent metadata under a mocked critical
  section; it is not proof of actual pool ownership or protection against reuse.
- Native `xTimerCreate` at `0x10b5c` replaces name, period, job ID and callback,
  clears active status and treats any nonzero reload argument as autoreload.
  **Creation does not enqueue START.** The list-item initializer is a substitute;
  tests deliberately preserve its sentinel bytes rather than claim a completely
  initialized/list-safe object from instructions that were not executed.
- **A zero native period asserts after allocation.** Before entering the unread
  assertion handler, the captured code consumes the free-list entry, increments
  its count, sets its bitmap bit and clears its status byte. It has not replaced
  the old callback or returned the handle to the vendor wrapper. There is no
  rollback before that boundary. The handler's eventual recovery/reset behavior
  is unknown; this is not a claim of a measured permanent leak on the ring.
- Captured start/restart defaults distinguish the selector's zero/nonzero
  branches, use commands 1/6 or 4/9 respectively, wait zero and accept only queue
  result **1**. Results 0, 2 and `0xffffffff` are failures. The wake-flag path can
  request a yield even when the queue reports failure, so a yield is not an
  acceptance receipt. Neither default clears the caller's handle.

### Conditional timing hazards, not established hardware conversion

Under the explicitly assumed unsigned-division helper and synthetic 100-tick/s
configuration, actual create/default arithmetic maps 17 requested units to two
native ticks. Requests `0xfffffff7` and `0xffffffff` wrap the add/subtract to a
zero quotient; the combined default/native chain then consumes an allocation
and enters the assertion handler without publishing a handle. The restart
default can also submit command 4 with zero after those large inputs or a zero
input and return success when its mocked enqueue accepts it. The earlier actual
daemon test establishes that native CHANGE(0) asserts after partial mutation.

These complete conditional paths identify required input/conversion guards,
but do **not** prove the unread helper implements division, the missing restart
literals match create's, or the ring uses the synthetic tick configuration.
No production range or milliseconds conversion was inferred from them.

### Explicit unproved boundaries and next binding requirements

The context selector, task/ISR ticks, unsigned division, optional hooks, queue
submission, list-item initialization and diagnostic helpers are substitutes.
Critical-section bodies are available in the older capture but are intentionally
out of scope here: no concurrency, scheduling or pool-lifetime proof is claimed.
Creation uses an existing synthetic queue; lazy queue creation is not executed.
The three missing restart/yield literal words are separately marked fixtures.
Negative tests prove absent hook-state RAM and a missing restart literal fail
closed instead of reading zero-filled mapped memory.

A real adapter still needs validated nonzero/bounded **native** periods, owned
timer objects throughout create/enqueue/daemon use, fresh job provenance,
serialization against old work, and independent acceptance/completion handling.
Checking a nonzero requested millisecond value alone is insufficient under the
demonstrated conversion hypothesis. Hook selection/helper/literal/configuration
evidence must be closed before binding the vendor API; no new diagnostic read
is prepared or authorized by these emulator cases. The physical, recovery,
steps/sleep and construction gates remain closed.

### Separately prepared next diagnostic

The later [support-code/state diagnostic](UNIFIED_SUPPORT_READ.md) completed on
a separately requested retry: 284 matching transactions, repeated values and
postchecks, verified disconnect. Its earlier zero-command discovery failure
remains historical. The helper/context and flash/OTA literals are now captured,
along with 17 fixed non-secret state bytes. Rate configuration is 100 and the
create hook is **nonzero (`0x205c01`)**; start/restart hooks are zero in this idle
snapshot. The target was not followed. New execution replaces the division/
context/literal assumptions below, but actual hooked creation remains unproved.
Direct default tests must not masquerade as the live wrapper path. No physical
timing, pool ownership, immutable hook state or recovery approval follows.

Subsequent [separately captured hook execution](UNIFIED_CREATE_HOOK_READ.md#captured-body-execution--2026-09-24)
runs that actual wrapper/hook/default/allocator success path off-ring, retaining
synthetic pool/list/critical boundaries. Failed creation with an empty handle
instead reaches unread `0x111a6`; it cannot be treated as a safe failure return.
The prior direct-default tests remain scoped to the earlier capture. No
production resume API or physical timing/ownership/recovery gate was enabled.

## Captured kernel behavior now executed

`tests/test_fwrom_rearm.py` executes selected instructions from the already
archived, twice-matching 6076-byte ROM capture. It does not read new device data.
The capture SHA-256 remains
`d02cc3582a789d933e1be09fa1bbec05ade7a193508418149f145dc12df3b05b`.

- `xTimerGenericCommand` at `0x108e0` marshals START/RESET/CHANGE commands and
  propagates queue return values unchanged. Enqueue does not mutate the timer.
  Like STOP, these cases do not check its allocation bit. Owned lifetime must
  be established independently before calling this assertion-prone API.
- Captured daemon CHANGE case `0x10a3e` sets the active bit and stores the new
  period before checking for zero. Zero enters the assertion handler after
  those partial mutations. This does not prove the unread vendor wrapper
  accepts zero; a future direct native binding must not submit it.
- Valid CHANGE schedules from the daemon's current native tick, through the
  actual insertion helper `0x108ac`. Positive and wraparound fixtures exercise
  active/overflow list selection. Neither callback pointer nor timer ID changes.
- START/RESET cases at `0x109e4` use the message's timestamp and retained period.
  A stale command can invoke the **old callback immediately inside the daemon**,
  before any later barrier. The one-shot fixture demonstrates this without
  claiming the old callback's sensor/result work was executed or safe.

Queue, tick-count, linked-list bodies, compiler switch helper and the callback
body are explicit substitutes. The switch substitute reads the actual captured
table. This is native-tick semantics, **not a measured tick rate or a proof of
millisecond conversion, RTOS timing/list integrity or physical acquisition**.
No production rearm function was added: rearming an old object is not a fresh
job, does not replace its identity, and cannot supply a resume receipt.

## Why the captured code was needed

Stock app wrapper `0x3e04` calls ROM create/start/restart entries at
`0x13634/0x13670/0x13694`. Their implementations and potential override selection
were not in the earlier STOP/DELETE capture. The known kernel cannot establish
the wrapper's time conversion, object identity/lifetime or error handling.
The completed plan obtained those fixed code neighborhoods for offline review rather
than assuming the missing ABI. It does not read live hook-state RAM or follow
any newly returned function pointer; those may remain separate evidence gaps.

## Exact completed diagnostic plan

New implementation: `whip/fwrom_resume.py`, selected only by
`probe.rom_read --timer-resume-code`. The flag means **read code about resume**,
not execute a timer operation. It is mutually exclusive with every prior plan
and requires fresh confirmation that all other ring clients are closed, with
no stream or DFU active.

Before connection, pin original25Hz/V2 images, the CD01 dispatcher, ROM symbol
map and previous STOP archive. On connection, check the exact expected BLE
identity/DIS and repeat the existing sampled image, idle, RAM/flash configuration
and bank0 descriptor checks. Sampled identity is not full image attestation.
Repeat the known application ROM UUID twice and compare the 72-byte STOP/DELETE
wrapper capture **twice** before admitting any new window.

| Fixed new window | Bytes | Boundary basis |
|---|---:|---|
| `0x13634..0x136bc` | 136 | Exported create/start/restart through, but not including, exported STOP |
| `0x137ec..0x137f8` | 12 | Fixed literal neighborhood immediately before STOP/DELETE; now captured hook-slot addresses, not live hook values |
| `0x13f9e..0x140ce` | 304 | Exported `osif_timer_create` to, but not including, the captured STOP default entry |

Total **452 new bytes**, each read twice with exact equality required. These
bounded neighborhoods are not a claim of complete function/callee closure.
Then repeat fixed RAM/flash configuration and idle postchecks and disconnect.
There are exactly **180 CD01 transactions** including all prerequisites and
postchecks. The maximum frame data length remains 14 bytes.

No reading of key fields, OTP, hardware registers/FIFO or new hook-state RAM;
no sensor start, target-code execution, firmware operation, pointer following,
retry or reconnect. CD01 retains its previously audited connection/timer/
activity bookkeeping effects: **data read does not mean zero device effects**.
A timeout, foreign/malformed/duplicate response, changed known code/repeat/
postcheck or unconfirmed disconnect poisons the session. No success JSON is
published unless the exact budget and disconnect both verify.

After a successful capture, stop device work and review the returned bytes
off-ring. Unknown targets remain unknown; neither the code's presence nor a
matching repeat approves its execution, new live reads or firmware flashing.

## Preflight

The focused reader/ROM/legacy-reader set passed **430 tests, zero skips**.
The 100 new cases comprise 70 diagnostic cases and 30 captured-kernel witnesses.
This count overlaps the full guarded suite; do not add it to the full total.

Diagnostic checks cover exact phase/chunk allowlists and ordering, both known
STOP reads, source/identity/configuration failures, six transport faults in
each new/known-STOP phase, changed repetitions/postchecks, all CLI plan conflicts,
disconnect/late-traffic failure and one-use poisoning. Arbitrary values shaped
like MMIO, hook-state or other disallowed addresses in the synthetic literal
reply are archived but never followed. Each injected phase-fault test proves
its intended phase was reached.

Actual original25Hz/V2 CD instructions copy the first/last chunk of each fixed
new window under selected state fixtures; inspected bytes are not executed.
All radio/ROM payloads in the read-plan tests are synthetic except the pinned
prior STOP witness. An early preflight failure exposed the fake radio's generic
STOP bytes; the fixture now uses that exact prior witness, and fault tests
explicitly reject passing because of an unrelated prerequisite failure.

Fresh client coordination was obtained before the completed diagnostic. Its
result supplies code, not physical STOP/resume, memory/recovery or motion/model/
steps/sleep continuity. All construction gates remain closed.

## Latest guarded execution build

`firmware/unified/build-20260923-resume-execution-v1/` passed **2129 tests in
182.19 seconds**, zero skips/failures/errors/xfails. All **213 hashes** verified:
143 inputs, 67 artifacts, three reports. The actual capture/transcript and both
new test modules are now snapshotted inputs. All 80 new cases executed: one
archive replay and 79 wrapper/default/native-creation cases. The focused set
passed 184 overlapping tests, not an additional count.

Manifest SHA-256:
`0f9616dfb830164ecc51f8b3f8d02754c94868522bf134faf32f895e60300cb9`.
Both ARM ELFs are unchanged from the earlier preflight/settings builds:

- Test ELF: `2e66a8133a753103ff412dd959d42d7e39bb177fc2c2120aaa344b9426a67b7e`.
- Stock-address ELF: `2c75d78867394ac4c9beb9ca18b3e4f5dca58c701884b64b92a65ac5720013e6`.

No firmware C, stock bytes, compiler flags, memory allocation or device state
changed. Components occupy 9272 configured bytes, with 248 remaining; dispatcher/
frame/fence totals 796 bytes. This is not complete integration fit or approved
RAM. `flashable`, `stock_linked`, `hardware_access` and `ram_ownership_verified`
remain false. No new simulator/phone/legacy-regression run, flash, commit or push.

## Earlier full preflight build

`firmware/unified/build-20260923-resume-code-preflight-v1/` passed **2049 tests
in 160.49 seconds**, zero skips/failures/errors/xfails. All **209 hashes** verified:
139 inputs, 67 artifacts, three reports. The 100 new cases are included, not an
additional count. Manifest SHA-256:
`d7f4b860a44a7fe7b9b6c8d4bd0a03eae3020d596a38707fdb37fcad256d5f27`.
Both ARM ELFs are byte-identical to the prior stock-settings build; no firmware
source, compiler flags, stock bytes, memory allocation or placement changed.
Components remain 9272 bytes, leaving 248 configured bytes, with no full-fit or
RAM/recovery approval. No new Swift, simulator or separate legacy-regression run.
