# Fixed ROM timer-code diagnostic

This record is chronological. The later internals and hook-state sessions below
supersede the initial capture's unread literal/default/hook statements. Scheduler,
callback-drain, recovery and physical STOP evidence remain incomplete.

The later [boot-reference comparison](UNIFIED_BOOT_REFERENCE.md) is a separate
182-transaction plan, not an extension of the ROM windows below. It matched the
ring's 52-byte non-secret header and 528-byte boot component to the pinned SDK
reference, with verified disconnect. That component validates factory/OEM
configuration, not a demonstrated application recovery path. No firmware was
flashed or sensor started; the older build records below remain historical.

2026-09-23. The user accepts considering a daily-ring test if risk is reduced,
requested diagnostics first, and freshly confirmed all clients closed with no
stream/DFU. This authorizes the bounded diagnostic below, **not a flash**.
No installable unified image exists; all production/construction gates stay shut.

## Selected plan and why

The next useful code boundary is timer cancellation: stock wrappers call ROM
`os_timer_stop` and `os_timer_delete`, but their implementations are absent from
the archived application. Reading their existing code may identify what they
actually call. It does not by itself establish callback drain, execution timing,
physical STOP, RAM ownership, boot recovery or steps/sleep continuity.

`probe.rom_read` / `whip.fwrom_read` admit only:

1. The existing 91-transaction prerequisite plan: sampled V2 identity, audited
   CD dispatcher, idle flag, repeated 16/48-byte non-secret configuration, and
   repeated 80-byte bank0 descriptor with postchecks. The new collector also
   requires the descriptor's exact previously captured SHA-256
   `d74c3afddf382c36dd4c566c539d2dcff16a22e0c7f525a9c1a342875cc4e12f`.
2. The application's ROM identifier at `0x82600c`, 16 bytes, twice. It must equal
   `f94c6b7e11c5eb118282f74a0c0cef5b`; this is header consistency, not full
   live-image or ROM attestation.
3. Exactly **72 code bytes at `0x136bc..0x13704`**, twice. These are byte
   addresses, not the odd Thumb entry pointers. The pinned symbol map locates
   stop at `0x136bd`, delete at `0x136e1`, and the following dump entry at
   `0x13705`. This is a bounded symbol interval, not a claim that every callee
   or external literal lies inside it.
4. Recheck the exact configuration and idle flag, unsubscribe, disconnect and
   verify the connection is no longer active before writing the success capture.

Total: **114 serial CD01 transactions**, maximum 14 data bytes each. No
returned code/pointer is executed or followed on the ring. No sensor/FIFO/MMIO,
generic OTP, key, absent-bank, backup-bank or arbitrary-address read is allowed.
There is no sensor start/stop, clock/settings change or firmware transfer.

The legacy CD dispatcher still changes activity/timer/connection-policy
bookkeeping; this is not a wholly side-effect-free transaction. The first
identity requests necessarily precede live code verification, a known bootstrap
limitation. The fixed sources and map are validated before connecting. Any
timeout, malformed/foreign/duplicate response, prerequisite mismatch, changed
repeat/configuration/idle state or unconfirmed disconnect aborts without retry.
The reader is one-use and closes its additional read permissions on every exit.

Collection has a 120-second deadline and the overall connection workflow has
a 180-second deadline. Cancellation initiates teardown; a timeout never proves
that disconnect succeeded. No successful capture is declared in that case.

## Preflight verification

Before device use, **218 tests passed, zero skips**, across `test_fwrom_read`,
`test_fwcapacity`, `test_fwcapacity_read`, `test_fwcapacity_cli` and
`test_fwcapacity_archive`, using the isolated proof environment.

New fake-transport cases exercise phase locking, exact transaction order,
forbidden adjacent/OTP/MMIO/bank addresses, wrong identity/configuration/map,
changed repeats, stale traffic, transport timeout, failed disconnect, exclusive
session confirmation and output preservation. Additional selected-instruction
tests execute the actual pinned original25Hz/V2 CD dispatcher/prelude/checksum
for each new chunk under states 0, 2 and 3. They use synthetic ROM source bytes
and a bounded memcpy mock: addressing is tested; physical ROM access and timer
behavior are not simulated. Target ROM instructions are never executed there.

The earlier 986-test unified build remains a separate historical input snapshot.
These new diagnostic files were not part of that build's 120 hashed inputs/
artifacts/reports, and its construction-policy wording has since changed.
Use the current build below; overlapping counts must not be added together.

The symbol map is ASCII assignments, not executable ROM or a factory backup:
`firmware/research/2026-09-22/rom_symbol_gcc.axf`, SHA-256
`6f5a59f6444c01328808ac148b9c60771410196ab3b57e08fc8ff90525934247`.

## Completed session

`data/rom-timers-20260923-01/` completed successfully and the connection was
verified closed. The user was told clients could reopen: **no continuing idle
authorization**. Exact files are archived in
`firmware/research/2026-09-23/rom-timers/`:

| Artifact | SHA-256 |
|---|---|
| `rom-timers.json` | `4290a08b6703c6b3e2ddf262285a28100368253ccff6a46b9116d31df039f16d` |
| `transcript.jsonl` | `fa32687d8e7f15a83c721ff2678f1fc9273d1245eea08b514bc42a9854962a78` |
| Captured 72 ROM bytes | `bf0174582ef92307490e0cdcf0802c912f6f36d8946aac5208f641ad81514e88` |

All 114 requests have matching, checksum-valid replies; CD01 was the only UART
command. Request-to-last-reply time was 15.46 seconds, excluding discovery and
connection. Both ROM reads match; the application ROM identifier, V2 sampled/
diagnostic code, descriptor, configuration and idle checks matched. No sensor,
FIFO, MMIO, firmware transfer, pointer-following or target-execution operation
was sent. This is one successful diagnostic, **not an estimate of brick risk**.

### What the captured code establishes

Both 36-byte functions are wrappers with an optional indirect hook. They save
the incoming timer argument, load a pointer through a PC-relative literal, then
load an optional callback. If present, that callback receives the timer argument
and a stack-byte output location. Its return indicates whether it handled the
request. If handled, the wrapper returns the separate output byte; otherwise it
calls a default implementation and returns that result.

| Wrapper | Literal word address | Default call target |
|---|---|---|
| Stop `0x136bc` | `0x137f8` | `0x140ce` |
| Delete `0x136e0` | `0x137fc` | `0x14124` |

**Neither literal word, actual hook-pointer storage/target, nor either default
implementation was read.** These are decoded addresses, not approved follow-up
reads. Literal values and whether a hook is installed remain unknown. The
wrappers alone do not prove queued/running callbacks have drained. The hook's
handled flag must not be mistaken for its separate reported result byte.

`test_fwrom_archive.py` replays all 114 transactions through the current fixed
reader and exactly reproduces the saved capture. Sixteen additional ARM cases
execute the captured wrapper bytes with **synthetic** out-of-window literals,
callback slots and hook/default boundaries. Cases cover absent hooks, fallthrough,
handled false/true results and raw output-byte propagation, bounded memory and
execution, and restored stack/saved registers. They do not model an actual timer
queue, scheduler, callback drain, installed hook or unseen ROM implementation.

Post-capture scoped verification: **237 tests passed, zero skips**, across six
diagnostic/capacity files. Before connection, 42 fake-transport cases also passed
in the Python/Bluetooth environment; 48 instruction cases were deliberately
deselected there and executed in the full proof environment. These overlapping
counts are not additive. The whole guarded build result is recorded separately.

### Current whole guarded build

`firmware/unified/build-20260923-rom-timers-v1/`: **1095 tests passed in
108.07 seconds, zero skips/failures/errors**. This includes both new diagnostic
test files, archived-session replay and captured-wrapper ARM execution alongside
the existing native, selected-stock ARM and compiled Swift checks. It does not
rerun the 58-test iOS simulator suite or 194 separate legacy regressions.

All **127** recorded hashes were independently rechecked after completion:
95 inputs, 29 artifacts and three proof reports. The build itself accesses no
hardware; it consumes the separately acquired capture above. Its flags remain
`flashable=false`, `stock_linked=false`, `hardware_access=false`.

- Manifest SHA-256:
  `0664425ae493d4976dfaf070a5b47c9c80acb1398cf50985254c3c6a116d027c`.
- Artificial-address test ELF SHA-256:
  `8f87fd2133f9ff32dba43638b2bafd0c9e0488bcabd4b8a391c03652af505ee3`.
  It is unchanged from the preceding memory build: no C firmware component
  changed in this diagnostic continuation. It is not an OTA image.

The construction blocker now requires a reviewed physical-validation/recovery
plan rather than categorically requiring a spare. This reflects the user's
daily-ring preference without clearing any technical gate or enabling build/
flash output. No actual placement, hardware bindings or service were added.

### Next evidence needed

A separately reviewed fixed read of the two literal words can precede resolving
their storage locations. Only after classifying a returned address against a
trusted non-secret memory map could a further code/state read be considered.
Do not follow it during this completed session. Independently, the default call
targets need bounded code intervals and a new plan. Acquisition/physical STOP,
RAM placement and recovery gates remain unchanged.

## Subsequent battery-only request

The user then explicitly requested reconnection, a battery check, and to run the
firmware if tests passed. A separate battery-only connection matched the expected
CoreBluetooth identifier, `R02_CC07`, `RT02CR_V3.1` and version
`RT02CR_3.12.07_260514`. It sent exactly one UART command, battery `0x03`, and
received checksum-valid `035e0000000000000000000000000061` at Unix time
`1790154843.711361`: **94%, not charging**. Disconnect was verified. No CD read,
sensor command, settings write or firmware transfer was sent in this connection.

The conditional request does not supply the missing stock-linked image or clear
the unpassed physical gates: 1095 passing offline tests are not all flash-readiness
checks. No unified image exists to transfer, so nothing was flashed. This battery
reading is not a drain measurement or a full installed-image fingerprint. The
completed ROM session's archived transcript remains unchanged; it does not include
this later battery transaction.

## Separately selected timer-internals follow-up

The user renewed authorization to perform on-ring diagnostics and said the ring
was ready. The assistant instructed keeping all other ring clients closed. The
following fixed plan is separate from the completed sessions above; it does not
reuse their idle confirmation or authorize a sensor start, transfer or code call.

`probe.rom_read --timer-internals` first repeats the prior identity/descriptor/
configuration/idle checks, application ROM identifier, and both 72-byte wrapper
reads. The wrapper bytes must equal the hash-pinned previous capture. Only then:

- Read `0x137f8..0x13800` (8 bytes), twice: the two PC-relative literal words.
- Read `0x140ce..0x1417a` (172 bytes), twice: a bounded window covering the
  previously decoded default entry points `0x140ce` and `0x14124`. The endpoint
  is a fixed capture cap, not a verified function boundary or permission to fetch
  unseen callees. These addresses lie in the mapped ROM timer-code region.
- Recheck exact configuration and idle, unsubscribe, disconnect and verify closed.

Expected total: **142 CD01 transactions**, versus 114 for the original plan.
All existing deadlines, no-retry behavior and CD bookkeeping caveats still apply.
No returned literal value is used as a read address; no hook slot, timer object,
queue, peripheral, FIFO, OTP or flash bank is added to the allowlist. The new
reader has distinct closed-by-default phases and a separate capture schema.
The original reader still rejects the new windows even under phase fault injection.

Before connection, fake-transport tests check exact order/count, prior-wrapper
mismatch, unsafe returned pointers, per-phase repeated mismatch/transport faults,
adjacent/other-phase reads, configuration/idle changes and CLI cleanup. Additional
actual-CD instruction cases test each new fixed chunk on both pinned images,
under all three existing dispatcher states, with explicitly synthetic source
bytes. This is read-addressing evidence, not execution of the target ROM code.

### Completed internals capture and concrete findings

Archived under `firmware/research/2026-09-23/rom-timer-internals/`:

| Artifact | SHA-256 |
|---|---|
| `rom-timer-internals.json` | `79fe567846b308a081d6820ce552b45fba107470f2258035d67e4cd2d1c88525` |
| `transcript.jsonl` | `cd7bee72e54f8a3d346c8b835e0eed4cf29c8c4cfaa6c99741b622f1a774f9c7` |
| Eight literal bytes | `a2f7b08f69cf8f6848ae008853bc9a53921ab3961e7b7f5f6ca1f3fd08cac777` |
| 172 default-code bytes | `d814c35d1f453d068409600fe9aa30d031bd5e8029cf72d9d803b9e570166da7` |

All **142 request/reply pairs** matched, with valid checksums and equal repeat
windows. First request to final reply: **19.44 seconds**, excluding connection.
Configuration/idle postchecks passed, and the transcript confirms disconnect.
Preflight: **355 passed, zero skips** in the proof environment; **76 host-only
tests passed**, with 132 instruction cases deliberately deselected in that
separate Bluetooth environment. Post-capture verification initially passed 376
tests, including replay and the 18 cases below; counts overlap, not additive.

The window contains the complete direct bodies of the default stop routine
`0x140ce..0x14124` and delete routine `0x14124..0x14154`, plus an unrelated
following routine and a partial one. Capturing those adjacent bytes does not
approve using those other entries. External literals, callees and actual state
remain distinct missing evidence.

- Both defaults accept a **pointer to the timer handle**, reject NULL pointer/
  NULL handle, and reject one bit from an external state block. The state-block
  literal at `0x1424c` is outside this capture and remains unread.
- Stop calls an unread selector at `0x14238`. Its nonzero branch calls symbol-
  pinned `xTimerGenericCommand` at `0x108e0` with command 3; its zero branch uses
  command 8 and an output pointer. Other explicit arguments and the stacked
  fifth word are zero. It reports success only for return **exactly 1**.
- In the command-8 branch, a nonzero output word causes a `1 << 28` write via
  the unread literal at `0x14248`. This resembles a scheduler-yield path, but
  the literal's value and selector implementation were not captured; neither
  is treated as verified here.
- Delete calls the same command function with command 5 and zero auxiliary
  arguments. On a **nonzero** return it clears the caller's handle and returns
  1; on zero it preserves the handle and returns 0. It makes no additional
  callback-drain call after command success. Clearing a handle is not a receipt
  that all queued/running callbacks have finished.

`tests/test_fwrom_timer_stop.py` executes the captured outer wrappers, literal
words and both default bodies in 18 ARM cases. Initially the absent-hook contents
were synthetic; final tests use the subsequent actual repeated idle snapshot
below. External state/selector/
command-call results and the scheduler-write destination are mocks. Checks cover
NULLs, the rejecting state bit, both stop branches, wake-output handling, zero/
one/nonboolean returns, exact handle mutation, saved registers and bounded
memory/instruction execution. The command function itself remains unread: these
tests prove caller behavior, **not actual queue semantics or callback drain**.

### Hook-state follow-up selected during the same client-closed work period

The internals read completed with 142 matching transactions, repeated equality,
and verified disconnect. The actual literal words are `0x201650` and `0x201654`.
The already-captured wrapper code reads each SRAM word and treats its value only
as an optional function pointer. This classifies these fixed eight bytes as
non-secret OS hook control state, not peripheral/OTP/FIFO data; the pinned map's
nearby `patch_osif_os_timer_create=0x201644` independently locates the OS hook
area. Nearby state is not thereby added to the allowlist.

Before a second connection, the assistant announced a separate eight-byte hook
check while asking that clients remain closed. `--timer-hook-state` repeats all
142-plan prerequisites including exact matches against the archived literals and
default-code window. It then reads **only `0x201650..0x201658`, twice**, before
the usual final config/idle checks and disconnect: **144 total transactions**.
Returned hook pointers are never called or used as read addresses. A nonzero or
changing hook is evidence to review offline, not permission to execute/follow it.
The previous two readers still reject this window. This limited snapshot cannot
prove hook state is immutable, callbacks have drained or the scheduler's behavior.

### Hook-state session completed

Archived under `firmware/research/2026-09-23/rom-timer-hooks/`:

| Artifact | SHA-256 |
|---|---|
| `rom-timer-hooks.json` | `1551f253f43fbd3b852f866ea76da07084c503124406ae38a3acbdfbb028de53` |
| `transcript.jsonl` | `9bc112033d125cbd9d0da037e4ed085f8a4751522e0518dcb1f8cf7f8133f504` |
| Eight zero hook-slot bytes | `af5570f5a1810b7af78caf4bc70a660f0df51e42baf91d4de5b2328de0e83dfc` |

All **144 request/reply pairs** matched, first request to final reply **19.65
seconds**, with exact wrapper/internals repeats, configuration/idle postchecks,
and verified disconnect. Both SRAM pointer words were **zero in both reads**.
Thus the captured wrappers select their defaults under this observed idle state,
not necessarily across later initialization/sleep/operations. No pointed-to code
was read or called.

Preflight: **415 passed, zero skips** in the proof environment; 109 host-only
tests passed separately with 138 instruction cases deselected there and covered
in the proof run. After archival, the scoped suite passed **418, zero skips**.
These counts overlap. Replay tests reproduce all three 114/142/144-transaction
captures. The 18 ARM default-path cases use actual zero slot bytes and ROM code;
other unread boundaries remain mocked, so actual queue semantics are not proved.

The user was told the ring was disconnected and clients could reopen. **The
client-closed work period ended.** Further connections need new coordination.
Neither follow-up sent sensor commands, peripheral/FIFO reads, settings/clock
writes, code calls or firmware transfers. V2 remains installed; optical health
is still globally disabled. No health/steps/sleep continuity is established.

### Remaining focused checks

The next cancellation evidence is the symbol-bounded `xTimerGenericCommand`
body and relevant timer-task dequeue/dispatch behavior, plus the unread selector
and state literals. Any acquisition needs a separately reviewed fixed plan;
do not follow live queue pointers. The observed default path does not establish
callback drain or physical STOP/current-settings resume. Memory ownership,
stock integration, recovery and physical source/model gates remain open.

### Final guarded build for both follow-ups

`firmware/unified/build-20260923-rom-internals-v1/` passed **1276 tests in
102.47 seconds, zero failures/errors/skips**. All **132** hashes were rechecked:
100 inputs, 29 artifacts and three proof reports. Its inputs include all three
ROM session archives, fixed collectors and selected ARM caller tests.

- Manifest SHA-256:
  `827b299149aec7069fa0d99cbb9786980f818953d1779dad369a4992993fb642`.
- Artificial test ELF SHA-256:
  `8f87fd2133f9ff32dba43638b2bafd0c9e0488bcabd4b8a391c03652af505ee3`.
  Unchanged from the memory build; no C component changed.
- `flashable=false`, `stock_linked=false`, `hardware_access=false`: the build
  itself consumes archived captures and does not connect to hardware.

No simulator rerun, production transport unlock or installable unified output.
The earlier 1095-test build is now a historical source snapshot, not the current
collector source. Test totals do not measure progress toward physical safety.
