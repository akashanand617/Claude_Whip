# Rejected source-size experiments — never install

No accepted code, firmware image, device state or release gate changed.
This is a compile/size archive, **not a behavioral-test checkpoint**.

Pinned ARMv6-M `clang -Oz` double compilation reproduced objects and local
stack reports for the baseline and five candidates. Whole-module text plus
input unwind was1060 bytes for baseline, then1100,1096,1070,1060,1100.
All candidates were rejected. Private helper extraction reduced caller size
but increased total input size and the known static nested stack chain.

`measurements.json` SHA-256:
`9906db7c9aefbd6c6e84ca9f052b9b6ebd47ede7c11f820846c236f0d5f0d421`.
It includes source/tool/artifact hashes, exact flags, section sizes, function
sizes and local stack. `*.command.json` records every compiler invocation.
No ELF was linked; no source candidate received differential acceptance.
The report explicitly records the headroom candidate's invalid-zero-period
caveat. Code retains no approved RAM or reclaimed flash allocation.

To reproduce into a **new** directory:

```sh
/tmp/whip-unified-build.m1E9lk/proof-env/bin/python \
  firmware/unified/experiments/measure_source_size.py \
  --preflight firmware/unified/research-20260925-source-size-rejected-v1/sources/preflight.c \
  --frames firmware/unified/research-20260925-source-size-rejected-v1/sources/frames.c \
  --output /tmp/whip-source-size-new-output
```

Object hashes incorporate source filenames; the report requires byte-exact
repetition within each run, not identical objects across different source
paths. Accepted source/pins remain unchanged. Whole28 append lower bound is
still10798/9520 (1278 over), before callback12, final alignment/unwind and
missing hardware bindings. All six release gates remain open.

Independent read-only review rechecked34 inputs,42 artifacts and two tools;
all six object/stack-report pairs,12 compiler logs and ELF section/function
inventories agree. Baseline executable sections and relocations match the
accepted pinned object; only source-filename metadata differs. The preceding
178-test discovery checkpoint's1130 content hashes and four tools remain intact.
Provenance limitation: this diagnostic records the command log before taking
object snapshots; it is not the stricter immediate-output sequence required
for acceptance builds. No behavioral or firmware acceptance depends on it.
