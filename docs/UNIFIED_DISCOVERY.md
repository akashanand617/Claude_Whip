# Read-only unified identification: unattached candidate

2026-09-24/25, entirely off-ring. The firmware now has a small C identity
encoder/borrowed-view helper and the app has a matching Swift decoder. Neither
is attached to Bluetooth. No capability, approved image, authentication,
production admission, storage ownership or flashing permission is established.
Health remains the unified boot/default; installed V2 optical-off is unchanged.

## Format and ownership contract

The [separate development service](UNIFIED_SERVICE_TABLE.md) already has a
read-only discovery attribute because every control request requires a boot ID.
`firmware/unified/discovery.{c,h}` supplies its proposed 20-byte value:

| Bytes | Meaning |
|---|---|
| 0–3 | `57 49 01 00`: `WI`, schema 1, reserved zero |
| 4–11 | Nonzero 64-bit boot identity, little-endian |
| 12–19 | Nonzero 64-bit build tag, little-endian |

These are self-reported identifiers, **not image attestation or authorization**.
No actual approved build tag, mapping to a full image hash, or fresh per-boot
ID generator is supplied. Stock/V2 must never be sent an unknown UART command
to obtain this value. The new app parser has no UART or CoreBluetooth calls.

`wdi_encode` writes exactly 20 caller-owned bytes, including unaligned buffers.
Null output or an all-zero boot/build ID returns false without touching output.
The caller must initialize before publication, publish only on success, and
never rewrite the published value while it can be borrowed. This helper does
not enforce initialization ownership or serialization.

`wdi_read` returns an eight-byte ARM32 pointer/length view only for offset zero.
Refusal clears a nonnull output's fields. It does not dereference, validate or
copy the value: the caller must supply a previously encoded, immutable, live
20-byte buffer and a disjoint writable view. It is **not the stock read callback
ABI**. Nonzero offsets are deliberately refused because whether ROM slices
the callback's returned base pointer afterward remains unproved; the eventual
callback still needs reviewed ATT error mapping and pointer lifetime handling.

This contract needs 20 persistent bytes in an eventual owned allocation. Added
to the selected 1164-byte all-persistent planning case, that is **1184 bytes**,
not an allocation or a demonstrated full memory budget. The eight-byte view is
caller scratch, not another mandatory persistent object. No writable static
section or heap allocation is introduced. Object-local stack reports are
24 bytes for the encoder and zero for the read helper; caller/nesting/interrupt
cost and the real task remain separate obligations.

`ios/R02Ring/Health/UnifiedDiscovery.swift` enforces exact length, magic,
schema/reserved byte and nonzero IDs. Successful parsing returns only two
numbers. It cannot enable `FirmwareCapabilities`, attach `UnifiedModeTransport`,
or bypass existing production locks. Discovery, connection generation, build
admission and return-to-stock preflight migration still need implementation.

## Actual whole-code budget, not another component subtotal

`probe/discovery_budget.py` links the 21 exact objects pinned by the current
raw-ingress checkpoint plus the newly double-compiled discovery object. It
does **not** claim to have recompiled all 22. All pinned source/tool/object
hashes are checked; generated object/stack/link/map files are snapshotted
immediately and rechecked through completion. Two ordinary links and the
map-producing link produce the same ELF.

Archive: `firmware/unified/research-20260924-discovery-budget-v1/`.

- 22 objects, 132 retained functions and three constants.
- Discovery adds **122 text bytes**. The full append grows by 124 with alignment.
- Same nine **unowned** moved-text intervals, **1894 bytes**; no extra holes.
- Append: **9240 text/constants + 16 unwind = 9256/9520 bytes**, **264 left**.
- All 1056 input unwind bytes are retained for linking and coalesce to 16;
  they are not discarded to obtain the fit.
- APP end stays `0x84a000`; stock service constants/sole relocation are checked.
- All construction/admission/ownership/integration flags remain false.

The full conditional ELF still lacks retirement stubs and production hooks;
the production verifier rejects it. **Never install it.** Remaining callbacks,
owner, scheduler/source bindings and other hooks have additional unknown cost.
The geometry/inventory inspector is not an opcode authenticator; reviewed
compilation and immediate hash snapshots supply separate provenance checks.
Failed links retain their logs/map without a successful ELF or margin claim.

SHA-256:

- Full 22-object ELF: `932203212bae6fd1354030dadba21db3c388d575def6389891da56929fc26e66`.
- Budget report: `54aa06cb7608519ff14c8e865d82867699dd3256b6f1804ee59e624ee55e53e3`.
- Guarded supplement: `4ec869f67ffe7e25be32152add9451c20c33e6ce389fbe4f7bde53c256180d3a`.

## Verification and its boundary

The final guarded supplemental run passed **63 tests in 40.88 s**, zero
failures/errors/skips/xfails, with identical ordered collection/execution
identities and all 189 phases passing:

- 16 [integrated retired-stock switching](UNIFIED_RETIRED_SWITCH.md) cases.
- 19 identity cases: actual ARM output against compiled Swift; 131 valid ID
  pairs plus malformed data; full-width offsets, nulls, alignment and bounds.
- 28 whole-budget cases: reproducibility, geometry/inventory mutants, source/
  tool/object pin failures, corruption between compile stages, refusal logs,
  and four actual-address ARM cases running the new encoder/read helper and
  its relocated `ww_put32` call with PRIMASK both zero and one.

The switch tests deliberately use the existing exact-pinned **21-object ELF**;
the discovery layout/ARM tests use the new **22-object ELF**. These are not a
claim that the entire switch ran in the new layout. The older 3251-test main
checkpoint and its two ELFs remain unchanged and were not rerun here.

The supplement records **253 content hashes**: 238 canonical inputs, 12 budget
artifacts and three proof reports; plus four tool executables and separate
launcher/SDK-metadata hashes. The standalone budget report records its own
80 inputs/12 artifacts/three tools and correctly says `tests_run: false`;
test results belong to the subsequent supplement, not the earlier link report.
Snapshots are boundary checks, not filesystem locks or hermetic SDK proofs.

The full app also built successfully for generic iOS Simulator using Xcode at
`/Applications/Xcode.app/Contents/Developer`; the new source compiled for arm64
and x86_64. Result bundle: `/tmp/whip-discovery-ios.Q7Fnk9/build.xcresult`.
Only the existing headermap warning appeared. This was a build, not a simulator
launch, phone deployment, device connection or ring test.

Next integration work is actual service resources/callback ownership, boot ID
and reviewed build admission, then production transport wiring. None can be
replaced by decoding this self-reported value successfully. All six
[release gates](UNIFIED_READINESS.md) remain open.

Subsequent [callback ABI review](UNIFIED_GATT_READ_BINDING.md) confirms that the
stock callback has six arguments and no context parameter: the owned identity
lookup cannot be smuggled in as a seventh argument. The
[boot-ID source review](UNIFIED_BOOT_ID_SOURCE.md) identifies the exact stock
startup random API, while leaving its entropy/failure/reset contract unqualified.
The [task map](UNIFIED_TASK_BINDINGS.md) additionally shows why qc_app's indefinite
wait is not an adequate supervisor for existing protocol deadlines. No new C
binding or source list is enabled by these reviews.
