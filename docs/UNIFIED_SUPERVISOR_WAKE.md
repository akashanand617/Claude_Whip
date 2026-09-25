# Conditional qc_app idle-wait supervisor candidate

Latest [control-owner integration](UNIFIED_CONTROL_OWNER.md) now provides the
real C `wuw_supervise` and runs it through this stock-loop path, dispatcher and
coordinator. Three strong physical bindings remain absent. The 31 isolated
tests described below deliberately retain their proof-counter provider; they
are distinct from the new 32-case integrated witness. The wrapper object itself
still has an external supervisor reference. Neither suite proves elapsed
cadence, owned storage or physical continuity; no production hook is attached.

OFF-RING only. The new unattached `stock_supervisor_wait.c/.h` can remove
qc_app's unconditional infinite idle wait without creating another task or
timer. It does **not** establish a periodic deadline, a real supervisor binding,
physical transition completion, Health continuity, an owned allocation or a
complete image fit. Health remains boot/default; Gesture remains opt-in. No
stock file, installed image, production hook plan or production source list is
changed here. Nothing described here is installable.

## Exact original path and finite change

The reference is `firmware/rt02cr-stock-3.12.02.bin`, 138016 bytes, SHA-256
`b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0`.
File offsets below map to executable addresses by adding `0x825fb0`.

The loop loads the existing semaphore from `0x208c90`. At `0x1356/0x1358`,
`movs r1,#0; mvns r1,r1` supplies `UINT32_MAX`; its call at `0x135c` goes to
ROM `0x13360`. At `0x1360/0x1362`, a zero return branches directly back to
`0x1356`, without entering the stock body. Any nonzero word enters the body,
then returns to the wait at `0x139a`. Merely changing the wait constant would
leave the zero-return path unable to run a supervisor.

The test changes exactly the four-byte BL at `0x135c` (`ecf728d8`) **in emulator
memory only**, redirecting it to the compiled C `wuw_take`. The original wait
constant, handle load, compare/branch and body remain byte-for-byte unchanged.
The complete mapped stock image is compared with the pinned input plus that
single edit. No edited image is written to disk.

`wuw_take(semaphore, original_wait)` requires a nonnull semaphore, the original
`UINT32_MAX` argument, thread mode and enabled interrupts. It requests 100 ms
from the same declared ROM take entry, checks context again, invokes the
required `wuw_supervise`, checks context again and returns the **original full
take word**. Invalid preconditions cause no calls; unexpected post-call context
returns zero without repairing/changing the interrupt mask. It is not an
invalid-context recovery policy.

## Source-supported semaphore contract, not captured ROM execution

The matching SDK's [`os_sync.h`](https://github.com/atc1441/ATC_RTL_BLE_OEPL/blob/49301d9b75816ccde1cc9657b827fdadf5736937/ATC_RTL_BLE_OEPL_8762ESL/sdk/inc/os/os_sync.h)
declares `os_sem_take(void *, uint32_t wait_ms)`: zero requests nonblocking
operation, `0xffffffff` waits indefinitely, and other values are milliseconds.
Its Boolean result reports successful or failed acquisition; **false does not
uniquely identify timeout**. `os_sem_give` likewise reports success/failure.
The stock create call at `0x13ce` supplies initial/max counts 1/1, matching the
header's binary-semaphore contract. Repeated signals can therefore coalesce;
they are not a counted work-item receipt. Header SHA-256:
`b3e267cd49cbea1b1a018ab12991be296ea0cd60c155f22025be0715f7d414c0`.

The matching archived ROM symbol map names take/give at Thumb addresses
`0x13361/0x13389`. No admitted saved capture used here supplies the ROM bodies
at `0x13360/0x13388`. Those operations remain explicitly named contract
fixtures. The tests do not execute their tick conversion, timeout, semaphore
object, scheduler or interrupt internals. A valid owned semaphore and its
lifetime remain prerequisites. A repeated immediate failure could still spin;
requesting 100 ms is not evidence that 100 ms elapsed.

Original wake helper `0x1178` reads the same handle and calls `0x13388` only if
nonnull. It returns without acting on give's result. Its instructions are not
changed. This preserves the selected stock wake path, not a guarantee that a
token was delivered or that task scheduling occurs within a bound.

## Executed witness and explicit boundaries

`tests/test_supervisor_wake.py` builds the actual candidate for Cortex-M0+ with
the existing flags and artificial proof linker script. Objects and the ELF
reproduce byte-for-byte. Input/tool/object/stack-usage/ELF snapshots are checked
at build boundaries and test teardown. The production ELF inspector rejects
the artificial layout.

The strong `wuw_supervise` symbol remains undefined in the candidate object.
Omitting its provider makes the link refuse; there is no production weak or
no-op fallback. Tests link a separately named **proof-only provider** that
increments a counter in artificial RAM. It is not `wd_tick`, the coordinator,
an actual owner binding or a Health operation.

Each stock loop/waker witness and the compiled wrapper share one ARM address
space. The seven body callees are named boundary fixtures, with exact original
BL return-address checks; the intervening original stock instructions execute:

| Call site | Original target | Marker before call |
| --- | --- | --- |
| `0x1366` | `0x657c` | 0 |
| `0x136e` | `0xcd60` | 1 |
| `0x1374` | `0x905c` | 2 |
| `0x137a` | `0x1202` | 3 |
| `0x1382` | `0x343a` | 4 |
| `0x138a` | `0x1279e` | 6 |
| `0x1392` | `0x3fd2` | 7 |

The final marker is 8. No body callee's implementation or Health algorithms
are claimed executed in this witness. The loop's earlier prologue/setup is
also explicit fixture state, including its preserved `r5=3`.

The focused run passes **31 tests**. Coverage includes original-versus-edited
body trace/marker equality for zero and four nonzero return words; preservation
of the complete return word; a persistent six-iteration failed/successful-take
sequence; null/wrong-wait/exception/masked preconditions; altered context after
each external call; original null/non-null wake-helper behavior; required
provider link refusal; and rejection of unadmitted execution/data accesses.

A deliberately blocking body fixture stops at the second body call after one
supervisor poll, leaving the next take/poll unexecuted. Thus this change can
only enable a conditional **idle** poll; it cannot preempt a blocked body.
The zero-return cases are failed-take fixtures, not physical timeout evidence.
No elapsed scheduling cadence is modeled or asserted.

With the reviewed toolchain, the candidate object has 72 text bytes plus 8
unwind bytes, no writable globals, and compiler-reported local stack use of
16 bytes. These are not a complete linked increment, nested stack budget or
approved memory placement. The mandatory real provider has additional costs.

## Remaining finite obligations

An eventual attachment needs an owned, serialized real supervisor provider
that obtains fresh time and services dispatcher/lifecycle work without
inventing physical receipts; reviewed semaphore validity/lifetime and runtime
wait semantics; a bound on the supervisor and every stock body handler;
cross-task ingress ownership; and full code/RAM/stack placement. The existing
physical-source/STOP/resume, Health/steps/sleep and recovery gates remain open.
This test does not add a timer, task, physical receipt or production provider.

Pinned selected stock slices, SHA-256 (exclusive end offsets):

| Slice | SHA-256 |
| --- | --- |
| `0x1178..0x1188` wake helper | `79b40c2fd699cbadf827f169ac3147a95b54aacc40219989fa31b7e50f1e8d34` |
| `0x1350..0x139c` loop | `970d303ce79fc7f517e8626ef7b9e57a5cfb2520573ba81310c6b5d5243f1165` |
| `0x13c6..0x13d2` semaphore create arguments/call | `34fcbdf62160ff1f8aebe002ff01b6a499e0a171bd80e045d343551a7c72e404` |
| `0x13ec..0x13f0` handle-base literal | `1898aacbd5329ac638180d331e7e0dbdd0a9cc7ef9a43931dfed0ae6fb1fd962` |
