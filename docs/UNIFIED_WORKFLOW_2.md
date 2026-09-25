# Unified firmware: capacity, fresh source and lifecycle follow-up

2026-09-23. Health remains the boot/default mode; Gesture is explicitly temporary.
This follow-up builds on [the first workflow](UNIFIED_WORKFLOW.md), but its proof
artifacts must be regenerated for the new sources. No unified OTA image is
constructed, no production capability is unlocked, and nothing is flashed.

Historical checkpoint: [workflow 3](UNIFIED_WORKFLOW_3.md) subsequently completed
the separately coordinated descriptor read and deepened the stock-code checks.
The next-check list below describes the state at the end of this second workflow;
its 512-test artifact does not attest later source changes.

## Bounded device session

The user confirmed that QRing, the phone ring app and other laptop clients were
closed and the ring was idle. The new fixed-plan reader was independently
reviewed and passed 21 fake-transport tests before a single connection. It
permits only the pinned code fingerprints, diagnostic-path code, raw-mode byte,
16-byte RAM configuration and 48-byte flash configuration. It cannot follow
returned pointers, scan arbitrary memory, start/stop sensors or flash.

Evidence: `data/capacity-20260923-idle-config/transcript.jsonl` and
`configuration.json`. These are generated local captures, not synthetic tests.
The reader disconnected after collecting the data. It sent only `CD 01` UART
transactions; Device Information was read through GATT. Both configuration
windows were read twice and agreed. Raw mode was zero before and after.

The existing 22 critical sites and additional diagnostic-path windows matched
the V2 reference. **This is a limited fingerprint, not an on-device full-image
hash.** The capture's `image_sha256` names the reference image used for matching.
The legacy `CD` prelude changes activity, timer and connection-policy bookkeeping;
this was not a wholly non-mutating operation. No sensor/flash/reset call was
found in the mapped diagnostic path, but opaque ROM work and races remain outside
that static review. No automatic retry or further bank-pointer read occurred.

The strict configuration parser initially refused `backup1`, whose pair was
outside its supported flash-address envelope. Raw evidence was preserved and
the session ended. Review of the exact V2 startup found writes deliberately
replacing those two configuration words. They cannot be used as chip-capacity
evidence. See [capacity interpretation and diagnostic audit](UNIFIED_CAPACITY_GATE.md)
for the supported interpretation and unresolved fields.

## Off-ring components

- `health_adapter.{c,h}` separates cancellation/draining, publication fencing,
  verified physical STOP and current-settings resume. Old callback tickets and
  unmeasured fallback results do not become new Health measurements.
- `fresh_source.{c,h}` validates acquisition receipts and copies one original
  frame per 40 ms bucket, without changing Health's source or cursor. There is
  no built-in qualified hardware profile. Stock does not currently preserve all
  necessary acquisition-time, overflow and transport-completion evidence.
- The additional integration joins these components to the existing controller
  and sample runtime. Receipts remain explicit physical obligations, not proof
  that a stock hardware binding exists.

The artificial ARM test ELF executes its C memory helpers and unsigned division
helper; these are not Python substitutes or a claim about the stock ROM ABI.
The division test checks edge cases and deterministic randomized pairs against
host integer arithmetic. Any real compiler-runtime linkage still needs reviewed
placement and ABI evidence.

Detailed source assumptions: [fresh-source audit](UNIFIED_FRESH_SOURCE.md).
One frame per bucket is not a promise of exactly 40 ms physical intervals;
compatibility with the finalized gesture model still needs measured-stream
replay. No interpolation or guessed fixed-ratio decimation is introduced.

## Gates still distinct

A reported bank map is not a physical flash capacity measurement. A configured
application region is not approved free RAM/code space. Passing synthetic FIFO
receipts is not a measured fresh source. Executing selected stock callbacks
against a publication guard is not complete interception of stock timers, ROM
producers, hub work and physical optical RUN/STOP.

Keep these gates closed until the corresponding device-specific evidence exists.
In particular, do not install an incomplete Health gate merely to enable Gesture:
unavailable unified capability must leave ordinary stock Health untouched.

## Validation record

The current existing firmware/protocol/accelerometer/cleanup regressions passed
206 tests (189 + 17 in separate invocations). No iOS source was changed or
redeployed by this follow-up.

Two complete guarded builds passed **512 tests, zero failures/errors/skips**.
The first took 37.33 s; the final execution took 32.70 s. Before the second run,
the two firmware-byte parameters received readable test IDs, so reports do not
embed entire binaries in test names. The final local output is:

```
firmware/unified/build-20260923-workflow2-final/
  manifest.json
  unified-test-only.elf
  collected.json / executed.json / tests.xml
  component and test-support .o / .su files
```

- Test ELF SHA-256:
  `3120d3934dcbced8fcd192bfa024c8cafa46412b0a2ec3af6dbe9dc2386d76bf`
- Manifest SHA-256:
  `d342db09195986ef2f5873c26a0a53a8e0782ba360bb3d46fe70cc7600887912`
- All **74** source/artifact/report hashes were rechecked after completion.
- Both runs double-compiled every component and support object and double-linked
  the ELF with byte-identical results. Neither run accessed hardware.
- The final ARM suite includes 58 tests: existing runtime checks, actual
  unsigned division and overlap-safe memory operations, default-Health refusal,
  real-instruction execution of the joined source/lifecycle component, bad FIFO
  receipts, clock wrap, partial entry and genuine Health-fault recovery.
- Other suites include 73 capacity checks, 21 fake-reader checks, 65 Health
  component/stock-witness checks, 47 fresh-source checks and 52 native adapter
  integration checks. These counts are subsets of 512, not additional passes.

Integration review found and fixed a genuine Health fault leaving the public
mode at Health despite a closed internal gate. The adapter now reports Fault
promptly for a proven-inventory failure, while retaining ordinary Health for
an unavailable boot capability. Recovery still needs explicit cleanup receipts.
The first exploratory expanded ARM link also correctly refused unexpected
writable compiler-runtime data. Adding executed, bounded `memcpy4`/`memmove4`
test helpers resolved it; linker/memory guards were not weakened.

The six component objects contain 5600 `.text` bytes before placement, real
hooks, transport, relocations and compiler-runtime integration. This is **not**
a final image size or proof of fit. Artificial code/RAM addresses and test-only
profiles remain unsuitable for deployment.

## Concrete next checks

1. A separately coordinated, bounded read of bank0's 80-byte descriptor at
   `0x802198`, repeating identity/configuration checks first. Do not follow the
   absent bank1 or the unresolved backup1 declaration. This was not run.
2. Cross-check actual app extent, chip/erase geometry, OTA routing/recovery and
   RAM ownership. Current configuration gives only a **9520-byte upper bound**
   beyond the stock image, not approved expansion space.
3. Obtain physical FIFO timing/completion/overflow evidence without changing
   Health's source, and validate resulting samples against the gesture model.
4. Close and implement the actual producer/result inventory and serialized
   hardware bindings described in [the Health audit](UNIFIED_HEALTH_ADAPTER.md).
   Verify real STOP, current-settings resume and steps/sleep continuity.

No unified image, app deployment, commit or push was performed. Construction
and production capability gates remain closed; this workflow is not flash-ready.
