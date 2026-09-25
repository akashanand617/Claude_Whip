# Bounded boot-reference comparison

2026-09-23. This is an evidence-gathering diagnostic, not a firmware installation
or recovery test. Health remains the unified boot/default requirement; the ring
currently runs V2 optical-off. No installable unified image exists.

Later [captured-ROM execution](UNIFIED_STOCK_INTEGRATION.md#captured-rom-execution-and-null-queue-guard)
resolves the error helper `0x4c7a` mentioned below: its captured body only stores
a bounded image-indexed error byte. It is no longer an unknown helper, but its
callers' wider recovery behavior remains unproved. Header early-rejection paths
are also executed; valid-looking headers reach an unread shared literal, so
complete header/activation/recovery proof is still unavailable.

The separately [completed support-code read](UNIFIED_SUPPORT_READ.md) captured
the referenced flash/OTA literal pools, not their pointed-to storage or header
key/authentication fields. All 284 transactions passed and disconnect was
verified. OTA-table-header magic checks now execute with actual constants; APP
checking reaches unread comparator `0x8e24` and stops the proof there. These
constants do not establish physical flash geometry or a failed-boot recovery
route. No extra address was followed; further device work needs new coordination.

The newer [create-hook reference review and read plan](UNIFIED_CREATE_HOOK_READ.md)
finds an actual SDK/ring hook mismatch: SDK initializer writes `0x206359` to
the create slot, while this ring reported `0x205c01`. This reinforces why the
matching boot component/ROM UUID does not attest the rest of the system image.
The next bounded prefix/code diagnostic is prepared but NOT RUN.

## References examined

Nosh118's `colmi-ring-tools` at commit
`bf68bf4a0234f8341729fb8d487c34597af088df` contains the application binaries,
patch/container/protocol notes and browser flasher already used here. Its
RT02CR low-latency binary matches our local reference exactly. Those references
are useful, but do not include an exact ring SDK, link map or hard-brick recovery
procedure. A BLE-connectable recovery image is not recovery from failed boot.

The related Realtek SDK-origin mirror
[`atc1441/ATC_RTL_BLE_OEPL`](https://github.com/atc1441/ATC_RTL_BLE_OEPL/tree/49301d9b75816ccde1cc9657b827fdadf5736937)
contains additional source, headers, a UART loader and system image. It targets
an e-paper board, **not this ring**. The system blob `gcc/data_0x801000.bin`
under `ATC_RTL_BLE_OEPL_8762ESL/` is 190668 bytes with SHA-256
`ca53de5cfabc4eb9f4071773fe65db0e573560a0ad0c53c9c4d4ddfa02124347`.
Its UUID agrees with the ring reference, which alone does not establish that
any installed code or layout matches.

The mirror places APP at `0x832000`, 148 KiB, and reserves 144 KiB for upper
stack; the ring descriptor puts APP at `0x826000`, 144 KiB, with a 96 KiB upper
stack. Its application RAM/heap sizes also differ. Do not transplant its flash
map, system blob or RAM assumptions. Its UART loader requires physical serial/
download/reset access; that access and recovery are not established on the ring.

The mirror's secure-boot descriptor does agree with the ring's declared secure-
boot partition at `0x80d000`. The external header declares 528 code bytes at
`0x80d400`, executing at `0x214000`. Only a 52-byte non-secret header prefix and
those code bytes are retained in
`firmware/research/2026-09-23/reference-boot/rtl8762e-sdk-boot.json`. It is labeled
external reference, not device evidence or an installable image. Original rights
remain with their owners. The original header's key/authentication metadata is
excluded.

## Freshly coordinated fixed plan

The user confirmed all clients closed and the ring idle for this comparison.
The originally proposed 64-byte prefix was narrowed **before any device read**:
the SDK header's `dec_key[16]` begins at offset `0x34` (52). The selected read
ends at that boundary. No key bytes, authentication block, OTP or MMIO are read.

`probe.rom_read --boot-reference` / `whip.fwboot_read` perform:

1. The existing 91-transaction V2 identity, audited CD code, idle, configuration
   and bank0 descriptor plan. Require the exact archived descriptor hash.
2. Read `0x80d000..0x80d034` twice. Require exact equality to the reviewed
   external non-secret prefix. Any mismatch stops before the code read.
3. Only then read `0x80d400..0x80d610` twice. Compare repetitions and preserve
   whether these bytes match the SDK. No returned target is executed/followed.
4. Recheck configuration and idle; unsubscribe and verify disconnection before
   declaring a successful capture.

Maximum 182 serial CD01 transactions; no retries/reconnect, arbitrary-address
input, sensor commands, clock/settings writes or firmware transfer. CD01 itself
has the previously audited activity/timer/connection-policy bookkeeping side
effects. Sampled identity is not complete live-image attestation. Collection is
bounded to 120 seconds, the full workflow to 180 seconds. An ambiguous reply,
timeout, changed prerequisites/repetition/postcheck or unconfirmed disconnect
aborts the plan; an abort does not itself prove successful disconnection.

## Preflight

408 scoped tests passed, zero skips, before connection: boot/ROM readers,
configuration/descriptor transport and CLI, saved captures and selected timer
execution. New cases cover prefix-before-code gating, exact count and boundary,
key/adjacent/returned-pointer exclusion, prerequisite/repeat/postcheck changes,
transport faults, one-use closure, conflicts and cleanup. Actual pinned CD
instructions were executed offline at both ends of each new window, on original
25 Hz and V2 under three dispatch states; source bytes and memcpy/timer callees
were explicit fixtures, not physical boot or recovery evidence.

The prior 1276-test full build predates this reader and is not a hash statement
about the newly modified sources. A matching boot reference would improve code
provenance, not prove chip geometry, power-loss recovery, allocated RAM, physical
FIFO timing, STOP/resume, model accuracy or steps/sleep continuity.

## Completed physical comparison

The separately coordinated session completed **182 matching CD01 transactions**
and verified disconnection. Both reads of the non-secret header and both reads
of the 528-byte body agree exactly with the SDK reference. Before/after idle
and configuration checks passed. No key/authentication field, sensor command,
flash, pointer-following or on-device target execution occurred. Clients may
reopen; this session grants no continuing idle authorization.

Original evidence is in `data/boot-reference-20260923-01/`, with byte-identical
copies in `firmware/research/2026-09-23/boot-reference/`:

| Artifact | SHA-256 |
|---|---|
| `boot-reference.json` | `f9798ed89e9d2e5b055a2fd5f930be635621e7ec7f35e0e0ada6bd82e36b8aed` |
| `transcript.jsonl` | `e5391cc14ccb75d3f196316bf05af54d26b685a5ecd39d1e142118c7b23d1925` |
| 52-byte prefix | `d37a5699dfb71b63e0c9c9f30c45e95b82b1a1ace2b80481b5f7ad49708aa109` |
| 528-byte body | `17a7115e12cc472b5e745802be29df8b0b0917cfc3eaa4ee99d2f4134c59cf04` |

An offline replay checks all saved request/reply checksums, ordering, allowed
addresses and exact emitted requests, and reproduces the saved capture. This
guards against evidence/code drift; it is not another independent device test.

## What this specific boot component does

Disassemble at its declared SRAM execution address **`0x214000`**, not flash
storage `0x80d400`, or its PC-relative calls will be misidentified. Actual entry
code and its two captured helper bodies:

- Initialize log UART; use the known ROM header resolver for image IDs `0x278d`
  and `0x278e`. Those ROM implementations are not captured here.
- Check a 480-byte factory-data region against its following 32-byte SHA-256,
  trying the alternate location when the first fails. Publish a validity byte
  at `0x2011dc` and selected data pointer at `0x200110`.
- If neither factory-data copy validates, return before the OEM checks. The
  helper calls an unidentified ROM failure routine at `0x4c7a`; its real side
  effects remain unproved.
- For OEM configuration, reject an erased first byte (`0xff`), otherwise compare
  SHA-256 over 96 bytes with the next 32 bytes. Try the alternate location after
  primary failure; store the chosen pointer at `0x200114` and validity at
  `0x2011dd`. Then clear `0x2011ea`.
- The entry returns `1` even on the captured no-valid-factory-data branch;
  treating this return alone as successful configuration or recovery is wrong.

Sixteen offline ARM cases execute the captured entry and helpers across all
primary/alternate hash-validity combinations. Factory/OEM data are invented;
ROM lookup, SHA-256, comparison, UART/logging and the unidentified error helper
are explicit mocks. Checks cover results, selected pointers, early return,
callee-preserved registers, balanced stack and bounded RAM writes. No actual
factory data was read and no boot code was called on the ring. Unread ROM
callees may have additional effects; these tests do not qualify the full boot
chain, image verification, copy/activation or power-loss recovery.

This closes the provenance question for **one 528-byte component**. It does not
make the e-paper board's differing flash/RAM map usable on the ring. The remaining
integration is still substantial: approved stock-linked placement and RAM,
recovery evidence, serialized health bindings/fences, physical fresh-source
timing and real health/steps/sleep continuity. Construction gates remain closed;
there is no unified OTA file to flash.

## Historical full build

The boot-only continuation completed its guarded build in
`firmware/unified/build-20260923-boot-reference-v1/`: **1356 passed in 119.04 s**,
zero skips/failures/errors, all 138 hashes checked (106 inputs, 29 artifacts,
three reports). Manifest SHA-256:
`400af47d8685b9341f8b413e5e6510297a06943b6fc4c3a5fb3318504542f4f3`.
Its test ELF was unchanged from the preceding memory/ROM work. This is a
historical input snapshot, superseded by the
[stock-address implementation](UNIFIED_STOCK_INTEGRATION.md), not a hash claim
about later source changes or an installable image.
