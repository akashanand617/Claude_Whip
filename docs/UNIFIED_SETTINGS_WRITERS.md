# Stock current-settings writer inventory

2026-09-24. Bounded, off-ring static audit. **No revision owner, writer hook,
memory allocation, production patch or release gate is approved.** No tests,
emulator run, ring access, phone operation or flash were performed for this
inventory. Only this document was added.

## Result

The four bytes read by `wss_read_controls` have **18 confirmed direct byte-store
sites**, plus boot clearing, a bulk settings load/default operation, and an
unrestricted diagnostic memory-write path. The five previously exercised
schedule setters are not a complete writer boundary.

Most importantly, stock command **`BF` can write arbitrary RAM**, including those
controls and any future revision word. Instrumenting typed setters without
retiring or otherwise constraining that path cannot establish a truthful
current-settings revision. The smallest defensible implementation is a shared,
bounded mutation primitive at the actual write boundaries, combined with
explicit diagnostic retirement and a separate eligibility revalidation policy.
The existing GATT callback and main task do not already form one serialized
settings owner.

## Evidence and address convention

Input: `firmware/rt02cr-stock-3.12.02.bin`, SHA-256
`b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0`.
All code locations below are **file offsets**; runtime code address is file
offset plus `0x825fb0`. Data addresses are absolute stock RAM. These are not the
installed V2/25 Hz addresses.

The audit checked original Thumb instructions and PC-relative literal values,
and followed selected immediate callers and registered callback pointers. A
short-lived read-only Capstone scan located candidate constant-base stores;
the reported stores were then checked in their surrounding instructions. The
scan is not a whole-program pointer analysis or an executed witness.

Relevant existing source/reference boundaries:

- `firmware/unified/stock_schedule_settings.{c,h}`: the four-byte read and its
  explicit partial-settings contract.
- `firmware/unified/stock_health_commit.{c,h}`: final commit requires a separate
  monotonic, non-wrapping revision and a common serialization domain. It does
  not implement that writer contract.
- `whip/fwhealth_schedule.py` and [stock settings](UNIFIED_STOCK_SETTINGS.md):
  existing exact-stock getter/setter and schedule execution, with clock,
  activity/charging, timers and queue boundaries explicitly substituted.
- [Wire audit](UNIFIED_WIRE_AUDIT.md): the checked fast/queued command routes,
  GATT callback, main-loop queue and stateful receive prelude.
- `firmware/research/2026-09-22/rom_symbol_gcc.axf`: declared ROM symbols
  `ftl_load=0x7b1f`, `ftl_save=0x7b33`, `__aeabi_memset=0x3f8cb`,
  `memcpy=0x3f849`. Thumb bits are included in these declarations. They identify
  call targets; the symbol text is not execution of their implementations.

## Direct writes to the four controls

### HR interval: RAM `0x208aac`

| Store | Containing path | Observed write |
|---|---|---|
| `0x1596` | Defaults `0x154e` | `30` |
| `0x50e2` | HR setting command `0x16`, handler `0x50ba` | Incoming byte 3 |
| `0x5118` | Same command handler | Replaces incoming `0` or `255` with `30` |
| `0xe4b2` | Health initialization `0xe49a` | Replaces stored `0` or `255` with `30` |

The command updates enable bit 0 through `0x1732` **before** writing and possibly
normalizing the interval. Thus a wrapper around just the bit setter does not
cover the complete HR setting transaction. Its local mutation section starts
at `0x50d6` and reaches `0x511a`; there is a separate read-response branch.
The only call in the mutation section is the leaf enable setter. Reply/checksum
and notification work follows and must not be pulled into a long interrupt mask.

The initialization route is `0x131e -> 0x3714`, then `0x1324 -> 0x12d2`,
`0x12e4 -> 0xe4b6`, `0xe4b8 -> 0xe49a`. No other direct caller of `0xe49a`
was found in the inspected app code. That supports a boot initialization
boundary, not proof that no indirect re-entry is possible.

### Enable/control byte: RAM `0x208aad`

| Setter entry | Store | Bits changed | Immediate caller / context found |
|---|---|---|---|
| `0x1732` | `0x174a` | 0 | `0x50dc`, fast command `0x16` |
| `0x174e` | `0x1766` | 1 | `0x5098`, fast command `0x2c` |
| `0x1782` | `0x1790` | 2 | `0x502e`, fast command `0x36` |
| `0x188c` | `0x189a` | 3 | `0x5d34`, queued command `0x38` |
| `0x18aa` | `0x18b8` | 4 | `0x5fda`, queued command `0x3a` |
| `0x192a` | `0x1942` | 5 | No direct caller or exact Thumb function-pointer value found |
| `0x18c6` | `0x18d4` | 6–7 | `0x5520`, fast command `0x19` |
| Defaults `0x154e` | `0x15ae` | Entire byte | Produces `0x40` after the bulk fill |

The setter for bit 5 is real code, not an inferred vacant bit. Its getter is
`0x191e`; both share the return at `0x18d6`. Absence of a direct caller does not
justify excluding it from a future complete inventory. Bits 6–7 have getter
`0x18bc`; the `0x19` handler bounds its selected value to `0..2`. No semantic
feature name for bits 5–7 is asserted here.

The bit-2/3/4 setters shift the incoming value and OR it into the byte without
first restricting the input to one bit. Their inspected command callers supply
0 or 1, matching the existing tests. A replacement leaf must preserve the
original raw-input ABI or explicitly constrain **all** callers; it must not
silently generalize those tests to arbitrary inputs. Bit-0/1/5 setters have
their own compare/mask behavior and may return without a store.

### Operating mode: RAM `0x208c44`

| Store | Value | Containing path / immediate callers |
|---|---:|---|
| `0x132c` | 3 | Main-task initialization after settings/health initialization |
| `0x1638` | 1 | `0x162a`, after charging predicate returns zero; called at `0x1cf4`, `0x2c00`, `0x6650` |
| `0x1698` | 3 | `0x168c`, only when old mode is 1; caller `0x3470` in the main-loop `0x343a` work |
| `0x16e8` | 5 | Reset path `0x16d2`, called at `0x6128`, `0x6666` |

These are observed numeric states. The surrounding functions also stop/start
subsystems, wait, persist state or reset. They are not safe to execute with
interrupts masked as whole-function revision wrappers. A hook must cover the
actual state mutation and its required invalidation ordering, without claiming
that the adjacent subsystem calls succeeded.

### Time-set gate: RAM `0x208c46`

| Store | Value | Path |
|---|---:|---|
| `0x097a` | 1 | Boot routine `0x0954`, if restored `0x208bed` equals 1; called at `0x09e6` |
| `0x4a20` | 1 | First-time clock setup inside queued command `0x01`, handler `0x4966` |

The clock handler also changes current time when this byte is already 1.
Watching only the gate store would miss those eligibility changes. No direct
runtime store clearing this byte was established in this audit; BSS clearing
and unrestricted diagnostic writes can still change it.

## Bulk and dynamic writers

### Settings initialization and defaults

`0x36f4` calls declared ROM `ftl_load` at `0x3700` with destination
`0x208a80`, FTL offset `0x400`, length `0x160` (352 bytes). This covers both
`0x208aac` and `0x208aad`, but not operating mode or the time-set gate. It checks
the loaded block's first byte for marker 5. `0x3714` selects this load or
defaults. A successful marker is not independent validation of every setting.

`0x154e` calls declared `__aeabi_memset` at `0x1558` with the same destination
and length, filling it with `0xff`, before individual defaults are installed.
It is therefore a writer even before `0x1596`/`0x15ae`. Later work in that
function includes persistence and other subsystems; it is not one bounded
PRIMASK-safe transaction.

There is a second direct defaults call at `0x6536`, inside `0x64f6`, when a
12-byte comparison differs. The queued dispatcher calls that handler at
`0x65f4` for opcode `0x7c`. **Do not confuse it with the externally selected
fast `0x7c` handler `0x5756`: that route is different and does not enqueue here.**
The source of a queued `0x7c` is not closed by this audit. The defaults call
exists, but its ordinary runtime reachability must not be invented.

`0x3726` saves the settings block through declared `ftl_save`; it is not the
load-side mutation boundary. `0x373e` loads a comparison block into its own
stack before conditionally saving current settings. A hook only on settings
persistence would miss both the actual write time and unsaved changes.

The startup BSS clear covers `0x208990..0x20e734`, including all four controls;
see [memory audit](UNIFIED_MEMORY_AUDIT.md). Revision initialization must be
ordered after the relevant boot restore/default/normalization work, before
unified admission, and invalidated on reset/re-entry. It cannot assume the
first observed controls are immutable boot constants.

### Confirmed unrestricted `BF` memory write

The existing checked route is:

```text
UART write 0x7ace -> 0x5c22 -> fast dispatcher 0x5882
  opcode BF -> 0x5bb4 -> call 0x5bb6 -> handler 0x48c6
  -> ROM memcpy call at 0x4916
```

The handler constructs destination `r0` from packet bytes 1–4 in big-endian
order, takes length from byte 5 (capped at 8), and copies from packet+6. Zero
length skips the copy. The reviewed handler contains **no destination-range
filter**. The callback's normal length/mode gate does not prevent writes to
these settings or to any subsequently chosen revision/adapter address.

This is a concretely decoded dynamic writer, not merely an unclosed pointer
scan. The actual ROM copy implementation was not executed in this task; the
call ABI and its unrestricted destination are explicit. No diagnostic command
was sent and no memory on the ring was changed.

Recommended production candidate: **unconditionally retire `BF` arbitrary
memory writes from the unified legacy-command entry**, before the stateful
receive prelude. Do not merely reject overlaps with the four current bytes:
unrestricted writes elsewhere can modify revision/preparation, job fences,
function pointers and other invariants. This is a recommendation for a reviewed
future patch, not approval or an installed change. It does not imply retiring
stock Health commands.

The companion diagnostic boundary must also cover:

- `CE`, handler `0x4b02`: packet-directed calls at `0x4b4c -> 0xdcce` and
  `0x4b5a -> 0xdbca`, plus GPIO/I2C recovery operations. These bypass typed
  sensor ownership. Merely fixing settings revisions does not constrain them.
- `CD`, handler `0x4c36`: a RAM-read case plus other diagnostic subcommands.
  Every ordinary `CD` request has already passed the stateful `0x8112`
  prelude. It must not be advertised as a side-effect-free observer of unified
  state. Production must gate it or supply a separately bounded, reviewed
  replacement; no existing physical diagnostic permission is expanded here.

Neither removing these paths nor their code bodies supplies approved reusable
flash space. In particular, the `BF` handler straddles a literal/data island;
its whole apparent address span is not a free contiguous code cave.

## Eligibility changes beyond the four bytes

The scheduled start functions are not equivalent to a four-byte equality test:

- Charging getter `0x2dae` reads bit 0 of RAM `0x209ce8`. Setter `0x2dba`
  updates it at `0x2dce`; direct caller `0x334a` is in `0x3328` charging work.
  Initialization also clears that region through the call at `0x2cd6`.
- Getter `0xb7b0` reads RAM `0x20bd40`. All five reviewed starts refuse value
  1. Its state comes from the algorithm result stored at `0xb57e` in minute
  bookkeeping `0xb53e`; `0xb850` explicitly clears it, and `0xb874` bulk-clears
  its containing 64-byte block. These are activity/wear-related eligibility
  inputs, not decoded medical classifications.
- Clock setter `0x1a84` stores changed time at `0x1a8c` and branches into
  reconciliation `0x194c`; `0x1a7c` clears its time word. Clock command `0x4966`
  can call the setter without changing any of the four controls. The minute
  scheduler also consumes pending seconds and advances its own counter.
- The dispatcher `0x1202` requires time-set exactly 1 and mode 3 for its
  scheduled-optical selection. HR start repeats exact time-set 1 and mode 3;
  several other starts test nonzero time-set. `0xecbe` does not itself repeat
  the mode-3 test and additionally rejects a zero day value through `0x2696`.
  These differences matter if a future binding calls start functions directly.

Relevant changes therefore require invalidating/rechecking prepared eligibility
in the same serialized domain, or a proved fresh check at admission; a settings
counter alone must not pretend to version the passage of time, changing
charging state, activity classification or scheduler work. Do not call the
whole minute handler as a resume primitive or stop its non-optical work.

## Smallest realistic implementation boundary

1. Retire/gate the arbitrary diagnostic mutation paths at an early legacy
   ingress boundary. Keep ordinary Health/history operations separately
   reviewed. Reusing the unchecked ten-entry queue is not a safe ownership fix.
2. Establish one caller-owned aligned revision word and an explicit terminal
   no-wrap policy. No address or lifetime is assigned by this document. A
   saturated/invalid revision must permanently refuse reuse of prepared resume
   evidence; silently wrapping is not allowed.
3. Instrument actual typed writes, including all seven enable setters and
   interval, mode and time-gate stores. Each bounded revision advance must occur
   before the associated control write becomes visible, under the same
   PRIMASK-preserving serialization contract as final Health commit. Preserve
   each original setter's masks, input behavior, return/flags obligations and
   callee-saved registers. A `BL` inserted into a leaf is not automatically a
   safe trampoline: it changes LR and may displace PC-relative instructions.
4. Treat multi-store transactions explicitly. For example, the HR enable plus
   interval normalization must not expose reusable preparation halfway through
   the command. Incrementing once at function entry and then allowing a task
   switch before the stores is insufficient. Long default/FTL/clock operations
   need admission closure or an explicit in-progress owner protocol, **not**
   an interrupt mask around ROM/RTOS/I/O calls.
5. Order boot initialization and reset separately; revalidate eligibility
   beyond the four controls at the genuine current-settings resume boundary.
   Do not manufacture timer-create, scheduler, physical RUN/STOP or Health
   continuity receipts from revision acceptance.

This is a concrete inventory for the next implementation, not a completed
binding. Exact hook encodings, preserved-register/flags witnesses, complete
indirect and ROM writer closure, real task/interrupt ownership and placement
must still be reviewed. No new instruction-storage total is claimed: the
seven existing setter bodies occupy 156 bytes in total, but that is **existing
stock code**, not a measured size for safe replacement hooks. The independent
revision word is 4 bytes if newly allocated; it is already part of the
illustrative 16-byte preparation plus 4-byte revision accounting in the Health
commit candidate and must not be counted twice.

## What this does not close

Constant-base stores and immediate callers do not exclude computed addresses,
pointer escapes, indirect callbacks, ROM patch code, DMA/debug/NMI/reset writes
or an unreviewed alternative entry. The separate
[RAM ownership audit](UNIFIED_RAM_OWNERSHIP.md) likewise leaves dynamic
clear/copy destinations unresolved. This inventory does not supersede those
limits or certify all writers. It does identify a specific reachable bypass
(`BF`), specific missing setters, and the split task/callback ownership that a
real revision implementation must address before claiming closure.

## Proposed early legacy-ingress hook — bounded follow-up

2026-09-24, static inspection only. Claude Code owns live ring testing; this
follow-up used no device, emulator, build or test runner and changed no source
or stock bytes. It identifies a next **off-ring implementation target**, not a
flash patch or a completed diagnostic interlock.

### Preferred narrow interception point

Stock file **`0x7b0a`**, runtime **`0x82daba`**, contains one complete four-byte
instruction, **`fe f7 8a f8`**: `bl 0x5c22` (runtime target `0x82bbd2`, Thumb
function pointer `0x82bbd3`). This is the earliest ordinary call boundary
**after** the registered UART callback has checked non-null data and attribute
index 2, but **before** either the length/mode gate or the stateful dispatcher.
Redirecting this call to a future reviewed helper would leave the callback's
other attribute/error paths untouched. The earlier registered callback entry
is file `0x7ace`, pointer `0x82da7f` at file `0x1f308`; replacing that entire
callback requires the wider stack-supplied vendor ABI and is unnecessary for
this narrow filter.

The complete 84-byte callback `0x7ace..0x7b22` has SHA-256
`5532f52924e801f3769c205100ce0e5f2201e1f106b281a0ea3a0dcfeac1d36b`.
The original 16-byte gate `0x5c22..0x5c32` is:

```text
5c22  fe4a  ldr  r2,[pc,#0x3f8]  ; literal601c = RAM208c44
5c24  1278  ldrb r2,[r2]
5c26  012a  cmp  r2,#1
5c28  02d0  beq  5c30
5c2a  1029  cmp  r1,#16
5c2c  00d1  bne  5c30
5c2e  28e6  b    5882
5c30  7047  bx   lr
```

Its SHA-256 is
`8a59a3917bd9679488905527b5ea3f887f841a2d2bac1697d8c47c6074925883`.
**Do not overwrite four bytes starting at `0x5c2e`:** its two-byte branch is
followed by the separately targeted rejection return at `0x5c30`. Such an
overwrite would destroy an existing entry path. The preferred `0x7b0a` call
does not split an instruction or consume that return.

### Derived argument and return contract

Let `S` be the stack pointer on entry to `0x7ace`. The callback pushes
`{r3,r4,r5,lr}` (16 bytes), then performs:

| Instruction | Machine-level fact |
|---|---|
| `0x7ad0: ldr r0,[sp,#0x14]` | Packet pointer comes from incoming `[S+4]` |
| `0x7ad2: movs r4,#0` | Default saved callback result is zero |
| `0x7ad6: ldr r1,[sp,#0x10]` | Length comes from incoming `[S]` as a full 32-bit load |
| `0x7ad8..0x7ada` | Null packet takes the separate error/log path |
| `0x7adc..0x7ade` | Only incoming `r2 == 2` reaches `0x7b0a` |
| `0x7b0e -> 0x7b1e` | After the helper, callback sets `r0 = r4`, then restores its frame |

The narrow helper's inputs are therefore **`r0=packet`, `r1=length-word`**.
It must preserve the ordinary ARM callee-saved registers, especially `r4=0`,
and balance its stack/LR across any delegation. Its return value and condition
flags are not consumed by this caller. Stock returns zero after a valid-index
helper call even if the length/mode gate rejected the request. This is not a
command reply or an acknowledgment that the command ran.

Null data instead returns `0x40d`; an unsupported attribute returns `0x40a`.
Attribute 7 takes a logging path and returns zero without legacy dispatch.
Those paths precede or bypass the proposed call-site filter and should remain
unchanged. Incoming `r3` is saved/restored but not inspected as a write-kind
gate here. No connection identity, authorization, checksum validation or packet
buffer lifetime is established by this small callback. The ROM transport must
still supply a readable buffer; non-null alone is not pointer validation.

A candidate must compare the **whole loaded length word** with 16 before
reading the opcode; narrowing it to `uint16_t` could admit a value stock
rejects. Preserve stock's mode-1 rejection before opcode access if reproducing
the original access contract. Other ordinary commands must continue through
the unchanged stock mode/length gate and dispatcher. An extra preliminary mode
read must not be treated as a serialized snapshot or as proof of mode ownership.
Those access/order details need focused off-ring validation before attaching a
helper; no helper was compiled or tested in this follow-up.

### Unconditional retirement versus mode-dependent policy

For a rejected BF/CE/CD request, returning from the proposed helper reaches
`0x7b0e`, then the zero-result callback epilogue. It never branches to
`0x5882`, so neither prelude call `0x5890 -> 0x8112` nor any diagnostic handler,
command queue or notification helper is reached. A silent drop is the minimal
no-side-effect outcome; it does **not** generate a legacy error packet. Adding
an error response is a separate transport/queue design, not an assumed safe
call to `0x7e30`.

Recommended initial policy is unconditional retirement of **BF arbitrary RAM
write**, irrespective of unified mode or whether a revision owner is ready.
Otherwise BF can overwrite the very state used to decide whether BF is allowed.
The same early boundary can unconditionally retire CE/CD diagnostics without
requiring a unified-state pointer. Blocking those opcodes before the prelude
also avoids their bookkeeping effects. This is a proposed production policy,
not a change to Claude's currently installed diagnostic image or permission to
interrupt live testing.

Mode-dependent CE/CD allowance is materially harder: permitting them merely
in Health, or blocking them only in Gesture, leaves initialization, ENTERING,
RETURNING, FAULT and outstanding-job races. A valid exception would require a
serialized maintenance state, all relevant work drained, an authenticated and
bounded operation set, and no claimed Health/source continuity during it.
Stock `RAM208c44 == 1` is not a unified Gesture/Health state and cannot serve as
that policy. The ordinary Health/settings/history commands need not be retired
by a denylist limited to these diagnostics.

### Alternate-entry coverage and limits

A fresh static scan covered immediate branch candidates at halfword boundaries
in XIP code, permanent RAM code and the boot overlay, using each region's real
execution address. Stored pointer candidates were searched at every byte
offset of the exact stock file. Findings, with instruction boundaries checked:

| Boundary | Incoming paths found |
|---|---|
| UART callback `0x7ace` | Stored Thumb pointer at `0x1f308`; no immediate call into its entry |
| Gate `0x5c22..0x5c32` | Only `0x7b0a -> 0x5c22`; no stored pointer into this interval |
| Fast dispatcher entry `0x5882` | Only `0x5c2e -> 0x5882`; no stored pointer into its function interval |
| BF handler `0x48c6` | Only `0x5bb6 -> 0x48c6`; no stored pointer into its interval |
| CE handler `0x4b02` | Only `0x5c1c -> 0x4b02`; no stored pointer into its interval |
| CD handler `0x4c36` | Only `0x5c14 -> 0x4c36`; no stored pointer into its interval |

Three external branches into the fast dispatcher's interval are shared returns,
not ingress bypasses: `0x5cf8`, `0x5e8c`, `0x613a` each branch to the
`pop {r4,pc}` epilogue at `0x5990`. Halfword scanning also reports apparent
branches from `0x7a06/0x7a26/0x7a5e/0x7aba` into the callback; each is the
second halfword of an actual four-byte BL and is **not a valid instruction
boundary**. These were excluded after checking their enclosing instructions.

This closes the identified normal legacy receive routes, not all possible
invocation mechanisms. Computed/indirect calls, ROM/patch-created callbacks,
runtime pointer mutation, deliberate entry into a handler's interior and
DMA/debug/reset remain outside the scan. The original callback pointer is
registered through stock/ROM transport; matching it in the file is not proof
that no alternate callback can be installed at runtime. Retirement must be
part of a boot-installed, fully identified image before unified admission;
installing a filter after untrusted diagnostic writes have already occurred
would not restore trustworthy state. Safe encoding, code/stack placement,
whole-image reproducibility and actual hook execution remain unimplemented.

## Compatibility, Health and recovery impact of retirement

2026-09-24. Independent read-only review of the current iOS/host source and
selected original stock paths. No app, test runner, emulator or device was
started. These findings qualify the production-policy recommendation above:
**an unattached denylist is useful, but attaching it without updating firmware
identity can break the current app's restore workflow.**

### Ordinary Health and gesture paths

`ios/R02Ring/Health/ColmiR02Client.swift` and `RingProtocol.swift` use UART
`01` for clock, `03` for battery, `15` for HR history, `16` for HR settings,
`43` for steps, and `69`/`6a` for realtime HR. Sleep uses data ID `27` in
`BC` framing on the **separate big-data service**. None of those requests is
BF, CE or CD. An opcode-only retirement at the proposed UART call site does
not select them for rejection. This is source-level compatibility, not
measured post-patch Health/steps/sleep continuity.

Normal host motion capture in `whip/capture.py` uses A1 start/stop and optional
ordinary schedule/realtime-stop commands. The special CE optical STOP is not
that capture path: it belongs to the research workaround described below.
The future `UnifiedModeTransport`/`UnifiedWire` APIs use a separate service
candidate; they do not use BF/CE/CD. They are still unattached to production
CoreBluetooth, so their existence is not a ready replacement for legacy
firmware identification.

No normal app/host BF request constructor was found in the inspected Swift,
`whip/` and `probe/` command paths. Search hits such as `00 bf` NOP encodings,
file offsets starting `0xbf`, UUID bytes and emulator-memory APIs are not
legacy BF commands. Generic packet/write APIs and uninspected third-party
clients remain outside that absence claim.

### CD is currently required by iOS firmware identification

`FirmwareIdentity` in `Health/FirmwareSwitching.swift` constructs **22 CD01
requests covering 244 code bytes**. `AppModel.identifyFirmwareMode()` runs them
when DIS reports `RT02CR_3.12.07_260514`, to distinguish the pinned Gesture V2
image. This is an actual shipped call path, not only a research tool.

The effect of silently retiring CD while retaining that version string is:

1. The first fingerprint request receives no legacy reply and times out after
   three seconds.
2. `RingManager.requestUART` marks `uartNeedsReconnect = true`; subsequent
   UART requests are refused until reconnect to avoid ambiguous late replies.
3. `AppModel` sets firmware mode to `.unknown` and reports uncertain identity;
   automatic Health sync does not proceed. A pending switch cannot be marked
   verified.
4. `switchFirmware` needs a UART battery reply before starting DFU. That
   preflight is now refused; reconnecting to the same version repeats the
   fingerprint failure. Thus the **current app's return-to-stock workflow can
   fail even though the DFU byte-transfer implementation remains intact**.

This is derived from the present source, not an executed app regression. The
stock DIS string `RT02CR_3.12.02_260824` currently bypasses CD and is classified
as Health directly. Reusing that string for unified firmware avoids this
particular timeout but silently misidentifies a new build as stock; it is not
a substitute for reviewed unified discovery. An unfamiliar new string instead
leaves the app in unknown mode. Production needs an explicit unified identity,
capability/discovery and app admission path **before** retiring CD on a deployed
image. Do not bypass fingerprint, reconnect, battery or Health-history guards
to make the old app accept it.

### Research functions deliberately lost

- `probe/ledcheck.py` uses CE02 to write optical STOP and CE01 for selected
  non-consuming sensor register reads. `probe/batterycheck.py` imports that
  STOP workaround, uses CD for code/RAM checks, and verifies cleanup via CD.
  Retirement disables those old experiments; it must not be reported as
  their successful replacement.
- `whip/fwidentity.py`, `probe/validate_optical_off.py`, and the bounded
  capacity/ROM/boot/RAM readers use CD01 for pinned reads. They will refuse or
  time out against a retired interface. Their captured evidence remains
  usable offline. These tools target the existing 25 Hz/V2 diagnostic family,
  not an approved unified interface.
- Raw BF memory writing, CE bus/GPIO diagnostics and CD's additional diagnostic
  subcommands cease to be available through the normal UART service. Factory
  or third-party dependence on those operations has not been established.

Claude's live work is on the currently installed image, which this audit and
the unattached helper do not change. Retirement is not permission to interrupt
that work or replace its commands with a different unreviewed diagnostic.

### DFU and sleep use a distinct stock receive path

Both `whip/flashing.py`/`whip/dfu.py` and iOS `RingManager.flashFirmware` send
START/INIT/DATA/CHECK/END (`01..05`) as **BC frames** to the DE5B service's
`...72a` characteristic, receiving `...729` notifications. Python preflight
uses DIS information, a locally pinned image and UART battery `03`, not
BF/CE/CD. iOS adds the identity dependency described above outside the DFU
transport itself.

The exact stock database independently distinguishes the receive routes:

| Item | Exact stock file evidence |
|---|---|
| DE5B service UUID / six-row table | `0x1f188` / `0x1f198..0x1f240` |
| Its write callback pointer | `0x1f244 = 0x82d967`, entry file `0x79b6` |
| Data attribute-2 call | `0x79f4 -> 0x823e`, after `uxtb r1,r1` |
| BC header check | `0x8264..0x8268` in reassembly `0x823e` |
| Its own reassembly-timer call | `0x82ba -> 0x80ee` |
| Separate UART filter candidate | `0x7b0a -> 0x5c22`, not this path |

The reassembly timer immediate at stock **`0x80f8`** and helper `0x80ee` must
remain intact. Removing BF/CE/CD's prelude effects does not remove this real
DFU timer call. **Never apply the opcode denylist to all Bluetooth writes or
DFU segments:** their payload bytes may legitimately start with BF, CE or CD.
Only the reviewed legacy-UART ingress is in scope.

The earlier three-execution-region branch/pointer scan found no additional
direct callers or stored pointers into the BF/CE/CD command handlers beyond
their fast UART routes. No boot/task requirement to execute those handlers
was established. This does **not** mean their underlying I2C, memory or timer
helpers are dispensable: ordinary stock Health and transport call such helpers
directly, and they must not be globally disabled or reclaimed along with the
diagnostic entry points. Dynamic/ROM roots and complete OTA/boot behavior
remain unclosed.

No demonstrated hard-brick recovery route exists for this ring. The family
ROM-download leads in [the recovery reference](UNIFIED_VENDOR_RECOVERY_LEADS.md)
are not BF/CE/CD procedures and do not qualify recovery on RT02CR_V3.1. Keeping
DFU's app-level route unchanged is necessary, not proof that a failed new image
can be recovered. Diagnostic retirement also removes useful troubleshooting
visibility; do not equate that loss with a proven loss or preservation of a
bootloader recovery mechanism.

### Could the denylist be narrowed safely?

Unconditional BF retirement remains the defensible default: protecting only
four control bytes leaves writes to revision, adapter state and pointers.
Allowing arbitrary CE reads is also not a safe generic alternative: sensor
reads can consume FIFOs or otherwise affect shared hardware. A fixed,
non-consuming register allowlist would need separate owner, bus and lifetime
proof, not merely Health-mode gating.

For CD compatibility, a separately implemented **fixed immutable-image identity
read** could eventually replace only the necessary fingerprint function,
without arbitrary RAM addresses, diagnostic subcommands or the legacy stateful
prelude. Such a path would need exact bounds/image semantics, a reviewed reply
transport and explicit app expectations. Simply allowing CD01 through to the
old dispatcher retains its prelude and arbitrary-address behavior. The preferred
long-term design is the separately reviewed unified discovery characteristic,
not preservation of general CD as a backdoor. Neither narrowing alternative is
implemented or approved by this review.
