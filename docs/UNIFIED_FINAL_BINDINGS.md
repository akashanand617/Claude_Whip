# Final-build bindings: concrete remaining work

2026-09-24/25. Off-ring review of the accepted control owner and pinned stock
instructions. This is preparation for a final build, **not a final image**.
Health stays the boot/default. None of the definitions below may be supplied
by a guessed address, constant clock or test-only provider in a release link.

| Required symbol | Established reference | Missing binding |
|---|---|---|
| `wco_bound_owner` | Implemented 880-byte owner; stock qc_app initialization `0x131e → 0x3714/0x12d2`, candidate wait hook `0x135c` | Owned storage, boot/retention lifetime, initialization after Health and before admission, qualified boot ID, serialized callback/receipt/output handoff and bounded servicing |
| `wco_bound_stock` | Stock optical **pointer slots** `0x20859c/0x2085a8`; read/clear paths `0x11994/0xfbc0` | Actual pointee allocation/lifetime, reviewed publication, owned monotonic revision, hooks on the real settings/eligibility writers |
| `wco_monotonic_ms` | ROM symbol `os_sys_time_get` Thumb `0x13163`, patch slot `0x201580` | Actual selected implementation, units, atomicity, wrap, reset/DLPS behavior and common timestamp domain |

Code offsets are stock file offsets; RAM/ROM addresses are identified above.
The 880-byte owner embeds previously counted state: accepted total planning
is 1244 bytes, not 1244 + 880. The generated low16 experiment would reduce it
to 1180, but is not adopted or an owned allocation.

`wco_bound_stock.buffer/status` must hold the pointer **values**, not the
addresses of their slots. `wop_retire` rechecks the live slots. A const flash
binding is only valid if pointee addresses are proved fixed; runtime-assigned
objects require an explicit publication/lifetime design. Do not cast away
const to make the current declaration work. Raw settings bits cannot substitute
for a revision: change-and-change-back must invalidate stale preparation.
See [settings writers](UNIFIED_SETTINGS_WRITERS.md) for the 18 direct stores
and additional bulk/default/clock/eligibility paths requiring coverage.

## Clock shortcut rejected

The exact 36-byte stock clock leaf at file `0x1ad0` has SHA-256
`02c9cb5572ba288d6fa28fc4ee165a63cdbabb2038f69dd11964519b9737ac6a`.
Decoded instructions read `0x40000130`, multiply by 1000 in **32 bits**, then
divide by 32000 or 32768 according to byte `0x2001ec`.

For hypothetical consecutive input counts 4294967 and 4294968, the 32768
divisor produces 131071 then 0. This is not the uint32 millisecond wrap that
the runtime handles. It is an arithmetic counterexample, **not a measured
hardware clock failure**. Directly binding Thumb `0x827a81` is unjustified.
The symbol-named ROM time getter and its patch selection have not yet been
qualified by saved implementation evidence. No MMIO read was performed.

## WeChat slot replacement is a separate integration

Claude's [verified GATT results](UNIFIED_GATT_RESOURCES.md) and the user's
explicit WeChat-only retirement decision allow designing around five services,
not adding a sixth. UART, DFU, DIS and HID remain. Removing this BLE service
does not authorize removal of the Health step/sleep algorithms or history.

Stock setup calls FEE7 registration at `0x76de`, then stores its return at
RAM `0x209e1e`. **Correction from exact literal review:** shared callback
`0x6f28` instead compares incoming IDs with `0x209df7`, then `0x209df8` on its
fallback branch. These are different addresses; their relationship is not yet
proved. Returning `0xff` into the setup slot alone therefore does **not** prove
the shared callback route disabled. The candidate must keep the unified ID in
separate owned storage, publish it only after checked success, and leave full
shared-callback routing/reference closure explicitly unresolved.

The unified database is already 240 bytes; the old FEE7 table is 252. Replacing
one with the other leaves only 12 table bytes after accounting for the new
table, not 252 extra free bytes plus an uncharged new table. Callback/code
retirement, literal/reference closure and placement remain separate proofs.
Claude subsequently reported its requested FEE7 retirement-closure analysis
halted, with no deliverable. That analysis is **not pending evidence we can
count on**; complete FEE7 reference closure remains open. Its completed GATT
capture is a separate verified result.
At the user's subsequent request, Codex directly completed a
[bounded stock-reference survey](UNIFIED_WECHAT_RETIREMENT.md) and compiled
the unattached slot adapter. This adds concrete references/hazards, not full
indirect-reference or reclamation closure.
Registration success in an emulator does not establish real pool allocation,
callback ownership, send completion, service discovery or safe admission.

The subsequent unattached `wge_common` gate suppresses only the published
unified ID, forwarding every other event opaquely to stock. Both known callback
literal roots (`0x7788` and `0x77ac`) are exercised in the emulator; patching
only one demonstrably leaves the other unguarded. This narrows the known-root
routing gap, not retained/direct/computed-pointer closure. Dedicated callbacks
still must fail closed before ID publication and never fall through. The gate
does not supply those callbacks or a unified completion handler. Two mandatory
strong symbols, `wgs_service_id` and `wgs_callbacks`, remain missing in addition
to the three owner symbols above. Separate exact-stock advertising slices now
remove the FEE7 service-list entry without changing manufacturer bytes; full
startup, actual discovery and attachment remain unqualified.

The subsequent actual six-argument discovery read is now implemented and
separately ARM-tested. It adds the sixth required strong binding,
`wdr_identity[20]`: real boot initialization before service-ID publication,
followed by immutability for the complete borrowed-read lifetime. Its mutable
declaration permits initialization, not post-publication mutation. This is the
already-budgeted identity20, not another allocation. Write/CCCD callbacks,
callback-table attachment and physical lifetime are still missing. The new
selected startup witness composes slot/gate/advertising in one persistent ARM
context, but does not establish the actual full boot sequence or discovery.

The subsequent [107-test ingress supplement](UNIFIED_CONTROL_INGRESS.md)
demonstrates why resolving the current generation inside a write callback is
not that missing binding: old frames can be relabeled and start software Gesture
entry after ID reuse. Original provenance or the real upstream drain barrier is
required; no fixture provider was added to the production table. The compatible
seventh write argument is a post-process output, not context, and its validity
is not established by stock callbacks that never read it. No new dereference
or C/Swift wire-format migration was introduced.

The [six release gates](UNIFIED_READINESS.md) remain the finite approval list.
Resolving three link symbols alone would not establish fit, optical shutdown,
fresh motion, step/sleep continuity or usable recovery.
