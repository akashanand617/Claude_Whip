# Unified firmware: descriptor and concrete stock binding checks

2026-09-23. Follow-up to [workflow 2](UNIFIED_WORKFLOW_2.md), requested for the
four remaining checks: the exact bank0 descriptor, placement/OTA/RAM evidence,
physical FIFO provenance and the actual stock health lifecycle binding.

Use the [six-gate readiness checklist](UNIFIED_READINESS.md) for the current
integration milestone, whole-image memory deficit and explicit simulated
boundaries. This chronological workflow is retained as evidence, not a release
checklist whose length grows with every new test.

Later [conditional placement](UNIFIED_RAW_RELOCATION_TRIAL.md) links all 21
current objects with 9132 append bytes/388 remaining, using 1886 bytes in unowned
stock regions. No old entry retirement or production acceptance. The separate
59-test guarded supplement passes, including selected raw-entry/Health-path
comparisons, with 274 content hashes checked; it is not a full 3212-suite rerun.
See [resource handoff](UNIFIED_RESOURCE_BUDGET.md) for exact archive/limitations.

Current [legacy-filter checkpoint](UNIFIED_LEGACY_GATE.md): **3212 guarded
tests, zero skips; all 370 source/artifact/report hashes checked**. Both main
ELFs are unchanged; the fourth unlinked candidate blocks BF/CE/CD only in
emulator callback tests. All implemented code attempts 11100/9520 bytes,
1580 over, no full ELF. App identity/discovery migration must precede filter
attachment. The separate Claude RAM session completed 268 reads/disconnect;
root checked the archive and 39 RAM tests. V2's 264 free heap bytes (104 minimum)
do not support the 1164-byte selected state; the gap remains unowned. Codex
stayed off-ring. See [resource handoff](UNIFIED_RESOURCE_BUDGET.md).

Preceding [coordinator checkpoint](UNIFIED_COORDINATOR.md): **3143 guarded tests
passed, zero skips; all 365 source/artifact/report hashes checked**. Actual C
joins STOP/retirement/current-settings commit, while physical source/drain/resume
receipts remain fixtures. The three unlinked candidates and all real components
together exceed the unchanged final region by 1524 bytes; no complete ELF.
Existing components use 9500/9520 bytes. Linker final-bound checks were qualified
and tightened without adding capacity. RAM/vendor/code-space candidates remain
unowned and unapproved. No Codex device access or production unlock follows;
Claude Code separately owns user-requested live tests.

Preceding [resource handoff](UNIFIED_RESOURCE_BUDGET.md): **3060 guarded tests
passed, zero skips; all 357 source/artifact/report hashes checked**. The service
database is a separate unlinked candidate; the main ELFs are unchanged from
the preceding checkpoint. An unowned relocation diagnostic includes Health
commit but is production-rejected; adding the service fails the unchanged
bound and emits no ELF. Claude's separate RAM audit does not establish owned
storage. No device access, production unlock or flash approval follows.

Preceding [resource checkpoint](UNIFIED_RESOURCE_BUDGET.md): **3004 guarded tests
passed, zero skips; all 265 source/artifact/report hashes checked**. Receipt
storage remains 288 bytes; bounded temporary delivery drops 208→64 and observed
nested stack 388→244, retaining all 32 input frames and exact time bounds. Both
main ELFs change reproducibly, with old/new ARM equivalence checks. The integrated
switch runner now executes stock notification wrappers; unresolved ROM transport
and physical boundaries remain fixtures. The separate
[Health commit candidate](UNIFIED_HEALTH_COMMIT.md) is archived/tested but excluded
from both main ELFs: its full addition fails unchanged capacity limits. The preceding
[heap-free sample I/O](UNIFIED_OPTICAL_IO.md) executes two fixed call-site edits
only in emulator memory; it retains bus/release failures without allocating.
No stock file or physical gate changed. The preceding
[optical work implementation](UNIFIED_OPTICAL_WORK.md) adds real C for in-flight
original reads and software-buffer retirement after verified pause. Compiled
ARM executes the original stock reader/clear; both ELFs change reproducibly.
Shared checked code saves space without removing predicates or capacity. Real
source provenance, full hardware attachment and physical continuity remain open;
no ring command or construction gate was enabled. The preceding
[optical read evidence](UNIFIED_OPTICAL_ACQUISITION.md) executes failure masking
and cached-success paths; top-level zero and parsed/read flags cannot prove
measurement provenance. No C or ELF changed in that continuation. The preceding unattached
[HR commit guard](UNIFIED_HR_RESULT_COMMIT.md) adds 80 linked bytes and 60 ARM
cases, protecting four HR-result stores against a modeled ordinary-interrupt
pause. Both ELFs change, but no stock hook, production inventory or physical
gate was enabled. Original source identity/provenance remain unproved. The
[optical-event/commit evidence](UNIFIED_OPTICAL_DISPATCH.md) exposes a separate
untagged hub path and late result stores; it does not install a guard or close
physical gates. Off-ring status-constructor tests
and redacted metadata logging do not change the firmware ELFs or foreign-packet
abort policy; see [the status audit](UNIFIED_STATUS_NOTIFICATIONS.md). The separate
requested [create-hook retry](UNIFIED_CREATE_HOOK_READ.md) completed 359 matching
transactions, repeated equality/postchecks and verified disconnect. Its exact
archive replay passes. Captured-hook/comparator execution now passes off-ring;
empty-handle creation failure reaches unread `0x111a6`, not a safe-return proof. The earlier
`0x73` abort remains historical. Further access needs fresh coordination;
no construction gate opened.
At that preceding checkpoint actual-address components occupied
9468 of 9520 configured bytes (52 remaining); dispatcher/frame/fence totals 796 bytes, with no
approved RAM ownership, complete hardware binding or OTA image. The latest
[indicator retirement experiment](UNIFIED_INDICATOR_RETIREMENT.md) changes only
emulator entries. The newer [current-controls read](UNIFIED_STOCK_SETTINGS.md)
adds 48 linked bytes but no static RAM or complete resume binding. No stock space
is reclaimed or physical STOP proved.
The [timer-resume code diagnostic](UNIFIED_TIMER_RESUME_READ.md) subsequently
completed after fresh coordination: 180 matching transactions, 452 new bytes
read twice, passing postchecks and verified disconnect. Separate archive replay
passes; this adds code evidence, not physical pause/resume or flash approval.
The separately coordinated consolidated ROM retry completed 974 transactions
and 6076 bytes read twice, with matching postchecks and verified disconnect;
the preceding abort remains historical. These results supersede current-count/
size and unread-ROM wording below, not the remaining safety gates.

Later offline continuation: [shared C/Swift wire codec](UNIFIED_WIRE_CODEC.md),
793 guarded tests and 58 simulator tests, zero skips. It performs no new device
access and does not close the physical gates below. This workflow's own build
and test counts remain historical records of its then-current inputs.
The subsequent [dispatcher integration](UNIFIED_DISPATCH.md) brings the current
guarded suite to 874 passing tests, zero skips, still without hardware access.
The latest [exact-stock transport continuation](UNIFIED_STOCK_TRANSPORT.md)
passes 936 guarded tests with zero skips; it does not add physical evidence or
register a unified service.
The subsequent [memory continuation](UNIFIED_RESOURCE_BUDGET.md) passes 986
guarded tests, zero skips, and removes duplicate delivery scratch from a nested
stack path. It records that only the daily ring is available. No new hardware
session or approved placement follows from that result.
Later [fixed ROM diagnostics](UNIFIED_ROM_DIAGNOSTIC.md) completed 114/142/144
matching transactions under reviewed plans with verified disconnect and no
sensor command or flash. Current guarded suite: **1276 passed, zero skips**,
all 132 hashes matched. The actual zero hook snapshot selects the captured
defaults, but their timer-command API and callback drain remain unproved.
This workflow's older counts remain historical.

The subsequent [boot-reference comparison](UNIFIED_BOOT_REFERENCE.md) completed
182 matching transactions and verified disconnect. It established an exact
match for a 52-byte non-secret boot header and 528-byte factory/OEM configuration
checker. No key fields were read, no sensor commands or flash were sent, and
neither full boot recovery nor the SDK board's different memory map is qualified.

Health remains the default; Gesture is temporary and opt-in. No flash, sensor
start, arbitrary-memory read or production capability unlock is part of this
workflow. Offline fixtures and selected Thumb execution do not become physical
evidence merely because their tests pass.

## Coordinated descriptor plan

The user newly confirmed all phone/laptop ring clients closed and no stream or
DFU active. `probe.capacity_read --bank0-descriptor` is a separately selected
plan, not an address-taking memory reader. It first repeats the V2 sampled-code
fingerprint, diagnostic-code checks, idle flag and both prior non-secret
configuration windows. The prior 16/48-byte values are pinned exactly.

Only then does it read `0x802198..0x8021e8` (80 bytes) twice. It does not follow
any returned address or the absent bank1/unresolved backup1 declarations. It
rechecks configuration and idle afterward, and disconnects. A timeout, malformed
reply, duplicate/foreign traffic, changed configuration or changed descriptor
closes the read phase and poisons the session without a retry. Unsupported
descriptor contents are retained for offline interpretation, never followed.

The fixed plan passed 44 fake-transport tests and independent read-only review
before connection. These include six transport failures during the descriptor
phase, forbidden adjacent/MMIO/backup addresses, prerequisite mismatches and
post-read changes. Expected success is 91 serial `CD 01` transactions. CD's
known activity/timer/connection-policy bookkeeping side effects still apply;
this is not a wholly non-mutating protocol. Sampled code is not full live-image
attestation.

## Parallel off-ring work

1. Placement: exact app descriptors, OTA bounds/staging/erase/copy behavior and
   RAM ownership. Do not use another device's flash map or apparent padding.
2. FIFO: execute concrete low-level I2C/read/drain paths, establish what the
   archived physical captures do and do not retain, and identify observer hooks
   without draining/reconfiguring Health's source.
3. Health: trace actual timer, hub queue, RUN/STOP, publication and result paths.
   A stock return value or queued command is not a physical completion receipt.

The principal pre-existing physical gap is observability: the installed images
do not retain a complete timestamped record of FIFO status, byte completion and
acquisition times. Reading the FIFO port would consume data and is excluded.
Any instrumentation design still needs approved placement, serialization and
timing-impact validation before installation, preferably on recoverable test
hardware. The daily ring is not being used for speculative firmware debugging.

## Results and handoff

### Descriptor session completed; no flash or sensor command

Evidence is in `data/capacity-20260923-bank0-descriptor/`. The ring was
disconnected afterward, and the user was told clients could reopen. Independent
offline inspection confirmed 91 matching request/reply pairs, valid checksums,
12 chunks covering only the repeated descriptor window, and `CD 01` as the sole
UART command. V2 sampled code, repeated configuration and before/after idle
checks matched. No follow-up address was read.

Exact artifacts are also preserved in the shareable
[research archive](../firmware/research/2026-09-23/README.md). New offline tests
replay all 91 recorded replies through the fixed reader, require the exact
recorded outgoing commands, and reproduce the archived configuration. This
guards against later code/evidence drift; it is not independent live attestation.

| Configured partition | Address | Bytes |
|---|---:|---:|
| ROM patch | `0x803000` | `0xa000` |
| Secure boot | `0x80d000` | `0x1000` |
| Upper stack | `0x80e000` | `0x18000` |
| Application | `0x826000` | `0x24000` (144 KiB) |
| App-data slots 1–6 | `0x84a000` | zero each |

The app ends at `0x84a000`, exactly the configured bank0 end; the temporary
OTA region is separately configured at `0x84e000..0x872000`. Relative to the
stock container's `0x21ad0` inner-image bytes, the app descriptor confirms a
**9520-byte configured margin**. It is no longer merely an upper bound inferred
from the bank end. It is still **not approved expansion space**: no chip geometry,
active-bank identity, boot/header validity, recovery behavior or RAM ownership
has been inferred from these declarations.

Artifact SHA-256 values:

```
transcript.jsonl
9b98a908895249d2987ff675b7ebf340898f67437e3f2f5bc8e6f08a6d666043
configuration.json
ba6f56f927bae69ad8144673b878970ea0279a9e96ad89b986f0e76891e58dd7
report.json
604fe44e0ac19b9e510abfd9d47a4dfa285ac23ca2c46dd169263f113aa51762
raw descriptor bytes
d74c3afddf382c36dd4c566c539d2dcff16a22e0c7f525a9c1a342875cc4e12f
```

The report intentionally retains `physical_evidence_verified=false`,
`placement_approved=false` and `flash_authorized=false`. Its parser does not
turn a declared capture label or content hash into provenance/flash approval.

### Placement and OEM OTA route

[Placement evidence](UNIFIED_PLACEMENT_GATE.md) and `whip/fwplacement.py` bind
the actual descriptor to the exact stock, original-25-Hz and V2 code. The OEM
INIT route hard-codes maximum vendor file size `0x24050` (147536 bytes) and
staging address `0x84e000`. Removing the vendor's `0x50` header gives exactly
the observed 144 KiB app/staging limit. The stock boot resolver also reads the
APP size word from this descriptor, under explicitly mocked ROM/header checks.

The deeper OTA witnesses reveal why upload acceptance is not a recovery proof:
the selected write shim returns success despite a failed flash write or mutex
take; continued DATA can credit/acknowledge failed writes and cross the configured
end before a later byte-counter check rejects it. END reaches its next helper
after a mocked failed checksum result. These are selected unchanged application
instructions with flash/ROM operations mocked, not evidence that invalid bytes
would boot, nor a test of a real power-loss recovery path.

Physical chip identity/erase geometry, active-bank/header validity, boot-ROM
copy/recovery and indirect RAM ownership remain unverified. The real image tail
is occupied by its boot overlay. Neither nominal RAM reservation nor a code-size
arithmetic fit allocates safe space for the new objects.

### FIFO completion and app/model representation

[FIFO evidence](UNIFIED_FIFO_EVIDENCE.md) and `whip/fwfifo_trace.py` execute the
actual stock and V2 read/poll/drain paths with explicit peripheral/ROM fixtures.
Partial transfers are correctly reported as failures by the low-level reader,
but the existing drain discards the burst status and can publish the completed
prefix plus cleared zero bytes. It also discards the FIFO overflow bit. Status
and data reads have separate mutex scopes; neither cursor advancement nor a
nonzero sample is a successful complete-acquisition receipt.

The stock encoder, Python decoder and compiled checked-in Swift decoder agree:
native signed FIFO words `(w0,w1,w2)` become model axes `(w2,w0,w1)`, at 8005
counts/g. Signed boundary/random-frame tests pass without a simulator or app
deployment. This closes representation/scale parity, **not model accuracy or
sampling-timing compatibility** for a newly selected source.

Two actual archived captures are assessed and hashed. One contains 208 packets
at about 25 Hz with only one distinct XYZ and an overflow status snapshot; V2's
later capture contains varying 25 Hz packets but no complete per-drain receipts.
Both deliberately remain `qualified=false`. Neither can supply the missing
physical acquisition timestamps, per-burst completion/overflow ordering or a
measured unchanged-Health baseline.

### Concrete stock binding advance and remaining inventory

[Stock binding evidence](UNIFIED_STOCK_BINDING.md) executes actual queue/task,
timer, optical bus, indicator, realtime and activity paths. It corrects an older
lifecycle test fixture: optical control returns **zero on write success**, not
boolean true. The full stock STOP routine ignores errors with either polarity.
The allocator path also dereferences a failed allocation while holding the mutex.

`firmware/unified/stock_binding.{c,h}` therefore implements a small heap-free
RESET/STOP-write helper using the reviewed caller-buffer bus routine. It takes
one bus mutex, attempts STOP even after RESET failure, retains both bus results
and checks release. Its ROM pointer types match the vendor boolean/opaque-handle
ABI. The compiled ARM helper executes against the original stock bus code in
tests. It is **unattached**, exact-stock-only and never emits a successful
`wh_stopped` receipt merely because writes report success.

New counterexamples show late hub/indicator/realtime work can restart optics;
timer stop/delete is not a proven callback-drain fence; a realtime path can
perturb a cached result without a new acquisition; activity stop resets algorithm
parameters and is not a preservation-safe pause. Complete indirect/ROM producer
and result-sink closure, cross-context admission/serialization, and real physical
STOP/current-settings resume remain open. Steps/sleep continuity is not claimed.

### Physical gates and next decision

| Requested check | Outcome of this workflow | Still needed |
|---|---|---|
| Fixed bank0 descriptor | Completed twice, identity/configuration checked, evidence archived | No further pointer following authorized |
| Capacity/placement/recovery/RAM | Descriptor and OEM bounds agree; failure paths executed | Chip geometry, valid linked placement/RAM ownership, ROM copy/recovery evidence |
| Fresh source and model compatibility | Read/completion semantics and app axis/scale parity tested | Passive physical acquisition trace, timing/overflow/completion proof, measured model replay |
| Serialized health binding | Heap-free write helper and concrete lifecycle witnesses implemented | Closed inventory/fences, physical STOP, current-settings resume, steps/sleep continuity |

No safe installed diagnostic currently exposes all the missing physical receipts.
Do not read the FIFO port to obtain them: that consumes Health's source. A passive
bus/debug trace on matching recoverable test hardware is the preferred next
physical evidence path. Instrumented firmware still requires reviewed placement,
RAM, serialization, timing-impact and recovery checks **before** installation;
the need for observability is not permission to bypass those checks on the daily
ring. Any further ring session needs a new bounded plan and client coordination.

Health-default remains the unified design requirement. The installed ring is
still the V2 optical-off image, whose optical health is globally disabled; this
workflow did not restore stock health or change the installed firmware. No
unified image, production capability unlock, app deployment, commit or push was
performed. No physical continuity or flash readiness follows from passing the
offline tests.

### Build validation record

The initial whole-build attempt in `build-20260923-workflow3-final/` failed
closed with 747 passed and one failed test, no success manifest. The resolved
Swift compiler lacked the SDK setup normally supplied by its `/usr/bin` wrapper;
the exact diagnostic was `unable to load standard library for target
'arm64-apple-macosx26.0'`. Supplying the resolved macOS SDK reproduced a successful
compile. The builder now explicitly selects that SDK and fingerprints its
settings; the test surfaces compiler stderr. No test or assertion was removed.
This failed directory is retained as evidence, not presented as a passing build.

The corrected full guarded build is
`firmware/unified/build-20260923-workflow3-verified/`:

- **748 passed in 54.00 s; zero failures, errors, skips or xfails.** Ordered
  collected/executed test identities agree, including setup/call/teardown.
- All seven component objects and two test-support objects were compiled twice
  with identical bytes; the artificial-address ARM ELF was linked twice identically.
- After completion, all **95 hashes** were independently rechecked: 73 source/
  evidence inputs, 19 artifacts and three proof reports. The resolved SDK settings
  hash was checked separately. Compiler/tool snapshots are checked during the build.
- The manifest includes the actual-capture placement assessment and both archive
  FIFO refusal reports. Neither report unlocks its production gate.
- Test ELF SHA-256:
  `65df21f01252ed582feeabe07ee35f26bac568a9443a5ce2b8536381d0a589c0`.
- Manifest SHA-256:
  `193964e1607f9514d77817a0ee22842e22b10803c6c6b9fd4f4dc8715e74b40c`.
- Seven component objects contain 5728 `.text` bytes before real hooks, linkage,
  metadata/alignment and compiler-runtime integration. The STOP helper contributes
  128 `.text` bytes and reports 32 local stack bytes, excluding all callees.
  These are **not** a final image-size/fit proof or a complete stack budget.
- A separate existing firmware/protocol/accelerometer/cleanup invocation passed
  **194 tests in 5.89 s**. No app source changed and no app was deployed here.

Reproduction requires the isolated proof dependencies, pinned Zig 0.15.2, Clang
and Swift/macOS SDK; the output directory must not already exist:

```sh
python -m probe.unified_build --zig /path/to/zig-0.15.2 \
  --output /new/path/to/offline-proof
```

The emulator's JIT required the scoped local run outside this Mac's sandbox.
That approval was for offline tests only. The proof is not hermetic over every
compiler/SDK library, a full ROM/RTOS boot, or physical timing. Nothing in its
success changes the remaining physical gates above.
