# Optical read provenance and error propagation

Later implementation: [optical work lifetime and retirement](UNIFIED_OPTICAL_WORK.md)
adds actual C around the original sample reader and software-buffer clear,
with compiled ARM/stock execution tests. It does not turn a zero return into
measurement provenance or complete the physical Health binding. The analysis
and build counts below remain the preceding audit's historical record.

2026-09-24. **Off-ring original-code evidence, not a completed source binding.**
No ring connection, sensor command, firmware change or production capability.
Installed V2 optical-off is unchanged. Unified Health remains boot/default;
Gesture remains opt-in and unavailable until the physical/integration gates close.

This follows the [HR result guard](UNIFIED_HR_RESULT_COMMIT.md). That guard's
`measured` argument cannot be supplied by stock's top-level return code, cached
ready bit or parsed/status-read flags: the executed cases below disprove those
shortcuts. The guard remains unattached; this audit does not create a substitute
source-provenance flag or approve any real job identity.

## Actual code replacing former fixture boundaries

`whip/fwoptical_acquisition.py` extends the existing optical-dispatch harness.
It accepts only stock 3.12.02, SHA-256
`b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0`.
All addresses below are file offsets with runtime bias `0x825fb0`.

| Stage | Original instructions now executed | Relevant behavior |
|---|---|---|
| Acquisition wrapper | `0x10f56` | Calls status/parser, but its final zero is not a successful-read receipt |
| Status cache helper | `0x10834` | Ignores status-reader return and sets `STATUS+0x1b` to 1 |
| Status register reader | `0x1174c` | Reads register 2, three or four bytes; copies zero-initialized/partially delivered bytes even on failure |
| Metadata parser | `0x106e2` | Ignores metadata-reader and channel-control failures, sets `STATUS+0x18`, returns zero |
| Metadata reader | `0x1181c` | Selected layout-one path reads 17 bytes at register 9 or 10 and does detect `UINT32_MAX` |
| Channel controls | `0x11f3e` | Reads three registers per channel; returns only the first read's status, which the parser ignores |
| Classification | `0x1085a` | Actual short branch returns 2 when the selected buffer flag is zero; deeper wear paths are not admitted |
| Optical read wrapper | `0xedda` → `0xdcce` → `0xdc40` | Takes existing mutex, issues RX, maps read failure to `UINT32_MAX`; mutex-release failure is ignored |

The selected layout-one fixture is **not a measured live ring configuration**.
Synthetic buffer/status/classification/channel pointers occupy test-only RAM,
not approved ring allocations. The low-level receive at `0x1371e`, mutex and
bus-status/delay boundaries remain explicit substitutes. Its fixture reports
bytes delivered and return status independently. This does not execute optical
physics, real timing, full sample acquisition or a real RTOS.

The eight pre-processing reads in this fixture are:

1. Register 2: three bytes for sensor-kind `0x10`, four for `0x30`.
2. Register 9 (`0x10`) or 10 (`0x30`): 17 metadata bytes.
3. Channel zero: registers `0x42`, `0x40`, `0x43`, one byte each.
4. Channel one: registers `0x46`, `0x44`, `0x47`, one byte each.

These are not proof of fresh PPG samples. Ready state is still explicitly
synthetic, and the actual HR/SpO2 algorithms remain intercepted.

## Findings that constrain implementation

`tests/test_fwoptical_acquisition.py` adds **29 cases**. With the preceding 32
dispatch cases, the focused run passed **61 tests in 1.82 seconds**, zero skips.

- Injecting failure at each of the eight receives still yields zero from
  `0x10f56`. The real read wrapper reports `UINT32_MAX`, but callers lose it.
- Status failure copies zero-initialized or partially received status bytes,
  then `0x10834` marks the status as read. Thus a missing error bit can itself
  be the consequence of a failed read; it is not evidence of a healthy sensor.
- Conversely, a successful read carrying status bit `0x10` causes `0x10f56`
  to return `UINT32_MAX`. The physical meaning of that bit is still unknown;
  it must not be renamed "I2C failure".
- A failed metadata refresh leaves the old packed value in place, after which
  the parser converts it and marks parsing complete. In the fixture, retained
  `0x0203` becomes 103 despite the failed read.
- With parsed/status-read flags already set, repeated actual acquisition calls
  return zero without any read or buffer update. There is no acquired-job or
  sample-generation identity in these selected paths.
- Mutex-unavailable, bus-not-ready and bus-busy cases also let processing reach
  real HR result stores under cached-ready/algorithm fixtures. All nine modeled
  reads can fail with zero bytes delivered while the original processor stores
  the fixture HR value 72 and result state 2. This is **not** an observation of
  a false health value on the physical ring.
- Unknown execution, literal islands, layout-zero floating conversion, deeper
  wear classification and the real peripheral body remain rejected. Image
  mutation, unreviewed sensor kind and short fixture data also fail closed.

### Correction: completion's register operation is RX, not TX

`0x11216` clears four status bytes and calls **read** wrapper `0xedda` with
register `0x40` and a 24-byte zero-initialized destination on the stack. Executed
RX instructions confirm that operation is not a control write or STOP request.
The earlier dispatch harness's "completion control write" boundary label was
wrong and is corrected. Its original limitation (no actual transfer modeled)
and the finding that it does not clear the published HR cache remain valid.
`0xee12` / `0xdbca`, not `0xedda` / `0xdcce`, are the reviewed write path.

## Consequences for the real binding

Do not set the HR guard's `measured` argument from any combination of return
zero, plausible value, optical state 2 or the cached flags examined here.
Likewise, stamping a current job ticket at dequeue cannot identify the work
that originally filled a retained buffer.

Required next attachment evidence is the **actual sample-producing path** and
buffer retirement: its complete read outcomes/byte counts, acquisition identity,
algorithm-consumption identity and association with each logical Health job.
Failure must remain latched for that original acquisition through every result
and publication sink. A later successful metadata read cannot rehabilitate old
or failed sample work. Retire old buffers/queued work before admitting a new
generation; preserve unrelated steps/sleep state and current user settings.
This needs real serialization and complete producer/result coverage, not a new
boolean inferred from a wrapper's return value.

Static follow-up locates the next bounded code target: `0x10610` calls
`0x11994`, then writes the readiness byte at `STATUS+0x1a`. Selected inspection
of `0x11994` shows register-`0xfe` write and register-`0xff` read calls, beyond
the metadata path executed here. These routines have **not** been admitted to
this new harness; their cursor/error/buffer behavior must be executed and
reviewed before claiming a sample-producing source or safe buffer retirement.
No new on-ring diagnostic is needed to start that analysis: the bytes are in
the pinned stock image already.

No C firmware component or memory size changed in this continuation. Current
build evidence is maintained in [the resource handoff](UNIFIED_RESOURCE_BUDGET.md).
Full stock attachment, memory ownership/recovery, genuine 25 Hz motion/model
qualification and physical health/steps/sleep continuity remain open.

## Guarded build record

`firmware/unified/build-20260924-optical-acquisition-v1/`: **2734 passed in
170.36 seconds**, zero skips/failures/errors/xfails. All **239 hashes** checked:
165 inputs, 71 artifacts and three reports. Manifest SHA-256:
`2de14d67ced3621281a69c615f1db9bc04571328d712373b831e99fa5629503b`.
Both ARM ELFs exactly match the prior HR-commit build. Components remain
9352/9520 configured bytes (168 remaining), combined dispatcher/frame/fence
796 bytes. Neither figure approves ownership or complete integration fit.
No stock hook, source-provenance flag, recovery approval or OTA image was added.
