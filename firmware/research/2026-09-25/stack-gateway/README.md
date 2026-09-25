# Fixed stack-gateway device capture

One freshly coordinated, read-only session on 2026-09-25 completed the exact
122-request plan in `docs/UNIFIED_STACK_GATEWAY_READ.md`. The ring identified as
`R02_CC07`, hardware `RT02CR_V3.1`, firmware `RT02CR_3.12.07_260514`. The CLI
confirmed disconnect. It issued no sensor or flash command and did not follow
or execute the captured pointer.

The two reads of each new window matched. ROM `0x4926..0x4946` contains the
guarded indirect gateway call. Slot `0x2011d4` contains little-endian
`01e48000`, the Thumb pointer `0x80e401`; its even target equals the repeated
Upper Stack header execution address `0x80e400`. This establishes only the
first ROM-to-Upper-Stack boundary. Target dispatch, callback provenance,
disconnect drain, recovery and flash safety remain unproved.

Files:

- `stack-gateway.json` — bounded structured result, SHA-256
  `c8ea5af0fb5ae5a820b71b2e86fbeafac3c1e3e36105bb0c860370347ab96604`
- `transcript.jsonl` — requests/replies and confirmed cleanup, SHA-256
  `91d350563a167869c1a145c34e1eed644b7242a7c4519935f817947b6122071e`

The initial command invocation failed before importing the BLE hardware layer
because its dated parent output directory did not exist. It sent no device
request; the successful invocation above was the sole device attempt.
