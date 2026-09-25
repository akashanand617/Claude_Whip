# Unified firmware: stock memory ownership audit

Status: off-ring research, 2026-09-22. **No allocation approved, no stock patch,
no candidate OTA, no device access.** This closes the previously unclassified
stock tail and the meanings of the startup memory-layout arguments. It does
not close the memory-placement safety gate.

Later [descriptor/placement evidence](UNIFIED_PLACEMENT_GATE.md) captured the
narrow configuration and bank0 windows discussed below. The subsequent
[resource budget](UNIFIED_RESOURCE_BUDGET.md) measures the current ARM objects,
records the daily-ring-only constraint, and reduces a nested sample-processing
stack pair from 600 to 440 bytes. None of these findings approves the nominal
RAM gap or proves complete task-stack headroom; historical sections below retain
their original evidence boundary. The newer
[whole-integration budget](UNIFIED_READINESS.md#whole-integration-budget-current-append-only-approach-is-insufficient)
now accounts for the **288-byte input receipt and 244-byte observed nested
observation path**, reduced from 480/460 by lossless receipt encoding,
transactional-progress-only scratch and the bounded eight-frame delivery buffer.
The intermediate source-storage checkpoint measured 388 bytes. The older 440 figure was a sum of two
local frames, not the then-full 460-byte nested path. Persistent state alone
is not a complete RAM budget; state plus receipt is still 1084 unallocated bytes.

The later [captured-ROM execution](UNIFIED_STOCK_INTEGRATION.md#captured-rom-execution-and-null-queue-guard)
now executes `update_ram_layout` at `0x4a78` itself: it stores app size,
data-heap size and cache-sharing selector, leaving the base pointers untouched.
That supersedes the older unread-callee boundary below, but still does not
initialize an allocator or approve ownership of the nominal RAM interval.

Input is exclusively `firmware/rt02cr-stock-3.12.02.bin`, 138016 bytes, SHA-256
`b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0`.
File-to-flash bias is `0x825fb0`; RAM-loaded code has a different execution
address. `whip/fwlayout.py` refuses all nonidentical input before returning a
map or constructing the emulator. Never transplant these addresses to V2.

## 1. The last 200 file bytes are a boot overlay, not spare space

The earlier stock audit correctly declined to use the tail but left its purpose
unclassified. It is now traced in three independent ways: actual stock startup
calls, the initialized descriptor table, and selected instruction execution.

| Region | File interval, end exclusive | RAM interval, end exclusive |
|---|---|---|
| Permanent RAM code | `0x20cc8..0x21578` | `0x207c00..0x2084b0` |
| Initialized data | `0x21578..0x21a58` | `0x2084b0..0x208990` |
| BSS | none | `0x208990..0x20e734` |
| Boot-only overlay, including literals | `0x21a58..0x21b20` | `0x20e734..0x20e7fc` |

The table at file `0x21578`, loaded to RAM `0x2084b0`, has three 36-byte
descriptors. Each holds nine words: signature pointer, code/data load pointers,
code/data/BSS execution pointers, and the three lengths. Descriptor zero copies
`0xc8` bytes from flash `0x847a08` to RAM `0x20e734`. Its other lengths are zero.
Descriptors one and two have zero lengths, so selecting them changes the
eight-byte scenario signature but does not erase the old overlay code.

Stock loader `0xa34` checks the index, compares the signature at RAM `0x208c72`,
then performs the specified copies/clear only if the scenario changed. Boot
loads index zero at file `0x670`, then calls RAM `0x20e734` at file `0x6a4`.
Decoded at that RAM execution address, the tail calls the correct ROM functions:
`__aeabi_memcpy4`, `RamVectorTableInit`, `trace_string`, and `log_buffer`.
Decoding at its flash load address instead produces misleading branch targets.

The overlay initializes interrupt vectors from the 58-word table at file
`0x20be0`. It considers indices 2 through 57; selected writes go to
`0x200008..0x2000e4`. Tests with VTOR already initialized and with explicit
mock ROM initialization both leave the entire following 1028-byte interval
unchanged. This proves the selected vector-initialization path, not every
possible writer in ROM, a ROM patch, or the Bluetooth upper stack.

## 2. Startup memory-layout ABI is now supported by source and binary evidence

The public SDK-derived RTL8762E project at commit
`49301d9b75816ccde1cc9657b827fdadf5736937` contains Realtek-copyrighted declarations
and startup source. It is a third-party source mirror, **not a signed vendor SDK
or proof that the ring was built with this SDK release**. Compatibility is
supported more strongly than by matching function names:

- Its ROM UUID is exactly the stock header's
  `f94c6b7e11c5eb118282f74a0c0cef5b`.
- Its complete 427-entry ROM symbol file is byte-identical to the archived
  symbol file, SHA-256
  `6f5a59f6444c01328808ac148b9c60771410196ab3b57e08fc8ff90525934247`.
- The stock caller's register values and allocator wrappers match the declarations.

The declaration in
[system_rtl876x.h, lines 195–202](https://github.com/atc1441/ATC_RTL_BLE_OEPL/blob/49301d9b75816ccde1cc9657b827fdadf5736937/ATC_RTL_BLE_OEPL_8762ESL/sdk/inc/platform/system_rtl876x.h#L195)
assigns `update_ram_layout` three arguments: application globals/code size, data
heap size, and cache RAM sharing size. The
[startup source](https://github.com/atc1441/ATC_RTL_BLE_OEPL/blob/49301d9b75816ccde1cc9657b827fdadf5736937/ATC_RTL_BLE_OEPL_8762ESL/sdk/src/mcu/rtl876x/system_rtl876x.c#L710)
uses the corresponding configuration constants.

Actual stock instructions at file `0x6d4..0x6f2` supply:

| Register | Value | Supported meaning |
|---|---|---|
| r0 | `0x7000` = 28 KiB | Application globals and RAM code |
| r1 | `0x7400` = 29 KiB | Data heap |
| r2 | `0` | No cache RAM shared as application RAM |

The third argument was previously omitted from the research notes. `movs r2,#0`
at `0x6d6` survives unchanged to the call at `0x6ee`. The execution harness now
captures all three registers at ROM `0x4a78` and stops **before** executing the
unavailable ROM implementation.

The mirrored
[memory configuration](https://github.com/atc1441/ATC_RTL_BLE_OEPL/blob/49301d9b75816ccde1cc9657b827fdadf5736937/ATC_RTL_BLE_OEPL_8762ESL/config/mem_config.h)
and [linker script](https://github.com/atc1441/ATC_RTL_BLE_OEPL/blob/49301d9b75816ccde1cc9657b827fdadf5736937/ATC_RTL_BLE_OEPL_8762ESL/gcc/app.ld)
place the application after reserved and upper-stack RAM, with the heap after
the application reservation. Their sample *sizes* belong to an e-paper device;
only the ABI/relationship is used here. Combining that relationship with the
stock copy base gives a **nominal** application reservation
`0x207c00..0x20ec00`, followed by heap `0x20ec00..0x216000`.

There are therefore **1028 nominal bytes between the last known overlay byte
and the reservation end**: `0x20e7fc..0x20ec00`. Aligning to `0x20e800` would
leave 1024 bytes. This is an investigation lead, not an approved allocation:

1. The ring's exact live OTP configuration, upper-stack image, and ROM-patch
   configuration have not been obtained here. The newer mirrored startup writes
   `OTP->appDataAddr`; that store is not present in this stock startup slice.
2. A halfword-aligned literal-word survey finds only the two zero-length overlay
   endpoints at `0x20e7fc` and no literals inside the interval. Absence of literal
   references does not rule out indirect accesses, externally supplied pointers,
   alternate image behavior, or unexpected ownership outside the application.
3. Startup clear currently ends before this interval. A future state object needs
   an explicit initialization path, correct warm/deep-sleep behavior, and an
   independent check that no existing execution can overwrite it.

The official
[RTL8762E SDK User Guide v1.4](https://www.realmcu.com/img/ipd/en_638324676932758544.pdf)
describes RAM as shared by ROM state, stacks, patch/upper-stack/application state,
and dynamic allocation. Its configurable cache region starts at `0x216000`;
the zero-sized stock cache copy is not evidence that those 8 KiB are available.
The older guide's default-size diagram is not a ring-specific linker map.

## 3. Dynamic allocation is an alternative, with explicit failure obligations

The
[SDK-derived allocator declarations](https://github.com/atc1441/ATC_RTL_BLE_OEPL/blob/49301d9b75816ccde1cc9657b827fdadf5736937/ATC_RTL_BLE_OEPL_8762ESL/sdk/inc/os/os_mem.h)
define `(ram_type, byte_count, caller_string, source_line)` for allocation and
zero-allocation, with null indicating failure.
[mem_types.h](https://github.com/atc1441/ATC_RTL_BLE_OEPL/blob/49301d9b75816ccde1cc9657b827fdadf5736937/ATC_RTL_BLE_OEPL_8762ESL/sdk/inc/platform/mem_types.h)
assigns data-on RAM type zero. Stock wrappers independently confirm this ABI:

| Wrapper / function | Stock file or Thumb ROM address | Observed behavior |
|---|---|---|
| malloc wrapper | file `0x12948` | Passes requested byte count, RAM type 0, caller/line |
| calloc wrapper | file `0x12958` | Multiplies two inputs, then calls zero-allocation |
| allocation | ROM `0x12c31` | Interface endpoint, not executed in proof |
| zero-allocation | ROM `0x12c8b` | Interface endpoint, not executed in proof |
| free | ROM `0x12d4d` | Existing stock free wrapper at file `0x129f4` |

Selected-instruction tests exercise the actual malloc/calloc wrappers with
successful-pointer and null returns from the mocked allocator. They prove the
calling convention and unchanged return propagation, **not allocation safety or
capacity**. Avoid the stock realloc wrapper for integration: its path frees the
old block before allocating/copying a replacement and is not a safe foundation
for a new fallible mode transition. Fixed-size allocation avoids multiplication
overflow and mode-by-mode fragmentation.

A defensible future strategy is one fallible allocation after stock Health
initialization, with no sensor changes until it succeeds. Failure must leave
all stock Health behavior untouched and report Gesture unavailable. However,
success alone is insufficient: permanently holding heap memory can starve later
stock allocations. Stock configuration-writing code at `0x1a4f0` requests
1024 and 2048 bytes, for example. Free heap, fragmentation, future workload
reserve, deep-sleep retention, and a safe persistent pointer slot still need
evidence. `os_mem_peek` is not a guarantee of the largest contiguous block.

## 4. Task stacks and serialization are real constraints

The SDK-derived
[task API](https://github.com/atc1441/ATC_RTL_BLE_OEPL/blob/49301d9b75816ccde1cc9657b827fdadf5736937/ATC_RTL_BLE_OEPL_8762ESL/sdk/inc/os/os_task.h#L38)
specifies stack size in **bytes**, not words. Three direct stock task creations:

| Entry file | Creation call | Stack bytes | Priority |
|---|---|---:|---:|
| `0x854` | `0x8e2` | 1024 | 2 |
| `0x131e` | `0x13e6` | 3584 | 1 |
| `0x1466` | `0x14b6` | 2560 | 2 |

Stock entry code at `0x48c` explicitly sets the startup SP to `0x203800`.
None of these values establishes unused stack margin. Compiler frame reports
are local frames, not nested call-chain/interrupt maxima. The vendor guide
describes priority-based preemption, so main-task command handling and a
higher-priority sensor queue cannot be treated as serialized just because both
eventually call the same driver.

## 5. Appending flash code: structurally possible, capacity not established

The actual Realtek image occupies flash `0x826000..0x847ad0`: a `0x400`-byte
header plus `0x216d0` bytes of payload, excluding the outer 80-byte container.
Adding bytes **after** file EOF would not inherently relocate any existing
code/data/overlay, and the three overlay descriptors use explicit lengths.
Keeping every original load address and descriptor is a necessary condition.

It is not yet a sufficient condition. The app image's length field is not its
flash partition size. Stock OTA bounds function `0x10a2` asks ROM for the
temporary bank capacity (`get_temp_ota_bank_size_by_img_id`, with a special
`flash_get_bank_size(5)` branch), checks header payload length plus `0x400`
against that capacity for the first block, and checks offset plus block length.
The returned capacity lives in external platform/OTA configuration, not in the
application bytes audited here. The ROM symbol/UUID match does not supply it.

The mirrored e-paper `flash_map.h` explicitly puts its application at
`0x832000`, unlike this ring's `0x826000`; borrowing its 148 KiB slot would be
an error. Before append can be approved, obtain and validate the ring's exact
active/temporary bank map, next occupied region, flash part/capacity, image-ID
handling, loader/cache behavior, and DFU maximum-size checks. Checksums and a
host reassembly test cannot prove that an extended image fits either bank.

The arithmetic lower bound for each relevant application partition is
`new_vendor_file_size - 0x50`, equivalently
`0x400 + new_payload_length`. For an append of N bytes without other length
changes, this is `0x21ad0 + N`. Any erase/program alignment or container-staging
overhead must be validated separately, not silently rounded away. This bound is
not a permission check and does not identify the correct staging bank.

### A future memory-read plan can supply missing configuration

The UUID-matching
[OTP RAM structure declaration](https://github.com/atc1441/ATC_RTL_BLE_OEPL/blob/49301d9b75816ccde1cc9657b827fdadf5736937/ATC_RTL_BLE_OEPL_8762ESL/sdk/inc/platform/otp.h)
provides concrete non-peripheral data addresses. No device reads were authorized
or performed for this audit:

| Address / length | Requested fields, little-endian words |
|---|---|
| RAM `0x200380`, 16 bytes | appDataAddr, appDataSize, heapDataONSize, heapBufferONSize |
| RAM `0x2003e4`, 48 bytes | Bank 0 address/size, Bank 1 address/size, FTL address/size, OTA-temp address/size, backup 1 address/size, backup 2 address/size |
| Each validated nonzero bank base + `0x198` | Image address/size descriptors; application pair is at `+0x1a8` / `+0x1ac` |

The application descriptor offsets agree with both the
[OTA structure declaration](https://github.com/atc1441/ATC_RTL_BLE_OEPL/blob/49301d9b75816ccde1cc9657b827fdadf5736937/ATC_RTL_BLE_OEPL_8762ESL/sdk/inc/platform/patch_header_check.h)
and stock file `0x4f4..0x4fc`: its image-ID-indexed size access gives bank-base
`+0x1ac` for application image ID `0x2793`. The same code's upper-stack ID
`0x279a` accesses `+0x1e4`, so retain the full relevant descriptor area through
`+0x1e8`, not merely the shorter application-only part of the mirrored struct.
Validate every returned address, size, non-overlap and header identity before
using it to choose a second read. Header metadata must be checked against the
known application base and the current installed image, not trusted in isolation.

**Do not dump all OTP RAM:** neighboring fields include keys. The narrow windows
above exclude those fields. Do not read hardware registers, FIFO ports, or invoke
ROM functions via diagnostic operations to obtain a capacity.

Also distinguish read-only *data* from side-effect-free *transactions*. In this
stock binary, the CD01 handler at `0x4c36` copies at most 14 bytes to a reply;
it does not write the requested address. However, the common UART dispatcher at
`0x5882` first calls `0x8112` for CD as it does for most commands. That prelude
sets RAM `0x20a66c` to one and, in states two/three returned by `0x96e0`, calls
the DFU reassembly-timer restart at `0x80ee` and `0x948a(0,0)`. Its complete
state-machine effects have not been reclassified here as harmless.

Therefore a future diagnostic session requires a coordinated idle connection,
no DFU or streaming, and an audit of this prelude in the **actually installed**
image. The stock offsets above do not authorize a current-V2 transaction. Keep
the existing one-request-at-a-time, poisoned-session-on-timeout rule: CD replies
do not echo their address or a request ID. Config reads can establish configured
bank extents without executing ROM, but cannot alone establish that the flash
part, OEM/OTA headers, ROM-patch behavior, retention, or recovery are correct.

## 6. Reproduction and limits

`tests/test_fwlayout.py`: **25 passed, none skipped**, using the existing isolated
Unicorn 2.1.4 proof environment outside the macOS JIT-restricted sandbox:

```sh
python -m pytest -q tests/test_fwlayout.py
```

Tests cover exact identity refusal, descriptor decoding, contiguous occupied
ranges, boot load-before-call instructions, real loader copy bounds, repeated
scenario behavior, invalid indices, zero-length overlays, corrupted descriptor
refusal, instruction budgets, actual setup register values, allocator wrapper
null propagation, and relocated vector-code writes under two VTOR states.

The harness is deliberately bounded. The test stack at `0x301000` is synthetic,
not ring RAM. ROM allocation/layout, vector initialization and logging are
explicit observation/mocking boundaries; full boot, actual ROM patch, scheduler,
interrupt execution, retention, heap management and hardware are not emulated.

Source downloads are read-only reference copies at
`/tmp/whip-stock-layout.sBSW18/`; source URLs above pin a commit. Relevant SHA-256:

| Reference | SHA-256 |
|---|---|
| `system_rtl876x.h` | `cc37e906cbb9f70545148f9496658106bb1b923ea0154a857c6508593b4cafed` |
| `system_rtl876x.c` | `d784cc2394b0a2bcc4d39f6ffcdcf4efa655091105238394565afc075968ab79` |
| `os_mem.h` | `f8fc3a31486ca98f76161a4e0613a3ef25964e2d565fd89ff3429fe3ef4d9c80` |
| `mem_config.h` | `7589f88c34190df9a79e3557d0d1cf21cfe8b23a638c664e107e3a8a757c2130` |
| `overlay_mgr.c` | `933db999a1172024ca69810f464b3cc032ad1e3f8e93dabf6ee4fbf4ab5e6a37` |
| `rom_uuid.h` | `dc0260059fffcac192925198435ba079c76d7a31b515e026ac571a49c279de22` |
| `otp.h` | `21e0624c0d4c9b661a57bb8721f67c61de302d0c51c181e7f30e780e75b7a3e1` |
| `patch_header_check.h` | `14a82f325d07b1702fa7acbf7c078662b5131fb4f7ce0fb94e934f5b34c67ba8` |

No source from the e-paper application is installed or used as ring firmware.
The PDF-reading skill was used to inspect the vendor guide; the decisive ring
boundaries above come from the pinned binary and bounded instruction tests.
