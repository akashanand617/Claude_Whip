# Fresh 25/s acquisition — offline evidence and source contract

Status: 2026-09-23. The source validator/selector is implemented and tested;
**a qualified physical source is not available**. No ring connection, register
write, BLE command, image build or flash was performed for this work. This
document does not authorize those operations. Start with
[UNIFIED_WORKFLOW.md](UNIFIED_WORKFLOW.md),
[UNIFIED_STOCK_MOTION.md](UNIFIED_STOCK_MOTION.md) and
[UNIFIED_HEALTH_LIFECYCLE.md](UNIFIED_HEALTH_LIFECYCLE.md).

Later [memory-budget continuation](UNIFIED_RESOURCE_BUDGET.md): exclusively
caller-owned output scratch reduced the selector's ARM local frame from 344 to
184 bytes. The 2026-09-24 source revision reduces it again to **112 bytes** by
copying only transactional progress. Exact checked byte ages relative to final
status time reduce the receipt **480→288 bytes**, retaining all 32 frames and
both endpoints without rounding. `ws_set_bounds` rejects before narrowing;
direct raw ages remain checked at observation. Integrated observation now uses
**388 observed nested stack bytes**, excluding input receipt and outer callers.
Every rejected batch clears output and leaves progress uncommitted; prior-ARM
equivalence and exhaustive representation checks are in the linked handoff.
No physical profile, owned RAM or complete task stack was qualified.

## What the exact images establish

All addresses below are file offsets; application addresses add `0x825fb0`.

| Image | SHA-256 |
|---|---|
| Stock 3.12.02, 138016 bytes | `b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0` |
| Historical 25 Hz, 137540 bytes | `f13e63d3fdef3b10aa20fd4e0672077b66f60bb19c689ef64053840e4d35d3d9` |
| Historical V2, 137540 bytes | `0d18a0fa860d58ab8f984b5f542f45dac105241f47bf1c2af41321eb0431e14c` |

| Operation | Stock | 25 Hz / V2 | Acquisition consequence |
|---|---|---|---|
| Active configuration | `0xbf34` | `0xbedc` | The complete 28-byte function is identical across the images: writes `11=74`, `10=0f`, `3e=c8`. |
| STK initialization | `0xbf50` | `0xbef8` | The complete 80-byte function is identical: reset, range `0f=05`, undocumented `5e=c0`, `34=04`, interrupts and watermark `3d=20`, then active configuration. |
| Register/burst read wrapper | `0xbc6a` | `0xbc12` | Takes the shared mutex with argument 100; returns zero on mutex or bus failure, one on bus success. Mutex coverage is one transaction, not status + burst + publication. |
| FIFO drain | `0xc280` | `0xc228` | The STK-ID-23 branch reads count, drains up to 32 frames, and publishes to the Health ring. V2 leaves this entire inspected body unchanged. |
| Raw reader | `0xcc32` | `0xcbda` | Independently drains when active; otherwise repeats retained XYZ. Active return 20 is not a count or freshness receipt. |
| Wake | `0xcb5e` | `0xcb06` | Restarts a timer with argument 800, posts active request, and assigns the Health cursor to the current producer. Not a harmless source-start primitive. |
| Producer store / Health cursor | `0xc4e8`, RAM `0x20bdd2` | `0xc490`, RAM `0x20bdce` | New source must never advance/reset the Health cursor. |

The driver ring contains 82 frames. Producer equality can hide a complete lap;
it is not overflow evidence. Health consumes individual valid native frames,
not every third frame. Maintaining its input order alone is insufficient if a
new observer changes when drains, algorithm calls or idle/wake transitions occur.

### Failures currently hidden by the stock drain

For ID `0x23`, stock `0xc360` calls the status reader. At `0xc36c..0xc36e`
it masks the full status down to seven count bits, discarding overflow. It
clamps count to 32. At `0xc388` it clears the 192-byte burst destination;
`0xc39a` calls the FIFO reader, and `0xc39e` branches into copying without
checking its return. A failed burst can therefore publish zeros or a partly
filled batch. A producer increment is not evidence of successful acquisition.

The underlying path is `0xbc6a -> 0xdcce -> 0xdc40 -> 0x1371e`.
The last routine performs byte polling and writes the destination progressively;
abort/timeout can leave a partial buffer. `0xdc40` maps a nonzero transfer result
to error, and `0xbc6a` maps bus success to one. Capturing this previously ignored
result is necessary. Treating it as an exact byte-completion receipt additionally
requires the successful polling/control-flow and live timeout-state assumptions
to be validated; the stock API does not expose a transferred-byte count.
Repeated bus errors also reach recovery `0xdaf0`; they are not merely empty FIFO.

## Why the physical rate remains unresolved

The manufacturer’s preliminary v0.9.4 describes `3e=c8` as stream FIFO,
XYZ and every-fourth subsampling. Its low-power table gives a nominal 75 Hz
at 10 ms sleep/1 kHz bandwidth, while ESM timing has an additional condition.
It says FIFO reads clear overflow and partial-frame reads discard the partial
frame. Direct-data protection is per-axis, requires low-byte-first reading,
and reads clear new-data indications. However, the direct-output register
tables mark low bits reserved while the prose describes new-data flags;
the ESM equidistance formula is also problematic for this configuration.
The documented register map does not explain stock’s `5e=c0` write.
These are reasons to measure the actual implementation, not to silently correct
the document or infer 75/4 Hz. [Sensortek STK8321 preliminary datasheet,
pp. 11–12, 20–23 and 28](https://cdn.hackaday.io/files/1822057795458720/STK8321.pdf).

The saved evidence is internally useful but does not timestamp physical frames:

| Archived capture | Observation | What it cannot prove |
|---|---|---|
| `check_1790071705479474000.jsonl` | First phase: 208 packets, one distinct XYZ, about 25 packets/s. Status at 8.1895848 s is `0xa0`: overflow plus count 32. | Packet rate does not establish fresh acquisition. |
| Same capture, motion control enabled | Range/BW/power becomes `05 0f 74`; 60-second optical-stopped phase has 1509 packets, 1483 distinct XYZ. | Unique values do not establish the complete FIFO cadence or losslessness. |
| `check_1790072161023025000.jsonl` | 120-second optical-stopped phase: 3008 packets, 3007 distinct XYZ, about 25 packets/s. | Does not justify a nominal 75 Hz or 18.75 Hz FIFO source. |
| `firmware_validation_1790114546989490000.jsonl` | Historical V2 A104-only: 1450/1450 distinct XYZ, 24.998 packets/s. | Native V2 delivery still lacks acquisition timestamps and overflow receipts. |
| `firmware_validation_1790114992385243000.jsonl` | Second V2 run: 700 packets, 699 distinct XYZ. | No exact rate or all-axis coherence proof. |

These files and their hashes are preserved in
[the evidence archive](../firmware/research/2026-09-22/README.md). Existing
diagnostic register reads cover chip ID, XYZ, `0f..11`, status and interrupt
mapping, but do not read FIFO configuration `3e` or record every FIFO transaction.
Direct XYZ low-byte nibbles are nonzero, another reason not to substitute the
preliminary twelve-bit interpretation for the empirically validated signed-word
decode. Register reads and packets have host timestamps; neither provides the
oldest acquisition timestamp required by the runtime.

## Chosen offline adapter contract

[`fresh_source.h`](../firmware/unified/fresh_source.h) and
[`fresh_source.c`](../firmware/unified/fresh_source.c) observe immutable copies of
existing Health-owned FIFO transactions. They contain no I2C, timers, sensor
addresses, firmware hooks, allocations, stock pointers or Health-cursor writes.
They deliberately do not call the raw reader or wake helper. Direct-register
polling is not implemented: its additional bus traffic, indication clearing,
axis coherence and effects on active/sleep duration are unproved.

`ws_profile_valid` checks a profile’s numerical and identity consistency, not
its authenticity. A profile supplies measured minimum/maximum physical frame
periods, timestamp uncertainty, trace digest, measurement span/frame count,
binding identity, configuration epoch and exact active configuration bytes.
There is **no accepted physical profile** in this repository. Synthetic test
profiles are not a production allowlist. A real binding must independently
review and pin the complete measurement and configuration provenance, including
unrepresented relevant registers such as `5e`, IRQ/timer behavior and clock units.
Nonzero identifiers or a digest alone cannot attest a measurement.

Every receipt must carry:

- The original XYZ burst bytes; complete requested/transferred byte counts and
  transport result, including status-read success.
- The **unmasked** pre-burst FIFO status; the earliest status-snapshot time and
  completion time of the complete burst.
- Conservative earliest/latest **physical acquisition** bounds for every frame.
  They cannot be callback times, fabricated sequence timestamps or an assumed ODR.
- Matching session/configuration/binding identity and consecutive transaction
  IDs, including empty status observations. All physical drains must participate.

Without sensor phase, the selector conservatively reserves
`1 + floor((completion - status_time) / minimum_period)` arriving frames and
requires initial count plus that reservation to fit 32. It assumes no FIFO pop
relieves pressure before completion. Thus count 32 is rejected even with an
otherwise successful read: a cleared post-read overflow flag cannot prove there
was no overflow during the read. A less conservative bound would need reviewed
per-frame pop timing and sensor phase, not an unchecked Boolean.

Start consumes a boot-unique session and remains physically uncompleted until
the first valid delivery. The first frame must fall within start’s first
40 ms bucket. The source emits one original frame from each successive bucket;
it neither interpolates nor assumes a fixed decimation ratio. Identical values
can be valid stationary samples. Output is **25 fresh selections/s**, potentially
with measured within-bucket acquisition jitter, not an assertion that the sensor
converts at exact 40.000 ms intervals. It is not an anti-alias filter.

Ambiguous timestamp bounds crossing a bucket, a missing bucket, replay, unknown
configuration, transfer failure, insufficient FIFO headroom or acquisition age
of 250 ms closes the Gesture source. Empty/status-only receipts cannot renew
physical age. Output copying is atomic, and stale-session callbacks cannot alter
the current source. Timestamp wrap is supported within the serial-number
half-range; sessions/counters do not silently wrap into replayable identities.

The integrated adapter must keep START pending, then atomically complete START
and offer the first delivery to the runtime. Source validation never completes
Health cleanup or proves the physical hold itself. All source calls, hardware
receipts, Health publication and final send checks require a reviewed serialized
binding. Per-I2C mutex acquisition alone does not supply that serialization.

## Tests and remaining measurements

`python -m pytest -q tests/test_fresh_source.py`: **47 passed**. The tests compile
the actual C, exercise period 10/13/20/40 ms without a fixed ratio, exact native
signed decode, unchanged input bytes, atomic failure, overflow/headroom, partial
I2C, replay, missing/overlapping/old timestamps and clock wrap. The UBSan native
stress test covers 10,000 sessions and 250,000 selected samples. These synthetic
receipts test the contract; they do not qualify the hardware. Root’s linked ARM
workflow separately verifies compiled instruction/ABI behavior.

Before any physical source can be approved, obtain and review:

1. Exact chip/register revision and complete relevant configuration readback,
   especially `3d/3e`, data setup and undocumented `5e`; resolve preliminary-sheet
   contradictions against the actual sensor.
2. Independently timestamped sensor acquisition/FIFO events, pre-drain counts,
   overflow and byte/transfer boundaries, with a conservative clock-error bound.
   Measure stationary and moving behavior, active/idle/wake transitions, and
   competing optical/I2C activity. Host packet timing is not a substitute.
3. Successful, failed, timeout and partial-transfer semantics on the real
   controller, including FIFO advancement and recovery after partial frames.
4. Every drain producer and its concurrency/IRQ/task ownership. Determine whether
   the existing Health drain provides enough headroom and <250 ms acquisition
   age without changes. A watermark of 32 and timer arguments 800/2000 do not
   establish those properties.
5. A before/after trace showing identical Health frame bytes/order, drain and
   algorithm-call timing, cursor behavior, idle/wake and step/sleep results.
   Adding another reader, reducing a timer or waking through `cb5e` would require
   a separate reviewed design; none is authorized by this document.

If existing Health drains are too old/full, a strictly passive source cannot meet
the contract. That is an explicit design blocker, not permission to change its
cadence. The current evidence supports a fail-closed adapter and a measurement
plan, not a deployable fresh-25-Hz firmware claim.
