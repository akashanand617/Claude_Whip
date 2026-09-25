# RAM owner prototype: offline measurement, not a source or builder input

2026-09-24. Unowned, **not installable**, not referenced by any builder or
test manifest. No allocation is approved; this is **not** an owned
allocation. Context: [docs/UNIFIED_RAM_OWNERSHIP.md](../../../../docs/UNIFIED_RAM_OWNERSHIP.md).

## What it measures

`unified_state.c` gathers the current persistent unified state and the
input receipt into one static object. It puts that object in a `NOLOAD`
section at the **unapproved** candidate `0x20e738..0x20ec00` (1224 bytes:
post-boot BootOnce overlay RAM plus the nominal gap).

| Member | Bytes |
|---|---:|
| `wd_dispatch` | 764 |
| output frame | 20 |
| `wf_timer_fence` | 12 |
| `wc_owner` (coordinator) | 28 |
| `wc_stop_receipt` (asynchronous STOP observer) | 28 |
| `wc_resume_receipt` (contains the 16-byte `wsc_prepared`; synchronous, could live on the stack) | 20 |
| settings revision owner | 4 |
| `ws_receipt` | 288 |
| **`uw_state`** (all 4-byte aligned, no internal padding) | **1164** (`0x48c`) |

Region placement: start `0x20e738` (8-aligned), end `0x20ebc4`, **60 bytes
spare** to `0x20ec00`. Coordinator types come from Codex's
`stock_coordinator.h`, read-only, at its coordinator-v1 freeze. An earlier
revision without the coordinator measured 1104 bytes.

The RAM program header has **filesz 0**, so the section adds no image bytes. The owner `uw_state_claim` (explicit clear + address)
adds **24 flash bytes**: 16 code + 8 literal, no new unwind entry.

## Linker variants

- `strict_assert.ld`: `stock_append.ld` plus the state section. **Refused**
  ("configured APP bound exceeded"). lld evaluates that ASSERT against the
  pre-merge `.ARM.exidx` during initial address assignment.
- `region_only.ld`: the same, minus only that ASSERT. The `MEMORY` region
  still bounds the final layout exactly. **Links**, with the unwind table
  ending at `0x849fe4` (28 bytes under `0x84a000`). This exists only to
  measure; no production relaxation is proposed or approved.

## Reproduce

```sh
PATH=/Library/Developer/CommandLineTools/usr/bin:$PATH \
  firmware/research/2026-09-24/ram-owner-prototype/reproduce.sh /path/to/zig-0.15.2
```

It links the **pinned** checkpoint objects from
`firmware/unified/build-20260924-layout-candidates-v1/stock-address/`
(manifest `ad5ad870…6cc36512`), not live sources, which are changing. It
compiles only `unified_state.c`, against current headers, and refuses if the
state layout drifts from `0x48c`. It writes nothing in-tree. Same
clang/zig as the checkpoint (`b8763cf2…` / `c65cd349…`).

## Explicitly excluded, still unproved

- Ownership of `0x20e734..0x20ec00`: ROM, ROM-patch and upper-stack writers,
  the heap base, dynamic-index stock writes.
- Boot lifetime: `app_pre_main` must run once per reset; a re-run would
  execute this RAM as overlay code. Per-boot clear order must follow stock
  Health init.
- DLPS/power-down retention of this range.
- Stack: `wa_observe`'s 244 observed nested bytes, the 64-byte delivery
  scratch, the outer caller and exception frames stay on the serialized
  task's stack, whose headroom is unmeasured.
- Heap: none used; heap reserve is untouched but unmeasured.
- The boot hook that calls the owner, and its flash cost.
- Concurrency: a single writer in the proven serialization domain; the
  receipt must not alias delivery scratch.

## Hashes (SHA-256)

| File | SHA-256 |
|---|---|
| `unified_state.c` | `dcdfa5d23e07754521e51ba2ef19f458f64c96aca8a8d898ec4365d0789c8cc4` |
| `strict_assert.ld` | `4d478367b4e69b2ad5e73a6ce119bcb8eee968e1083ea1c0d6032a3d082f0e54` |
| `region_only.ld` | `43786ce15a625d0bd093f6571d419a10843a46da124ff7c857d6bc942116d66a` |
| `reproduce.sh` | `2ca1e1d1796f7fed55e567765d77c29721454ff7e28a800cc56ebfc1a5634569` |
