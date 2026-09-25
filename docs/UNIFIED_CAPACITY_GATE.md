# Unified capacity gate: evidence parser and diagnostic-path review

2026-09-23. **The analysis/tests here are off-ring. No RAM placement or flash
permission is granted.** A separately coordinated bounded physical read is now
recorded in the final section. The reader belongs to
`whip/fwcapacity_read.py` / `probe/capacity_read.py`; any later physical result
must be linked and reviewed separately, not inferred from the tests below.

## Existing evidence does not establish the bank map

An inventory of `data/` and `firmware/research/` found 136 JSONL files, including
archive duplicates, with 456 explicit `CD01` request records and 176
address-bearing code-read records. These counts are records, not independent
device transactions or sessions. Parsing every JSON line succeeded.

The explicit RAM-read intervals start at `0x209e09`, `0x20bd94`, `0x20bdc4`,
`0x20bfc0` and `0x20cc4c`. The flash reads are the existing 22 critical-code
chunks spanning eight short regions. **None overlaps the two configuration
windows needed here.** Previous fingerprints identify sampled code only.

Repository-wide filename inventory, including ignored files outside virtual
environments/build/dependency directories, found six application containers,
duplicate iOS app containers, the archived ROM symbol text, artificial-address
test ELFs and classifier weights. No full-chip flash image or OTP/configuration
capture was found. The longest application container is 138016 bytes; it is not
a complete flash backup. Other local/user directories were not searched.

Consequently, the existing archives cannot honestly close bank capacity. An OEM
flash/configuration image supplied independently could still resolve this
off-ring. Otherwise a separately authorized, narrowly bounded inspection is
needed; a full OTP dump is specifically excluded because neighboring fields
include keys.

## Exact input contract

`whip/fwcapacity.py` has no BLE dependency, transport, arbitrary memory reader,
patcher, writer or authorization override. Its public parsing entry points are:

```python
parse_ram_config(data16)
parse_flash_config(data48)                # tuple[Region, ...]
inspect_flash_config(data48, image_sha256=...)  # separates opaque declarations
parse_bank_descriptors(data80, bank)       # tuple[Region, ...]
analyze_capture(capture, vendor_file_size=138016)
load_capture(json_text)                   # rejects duplicate JSON keys
```

`Region` is immutable and carries `name`, `address`, `size`, `end`. The exact
capture object, with no extra keys accepted, is:

```json
{
  "schema": "whip.capacity.capture.v1",
  "evidence_kind": "device_capture",
  "session_id": "bounded-session-identifier",
  "image_sha256": "FULL_REVIEWED_IMAGE_SHA256",
  "windows": [
    {"address": 2098048, "data_hex": "LOWERCASE_HEX_OF_EXACTLY_16_BYTES", "sha256": "HASH_OF_DECODED_BYTES"},
    {"address": 2098148, "data_hex": "LOWERCASE_HEX_OF_EXACTLY_48_BYTES", "sha256": "HASH_OF_DECODED_BYTES"}
  ]
}
```

The placeholders above are not accepted input. This is a schema illustration,
not an invented physical capture. `evidence_kind` is either `device_capture` or
`synthetic_fixture`; the session identifier contains 1–96 ASCII letters,
digits, underscores, dots or hyphens. Accepted declared image hashes are the
exact stock, original 25 Hz and V2 values in the firmware ledger.

The RAM window is `0x200380` (2098048), exactly 16 bytes. Its four little-endian
words are `appDataAddr`, `appDataSize`, `heapDataONSize`, `heapBufferONSize`.
The flash window is `0x2003e4` (2098148), exactly 48 bytes. Its six little-endian
address/size pairs are bank0, bank1, FTL, OTA temporary, backup1 and backup2.

After parsing those windows, at most two additional windows are accepted:
exactly 80 bytes at each **validated, nonzero-sized** bank's base plus `0x198`.
This is a parser allowlist, not permission to follow pointers on hardware.
The first reader stage deliberately follows no bank pointers. Descriptor pairs
are secure boot, ROM patch, app, app-data1…6, and upper stack. Application fields
are at bank `+0x1a8/+0x1ac`; upper-stack fields are at `+0x1e0/+0x1e4`.
The stock image-ID-indexed access independently supports the final pair; the
shorter mirrored `T_OTA_HEADER_FORMAT` declaration stops before it.

Validation rejects duplicate/unreviewed windows, extra fields, noncanonical or
oversized hex, wrong content hashes, malformed lengths, bool-as-integer inputs,
out-of-envelope extents, overlap, overflow, application partitions overlapping
the bank header, and descriptor pointers outside their validated parent bank.
Empty slots may retain an aligned endpoint, as SDK configuration examples do;
they never become follow-up read targets.

The 4 KiB alignment requirement is a conservative supported-format policy, not
a measured erase-sector property. Flash address bounds `0x800000..0x1000000`
are a syntactic envelope, **not an assertion that the ring has 8 MiB of flash**.
Unfamiliar but potentially valid layouts are refused for separate review.

## A valid configuration is not a passed physical safety gate

The lower bound for an application's partition is:

```text
required bytes = vendor file size − 0x50
               = Realtek header 0x400 + payload length
stock required = 0x21ad0
stock plus N appended bytes requires at least 0x21ad0 + N
```

The parser reports per-bank configured app fit/margin and a separately named
OTA-temporary configured fit. It does not assume which bank is active or which
OTA route this product uses. A bank containing an app descriptor at `0x826000`
is labeled as describing the known app base, not as proven active. A temporary
region fitting the bytes is not proof the ROM/OEM DFU path uses that region.
Erase/program rounding and other staging overhead remain separate obligations.

Even a document labeled `device_capture` is only a claim. Self-supplied hashes
bind content, not provenance; stable repeated reads do not validate late-reply
correlation or exact live-image identity. Reports therefore **always** contain:

- `physical_evidence_verified: false`
- `live_image_verified: false`
- `staging_route_verified: false`
- `flash_chip_capacity_verified: false`
- `placement_approved: false`
- `flash_authorized: false`

Likewise, matching nominal stock RAM reservation does not establish that the
1028-byte interval after the boot overlay is unowned, correctly initialized or
retained. ROM patches, upper-stack ownership, indirect writers, stack margin and
health-safe heap reserve remain unresolved. See [the memory audit](UNIFIED_MEMORY_AUDIT.md).

## Exact 25 Hz and V2 diagnostic side effects

`audit_cd_image` accepts only these complete local files, both 137540 bytes:

| Image | SHA-256 |
|---|---|
| Original 25 Hz | `f13e63d3fdef3b10aa20fd4e0672077b66f60bb19c689ef64053840e4d35d3d9` |
| Optical-off V2 | `0d18a0fa860d58ab8f984b5f542f45dac105241f47bf1c2af41321eb0431e14c` |

The relevant paths/literals are byte-identical in these two binaries. Their ROM
UUID matches the stock audit. All following code addresses are **file offsets**;
runtime address is file offset plus `0x825fb0`.

| Component | File / RAM address |
|---|---|
| Registered UART write callback | `0x78aa` |
| Command length/gate function | `0x59d8`, state pointer literal at `0x5dd4` |
| Fast dispatcher | `0x564a` |
| Prelude call / prelude entry | `0x5658` / `0x7eee` |
| Prelude state getter | `0x94cc`, RAM byte `0x20bbf0` |
| Unconditional activity flag | RAM `0x20a664 = 1`, pointer literal at `0x8130` |
| Conditional DFU reassembly timer restart | `0x7eca`, states 2/3 only |
| Conditional connection-policy helper | `0x9276(0,0)`, states 2/3 only |
| CD handler / operation-1 copy call | `0x4b16` / `0x4b68` |
| Checksum / transmit helpers | `0x3eec` / `0x7c0c` |

These are not the stock offsets or RAM flag; stock uses prelude `0x8112` and
RAM `0x20a66c`. Applying stock addresses to V2 would be incorrect.

Operation 1 clamps its copy to 14 bytes, copies from the requested data address
to a stack reply, checksums and transmits it. The requested source is not
written. The dispatcher prelude nevertheless runs first, before any identity
or idle read can have been checked by the host. Historical sampled identity
and a DIS/version string cannot remove this bootstrap limitation.

### Connection-policy helper closure, statically reviewed

For the specific `(0,0)` call, helper `0x9276` first requires connected state 2
at RAM `0x209e09`. It may stop a timer through ROM `os_timer_stop` using pointer
slot `0x20bbe8`, then clear RAM `0x20bbf3`. If the pending-policy lock bit is
set, it writes `0x80` to RAM `0x20bbf1`. Otherwise it can select policy zero,
store parameter-record pointer `0x845410` at RAM `0x20bbf4`, set state byte
`0x20bbf0` to zero and enqueue an eight-byte message of type14/subtype10 through
`0x9270 → 0x925c → 0x8e8`. Queue acceptance is not assumed.

Task loop `0x854` routes that message through `0x6c72 → 0x6e92`. The actual
compiler switch sends subtype10 to `0x6ed2`, which calls `0x9458`. The BLE
parameter-update instruction site at `0x9480` is already **two NOPs in both
25 Hz and V2**. The remainder still sets RAM `0x20bbf2 = 1` and starts/restarts
a 5000-unit timer via `0x3d0c`, callback `0x9336`. That callback clears this flag
and applies a pending policy through `0x9316`; the alternate policy callback
`0x9310` requests `(2,0)` from the same helper.

No direct sensor start/stop, flash erase/program or reset call was found in
these mapped helper/message/timer paths. This is a bounded static conclusion,
not proof of all ROM queue/timer internals, preemption, hardware state or live
patch identity. The DFU timer path remains stateful; exclude an active transfer
and keep all other clients closed. Do not describe the overall transaction as
side-effect-free, and do not relax the poisoned-session-on-timeout rule.

## Reproduction and explicit mock boundary

```sh
python -m pytest -q tests/test_fwcapacity.py
```

Initial result: **64 passed, zero skipped** in the isolated Unicorn proof environment.
Parser tests use an explicitly invented map and establish no ring capacity.
They cover exact arithmetic boundaries, invalid input types/sizes, overlapping
regions, parent/header boundaries, absent banks, unsupported addresses, forged
provenance claims and malformed/duplicate JSON fields.

`CDReadHarness` executes actual pinned Thumb dispatch, prelude, state getter,
CD01 handler and checksum instructions. Each image is exercised over all 256
state-byte values and all 256 requested-length bytes. The source is a synthetic
16-byte non-secret RAM fixture; packet/stack memory is artificial and outside
real ring RAM. Direct writes are restricted to its stack and the one reviewed
activity flag. The harness checks source preservation, stack restoration,
execution spans and instruction budgets. Whole-image mutations are refused.

Timer-restart and connection-policy helper calls are **observed, not executed**
by this harness; the deeper lifecycle discussion above is static analysis.
ROM memcpy has an exact bounded fixture implementation. TX stops at its helper
entry and captures the response, without pretending the stock queue accepted or
delivered it. Callback registration, full boot, live ROM/RTOS, interrupts,
sensor timing, radio behavior, encryption/security configuration and recovery
are not emulated or certified here.

Source field declarations, pinned commit/UUID/ROM-symbol evidence and their
scope limits are retained in [UNIFIED_MEMORY_AUDIT.md](UNIFIED_MEMORY_AUDIT.md).

## Separately collected bounded configuration: 2026-09-23

After the user confirmed an exclusive idle session, the root agent ran the
reviewed fixed-window reader and disconnected. This subtask did not access the
device. Immutable local evidence:

- `data/capacity-20260923-idle-config/configuration.json`, SHA-256
  `f8caf08fecc769c4652c57da7db5e1b385dd6223468cbedefbc9d8f705dd9d14`
- `data/capacity-20260923-idle-config/transcript.jsonl`, SHA-256
  `80e9443db0ef0a53b831e9261b3f99b56af347b83c59c6fd9cf324cc2efcf7a6`

The transcript reports the V2 critical/diagnostic-code fingerprint, raw-mode
zero before and after, and two identical reads of each 16/48-byte window. It
does not attest the complete installed image or physical flash capacity. These
two raw windows, not the whole transcript, are embedded in a provenance-labeled
regression fixture so tests do not depend on ignored local files.

### Observed configured values

| Field | Observed value / interval |
|---|---|
| App RAM address / reservation | `0x207c00` / `0x7000`, ending `0x20ec00` |
| Data heap configured bytes | `0x7400` = 29696 |
| Buffer heap configured bytes | `0x3870` = 14448 |
| Bank0 | `0x802000..0x84a000`, size `0x48000` = 288 KiB |
| Bank1 | size zero; endpoint `0x84a000` is not an occupied bank |
| FTL | `0x84a000..0x84e000`, size `0x4000` = 16 KiB |
| OTA temporary | `0x84e000..0x872000`, size `0x24000` = 144 KiB |
| Backup1 declaration | address `0x01000000`, size `0x00800000`; **unresolved, not capacity** |
| Backup2 | address/size zero |

The RAM reservation matches the earlier stock-derived nominal layout, but this
is a V2-session observation, not a live stock-boot measurement. It does not
establish free heap, static ownership, retention or stock Health's peak needs.

From the known app base `0x826000` to bank0's configured end there are at most
`0x24000` bytes. Subtracting stock's `0x21ad0` minimum leaves **9520 bytes
(`0x2530`) as an upper bound only**. The actual app partition could end earlier;
its descriptor has not been read. OTA-temporary size happens to match this
upper bound, but its configured extent alone does not prove the OTA routing,
physical chip size, sector geometry or recovery safety.

### Why the initial parser refusal was correct

The captured pair at `0x200404/0x200408` lies outside the supported primary-flash
envelope. It is not a shifted or differently typed SDK field: the pinned
[OTP declaration](https://github.com/atc1441/ATC_RTL_BLE_OEPL/blob/49301d9b75816ccde1cc9657b827fdadf5736937/ATC_RTL_BLE_OEPL_8762ESL/sdk/inc/platform/otp.h#L205)
names exactly those words `bkp_data1_addr` and `bkp_data1_size`. The corresponding
[startup source](https://github.com/atc1441/ATC_RTL_BLE_OEPL/blob/49301d9b75816ccde1cc9657b827fdadf5736937/ATC_RTL_BLE_OEPL_8762ESL/sdk/src/mcu/rtl876x/system_rtl876x.c#L742)
allows the application to overwrite them under
`SUPPORT_SINGLE_BANK_OTA_USER_DATA`. More decisively, the exact local 25 Hz and
V2 binaries do so explicitly:

| File instruction | Effect |
|---|---|
| `0x6f2: ldr r0,[pc,#0xbc]` | Literal `0x7b0` supplies `0x200480` |
| `0x6f4: movs r1,#1`; `0x6f6: lsls r1,r1,#24` | `r1 = 0x01000000` |
| `0x6f8: subs r0,#0x80` | `r0 = 0x200400` |
| `0x6fa: str r1,[r0,#4]` | Write backup1 address at `0x200404` |
| `0x6fc: lsls r1,r0,#13` | 32-bit result `0x00800000` |
| `0x6fe: str r1,[r0,#8]` | Write backup1 size at `0x200408` |

The new selected-instruction witness executes these seven instructions in both
pinned images, observing exactly those two stores and unchanged neighboring
configuration. It stops before the remaining startup code; no ROM or real
hardware executes. This proves an application-written declaration, **not** the
existence of an external flash, a usable address alias or an 8 MiB chip.

`parse_flash_config` remains strict and continues to reject this input.
`inspect_flash_config`, used by `analyze_capture`, recognizes only this exact
pair under the two reviewed image declarations and returns it separately in
`unresolved_flash_declarations`. It is excluded from validated `flash_regions`;
`complete_flash_map_validated` is false. Unknown variants still fail. Other
overlap/overflow/pointer checks remain enforced. Backup1 cannot become a
descriptor-read target or contribute to any capacity calculation.

### Next possible data read, not executed here

The narrow next descriptor target is **`0x802198`, exactly 80 bytes**, ending
before `0x8021e8`, wholly inside the observed bank0 header. No bank1 or backup
pointer should be followed. A future separately coordinated session must repeat
the relevant configuration/identity checks and bound both repeated descriptor
reads; changed configuration, ambiguous replies or an unsupported header stop
the operation. No additional data read was performed by this follow-up.

Even a validated descriptor must still be cross-checked with the actual bank
header identity, ROM/OEM image routing and physical chip/erase limits before
placement or flashing. Reading a flag or a capacity declaration does not
establish those facts.

Final follow-up verification: **73 capacity tests plus 21 fake-reader tests =
94 passed, zero skipped**. The added cases pin the observed window hashes,
preserve the strict parser refusal, quarantine the known declaration, refuse
unknown variants and unreviewed follow-up addresses, and execute the exact
startup stores in both binaries. These are offline regressions, not another
physical measurement.
