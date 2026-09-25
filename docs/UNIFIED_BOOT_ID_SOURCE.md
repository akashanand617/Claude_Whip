# Per-boot identity source: exact stock lead, unresolved qualification

2026-09-24/25. Off-ring static/source review and bounded execution of existing
arithmetic instructions only. No device access, peripheral access, target ROM
call, source change, allocation, flash write or production admission.

**No qualified per-boot identity generator is established.** Exact stock does
call the documented RTL8762E `platform_random(uint32_t max)` API during its
startup path. That is a stronger lead than a similarly named ROM symbol, but
the API's exact entropy, initialization, failure and reset/retention behavior
are not established by the available implementation or captures. Discovery
must remain unattached and must not publish a repeated or invented boot ID as
freshness evidence.

## Exact stock path

All file offsets below refer to the 138016-byte stock 3.12.02 image, SHA-256
`b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0`.
Runtime XIP addresses add `0x825fb0`. ROM addresses are stated explicitly.

| Exact instruction evidence | Bounded conclusion |
|---|---|
| File `128ec..128fc`: load `0xffffffff`, `bl` ROM `0x8d3e` at `128f2`, load literal `12a4c = 20c8e4`, store result at base+12 | One 32-bit returned word is stored at RAM `0x20c8f0`; no status or zero check is visible in this wrapper |
| File `12928` calls `128ec` in the selected startup routine at `128fe`; file `808` contains its Thumb pointer `0x8388af` | The wrapper is part of actual stock startup code, not an unused SDK declaration |
| File `9dc..9e6`: load literal `a30 = 20c8f0`, load that word, call `17bfc` | The app initializer seeds its software PRNG with that stored word |
| File `17bfc..17c28` and literals `17c2c..17c38` | Deterministic initializer for a 55-word state region `20db4c..20dc28`, with two cursor words at `20dc28/20dc2c` |
| File `81c..850`, literal `850 = 20dc28` | Add two state words, update a word and both cursors, wrap within the array, return the low 31 bits; no entropy or clock call |
| File `17c28..17c2c`, called at `486` | Separate runtime initializer supplies constant seed 1; it is not a fresh identity source |
| File `e602/e606` and `e68a/e68e` | Selected algorithm paths also feed a generated value back to the seed initializer; the generator is shared mutable algorithm state |

These are decoded stock instruction paths. They do not establish full boot
execution, all callers, all state writers, or the ROM callee's behavior.
Changing the generator or taking extra draws would also change shared state;
this review does neither. Existing optical harnesses deliberately substitute
this PRNG with named values and do not measure its entropy.

The selected normal startup path has **one 32-bit seed**. For a fixed draw and
reseed schedule, two software-PRNG outputs are deterministic functions of that
seed: concatenating them does not establish 64 independent random bits or
reset uniqueness. The existence of a seed-changing API does not establish that
the initial word changes across power-on, watchdog reset or other reset modes.

## Matching SDK evidence and its limits

Sources were read at repository commit
`49301d9b75816ccde1cc9657b827fdadf5736937`, under
`ATC_RTL_BLE_OEPL_8762ESL/`. These are vendor-origin SDK sources hosted by a
third-party project, not source for this ring's proprietary application or a
byte-equivalent ROM patch. No source bundle was copied into this repository.

- [platform_utils.h](https://github.com/atc1441/ATC_RTL_BLE_OEPL/blob/49301d9b75816ccde1cc9657b827fdadf5736937/ATC_RTL_BLE_OEPL_8762ESL/sdk/inc/platform/platform_utils.h)
  declares `uint32_t platform_random(uint32_t max)` and describes a maximum
  permitted result. It does not specify entropy strength, cross-reset
  independence, readiness, failure signaling, startup ordering or concurrency.
- [system_rtl876x.c](https://github.com/atc1441/ATC_RTL_BLE_OEPL/blob/49301d9b75816ccde1cc9657b827fdadf5736937/ATC_RTL_BLE_OEPL_8762ESL/sdk/src/mcu/rtl876x/system_rtl876x.c)
  lines 379–394 define a 32-bit `random_seed_value` and initialize it with
  `platform_random(0xffffffff)`. `common_main` calls that initializer at line
  423 before the selected app startup; lines 704–708 register the SDK startup
  callbacks. This agrees with the selected stock instruction pattern, without
  proving equality of all startup or ROM behavior.
- [rom_symbol_gcc.axf](https://github.com/atc1441/ATC_RTL_BLE_OEPL/blob/49301d9b75816ccde1cc9657b827fdadf5736937/ATC_RTL_BLE_OEPL_8762ESL/sdk/lib/rom_symbol_gcc.axf)
  is byte-identical to the archived symbol file. It assigns `platform_random`
  Thumb address `0x8d3f` and names RAM symbols
  `init_true_random_generator = 0x200854` and
  `get_true_random_number = 0x200858`. The two RAM addresses are **not documented
  executable entry points** here. Their names do not establish their contents,
  types, initialization, current targets or hardware entropy semantics.
- [os_sched.h](https://github.com/atc1441/ATC_RTL_BLE_OEPL/blob/49301d9b75816ccde1cc9657b827fdadf5736937/ATC_RTL_BLE_OEPL_8762ESL/sdk/inc/os/os_sched.h)
  describes system ticks since scheduler start and warns about overflow. A
  scheduler tick is elapsed-time state, not a non-repeating reset identity.
  `platform_utils.h` separately describes a 26-bit vendor timer driven at
  40 MHz. Neither timer supplies a documented persistent incarnation counter.

Even an independent random source would give a collision probability, not an
absolute no-reuse guarantee. This review does not choose a weaker freshness
contract, invent a collision-free ID, borrow a device address as a boot epoch,
or propose a flash-backed counter. A fixed device address, code address,
build tag or reset-reason category alone cannot distinguish repeated boots.

## Reset versus DLPS

The [captured reset/resume review](UNIFIED_ROM_RESUME_EVIDENCE.md) remains the
controlling qualification. ROM `0x4efe` tests an AON bit before the normal boot
path; the observed resume pointer selects `0xd22c`. That function calls an
unread indirect restore callback and `os_task_dlps_return_idle_task` at
`0x135b8`. If those return normally, a captured continuation leads back toward
first-boot initialization. Non-returning restoration semantics remain unread,
including the literal at `0xd478` needed to identify the callback slot.

Consequently, the startup seed wrapper cannot yet be treated as an exactly-once
boot-ID owner. A genuine reset must invalidate old boot/session receipts; a
retained continuation must preserve a coherent identity and all state that
uses it. No such owned state, publication ordering or reset/retention contract
has been established. Unchanged gap digests are not a retention test, and a
reset-reason value is not itself a unique boot number.

## Finite missing evidence

The smallest unresolved entropy boundary is the **actual implementation reached
by stock's call to ROM `0x8d3e`**, together with its exact literal/callee closure
and initialization contract. No saved structured `address`/`data_hex` window
under `firmware/research` covers that entry or either named RNG RAM address.
The public matching header supplies the signature but not that implementation.
The distance to the next exported ROM symbol is not a function-size proof.

Qualification needs an exact matching source/implementation establishing:

1. What supplies each returned word, when the source becomes ready, how failure
   is represented, and whether repeated calls/reset modes can reproduce state.
   Any hook/patch selection must be established from that code; no target or
   callback ABI should be inferred from the RAM symbol names.
2. A reset-versus-resume initialization boundary with the outstanding context
   restoration semantics closed, plus owned storage and immutable publication
   lifetime for the ID and the dispatcher state that consumes it.
3. A reviewed non-reuse/freshness contract across real resets and reconnects.
   Two draws, a nonzero result or a finite repeat test cannot by themselves
   prove this property.

These are source/code proof requirements, **not a device-read plan or authority
to invoke ROM, read RNG state, inspect MMIO, sample a sensor or reset the ring**.
No substitute generator is added. The existing discovery encoder still only
checks that caller-provided 64-bit identifiers are nonzero.

## Reproducibility witnesses

SHA-256 of the exact remote source bytes read for this review:

| Source | Bytes | SHA-256 |
|---|---:|---|
| `platform_utils.h` | 3540 | `045dd763344396181834644e89a66c96e09a797606d6a7deb2b3e8e91c695d93` |
| `system_rtl876x.c` | 42412 | `d784cc2394b0a2bcc4d39f6ffcdcf4efa655091105238394565afc075968ab79` |
| `os_sched.h` | 6939 | `d0b16b2a1a6dc03f7f4bd7388305b50ee2994f1acfd0c7f739c7a807c9aafadb` |
| `rom_symbol_gcc.axf` | 14755 | `6f5a59f6444c01328808ac148b9c60771410196ab3b57e08fc8ff90525934247` |

Stock slices: `81c..854` hashes to
`77f3ada0492404f9229f2a9da8a978475f886dfe2beed68acd2232f1fd5596e2`;
`128ec..12962` to
`cb1d8d06ee345cad5e1e5ea8368c3063985c218788d93fceb337724a18caf1cb`;
`17bfc..17c38` to
`9d80b47d8976126ed61fe218e55f1a87e9196a37f82160c6186af17a9227c363`.
Bounds are exclusive and include the stated literals where applicable.

A one-off, in-memory Unicorn check executed only seed instructions
`17bfc..17c28` and generator instructions `81c..850`, with reads restricted to
their three seed literals, one state literal, 228 bytes of fixture state and
32 bytes of fixture stack. It executed no ROM, MMIO or peripheral boundary.
Each of four seeds was initialized twice and produced the same four results;
for seed 1 these were
`1447534768, 1904222667, 1603566409, 2107693160`.
This supports the deterministic arithmetic interpretation only. It is not a
new archived pytest checkpoint, entropy test, cross-reset observation or proof
of physical Health behavior. Existing build/test manifests are unchanged.
