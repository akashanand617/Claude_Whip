# Exact-stock Bluetooth transport binding — offline evidence

2026-09-23. Continues [command ownership](UNIFIED_DISPATCH.md) toward the unified
Health-default firmware. **No Bluetooth operation, physical phone deployment,
image patch, registration or flash was performed.** The installed ring remains
V2 optical-off; production unified capability is still unavailable.

The preceding turn was progress: commands and replies were integrated with the
portable adapter. This turn reaches the original stock registration/send wrappers
with compiled ARM code, and replaces earlier queue inferences with executable
counterexamples. It does not close the stock-linked or physical safety gates.

## Evidence boundary

`whip/fwtransport.py` requires the complete stock image hash:

```text
firmware/rt02cr-stock-3.12.02.bin
b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0
```

All code offsets below are file offsets; runtime = file + `0x825fb0`.
RAM/ROM addresses are identified explicitly. Execution is restricted to listed
instruction ranges and two named compiled shim functions. Other calls fail
closed; peripheral memory is not mapped. ROM stack calls, logging, queue posts
and delays are explicit mocks. Setup's separate client registration and TX
allocation are boundary mocks, not a full boot. Argument/state effects are real
application instructions, but radio delivery, RTOS timing, buffer ownership and
recovery are not emulated or measured.

The harness checks instruction bounds, call budget, restored stack, callee-saved
registers, stack canary and fixture buffer spans. Its broad fixture RAM mapping
is not a real memory reservation or exhaustive RAM-ownership proof. Initial
stock RAM copies follow the existing exact-image harness. Full-image mutation
and calls outside the reviewed transport ranges are rejected.

## Registration and ABI

| Boundary | Exact stock evidence |
|---|---|
| Setup `0x76b8` | Calls server initialization with **5**, then all five service-add functions; returned IDs stored at RAM `0x209e1b..0x209e1f` |
| UART add `0x7b40` | Database `0x1f25c`, 168 bytes; callback addresses from `0x1f304`; returns assigned ID or `0xff` |
| Stack add wrapper `0x15824` | Callback structure passed **by value**: read pointer in r3, write/CCCD pointers on caller stack |
| ROM boundary `0x4926` | Stack service `0x3102`, with explicit service-ID and result-byte output pointers |
| UART app callback | Stored at RAM `0x209e44` only after successful UART registration |
| General callback registration `0x1587c` | Stack service `0x3104` receives common callback `0x82ced9` (file `0x6f28`) |

Tests execute the five original registration functions, not five mocked add
wrappers. The ROM mock supplies assigned IDs/results. On each individual
registration failure, setup stores `0xff` for that service and still proceeds
through the others; this is not successful service recovery.

**There is no declared spare sixth service slot.** The new service requires a
reviewed initialization change and additional stack memory, not merely another
call to add a service. No such patch/allocation is approved here.

The six-entry UART database uses 28-byte entries. Its write callback `0x7ace`
loads length and data pointer from incoming stack words 0 and 1, respectively;
attribute index is r2. Type in r3 is ignored. For attribute 2, it calls the legacy
dispatcher boundary, where these tests stop. This is **not** a harmless-command
claim. Null data returns `0x40d`; unsupported index returns `0x40a`.

The CCCD callback `0x7b22` only logs in these executed paths and writes no retained
subscription state. Stack enforcement is outside this test. The dormant read
branch at `0x7ac0` ignores the requested read offset, returns pointer `0x208528`
and subtracts one from a stored byte length; zero becomes 65535. Its index 7 is
outside this service's registered six attributes. It is neither an available
discovery characteristic nor a bounded descriptor implementation.

## Do not import an unverified SDK structure layout

The original general callback `0x6f28` reads the event ID as a byte at offset 0
and a send-completion cause as a halfword at offset **8**. A compatible candidate
layout uses a short enum and a union aligned at offset 2. The mirrored vendor
[profile header](https://raw.githubusercontent.com/atc1441/ATC_RTL_BLE_OEPL/49301d9b75816ccde1cc9657b827fdadf5736937/ATC_RTL_BLE_OEPL_8762ESL/sdk/inc/bluetooth/profile/profile_server.h)
declares the callback fields, by-value service callback structure and send API.
Compiler-dependent layout must still be matched against this exact firmware.

A negative test builds a plausible four-byte-enum event with failed cause 9 at
offset 10. Stock instead reads the zero attribute field at offset 8 and follows
its **success** wake path. Blindly copying a host/default-compiler structure can
therefore turn a failure into apparent success. No complete ROM callback-packing
implementation is claimed: untouched conn/service/credit fields remain inferred
from the compatible header, not established by this callback's reads.

The stock success branch just calls a global TX wake helper; it does not check
the supplied connection, service, attribute or an application sequence. It is
not a completion receipt for an individual unified frame. No new callback parser
or old-connection fence is installed by this work.

The [attribute header](https://raw.githubusercontent.com/atc1441/ATC_RTL_BLE_OEPL/49301d9b75816ccde1cc9657b827fdadf5736937/ATC_RTL_BLE_OEPL_8762ESL/sdk/inc/bluetooth/profile/gatt.h)
also agrees with the observed 28-byte table shape, UUID/value flags and read/write/
notify permissions. These pinned vendor-source mirrors aid interpretation;
neither source is proof of the ring's exact ROM build or physical stack behavior.

## Executed legacy queue hazards

These now run actual producer, wake, drain and send instructions, with only the
stated ROM boundaries mocked:

1. **Full appears empty.** Enqueuing 128 undrained 16-byte packets through
   `0x7e30` wraps write to read. `0x7e64` then sends nothing. The 129th enqueue
   overwrites slot zero and is the only packet subsequently sent.
2. **Failed wake remains latched.** `0x7dde` sets busy before `0x8e8` posts the
   message and event queues. Either post can fail; busy stays set. Later enqueue
   and `0x7dfe` send-completion wake do not post again while that byte remains set.
   This proves the failure path, not that no other recovery ever clears it.
3. **Old data has no connection generation.** Queue a frame, change the fixture's
   current connection ID, then drain. `0x7dc4` sends that old frame using the new
   ID. No claim is made about the hardware's disconnect-time queue clearing;
   that fence must be proved separately rather than assumed.
4. **Retry exhaustion drops pending data.** Returns other than exactly 1 cause
   twenty delay/retry increments; the 21st failure sets read=write and discards
   the pending small queue. Returns 0, 2 and 255 are tested.
5. **Disconnected enqueue is silent.** The enqueue helper returns without owning
   or sending data when the connected-state predicate is false.

Thus calling the legacy queue and immediately declaring `wa_sent(..., true)`
would still be incorrect. Its nominal depth does not supply bounded ownership,
backpressure or a generation fence for the new protocol.

## Concrete, unattached call shim

`firmware/unified/stock_transport.{c,h}` implements just two exact-stock calls:

- `wg_stock_add`: accepts a reviewed database's entry count, checks nonzero and
  16-bit length bounds, passes the three callback words by value, and leaves the
  output ID `0xff` on any failure. Null pointers, even nonzero callback addresses,
  anomalous result bytes and an invalid assigned ID fail closed. Multiplication
  by 28 replaces a runtime remainder calculation; no implicit division helper
  or global state is needed.
- `wg_stock_notify20`: submits exactly 20 bytes to the explicitly provided
  connection/service/attribute through stock wrapper `0x158ee`, notification type
  1. It rejects invalid sentinel IDs/null data and accepts only result byte 1.
  It never calls the legacy queue, retries or treats acceptance as delivery.

The stock wrappers return the byte written through the ROM's result pointer,
not the ROM call's register return. Tests deliberately give those different
values and execute the original wrappers to verify the shim's ABI.

There is no new UUID, database, callback registration, stack-capacity increase,
production caller or dispatch attachment. Callers still need proven identity,
table/buffer lifetime, subscription and MTU, stack-thread serialization, send
credit/ownership and disconnect fencing. The shim itself cannot establish them.
Do not call these stock addresses on the installed V2 or other firmware.

## Validation and remaining work

Scoped suite: **62 passed, zero skips**. This includes the original stock paths,
all five service failure positions, enum-layout counterexample, queue failures,
and compiled ARM shim calls through the unchanged stock wrapper to the explicitly
mocked ROM boundary. `tests/test_fwtransport.py` is part of the guarded builder.

The first scoped compile exposed an unintended `__aeabi_uidivmod` dependency and
failed the strict linker's writable-data assertion. Changing the shim API to
bounded entry counts removed that dependency and passed the same guard. No linker
assertion was weakened; the failing setup was not accepted as a passing proof.

### Completed guarded build

`firmware/unified/build-20260923-transport-v1/` passed **936 tests in 85.03 s**,
zero failures/errors/skips. Ordered collected/executed identities and phases
match. All ten components and four support units were compiled twice identically,
and the artificial-address test ELF was linked twice identically. All **120
hashes** were rechecked: 88 source/evidence inputs, 29 artifacts and three proof
reports. `flashable`, `stock_linked` and `hardware_access` are still false.

- Manifest SHA-256:
  `b30221bdfa1acb91b65fb18b93d960be7f925b69be0b36acd55b5f3ebc2f89d6`.
- Test ELF SHA-256:
  `dc03e4684311a1cefd719403268ff2dbed247ec49b6d9b2f912f246d6e5537c4`.
- The new shim has 176 `.text` bytes, 16 `.ARM.exidx` bytes and no unresolved
  symbols. Its absolute calls still require the exact reviewed stock base.
- Ten components total 8242 `.text` bytes before actual hooks, table, transport
  ownership, helpers/alignment/metadata. This is not final fit or placement proof.
  Local shim stacks are 40/24 bytes excluding stock/ROM callees; not a complete
  stack budget. No global or heap allocation is added by the shim itself; the
  underlying stack's registration resource use remains unresolved.
- `git diff --check` passed. No Swift or production client changed, and no iOS
  simulator was rerun. Its previous 58-test result and workflow 3's separate
  194 legacy regressions remain historical, not additional tests in this run.
- No unified image, stock patch, UUID registration, commit or push was made.

Reproduce with the isolated proof dependencies, Clang/Swift and pinned Zig 0.15.2:

```sh
python -m probe.unified_build --zig /path/to/zig-0.15.2 \
  --output /new/path/to/offline-proof
```

Earlier build manifests remain records of their then-current inputs, not of the
current builder/test source.

Next: establish actual stack callback packing/lifetime/credits and a single
serialization domain; construct the reviewed separate service and bounded
discovery descriptor; attach firmware/app transport with genuine generation
fences. These still depend on approved placement, RAM ownership and stack resource
capacity. The source/health/steps/sleep/recovery gates in
[workflow 3](UNIFIED_WORKFLOW_3.md) remain open. No unified image is ready to flash.
