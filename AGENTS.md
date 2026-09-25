# Whip — working notes

## BLE recovery and unified-V1 postmortem — 2026-09-25

This supersedes the "current compact unified candidate" claims below. The
flashed transfer used SHA-256 `b1070bed755ce14936501431e379c6c47570ce747265fe0b6af0e87553eb2dc4`.
That image has a proven builder defect: it patched startup call `0x749A`, which
registers UART, instead of `0x74B6`, which registers FEE7. It therefore removed
UART registration while still registering FEE7 over the bytes replaced with
helper code. Never install or rebundle that hash. Whether it became the active
on-ring image is not attested; normal services existed on one uninterrupted
system link before the final forced Forget, and the present silent-radio state
may also involve the stock disconnect/advertising-state race. Do not present
either mechanism as physically proven.

The corrected builder now patches the exact FEE7 call and fingerprints UART,
DFU, DIS, FEE7 and HID setup. Its offline-only output is 137,540 bytes, SHA-256
`7e2b3e2e61906031f5b79262ca39022fc34518ab421f814a586f9e49f8691243`;
154 focused builder/identity/container/recovery tests pass with the pinned
Zig 0.15.2 toolchain, zero skips. It is **not flash-approved** and is not the
recovery path for the currently unreachable daily ring.

The repaired iOS app now tries system-connected UART/DFU peripherals and exact
historical CoreBluetooth identifiers; both iOS and macOS cached direct connects
still received no response. A new exact macOS cached-peripheral latch then waited
the full 300 seconds with zero connection callback and zero characteristic/DFU
writes. `probe.ble_recovery` also provides a guarded Linux raw-HCI
scanner/link test for a dedicated USB adapter. It can reveal name-less, directed
or otherwise OS-filtered connectable advertisements, but cannot connect if the
ring emits none. This Mac has only Apple's internal PCIe controller and cannot
execute raw HCI. See [docs/BLE_RECOVERY.md](docs/BLE_RECOVERY.md). No physical
pad shorting/opening or further firmware write is authorized.

## Emergency handoff — unified V1 revoked, 2026-09-24

The daily ring accepted unified V1 through DFU CHECK/END, then failed to return
a valid R02/UART/DFU advertisement. Charging indication still works, but short
and 15-second charger wakes plus phone and raw laptop scans found no recoverable
ring service. Do not reflash or retry unified V1. Its app install action is
hard-disabled. Recovery now requires a working BLE/DFU advertisement or an
exact RT02CR hardware recovery route; the archived stock OTA image alone cannot
recover a non-advertising application.
All-advertisement near/far and two-window charger-trigger scans subsequently
excluded invalid RSSI, Apple manufacturer beacons and nonconnectable devices;
they found no R02/UART/DFU or nearby connectable non-Apple candidate. Do not
repeat generic BLE scans without a new recovery hypothesis.

Read this before touching the ring or the firmware. It records what has been
measured, what was got wrong along the way, and the traps that cost hours.

## Current compact unified candidate — 2026-09-25

Read [docs/UNIFIED_MODE_V1.md](docs/UNIFIED_MODE_V1.md) first. A size-neutral
Health-default / temporary-Gesture candidate is now built and bundled in the
iOS app. Its SHA-256 is
`b1070bed755ce14936501431e379c6c47570ce747265fe0b6af0e87553eb2dc4`.
It reuses audited `A1 04` to enter Gesture and `A1 05`, then `A1 02` to return
to Health; it adds no protocol, partition growth, or persistent RAM. The 184-byte
helper occupies the retired FEE7 database after its sole registration call is
disabled. Candidate-specific tests pass 71/71; the full iOS suite passes 61/61;
Debug and Release simulator builds succeed. The installed ring is still V2.
This candidate has not been flashed or physically validated. Do not describe it
as completely safe: default Health, dark/fresh 25 Hz Gesture, optical resume,
steps continuity, sleep continuity, and rollback remain physical gates.
Use `python -m probe.validate_unified_mode --address <ring-address>` after the
first reconnect; it is identity-gated and self-cleans raw and realtime-HR modes.

## Latest off-ring storage experiment — 2026-09-24/25

**Newest fit lead, still NOT production:** reusing the retained Colmi UART for
versioned20-byte unified frames eliminates the separate replacement service,
database/discovery/slot/event-gate units while preserving ordinary16-byte
Health UART, DFU, DIS and HID. A reproducible measurement-only link places760
bytes of current functions in gross FEE7 spans and occupies **9484/9520**, only
36 bytes free. Its ingress+clock are fake6-byte fixtures; original connection/
arrival ownership, zero-boot status discovery, send drain, complete FEE7
retirement, placement and behavior are unproved. No accepted source/object or
gate changes. Archive `research-20260925-uart-mux-fit-lead-v1`, report
`231cccf7a85e93a3a9d28b5177adbd5598e7682a61a81b8376d63ec05bcb143d`.
Focused actual-ARM routing:34 passed; all256 legacy opcodes ×3 stock modes keep
the existing policy, matching20-byte requests reach only a fake sink, malformed
20-byte traffic does not dispatch, and DFU bypasses the hook. This does not
qualify the sink or the 36-byte margin.
See `docs/UNIFIED_RESOURCE_BUDGET.md`.

**Newest code-size checkpoint: both broader compiler shortcuts rejected.** All
28 current sources reproduce exact objects. Short enums save72 text bytes but
make `wco_owner`868 instead of required880. Internalized append LTO retains all
38 public no-in-set-caller roots and saves112 text but adds456 unwind: measured
occupancy11188/9520,344 worse than exact baseline10844/9520. Even hypothetical
gross FEE7 790 leaves baseline at least534 over before real missing callbacks/
bindings; approved reclaim remains0. Archive
`research-20260925-whole28-flags-rejected-v2`, report
`8cdcd42e778304624c48e809243c723314e8c53b0abfc197f365d1997d4b94e1`,
538 checked content hashes/three tools. V1 stopped before report and is failed
provenance only. No adopted source/object/image/ring change; all gates open.
See `docs/UNIFIED_RESOURCE_BUDGET.md`.

**Newest device result:** after separate fixed gateway reader passed 444 guarded
checks (150 new), the freshly coordinated physical run completed exactly
122 requests with repeated equality and confirmed disconnect; no sensor or
flash command. ROM0x4926 saves arguments, null-checks and calls through the
named slot. Live slot0x2011d4 is Thumb pointer0x80e401, exactly the previously
captured Upper Stack execution address0x80e400. This closes only the first
gateway boundary, not target dispatch, callback provenance/drain or any release
gate. Device archive `firmware/research/2026-09-25/stack-gateway`, capture SHA
`c8ea5af0fb5ae5a820b71b2e86fbeafac3c1e3e36105bb0c860370347ab96604`.
Preflight archive
`research-20260925-stack-gateway-preflight-v2`, supplement
`b6afabcc24688284b11ef4d3aeb4d5aa002523c792cda1d113c330c222e1ffdf`.
Its synthetic transport artifacts remain fake. The physical run never followed
the pointer; any target read needs a new bounded plan and fresh confirmation.
The separate CLI owns cleanup before connect; v1/413 cases missed inherited
pre-yield cancellation cleanup and are historical. All six gates remain open.
See `docs/UNIFIED_STACK_GATEWAY_READ.md`.

**Newest ingress audit:**107 guarded tests pass (13 new),1178content hashes,
fourtools; archive `research-20260925-control-provenance-v1`, supplement
`6ceacaf36ff5346eb564fcbeb9bb70fedfb99fefe03c02a6f8427518a54a2e24`.
Hypothetical old writes relabeled with current generation after BLE ID reuse
reach software Gesture ENTRY; original generation rejects. Not an observed
ring-stack bug. Require original callback ownership or proven upstream drain,
not a current-ID lookup. SDK's seventh write arg is post-process output, not
context; stock doesn't read it, so its dereference remains unqualified. Core,
wire format, prior178 checkpoint and ring unchanged. See `docs/UNIFIED_CONTROL_INGRESS.md`.

**Subsequent bounded size trial: all five candidates rejected.** Helper splits,
exact bucket remainder and FIFO-headroom multiplication produced whole-module
text/unwind deltas +40/+36/+10/0/+40 bytes; outlining also raised the known
static nested stack chain. Accepted sources/pins unchanged, no new behavioral
test count, ring command or image. Archive `research-20260925-source-size-rejected-v1`,
report `9906db7c9aefbd6c6e84ca9f052b9b6ebd47ede7c11f820846c236f0d5f0d421`.
Do not repeat these as untried optimizations; see `docs/UNIFIED_RESOURCE_BUDGET.md`.

**Newest discovery/startup checkpoint:** actual six-argument `wdr_read` returns
only the initialized20-byte identity view; no Gesture admission or mode change.
Strong `wdr_identity` remains unbound (initialize before service-ID publication,
then immutable); its20 bytes were already planned. Slot/gate/advertising now
also execute together in one persistent ARM test, not full physical boot.
**178 guarded tests pass in30.93s**,1130content hashes/fourtools; archive
`research-20260925-discovery-read-v1`, supplement
`efc06a5a3540d82ad16239aceb54521b383931187ba124b9ce392e9d2a1d90ee`.
Whole28 lower bound10798/9520, **1278 over**, plus callback12 and remainingcode;
six strong bindings missing. No productionELF, allocation, ring/bin or gate change.
The prior27/26-object checkpoints below are historical. See WeChat/read audits.

**Newest WeChat routing checkpoint:** `stock_event_gate` now guards both known
callback pointer roots in the emulator; separate 13 size-neutral advertising
edits remove only the FEE7 service-list entry and preserve manufacturer bytes.
**144 guarded tests pass in 12.92 s**, 994 content hashes/four tools, archive
`research-20260925-wechat-routing-v1`. Whole27 lower bound **10706/9520**, still
**1186 over** before callback12 and remaining bindings. Five strong symbols
remain undefined; no production ELF. Service ID adds1 owned RAM byte to the
1244 planning subtotal. Before ID publication the still-missing dedicated
callbacks must fail closed, never fall through. Retained/computed/direct roots,
full boot/physical discovery and all six gates remain open. No ring/bin changes.
The 26-object checkpoint below is historical; see the linked audit for details.

**Subsequent direct WeChat work:** user approved FEE7-only retirement and asked
Codex to audit it when Claude stopped. Read
[the direct audit and adapter](docs/UNIFIED_WECHAT_RETIREMENT.md).
Unattached `stock_service_slot` compiles; **98 guarded tests pass in5.22s**,
915 content hashes/four tools, archive `research-20260925-wechat-slot-v1`.
All26 known objects lower bound10674/9520 is still1154 over, plus callback
constant12 and remaining bindings; separate ID needs1 owned RAM byte. Five
strong bindings remain absent. No production ELF or gate closes. Crucial
correction: setup ID209e1e differs from shared selectors209df7/209df8; sentinel
alone does NOT disable old routing. Startup also advertises FEE7. Direct scan
gross790 bytes is NOT approved space. Preserve UART/DFU/DIS/HID/Health.

User asks to expedite testing and prepare the final compilation. Codex remains
off-ring. Claude's separately authorized GATT archive now independently verifies
172/172 reads and disconnect; see [GATT resources](docs/UNIFIED_GATT_RESOURCES.md).
The ring Upper Stack differs from the reference mirror. The mirror's presumed
server-init address is inside the ring APP, not its Upper Stack; never transplant
that address. User explicitly accepts retiring WeChat/FEE7 sync, NOT HID or
UART/DFU/DIS. This feature decision is not flash or memory-reclamation approval.
See [timestamp experiment](docs/UNIFIED_TIMESTAMP_STORAGE.md).
Generated low16 motion-queue timestamps pass **44 guarded tests in 17.06 s**,
zero skips/failures/errors, with all 1202 content hashes independently audited. Archive:
`firmware/unified/research-20260925-runtime-stamp16-v1/`.
Supplement SHA: `cfced73f26753b7a0a9fc04bb50f9bcc6922586fb8fb7303895e3bde41cc3914`.

This is NOT adopted core or flash approval. All 32 slots and exact live times
remain; live head age is bounded by 7968 ms, pending stays full32. Prospective
persistent RAM saves64 (1244→1180); wr_next local stack grows8 (24→32), with
physical/nested headroom unproved. All25 rebuilt input lower bound is10608/9520,
still1088 over, with the same three missing physical bindings. Runtime proof
executes; the rebuilt low16 owner has NOT had full downstream integration.
Accepted core, source pins and preceding767 content files are unchanged.
Additional reclamation scans found only hypothetical space; approved reclaim
remains zero. No BLE/bin/deploy/hooks/commit/push, no release gate closed.

## Accepted integrated control-owner checkpoint — 2026-09-24/25

Codex remains **off-ring**; Claude owns separately authorized device work.
Health stays unified boot/default, Gesture temporary/opt-in. No BLE, stock/bin
edit, phone deploy, production attachment, commit or push. All six release
gates stay open. Read [the current checkpoint](docs/UNIFIED_CONTROL_OWNER.md)
and [readiness](docs/UNIFIED_READINESS.md); preceding checkpoints are historical.

Implemented real C `wuw_supervise` → `wco_service` → dispatcher/coordinator,
with fresh time before/after stock work and original-arrival fragment expiry.
Mailbox now holds two 20-byte frames (56-byte state); a third queued frame
closes with FAULT. New actual-ARM owner witness runs selected original stock
Health paths and Health→Gesture→Health with explicit physical/clock/storage
fixtures. It is not the separate 21-object retired-layout witness and does
not prove physical continuity, bounded cadence or production attachment.

Full unchanged main regression: **3251 passed in 424.69 s**, zero skips;
`firmware/unified/build-20260925-control-owner-regression-v1/`, 371 hashes
independently checked, both main ELFs unchanged. The new units are absent from
that main source list. Separate final supplement: **258 passed in 90.35 s**,
zero failures/errors/skips/xfails, at
`firmware/unified/research-20260925-control-owner-v2/`; 767 content hashes
(440 inputs, 324 artifacts, 3 reports), four tools and three support pins.
Supplement SHA: `7dcf4fb5ad98f4798b2e3dc3b9f6a059f9a38bef4a98f37056a16c408eb69a36`.
The v1 tests passed but archive packaging failed on a duplicate pytest symlink;
only v2 has a completed aggregate proof manifest. Old mailbox/wait source pins
below are superseded, not current-source revalidation.

Whole 25-object input-only append lower bound: **10610/9520, at least 1090
bytes over**, same 1894 unowned moved bytes, before final alignment/unwind and
remaining bindings. No production ELF; strict links refuse `wco_bound_owner`,
`wco_bound_stock`, `wco_monotonic_ms`. Real supervisor is no longer missing.
Compiler-only LTO saves only 40 bytes with nine moved objects exact; not a fit.
RAM planning is **1244 = 1164 + identity 20 + mailbox 56 + arrival 4**. Owner 880
already embeds dispatcher 764/coordinator 28/STOP 28: never add it twice. Event 32
is stack scratch; nominal unowned 1224-byte overlay/gap is not an allocation.
Physical source/STOP/current-settings resume, steps/sleep, storage ownership,
recovery, real callback/output ownership and fresh clock binding remain open.

## Preceding mailbox/wait checkpoint — 2026-09-24/25

Codex remains **off-ring**; Claude owns separately authorized device work.
Health stays unified boot/default, Gesture temporary/opt-in. No installed-image
change by Codex. Read [the current checkpoint](docs/UNIFIED_OWNER_WAIT_BUDGET.md)
and [six open gates](docs/UNIFIED_READINESS.md).

New unattached C input mailbox and exact-stock idle-wait wrapper pass **131
guarded tests in 41.44 s**, zero skips/failures/errors/xfails. Final archive:
`firmware/unified/research-20260925-owner-wait-v2/`. Its 279 content hashes
(262 inputs, 14 artifacts, 3 reports), three tools and launcher are guarded.
Supplement SHA: `45b82ad5414076cba77c0af1c5544bb8883135b0a9ad5750bb11b835dbe935fa`.
The pre-hardening v1/125-case result is historical, not the current source pin.

Mailbox text 480 + wait 72 are now included with all prior 22 objects. The whole24
link **refuses** strong undefined `wuw_supervise`: no fake production provider.
The append input-only lower bound is **9782/9520, at least 262 bytes over** before
final alignment/unwind and remaining owner code, using the same 1894 unowned moved
bytes. No new holes, no unwind discard, no full24 ELF or installable image.
Prior 264-byte margin below is only the old 22-object subtotal.

Mailbox needs 32 persistent bytes plus separate 32-byte event scratch. Persistent
planning 1184→1216 is not ownership of the nominal 1224-byte overlay/gap. IRQ-safe
bounded copies do not establish serialized owner, physical fence or deadline.
The wait witness changes one BL only in emulator memory; ROM/body/supervisor
are explicit fixtures. The two new modules execute separate artificial ELFs,
not a full unified switch. Fresh time, real provider, bounded stock work,
physical STOP/source/resume/steps/sleep and recovery remain open.
No BLE, stock/container edits, phone deploy, production admission, commit or push.

## Preceding integrated-retirement/discovery supplement — 2026-09-24/25

Codex remains **off-ring**; Claude owns separately authorized device work.
Health is unified boot/default; Gesture temporary/opt-in. Installed V2 optical-off
is unchanged. All six [release gates](docs/UNIFIED_READINESS.md) remain open.
[Integrated switching](docs/UNIFIED_RETIRED_SWITCH.md) now runs the compiled
coordinator, original Health sample paths and known queued/stored-root retirement
in one persistent ARM context, using the pinned **21-object ELF** and **18
emulator-only instruction edits**. Physical/RTOS/steps/sleep remain fixtures.

[Discovery](docs/UNIFIED_DISCOVERY.md) adds an unattached 20-byte C boot/build
identity format and Swift parser, with no callback, owner or admission.
The full app builds for iOS Simulator; no launch/deployment/device connection.
The separate **22-object/132-function** budget links reproducibly:
**9256/9520 append bytes, 264 left**, plus unchanged **1894 unowned moved bytes**.
Output: `firmware/unified/research-20260924-discovery-budget-v1/`.
ELF: `932203212bae6fd1354030dadba21db3c388d575def6389891da56929fc26e66`.
It has no retirement stubs and is production-rejected. **Never install it.**
Discovery's immutable value would increase the unallocated selected state
planning case from 1164 to **1184 bytes**; no RAM or task owner is approved.

Final guarded supplement: **63 passed in 40.88 s**, zero failures/errors/skips/
xfails, 189 passing phases. **253 content hashes** (238 inputs, 12 artifacts,
three reports), four tools and two support hashes independently checked.
Supplement: `4ec869f67ffe7e25be32152add9451c20c33e6ce389fbe4f7bde53c256180d3a`.
Switch tests use the old 21-object ELF; new 22-object discovery runs separately.
The 3251-test main checkpoint was not rerun; its 371 and prior supplement's 277 hashes
still match. No source list, main ELF, retirement pin or production lock changed.

[Independent stack review](docs/UNIFIED_STACK_EVIDENCE.md) verified Claude's
198/194/454-transaction archives, task windows and known-A5 hashes. Paint does
not establish SP-depth history, future headroom, allocation ownership or
stock-Health workload peaks. No flash/container, stock .bin edit, phone deploy,
Codex ring access, commit or push.

Subsequent source-only binding audits (no C/build changes):
[task map](docs/UNIFIED_TASK_BINDINGS.md) places selected Health scheduling and
consumption in **qc_app**, acquisition/optical work in **hub**, and timer/deferred
callbacks in **Tmr Svc**. qc_app waits indefinitely and may block while servicing
work; it cannot by itself guarantee the 1 s/3 s/10 s deadlines. A bounded
supervisor wake and immutable cross-context handoff remain required.
[Read ABI](docs/UNIFIED_GATT_READ_BINDING.md) has six arguments, no context pointer;
an owned identity lookup is still needed. [Boot-ID source](docs/UNIFIED_BOOT_ID_SOURCE.md)
finds actual stock `platform_random` startup use, but entropy/failure/reset
qualification is absent; the shared software PRNG is not a fresh 64-bit ID.
The separate proposed GATT resource audit was not delivered and is not evidence.
These three audits use stock/public source only; no ring or vendor-guide access.

## Preceding raw-ingress and combined-retirement checkpoint — 2026-09-24/25

Codex stayed entirely off-ring while Claude owned separately authorized device
work. Health remains unified boot/default; Gesture temporary/opt-in. Installed
V2 optical-off is unchanged. Read [the finite gates](docs/UNIFIED_READINESS.md)
and [combined retirement](docs/UNIFIED_STOCK_RETIREMENT.md).

`firmware/unified/build-20260924-raw-ingress-v1/`: **3251 passed in 515.24 s**,
zero failures/errors/skips; **371 content hashes** independently checked
(197 inputs, 171 artifacts, three reports), plus four tools and SDK metadata.
Manifest: `4ab65e86daeab7fee1d186c4fd873fe95fec7dd1dbb3040ba3ba5ee9d37d1cee`.
The 64-byte unattached guard now denies **A1/BF/CE/CD** before the legacy
receive prelude. Both main ELFs are unchanged; this guard and three other
candidates remain unlinked there. Append-only all-code refusal is **11108/9520**,
**1588 over**, before missing hooks. No complete append-only ELF is emitted.

New conditional archive: `firmware/unified/research-20260924-raw-retirement-v1/`.
All 21 objects/130 functions reproduce; **1894** bytes move into nine **unowned**
regions, with **9132 append bytes / 388 remaining**. ELF:
`9cad661e85edd74ebc9f425956aa1937da0dfa9f2f5344ddf20cf9d61109d432`.
A fixed planner pins that whole ELF and describes **16 emulator-only edits**:
15 entry stubs plus the early UART BL. Combined tests cover known queued/direct/
stored roots and selected preserved Health/DFU paths, not all indirect/retained
roots, full switching or physical continuity. The ELF alone still has no stubs.
**Never install it.** No stock/container file is changed or generated.

The separate **55-test guarded supplement passed in 5.57 s** (42 placement,
13 combined), with **277 hashes** checked (228 inputs, 46 artifacts, three
reports), plus tools. Its 1078 policy vectors are not 1078 pytest cases.
Supplement: `5d5c058abbe066ad662946450b986611dafa2d4a1b97f5ce50e2af925f304eac`.
The earlier 59-test supplement and 3212 checkpoint below are historical.

[Independent ROM review](docs/UNIFIED_ROM_RESUME_EVIDENCE.md) verifies Claude's
274/108/178-transaction archives but finds a normal-return continuation into
first-boot initialization; excluding it needs unread context-restore semantics.
Literal `0xd478` is also missing. Equal gap digests across ~4.61 hours prove no
observed net change, not DLPS retention or no writers. RAM ownership, physical
source/STOP/resume/steps/sleep, app identity migration and usable recovery remain
unresolved. All six release gates stay open; no OTA, deployment, commit or push.

## Earlier legacy-filter checkpoint and measured RAM constraint — 2026-09-24

Later off-ring supplement: [conditional whole-code placement](docs/UNIFIED_RAW_RELOCATION_TRIAL.md)
now links all 21 current objects/130 functions, moving **1886 bytes** into nine
**unowned** raw/diagnostic/indicator regions. Append usage is **9132/9520**, 388
remaining before missing hooks. Output:
`firmware/unified/research-20260924-raw-relocation-v2/`. Production rejects it;
old raw entries are NOT retired and this ELF must never be installed. V1 is
historical: V2 fixes immediate object-snapshot timing without changing the ELF.
The separate **59-test guarded supplement passed in 5.28 s**, zero skips;
274 content hashes checked (225 inputs, 46 artifacts, three reports), plus
tool hashes. Its 17 raw-entry tests compare selected real stock Health/command
paths with only two emulator entry stubs; physical algorithms/continuity and
all-entry closure remain unproved. This is not a full 3212-suite rerun.
Supplement manifest:
`da91ae46d68f8060a29b185ec2d1663c4e7a9f725cccdaf8c2e3a754ef8cc9aa`.

Read [docs/UNIFIED_READINESS.md](docs/UNIFIED_READINESS.md) and
[docs/UNIFIED_LEGACY_GATE.md](docs/UNIFIED_LEGACY_GATE.md).
`firmware/unified/build-20260924-legacy-gate-v1/`: **3212 passed in 434.50 s**,
zero failures/errors/skips; all **370 hashes** checked (196 inputs, 171
artifacts, three reports). Manifest:
`cbfd74c0eb2218b5f2e6d5f10570b5dceb811a1c817087fd4c04bd6bf60e3467`.
Both main ELFs are byte-identical to the coordinator checkpoint. The new
56-byte legacy filter is a fourth **unlinked candidate**; exact stock UART
callback/gate tests exercise BF/CE/CD rejection before the stateful prelude.
A1 remains admitted. Dedicated unified identity/app discovery must precede
attachment: retiring CD under the existing V2 identity would poison its CD01
fingerprint and block the app's battery preflight for return-to-stock.

Append-only, all implemented code attempts **11100/9520 bytes**, **1580 over**;
the correct capacity refusal emits no full ELF. Unknown remaining hooks are
additional. [Raw retirement](docs/UNIFIED_RAW_RETIREMENT.md) identifies 1220
conditional bytes, preserving shared Health readers, pools and timer slots;
diagnostics add 476 conditional bytes. Neither is owned or approved for reuse.

Claude completed a separately authorized read-only session: **268 matching
CD01 transactions**, verified disconnect, archive under
`firmware/research/2026-09-24/ram-ownership/`. Archive hashes and its separate
39-test RAM suite were rechecked off-ring. Installed V2 had **264 bytes free
data heap, 104 minimum-ever**, insufficient for the 1164-byte selected unified
state. The nonzero gap was unchanged during one 60-second idle window; that
does not establish ownership, boot/DLPS safety or stock Health's peak usage.

Codex remains entirely off-ring; no firmware-file edit, OTA image, phone
deployment, commit or push. Claude released the device but further device work
needs fresh coordination. Installed V2 optical-off is unchanged. Health remains
unified boot/default, Gesture temporary/opt-in. All six release gates remain
open. This supersedes current counts/sizes below, not their historical evidence.

## Earlier coordinator checkpoint — 2026-09-24

Read [docs/UNIFIED_COORDINATOR.md](docs/UNIFIED_COORDINATOR.md) and the finite
[readiness checklist](docs/UNIFIED_READINESS.md). Coordinated with Claude Code
and parallel implementation/review, entirely off-ring on the Codex side.
`firmware/unified/build-20260924-coordinator-v1/`: **3143 passed in 454.34 s**,
zero failures/errors/skips; all **365 hashes** independently checked
(193 inputs, 169 artifacts, three reports). Manifest:
`00a65e568e1c2900ca83a48a1ffee69adb11ecc1d1f75b0c52cfc8503601e61c`.

A real C coordinator now joins checked one-shot STOP, original-pause-token
software retirement and atomic current-settings Health commit. Partial-entry
resume has a fully-quiet retirement predicate; unexpected masked STOP returns
latch failure. Physical STOP/source, producer/queue drain and fresh scheduler
preparation are still explicit fixtures. Coordinator, Health commit and service
remain **unlinked candidates**. Existing components occupy **9500/9520** bytes;
all implemented candidates together attempt **11044**, **1524 over**, no ELF,
before additional hooks. Candidate persistent state is **1164 bytes**, not owned.

Only the premature pre-coalescing linker assertion was removed; exact MEMORY
capacity stays fixed and final ELF checks are stricter and boundary-tested.
The unowned relocation diagnostic retains its old strict script; its baseline
is 9208 append bytes and excludes the coordinator. Approved reclaimed space
remains zero. Claude's RAM/vendor and code-space evidence is separate, not
proof of exact-ring lifetime or complete fit. The settings-writer audit exposes
legacy BF arbitrary-write bypasses requiring retirement before revision safety.

No Codex ring access, firmware-file edit, OTA generation, phone deployment,
commit or push. The user assigned separate live testing to Claude Code;
Codex must remain off-ring while that session owns the device. Do not infer
its results from this checkpoint. Health remains unified boot/default, Gesture
temporary/opt-in; installed V2 optical-off is unchanged by this batch. No
release gate is fully closed. This supersedes current counts/sizes below.

## Earlier parallel layout-candidate checkpoint — 2026-09-24

Coordinated directly with the active Claude Code peer: separate RAM/code-space
research, service implementation, relocation experiments and independent review.
Read [docs/UNIFIED_READINESS.md](docs/UNIFIED_READINESS.md) and
[docs/UNIFIED_RESOURCE_BUDGET.md](docs/UNIFIED_RESOURCE_BUDGET.md).
`firmware/unified/build-20260924-layout-candidates-v1/`: **3060 passed in
327.59 s**, zero skips/failures/errors; all **357 hashes** independently checked
(190 inputs, 164 artifacts, three reports). Manifest:
`ad5ad8705c40cd68e7dc1a9e4064c7a4001ab0ce9baeb824e44946d10cc36512`.
Both main ELFs remain byte-identical to the prior checkpoint. Health commit
and the new 240-byte service database are separate unlinked candidates.

An explicitly unowned scattered-placement diagnostic moves 408 bytes into
hypothetical indicator holes and includes Health commit: 9176 append bytes,
344 configured bytes remain. The production verifier rejects this layout.
Adding the service **fails the unchanged link bound**; archived failed-map
arithmetic is not a successful fit. Exact LLD source explains provisional
unwind sizing before coalescing. No bound or production verifier was relaxed.
Claude's RAM audit has 15 separately passing tests, but its overlay/gap candidate
does not establish ownership, retention or recovery. Approved reclaimed space
remains zero. No complete coordinator/hardware bindings or installable image.
No ring access, stock-file change, flash, app deployment, commit or push.
Installed V2 optical-off is unchanged; Health remains unified boot/default.
All six release gates remain open. This supersedes current counts below.

## Earlier parallel-integration checkpoint — 2026-09-24

Read [docs/UNIFIED_READINESS.md](docs/UNIFIED_READINESS.md) and
[docs/UNIFIED_RESOURCE_BUDGET.md](docs/UNIFIED_RESOURCE_BUDGET.md).
`firmware/unified/build-20260924-parallel-integration-v1/`: **3004 passed in
218.01 s**, zero skips/failures/errors; all **265 hashes** independently checked
(180 inputs, 82 artifacts, three reports). Manifest:
`fae04b2e10e1ddc1b6a645db0cac72c43d5c98d274320b5a50c1bbd4cd02a040`.
Both main links and archived objects reproduce. This supersedes current
counts/sizes below, not physical or release gates.

Temporary delivery scratch is **64 bytes**, down from 208, by the proven
eight-bucket bound within the unchanged <250 ms window. All 32 input frames
and the 32-sample persistent queue remain. Measured observation nested stack
is **244 bytes**; receipt-on-stack planning is **532** before outer/interrupt
use. Persistent state plus receipt remains **1084**, not an approved RAM fit.
Existing linked components use **9468/9520** bytes, 52 remain; complete fit fails.

The persistent switch runner now executes the stock notification wrapper for
replies/motion. ROM acceptance, buffer lifetime/draining and physical transition
evidence remain fixtures. The new [Health commit guard](docs/UNIFIED_HEALTH_COMMIT.md)
checks current settings and commits software Health under one critical section.
It is a **separate unlinked candidate**: 196 text bytes, full addition rejected by
the unchanged APP bound. Neither main ELF contains it. A revision owner, fresh
scheduler resume, all hardware hooks and their complete memory budget are absent.
Its 16-byte preparation plus separate revision word need owned storage too.

Parallel independent reviews found no blocking defects under stated contracts.
[Vendor references](docs/UNIFIED_VENDOR_RECOVERY_LEADS.md) document a family ROM
bypass, not a proven recovery route for RT02CR_V3.1. No ring access, stock-file
change, flash, app deployment, commit or push. Installed V2 optical-off stays
unchanged; unified Health remains boot/default and Gesture temporary/opt-in.
No release gate is fully closed; no installable unified image exists.

## Earlier source-storage checkpoint — 2026-09-24

Read [docs/UNIFIED_READINESS.md](docs/UNIFIED_READINESS.md) for the finite six
release gates and [docs/UNIFIED_RESOURCE_BUDGET.md](docs/UNIFIED_RESOURCE_BUDGET.md)
for the exact handoff. Source-level receipt/progress compaction is implemented:
receipt **480→288 bytes**, selector local frame **184→112**, observed integrated
observation nested stack **460→388**. All 32 input frames, exact millisecond
bounds, output queue capacity and failure behavior remain; ages are encoded by
checked `ws_set_bounds` relative to final status time, never unchecked casts.
Only transactional progress is copied on stack, not the immutable profile.

`firmware/unified/build-20260924-source-storage-v1/`: **2912 passed in 191.86 s**,
zero skips/failures/errors. Both links reproduce; all **260 hashes** independently
match (177 inputs, 80 artifacts, three reports). Manifest:
`f6790c649e7213b60aaf2a59b10ea945eaa8b65ab9675161b2401117411e0b95`.
This supersedes current counts/sizes below. Prior/new ARM differential tests,
131072 raw age-pair cases and 65536 FIFO status/count cases are included, not
physical source evidence. Integrated Health → Gesture → Health still uses
explicit fixtures for hardware/coordinator boundaries.

Components now occupy **9464/9520** configured bytes (56 remain), not a complete
image. State remains 796 bytes; persistent receipt scratch would total **1084**,
still 60 beyond the unapproved 1024-byte gap. Receipt-on-stack planning is
**676** before outer caller/interrupts, not a proven task budget. A six-entry
service database alone would take append usage to 9632, **112 over capacity**,
before its other code and the remaining hooks. Reclaimed stock space stays zero.
Compiler flags, unwind metadata, linker script/bounds and ELF verifier are
unchanged. Early failing draft links are not successful checkpoints.

No ring access, OTA generation, stock-file change, app deployment, commit or push.
Installed V2 optical-off is unchanged. Health remains unified boot/default,
Gesture temporary/opt-in. Physical pause/resume, source freshness/model, steps/
sleep, RAM ownership and recovery gates remain open. Next source-memory candidate:
prove maximum selected batch size before reducing delivery scratch; its current
208-byte witness is unchanged. This cannot substitute for whole integration.

## Earlier integrated-switch checkpoint — 2026-09-24

Read [docs/UNIFIED_READINESS.md](docs/UNIFIED_READINESS.md): the finite six-gate
checklist and whole-image budget now lead the work, not isolated test counts.
`firmware/unified/build-20260924-integrated-switch-v1/`: **2883 passed in
179.35 s**, zero skips/failures/errors; all **258 hashes** independently checked
(175 inputs, 80 artifacts, three reports). Manifest:
`6d6c8a5ee06f89f9c91231688362274913871a0d9e1e0087bf249492463f8119`.
This supersedes current counts below. Both links reproduce; the production
component ELF is unchanged from the I/O checkpoint.

New runner joins wire commands/replies, controller/lifecycle C, original optical
read/clear/TX, guarded HR stores and original motion consumer in ONE persistent
ARM state. Health → Gesture → Health executes, but inventory, physical source/
STOP, draining, transport and fresh scheduler setup remain NAMED FIXTURES.
Same motion-consumer inputs through eight phases do not prove steps/sleep.
Retirement must use the original Health pause token, not HOLD's newer token.

Whole-image fit is NOT established: existing components use 9480/9520 bytes;
a stock-shaped six-entry service table alone adds 168, exceeding append capacity
by 128 before the remaining hooks. Current state is 796 bytes, input receipt
480, and observed observation nested stack 460 (not the older two-frame sum of
440). None is approved RAM; the 208-byte output scratch is already in stack.
Approved reclaimed stock space remains zero. Resolve the integrated allocation
before more one-helper-at-a-time squeezing. Source/reference review found another
exact upstream-base match, not vendor application source or proven recovery.

No ring access, stock file change, production gate, app deployment or flashing.
Installed V2 optical-off is unchanged. Health is unified boot/default; Gesture
is temporary/opt-in. Full tests at integration checkpoints, focused tests during
edits. Further hardware work needs a new bounded plan and coordination.

## Earlier optical-I/O checkpoint — 2026-09-24

Completed before starting the user-requested integrated-switch milestone.
Read [docs/UNIFIED_OPTICAL_IO.md](docs/UNIFIED_OPTICAL_IO.md).
`firmware/unified/build-20260924-optical-io-v1/`: **2868 passed in 183.28 s**,
zero skips/failures/errors; **257 hashes independently checked** (174 inputs,
80 artifacts, three reports). Manifest:
`f04a5dd7dab093f3c02cb375737583cc348637e09463298e1bea625ad164cc48`.
This supersedes current counts/sizes below; earlier builds remain historical.

Compiled C `woi_samples_io` uses caller-owned buffers and checked take/bus/give
results, with no allocation or automatic recovery. A pinned two-BL plan redirects
the selected stock sample reader in emulator memory only. Both edits are needed;
`wop_read` alone does not install them. Other stock I/O paths retain old defects.
FE/FF still have separate mutex scopes, not atomic acquisition. Source identity,
buffer lifetime, physical completion/STOP and fresh-job resume remain unproved.

Components occupy **9480/9520 configured bytes**, leaving **40**; state remains
796 bytes, with no approved RAM/stack ownership. This is not complete image fit.
Read nested stack is 336 observed bytes excluding substituted internals; control
reply local stack drops from 72 to 32 bytes. The host-only motion validator moves
to test support; all production incoming-control validation remains. No queue,
safety predicate, unwind metadata or compiler flags were removed.

No stock file, installed V2, construction gate or hardware state changed.
Health is the unified default, Gesture temporary/opt-in. No installable image.
Next milestone: integrated Health → Gesture → Health using actual stock paths
where possible, explicit fixture boundaries, a whole-image budget and finite
readiness checklist. Full regression/reproducibility runs belong at integration
checkpoints; focused tests during edits. Exact vendor references/source are in
scope, but a similar SDK is not evidence of ring-code equivalence.

## Earlier integrated component handoff — 2026-09-24

Reference policy reaffirmed by the user: use functioning firmware's actual
behavior as the reference. Rechecked all five current image hashes and compared
payloads: upstream 50 Hz, local 33 Hz and original 25 Hz differ ONLY at `0x2248`
within `0x450..EOF`. This supports shared code/layout within that lineage, not
health/timing equivalence at different rates. Stock 3.12.02 has a different map;
V2 changes 81 payload bytes and globally disables optics, so it is not a working
optical-Health baseline. Keep stock Health/steps/sleep code as the unified base;
use the measured motion images as references, not unconditional patch donors.

Latest device session: after the user's new connection request, the fixed
create-hook retry completed **359 matching CD01 transactions**, repeated
header/code equality, final state/header/config/idle checks and verified
disconnect. Archive: `firmware/research/2026-09-23/rom-create-hook/`; exact replay
passes. All 224 preflight hashes and 226 selected tests passed before connection.
The earlier 170-request/169-reply `0x73` abort remains separately archived and
its subtype/cause remains unknown. No sensor/flash command, filter bypass or
automatic retry. This session ended; further device access needs new coordination.

Captured patch prefix declares RAM `0x203800..0x206d10`, source `0x1809404`,
length `0x3510`, payload `0x9528`; these are not ownership/copy/recovery proofs.
Off-ring captured-body execution now runs the actual wrapper/hook/default/
divider/native-create path. Successful creation installs a new identity/callback
but does not START. Empty-handle failure calls unread `0x111a6`
(`vTimerCreateFailedHook`); do not assume it safely returns failure. A null
output pointer reaches an unadmitted zero-address read; wrapped large periods
consume allocation before asserting. Hook handled=1 is not operation success.
Pool/list/critical boundaries remain synthetic. Comparator `0x8e24..0x8e46`
and selected APP/patch header checks execute, not payload authentication or
recovery. Neighboring code/literals remain forbidden. No production resume
binding, physical gate or continuing hardware authority follows.

Read [docs/UNIFIED_RESOURCE_BUDGET.md](docs/UNIFIED_RESOURCE_BUDGET.md) and
[docs/UNIFIED_HEALTH_CANCELLATION.md](docs/UNIFIED_HEALTH_CANCELLATION.md).
This supersedes earlier build counts and sizes. Component development was
off-ring; the separately coordinated diagnostic below changed no firmware.
Installed V2 optical-off is unchanged; Health remains the unified boot/default.

`firmware/unified/build-20260924-optical-work-v2/`: **2812 tests passed** in
188.17 seconds, zero skips/failures/errors; all **248 hashes** checked (170 inputs,
75 artifacts, three reports). Components occupy **9468/9520 configured bytes**,
leaving **52**. Dispatcher/frame/fence remains **796 bytes**, with 228 nominal
aligned RAM bytes remaining. Neither complete integration fit nor RAM/stack
ownership is approved. Both ARM ELFs change and reproduce identically.
Manifest: `a9ce16455f17c1c0a55d2d6af22f21ec96ad1e2e1edf5ecb28c6528a1d4613e2`.

Read [docs/UNIFIED_OPTICAL_WORK.md](docs/UNIFIED_OPTICAL_WORK.md). New unattached
C `wop_read` keeps an original shared-sensor acquisition in flight, executes
stock's real sample reader, preserves surfaced nonzero statuses and rejects
late zero after pause. `wop_retire` runs the stock software clear only after
fully evidenced PAUSED, even when old ready is zero, then clears four flags.
It does not flush hardware FIFO, assign source provenance or complete resume.
The 59 compiled-ARM integration cases, 15 stock-sample witnesses and four shared-
codec cases are included in the full count. Modeled read/retire nested stack
peaks are 352/56 bytes; retirement has 5417 masked instruction boundaries, not
qualified physical latency. Stock allocation/ignored-release-result limitations,
real producer identity, physical STOP and steps/sleep continuity remain open.

Shared existing checked bodies and one byte-wise wire codec recovered space;
no predicate, queue capacity, unwind data or compiler flag was removed. Net
linked growth is 116 bytes; no static RAM or stock bytes changed. The earlier
`build-20260924-optical-work-fit-v1/` is a retained failed APP-bound link with
no success manifest. No production/construction gate opened and no ring access
occurred. Only 52 configured bytes remain; complete hooks/service/bindings still
need fit/ownership approval. This is not an installable firmware.

The preceding optical-acquisition build passed 2734 tests with 239 checked
hashes at 9352 component bytes; its audit and manifest below are historical.

Read [docs/UNIFIED_OPTICAL_ACQUISITION.md](docs/UNIFIED_OPTICAL_ACQUISITION.md).
Selected actual status/parser/classification and mutex/RX paths now replace
former mocks. Failed reads can still yield top-level zero and parsed/read flags;
cached calls can return zero with no read. Never derive measured provenance from
those flags/returns or a plausible cached value. All nine modeled reads can fail
while cached-ready/algorithm fixtures reach HR stores; this is not a physical
health observation. Completion's `0xedda` operation is RX, not a control write;
the former harness label is corrected. Source/algorithm/job association and
sample-buffer retirement remain unbound. The 29 new cases pass in a 61-test
focused run; both ARM ELFs match the preceding HR-commit build. No C, stock
bytes, memory allocation or gate changed; no ring access occurred here.
Manifest: `2de14d67ced3621281a69c615f1db9bc04571328d712373b831e99fa5629503b`.
The next bounded source path (`0x10610` / `0x11994`) is in the pinned stock
image; further off-ring analysis does not require another ring connection.

Read [docs/UNIFIED_HR_RESULT_COMMIT.md](docs/UNIFIED_HR_RESULT_COMMIT.md).
Unattached `wrc_commit_hr` protects exactly four stock positive-HR-result stores
with a bounded original-ticket/provenance check under preserved PRIMASK. It
rejects exception entry and adds no static RAM. Its 60 actual-ARM cases include
stock-store equivalence, lifecycle/stale-ticket rejection, all 64 modeled pause
instruction boundaries and missing-mask/restore mutants. The 92-test focused
run overlaps the full count. Observed nested stack peak is 56 bytes, not real
task headroom. Original producer identity, measured provenance and metric/job
association remain caller obligations; no production inventory was assigned.
Other result/publication paths and real hardware fences remain unbound. Never
install a closed guard over default Health when its inventory is unresolved.
That preceding implementation changed both ARM ELFs (+80 bytes of C), not
stock bytes or compiler flags. Its historical manifest:
`954c042ddf9f9ecca308c8fe8fc25f1c34bbe6751363d6bd7b61f9cc374bad07`.
The earlier 32-case optical audit and 121 hook/comparator cases remain included.
Optical-dispatch v1 was deliberately interrupted before terminology correction
and has no success manifest; it is not a passing build.

Read [docs/UNIFIED_OPTICAL_DISPATCH.md](docs/UNIFIED_OPTICAL_DISPATCH.md).
GPIO/software producers `0xd8f0/0xd9f8` post untagged `(3,0,0)`; hub processing
goes through `0xf7a8/0xf774/0xf308`, not ordinary enable. Under synthetic cached
ready/algorithm fixtures, late processing after STOP can restore HR/SpO2 result
state with zero owners and no new RUN, and SpO2 can reach later aggregation.
Actual `0x10f56` early status is ignored; the physical cause of its status bit
is not established. Completion clears lower flags, not the published HR cache.
Immediate C5/raw-report sinks also exist. Entry-only checks lose a mid-call
pause race; assigning a current ticket at dequeue relabels old work. Original
identity and real commit/IRQ/hub/publication fencing remain required. This is
not an installed guard, source-provenance flag, complete inventory, physical
observation or another ring session. No production inventory mask was enabled.

Read [docs/UNIFIED_STATUS_NOTIFICATIONS.md](docs/UNIFIED_STATUS_NOTIFICATIONS.md).
Off-ring execution proves three stock/original25Hz/V2 constructors share `0x73`
with different subtypes; selected callers include motion, SpO2 aggregation and
device state. Getters/transport remain explicit fixtures, not physical-cause
proof. The failed archive lacks a subtype and cannot be retrospectively decoded.
Code readers now log only type/length/checksum validity, valid `0x73` subtype
and host time; no health values/checksum value/raw payload. EVERY foreign packet
still aborts, including valid `0x73`. No filter, retry or address/budget change.
The separate passive observer has the same redacted metadata (v2), no UART
writes, and has NOT run. 35 new cases plus one passive case are included in
2491; 20 separate protocol/cleanup tests pass. Both ARM ELFs are unchanged.
This is better observability, not a completed inventory or flash approval.

Read [docs/UNIFIED_TIMER_RESUME_READ.md](docs/UNIFIED_TIMER_RESUME_READ.md).
Captured kernel rearm preserves old callback/ID; stale START/RESET can invoke that
callback immediately, and native zero-period CHANGE mutates state before asserting.
These are synthetic native-tick/queue/list witnesses, not safe job resume or ms
conversion. No production rearm API was added; both ARM ELFs match the prior build.
After fresh user confirmation, `probe.rom_read --timer-resume-code` completed:
180 matching CD01 transactions, all 452 new ROM bytes read twice equally,
matching prerequisites/known STOP/postchecks and verified disconnect. Archive:
`firmware/research/2026-09-23/rom-timer-resume/`. Exact offline replay passes.
Preflight reran 540 selected tests and all 209 prior-build hashes matched before
connection. The current build includes the archive replay and 79 new captured-
code execution cases; both ARM ELFs remain byte-identical to the prior build.
Captured literals locate create/start/restart hooks at `0x201644/48/4c`;
their values were NOT read in that earlier session (see the later support read
below). Physical resume remains unresolved. That session had no hook-state RAM, pointer following, sensor-start,
target execution, flash, retry or reconnect. CD bookkeeping effects remain.
This session ended and the user may reopen clients; further device work needs
a NEW bounded plan and exclusive-idle confirmation. No construction gate opened.

Captured native create consumes an allocation before asserting on zero period;
no rollback occurs before the unread assertion boundary. Valid native creation
replaces callback/ID but does not start the timer. Hook fallback arguments and
exact queue-result handling execute correctly under explicit substitutes.
Large requested periods can wrap to zero under the assumed division/config
fixtures; restart can enqueue zero and report acceptance under those fixtures.
These conditional conversions are NOT a proven tick rate or physical hazard
measurement. The future binding must validate native periods before allocation/
enqueue and independently prove object lifetime and fresh-job admission. No
production create/rearm API, hardware binding or approved timer pool was added.

Read [docs/UNIFIED_SUPPORT_READ.md](docs/UNIFIED_SUPPORT_READ.md). The separately
requested support diagnostic completed **284 matching CD01 transactions**:
616 new ROM bytes and 17 fixed non-secret state bytes, each twice; known-code
comparisons and final idle/config checks passed, followed by verified disconnect.
Archive: `firmware/research/2026-09-23/rom-support/`. No sensor/flash/reset,
target execution, returned-pointer following or automatic retry. CD bookkeeping
effects remain. Preflight passed 134 tests and all 215 prior-build hashes matched.
The earlier zero-command discovery failure remains in `rom-support-not-found/`.
A preceding separate battery-only session reported 99%, not charging.

Observed inhibit is zero, rate configuration 100, and create/start/restart hooks
are **(0x205c01, 0, 0)**. The nonzero create-hook target was NOT read or followed
in that support session; it was acquired only by the later separately bounded
session described above.
Never substitute the ROM create default for that actual live wrapper path.
The new unsigned arithmetic helper and IPSR context selector execute off-ring
without those former mocks. Direct create-default tests confirm rounding/wrap
under captured configuration, but bypass the unread hook and retain synthetic
pool/list/critical-section boundaries. START/restart use real literals/context
with captured zero hooks; queue/tick behavior remains substituted. These are
not atomic/immutable state, physical cadence or safe resume proofs.
OTA-table-header magic checks use captured constants. The support-only APP test
stops at its missing comparator; later separate-capture tests above execute it.
No geometry/recovery approval follows. The 60 then-new
offline cases include exact archive replay and 59 instruction cases.
Both device sessions ended. Further ring access needs new bounded coordination;
no construction gate opened or production hardware binding was added.

Read [docs/UNIFIED_CREATE_HOOK_READ.md](docs/UNIFIED_CREATE_HOOK_READ.md).
The pinned SDK initializer installs create hook `0x206359`, NOT the ring's
observed `0x205c01`; matching ROM UUID is not patch-code equivalence. The new
`--timer-create-hook` diagnostic plan requires, after 279 matching
prerequisite transactions, repeat a fixed 52-byte non-secret ROM-patch prefix.
Only if its identity/declared containment checks pass, read fixed 256-byte RAM
hook and 128-byte ROM comparator caps twice, then state/header/config/idle
postchecks. Exactly 359 transactions; no keys, MMIO/FIFO, returned-pointer
following, target execution, sensor/flash/reset, retry or reconnect. CD
bookkeeping effects remain. Caps are not function closure; header declarations
are not runtime-copy, RAM ownership or recovery proof. All 132 new preflight
cases pass within a 789-case focused run. Fresh exclusive-idle confirmation is
required for another attempt; neither completed session grants ongoing access.
The corrected v2 preflight includes every new case; both ARM ELFs are unchanged.
V1 is a retained pre-correction build (ROM-byte summary omitted a four-byte
known caller; now derived as 1282). Addresses and transaction budget did not
change. Both builds preceded the later aborted device attempt recorded above.

Read [docs/UNIFIED_STOCK_SETTINGS.md](docs/UNIFIED_STOCK_SETTINGS.md).
Unattached `wss_read_controls` snapshots four exact-stock bytes under bounded
PRIMASK preservation: HR interval `0x208aac`, controls `0x208aad`, mode `0x208c44`,
time-set `0x208c46`. The 25 Hz/V2 map differs. No settings/clock/history writes,
heap or static RAM; +48 linked bytes, eight-byte local ARM frame. This is not a
monotonic revision, complete Health-settings snapshot or resume receipt.
Actual stock getters/setters and minute selection execute with synthetic clock,
wear/charge/queue/timer/bookkeeping boundaries. The whole minute handler consumes
pending time and does not replay crossed due minutes; keep non-optical work alive.
Fresh job starts reset working state, and owners 0x200/0x100 share a write at
`0x20c0fa`. Do not implement resume by restarting old timers or calling the whole
minute handler. A complete serialized fresh-job resume remains unimplemented.

Read [docs/UNIFIED_INDICATOR_RETIREMENT.md](docs/UNIFIED_INDICATOR_RETIREMENT.md).
Ten indicator entries are replaced only in emulator memory; tested late callbacks
cannot request LEDs, while selected stock Health starts and command replies match
unmodified controls. All non-entry bytes, timer helpers, literal pool and boot
overlay remain intact. The potential 764-byte body reuse is NOT approved space;
computed/indirect references, full boot/retention and real STOP remain unresolved.
This is not a live hotpatch and does not shut down pre-existing optics/timers.
Do not delete indicator jobs from the production inventory based on these tests.

Lossless tap storage compaction retains all 32 samples and the same output/
failure behavior. Oldest sequence is derived from conserved FIFO counters,
not stored per entry. This saves 192 RAM bytes and 40 linked flash bytes.
57 ARM cases also match the actual archived pre-change ELF; native sanitizer
stress includes 100,000 interleaved operations. No queue capacity, freshness,
timestamp, overflow or sequence-exhaustion protection was reduced.

Unattached `wht_stop_reviewed` checks twelve mapped timer slots: the original
five scheduled jobs plus realtime, on-demand 0x1e, wear, activity, raw and both
indicator timers. The original five-job API retains its bounds. Individual
STOP failures are preserved; no handles/state/settings/history are cleared.
Captured-ROM tests show twelve accepted STOPs precede the timer barrier, but
a failed STOP can leave its timer active even when a later barrier completes.
Never use the barrier alone as a successful cancellation receipt.

This is not a closed producer inventory or complete pause/resume adapter.
Activity/wear timers have additional duties; do not blindly pause all twelve
in production. Real serialization, hub/IRQ/RUN/result fences, physical STOP,
current-settings resume, memory/recovery and physical FIFO/model/steps/sleep
continuity remain open. Compiler flags and stock bytes are unchanged; no
construction gate opened or final OTA image produced. Further ring
access needs a new bounded plan and fresh exclusive-client coordination.

## Earlier checked-health cancellation — 2026-09-23

Read [docs/UNIFIED_HEALTH_CANCELLATION.md](docs/UNIFIED_HEALTH_CANCELLATION.md).
This supersedes older build counts and sizes below. Entirely off-ring; installed
V2 and locked production/construction gates are unchanged. No final unified
firmware, complete health adapter, memory/recovery approval or physical trial.

`firmware/unified/build-20260923-health-cancel-v1/`: **1648 tests passed**, zero
skips/failures/errors; all **192 hashes** checked (128 inputs, 61 artifacts,
three reports). Components occupy **9220/9520 configured bytes**, leaving **300**.
Dispatcher/frame/fence still totals 988 bytes; no RAM allocation is approved.

New unattached `wht_stop_scheduled` validates the five reviewed scheduled-health
timer slots, queue/pool bounds, timer number and allocation bit before submitting
STOP with zero wait. It preserves handles/state and accepts only ROM result 1.
It requires a caller-proved serialization/lifetime domain through enqueue;
PRIMASK snapshot protection alone is insufficient. Compiled C and captured ROM
execute five STOPs before the timer fence acknowledgment under a synthetic FIFO.
This is not full optical cancellation, physical STOP or current-settings resume.
Realtime/wear/activity/raw/indicator producers and all result sinks remain open.

Do not reclaim the apparent raw/debug region wholesale: it shares constants/
epilogue and has neighboring startup/OTA dependencies. No bytes were reclaimed.
Physical FIFO/model/step/sleep testing and usable recovery remain required;
fresh coordination and an exact bounded plan precede any further device access.

## Earlier captured-ROM integration — 2026-09-23

This supersedes the older build counts/sizes and unread-ROM claims below.
Read [docs/UNIFIED_STOCK_INTEGRATION.md](docs/UNIFIED_STOCK_INTEGRATION.md).
Entirely off-ring: no connection, sensor/flash command, deployment, commit or push.
Installed V2 optical-off is unchanged. Unified Health remains boot/default and
Gesture opt-in; no installable unified image or production capability exists.

`firmware/unified/build-20260923-captured-rom-v1/` passes **1588 tests**, zero
skips/failures/errors; all **185 hashes** checked (125 inputs, 57 artifacts,
three reports). The successful 974-transaction ROM archive/replay is included.
Actual-address components occupy **8892/9520 configured bytes**, leaving **628**;
dispatcher/frame/fence remains **988 bytes**, 36 nominal RAM bytes remaining.
Neither figure approves ownership, complete integration fit or physical safety.

The captured ROM timer-pend wrapper asserts on a null queue. The unattached C
fence now guards the exact queue slot `0x201478`, permanently refusing enqueue
if absent. Compiled C -> captured pend/dispatch -> compiled acknowledgment is
executed together; queue kernel/scheduling remain explicit synthetic fixtures.
Captured generic STOP/DELETE exposes deliberate null writes for invalid handles;
STOP can enqueue a pool-aligned unallocated handle. Handle lifetime/ownership
must be proved before cancellation. Timer acceptance is not completed shutdown.
The RAM-layout helper only writes configuration; the boot error helper stores
a bounded status byte. Neither proves RAM ownership or recovery. Valid-looking
headers reach unread literals and fail the offline proof rather than inventing
successful validation. No new physical evidence or construction gate opened.

Still required: queue/hub/IRQ/RUN/result fencing and full health bindings,
current-settings resume, qualified physical source/model and steps/sleep
continuity, complete flash/RAM placement and recovery. Further device access
needs a new bounded plan and coordination; the earlier retry ended.

## Earlier stock-address implementation — 2026-09-23

This section supersedes the older unified-workflow build numbers and RAM/code
sizes below. Read [docs/UNIFIED_STOCK_INTEGRATION.md](docs/UNIFIED_STOCK_INTEGRATION.md)
and [docs/UNIFIED_BOOT_REFERENCE.md](docs/UNIFIED_BOOT_REFERENCE.md).
Health remains the required unified boot/default, Gesture temporary and opt-in.
Installed V2 optical-off is unchanged; optical health is still globally disabled.

The full guarded build `firmware/unified/build-20260923-stock-address-v1/`
passes **1495 tests, zero skips/failures/errors**. All **179 hashes** were checked
(119 inputs, 57 artifacts, three proof reports). It includes artificial-address
and real-address ARM component execution, native sanitizers and compiled Swift
checks. No new simulator/legacy-regression run, app deployment, commit or push.
The real-address component ELF starts at `0x847ad0`, preserves all stock bytes
including the boot overlay, and occupies **8868 of 9520 configured bytes**,
leaving **652 bytes**. It is NOT a complete stock-hooked image or OTA container.
RAM profile deduplication reduces adapter to 864 bytes and dispatcher to 956;
dispatcher + 20-byte frame + 12-byte timer fence totals **988 bytes**, leaving
only 36 nominal aligned bytes. No RAM ownership or complete integration fit is
approved. A separate LTO experiment was rejected; do not treat it as a build.

The new unattached timer-daemon fence calls the mapped ROM enqueue API, keeps
boot-lifetime ticket storage, preserves PRIMASK, and rejects stale/wrapped/failed
requests. An enqueue/abandon/reentry race is fixed and executed in ARM tests.
Actual ROM queue semantics, hub/IRQ/RUN/result fencing and physical STOP remain
unproved. Never turn this timer receipt alone into a health quiescence receipt.

The prior boot comparison completed 182 matching CD01 transactions and verified
disconnect; only the 52-byte non-secret header and 528-byte factory/OEM checker
were compared. Both matched the SDK reference. No key fields were read; matching
one checker does not establish full boot recovery or the SDK board's memory map.

A subsequent newly coordinated 6076-byte ROM plan **aborted**: 189 requests,
188 matching replies, unrelated UART traffic at request `0x4f8e`. Only 1302 new
bytes returned once; no new window passed repeat/postchecks. No retry/reconnect
or success capture. Archive: `firmware/research/2026-09-23/rom-integration-aborted/`.
The old abort logger did not record packet type or verified disconnect; do not
invent them. Cleanup ran and the process ended. New failure logs retain only
packet type/length and backend-disconnect state, with abort behavior unchanged.
A separately coordinated passive check then completed **60 seconds with zero
notifications and zero UART commands**, followed by verified disconnect.
Archive: `firmware/research/2026-09-23/idle-notifications/`. The earlier packet's
type/cause remain unknown; quiet passive traffic does not qualify CD01 behavior
or allow ignoring foreign packets. No code-read or sensor/flash command occurred
in that passive session.

The user then explicitly requested one retry and freshly confirmed client
closure. It **completed 974 matching CD01 transactions**, all **6076 fixed ROM
bytes read twice with equal results**, configuration/idle postchecks and verified
disconnect. Archive: `firmware/research/2026-09-23/rom-integration/`. No sensor,
flash, key-field, MMIO/FIFO, pointer-following or target-execution operation.
The unchanged reader/references passed 378 preflight tests; exact archive replay
and the retained abort archive passed separately (2 tests). Firmware and the
older 179 build hashes remain unchanged; the new archive/test are outside that
1495-test manifest. Timer API code is now captured for off-ring review, not a
completed RTOS/hardware fence. Some header literals/callees remain unread.
No production gate opened. This retry ended; future device access needs a new
bounded plan and coordination. See the stock-integration handoff for hashes.

Production transport/construction remain locked. Chip/erase/recovery and RAM
ownership, a physically qualified source/model replay, complete stock health
bindings, current-settings resume and steps/sleep continuity remain open.
Passing offline tests or fitting configured bytes does not close these gates.

## Earlier unified-workflow handoff — 2026-09-23

This section supersedes conflicting historical firmware/app claims below.
Read [docs/UNIFIED_WORKFLOW_3.md](docs/UNIFIED_WORKFLOW_3.md), its linked audits,
the [offline wire continuation](docs/UNIFIED_WIRE_CODEC.md), and the
[command dispatcher integration](docs/UNIFIED_DISPATCH.md), and
[stock transport evidence](docs/UNIFIED_STOCK_TRANSPORT.md), and the
[memory-budget continuation](docs/UNIFIED_RESOURCE_BUDGET.md), and the
[completed ROM-code diagnostic](docs/UNIFIED_ROM_DIAGNOSTIC.md).
Health is the required unified boot/default; Gesture is temporary and opt-in.
The installed ring remains **V2 optical-off**, not the unified image; optical
health is globally disabled on that installed image. Historical claims below
that V2 has not been flashed are superseded.
The current guarded offline build passes **1276 tests, zero skips**, including
actual ARM and compiled Swift codec/decoder checks. The previous full iOS
simulator run passed **58 tests, zero skips**; no Swift changed or simulator was
rerun in the dispatcher/stock-transport/memory/ROM continuations. Output is
`firmware/unified/build-20260923-rom-internals-v1/`, NOT installable. Workflow 3 separately
passed 194 existing firmware/protocol/acceleration/cleanup regressions; those
were not rerun in the codec, dispatcher, stock-transport, memory or ROM continuations.
The earlier workflow3-final directory is a retained failed compiler-setup run,
not a passing build. All 132 source/artifact/report hashes in the new build
were rechecked; no unified OTA image or production capability was enabled.
The shared C/Swift codec is only an offline candidate for a distinct future GATT
service, never a legacy UART command. The offline dispatcher now joins commands
to the guarded adapter, waiting for committed transitions and owning both reply
fragments. Native/ARM cases and 20,000 sanitizer-stressed connections pass. No
UUID, service registration or live transport is attached; those components were
tested offline, separately from the bounded diagnostic sessions below.
The exact-stock transport shim passes callback structs by value and preserves
stack-result bytes, bypassing the unsafe UART queue. It is NOT attached to the
dispatcher or a service. Stock requests five service slots and registers five services;
additional capacity is unproved. Executed queue witnesses show wrap/data loss,
latched wake failure and no per-packet connection generation. Callback event
layout is compiler-sensitive; do not import default-size SDK enums blindly.
A newly coordinated idle session completed the fixed 80-byte bank0 descriptor
read twice after identity/config checks: 91 matching CD01 transactions, no
sensor start or flash, ring disconnected. Raw evidence is archived under
`firmware/research/2026-09-23/bank0-descriptor/`. Sampled code is not full
on-device image attestation. Further device work needs a new bounded plan.
A later freshly coordinated session repeated those prerequisites and read only
the fixed ROM identifier and 72 bytes of timer stop/delete wrappers, twice:
114 matching CD01 transactions, verified disconnect, no sensor command or flash.
Evidence: `firmware/research/2026-09-23/rom-timers/`. Both wrappers support an
optional hook and separate result byte. Later user-ready on-ring sessions
captured the literals/default code (142 matching transactions), then the fixed
eight-byte hook slots (144 matching transactions), each with repeated prior
evidence, configuration/idle postchecks and verified disconnect. Both hook
pointers were zero in both reads: defaults were selected in that idle snapshot.
Defaults call `xTimerGenericCommand`; delete clears the caller's handle on
nonzero return. The command implementation, external selector/state and actual
callback drain remain unproved. No sensor or flash command was sent.
New evidence: `firmware/research/2026-09-23/rom-timer-internals/` and
`firmware/research/2026-09-23/rom-timer-hooks/`. Replay and selected actual ARM
caller tests pass; unread boundaries remain explicit mocks.
The user was told clients could reopen; no continuing idle authorization exists.
APP and OTA staging each declare 144 KiB, agreeing with OEM upload bounds;
the stock-image margin is **9520 configured bytes, not approved expansion**.
Bank1 is absent; backup1's override is NOT an 8 MiB chip-capacity proof.
Geometry, ROM recovery, linked placement and RAM ownership remain unproved.
New exact-code witnesses expose ignored FIFO overflow/partial-read failures,
ignored OTA write failures, late optical restarts and unsafe STOP allocation.
An unattached heap-free STOP-write shim preserves bus/mutex failures; it does
not prove physical shutdown, callback fencing or current-settings resume.
Model axes/scale agree, but physical FIFO timing and new-source model accuracy
remain unqualified. Steps/sleep continuity is not established. No live FIFO
read or speculative instrumentation is authorized by this completed session.
New unified production transport remains unattached/locked.
The user has only the daily-use ring and permits considering a specifically
reviewed test if risk is reduced. A spare is preferred, not an absolute
requirement. Diagnostics first does NOT authorize a flash or waive technical gates.
The preceding memory change reduces `ws_observe`'s ARM
local stack frame from 344 to 184 bytes; its nested pair with `wa_observe` drops
600 to 440, excluding callers/other callees/interrupts. The dispatcher still
needs 1016 bytes versus only 1024 nominal aligned RAM bytes (not approved space).
Ten component `.text` sections now sum to 8252 bytes, not a linked-image fit.
All 132 new-build hashes match. The bounded sessions above were diagnostic only;
no phone access or firmware change occurred. The test ELF is unchanged from the
memory build; no C firmware component was changed by the ROM diagnostics.
The user subsequently requested a battery check and to run firmware if tests
passed. A separate battery-only connection reported 94%, not charging, then
verified disconnect (one checksum-valid 0x03 reply; no sensor/CD/flash command).
Offline tests passed, but flash-readiness gates have not: no stock-linked unified
image exists to transfer. Nothing was flashed under that conditional request.
Current health sync preserves clock/settings; older automatic-write claims below
are historical. Never use an unknown command as a harmless capability probe:
stock UART dispatch has side effects. Never use the image tail as spare space:
all final 200 bytes are a relocated boot overlay. Keep construction gates closed.

## Firmware handoff — 2026-09-22 (supersedes older LED conclusions below)

Read [docs/FIRMWARE_RESEARCH.md](docs/FIRMWARE_RESEARCH.md) before further ring
work; it contains the corrected address map, command semantics, exact firmware
hashes, patch history, hardware evidence, safety gates and open questions.
[docs/LED_FIX.md](docs/LED_FIX.md) retains the experiment chronology; original
reviews, tools and all six captures are saved under
[firmware/research/2026-09-22](firmware/research/2026-09-22/README.md).

- The ring still runs the original 25 Hz image. **No optical-off candidate has
  been flashed.** V2 is built/tested offline, not hardware-validated.
- Fresh 25 Hz motion with visibly dark LEDs passed two short host-workaround
  trials. Darkness alone and notification rate alone are not freshness checks.
- The permanent v2 candidate disables optical health and indicators globally.
  The user now wants to explore stock firmware for health and a separate image
  for gestures; no switching policy, automatic flash or candidate flash is
  approved by the request to save this handoff.
- Correct raw stop is `A1 05`, then `A1 02`. `69 01 04` starts HR, not stops
  it; the corrected HR disable is `69 06 04`. One logging setting is not a
  master switch for all background optical activity.
- V2 clears raw mode/timer on disconnect as well as releasing the STK idle
  hold; otherwise a retained raw mode can veto deep sleep. Battery benefit is
  **not measured**. The console's ordinary gesture target is still the old image.

## App integration and battery handoff — 2026-09-22

- Main now includes stock-health app PR #1 (`81b67d9`); local 11-class gesture
  edits were preserved. The merged app builds for the simulator under Xcode 27.0.
  No app was launched/deployed during that check. See `ios/IMPLEMENTATION.md`.
- Health sync can enable five-minute HR logging and first/full sync sends the
  history-clearing clock command. Keep the health app disconnected during gesture
  battery tests. A future mode switch must gate health jobs and preserve history;
  no automatic firmware switching is implemented or authorized by the merge.
- `docs/BATTERY_TESTS.md` distinguishes historical estimates, connected-idle
  captures, the requested ten-minute LED-off/fresh-motion test, and the still
  missing stock-health drain baseline. A prepared test is not a measured result.
- The ten-minute test was started in
  `data/batterycheck/battery_1790075215600058000.jsonl`: original25Hz identity
  matched all 22 code reads, 92% starting battery, first window 25.0 Hz and
  250/250 distinct XYZ. Read the log's final result/cleanup before calling it
  complete or estimating drain; visible darkness still needs user observation.
- That first run was user-interrupted after ~83 seconds to repeat while watching
  (the user had not seen a flash). Cleanup verified `000100` without errors.
  The separate ten-minute repeat is
  `data/batterycheck/battery_1790075332801725000.jsonl`; do not merge intervals.
- On the repeat, the user confirmed flashing then stopping. First post-STOP
  window again passed at 25.0 Hz with 250/250 distinct XYZ, starting battery 92%.
  The repeat subsequently completed 600.04 seconds: **92% to 90%, ~0.20 percentage
  points/minute**; all freshness gates passed and cleanup restored `000100`.
  Both logs are archived under `firmware/research/2026-09-22/captures/`.
  Historical flashing-LED drain was ~0.30 points/minute (~5.56 h extrapolated).
  This short, unmatched comparison does not establish runtime or LED savings.

Project goal: a smart ring emits a gesture when the model does something the
user dislikes; those gestures become preference data for a LoRA adapter. The
research question is whether preferences baked into weights hold up better than
preferences written into a context file as context fills.

---

## Status

| Milestone | State |
|---|---|
| M0 hardware gate | **PASSED** on `#4`: 25.00 Hz, 0.24% loss, 10 min worn |
| M1 gesture classifier | **COMPLETE (2026-09-21)**: 11 classes (flick x4, double_flick x4, snap, double_clap, wave), room-frame direction, held-out test 95/96 both seeds, 0 ambient events; live engine + web console; next: real-time use |
| M2 calibration corpus | **two layers.** Layer 1 (artifact style) finalized: 60 items, 5 per dimension. Layer 2 (agency / working style, `docs/AGENCY.md`): 11 axes, 28 items, situation-conditioned; `step_size` at a full 2x2, the rest paired exemplars. 88 items total, validated. Planner is layer-scoped |
| M3 labeling session | **tooling built, keypress-primary**: `python -m probe.label run / join / score / aggregate` (`whip/labeling.py`). Ring joined offline from `data/live/events_*.jsonl` as a secondary source. Blocked only on the rule-3 read-through of `corpus/gold/`, then four sessions on different days |
| M4 reward model | **built and tested** (`whip/reward.py`): factored reward, situation-aware direction, judge validation + trust gate. Blocked only on a judge backend |
| M5 LoRA adapter | **datasets built** (`reward.dpo_examples` / `kto_examples` / `split_by_item`); training blocked on a GPU and real labels |
| M6 three-arm eval | **harness built and tested** (`whip/arms.py`): mechanical context file, fill sweep, adherence with bootstrap CIs, per-dimension slopes. `python -m probe.pipeline dryrun` runs the whole chain on fixtures |

**M2–M6 need no ring.** They are the path to the research question. The ring only
ever replaces a keypress in the labeling UI. Do not let hardware work block them.

---

## The ring

| | |
|---|---|
| Model | Colmi R02, advertises as `R02_CC07` (was `COLMI R02_CC07` on stock) |
| MAC | `30:32:41:33:CC:07` |
| Hardware | `RT02CR_V3.1` |
| Firmware now | `RT02CR_3.12.07_260514`, immediate `#4` (`rt02cr-25hz.bin`) |
| Firmware was | `RT02CR_3.12.02_260824` (stock) |
| SoC | Realtek RTL8762E family (79/79 ROM-target matches; supersedes RF03 attribution) |
| Accelerometer | STK8321 |
| Battery | 17 mAh |

**Name matching:** it advertises `COLMI R02_...`, so `startswith("R02")` misses it.
Use `protocol.looks_like_ring()`, which matches anywhere in the string.

---

## Operational traps

These each cost significant time. Check them before debugging anything else.

**A stale BLE bond on the Mac blocks all connections.** Symptom: the ring
advertises reliably at strong signal, but every connect times out — in `bleak`
*and* in Chrome, with no error either side. Fix: System Settings → Bluetooth →
**forget the device**. Nothing else works. Not Bluetooth toggles, not
`sudo pkill bluetoothd`, not a full restart (the bond is on disk), not charger
taps, not unbinding from QRing.

**A ring can be visible and still "not found".** `BLEDevice.name` is often
`None` while the name lives in the advertisement's `local_name`. Matching on
`device.name` alone missed a ring sitting at -67 dBm, then "worked" on a retry
that happened to populate it -- which reads exactly like a flaky ring.
`find_ring` now matches on `adv.local_name or device.name`, and on the UART
service UUID as a fallback.

**The ring rotates its BLE address.** Chrome's picker showed it twice under one
name, at `30:32:41:33:CC:07` and `53:20:0D:60:4C:8F`, both marked Paired — one
live, one a stale bonded record. From Python this is invisible: CoreBluetooth
collapses both to one identifier and may pick the dead one.

**A healthy connect is slow.** The ring advertises infrequently and negotiates a
slow connection interval, so service discovery across four services takes tens of
seconds. Early 10–30 s timeouts could not distinguish slow from broken.
`CONNECT_TIMEOUT_S` is now 90 s.

**Binding the ring in QRing causes trouble.** Avoid it. If you must, unbind
afterwards *and* forget the device on the Mac.

**LED-off streaming is possible, but sample freshness must be checked.**
An explicit STK wake/hold plus optical-only STOP passed two short trials on the
unchanged firmware; optical STOP alone allowed cached acceleration. A charger
tap still clears stuck states, but is not the only optical shutdown mechanism.
See the firmware handoff above; the LED section below is historical.

---

## Protocol

All commands over the nRF UART service. 16-byte packets: command byte, up to 14
sub-data bytes, checksum = sum of the preceding bytes mod 256.

| Purpose | UUID |
|---|---|
| UART service | `6e40fff0-b5a3-f393-e0a9-e50e24dcca9e` |
| Write | `6e400002-...` |
| Notify | `6e400003-...` |
| DFU service | `de5bf728-d711-4e47-af26-65e3012a5dc7` |
| DFU notify / write | `de5bf729-...` / `de5bf72a-...` |

**Raw sensor:** `A1 04` starts; stop with `A1 05` then `A1 02` (the latter alone
leaves raw optical bit `0x800` set). Notifications are tagged `A1` with
a subtype in byte 1: `0x01` SpO2, `0x02` PPG, `0x03` accelerometer, `0x05`
undocumented and near-static.

**On this firmware `0x04` is the only usable parameter.** Swept `0x01`–`0x0F`;
nothing else streams motion. There is no accel-only mode.

**Accelerometer decode — settled empirically:**

```python
x = int.from_bytes(payload[6:8], "big", signed=True)   # note the axis order
y = int.from_bytes(payload[2:4], "big", signed=True)
z = int.from_bytes(payload[4:6], "big", signed=True)
```

`signed16_be`, **8005 counts per g** (≈ ±4 g full scale). Axis order is Y, Z, X.
One sample per packet; bytes 8–14 are always zero.

The public Edge Impulse implementation decodes this as 12-bit with an incoherent
sign check. It is wrong. Three independent lines of evidence are in
`docs/HARDWARE.md`.

---

## Firmware

### Container (RT02CR, magic `e5c3bd81`)

| Offset | Field |
|---|---|
| `0x000c` | u32 LE sum of every byte from `0x50` to EOF |
| `0x0010` | firmware version string |
| `0x0030` | hardware version string |
| `0x0050` | nested Realtek header |
| `0x0052` | u16 LE control flags; **bit 7 is `not_ready`** |
| `0x0058` | u32 payload length (filesize − `0x450`) |
| `0x01c4` | 32-byte SHA-256 of the payload at `0x450`→EOF |
| `0x0450` | Realtek application payload |

**It is not encrypted.** An earlier conclusion in this repo said it was, inferred
from entropy and a CRC32 that would not verify. Both were wrong — the payload
disassembles as plain ARM Thumb from `0x450`. Never conclude a binary is opaque
without disassembling it.

To build a bootable custom image: patch the payload, refresh the SHA-256, clear
`not_ready`, recompute the body sum **last** (it covers the other two fields),
and transfer with init type `0x04`. `whip/fwbuild.py` does all of this, validated
by reproducing the published low-latency image byte-for-byte.

### The raw motion rate is one byte

`movs rN, #imm` feeding `lsls rN, rN, #3`, at file offset `0x2248`.

**The instruction computes `imm * 8` ms, but the delivered period is
`imm * 10` ms.** Measured at three points, so predict from the measurement, not
the arithmetic -- the instruction is 25% optimistic. Where the extra 25% comes
from is not established: a slower timer tick, or scheduling overhead between the
timer firing and the notification going out.

| Immediate | Measured rate | Loss | |
|---|---|---|---|
| `#125` | 1.00 Hz | 0.00% | stock, with a 1114 ms hole |
| `#2` | 50.00 Hz | 25.94% | published low-latency; bimodal arrivals |
| `#3` | 33.33 Hz | 2.99% | more headroom, fails the loss bar |
| `#4` | **25.00 Hz** | **0.24%** | **currently flashed, passes M0** |

`#3` is the operating point. `#2` produces faster than BLE delivers -- 61% of
intervals at one period and 33% at double it, the signature of dropped samples.
`#3` and `#4` are unimodal with jitter only. `probe/build.py` locates the timer
site by period rather than a hard-coded address.

**`#4` is the operating point.** Over 10 minutes worn: exactly 25.00 Hz
(15000 packets in 600 s) and 0.24% loss. An earlier 60 s capture read 24.98,
which was a window-boundary artifact -- the period is a firmware constant, so
the rate does not drift.

Loss does not scale with rate the way you would expect. `#3` at 33 Hz loses
2.99% worn; `#4` at 25 Hz loses 0.24%, ten times better for a 25% rate cut.
Producing under what the link comfortably carries stops the notify queue
thrashing rather than merely reducing it.

Loss also tracks **motion**, not the link: still chunks read 0.1-0.2%, moving
chunks up to 6%. A loss figure is partly a statement about how much the wearer
moved.

### The accelerometer range is one byte too

`write_register(0x0F, 0x05)` at **file offset `0x00bf0a`** -- `RANGESEL` set to
±4 g, which is why counts-per-g measures 8005.

Found by `probe/accelrange.py`, structurally rather than by hunting immediates:
counting occurrences of `0x0F` gives 141 sites and settles nothing, and many are
`movs r1,#0x0f; mov r0,sp; bl`, a 15-byte buffer length. What works is finding a
*run* of `movs rA,#x; movs rB,#y; bl helper` triples sharing one call target --
a peripheral init -- which needs no load base. The decisive anchor is
`write(0x14, 0xB6)`, the documented STK832x soft reset. The same helper writes
`POWMODE2`, `BWSEL`, `FIFO_CONFIG`, `SWRST`, then the range.

`0x08` would give ±8 g and recover the top fifth of the amplitude information
now lost to clipping (gesture peaks reach 6-7 g against a ±4.09 g rail).

**The cost is not the flash.** Changing the range changes counts-per-g, so
`accel.COUNTS_PER_G`, every amplitude threshold derived from it, and the
comparability of the entire recorded corpus all go with it. That is a decision
about re-recording. Not patched, not flashed.

Two disassembly traps, both of which produced "nothing found": linear
disassembly from byte zero yields nothing because the container header is not
instructions and capstone stops at the first thing it cannot decode -- start at
`0x450` and resync past data islands. And in a test fixture, a BL with a constant
delta sends every call to a *different* absolute target, so the grouping never
fires.

**Never patch `0x007ed4`.** It carries the identical timer idiom but belongs to
DFU frame reassembly; lowering it can break OTA recovery. It is excluded via
`fwimage.DO_NOT_PATCH`.

### DFU

Frame: `BC | cmd | len_lo | len_hi | crc16_lo | crc16_hi | payload`. CRC-16/Modbus
over the payload. Commands: START `0x01`, INIT `0x02`, DATA `0x03`, CHECK `0x04`,
END `0x05`. 1024-byte chunks, 240-byte BLE segments, init type `0x04`.

**The ring never acknowledges END** — it reboots to apply the image. CHECK is the
frame that confirms receipt. Treating END's silence as failure reported a
successful flash as ABORTED.

---

## Measurements

**M0 gate:**

| | Stock `#125` | Low-latency `#2` | **Custom `#3`** |
|---|---|---|---|
| Rate | 1.00 Hz | 50.00 Hz | **33.33 Hz** |
| Interval median | 1023 ms | 16.99 ms | 30.00 ms |
| Interval mean | — | 20.00 ms | 29.99 ms |
| Jitter | 77 ms | 6.99 ms | **4.51 ms** |
| Gap max | 1114 ms | 74 ms | 60 ms |
| Windows with a stall | — | 0 of 400 | 0 of 40 |
| Implied loss | 0.00% | 25.94% | **1.96%** |
| Gate | FAIL | rate only | **PASS** |

**The 25.94% at `#2` was real dropping, not a metric artifact.** The interval
histogram is bimodal — 61% at one period, 33% at exactly double — which is what
missed samples look like. At `#3` the distribution is unimodal and median equals
mean, and the loss falls to 1.96%.

Worth keeping in mind: stock scored **0.00% loss while containing a 1114 ms
hole**. A perfect score on a useless stream. Rate and loss together, plus the
gap distribution, are what actually characterise a capture.

**Battery, measured on three images:**

| Image | Rate | Drain | Projected runtime |
|---|---|---|---|
| `#2` | 50 Hz | 1.0 %/min | ~1.7 h |
| `#3` | 33 Hz | 0.27 %/min | ~6.3 h |
| `#4` | 25 Hz | 0.30 %/min | ~5.5 h |

**Drain is not dominated by the packet rate.** Going 50 → 33 Hz gave a 3.7x
improvement, far more than the rate ratio, because it stopped the retransmission
churn. Going 33 → 25 Hz changed nothing measurable. So the remaining cost is the
LEDs and holding the BLE link, and **no rate choice unlocks Phase B** -- ~6 h is
the ceiling until the emitters can be turned off. Phase A (1 h session) has
ample margin.

---

## LED

**Historical investigation, superseded on 2026-09-22:** the failures below are
retained as history, but their conclusions about inseparable sensors, an unknown
load base and no working optical stop are no longer current. Use
[docs/FIRMWARE_RESEARCH.md](docs/FIRMWARE_RESEARCH.md) for the corrected account.

Green and red are the PPG and SpO2 emitters. They light whenever `A1 04` runs
and cannot be turned off:

- the realtime stop commands (`69 01 04`, `6a 01 00 00`, `6a 03 00 00`) do
  nothing, sent during streaming or after it
- **no command lights them either** — `69 01 01` (start HR) produced no LED at
  all, so they are not driven by the health-command path
- no `A1` parameter streams motion without them

### Everything ruled out, with evidence

**Protocol: exhausted.**

- Periodic HR logging (`16 02 02 3c`) was **already disabled** before we sent
  anything -- confirmed by read-back (`16 01`) -- and the LEDs flicker anyway.
- SpO2 (`0x2c`), stress (`0x36`), `0x38` all read zero; `0x37`/`0x39` unsupported.
- Realtime stop commands (`69`/`6a`) do nothing, sent before, during or after.
- All 15 `A1` parameters light them; none streams motion alone.
- Sending the logging disable *before* `A1 04` darkens the ring but the
  accelerometer never starts -- one packet in three minutes. The only dark state
  is the one with no data.

**Not a regression from the mod.** Stock `RT02CR_3.12.02` was flashed back and
streamed for three minutes: **it flickers too**, while emitting spo2, ppg, accel
and `0x05` at 1 Hz each. The optical sensor was always sampling; the low-latency
build only suppresses the *reports*. All three of upstream's NOPs remove calls to
one function, `bl #0x7e30`, the notification send -- no power-down instruction
was dropped.

So `A1 04` means "power the whole sensor front end" on every firmware, and the
emitters are inseparable from the accelerometer at the protocol level.

**Firmware: attempted and not cracked.** The call graph reachable from the A1
handler is ~5100 call sites, far past blind bisection. Following the raw-sampling
timer callback needs the image's load base, and solving for it failed -- the best
candidate put only 49 of 206 function pointers on a prologue, with the top six
scoring within noise across a 100 KB spread. Position-dependent code, no symbols,
no memory map, and validation only by flashing and looking at the ring.

**If revisiting:** ask the upstream author. Nosh118 found the timer immediate,
the three send sites, the connection-parameter call and the Realtek activation
sequence in this exact image. One question could replace days of work.

---

## The gesture platform

The CNN is a **general gesture classifier**; the Whip app consumes only the
gestures it maps to actions. One vocabulary, declared in `whip/registry.py`:
flick, double_flick, snap, double_snap, double_clap (impulsive), wave, clap
(sustained).
Classes materialise from data -- the exporter emits only classes with windows
and prints the declared-but-absent ones. Legacy names on disk (`flag`,
`approve`, `waving`, `snapping`, `clapping`) map in via aliases.

**Two labelling modes, decided by the mark's shape.** Point marks (prompted
gestures) keep the coverage rule. Span marks (20 s "keep waving" blocks) label
windows fully inside the span, with a 0.5 g hygiene floor so pauses inside a
span stay `none` -- the label source is the human cue; amplitude only gates
whether the cued motion was happening at that moment. Unrecognised motions
('dismissive flick', 'so-so wobble') stay attribution-only **negatives**:
promoting every cued motion to a class would silently convert hard negatives
into positives. `snapping` IS promoted, deliberately -- the model learns the
snap/flick boundary explicitly.

**Event policies are per gesture.** Impulsive keeps the 3-14 run band.
Sustained fires once at min_run with **no upper bound** -- `max_run` exists to
reject sustained motion, so a bounded wave is unfirable by construction -- plus
a refractory measured from run end, so a mid-wave dip cannot split one wave
into two. Judgement happens exactly once per run. Batch `events.detect` is a
loop over the incremental `RunTracker`; the realtime engine feeds the same
tracker, so live and offline are one implementation.

**The console's calibration is a gate with a reason, and it can be re-run**
(2026-09-21 late). `realtime.PoseCalibrator` judges the fingers-down pose on
a rolling 2 s buffer and only accrues the 3 s while the pose is accepted;
when it is not, it says which of the two checks fails -- `moving` (peak g)
or `not_down` (degrees off vertical) -- because the one-line countdown had
been saying "hold still" to a wearer whose fingers were 40 degrees off. The
result (frame, wearing, angle, motion) rides in `/api/status` so a page
opened mid-session shows it, and `POST /api/calibrate` holds events until a
fresh pose: a ring handed to a second wearer ran that wearer's whole
segment under the first wearer's frame because tracking calibrated once.
The Live tab shows the three checks, a progress bar, the result, and a
Recalibrate button.

**One event per movement: the decoder is burst-anchored (2026-09-22).**
Decoding gestures as runs of same-label windows failed live in three ways
(traces 22:38, 22:53, 22:56 on 2026-09-21): two same-class gestures in
succession made ONE run (one event, none past 14 windows); a different
gesture whose windows abutted a fired run started inside its 0.5 s dead
time and was dropped; and continuous motion -- a 9 s shake, a wave from
a hanging hand -- was chopped into four double flicks. `events.BurstTracker`
segments the stream itself: impulsive magnitude |a - gravity| (gravity =
causal 1 s mean) opens a burst at 1 g and closes it after 0.6 s below (a
double's stroke gap is at most 0.5 s, so a double is one burst); a lone
sample under 1.5 g is a blip, not a burst. Each burst is judged ONCE from
the windows that contain its core (first 1.3 s) and no other movement --
start after the previous burst ended, end before the next begins; if
gestures come too fast for two such windows, windows may run into the
next movement's start but never back into the previous one's tail. Most
voted impulsive label wins with at least 2 votes; a burst over 2.0 s gets
no impulsive event (sustained classes keep the run policy). The decision
is made early once the remaining vote windows cannot overturn it: a flick
or snap is decided ~1.0-1.5 s after onset, a double ~2 s; the event time
IS the onset and `latency_s` is measured, not designed. `detect_bursts`
is the batch loop over the same tracker; `probe.split score --decoder
runs` keeps the retired decoder for comparison. Same checkpoint, thr 0.5:
runs val 77/77 test 98/102; bursts val 77/77 test 97/102 (the one
difference started 1.7 s before its cue), ambient 0 in both. Live
replays: 20/20, 20/20, 3/3, 0 spurious; the 9 s shake is now one wave
and the two hanging-hand waves are "too long", not double flicks. Scorers
match on the onset with the split's 1.4 s early bound (`gesture_hits
early_s`, `livetest.EARLY_S`): a fifth of cued gestures start before the
cue, and centre-of-run timing had hidden that. Consoles show every judged
movement, event or not, with why.

Measured on the 4.2 min session of 2026-09-22 01:20 (87 movements): the
engine costs 0.25 ms per packet against a 40 ms budget and does not grow
with the number of gestures; BLE delivery is 25.0 Hz with a 60 ms p99 gap
whether the hand is moving or not. So "lag" is the decision itself
(median 1.4 s, p90 2.0 s after onset: the last vote window must contain
the whole core of the movement and completes 2 s after onset; a closed
burst with three unanimous votes is decided at once). The misses there
were: five pairs of consecutive gestures 0.40-0.56 s apart merged into
one "too long" burst -- now split at the longest internal lull
(`SPLIT_QUIET_S` 0.35, only for bursts over `MAX_IMPULSIVE_S`; a double
clap's internal lull reaches 0.5 s but its burst never exceeds 1.3 s, so
13 of 66 would have split under a shorter merge gap and none do under
this rule), 57 -> 64 events; and nineteen shock-shaped movements
(0.2-0.8 s, 4-8 g, mostly right after a flick sequence) on which the
model itself said `none` on every containing window at threshold 0.3,
0.4 and 0.5 -- the model, not the decoder, and not posture (gravity
along the finger ranged -0.9 to +0.9 in both hits and misses): snaps and
claps done in the flow of other gestures, with a follow-through the
corpus's isolated, from-rest recordings do not have. The data ask is a
session of snaps/claps interleaved with flicks. Same checkpoint after
the split: val 77/77, test 98/102 (= the run decoder), ambient 0, live
replays 20/20, 20/20, 3/3, 0 spurious.

**Direction is room-frame, so posture changes what a "flick down" is.**
Console session 2026-09-21 22:38 (`data/live/console_20260921_223802.jsonl`,
frame identity, verified: gesture TYPE was right on every burst -- snaps,
singles, doubles -- and wrong under the other frame): the wearer's flick
downs came back as `double_flick left` eleven times running. Not the frame,
and not a training-data orientation error. The gestures were done with the
hand hanging (gravity 0.75-0.93 along the finger, i.e. fingers 50-70 degrees
below level); every training and live-test flick down was done with the
forearm level (median 0.1-0.2 along the finger, p90 0.5), and in the corpus
the hanging posture only ever carries UP flicks. From a hanging hand a wrist
flick moves the ring forward/sideways in the room, not down -- the first
stroke's vertical sign was opposite to 98% of training downs -- so the room
frame reports exactly what happened. Fix is one of: gesture with the forearm
level (the 20/20 live test did), or record downs/lefts/rights from the
hanging posture, which the corpus has none of. Also seen there: a snap whose
stroke had a large sideways component read as `flick right`; a 1.1 g snap was
below the 1 g stroke floor of anything the model has seen (training snaps
median 5.6 g).

**Direction: what it physically is, measured** (`probe/directions.py`). In the
ring's frame ALL FOUR directions rotate about one shared axis (unsigned axis
angles 4-17 degrees in every session). An earlier sentence here said `up` was
"the opposite sense, 119-153 degrees away" from the other three; that came
from the gravity-track sense estimator, which re-measured is a coin flip for
every direction but `down` (same-sense agreement 31-69%), so it cannot assign
sense at all and that claim is withdrawn. Sense measured on the full-band
shape channels instead (signed area swept in the plane perpendicular to the
finger) IS consistent: `down` and `right` share one sign (90-100%), `left`
the other (87-98%), and `up` shares `left`'s sign but weakly (66-80% in the
training sessions, 47% -- a coin flip -- in the reference session). So the
same-sense pairs are up/left and down/right, exactly the pairs the models
confuse. What separates the palm-down pair from the hand-vertical pair is
POSTURE: the gravity vector during the gesture differs by 47-58 degrees
between the pairs and 3-15 within them. Between days each posture cluster
moves 23-55 degrees, the same order as the pair separation, yet the pair
assignment survives -- nearest s1+s2 centroid put 100% of the reference
session's up/down windows in the palm-down pair and 91%/79% of left/right in
the hand-vertical pair. Every direction is a repeatable motion -- unsigned
axis consistency 0.88-1.00 in all three prompted sessions -- and `up` is the
least stereotyped: soft, broader, and its waveform changes most between days.

Two earlier claims in this file were wrong and are withdrawn: the ring did not
sit "60 degrees rotated" between sessions (rest gravity in the finger-
perpendicular plane differs by ~15 degrees; hand PITCH differs by ~50 -- the
60 came from averaging rotation axes across directions that rotate about
different axes); and `up` was never "random" (signed consistency 0.06 was the
rotation-SENSE estimator flipping sign; unsigned it is 0.97).

**Why the first direction models permuted** (down->right, up->left): trained on
ONE session, they could only see the sense of the flexion, because posture --
the per-window gravity vector -- was subtracted before the model saw anything.
Same-sense/different-posture pairs were indistinguishable by construction.

**Fixed by data first, posture second.** Trained on two sessions and tested on
a fresh 32-gesture session: direction 93% with the plain channels, 96% with the
`posture` channel group (the window's unit gravity vector, export v5 keeps it),
recall 88-91% on both seeds. Direction-split classes (`split_by_direction`)
and the direction head both exist; the head's loss is still off (it cost ~10
recall points when trained on 264 gestures). `invariant` channels (|a|,
along-finger, perpendicular magnitude) are exactly spin-invariant and exist for
gesture TYPE; with posture they scored worse for direction (81%), as expected.

**The physically right direction feature is gravity-referenced, not the
ring frame** (`gref` channel group, 2026-09-15). Up/left and down/right are
the same wrist motion at a different forearm roll, so in the ring frame the
waveforms are identical and only gravity's position differs. Resolving the
impulsive acceleration ALONG gravity and PERPENDICULAR to it turns that into
a relation between a and g measured in one frame -- invariant to how the
ring sits and to which way its axes point (test: rotating window and gravity
together leaves it unchanged). Hand-computed, no training: the fraction of
impulsive energy along g is 0.49-0.69 for up/down and 0.10-0.16 for
left/right in all three sessions, and ONE fixed cut separates the pairs for
95% of 296 gestures across three days. Within a pair, left/right is the
rotation sense (swept area sign, 88-100% consistent); up/down sense is the
weak link (down 94-100%, up 66-80%, and 47% in the reference session).
Trained (`shape,scale,saturation,gref`, sessions 1+2, reference held out,
2 seeds): every up gesture right (8/8 both seeds, vs 5-6/8 without), recall
93.8% both seeds (CI 84-100), and ambient false positives LOWER than the
plain channels at every threshold (0.03-0.13/min at thr 0.4 vs 0.27-0.30;
0.00-0.03 at 0.9 vs 0.07) -- the opposite of `posture`, which raised them.
The remaining misses are the same two uneven doubles read as singles and
one or two soft (1.8-1.9 g) double_flick_right read as left. ONE reference
session and 30 ambient minutes: not yet the default, re-measure on the next
session before promoting it.

**Every cued gesture is audited from its own stream and gets a verdict**
(`python -m probe.audit <session> --write`; `notebooks/data_quality.ipynb`
has the full analysis, 2026-09-15). valid / suspect (kept, listed) /
invalid (dropped: `dataset` treats every window touching it as ambiguous,
`probe.rollout` does not score it). **The double flick is DEFINED as a
range**: two strokes 0.20-0.50 s apart, second peak 0.5-2.0x the first
(corpus p5-p95 0.22-0.46 s and 0.70-1.66, with margin). A "double" with a
pause is a different gesture, not a tempo. The two doubles every held-out
model missed are exactly that (spacing 0.51 and 0.68 s), and the audit finds
them from the stream alone, before any model. Direction is checked against
gravity: one fixed cut on the impulsive-energy-along-g fraction puts 96.3%
of 296 gestures in the cued vertical/horizontal pair, no training.

The corpus, audited: 296 gestures -- 255 valid, 29 suspect, 12 invalid
(86.1% clean). Invalid: 5 doubles with a pause, 3 with a stroke ratio
outside range, 3 doubles with one stroke, 1 with no motion (session 1 #190,
0.7 g). Suspect is uncertain rather than wrong (a single whose recoil is 70%
of its stroke, a soft cue done hard, motion just across the pair cut).
**Only valid trains and scores** (`audit.EXCLUDED_VERDICTS`, decided
2026-09-15): uncertain data is dropped and made up next session, not trained
on -- including a correct gesture whose prompt word was not followed. A
shape review of all 29 suspect gestures added two hard rules: peak under
1.5 g is `WEAK` and onset after 0.6 s is `LATE_ONSET` (both invalid; every
gesture they catch was a smear or a non-response). The make-up list is 44
gestures (`probe.audit` prints it per session as "to re-record";
`scripts/rerun.sh` runs audit -> export -> train -> rollout, and with
`--notebook` the experiments and `notebooks/data_quality.ipynb` too). Stroke COUNT is never a hard check: at 25 Hz a recoil and a
weak second tap are the same size, and 27 of 100 singles would otherwise be
flagged. Synthesising slow/unequal doubles from pairs of singles was tried
and is net zero: it recovers the two misses and loses the same number of
recoil-heavy singles, with more ambient false positives.

Protocol facts from the audit: the amplitude prompt is followed (soft
2.3-3.8 g vs hard 4.7-5.7 g medians); the "brisk/deliberate" tempo prompt
changed NOTHING in any session (stroke spacing medians 0.29-0.39 s for every
word) and should be dropped; a fifth of gestures start before the cue
(predictable schedule); nothing starts after 1.0 s.

What the exclusion costs, measured (`shape,scale,saturation,gref`, sessions
1+2, reference held out, 2 seeds, scored on the 21 valid reference
gestures): trained on valid only, 19-20/21 exact class and 21/21 type at
thr 0.4-0.6, ambient false positives 0.20-0.27/min at 0.4 and 0.00-0.03 at
0.9. Trained on everything: the same 19-20/21 and 21/21, ambient 0.07/min
at 0.4. Recall is a tie; the suspect boundary cases were buying
low-threshold false-positive margin, which the next session's clean
examples have to replace. Both remaining misses are one soft (1.9 g)
double_flick_right read as double_flick_left: right type, wrong sense.
Learning curve over 57-231 valid training gestures: gesture TYPE is 20-21/21
from 115 on; exact class is 19-20/21 at every size, so more of the SAME two
days is not the lever -- new days are. Days matter more than
gestures (posture and the up waveform moved more between days than within
one), so the ask is sessions: 4-5 training days of 64 audited gestures, a
never-trained demonstration set of >= 100 gestures on >= 2 further days
(observed 97% on 100 bounds recall above 91%; on 28 it bounds nothing above
84%), 3 days x 3 spans per sustained class plus snap/double_snap sets, and
180+ ambient minutes across >= 2 days.

**The ring can go on either way round, and the model must not care**
(2026-09-15 evening). The fill session and the second ambient hour were
recorded with the ring turned around: the along-finger gravity component
was positive in 93-97% of 2 s chunks, negative in 0-47% of every earlier
session. The deployed model scored 0/44 exact on that session; rotating
the recorded frame a half-turn about the ring's perpendicular axis gave
37/44. The audit cannot see this (its measures are frame-invariant) --
`probe.checkup`/the collector should report the along-finger gravity sign
so a flipped ring is noticed at recording time. Fix in the model, not the
protocol: `probe.train --frame-aug flips` (default) rotates each training
batch by a random proper half-turn of the frame, window and gravity
together, so every channel group sees one consistent frame and rotation
sense survives. Held out, as recorded, 2 seeds: 37-38/44 exact (21/22 of
the valid ones, every hit with the right direction), ambient 0.00-0.03/min
at thr 0.4; without flips 0-3/44. The same session also shows the posture
protocol drifting: down, left and right were done in ONE hand posture
(rest gravity 2 degrees apart) and only up differed, so 18 of 44 gestures
fail the vertical/horizontal pair check -- that is the wearer, not the
ring, and it is why the pair check stays a flag rather than a hard rule.

**"Left" and "right" are wrist motions, not room directions** (posture x
direction matrix, `probe.collect --matrix`, 2026-09-16: 12 hard single
flicks, every hand orientation but palm-down, all audit-valid). The
vertical/horizontal pair from gravity held in EVERY posture (up/down 0.45-
0.74 along g, left/right 0.02-0.21) and the model called up and down right
in all three postures. Left/right were right with the palm facing right
(the posture every training session used for them), one of two right with
the palm facing left, and BOTH SWAPPED with the palm up. That is what the
training data taught: "left" is the wrist motion that moves a
palm-right hand left. Room-left needs the palm's facing, and the frame
flips that make the model orientation-proof deliberately erase which way
the ring is on -- so room-left versus room-right is not recoverable from
the ring alone once the palm may face up or down. The decision is a
definition: either the horizontal gestures are wrist-relative (toward the
thumb / toward the little finger; the ring senses that unambiguously in any
posture) or they require the hand-vertical posture. **Decided the same day: room frame.** Every direction is the
direction the hand moved in the room, in any posture. That needs the one
bit the flips erased -- which way the finger axis points -- so: the `room`
channel group (along gravity, lateral = gravity x finger, forward; signed),
`--frame-aug spin` (full spin about the finger, no front-to-back flip), and
a **wear rule: the ring goes on the same way round every time.** A session
worn back to front is not thrown away: `<session>.frame.json`
(`audit.set_frame`) names the half-turn and the exporter rotates the stream
into the canonical frame. Which way a session was worn is measured, not
eyeballed -- the static along-finger gravity sign is posture-confounded
(the 22-gesture fill read 65% positive and was the right way round) -- by
scoring it under the four rotations with a room model trained on
known-canonical sessions: last night's 44-gesture session 19/22 flipped vs
12/22 as recorded, so it and the ambient hour from the same wearing are
corrected; every session since is canonical. Matrix session held out, room
model: 8/12, and the palm-up left/right that the wrist-frame model swapped
are both right. The corpus has no horizontal flicks outside the
hand-vertical posture; `probe.collect --matrix --reps 3` (and with
`--gestures flick,double_flick`) is the recording that fills that.

**The finger is ring axis 1, not axis 0 -- measured, and it mattered.**
The flick's ROTATION axis is axis 0, which was read as "axis 0 runs along
the finger". A wrist flick rotates about the palm normal, not about the
finger. Resting gravity in three known palm orientations (`--matrix`)
settles it: palm up puts gravity on axis 0 (palm normal), palm left/right
on -/+ axis 2 (thumb-pinky line), so the finger is axis 1
(`model.FINGER_AXIS`). With the wrong axis, gravity x finger was
near-degenerate in every palm-down window and the room channel carried
nothing. With the right one the hand-computed rule -- sign of the first
stroke along gravity (up/down) or along gravity x finger (left/right) --
gives the cued direction in all 12 matrix cells and 25-39 vs 1-8 per
training session, no model. The same rule reads which way round the ring
was worn (`audit.hand_rule`, canonical = sensor-below: left negative);
every session's frame file comes from it, `probe.audit --auto-frame`
writes it for new sessions. Room model, matrix held out: **11/12** (palm
right 4/4, palm left 4/4, palm up 3/4 with one no-fire) from a model that
never saw a horizontal flick outside the hand-vertical posture.

**Full matrix, 48 flicks in four palm orientations, held out** (2026-09-16,
`prompted_20260916_040358`, 41 valid; one skipped cue, six up/down done
sideways enough to fail the pair check): room models trained on nothing
from that posture set, thr 0.4, seed 0 39/41 and seed 1 34/41; at thr 0.9
34 and 29. Every miss but one is a NO-FIRE, not a wrong direction --
direction was right in 79 of the 80 calls that fired, in all four
orientations. The no-fires cluster in palm-up, which no training data
covered. The room frame delivers direction as derived; firing confidence
in an unseen posture is the data-limited part, and that session now trains.

**A snap is a glitch-shaped event, and the despiker was eating it**
(2026-09-16, `prompted_20260916_044426`: 37 each of snap, double_snap,
clap, double_clap in blocks, then one 60 s wave). At the ring a finger snap
is a 1-2 sample shock at 5-7 g -- the width of the BLE glitches the Hampel
filter exists to remove -- and it removed them: median snap peak 5.8 g raw,
1.1 g filtered, 24 of 37 audited as no motion. Both filters now replace
only an ISOLATED outlier (both neighbours within the centre's threshold).
Kept: snap 73% above 1.5 g, double_snap 86%, claps all. Cost: ambient
windows above 3 g rise ~40% (68 -> 94/hour, 225 -> 359/hour); they are real
desk shocks and are the natural hard negatives for a snap class. A clap is
wider (3-4 samples, with recoil) and never had the problem. After the
change the session audits 95 valid: snap 28, double_snap 13, clap 34,
double_clap 20 (doubles lose to the ratio/one-stroke rules when the
despiker still takes a one-sample second spike), plus 242 wave windows.
Single snap remains the marginal class: 1-2 samples at 25 Hz is the same
signature as a desk tap, and ambient wear has ~100 of those an hour.

**One fixed split BY GESTURE, decided 2026-09-16; leave-one-out and the
by-session split are both retired.** Sessions are lopsided in size, one
session holds whole classes, and the deployed model trains on every day
anyway -- so every valid cued gesture is dealt to train / val / test at
random, stratified by class, seed fixed in `data/split.json` (65/15/20;
`probe.split make` writes `data/split/{train,val,test,trainval}.npz`). A
gesture's windows go with it; consecutive gestures' intervals meet midway
between cues and any window straddling a boundary is dropped (the 88%
overlap leak, closed by construction; ~16% of windows). The non-gesture
timeline of every recording, ambient hours included, is dealt in 20 s
chunks the same way, so the false-positive rate is measured on pieces of
every negative recording. Val chooses threshold and seed; test is scored
once per model and never tuned on; the deployed checkpoint trains on
train + val. Earlier by-session numbers (77/97 on a 3-session hold-out;
adding the snap/clap session cost the posture fold 40 -> 24 of 41) are
superseded and kept only as the record of why.

**First scores under the gesture split** (train-only models, 2 seeds; val
69 gestures, test 90; ambient = the val/test chunks of every negative
recording, ~19 and ~26 min):

| thr | val exact | val ambient /h | test exact | test type | test ambient /h |
|---|---|---|---|---|---|
| 0.4 | 63, 62 / 69 | 6.3, 15.9 | 85, 84 / 90 | 86, 84 | 7.0, 4.6 |
| 0.7 | 62, 61 / 69 | 0.0, 3.2 | 81, 83 / 90 | 82, 83 | 4.7, 0.0 |
| 0.9 | 62, 60 / 69 | 3.3, 6.4 | 78, 78 / 90 | 79, 78 | 2.3, 2.3 |

Threshold 0.7 is the operating point chosen on val. On test at 0.4, seed
0: every single flick 40/40, doubles 28/30, snap 5/6, clap 7/7,
double_clap 4/4, double_snap 1/3; every miss but one is a no-fire, the
one direction error is double_flick_right -> left. The gesture interval
must hold every window that carries the label (cue-1.4 .. cue+2.85); the
first bounds kept 3 of 10 and scored 4/69.

**Left/right is a ~95% physical rule, not a proof, and the model beats it**
(2026-09-16). Every hand-computable estimator of a horizontal flick's
lateral sign was scored on all 186 valid left/right flicks and doubles in
the room frame: velocity extremum over the first 0.6 s 94.6%, first five
samples 89.2%, first-lobe integral 52.7%, sign at peak 55.4%, largest lobe
66.7%. So the first-stroke sign that the derivation rests on is right for
about 19 in 20 gestures; the rest begin with a windup or a recoil-first
pattern and the sign of the initial lateral acceleration is the wrong way
round. The CNN, which sees the whole window, confused left and right 3
times in 236 held-out scores (98.7%). The frame makes the pair (vertical
vs horizontal) exact and makes the sign LEARNABLE in any posture; it does
not make it foolproof, and nothing about a 25 Hz accelerometer on one
finger can. What would close the last percent is not a rule but more
horizontal flicks recorded across postures (the matrix sessions).

**Scores on the raw stream, gesture split, thr 0.7 chosen on val** (train-
only models, 2 seeds; val 78 gestures, test 103; ambient = val/test chunks
of every negative recording, ~19 and ~25 min): val exact 69 and 72 of 78,
test exact 94 and 92 of 103 (91%, 89%), type 97 and 94; **ambient 0 events
in every part for both seeds at thr 0.4-0.9**. Test misses: 5-6 no-fires
(double_flick_down 2, flick_right 1-2, clap 1-2), and the shock classes
mixing among themselves (double_snap <-> double_clap, clap -> snap); zero
left/right confusions on test, one flick_up -> left on val. Against the
filtered stream the same split gave 81-83/103 and 0-5 ambient events/h.
Corpus after the raw re-audit: snap 43, double_snap 40, clap 37,
double_clap 29, flicks 37-57 per class; 17 short of level.

**Ablations on the gesture split, 2026-09-20** (`notebooks/experiments/
ablate.py`, test exact of 103, threshold 0.7 chosen on val, ambient 0
events in every run): baseline 94, 92, 93 (3 seeds). Shock-class data
curve: a third of the snap/clap gestures 86, 80; two thirds 92, 91; all
92-94 -- still rising, the shock classes are data-limited. 120 epochs 94,
96. Adding the raw gravity-swing channel 97, 94, 93. Both together 90, 96,
95 -- no better than either alone; seed spread (+/-3) is as big as any
single change. Balancing classes by subsetting the flicks to 19 each:
92, 94 -- a tie, imbalance is not the problem. Without the room channels
gesture TYPE is best of all (98, 99) but direction falls (91, 89): the
room frame buys direction at a small cost in firing confidence. Event
policy: a 2-window minimum run would add 2-3 shock-class hits and zero
ambient events; the no-fires mostly have a correct-class run of 0-2
windows. Window-level confusion inside the shock group is small (snap 95-
98% itself, double_snap 73-83% with 10% to double_clap and snap, clap
66-84% with up to 19% none, double_clap 89%). Conclusion: recall is at
89-94% with the remaining loss in the shock classes; the levers that
showed are more shock-class data (the curve has not flattened) and
possibly min_run 2; channels and epochs are within noise.

**Shock classes levelled to 47-66 (2026-09-21), and the double clap got its
own definition.** A double clap at the ring is one clap landing squarely
(5-7 g) and one glancing (1.5-2.5 g), 0.2-0.45 s apart, either order;
the flick ranges rejected 16 of 21. `GestureSpec` now carries
double_gap_s / double_ratio / stroke_ratio_floor per gesture. After the
fill: snap 50, double_snap 50, clap 47, double_clap 66. Test (115
gestures, 2 seeds, thr 0.7): exact 108 and 107 (94%, 93%), type 108,
ambient 0; snap 10/10 and 9/10, double_snap 9/10, clap 7/9, double_clap
12/13 and 13/13. Val 74 and 72 of 89, weaker on clap (3/7 both seeds:
no-fires) and double_snap (5/8). Every remaining miss but one is a
no-fire; the one confusion is double_clap -> double_snap.

**Root causes of the val misses, traced gesture by gesture (2026-09-21).**
Two were the SCORER, not the model: (1) the split's wholly-inside rule
stripped a gesture's later windows when its neighbour was in the same
part (fixed: same-part straddlers are kept); (2) scoring on a part's
windows alone cut runs at boundary zones (fixed: the whole session
stream is run, only the part's gestures are counted). Same checkpoints,
val 74/72 -> 78/75 of 89, test 108/107 -> 110/110 of 115 (95.7%),
ambient 0. What remains, per gesture: (a) four soft shock gestures at
1.5-2.2 g called `none` by both seeds -- at the WEAK floor, marginal by
construction; (b) five hard shock gestures read as the other family
(clap -> snap, double_clap -> double_snap at p 1.0, double_snap -> clap):
a 5-fold random forest on 12 hand features separates the snap family
from the clap family at only 89.7% (width 2 vs 3 samples is the main
cue), so part of that confusion is the sensor, not the model; (c) two or
three mid-run confidence dips to 0.5-0.6 at thr 0.7, which thr 0.5
recovers (val 80/76, test 111/115) with ambient still 0; min_run 2
changes nothing. Ambient was never the val problem.

**Vocabulary settled 2026-09-21: snap and double_clap.** The sensor cannot
tell a snap from a clap (both a 2-3 sample shock; hand features 89.7%),
so the kept pair differs by COUNT, never by width alone. `double_snap`
and single `clap` are retired in the registry; their recordings stay and
export as unlabelled negatives. Live threshold 0.5. Retrained on the
11-class vocabulary (2 seeds, thr 0.5): **test 95/96 both seeds, every
flick class 100%, snap 10/10, double_clap 12/13, ambient 0**; val 69 and
68 of 74, the misses being two soft flick_ups and two or three double
claps called `none`, and one double_flick_up read as flick_up.

**Live, on the ring (2026-09-21, `probe.livetest`).** First run 2/20: the
ring was on the other way round; the saved bytes replayed offline gave the
same 2/20, and 17/20 with the half-turn frame applied -- engine parity is
exact (501 windows, max probability difference 0.0000), the wearing was
the whole gap. The engine now finds its frame from a fingers-at-the-floor
pose (gravity along the finger; canonical sign positive in 98-99% of
hanging-arm ambient windows), automatically or from a 3 s calibration at
start. Second run, calibrated: **18/20, every flick and snap, both
directions and types right, latency 0.55-0.8 s after the cue**; the two
misses were soft double claps (3.7 and 4.6 g, four small strokes /
a late first stroke). Two "double_flick then flick" tails on the same
gesture -> `events.DEAD_TIME_S` 0.5 s. Lifting the arm from the hanging
pose read as flick_up once: the calibration pose should end with the hand
brought back slowly.

**The snap/clap sessions were recorded turned around, and nothing could
tell** (2026-09-21). A double-clap-only live test scored 0/3 with the
calibrated frame; replayed under identity it scored 2/3, and the 18/20
session's flicks did the opposite. The hand rule needs left/right flicks,
the fingers-down pose is rare in recordings, and the blocked snap/clap
sessions had neither -- so their frame was assumed identity while they
were in fact flip_axis0 relative to the flick sessions. Frame files set,
retrained: test 96-97/102, ambient 0, and both live sessions replay at
20/20 and 3/3. Lesson: **every recording session must carry a frame
witness** -- either a few left/right flicks or the 3 s fingers-down pose
at the start -- and `probe.collect` should cue the pose itself.

**Training recipe.** Default channels `shape,scale,saturation,room`,
direction head off, flicks direction-split, frame spin on (no flips),
despike OFF, threshold 0.5, wear rule: sensor below the finger, same way
round; the audit and the live engine both check. Isolated one factor at a time on session 2
(2 seeds): 3-class old recipe 63.3%; 6-class costs ~5 (58.6%); saturation
buys it back (65.6%); direction head at 0.3 drops it to 55.5%. On the fresh
reference session (32 gestures, trained on sessions 1+2, 2 seeds), all of
unsplit / split / +posture tie on recall at 88-94% (thr 0.4) and ~85-88%
(thr 0.9); the split is free and yields direction, and `posture` raised
low-threshold ambient false positives in every arm (unsplit+posture worst:
0.53-0.80/min at thr 0.4 vs 0.30-0.37 without), so it stays off by default.
Session 2 is the hard session -- 76.6% recall even trained on session 1 + the
reference -- recorded at 1 a.m. at a ~50-degree different hand pitch.

**What "satisfactory" currently means, honestly.** Recall: 19-20 of 21
valid gestures on ONE held-out session (both misses one soft
double_flick_right read as left). False positives, MEASURED for the first
time on two held-out ambient hours (2026-09-15, 119 min, a model trained on
no ambient hour): hour 1 (1 a.m., vigorous) 8/h at thr 0.4, 4/h at 0.9,
3/h at 0.95; hour 2 (evening) 4.1/h at 0.4, 1/h at 0.9 and 0.95. The
deployed checkpoint (trained on hour 1, hour 2 held out): 4.1/h at 0.4,
1/h at 0.8-0.9 (a `clap`, unmapped), 0 at 0.95; zero mapped flag/approve
events in 59 min at thr 0.9, which bounds that rate at 3/h. The rollout's
calibrated threshold on hour 2 is 0.93. So at the deployed operating point
the ambient rate is about 1/h all-classes and bounded at 3/h for mapped
actions -- not yet demonstrated below 1/h, which needs the third hour.

**Realtime engine** (`whip/realtime.py`): decode -> `StreamingHampel` (fixed
120 ms lag; same maths as batch, running MAD floor because a stream has no
future -- and the floor must NOT be a constant, it varies 10x across sessions)
-> 50-window at stride 6 with dataset-identical centring -> the checkpoint's
channels -> forward -> threshold -> RunTracker. The parity test demands
identical events from the engine and the offline chain on the same samples.
Latency ~1.3 s for impulsive gestures, stated in the UI. Events + resolved
actions land in `data/live/events_*.jsonl` -- the artifact M2 consumes.
`data/app_config.json` maps gestures to actions (`flick`->flag,
`double_flick`->approve by default; `flick:up`-style keys win over bare names).

**Ring console** (`python -m probe.serve` -> http://127.0.0.1:8642): live
waveform/probabilities/events, settings, and stock <-> gesture flashing with
every refuse-by-default gate from `whip/flashing.py` (shared with the CLI so no
frontend can skip one) plus: state machine forbids flashing while streaming, a
server-enforced dry-run must pass per connection (HTTP 412), and the typed
FLASH word. After a flash the ring reboots and the manager settles to idle.
`probe/live.py` is the same engine headless.

**Checkpoints are self-describing**: labels, channels, direction_names,
direction_trained, trained_on. Consumers read the vocabulary from the file;
adding a gesture = record (`probe.collect --gestures snap,double_snap` or
`--cues` for sustained), re-export, retrain. No code edits.

The C++ daemon remains the eventual spec deliverable; the Python engine is the
reference implementation it must reproduce (numpy-only preprocessing on
purpose).

## M1 design decisions

Architecture is an InceptionTime-style 1D CNN, ~226k parameters, on 50-sample
windows (2.0 s at 25 Hz). Input is **four** channels, not three: see "shape and
scale" below.

```
InceptionBlock(4->128)    parallel k=9,19,39 + maxpool branch, 1x1 bottleneck
InceptionBlock(128->128)
InceptionBlock(128->128)  + residual 1x1 shortcut from the input
GlobalAvg (+) GlobalMax (+) GlobalStd -> Dropout -> Linear(384->3)
```

**No temporal pooling anywhere in the trunk**, and that is the point. The first
design pooled 2x twice (50 samples -> 12) and then pooled globally. The
discriminator is *oscillation count* -- singles 2 peaks, doubles 5 -- and a 1.4 s
double flick is ~35 samples, ~8 after pooling, so five distinguishable peaks sat
at the Nyquist limit. Global average and global max cannot count in any case: one
reports total activation, the other the largest single value. The architecture
was discarding the feature the classes differ on.

Kernels span three time scales because one scale cannot cover the problem: at
25 Hz, k=9 is 360 ms (one oscillation), k=19 is 760 ms (the gap between two),
k=39 is 1560 ms (the whole gesture).

**The architecture table below is PROVISIONAL and mostly ties.** It is kept
because the reasoning about pooling is sound and the ranking is the best that
exists, but it was produced under a protocol since found to be broken, and a
re-rank is pending. Read it with all four caveats.

| architecture | recall @ 1 FP/hour |
|---|---|
| CompactNet (the old one) | 57.1 ± 13.6 |
| + std pooling | 62.1 ± 6.3 |
| dilated, no pooling | 62.3 ± 8.9 |
| dilated + attention pooling | 63.8 ± 15.4 |
| resnet1d (499k params) | 59.4 ± 4.9 |
| conv + biGRU (DeepConvLSTM) | 56.2 ± 12.4 |
| **GestureNet (inception)** | **69.9 ± 7.4** |

**1. Every threshold was chosen by looking at the evaluation negative.** That is
tuning on test, and it inflates recall too, by a different amount per model. It
is also unstable in a way that reads as model variance: typing is 10 minutes, so
a 1/hour budget permits zero events and the threshold becomes an extreme-order
statistic. A real share of the ± columns is that number moving. `whip/evaluate.py`
now forbids this; see "Measurement rules" below.

**2. Only seed spread is shown. Sampling spread is larger and absent.** At 64
held-out gestures the binomial interval on 70% recall is about ±11 points. The
earlier claim that "differences under ~8 points are not resolvable" counted seed
variance alone and was wrong by roughly half. **Most rows here are ties.**

**3. "+12.8 from fixing the pooling" conflated several changes.** GestureNet also
changed the block type, the width, and 18k → 226k parameters. The *isolated*
pooling change is the std-pooling row: **+5, with overlapping intervals.**

**4. Two specific claims do not survive.**
- *"Recurrence lost"* -- 56.2 ± 12.4 against CompactNet's 57.1 ± 13.6 is a **tie**,
  not a loss. It remains true that `GestureNet` is pure convolution and needs no
  recurrent port, but that convenience was doing some of the deciding.
- *"Size bought reliability"* -- **withdrawn.** `resnet1d` has the tightest spread
  in the table at 499k params and a lower mean. The claim never held.

The flatten-head comparison elsewhere in this file has the same problem: it used
its own conv trunk, so it was never a pooling ablation. And the explanation given
for why it lost -- translation sensitivity against 88% window overlap -- is
backwards. Overlap supplies every offset during training, and event scoring needs
only one of ~8 windows to fire. The observation stands; the explanation does not.

---

## Measurement rules

Each of these exists because breaking it produced a confident wrong answer.

**Calibrate on data you do not report on.** `whip/evaluate.py` takes a
calibration negative and reports on a different one;
`dataset.split_session_by_time()` splits one session in two when there is only
one, with a guard band because 2.0 s windows at 88% overlap would otherwise share
samples across the cut.

**Report a curve, not a point.** A single operating point compares confidence
calibration as much as discriminative power.

**Report both variances.** Seed spread and sampling spread are different
quantities; `bootstrap_recall_ci` gives the second.

**A rate is per minute of the activity measured.** Nobody waves for an hour, so
"73 false positives per hour of waving" was never a meaningful number. Per-hour
is for ambient wear.

**Zero events is not evidence of a low rate.** By the rule of three, zero in T
minutes bounds the rate at 3/T. A clean *hour* of ambient wear bounds it at
3/hour, not 1 -- so it could never have settled the build spec's criterion.
**Demonstrating < 1/hour takes over three hours of clean wear.** An earlier
recommendation in this project for "one hour of ambient" was insufficient, and
`MIN_AMBIENT_MIN` is 190, not 30.

**Count false positives per segment, never on a concatenated stream.**
`events.detect` has no notion of time, so joining sessions end to end lets the
tail of one and the head of the next form a run that never happened.
The same artifact appears INSIDE a session once the audit removes a
gesture's windows: the two same-class gestures either side of the hole fused
into one 12-window run centred on the hole, and both scored as misses
(2026-09-15, four "misses" that were all called correctly window by window).
`RunTracker` now ends a run at any step longer than two strides
(`MAX_RUN_STEP_S`), live and offline alike.

**A model cannot reject what it has never seen.** The claim that the
loud-deliberate versus loud-incidental distinction was absent from the data
rested on 13 architectures failing on waving -- with the waving clip held out of
training in every one of those runs. Split a negative session in half by time and
train on one half instead. Doing that moved waving false positives from 73.6/hour
to about 14/hour.

**Shape and scale are separate channels.** Trained on raw g, the network keys on
amplitude, because amplitude is the easiest feature there. That one shortcut
causes both failure modes at once: soft flicks peak near 2.3 g and typing peaks
near 2.0 g, so an amplitude threshold misses half the soft gestures *and* fires
while you type. `to_model_input` feeds three unit-amplitude waveform channels
plus one log-peak channel. Over five seeds: soft recall 28 -> 39%, hard 61 ->
78%, typing false positives 10 -> 4/hour, variance roughly halved.

Dividing amplitude out *entirely* is worse in the other direction -- a quiet
window normalises sensor noise up to full scale and starts to look like a
gesture, costing 6 points on hard flicks. Keep both, separately.

Also ruled out: biasing amplitude augmentation downward to synthesise soft
flicks from hard ones. It makes things worse (soft 31 -> 24%), because hard
flicks clip at ±4.09 g, so scaling one down yields a flat-topped signal at low
amplitude -- not what a real soft flick looks like.

**Window and receptive field were both sized from measurement, not assumption.**
A first pass used 38-sample windows and a k=3 third layer, giving a 960 ms
receptive field on the assumption that a double-flick was two taps ~300 ms apart.
Measuring 33 real gestures showed they run **0.8-1.4 s**, so 74% of them exceeded
that receptive field and the window left only 125 ms of alignment slack.

That lesson holds, but the fix changed. The k=39 branch alone spans 1560 ms, and
with three blocks the stack sees the whole window, so receptive field is no
longer the binding constraint -- resolution is. Window stays 2.0 s (~600 ms of
alignment slack).

**The discriminator is oscillation count, not duration.** Singles average 2 peaks,
doubles 5. Duration overlaps completely between classes -- best duration-only
split is 73%, peak-count reaches 85%. Those are the baselines the model must beat.

**Clipping is confirmed.** Flicks peak at ~6.5 g against a ±4.09 g range, so
amplitude saturates on hard gestures and shape has to carry the discrimination.

**Three poolings, concatenated.** Max reports pattern identity ("did the two-peak
template match"), average reports total activation, and **std reports variation
over time**, which is the closest cheap proxy for oscillation count. Adding std
alone to the old architecture was worth 5 points -- mean and max both discard it,
and neither can count.

**The dataset makes amplitude a 95% solution.** Peak amplitude alone separates
gesture from not-gesture at **AUC 0.953** on the training set (0.918 held out).
Negatives have p90 = 2.53 g; gestures p10 = 2.48 g. Of 6555 negative windows only
~134 are gesture-loud, nearly all from one 1.7-minute waving clip. A network
trained on this leans on amplitude because amplitude answers the question asked.

**But "the distinction is not in the data" was wrong, and the reasoning was
circular.** That claim rested on 13 architectures all failing on waving -- while
the waving clip was in `HELD` for every one of those runs. No model ever saw a
wave in training. Models fail on data withheld from them; that is not evidence
about separability.

**Amplitude-matched test settles it.** Restrict to windows whose peak lies in
3.6-7.0 g, so amplitude is matched by construction, de-overlap by taking every
9th window in time, then score gesture vs waving:

| feature | separation |
|---|---|
| peak amplitude | 0.707 |
| crest factor | 0.870 |
| zero crossings | 0.927 |
| **energy concentration** | **0.972** |

Medians: zero crossings 6 (gesture) vs 17 (waving); energy concentration 0.47 vs
0.27. One hand-computed feature, no model, no training. A flick is one impulsive
lobe then quiet; a wave is periodic for seconds.

So the real diagnosis is an **objective and weighting problem, not an information
problem**. 134 loud negatives out of 6555 is 2% of the negative set -- under plain
cross-entropy, getting every one of them wrong costs almost nothing. Fixes are
oversampling loud negatives, a two-stage amplitude-gate-then-shape-classifier, or
explicit shape features. Not "collect until the model notices."

Collecting high-energy negatives is still right, for a different reason: 16
de-overlapped waving windows from one person on one day demonstrates the feature
exists and cannot train or validate a deployable rejector.

**The loud idle and typing windows are artifacts, not motion.** Windows above
3.6 g have a median width above half-peak of **1.0 samples (40 ms)**; a real flick
is ~9 samples. Idle has 27 such windows, typing 2. These are BLE or firmware
glitches, and the log-peak scale channel has been consuming them. A median-3
filter removes them (idle 27 -> 1, typing 2 -> 0) at a 17% cost to real gesture
peaks -- worth doing, but it moves every amplitude threshold, so it invalidates
existing calibration rather than dropping in.

**Ruled out, with numbers.** Each of these is the obvious simpler thing, and
each is measurably worse at a matched 1 FP/hour budget (7 seeds):

| variant | recall @ 1 FP/hour |
|---|---|
| **GestureNet, shape+scale** | **69.9** |
| GestureNet, raw g | 57.4 |
| flatten head instead of pooling, shape+scale | 56.0 |
| flatten head, raw g | 43.8 |
| flatten head without BatchNorm | 31.0 |
| MLP, no convolution at all | 27.5 |

- **Removing pooling entirely loses 14 points**, with twice the parameters. A
  flatten head keeps exact peak positions, which sounds right for counting
  oscillations, but it is translation-sensitive: with 88% window overlap the same
  gesture lands at many offsets and each must be learned separately, which
  divides an already small gesture count. Global pooling is not waste, it is the
  correct prior -- a flick is the same flick wherever it falls in the window.
- **BatchNorm is load-bearing, not decoration.** Removing it costs 25 points.
- **Convolution earns its keep by ~42 points** over a plain MLP.
- **Raw g loses ~12 points under both architectures.** The penalty being the same
  size regardless of design is the strongest evidence that the shape/scale split
  is real rather than an artifact of one model.

**No softmax in the model** (CrossEntropyLoss wants logits); it lives in the C++
daemon. **No RNN** -- originally assumed, now measured: a conv+biGRU scored worst
of seven architectures (56.2% vs 69.9%). Recurrence was the one mechanism that
could in principle count events, so this was worth testing rather than asserting.
It lost, which conveniently removes the only design that was painful to port.

Classes are `none`, `flag` (single flick), `approve` (double flick). `none` is not
a gesture: it is ~99.99% of windows, and it is why the false-positive budget
rather than F1 is the binding constraint. Two positives rather than one because a
negative-only signal trains the model toward terseness and refusal.

Split: PyTorch for training (user), hand-written C++ for inference (~200 lines, no
dependency). Export weights plus **golden vectors**; the C++ must reproduce them
to 1e-5 in float. Get float parity first, then quantise -- changing both at once
makes a discrepancy unattributable.

**Single-sample artifacts were being fed to the model as amplitude.** Windows
above 3.6 g in the idle and typing sessions have a median width above half-peak
of **1.0 samples (40 ms)**; a real flick is ~9. They are BLE or firmware
glitches, and `to_model_input` derives its log-peak channel from the window
maximum, so every one arrived as "something loud happened here". `whip/despike.py`
removes them with a Hampel filter: loud idle windows 27 → 0, typing 2 → 0, at a
cost of 1.3% of gesture peak height. A plain median-3 achieves the same removal
for **16.9%**, because it smooths every sharp peak including the real ones.

**The wrist rotation axis is measured, not assumed.** A flick is a very clean
rotation -- eigenvalue ratio 0.008-0.010 on the gravity trajectory -- about an
axis that every gesture in a session shares (agreement 0.97). That axis is 0.919
aligned with axis 0, so `model.augment` rotating axes 1 and 2 about axis 0 is
right. `probe/axes.py` measures it.

**Between-session change is posture, not ring spin.** An earlier reading of
"60 degrees of ring rotation between sessions" was wrong -- it averaged the
rotation axes of directions that rotate about different axes. Measured
directly, the ring's spin about the finger differs by ~15 degrees between
sessions and the hand's pitch by ~50. The session-holdout gap is posture and
execution variety, which more sessions cover; see "The gesture platform".

**Measured false-positive baselines.** Typing and walking are cleanly separable:
a conjunction of amplitude, duration and oscillation count gives zero false
positives on both, though any single feature gives 36-66/hour. Idle coding
motions also give zero. The real hard negatives are **waving** (1320 ms, 6 peaks
-- more oscillations than a median double-flick) and **snapping** (540 ms, 5.4 g
-- a single-flick profile). Both must be in the training set.

**Debounce with a band, not a floor.** A gesture fires ~8 consecutive windows; a
3-second wave fires ~15. Requiring `>= 4 consecutive` makes sustained motion
*more* likely to fire, not less. Accept 4-12.

See `docs/COLLECTION.md` for the collection protocol and the confounds it controls.

## Tooling

```
whip/       protocol.py  packets, commands, UUIDs
            accel.py     decoding, candidate ranking, stationary filtering
            capture.py   BLE connect and notification recording
            analyze.py   rate, jitter, gaps, loss, the gate decision
            fwimage.py   OTA container parsing, timer-site location
            fwbuild.py   custom image construction
            dfu.py       DFU framing, pure and hardware-free
            corpus.py    M2 corpus: both layers, situations, validation, session plans
            labeling.py  M3 labels: records, ring join by wall/action, scoring, preferences.json
            reward.py    M4 factored reward, judge validation, M5 datasets
            arms.py      M6 three arms, fill sweep, adherence, slopes
            persona.py   synthetic labeler + arm simulator (fixtures only)
probe/      scan stream sweep drain report simulate find quiet
            firmware flash build ledsweep ledtest gestures subdata
            calibrate    M2: validate / stats / plan
            label        M3: run / join / score / aggregate
            pipeline     M4-M6: dryrun / contextfile / judgecheck
corpus/     taxonomy.json  layer 1: 12 artifact-style dimensions
            agency.json    layer 2: 11 working-style axes + 5 situation factors
            gold/          contrast items, both layers
docs/       CALIBRATION.md  M2/M3 design and confounds
            AGENCY.md       layer 2: trajectories, situations, conditional policies
            PIPELINE.md     M4-M6 components, gates, falsifiers, sample budgets
            PIPELINE.md     M4-M6 architecture, gates, falsifiers
firmware/   archived images + SHA256SUMS
              rt02cr-stock-3.12.02.bin   vendor stock, the recovery path
              rt02cr-low-latency.bin     upstream #2, 50 Hz
              rt02cr-33hz.bin            ours, #3, 33 Hz -- currently flashed
              rt02cr-31hz.bin            ours, #4, 25 Hz
```

81 tests, none needing hardware. `probe/simulate.py` fabricates captures so the
whole pipeline runs without a ring.

**Design rule:** the capture callback only timestamps and stores. The quantity
being measured is arrival timing, and any work in the notification handler
contaminates it. All decoding and analysis is offline against saved payloads,
so any new idea can be tested against old captures without recapturing.

**The build spec requires C++ for the ring daemon.** This harness is not the
daemon — it is diagnostic tooling whose job was to answer whether the hardware
clears the gate. `ring/` will be C++17, ported from these constants.

---

## Methodological lessons

Worth keeping, because each was caught by data rather than review.

**Ranking on spread alone is exploitable.** A decoder right in some orientations
and wrong in others yields a tight cluster plus outliers, and scores well once
the outliers are dropped. It put the *worst* candidate top by discarding 40% of
the data. Coverage — how much of the data a hypothesis reconciles — has to
dominate, with spread only as tie-break.

**A metric can pass on a stream that is useless and fail on one that is fine.**
Stock scored 0.00% loss with a 1114 ms hole; the low-latency firmware scores 26%
with a 74 ms worst gap. Report both readings rather than choosing the flattering
one or quietly redefining the criterion.

**Entropy is not evidence of encryption**, and a checksum that will not verify
only means the algorithm differs.

**Predict from measurement, not from the instruction.** The timer arithmetic says
`imm * 8` ms and every delivered period was `imm * 10`. Three hardware
measurements beat a correct reading of one instruction, because the instruction
is not the whole path.

**Judge preprocessing with data independent of the hypothesis under test.**
Stationarity is decided on raw bytes, so the decoder being scored cannot select
the data it is scored on.

---

## Open

- **Killing the LEDs is the only lever left on battery.** Rate is not it.
- If M1's false-positive target proves hard, `#3` offers 33% more samples at
  the cost of the loss criterion. Revisit then, not now.
- LED: find and NOP the optical enable in the raw path.
- **Preferences are policies, not archetypes.** The first taxonomy measured
  only what a single response looks like, because the presentation format
  (one response, one screen) could not show anything else. The properties that
  actually distinguish coders -- how much the model does before checking in,
  what makes it stop, whether it narrates, whether it proves its work -- are
  properties of a *trajectory*. Layer 2 (`docs/AGENCY.md`) measures those by
  contrasting **compressed action logs**, which do fit the 40-second budget.
  Two rules came out of it:
  - **Do not box a coder into an archetype.** Nobody is hands-off all the
    time. Items declare a *situation* (reversible/irreversible,
    familiar/foreign, determined/underdetermined, exploring/shipping,
    small/large) and each axis declares which factors might flip it; whether
    they do is measured. The output is "large steps by default, small when the
    action cannot be undone", not "prefers autonomy".
  - **Conditionals are detected before the main effect.** A preference that
    flips cleanly cancels out in aggregate -- four votes each way -- and the
    first implementation dismissed exactly that as `contested`. Backwards: a
    perfect flip is the most informative result there is. A flip needs 4
    decided pairs per level, each lopsided, so the design detects flips, not
    gradients.
- **Layer 2's next steps are specific**, and `probe.calibrate stats` prints
  them: four items per level on any axis whose policy matters (the detection
  threshold); items for the three declared-but-unprobed second conditioners
  (`stop_trigger`/`scope_renegotiation` on reversibility, `verification` on
  familiarity) or drop those conditioners; and two sentinels, since the agency
  layer currently has none and the fatigue check would not run.
- **Guardrails are not dimensions.** Secrets, destructive commands, unilateral
  deploys: those have right answers, are trained in regardless, and never
  appear on screen -- putting one in the corpus invites approving reckless
  behaviour. Operationally: in an irreversible situation **both variants stop
  at the same safety line**, and the axis is how much is prepared before
  returning. If one pole is wrong, it is not a dimension.
- **M2 is a curated contrastive corpus, not mined repo data.** The earlier plan
  to pull interactions from the FDD pipeline and AsyncWorld repos is replaced
  (2026-09-15): mined responses differ from their alternatives on many axes at
  once with no counterfactual, so a flag cannot identify *which* property was
  disliked, and correctness confounds taste. Each corpus item is instead a pair
  of equally-correct responses differing on exactly one of 12 taste dimensions;
  the gesture identifies the class by construction. Finalized at 60 gold items
  (5 per dimension, `corpus/gold/`), machine-validated for schema, poles, and
  length leaks. Design and confound table: `docs/CALIBRATION.md`.
- **M3 tooling is built; the sessions are not run.** `probe/label.py` is the
  presenter. Order of operations:
  1. Rule-3 read-through of the 48 expanded items in `corpus/gold/` -- both
     variants correct, no strawmen. A bug found after labeling voids that
     item's labels, so this is human review, not a formality.
  2. `python -m probe.calibrate plan --session N --pairs 40 --seed <fixed>
     --layer artifact|agency` (one layer per session -- 23 axes cannot each
     get enough pairs in one sitting),
     then `python -m probe.label run --plan ...`. Keys f / a / Enter; the
     file appends per slot and resumes. The presenter never shows the
     dimension or pole.
  3. If the ring was streaming (`probe.serve` or `probe.live`):
     `python -m probe.label join --labels ... --events data/live/events_*.jsonl`.
     Joins by `wall` on `action` in {flag, approve} only, nearest key-label
     time, 2.0 s window past the key. Missed slots are reported, not skipped.
  4. `python -m probe.label score` -- sentinel agreement >= 80%, all 12
     dimensions, none-rate <= 85%, first-shown balance; exit 2 on reject.
     Ring-vs-key agreement is printed as matched / mismatched / missed and
     silent / spurious, which is M1's acceptance check at the same time.
  5. Four sessions on different days, then
     `python -m probe.label aggregate --labels data/calibration/labels_s*.jsonl`
     -> `data/calibration/preferences.json`: per dimension the winning pole,
     `indifferent` (> 60% indifferent pairs), `contested` (a later session
     flips it -- back to item review), or `unmeasured`; plus the ordered
     `context_file` statements the M6 context arm uses verbatim.
- **The ring is secondary in M3 by measurement, not caution.** Latency ~1.3 s
  gesture-end to event. Recall reached ~90% once two sessions were in
  training, but on one fresh 32-gesture session (95% CI 75-100); ambient false
  positives are bounded only at ~6/h by 30 min of wear, and every one observed
  was unmapped (wave/snap, `action: null`), so a spurious flag/approve has not
  been seen but also not bounded below the 1/h bar. Both numbers need a wider
  sample before the ring leads; the presenter would then also need an explicit
  no-gesture-arrived path, never a silent skip.
- **Direction is recorded but deliberately not routed on.** It transfers at
  93-96% to a fresh session once two sessions are in training (2026-09-15,
  `probe/directions.py`) -- the earlier "clean permutation between sessions"
  was a one-session-training artifact, not a rotated ring -- and
  `data/app_config.json` supports `flick:up`-style keys. M3 still joins on
  `action` alone: the label vocabulary is three states, which two gestures
  plus silence already cover, so a direction qualifier would add a second way
  for a ring label to be wrong on a path the keyboard already handles at 100%.
  It is stored on every joined record and reported as a per-action habit,
  because a coder who flags down and approves up without being asked is the
  only evidence that would justify routing on it later. M3 cannot score
  direction accuracy -- the labeler is never asked for a direction, so there
  is no ground truth.
- **M4-M6 harnesses are built and exercised on fixtures; only the model-facing
  parts are blocked.** `python -m probe.pipeline dryrun` plants a known
  preference (including conditionals) and runs sessions -> labels ->
  preferences.json -> context file -> reward -> three-arm sweep, failing unless
  the plant comes back, the base arm is flat, and context degrades faster than
  weights. It proves the chain wires together and the metrics have the power to
  see an effect of the hypothesised shape -- it is **not** a result about
  weights versus context, since the arms are simulated by a function written to
  contain the effect. Same standing as `probe/simulate.py`.
- **Two eval faults surfaced from the dry run, before any real data existed** --
  the argument for building the harness first:
  - **The base arm's slope was not flat** at low sampling. Unnoticed, that
    drift would have read as context-independent degradation and contaminated
    both other arms. Now a precondition the dry run asserts.
  - **The per-dimension conditional prediction needs ~160 samples per dimension
    per fill level** (measured over 12 seeds: at ~48 it inverts on 1 seed in
    12; at 160 it holds 12/12, and more buys nothing). The pooled arm
    comparison is stable well below that, so the headline number and its most
    interesting breakdown have different sample budgets -- and the breakdown
    sets the real cost of the sweep.
- **M4-M6 design, gates and falsifiers:** `docs/PIPELINE.md`. The decisions
  that matter:
  - **M4's direction term is a function of the prompt**, not a constant:
    `s_d(prompt)`, because a conditional preference cannot be scored by a
    fixed sign. That needs a second classifier over *prompts* -- which level
    of each situation factor does this task sit at -- supervised free by the
    corpus, since every item records its situation in frontmatter. A factor
    below the 90% bar forces the dimensions conditioned on it back to their
    unconditional default rather than guessing.
  - **M6 gets a sharper prediction from layer 2.** A style rule ("be terse")
    is a local constraint on every output; a conditional policy has to fire at
    a decision point buried in a filled context. So the context arm should
    degrade **fastest on conditional axes and slowest on unconditional ones**
    -- a per-dimension prediction that a pooled adherence number would hide.
  - **M4 is a factored reward**, `sum_d w_d * s_d * (2 p_d - 1)`: pole
    classifiers `p_d` trained on the corpus's own variant labels (120
    examples, free by construction, held out *by item*), direction `s_d` and
    weight `w_d` from `preferences.json`. Indifferent dimensions get `w_d = 0`
    -- flat by construction, not by hoping a scalar head learns it. An
    LLM-judge with the taxonomy text as rubric is tried first (>= 90% per
    dimension or that dimension is not scorable). Bradley-Terry on the pairs
    is the baseline; if it beats the factored RM outside its interval, the
    taxonomy is wrong, not the RM.
  - **M5 is DPO first, GRPO second.** DPO on ~160 pairs (rank-16 LoRA, beta
    picked by held-out win-rate under the RM, not by DPO loss), KTO on ~320
    singles as an ablation, then optional GRPO against the factored RM on
    prompts the corpus never contained -- the only stage where the RM
    generalizes beyond the 60 contrasts. Guards: KL budget, reward-hacking
    check (RM score rising while human spot-check agreement falls), and a
    functional-correctness canary that must hold at the base model's rate.
  - **M6 is built first.** Three arms on one base model: none / mechanical
    context file from `preferences.json` / adapter. Neutral non-code filler
    at 0, 8k, 32k, 64k, max tokens between system prompt and task. Metrics
    in order of authority: pole-classifier adherence per dimension, human
    blind spot-check through the same keypress presenter, correctness canary,
    BT score. The research question is two numbers: the B-C gap at zero fill
    and the two slopes against fill, with bootstrap CIs and a per-dimension
    breakdown -- because "weights hold for style axes, context for behavioral
    ones" is a plausible honest result that pooling would hide.
  - **Falsifiers are written down** for each stage in `docs/PIPELINE.md`;
    a flat result across all three arms is a result, not a failure to find
    one.
