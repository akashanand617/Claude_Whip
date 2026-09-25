# Control ingress: original connection identity is still required

2026-09-24/25. The counterexample and implementation audit are off-ring; one
subsequent fixed gateway read is physical and separately archived. Health
remains the unified boot/default and Gesture opt-in. No callback was attached,
wire format changed, sensor command sent or firmware image modified. This audit
prevents an unsafe proposed binding; it does not identify a demonstrated bug in
the installed ring stack.

## Executed counterexample

`tests/test_control_provenance.py` executes the actual compiled ARM mailbox,
owner, dispatcher and mode controller. The retained upstream events and reused
8-bit Bluetooth connection ID are explicit fixtures, not measured stack behavior.

1. Keep two valid old Gesture request fragments, including the unchanged boot
   identity, outside the mailbox. The artificial owner is generation7.
2. Close and logically retire7, then open8 with the same short Bluetooth ID.
   Deliberately do **not** claim the real physical callback-drain prerequisite.
3. Deliver the old frames with their original generation7: both are rejected,
   the complete880-byte owner is unchanged before the next tick, Health stays
   active and the new control owner remains idle.
4. Instead resolve the **current** generation8 at callback delivery: both frames
   pass, and actual C reaches `WD_WAITING / WM_ENTERING / QUIESCE`. This occurs
   for request IDs1 and `UINT32_MAX`, without weakening CRC/boot/fragment checks.

This is software entry, **not physical Gesture**: no STOP, source completion,
hardware transfer, timer call or physical success receipt occurs. A synthetic
source profile and inventory are explicitly provided by the existing owner
fixture; they remain unqualified for the real device.

The wire format does not carry the original connection generation. Its current
contract requires the binding to supply that generation from original event
ownership. Boot identity is constant across connections, and request history
resets at `wd_open`. Consequently, boot/CRC/request checks do not rescue a
binding that mislabels old callbacks. PRIMASK at callback entry can protect
against *later* races, not recover provenance already lost upstream.

Additional cases show that preserving an original timestamp can reject a
9000ms delayed event, while recapturing time at callback entry hides that
delay. It does not fix the3ms generation counterexample. One fragment alone
still leaves Health unchanged; completing the old pair causes the transition.

## Write and CCCD ABI boundaries

The commit-pinned compatible `profile_server.h` (SHA-256
`c3b04ad9a164ce1e7c0e05f3314ebe401027031c2abf479a1e15bb983f4497b0`)
declares the write ABI as follows. The archived copy is in the proof directory.

| ARM location | Compatible declaration | Exact application evidence |
|---|---|---|
| r0 | Connection ID, u8 | UART discards it; not original generation |
| r1 | Service ID, u8 | UART discards it |
| r2 | Attribute index, u16 | UART dispatches index2 |
| r3 | Write-type enum | UART ignores all tested values |
| entry SP+0 | Length, u16 | UART loads this word |
| entry SP+4 | Value pointer | UART loads this word |
| entry SP+8 | Post-process function-pointer **output** | Not loaded by reviewed stock write handlers |

The seventh argument is **not owner context**. Its pointed function has five
arguments: connection, service, attribute, length, value. Its validity and
initialization are compatible-header evidence only: the stock UART, DFU, FEE7
and HID callbacks do not independently establish that installed-stack contract.
Blindly clearing it would introduce a dereference absent from those callbacks.

Actual UART execution at file `0x7ace` is tested for kinds0/1/2/3/0x100/
0xdeadbeef. Only incoming stack words0/4 are read; the supplied seventh output
target stays `A5`. Execution stops at the existing legacy-dispatch boundary,
not inside a real command handler. This is not permission to accept arbitrary
write kinds in the unified service. The compatible enum values0..3 mean request,
without-response, signed-without-response and long; enum storage width is not
fixed by that declaration or by the unrelated general-event layout.

CCCD has four scalar arguments `(conn:u8, service:u8, attribute:u16, bits:u16)`
and returns **void**. A callback cannot return ATT refusal/backpressure.
UART's existing handler only logs in executed paths; it supplies no retained
subscription owner. A new binding needs generation-scoped enable/disable and
send fencing, not copying the FEE7/HID event structures as a universal layout.
Retain neither the write value pointer nor a stack-local event after return
without an independently verified stack retention contract.

## Required next evidence and implementation

Before attaching write/CCCD callbacks, establish either an original per-link
token reaching each invocation, or an actual disconnect barrier proving all old
callbacks and borrowed sends are finished/discarded before short-ID reuse.
No newly invented `current_connection()` provider can meet that requirement.
A protocol-level connection challenge could defend commands, but would require
a reviewed C/Swift format migration and would **not** establish CCCD, send-buffer
or callback lifetime. It is not silently substituted or implemented here.

The exact application boundary remains app `0x8ac` → wrapper `0x156bc` → ROM
`0x4926`, selector `0x107`. The subsequent fixed physical read captures the
gateway and slot: ROM saves the application arguments, null-checks the named
slot, and calls through it. The slot is the stable Thumb pointer `0x80e401`,
whose target equals the installed Upper Stack header's declared execution
address `0x80e400`. This closes the first indirect boundary only. The ring's
target code, selector dispatch, callback provenance and disconnect drain remain
uncaptured. The public Upper Stack differs from the ring's captured header/hash
and cannot establish ring-specific ordering. See [the fixed gateway result](UNIFIED_STACK_GATEWAY_READ.md)
and [GATT resources](UNIFIED_GATT_RESOURCES.md).

A next device investigation requires a new off-ring-reviewed, freshly
coordinated fixed-window plan starting at the established `0x80e400` target,
with identity/configuration checks, repeated equality and verified disconnect.
No target read, sensor start, flash or new connection is authorized by this
document. The legacy read command touches firmware bookkeeping and cannot run
alongside streaming, DFU or another ring client. Existing artifacts remain the
first option.

That [separate fixed reader](UNIFIED_STACK_GATEWAY_READ.md) passed 444 guarded
preflight cases, then completed its one physical session: 122/122 requests,
repeated equality and confirmed disconnect. It read only the 32-byte ROM cap
and four-byte slot beyond prerequisites and never followed the slot. The
preflight's synthetic transport artifacts remain fake; the distinct dated
capture is device evidence. The separate CLI owns cleanup before connection
setup; the earlier 413-case preflight missed an inherited pre-yield cancellation
gap and is historical.

## Verification

`firmware/unified/research-20260925-control-provenance-v1/` passes **107 guarded
tests in22.686s**, zero failures/errors/skips:13 new cases,32 existing owner
cases and62 existing exact-stock transport cases. Ordered collection/execution
contains107 identities and321 passing phases. This is a focused supplement,
not an additional full main or178-test discovery rerun.

Supplement SHA-256:
`6ceacaf36ff5346eb564fcbeb9bb70fedfb99fefe03c02a6f8427518a54a2e24`.
Independent review verified **1178 content hashes** (1134 inputs,41 artifacts,
three reports), four tools, both nested owner reports, repeated objects/stack
reports/artificial ELFs, and preserved prior1130 content hashes. Strict owner
production links still refuse their three absent physical bindings. No full28
relink was needed or claimed; its10798/9520 lower bound and six absent strong
bindings remain unchanged. No release gate closes.
