# Unified firmware: actual partition and OEM-update placement gate

Status: 2026-09-23, workflow 3. **The configured APP/staging capacity is now
measured and agrees with the pinned OEM transfer code. Placement and flashing
remain blocked.** This work did not build a candidate, modify an image, connect
to the ring, or change a production gate. The parent workflow performed the
separately reviewed bounded diagnostic session and disconnected afterward.

The new conclusion is narrower than “9520 bytes are safe to use”: there are
9520 configured bytes beyond the complete stock application, including its
occupied boot overlay, and the existing INIT size check accepts that maximum.
Physical flash geometry, boot-copy recovery, linked-code placement and RAM
ownership are separate obligations.

## 1. Actual evidence, with reproducible provenance

The parent captured the fixed 80-byte bank0 descriptor at
`0x802198..0x8021e8`, twice, after checking the existing V2 fingerprint, idle
raw mode, and prior 16/48-byte configuration values. Configuration and idle mode
were checked again afterward. The transcript ends with equal repeats; no
returned pointer was followed. The diagnostic CD path is **not wholly
side-effect-free**: its previously reviewed UART prelude updates connection/
timer bookkeeping. Nothing in this audit upgrades that to a harmless generic
memory-reading interface. See [the capacity audit](UNIFIED_CAPACITY_GATE.md).

The exact capture is now preserved in
[`firmware/research/2026-09-23/bank0-descriptor/`](../firmware/research/2026-09-23/bank0-descriptor/):

| Evidence | SHA-256 |
|---|---|
| `configuration.json` | `ba6f56f927bae69ad8144673b878970ea0279a9e96ad89b986f0e76891e58dd7` |
| `transcript.jsonl` | `9b98a908895249d2987ff675b7ebf340898f67437e3f2f5bc8e6f08a6d666043` |
| Descriptor's 80 raw bytes | `d74c3afddf382c36dd4c566c539d2dcff16a22e0c7f525a9c1a342875cc4e12f` |

Tests embed the exact 144 configuration/descriptor bytes with this provenance
and additionally compare them against the archived JSON and its complete hash.
They do not depend on the ignored `data/` directory. A declared `device_capture`
and self-supplied hashes are not cryptographic device attestation. In particular,
the capture's `image_sha256` names the V2 **partial-fingerprint reference**, not
a full image downloaded from the device. The pure parser intentionally keeps
live-image/physical-attestation flags false.

The actual descriptor contains these nonempty partitions:

| Partition | Start | Size | End, exclusive |
|---|---:|---:|---:|
| ROM patch | `0x803000` | `0xa000` | `0x80d000` |
| Secure boot | `0x80d000` | `0x1000` | `0x80e000` |
| Upper stack | `0x80e000` | `0x18000` | `0x826000` |
| APP | `0x826000` | `0x24000` (147456 bytes) | `0x84a000` |

APP-data1 through APP-data6 each have start `0x84a000` and size zero. They are
not additional space. The surrounding configuration gives bank0
`0x802000..0x84a000`, bank1 size zero, FTL `0x84a000..0x84e000`, and OTA staging
`0x84e000..0x872000`. This is not a dual-bank rollback guarantee.

The startup-written `backup1=(0x01000000,0x00800000)` declaration remains
quarantined. It is neither proof of an 8 MiB physical chip nor an approved read
target. No parser bounds were loosened to accommodate it.

## 2. Actual stock and V2 code agree with the configured capacity

`whip/fwplacement.py` hash-pins complete images before inspecting or emulating
them; all offsets below are **file offsets**, not absolute flash addresses.
The flash bias is `0x825fb0`.

| Image | File bytes | SHA-256 |
|---|---:|---|
| Stock 3.12.02 | 138016 | `b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0` |
| Original 25 Hz | 137540 | `f13e63d3fdef3b10aa20fd4e0672077b66f60bb19c689ef64053840e4d35d3d9` |
| Optical-off V2 | 137540 | `0d18a0fa860d58ab8f984b5f542f45dac105241f47bf1c2af41321eb0431e14c` |

The APP header has ID `0x2793` and ROM UUID
`f94c6b7e11c5eb118282f74a0c0cef5b`. Its payload length plus the 1024-byte Realtek
header equals `vendor_file_size - 80`. Therefore:

```text
complete stock Realtek image = 138016 - 80 = 137936 = 0x21ad0 bytes
configured APP and staging   =              147456 = 0x24000 bytes
configured stock margin      =                9520 = 0x02530 bytes
maximum vendor file size     = 147456 + 80 = 147536 = 0x24050 bytes
```

Stock occupies `0x826000..0x847ad0`; the configured margin is
`0x847ad0..0x84a000`. All future code, literals, alignment and metadata growth
must fit together. Using the shorter V2's margin for a stock-derived unified
image would be wrong. The 200 bytes immediately before stock EOF are an active
boot overlay, **not a code cave**; its evidence remains in
[the memory audit](UNIFIED_MEMORY_AUDIT.md).

These are the actual OEM call targets, independently checked by decoding their
dispatcher BL instructions and then executing the target instructions:

| Operation | Stock target / dispatcher call | 25 Hz and V2 target / dispatcher call |
|---|---|---|
| INIT | `0x841a` / `0x927a` | `0x81f6` / `0x905e` |
| DATA | `0x84b2` / `0x9280` | `0x828e` / `0x9066` |
| Receipt CHECK | `0x85ea` / `0x9286` | `0x83c4` / `0x906e` |
| END | `0x8626` / `0x928c` | `0x8400` / `0x9076` |

INIT requires nine bytes and type 1 or 4. It reconstructs the little-endian
vendor size and checks, with unsigned arithmetic:

```text
(vendor_file_size - 0x2800) < 0x21851
```

The accepted inclusive interval is exactly `0x2800..0x24050`. Tests execute
both boundary sides, extreme u32 values, all 256 type bytes, and wrong packet
lengths. DATA loads its fixed staging base `0x84e000` from stock pool `0x86ec`
or V2 pool `0x84c4`. The size-bound pool is stock `0x86e8` or V2 `0x84c0`.
Thus three separate pieces of evidence agree: captured APP size, captured OTA
staging size, and the pinned OEM INIT limit/staging literal.

The startup header resolver at `0x4e0` provides another exact Thumb witness.
For APP ID `0x2793`, its instruction at `0x4fc` reads the descriptor **size**
word at bank+`0x1ac`, inside the captured 80 bytes. Zero size returns no entry.
With mocked successful bank/header validation and header-address resolution,
the real pinned APP header returns Thumb entry `0x826401`. Those ROM decisions
are explicit mocks: this does not prove the boot ROM's active-bank selection,
signature policy, or recovery implementation.

The linked SDK `dfu_update` at `0xdd2` and its bounds helper `0x10a2` are **not
substituted for the OEM path**. No direct call or literal pointer to `0xdd2`
was found in the pinned APP. Its stronger-looking readback/bounds routines
cannot be credited to the actual OEM DATA handler above.

## 3. Exact failure witnesses: receipt is not verified programming

These are deliberately synthetic off-ring failure tests, never packets sent to
the ring. All flash calls stop at mocked ROM boundaries; recorded out-of-range
addresses are evidence of a defect, not permitted emulator/device writes.

### Flash-write and mutex failure are not propagated

Stock shim `0x36d8` (V2 `0x364c`) calls stock wrapper `0x3678` (V2 `0x35ec`)
then unconditionally returns zero. The wrapper takes a mutex with timeout 500,
calls ROM `flash_write_locked` at `0x8600`, then gives the mutex; the underlying
write result is overwritten. The DATA caller increments its byte count and
acknowledges success without checking that result.

Actual instruction tests cover successful writes, failed flash writes, and
failure to acquire the mutex. A continued 1024-byte DATA chunk advances the
counter and returns callback `(3,0)` in **all three cases**, including when no
flash-write call happened at all. Sector-erase failures are likewise not
propagated through stock `0x3630` / V2 `0x35a4`.

### Per-chunk final bounds are insufficient

The continued-DATA handler accepts payload lengths up to 1536. It tests only
`written < total_vendor_file_size`, not whether the incoming end remains below
`total_vendor_file_size - 80` or the staging partition end. It computes the next
4 KiB erase address before that comparison.

The exact negative witness starts with maximum legal total `0x24050`, already
credited `0x23ff0`, and a 1024-byte incoming payload. Real instructions request:

```text
erase sector selector 2 at 0x872000       # at configured staging END
write 1024 bytes starting at 0x871ff0     # crosses that END
credit 0x243f0 bytes and acknowledge (3,0)
```

The subsequent CHECK rejects the byte count, but only **after** those modeled
write requests. A separate synthetic state already beyond the declared total
still issues an erase request when the chunk crosses a sector boundary, before
skipping the write. These witnesses show why host-side exact chunk accounting
and receiver-side bounds are safety requirements. They do not claim the normal
existing sender emits malformed chunks.

### CHECK and END have different guarantees

CHECK compares only `written == vendor_file_size - 80` and the state byte.
No checksum, readback, or flash call occurs in the selected actual CHECK code.
It confirms the receiver's **credited length**, not successful programming.

END calls common helper `0xf7a` with APP ID `0x2793`. That helper consults ROM
`get_temp_ota_bank_addr_by_img_id` (`0x8b94`), bank-switch policy (`0x8b7a`), and
`check_image_chksum` (`0x8a5c`). On success it reaches `dfu_set_ready` (`0x3ed1a`)
through `0xf66`; on checksum failure it does not set ready.

The actual END caller nevertheless continues after either return value. The
witness executes END and `0xf7a` together, then stops **before** END's next
helper at stock `0x864a` / V2 `0x8424`. It never executes the later reset,
activation, or copy code. This is **not** a claim that a failed-checksum image
will boot: the not-ready state may prevent it. Whether the old image remains
recoverable through every interrupted staging/copy/activation state is unknown.

## 4. Geometry and recovery facts still missing

The compatible SDK-derived declarations at pinned commit
`49301d9b75816ccde1cc9657b827fdadf5736937` define sector selector 2 as 4 KiB and
block selector 4 as 64 KiB. The actual DATA code's shifts by 12 and erase
selector 2 match that API. This is an API/convention proof, **not a measured
JEDEC part number, capacity, program-page size or power-loss guarantee**.
See the pinned [flash-device declarations](https://github.com/atc1441/ATC_RTL_BLE_OEPL/blob/49301d9b75816ccde1cc9657b827fdadf5736937/ATC_RTL_BLE_OEPL_8762ESL/sdk/inc/platform/flash_device.h).

The public [advanced flash declarations](https://github.com/atc1441/ATC_RTL_BLE_OEPL/blob/49301d9b75816ccde1cc9657b827fdadf5736937/ATC_RTL_BLE_OEPL_8762ESL/sdk/inc/platform/flash_adv_cfg.h)
expose `flash_get_id()` and SFDP reads, but provide no implementation or proof of
a stable RAM copy of their results. The ROM symbol table names
`flash_device_info` at `0x201258`; its layout has not been established. Do not
guess that structure, read peripheral registers, execute a ROM function, or
expand the previous authorization to collect it. OTP `Info`, `PageSize`, and
`Main_Addr` are configuration declarations, not substitute JEDEC evidence.

This is a Realtek-copyrighted **third-party SDK mirror**, not a signed original
SDK for the ring. The exact ROM UUID and complete 427-symbol map match the
existing audit. That supports these ABI interpretations but does not prove
the device's physical flash model or exact SDK build. Cached source hashes:

| Source | SHA-256 |
|---|---|
| `flash_device.h` | `56c2dd44535778fe4305865d59248e70995de8a718044d6124c040e36d2430ba` |
| `flash_adv_cfg.h` | `1f7c1a312f7e6a3797a2530ea4020f935b8b32be045cd6e931b0456f1401df43` |
| `otp.h` | `21e0624c0d4c9b661a57bb8721f67c61de302d0c51c181e7f30e780e75b7a3e1` |
| `patch_header_check.h` | `14a82f325d07b1702fa7acbf7c078662b5131fb4f7ce0fb94e934f5b34c67ba8` |

A useful next off-ring input would be an exact manufacturer BOM/flash identity
or full factory package containing this ring's ROM patch, upper stack and boot
components plus the matching single-bank-update implementation/recovery
documentation. Existing APP-only images and narrow captures do not contain
those implementations. No further device read was proposed or executed here.

## 5. RAM placement remains a distinct blocker

The captured RAM values now confirm the nominal reservation from the earlier
startup audit: APP starts `0x207c00`, size `0x7000`; data heap is `0x7400` and
buffer heap `0x3870`. That closes the old “configuration not obtained” gap,
but not the ownership proof for `0x20e7fc..0x20ec00` (1028 bytes; 1024 after
aligning to `0x20e800`). The measured ROM-patch and upper-stack **flash extents**
do not supply their code or RAM indirect-writer behavior. Their implementations,
ROM retention paths, warm initialization and future heap reserve remain unknown.

The earlier malloc/calloc ABI witnesses remain valid. A fallible allocation
after stock Health initialization is more defensible than declaring arbitrary
RAM unused, but requires a safe pointer lifetime, fail-with-Health-untouched
path, fragmentation/capacity reserve and deep-sleep behavior. None is inferred
from configuration size alone. No code cave or RAM object is reserved here.

## 6. Reproduction and scope of the proof

`tests/test_fwplacement.py`: **66 passed, zero skipped**, using the locked local
proof environment with Unicorn 2.1.4. Without Unicorn the ordinary environment
skips instruction witnesses; that is not the safety result reported here.

```sh
/tmp/whip-unified-build.m1E9lk/proof-env/bin/python -m pytest tests/test_fwplacement.py -q
```

The module uses only the standard library, `whip/fwcapacity.py`, and Unicorn
inside the instruction harness. Tests require all three pinned firmware files
and the archived `configuration.json`; Capstone, network access, Bluetooth, and
ignored data files are not runtime dependencies. On macOS the emulator needs
JIT permission; that permission authorizes only local execution, not device I/O.

The harness rejects unexpected CPU reads, writes and executed addresses. Reads
are restricted to actual loaded image bytes, bounded synthetic context/packet/
stack fixtures, the mutex word and (only for the boot-resolver experiment) the
80-byte descriptor. Padded mapped flash/RAM is not silently accepted as data.
Writes are restricted to the synthetic stack and the reviewed context fields;
the callback pointer is protected. Explicit memcpy/flash/RTOS mocks have their
own argument checks. Instruction budgets and stack restoration are checked;
the intentionally partial END witness stops at its documented boundary.

The audit APIs return configured arithmetic and code bindings, but always keep
geometry, recovery, RAM ownership, candidate verification, placement and flash
authorization false. Passing these tests is a stronger description of the
remaining problem, not permission to flash an expanded image.
