# Early legacy raw/diagnostic filter — implemented, unattached

## Current A1 retirement checkpoint — 2026-09-24/25

The current helper also denies **A1**, with no subcommand exceptions. Unified
Gesture requires its separate qualified source/service; there is no raw A1
fallback. This is still an unattached candidate: stock/V2 behavior is unchanged.
Ingress denial does not cancel already-queued work or stored callbacks; the
separate [combined emulator plan](UNIFIED_STOCK_RETIREMENT.md) checks selected
such roots with exact entry stubs and the conditional full ELF.

The focused suite is now **91 cases**, including all 256 opcodes in four modes,
explicit retained Health/history/settings dispatch, all four retired opcodes
on the separate DFU route, and original pointer/length/mode/ABI checks. It passed
in 3.85 s; the complete guarded checkpoint passed **3251 in 515.24 s**, with
zero failures/errors/skips. All **371 content hashes**, four tools and SDK
metadata were independently verified. Main ELFs are unchanged.

Current helper: **64 text / 8 input unwind / 8 local stack** bytes. Append-only
all-code refusal: **11108/9520**, **1588 over**, no full ELF. Manifest:
`4ab65e86daeab7fee1d186c4fd873fe95fec7dd1dbb3040ba3ba5ee9d37d1cee`.
Object: `c50b394d7be6458cf50f6e1736723ff5f9fcb3ee43fb7a7e85c7bf566bdd3aaa`.
The conditional research link relocates the helper at `0x4c3c..0x4c7c`;
its tested emulator attachment is not production placement approval.
Dedicated app identity/discovery migration and every physical/recovery gate
below remain required.

## Historical BF/CE/CD-only checkpoint

2026-09-24. Off-ring only. Claude Code owns the user's separately coordinated
live-device work; this Codex batch neither connects to nor modifies the ring.
Health remains the unified boot/default and Gesture temporary/opt-in.

## Implementation and narrow scope

`firmware/unified/stock_legacy_gate.{c,h}` implements
`wlg_receive(const uint8_t *packet, uint32_t length)`. It is a fourth **unlinked
candidate**, alongside coordinator, Health commit and service table. Neither
main ELF contains it; no production callback or capability is enabled.

The proposed attachment replaces one complete BL at stock file `0x7b0a`,
runtime `0x82daba`, original bytes `fe f7 8a f8`. The original UART callback
has already checked its packet pointer and attribute index before this call.
The helper:

1. Defensively rejects null, then preserves stock's mode-byte-1 rejection.
2. Reads an opcode only when the **full 32-bit length equals 16**.
3. Silently rejects BF arbitrary RAM writes, CE bus/GPIO diagnostics and CD
   arbitrary reads/diagnostics before their stateful receive prelude.
4. Delegates everything else to the original gate at Thumb `0x82bbd3`, retaining
   the pointer, untruncated length and original mode/length recheck. Invalid
   lengths reach that old rejection gate without reading the packet.

There is no generated error reply, queue use, settings write, revision owner,
mode transition, authentication or allocation. The caller must own a readable,
immutable buffer for the full call lifetime. The preliminary volatile mode read
is not a serialized snapshot; the old gate can reject a later mode change.
The ordinary commands this filter admits still require the wider producer and
mode-policy hooks. In particular, **A1 is not retired by this filter**.

The neighboring two-byte branch at `0x5c2e` must not become a four-byte patch:
the next instruction at `0x5c30` is a shared rejection return. Exact callback,
gate, argument/return and alternate-entry evidence is in the
[settings-writer audit](UNIFIED_SETTINGS_WRITERS.md#proposed-early-legacy-ingress-hook--bounded-follow-up).

## What executes in the tests

`tests/test_stock_legacy_gate.py` double-compiles and double-links the helper.
It loads the pinned stock image and changes **only the four-byte UART call in
emulator memory**. A whole-image comparison checks that every other stock byte
is unchanged, and the original binary on disk remains identical.

The original UART callback and original gate actually execute. ROM logging,
the downstream legacy dispatcher and the separate DFU reassembly function are
explicit test boundaries. Reaching ordinary dispatch is recorded; its Health,
settings or sensor behavior is not simulated as a successful physical result.
The artificial helper ELF is rejected by the production placement verifier.

The **69 focused cases** include:

- All 256 opcodes in each of four stock mode-byte values, compared with the
  original callback. Only BF/CE/CD's admitted dispatch behavior changes.
- Invalid full-width lengths, including values whose low 16 bits equal 16,
  using an unmapped packet pointer to expose an early or narrowed read.
- Mode-1 rejection before opcode access, null pointer and attribute error
  paths, and a mode change just before the original gate's second read.
- Original return values, stack/callee-saved registers, PRIMASK, argument and
  packet canaries; no non-stack stores by the executing filter/callback.
- BF/CE/CD bytes passed through the **separate stock DFU callback** at `0x79b6`
  to its `0x823e` boundary without entering the UART helper. This is routing
  preservation, not completed DFU, power-loss recovery or boot proof.
- A restored-original-BL mutant exposes forbidden diagnostic dispatch.

Independent review corrected two test-oracle issues: UART runs now reject any
unexpected DFU routing; R3 preservation is required only on stock attribute-2
paths, with original-stock comparison on error paths that reuse its saved slot
for logger arguments. Those are harness fixes, not firmware fixes. The final
focused run passed **69 in 3.57 s**, independently repeated **69 in 3.46 s**.
The full guarded checkpoint `build-20260924-legacy-gate-v1` passed **3212 tests
in 434.50 s**, zero failures/errors/skips. All **370 hashes** match (196 inputs,
171 artifacts, three reports); both main ELFs are unchanged from coordinator-v1.
Manifest SHA-256:
`cbfd74c0eb2218b5f2e6d5f10570b5dceb811a1c817087fd4c04bd6bf60e3467`.
Focused counts overlap this suite and must not be added to it. See the
[resource handoff](UNIFIED_RESOURCE_BUDGET.md) for the separate physical RAM read.

## Compatibility prerequisite: migrate app identity before attachment

Current iOS Gesture/V2 identity performs **22 CD01 code reads**. Silently
retiring CD while reusing that version string makes the first request time out;
`uartNeedsReconnect` then prevents further requests, including the battery
preflight for app-based return-to-stock. Reconnect repeats that fingerprint.
Reusing stock's version would instead falsely classify unified as stock.

Therefore **dedicated unified identity/discovery and app admission must be
implemented and tested before this filter is attached to any deployed image**.
The candidate header records this prerequisite. No exception allows arbitrary
CD01 through the old stateful path, and no identity/battery/reconnect guard is
bypassed. The app and existing installed diagnostic image are unchanged.

Ordinary Health request opcodes are not BF/CE/CD. Sleep and DFU use separate BC
framing and callbacks; never apply this byte denylist to all BLE segments.
Research tools using CD/CE will intentionally stop working on a future retired
interface. Their current captured evidence remains usable offline. These are
source/routing findings, not measured Health/steps/sleep continuity or recovery.
See the [full compatibility audit](UNIFIED_SETTINGS_WRITERS.md#compatibility-health-and-recovery-impact-of-retirement).

## Combined budget and remaining roots

The helper is **56 text bytes plus 8 input unwind bytes**, with an eight-byte
compiler local stack frame and no writable static state. Input unwind is not
added blindly to final coalesced unwind. The whole implemented-code failure map
now has **11004 text/constants + 96 unwind = 11100 bytes**, **1580 beyond** the
fixed 9520-byte append region, before other hardware/service hooks. No
full-candidate ELF is emitted; the component-only main link is unchanged.
The builder now snapshots refusal logs/maps immediately when created, before
parsing them, and rechecks them with the other proof artifacts.

The [diagnostic retirement audit](UNIFIED_DIAGNOSTIC_RETIREMENT.md) identifies
496 handler instruction bytes and only **476 conditional aligned bytes** after
entry-stub allowances. BF's 40-byte intervening literal/string island has live
Health/timer users and is excluded, as are shared I/O, notification and timer
helpers. Even optimistic subtraction leaves **1104 bytes** of this new deficit;
also subtracting the earlier unowned 408-byte indicator relocation still leaves
**696**, before further costs. Those are arithmetic scenarios, not fitting
links or approved reclaimed space.

The static ingress scans do not close computed/ROM/patch entries or runtime
pointer mutation. An early filter cannot repair prior arbitrary-memory changes.
Any later attachment must be part of an identified boot image, precede normal
admission, preserve all other bytes and satisfy app migration, memory ownership,
complete fit, hardware/continuity and recovery gates. **Approved reclaimed flash
remains zero; no release gate is fully closed by this filter.**

The parallel compiler-target check ruled out an M4 retarget as a size shortcut:
Realtek specifies Cortex-M0+ for the RTL8762E variants. Current M0+ flags agree
with that family specification; package/CPUID and physical execution are not
newly attested by this check. No compiler target or ABI changed.
[Primary vendor specification](https://www.realmcu.com/en/Products/RTL8762E-Series).
