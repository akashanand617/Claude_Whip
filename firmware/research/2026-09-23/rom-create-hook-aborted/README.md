# Create-hook diagnostic: connected, then aborted during prerequisites

2026-09-23. In direct response to the user asking to reconnect, one unchanged
`probe.rom_read --timer-create-hook --confirmed-idle-clients` attempt connected
to `R02_CC07` / `3C2FA77E-1BE3-A0C5-0DD5-DB6A3AD452B2`. DIS matched
`RT02CR_V3.1` and `RT02CR_3.12.07_260514`. The process exited 2 and recorded
`disconnect_confirmed=true`; it was not retried or reconnected.

Original transcript: `data/rom-create-hook-20260923-idle-v1/transcript.jsonl`.
This archive is byte-identical. SHA-256:
`b28dbcb5749ed3e69dc577550f72bca7ff91bbb88df5f3d8cc973708445f6ece`.

The log contains 170 CD01 requests and 169 accepted matching replies. Request
170 was the known-code prerequisite at `0x1409a`, length 14. An unexpected
16-byte UART notification with command **0x73** poisoned the session; its
payload was deliberately not saved. The terminal error was
`unsolicited/duplicate traffic after diagnostic reply`. This wording does not
recover the unlogged reply or notification payload, establish its meaning, or
identify its cause. Do not infer another client, active sensor, or firmware
failure from that type alone.

All accepted traffic was still within the fixed prerequisites. **None of the
new header, create-hook RAM or comparator ROM windows was requested.** The
first-to-last request interval was 22.975 seconds, excluding connection and
cleanup. No final postchecks or successful `rom-create-hook.json` exist.
Partial reads do not become a completed capture or fresh state attestation.

Before connection, all 222 hashes in `build-20260923-create-hook-preflight-v2/`
matched and all 132 selected diagnostic tests passed in 2.79 seconds. This
attempt changed no diagnostic/firmware code, placement, image or release gate.
No sensor start/stop, settings/clock, DFU/reset, inspected-code execution,
pointer following, key/MMIO/FIFO read or flash occurred. CD01's known
connection/timer/activity bookkeeping effects remain.

The ring was reachable and responsive during this session. No battery or
charging measurement was requested; this does not establish physical health,
safe resume, recovery, or flash readiness. Further device work needs a newly
coordinated bounded session; the terminal process is not a live wait handle.
