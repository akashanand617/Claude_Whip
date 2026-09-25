# Exact-source and recovery leads — 2026-09-24

Bounded parallel reference search, entirely off-ring. **No RT02CR_V3.1-specific
application source or demonstrated daily-ring recovery procedure was obtained.**
These references narrow the questions; they do not close the recovery gate in
[the readiness checklist](UNIFIED_READINESS.md).

## Vendor package

The [official RTL8762E catalogue](https://www.realmcu.com/en/Resources/SDK/RTL8762E-Series)
lists SDK v1.5.0, ROM patch v1.0.373.16 and secure boot v1.1.0.0. The checked
[SDK download endpoint](https://www.realmcu.com/en/Resources/DownloadSingleFile/RTL8762E-SDK?panel=SDK&prod=RTL8762E-Series&version=v1.5.0)
returned an unauthenticated 401 response; current flash/security guides required
login. No downloaded SDK image was available for byte comparison.

A matching family/package name is not a matching ring application, ROM patch,
linker map or boot configuration. Do not replace the captured timer-hook or
boot-code evidence with an assumed version match. No account creation,
credential use, vendor message or unknown tool execution was performed.

## Documented family recovery mechanism, not ring recovery

The parallel reference worker checked Realtek's
[Hardware Instruction v1.1, dated 2023-05-12](https://www.realmcu.com/img/ipg/en_638357619405474080.pdf):
section 6.1/page 10 describes P0_3 sampled low at reset selecting ROM rather
than flash without erasing flash. Page 32 names factory test connections
LOG/P0_3 and UART P3_0/P3_1. Its
[MP Tool Guide v1.6, dated 2022-01-11](https://www.realmcu.com/img/ipd/en_637840773206765643.pdf),
pages 49–53, discusses download-mode communication, password locking and
encrypted RTL8762E flash readback.

Missing for **this ring**: accessible and identified programming pads, voltage/
reset routing, actual security state, a compatible loader/tool flow, and the
factory/OEM contents required to restore operation. None was tested. This is
not an instruction to open, short or reprogram the daily-use ring. Encrypted
UART flash readback also does not imply encryption of the known plaintext OTA
application payload.

These are URL/version/date references, not locally archived, byte-pinned SDK
artifacts. No new firmware hash, chip geometry or recovery capability is claimed.

## Supplier lead

Realtek's [Yawell announcement, dated 2025-09-18](https://www.realmcu.com/en/Media/Article/5b24e2fc-4e33-4d37-b181-03d8005c2789)
names RTL8762ESF-based rings. Its [smart-ring solution page](https://www.realmcu.com/en/Applications/Smart-Ring)
describes reference designs, prototype SDKs, OTA and production tools. Neither
identifies RT02CR_V3.1, the R02 application version, board pinout or factory image.
Its chip selection table is not evidence of this ring's installed flash part.

The specific useful external artifact would be the **RT02CR_V3.1 application
source/map plus factory recovery documentation**, including programming-pad
access and preservation of calibration/OEM data. Generic examples or another
ring's successful flash do not satisfy that request.
