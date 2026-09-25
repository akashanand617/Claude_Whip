# Completed create-hook/header-comparator diagnostic

2026-09-23 session. The user explicitly requested a new connection after the
prior attempt aborted. One fixed `--timer-create-hook` run completed all **359
matching CD01 transactions** and verified disconnect. No automatic retry or
follow-up address read occurred. The older failed attempt remains separately
archived in `../rom-create-hook-aborted/`; its missing subtype is still unknown.

Original: `data/rom-create-hook-20260923-idle-v2/`. The two archived artifacts are
byte-identical, pinned in `SHA256SUMS`. First request to last accepted reply:
**49.152349375 seconds**, excluding connection/DIS and disconnect.

All 279 known prerequisites passed before new memory was requested. The fixed
52-byte non-secret ROM-patch prefix matched twice and passed its conservative
containment check before either code cap. Both caps matched twice, followed by
state/header/config/idle postchecks and verified disconnect. No unexpected
notification occurred and no filter was bypassed.

| Fixed new window, end exclusive | Bytes | SHA-256 |
|---|---:|---|
| `0x803000..0x803034` header prefix | 52 | `1bb91c27a358ab3307730f7dff38e0adc1da0ac3c13bff574ab855462811a586` |
| `0x205c00..0x205d00` RAM code cap | 256 | `0f0e067c26d2ffc73ab8570f7f0a4a98a18c5ce2a98ef6eabe5877c04cb76d92` |
| `0x8e24..0x8ea4` ROM code cap | 128 | `b43b9de4927e9913a1c452092d8a08dd9c6d66d7cab05ed608a419efac6e57e3` |

The prefix declares IC 12, image ID `0x2792`, flags `0x916`, payload `0x9528`,
RAM start `0x203800`, load source `0x1809404`, load length `0x3510`, image base
`0x1803000`. Its declared RAM end is `0x206d10`. These are declarations, not
runtime-copy, authenticity, full RAM ownership, flash geometry or recovery proof.
The key field at offset `0x34` and returned load-source pointer were not read.
Known state remained inhibit=0, rate configuration=100 and hooks=(0x205c01,0,0)
at the reviewed repeated checks; this is not an atomic or immutable snapshot.

Initial off-ring disassembly identifies the create hook's selected body at
`0x205c00..0x205c30`, followed by its literal `0x200364`. It calls the captured
ROM default `0x13f9e`, stores a result byte, and conditionally calls **unread
`0x111a6`** on a failure/empty-handle branch before reporting the hook handled
the call. This additional path must not be replaced by an assumed successful
fallback. The pinned symbol text names the unread target `vTimerCreateFailedHook`;
that name does not establish its implementation. Adjacent functions in the
256-byte cap are not approved execution.
The comparator's selected body `0x8e24..0x8e46` performs byte equality; other
routines in the 128-byte cap are not part of that body. These are disassembly
findings at capture time; later bounded execution is recorded below. Neither
disassembly nor those tests establishes physical create/resume/recovery.

Before connection all **224** status-metadata-build hashes matched and **226
selected preflight tests passed in 3.22 seconds**. No diagnostic behavior or
firmware C changed during the run. Only fixed CD01 requests were sent: no sensor
start/stop, settings/clock, DFU/reset, key/MMIO/FIFO access, target execution,
pointer-following or flash. CD's existing bookkeeping side effects remain.

This session ended. Further device work needs new bounded coordination. All
construction/physical/recovery gates remain closed; no installable unified image
or health/steps/sleep continuity result follows from this code acquisition.

Subsequent guarded off-ring capture/replay build (2026-09-24):
`build-20260924-create-hook-capture-v1/`, **2492 passed in 153.48 seconds**, zero
skips/failures/errors; all **227 hashes** verified (157 inputs, 67 artifacts,
three reports). This includes exact request/reply/order/checksum/header/flag
replay. Both ARM ELFs are unchanged; captured-body execution is next work.
Manifest SHA-256:
`b3123dce765d24bc3fdf2a33f02a6aeb52c06a7f2ca143e355b39ed3a8c2a0b7`.

## Later off-ring execution — 2026-09-24

`build-20260924-create-hook-execution-v1/` passes **2613 tests in 145.13 seconds**,
zero skips/failures/errors/xfails; all **228 hashes** checked (158 inputs,
67 artifacts, three reports). Both ARM ELFs are unchanged. Manifest SHA-256:
`fb3d50e081a34bc82ca3541298a5b5b90683e3626469f8440489e6001469fed4`.

121 new cases execute the actual selected hook/default/native-create success
path and header comparator. Failure with an empty handle reaches unread
`0x111a6`; null output reaches an unadmitted zero-address read; wrapped large
periods consume allocation before asserting. Synthetic pool/list/critical
boundaries remain. Exact stock/original25Hz/V2 prefixes and this patch prefix
are tested through the real selected field checker, not payload authentication
or boot/recovery. See [the full audit](../../../../docs/UNIFIED_CREATE_HOOK_READ.md#captured-body-execution--2026-09-24).
No new ring session, raw evidence change, C binding or flash approval occurred.
