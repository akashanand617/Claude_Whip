# Firmware research evidence archive — 2026-09-22

Start with the corrected synthesis in
[FIRMWARE_RESEARCH.md](../../../docs/FIRMWARE_RESEARCH.md), then the chronology
in [LED_FIX.md](../../../docs/LED_FIX.md). This archive preserves the underlying
evidence so continuing the investigation does not depend on chat context or a
temporary directory. None of its contents authorizes a flash.

## Contents

| File | Purpose and caveat |
|---|---|
| `fable-findings-draft.md` | Exact saved Fable draft; **contains superseded conclusions**, retained as a source record |
| `fable-workflow-results.json` | All ten completed structured results, with agent IDs and original journal keys; nine verifiers plus final critic |
| `captures/check_*.jsonl` | Byte-identical copies of all six hardware experiments, originally in git-ignored `data/ledcheck/` |
| `captures/battery_*.jsonl` | Byte-identical host-workaround battery captures, including the two later 30-minute runs (100→100 gauge plateau, then 100→95); see `docs/BATTERY_TESTS.md` |
| `captures/firmware_validation_*.jsonl` | Pre/post-flash fixed-site identities and both native V2 stream/stop validations; LED darkness remains a human observation |
| `v2-patch-manifest.json` | Exact base/candidate hashes, seven old/new edit ranges, runtime addresses and 22 fixed code reads |
| `fwmap.py` | Fable's annotated Thumb mapping tool, with only the default image path made repository-relative |
| `rom_symbol_gcc.axf` | Text ROM-symbol assignments used to identify the RTL8762E platform |
| `loadbase.py` | Original load-base/prologue scanning script |
| `abs-original.py` | Original diagnostic script, preserved **without fixing its hard-coded path or Thumb-symbol lookup bug** |
| `SHA256SUMS` | Integrity manifest for saved evidence and referenced firmware; run from repository root |

The original captured device identifier and timestamps remain in these files.
This is local research data. No full conversation, hidden reasoning, account
secrets or unrelated assistant memory export was copied.

## Source provenance

Fable main session:

```text
/Users/akashanand/.claude/projects/-Users-akashanand-Claude-Whip/
  fce5503d-9fbc-4aa8-93c0-bd04600def2d.jsonl
```

Workflow journal relative to that project directory:

```text
fce5503d-9fbc-4aa8-93c0-bd04600def2d/subagents/workflows/
  wf_e507bed5-541/journal.jsonl
```

Only entries with `type == "result"` were extracted; their `agentId`, `key`
and `result` values are retained. The original result entries do not have
timestamps. Eleven starts and ten results were present (duplicate work was
started); do not claim eleven completed reviews. The main transcript's final
visible message was a usage-limit notice at `2026-09-22T10:24:33.798Z`.
The final critic's `overall` value is `proceed_with_changes`, not flash approval.

Scratch source directory:

```text
/private/tmp/claude-501/-Users-akashanand-Claude-Whip/
  fce5503d-9fbc-4aa8-93c0-bd04600def2d/scratchpad/
```

Hashes of original scratch text files before archival adaptation:

```text
8c02c7ba1a7a890b8b985ba58ac055195733377d9934f66f8d19c7e442a81558  FINDINGS.md
478d7a457348b0a481212dcd99887fcd3ae852e8b22821210a21d0e4bde070d1  fwmap.py
6f5a59f6444c01328808ac148b9c60771410196ab3b57e08fc8ff90525934247  rom_symbol_gcc.axf
ee130fbdb49fc369b39be0eabff3f1db94615e642672fb2e1c9cbb7844495042  loadbase.py
d3c8551f2ecc680aaac93b175e560458082764fcf8a661a944271eff5d930604  abs.py
```

`FINDINGS.md` was renamed `fable-findings-draft.md`, and `abs.py` was renamed
`abs-original.py`. The archived `fwmap.py` adds `pathlib.Path` and replaces
the absolute default image path with a path relative to `firmware/`. Its current
hash therefore differs from the original above. All other copied scratch files
are unchanged. Generated listings are reproducible and are not duplicated here.

The symbol table was originally downloaded by Fable from
[ATC_RTL_BLE_OEPL's RTL8762ESL SDK tree](https://github.com/atc1441/ATC_RTL_BLE_OEPL/blob/main/ATC_RTL_BLE_OEPL_8762ESL/sdk/lib/rom_symbol_gcc.axf).
That origin was recovered from Fable's visible download command; no new download
was needed. It is third-party SDK material, not a claim that the vendor firmware
or table is covered by this repository's code license. Preserve provenance and
review upstream terms before redistribution. Firmware-image origins and rights
are recorded in [PROVENANCE.md](../../PROVENANCE.md).

## Review index

| Agent ID | Review topic |
|---|---|
| `a4e53d4e291c570bd` | A1 dispatch / optical message payload routing |
| `af5044060830be0d3` | Independent A1 command dispatch and charging cases |
| `a9d808ade64e90a00` | Single-halfword patch encoding, artifact drift and mask semantics |
| `a09f0aa7d19422b6d` | Optical stop semantics and startup/indicator interactions |
| `ad4aea7cc33b75bca` | Optical enable/start path and bypasses |
| `a67b9b5572f2fb977` | Raw-bit exclusivity and other health owners |
| `a7c6ba7c6a29efc1c` | Accelerometer independence, idle state and cached samples |
| `a00de44b1fc14fe8c` | VC30F modes, slot configuration and LED-current alternative |
| `acb2fed7de9fc6051` | Power, deep-sleep veto and RAM layout |
| `a5017e9fe202cd0b7` | Final critic and required changes |

These primarily reviewed the one-halfword candidate, not the current v2 image.
The critic separately decoded v1. V2 has its own local code/tests/review record;
do not transfer a verdict between hashes. Some verifier evidence repeats an
earlier assumption that another reviewer corrected.

Especially important corrections to the preserved draft:

- `69 01 04` starts HR; the disabling command is `69 06 04`.
- A1 `05` is the matching stop for `04`; `02` clears a different optical bit.
- HR logging-disable is not a master switch for all five schedules.
- `0x80/0x20` optical bits are not established as the wear-detection labels
  used in the draft; use the corrected SpO2/schedule mapping in the synthesis.
- Existing mask bit `0x40` causes new enables to be dropped, not ORed.
- Posted constants `0x332`, `0x18D`, `0x195` are not the claimed routing IDs.
- The second reset-copy block is initialized data, not RAM-resident code.
- Mode-7 AGC raising zeroed slot currents was not established; the alternative
  remains incomplete for other reasons.
- Accelerometer independence from optics does not mean it stays fresh while idle.
- Retained raw mode after disconnect can prevent deep sleep and keep its timer
  firing, even if the STK is allowed to idle.
- Passing tests or preserving DFU bytes does not guarantee hardware recovery.

## Using the mapping tools without touching the ring

Run from repository root with the existing environment (Capstone is required):

```sh
.venv/bin/python firmware/research/2026-09-22/fwmap.py func 0x20bc 0x50dc
.venv/bin/python firmware/research/2026-09-22/fwmap.py xref 0xf68c
.venv/bin/python firmware/research/2026-09-22/fwmap.py calls os_timer_create
```

These commands read the pinned base only. Function bounds and pointer labels
are heuristic; always verify decisive bytes and call flow. `func`/`xref` do
**not** read a previously generated candidate listing: their default is always
the base image. To inspect a different image, instantiate `Image(path)` in a
small analysis script or use the builder tests; do not confuse the two.

Optional generated listings (writes only the ignored local `fw/` subdirectory):

```sh
.venv/bin/python firmware/research/2026-09-22/fwmap.py build
.venv/bin/python firmware/research/2026-09-22/loadbase.py firmware/rt02cr-25hz.bin
```

The `loadbase.py` scan is heuristic and may take time. `abs-original.py` is
historical source, not the recommended command: its original scratch path
will eventually disappear, and its even-target symbol lookup undercounts ROM
matches. Applying the Thumb bit reproduces **79/79** matches.

Verify integrity from repository root:

```sh
shasum -a 256 -c firmware/research/2026-09-22/SHA256SUMS
```

The archive manifest is a snapshot of evidence and exact image bytes, not a
deployment allowlist. The live flashing catalogue is `firmware/SHA256SUMS`.
No commit, push, cloud backup, BLE action or flash was performed to create this
archive. The saved files must be included in a separately chosen backup/version
control workflow if off-machine durability is desired.
