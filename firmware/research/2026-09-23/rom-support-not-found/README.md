# Support diagnostic: discovery failed before connection

2026-09-23. After renewed client-closure confirmation, one unchanged
`probe.rom_read --support-code --confirmed-idle-clients` attempt exited 2:
`no device found at address 3C2FA77E-1BE3-A0C5-0DD5-DB6A3AD452B2`.

Original transcript: `data/rom-support-20260923-idle-v1/transcript.jsonl`.
This archive is byte-identical; its hash is in `SHA256SUMS`.

The ten-second address scan and existing system-connected-device lookup did
not return the expected device. No BLE client connection was opened, no DIS
identity was read, and zero CD01 requests/replies occurred. There is no
`rom-support.json` success capture. No sensor, flash, reset, target-execution,
pointer-following or retry operation occurred. `disconnect_confirmed=null`
means no client was acquired; it is not a verified-disconnect receipt.

The transcript does not establish why the ring was unavailable: do not infer
a stale bond, phone connection, dead battery or firmware fault. No battery
reading was obtained. The reviewed support-code/state windows remain unread.
Further device work requires a separately coordinated retry, not reuse of this
terminal process or automatic reconnection.

Before the attempt, all 215 hashes in the existing support-preflight build
matched, and all 134 selected support preflight tests passed in 2.39 seconds.
No firmware C, diagnostic code, image, placement or construction gate changed.
This is an unsuccessful discovery record, not firmware or physical-validation
progress toward flash approval.
