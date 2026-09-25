# Compiled switching with conditional retirement in one ARM context

2026-09-24/25. Entirely off-ring, **unowned and not installable**. Health remains
the unified boot/default and Gesture temporary/opt-in. This experiment changes
no production source, stock file, container, installed firmware or app.

`tests/test_retired_stock_switch.py` joins the previously separate
[compiled coordinator](UNIFIED_COORDINATOR.md) and
[known-root retirement](UNIFIED_STOCK_RETIREMENT.md) experiments. One persistent
Unicorn address space contains exact stock, all segments of the pinned
21-object/130-function conditional ELF, and its sixteen retirement edits.
The two previously reviewed optical sample-reader BL replacements are also
applied only in emulator memory. There are **18 four-byte instruction edits**,
including the early UART BL; these 72 bytes do not include relocated sections.

The final focused development run passed **16 tests in 12.55 seconds**, with
zero failures or skips. The earlier 15-case run passed before adding the
retirement-mask mutant and strengthening stale-work assertions. These counts
are separate from the archived full checkpoint and any root-run supplement.

The subsequent [guarded supplement](UNIFIED_DISCOVERY.md) independently reran
these 16 cases alongside 19 discovery and 28 budget cases: **63 passed in
40.88 s**, all identities/phases checked. This switch still uses the pinned
21-object ELF below, not the separate new 22-object discovery layout.

The ELF is
`firmware/unified/research-20260924-raw-retirement-v1/UNOWNED-raw-relocation-NOT-INSTALLABLE.elf`,
SHA-256 `9cad661e85edd74ebc9f425956aa1937da0dfa9f2f5344ddf20cf9d61109d432`.
The existing retirement planner rechecks its exact whole-artifact pin, stock,
descriptor, source/object provenance, layout and finite ingress-policy witness.
The production verifier still rejects this layout. Its **9132 append bytes,
388 remaining and 1894 moved bytes in unowned regions** are unchanged; no new
capacity or ownership is established by running the linked functions.

## What executes together

The positive case runs this sequence without replacing the ARM instance or
resetting its adapter/coordinator state:

1. Boot into software Health; create an original job ticket, execute the real
   stock optical sample reader through checked I/O, and exercise guarded HR
   stores with an explicitly invented algorithm/provenance receipt.
2. Receive both Gesture wire fragments. The first leaves Health unchanged.
   Complete command admission starts quiescence; no success reply is available.
3. Supply named producer-drain and IRQ/hub/RUN/publication-fence fixtures.
   Actual `wc_pump` executes checked stock RESET/STOP writes. They alone cannot
   advance the mode. A separate physical-STOP fixture lets
   `wc_optics_stopped` retire actual software buffers with the original pause
   identity; retirement writes remain checked under the interrupt mask.
4. Pass HOLD through `wc_physical_done`, then admit the first synthetic source
   receipt through actual source validation. Only now does Gesture succeed.
   Both reply fragments and one packed motion notification execute
   `wg_stock_notify20` and the original stock notification wrapper. ROM
   submission status is still a fixture, not radio delivery or buffer lifetime.
5. Receive both Health wire fragments; run STOP and RELEASE through the C
   coordinator with explicit drain/preservation receipts. Change current stock
   controls and the simulated monotonic settings revision. Require
   `WC_WAIT_RESUME` before creating the fresh-preparation fixture. No Health
   success reply is available yet.
6. Run `wc_resume_prepared` and atomic `wsc_commit_health`, then execute both
   Health reply fragments through the original wrapper. Reject the old optical
   ticket and old Gesture source receipt; create a new ticket and run another
   original optical sample read after explicit fresh-acquisition setup.

At **nine phases**—Health, quiescence, retired/HOLD, START pending, Gesture,
STOP pending, RELEASE pending, preparation pending and restored Health—the
original stock FIFO drain and Health consumer receive another selected sample.
Their delivered inputs are compared with an untouched-stock runner. Every
phase also executes a seeded two-command legacy A1 queue across index 9→0,
then invokes original stored raw/indicator callback pointers. They hit their
entry stubs without changing raw state, bus operations, messages, timers,
notifications or pending FIFO samples. Existing raw timer handles deliberately
remain: stub execution does **not** certify cancellation or callback draining.

Each phase additionally executes the original UART callback and pinned early
filter for A1/BF/CE/CD. None reaches the recorded legacy dispatcher boundary
or changes stock data. The ordinary stock optical motion helper, retained
shared `cc32` reader and FIFO wrap path also run in this same persistent
context after restoration; selected scaled arrays and subsequent Health
consumer inputs match the separate exact-stock reference.

The software Health→Gesture→Health orchestration comes from compiled C.
The test runner supplies external events, fixture receipts and selected input
bytes; it does not substitute Python transitions for coordinator operations.
The separately compiled ABI witness checks the source-defined adapter offsets
and coordinator/receipt sizes; that artificial proof ELF is never loaded into
the persistent conditional-layout context.

## Failure and oracle coverage

The focused suite also exercises mutex-take, RESET, STOP, mutex-release,
physical-STOP and software-retirement failures; stale receipts after disconnect,
charging or timeout; settings revision changes and change-and-change-back;
unversioned control changes; and default Health with unknown inventory.
Failures cannot report Gesture or restored optical Health, cannot silently
retry the one-shot STOP, and do not revive retired queued/stored roots.

The loader does not broaden the append-only or artificial loaders. Transitions
from outside candidate code are admitted only by a named top-level function
call, one of the three exact stock→C BLs, or an observed actual C BL/BLX return
continuation; C→C execution remains the flow of the exact pinned code. An old
stock entry into an address now occupied by relocated C fails closed. All
original-stock execution continues to use the existing bounded path oracles;
additional queued/UART/optical-helper ranges are explicit. RAM accesses are
restricted to original stock data, named fixture objects and bounded stack.
The full stock image is compared with an expected image assembled independently
from pinned ELF segment bytes and the admitted edits; stock outside those
intervals must remain byte-identical. Each loaded segment, including appended
bytes beyond the stock image, is also compared directly with its pinned ELF
bytes before instruction edits.

Negative witnesses reject old interior entries and a stub that writes to mapped
but unadmitted RAM. Restoring the old UART BL visibly reopens A1 dispatch and
fails the independent no-dispatch expectation. Removing the retirement mask
is detected by the inherited actual-stock write oracle. These deliberate
mutations occur only after constructing the pinned emulator; they are not
accepted artifacts or changes to the planner's hash policy.

## What remains external

The following are still named fixtures: original producer inventory and drain;
serialized task ownership; IRQ/hub/RUN/publication and transport fences;
I2C/peripheral/mutex behavior; physical optical shutdown; accelerometer hold,
preservation and release; acquisition completion/overflow/timestamps; algorithm
values and optical provenance; ROM notification acceptance; monotonic settings
revision ownership; and fresh scheduler/acquisition preparation. The generous
emulator state/stack addresses do not allocate or establish available ring RAM.

Matching the selected Health-consumer inputs does not execute downstream
step/sleep algorithms or prove history continuity. Entry stubs still assume
fresh admission: there are no suspended old callback interiors or retained
return frames. Computed/ROM/patch roots, all producer closure, actual default
Health behavior, service registration, app identity migration, physical mode
switching, RAM/retention/stack ownership and usable recovery remain unresolved.
The dedicated service database is present in the pinned ELF but is not
registered by this test. No physical source or final-model evidence is added.

This is a focused integration supplement, not a rerun of the earlier
**3251-test** checkpoint or an installable firmware. All six
[release gates](UNIFIED_READINESS.md) remain open; approved reclaimed bytes
remain zero.
