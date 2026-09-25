# Resume-code read: installed V2 ring, read-only

2026-09-25. Same authorization family. The user freshly confirmed that all
other clients were closed, and Codex stayed off-ring. Plan:
`probe.ram_read --resume-code`. It first required `0x2000f8 == 0xd22d`
twice; the address came from `../ram-ownership-resume-pointers/`, chosen
offline, not followed in-session. Then it read ROM `0xd200..0xd400` twice.
**No flash, sensor command, write, execution or retry.**

Result: **178 of 178** matching CD01 transactions, verified disconnect, first
attempt. Pointer unchanged; the 512 code bytes were identical across both
reads.

## The DLPS resume target, disassembled offline

```
0xd22c  push {r4, lr}
0xd22e  r0 = 0x100 ; bl 0xd0b8                 (callee unread)
0xd236  r1 = [literal@0xd478] - 0x10 ; r1 = [r1 + 8] ; blx r1   (indirect restore callback, unread)
0xd23e  bl 0x135b8   os_task_dlps_return_idle_task   (ROM symbol)
0xd242  pop {r4, pc}
```

The window also holds `power_manager_suspend_all` (`0xd206`) and
`power_manager_resume_all` (`0xd210`). Neither `0x2011d0` (`app_pre_main`)
nor `0x2011d8` (`app_main`) appears in the 512 bytes.

**Interpretation, bounded (corrected after Codex's independent review).**
The reset handler reaches `0x4ee6` with a `BL` from `0x4f0e`. This routine
ends with `BL os_task_dlps_return_idle_task` and then a normal
`POP {r4, pc}`. **If** the idle-return routine resumes the saved task context
and never returns, the wake path never reaches first boot. If it did return,
control would unwind `0xd242 → 0x4efc → 0x4f12` and continue into the stack
paint and first boot (`0x4e36`). Non-return is the expected behavior for a
DLPS context restore and matches the guide, but it is **unread**. The
callback-slot literal at `0xd478` is outside this window, so even the slot
address is unknown. `0xd0b8` is unread. Absence of `app_pre_main` literals
here is **not** an exhaustive once-only proof. See also Codex's
`docs/UNIFIED_ROM_RESUME_EVIDENCE.md`.
