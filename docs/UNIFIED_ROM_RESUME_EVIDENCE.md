# Captured ROM reset/resume: bounded independent review

2026-09-24/25 evidence, reviewed entirely off-ring. No device connection,
firmware/source edit, target execution, PDF access, allocation approval or
release-gate change. This document records byte/transcript verification and
instruction-level control-flow analysis, not a complete ROM execution proof.

## Decision

The captures establish a real bit-1-selected reset path through the observed
resume pointer into ROM `0xd22c`. They do **not** establish that `app_pre_main`
runs only once, that this path cannot reach first-boot initialization, or that
the candidate RAM is owned and retained through DLPS.

The important qualification is an explicit return continuation: if the unread
resume/context-restoration callees return normally, the captured instructions
return through `0xd242 -> 0x4efc -> 0x4f12`, after which reset initialization can
reach `bl 0x4e36` at `0x4fd4`. Avoiding that continuation requires non-returning
context-restoration behavior which has not been captured. This is a conditional
control-flow fact, **not** a claim that a real DLPS wake takes that continuation.

## Archives checked

The three new directories are under
[`firmware/research/2026-09-24`](../firmware/research/2026-09-24/).
The independent check verified each directory's `SHA256SUMS`, paired request/
reply counts, request CD01 fields/address/length/checksum, unredacted response
checksums, absence of abort/unexpected-notification events, and final
`disconnected {confirmed: true}` followed by `completed` naming the capture hash.
It rebuilt the raw windows from both transcript passes and compared them to
the saved capture bytes and embedded hashes. It also checked the exact selected
diagnostic order after the 95-transaction prerequisite prefix and the seven
configuration/idle postcheck transactions. This was not another live read or a
fresh pytest run.

These are installed-V2 sessions with sampled critical-site identity and the
recorded configuration/declared ROM target, not complete on-device firmware
attestation or a stock-Health execution trace.

| Session | Requests / replies | Capture SHA-256 | Transcript SHA-256 |
|---|---:|---|---|
| `ram-ownership-followup` | 274 / 274 | `f038f9ad7e716617d8e5ac82867d1760cbe4ca77cc7a28de71dfac42973a681f` | `2230112b8575d2b5eb8d1b1369142cab4c7a7e09c9ee0fd3d9a28b49b444d286` |
| `ram-ownership-resume-pointers` | 108 / 108 | `7f5190fd069874aa4869d629f36a060f4eb05799a7937074ff3154d6f5db8a02` | `01f4310bbd3a52d4fd9cfe8982cbde6de276a506d7b35f40ada6d05eca6f2870` |
| `ram-ownership-resume-code` | 178 / 178 | `fbff5caa62754c03b7d7bdda0f0da11378baddca43e3337bbdf6651690d26851` | `e6fa3d00963d211d23fe8bc44ba00b4093de0d7ac3550016bdf27086c9c9199d` |

The pinned older
[`rom-integration`](../firmware/research/2026-09-23/rom-integration/README.md)
capture and transcript hashes also match:

- Capture: `d02cc3582a789d933e1be09fa1bbec05ade7a193508418149f145dc12df3b05b`.
- Transcript: `22d85dc403dda89e6bc6cfea605200d05d8201521d58b0ae83ee597235e39f8f`.
- Both reconstructed `0x4a78..0x53a4` windows are identical: 2348 bytes,
  SHA-256 `9b9903350dccd323195fae0a971f2297789dee4e7f9374a699612113a2e123da`.
- The older transcript ends in confirmed disconnect/completion too. This review
  rebuilt the selected reset/boot window, not every other older ROM window.

## Actual recorded values

All values below were rebuilt from repeated, matching raw responses.

| Address / field | Value | Bounded meaning |
|---|---|---|
| Vector word 0 | `0x203800` | Recorded initial stack pointer |
| Vector word 1 | `0x4eff` | Thumb entry at ROM `0x4efe`, inside the older captured window |
| NMI / HardFault | `0xd6d7` / `0x101` | Recorded vector entries, not executed |
| SVCall / PendSV / SysTick | `0x10fd5` / `0x25b` / `0x110a5` | Recorded vector entries, not executed |
| `0x2000f0` | `0x40eb` | First-boot hook's current value; target body `0x40ea` unread |
| `0x2000f4` | `0x400` | Recorded word; no additional interpretation |
| `0x2000f8` | `0xd22d` | Current resume pointer; separately rechecked twice before the code read |
| `0x2000fc` | `0xe8762` | Recorded word; no additional interpretation |
| `0x20014c` | `0xb9b3` | Early reset hook's current value; target body `0xb9b2` unread |

The new ROM code window is exactly `0xd200..0xd400`, 512 bytes, SHA-256
`b235092f1cc5e3a959a98a278b6f9b646af621ef5d63c12df71af33eed1b6b35`.
The runtime pointer was used to choose this fixed window **between** sessions;
no returned pointer selected an additional in-session address.

## Exact reset-to-resume control flow

Addresses in this section are runtime ROM addresses, not firmware file offsets.
The pinned SDK symbol map names `0x32f61` as `btaon_fast_read` and `0x135b9` as
`os_task_dlps_return_idle_task`. Symbol names identify intended endpoints; they
do not supply the unread endpoints' executed behavior.

1. Reset `0x4efe` saves registers/LR. At `0x4f00..0x4f02` it passes zero to
   `btaon_fast_read(0)`. The returned reason is saved as a halfword on the stack.
2. `0x4f0a: lsls r0,r0,#30` and `0x4f0c: lsrs r0,r0,#31` isolate bit 1.
   `0x4f0e` calls `0x4ee6` with that zero-or-one value. The call's continuation
   is `0x4f12`; the saved Thumb LR is `0x4f13`.
3. Wrapper `0x4ee6` returns immediately at `0x4efc` if the argument is zero.
   If nonzero, it calls unread `0x3a38` and `0x3a1e`, disables interrupts,
   loads literal `0x4f58 = 0x2000f4`, reads the word at base+4, and `blx r0`
   at `0x4efa`. The sampled word names `0xd22c` (Thumb pointer `0xd22d`).
4. That `blx` has an ordinary return continuation at `0x4efc` (Thumb LR
   `0x4efd`). `pop {r4,pc}` there returns to the reset continuation at `0x4f12`
   if its callee returns with the saved stack intact.
5. From `0x4f12`, captured reset code paints `0x203200..0x203380`, calls further
   helpers, invokes the hook at `0x20014c` via `0x4fa6`, and can reach
   `0x4fd4: bl 0x4e36`. Several intervening callees remain unread, so this is
   an explicit continuation, not an observed complete execution.
6. In `0x4e36`, the captured code includes patch-loading alternatives and
   `0x4ede: blx r0` using `[0x2000f0]`, currently `0x40eb`. The exact caller
   of `app_pre_main` is still not located by these windows.

Thus “the bit-1 path attempts resume before first-boot initialization” is
supported. “It never passes through the first-boot chain” is not established.

## Exact resume body and unresolved boundaries

The complete captured function body is only `0xd22c..0xd244`:

```text
0xd22c  push {r4,lr}
0xd22e  movs r0,#0xff
0xd230  adds r0,#1
0xd232  bl 0xd0b8
0xd236  ldr r1,[pc,#0x240]       ; literal address 0xd478
0xd238  subs r1,#0x10
0xd23a  ldr r1,[r1,#8]
0xd23c  blx r1
0xd23e  bl 0x135b8
0xd242  pop {r4,pc}
```

The first call receives `r0 = 0x100`. Its return value and side effects are
unknown. The indirect callback then comes from
`mem32(mem32(0xd478) - 8)`. **The literal at `0xd478` is outside the captured
window**, so even the callback-slot address is not known from these bytes.
Neither that callback nor `0xd0b8` nor `0x135b8` has been captured here.

The final direct call's symbol is consistent with restoration of an idle-task
context. It does not prove that the call cannot return normally. If it does
return normally, the captured POP restores the caller's LR, giving the return
chain described above. If it restores another context without returning, that
must be established from the actual restoration implementation and its state.

`power_manager_resume_all` at `0xd210` is an adjacent function in the window;
the shown body at `0xd22c` does not call it. Absence of literal words
`0x2011d0`/`0x2011d8` from these 512 bytes does not exclude an indirect call,
a computed address, or an access in one of the unread callees.

## Gap and heap observations: no ownership conclusion

The follow-up's two sets of 67 gap-block records exactly match the first
session's final records. Session-header timestamps differ by
**16605.558542 seconds**, about 4.61 hours. The raw gap was deliberately not
saved: 1060 bytes at `0x20e7dc..0x20ec00` are represented by per-block digests
and zero flags. The last of the 67 blocks is four bytes, not sixteen.

The transcript's gap replies are separately redacted. Their packet hashes do
not allow this review to reconstruct raw gap bytes or independently recompute
the saved 16-byte block digests. Archive integrity and equality of the recorded
digests are verified; those are not a second measurement of their generation.

This supports **no observed net content change between sampled endpoints**.
It does not exclude same-value writes, write-and-restore activity, transient
clobbering, or a reset that reproduces the content. There was no trace of actual
DLPS entry/exit, no controlled retention cycle, and no coverage of
`0x20e738..0x20e7dc`, which belongs to V2's own overlay/BSS region. User-reported
disconnected idle time is context, not proof that a particular power state ran.

Both heap snapshots reproduce the earlier raw counter words: presumed data
free/minimum/total `264/104/29688`, buffer `3680/3680/14440`. The format and
ownership qualifications from the earlier heap review remain; unchanged
counters do not establish a new stock-Health peak or future reserve.

## Source/test interpretation and next finite boundary

`fwram_read.py` uses fixed, phase-gated windows, prior-archive identity, repeated
pointer checks before the code window, equality enforcement for repeated ROM
code, postchecks and one-use readers. These controls constrain acquisition; they
do not validate the behavior of the captured function.

The new archive tests in `test_fwram_read.py` pin hashes and selected decoded
values. This review additionally reconstructed the new raw windows from every
matching transcript response. The `test_ram_ownership.py` resume test asserts
the instruction shape, call operands and absent literal words. Its name
`test_dlps_resume_target_returns_to_idle_task_without_app_hooks` and
`ends_in_return_idle_task` field must not be read as a demonstrated context
transfer or exclusion of app hooks: the function merely **calls** the named
endpoint and contains a POP continuation. No full target execution was added
for this review; inventing successful behavior for the unread callees would
not close the finding.

The smallest remaining evidence boundary is the exact `0x135b8` return/context
restore implementation, followed by the missing `0xd478` literal and its
statically reviewed callback binding, plus `0xd0b8`. The full boot-once claim
also needs the actual `app_pre_main` caller and every relevant wake/reset path.
Any additional device reads require a separate bounded plan and fresh
coordination; this document authorizes none.

Keep the bounded readers and replay checks; no generic ROM walker or new
abstraction is needed. Current status: capture integrity **verified**, selected
control-flow structure **verified**, resume-context/non-return semantics
**unresolved**, boot-once/retention/static ownership **unresolved**.
