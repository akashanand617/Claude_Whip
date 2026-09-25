# Task stacks and interrupt stack: installed V2 ring, read-only, 3 stages

2026-09-25. The user confirmed all other clients were closed and pre-approved
up to three short stack sessions. Codex stayed off-ring. No flash, sensor
command, write, execution or in-session pointer following. Each stage's
addresses were chosen offline from the previous stage's archive.

| Stage | Directory | Transactions | What it read |
|---|---|---:|---|
| 1 | `../ram-ownership-stacks/` | 198/198 | `pxCurrentTCB`, 256 B of ROM kernel lists (`pTaskHandleList`...), MSP paint **hash-only** |
| 2 | `../ram-ownership-tcbs/` | 194/194 | Task-handle table `0x2117a0` and six TCB headers (72 B), raw |
| 3 | this directory | 454/454 | Stack bottoms from each `pxStack` upward, **hash-only** (only a painted/not-painted profile is kept) |

All three stages ended in a verified disconnect on the first attempt.

**Qualification (Codex independent review, `docs/UNIFIED_STACK_EVIDENCE.md`):** intact `0xa5` paint is *observed untouched fill*. It is not a strict bound on maximum SP depth, because reserved but unwritten frame space leaves paint intact, and it is not a guarantee of future headroom. The workload is V2 with optics off. Stack sizes assume uncaptured 8-byte heap headers. The TCB reads are not one atomic snapshot, the 7th TCB is unread, and the 56 non-zero kernel-window words are list fields, not 56 handles. No task binding is approved.

## Interrupt (main) stack

The ROM reset handler paints `0x203200..0x203380` with `0xa5a5a5a5`
(`0x4f12..0x4f24`, captured ROM). All 96 words were still intact, so **MSP
paint untouched since the last reset: no write landed in the lowest 384 of 1536 bytes**
(observed paint, not a strict SP-depth bound).

## Tasks (7 in the ROM handle table; one TCB, `0x211740`, not read)

| Task | Prio | pxStack | Stack | Untouched bottom paint (not guaranteed headroom) |
|---|---:|---|---:|---|
| app | 2 | `0x213360` | 1024 | **192 B** |
| Tmr Svc | 6 | `0x2157b8` | 1024 | **504 B** |
| hub | 2 | `0x2148e8` | 2560 | ≥ 1024 B (whole read painted) |
| qc_app | 1 | `0x213928` | 3584 | ≥ 1024 B |
| IDLE | 0 | `0x215350` | 1024 | ≥ 256 B |
| UpperStac(k) | 5 | `0x2120a8` | 3072 | ≥ 512 B |

The stack sizes of app/qc_app/hub equal stock's three `os_task_create` sizes
(1024/3584/2560). Each stack sits directly below its TCB, with an 8-byte heap
header between them. TCB layout: `pxStack` at +48, name at +52.

## Bounds

- **V2 has optics off.** `hub` (sensor hub) and the others may use more stack
  under stock Health. These are V2 lifetime high-water marks since the last
  reset, not stock-Health maxima.
- The painted-bottom method assumes FreeRTOS's `0xa5` fill and no foreign
  writer. Painted words exist in every stack, which supports the fill.
- Raw stack contents were never stored or logged: per-16-byte hashes and a
  painted-word count only.
