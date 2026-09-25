# Consolidated ROM-code read — successful separately requested retry

2026-09-23. The user explicitly requested one retry and freshly confirmed all
phone/laptop clients closed, ring idle, no stream or firmware transfer. The
unchanged fixed reader repeated all identity/configuration/descriptor/ROM-ID
prerequisites before reading the five preselected code windows twice. All
**974 CD01 transactions** matched; all **6076 new bytes** matched their repeats;
configuration/idle postchecks passed and **disconnect was verified**. Diagnostic
request/reply time was 134.840 seconds, excluding connection/disconnection.

No sensor, flash, clock/settings, key-field, hardware/FIFO-register or target-code
execution command was sent. No returned pointer was followed. CD01 still has
its audited connection/timer/activity bookkeeping effects. Sampled V2 identity
is not full on-device image attestation. No further device work is authorized
by this completed session.

Originals: `data/rom-integration-20260923-02/`. These copies are byte-identical:

| Artifact | SHA-256 |
|---|---|
| `rom-integration.json` | `d02cc3582a789d933e1be09fa1bbec05ade7a193508418149f145dc12df3b05b` |
| `transcript.jsonl` | `22d85dc403dda89e6bc6cfea605200d05d8201521d58b0ae83ee597235e39f8f` |

| Code window | Address interval, end exclusive | Bytes | SHA-256 |
|---|---|---:|---|
| RAM/boot helpers | `0x4a78..0x53a4` | 2348 | `9b9903350dccd323195fae0a971f2297789dee4e7f9374a699612113a2e123da` |
| Flash-layout getters | `0x805e..0x81a0` | 322 | `449373e70816f028bd074946d6d09eda9edd869154f1369e919e46be096d96e4` |
| OTA-header helpers | `0x8a5c..0x8c72` | 534 | `c93311c9d2fd525c356d4af017289a9069f58231e5d9c8d875c7604c9994abc4` |
| Timer queue/API | `0x105c8..0x10fb8` | 2544 | `2083493e9a074bf2cb1fd9bc83f4b103ea96985becb59a7c9338fad2a3155e7a` |
| Critical sections | `0x1105e..0x111a6` | 328 | `15f6f19816a7cf7a244a869261930cfa189cae36aef07e134591c62d7e751cfb` |

Preflight: 378 offline tests passed; reader/protocol/reference hashes matched
the prior guarded build. The new separate archive test verifies checksums and
exact requests, replays every reply through the fixed reader, reproduces the
saved capture and confirms that the old 1302-byte partial prefix also matches.
This is offline replay, not another live read. Firmware code and the prior
1495-test build remain unchanged; this new archive/test was not in that manifest.

The original unexpected packet did not recur. Its original type/cause remain
unknown; neither the quiet passive session nor this success justify weakening
the diagnostic abort policy.

These bytes are now available for off-ring analysis. They do not themselves
reserve RAM, prove physical flash geometry/power-loss recovery, establish FIFO
timing/model compatibility or validate STOP/resume/steps/sleep. The capture
intentionally retains `recovery_verified=false` and `flash_authorized=false`.
