# Legacy diagnostic retirement: conditional code-space inventory

2026-09-24. Bounded, read-only, off-ring audit of the exact stock image. Only
this document is added by this task. No ring connection, command, emulator
patch, stock-file change, linker change, build, allocation or release approval.
Claude Code's separate live-ring work is outside this audit.

## Result

The BF/CE/CD handlers contain **496 instruction bytes** in four complete code
spans. BF jumps over a **40-byte shared literal/string island that must remain**.
If every entry were first retired and alternate-entry closure were established,
reserving a hypothetical four-byte return stub at each original handler entry
and aligning remaining regions inward to four bytes would leave **476 bytes**.
These are conditional planning regions, not approved holes or an implemented
stub design. Approved reclaimed stock space remains **zero**.

This cannot solve the existing **1524-byte** full-candidate deficit by itself:
even the optimistic 476-byte subtraction leaves **1048 bytes**, before the new
filter, remaining hooks, relocation and metadata costs. Adding the separate
408-byte indicator relocation candidate would still leave **640 bytes** under
the same optimistic arithmetic. Neither candidate has ownership approval, and
arithmetic is not a final-link result. See [readiness](UNIFIED_READINESS.md),
[resource budget](UNIFIED_RESOURCE_BUDGET.md) and
[indicator relocation](UNIFIED_RELOCATION_TRIAL.md).

## Exact input and address model

Input: `firmware/rt02cr-stock-3.12.02.bin`, 138016 bytes (`0x21b20`), SHA-256:

```text
b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0
```

Unless a runtime column says otherwise, code locations below are **file
offsets**, and range ends are exclusive. Target handlers are XIP: add
`0x825fb0` for their execution addresses. Reference scans used each source
region's actual execution mapping, not one XIP bias over the entire file:

| File region | Execution mapping |
|---|---|
| `0x450..0x20cc8` | File offset + `0x825fb0` |
| `0x20cc8..0x21578` | Permanent RAM code starts at `0x207c00` |
| `0x21a58..0x21b20` | BootOnce overlay starts at `0x20e734` |

Initialized data `0x21578..0x21a58` was not misclassified as XIP instructions.
The stored-pointer scan covered the **whole** image, including initialized
data and headers. These mappings come from the pinned layout/RAM analysis;
they are not new RAM ownership or overlay lifetime evidence.

## Complete handler spans and boundaries

| Handler segment | File span | Runtime span | Bytes / instructions |
|---|---|---|---:|
| BF prefix | `0x48c6..0x48e8` | `0x82a876..0x82a898` | 34 / 17 |
| BF continuation | `0x4910..0x4924` | `0x82a8c0..0x82a8d4` | 20 / 8 |
| CE | `0x4b02..0x4c36` | `0x82aab2..0x82abe6` | 308 / 139 |
| CD | `0x4c36..0x4cbc` | `0x82abe6..0x82ac6c` | 134 / 60 |
| Total | Four disjoint code spans | | **496 / 224** |

Every byte in each code span decodes continuously from its confirmed entry or
continuation. Known branches and return boundaries were checked in context;
continuous disassembly alone is not a proof of reachability or ownership.

- The preceding function returns at `0x48c4`. BF's `0x48e2` branch reaches
  `0x4910`; its capped-length branch at `0x48e6` reaches `0x4914`. The final
  reply call is `0x491e -> 0x47b4`, followed by `pop {r4, pc}` at `0x4922`.
  **`0x4924` starts the separate C0 handler**, which is not retired here.
- The preceding negative-reply handler is `0x4ade..0x4b02`, returning at
  `0x4b00`; it is not part of CE. CE's internal common reply tail starts at
  `0x4c14`; its stack restore and return are at `0x4c32` and `0x4c34`.
- CD's internal reply tail starts at `0x4ca8`; it returns through
  `pop {r0, r1, r2, r3, r4, pc}` at `0x4cba`. **`0x4cbc` starts a live command
  enqueue helper**, not more CD code.

No external immediate branch into either internal reply tail was found.
Shared *within a handler* does not mean shared with another function; equally,
absence of an immediate branch does not exclude an indirect interior entry.

Exact span SHA-256 values, in the table's order:

```text
48c6..48e8  09d2f2ea053ef12bdd1198689e3b99b7e911495a0eb7d08b6dc4aff51e2c202e
4910..4924  1e3035e6b16048f808b21acb0abeddbbc92e6cf45b74b8c80d98100be81fa98c
4b02..4c36  be3da8510b5d15c6b1b1d5c6a5d1c49a4578e9b65ca6fb9815c3833b5f8f41e5
4c36..4cbc  96f1172ead170561101c340cbb80f7c4901469613f957de17534d42a392006bf
```

## Preserve BF's shared island and all external pools

BF's apparent `0x48c6..0x4924` extent is 94 bytes, but its 40-byte middle
`0x48e8..0x4910` is **live data for other stock paths**:

| Pool location | Value or contents | Confirmed outside user(s) |
|---|---|---|
| `0x48e8` | `0x1701` | PC-relative load at `0x4508` |
| `0x48ec` | RAM `0x209d30` | Loads at `0x451a`, `0x455e`, `0x4694`, `0x46d0`, `0x4724`, `0x4748` |
| `0x48f0` | Thumb callback `0x82a6d3` (file `0x4722`) | Load at `0x4746` |
| `0x48f4..0x490c` | `m_heart_rate_timer_id` plus padding | `adr` at `0x4750` |
| `0x490c` | RAM `0x208aa0` | Load at `0x487e` |

The timer creator at `0x473e` actually loads the callback/data, takes the string
address, calls ROM `0x13634` at `0x4754`, and returns at `0x4758`. These are
confirmed surrounding instructions, not merely coincidental pointer values.
Keep the entire island, including padding. Its SHA-256 is
`5b95b1fd61372e8d7f7e2a0c9f2a538c9a13a5ad09f3c71ea56bd58c841130bc`.

CE also loads external literals: `0x4b60 -> 0x4ddc` (`0x40015000`),
`0x4b66 -> 0x4de0` (`0x200120`), and `0x4bda -> 0x4de4` (`0x40001040`).
These three loads were the only scanned immediate users of those words, but
the words are outside the handler spans and sit among other stock data/code.
**No extra 12 pool bytes are included in the conservative count.** CE's four
`blx r1` sites (`0x4b7e`, `0x4b94`, `0x4bb0`, `0x4bc6`) obtain the target from
`*(uint32_t *)0x200120`; the runtime target and its wider callers are not closed.

## Direct and stored-pointer reference audit

A read-only Capstone 5.0.7 scan decoded immediate branch/call candidates at
every halfword in each mapped executable region. It checked targets against
**every byte of all four handler code spans**, not just their entry addresses.
Candidate incoming sites were then checked in surrounding instructions.
LE32 absolute pointers, both even and Thumb-tagged, were searched at every
byte offset of the whole stock image. PC-relative literal loads and ADR users
were inspected separately for the pools above.

Only these outside immediate edges into the handler code were found:

| Handler | Incoming call | Original call bytes | Following branch |
|---|---|---|---|
| BF | `0x5bb6 -> 0x48c6` | `fe f7 86 fe` | `0x5bba -> 0x5990` |
| CE | `0x5c1c -> 0x4b02` | `fe f7 71 ff` | `0x5c20 -> 0x5990` |
| CD | `0x5c14 -> 0x4c36` | `ff f7 0f f8` | `0x5c18 -> 0x5990` |

No stored full absolute pointer into those code spans was found. No alternate
external immediate entry or epilogue branch was found in XIP, permanent RAM
code or the overlay. This is **not whole-program entry closure**: computed or
relative pointers, ROM and runtime-installed patches, mutable callbacks,
debug/DMA access and corrupted control flow are outside that result. A scan at
all halfwords can also decode data or instruction second halves; reporting
only confirmed incoming sites does not turn it into a complete control-flow
proof. Preexisting BF writes could already have changed pointers or state.

## Shared callees are not reclaim candidates

The following direct callees have confirmed callers outside these handlers;
retiring diagnostics must preserve them. Locations in the last two columns
are call sites, not new function extents.

| Target | Diagnostic call site(s) | Examples of outside call sites |
|---|---|---|
| ROM memcpy `0x3f848` | `0x4916`, `0x4b28`, `0x4c1c`, `0x4c88` | Widely shared ROM routine; no APP bytes to reclaim |
| Reply helper `0x47b4` | `0x491e` | `0x4806`, `0x4ed0`, `0x6660` |
| RX `0xdcce` | `0x4b4c` | `0x2e36`, `0xbbf6`, `0xedf8` |
| TX `0xdbca` | `0x4b5a` | `0x2e62`, `0xbc28`, `0xee30` |
| `0x135ac` | `0x4b62` | `0xda80` |
| GPIO `0x12bac` | `0x4b76`, `0x4b8c`, `0x4ba8`, `0x4bbe`, `0x4c10` | `0x279e`, `0xbab6`, `0xd7dc` |
| Initialization/recovery `0xd7b8` | `0x4bc8` | `0xd8e4`, `0xdaea` |
| `0x1399a` | `0x4bd6` | `0x27da`, `0x2806`, `0x2812` |
| GPIO `0x12b8e` | `0x4bf6` | `0x27c2`, `0xbaa4`, `0xd7c0` |
| Checksum `0x3fe8` | `0x4c24`, `0x4cac` | Shared ordinary command/reply paths |
| Notify `0x7e30` | `0x4c2e`, `0x4cb6` | Shared ordinary command/reply paths |

Four additional CD calls target two-byte `bx lr` leaves: `0x4c90 -> 0xa852`,
`0x4c96 -> 0xa850`, `0x4c9e -> 0xa858`, `0x4ca4 -> 0xa856`. No other immediate
caller or full stored pointer was found for those leaves. Their eight remote
bytes are **excluded** from the 496/476-byte counts: they are tiny fragments
among other live leaves, including the C4 handler at `0xa864`, and their
indirect entry closure remains unproved. The observed leaves return; do not
attribute a hardware action to these calls without further evidence.

## Conditional aligned regions and remaining integration roots

The following is only a placement-planning allowance: reserve four bytes at
each BF/CE/CD entry, then align each remaining region inward to four bytes.
The return stub's ABI, flags, result and late-entry policy are **not implemented
or approved** by this arithmetic. An entry stub cannot protect interior entry.

| File region | Runtime region | Conditional bytes |
|---|---|---:|
| `0x48cc..0x48e8` | `0x82a87c..0x82a898` | 28 |
| `0x4910..0x4924` | `0x82a8c0..0x82a8d4` | 20 |
| `0x4b08..0x4c34` | `0x82aab8..0x82abe4` | 300 |
| `0x4c3c..0x4cbc` | `0x82abec..0x82ac6c` | 128 |
| Total | 496 − 12 entry allowance − 8 alignment | **476** |

The largest region is 300 bytes; the current coordinator alone has 1106 object
text bytes. It cannot simply be relocated whole into one of these regions.
Relocated functions still need checked call/literal reach, preserved interfaces,
real segment/section geometry and unwind coverage. Keeping unwind input counts
unchanged does not prove an identical final unwind extent after scattering.

Required next boundaries, before any reclamation claim:

1. **Early retirement:** review the narrow callback call at file `0x7b0a`
   (runtime `0x82daba`, original `fe f7 8a f8`) into gate `0x5c22`, before
   dispatcher `0x5882` and its stateful prelude `0x5890 -> 0x8112`. Preserve
   the complete 32-bit length/mode/access contract and other callback paths.
   Do not overwrite four bytes at `0x5c2e`: the adjacent rejection return at
   `0x5c30` is independently targeted. The parallel filter implementation is
   not evaluated or certified by this static audit.
2. **Actual roots and activation ordering:** account for UART callback pointer
   `0x82da7f` stored at file `0x1f308`, its gate, the three dispatcher call sites
   above, and all indirect/retained/patch entries. Install retirement before
   admitting traffic; do not assume a late filter undoes earlier BF mutations.
   Retaining entry stubs is defense in depth, not alternate-entry closure.
3. **Preservation proof:** pin exact stock identity and proposed changes; retain
   all shared pools, next-function boundaries, ordinary Health/command paths
   and shared callees. Execute relevant negative/ordinary paths off-ring and
   verify every byte outside the narrowly reviewed changes is unchanged.
4. **Whole-image placement and release gates:** link all actual hooks together,
   include added filter/relocation/unwind costs, verify final ELF geometry and
   review container/boot/update behavior. Flash/RAM ownership, physical pause/
   resume, fresh motion, health continuity and recovery remain separate gates.

The [settings-writer inventory](UNIFIED_SETTINGS_WRITERS.md) describes why these
diagnostics must be constrained independently of space recovery. Retiring BF
does not itself implement the typed settings revision owner; retiring CE/CD
does not itself close Health producer/result ownership. The benefit of this
audit is a bounded candidate and explicit exclusions, not flash approval.
