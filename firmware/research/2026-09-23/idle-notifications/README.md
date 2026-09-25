# Passive notification observation — 2026-09-23

Completed after fresh confirmation that other phone/laptop clients were closed
and the ring idle. This was a separate connection, not a retry of the aborted
ROM read. Original: `data/idle-notifications-20260923-01/transcript.jsonl`.
The archived transcript is byte-identical, SHA-256:
`e459b22c6edc55800c03d2401f0190d300de8ad37f2eaab2760a9d89cf0f2cf6`.

`probe.idle_notifications` read DIS identity, subscribed to UART notifications,
waited the full **60 seconds**, unsubscribed and verified disconnection. It
recorded **zero notifications**, with **zero UART commands sent**. No sensor,
code-read, flash, clock/settings or battery command was sent. Subscription itself
uses BLE notification configuration; this is not a claim of zero BLE writes.
The DIS strings matched RT02CR_V3.1 / RT02CR_3.12.07_260514, not a full image
fingerprint or a way to distinguish images sharing those version strings.

The passive reader, tests and packet implementation matched the preceding
1495-test build's recorded hashes; the 11 fake-radio tests were rerun and passed
before connecting. No firmware source changed during this observation.

The earlier unrelated UART packet **did not recur in this interval**. Its type,
source and cause remain unknown. A quiet passive connection does not establish
behavior while CD01 commands execute, prove all internal producers idle, qualify
any ROM window, or justify ignoring foreign packets during diagnostics. No code
read was retried, and all construction/physical-evidence gates remain unchanged.
The session ended; further device work needs its own bounded plan/coordination.
