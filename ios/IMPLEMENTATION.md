# R02 Ring — SwiftUI implementation

## 2026-09-25: compact unified image and runtime switch

The app now bundles and SHA-pins the size-neutral candidate documented in
`../docs/UNIFIED_MODE_V1.md`. Firmware maintenance can install it after the
existing identity, battery, charging, hardware, health-sync and DFU checks. On
reconnect the app fingerprints nine audited code regions before enabling the
runtime control. Gesture entry uses only `A1 04` and requires fresh distinct
A1/03 samples; Health return uses `A1 05` then `A1 02`. Stale inference,
backgrounding and disconnect fail back toward Health. The full 61-test iOS
suite and Debug/Release simulator builds pass. The image has not yet been
flashed or physically validated; the installed ring remains V2 optical-off.

## 2026-09-24/25: offline unified discovery candidate

`Health/UnifiedDiscovery.swift` decodes the proposed 20-byte read-only boot/build
identity. It performs no BLE/UART access, image attestation or capability
admission; production transport remains locked. Actual ARM encoder output and
the compiled Swift parser pass cross-language tests. The complete app builds
for generic iOS Simulator (arm64/x86_64), using explicit Xcode developer path;
no simulator was launched and nothing was deployed or connected. See
`../docs/UNIFIED_DISCOVERY.md` for format, archive, tests and remaining owners.

## 2026-09-22: health-default unified-mode offline work

See `../docs/UNIFIED_FIRMWARE.md` for current implementation, tests and blockers.
The Gesture tab now includes a capability-gated runtime session control and the
pinned float32 model/Swift replay pipeline. The control is deliberately locked:
there is no approved unified firmware or production wire adapter. Existing
stock/V2 flashing is separately labeled **Firmware maintenance**. Nothing from
this implementation was installed on the physical phone or flashed to the ring.
Health sync is read-only, uses independent cursors/overlap, validates complete
responses and persists coverage uncertainty. It no longer sets the clock or
forces HR logging on. Settings changes are explicit user actions.

Built from the design handoff in `~/design_handoff_r02_ring/` (`README.md` and
`R02 Health Dashboard.dc.html`), which stayed outside this repo.
Open `R02Ring.xcodeproj` and run the `R02Ring` scheme. Target iOS 17, portrait iPhone.

```
R02Ring/
  R02RingApp.swift        @main + RootView (tabs, nav stack)
  Design/Tokens.swift     colours, type scale, metrics
  Design/Components.swift tab bar, battery pill, toggle, rules, legend, Screen chrome
  Model/AppModel.swift    tabs, metrics, ranges, gesture map, device/user state
  Model/HealthData.swift  health view models and preview-only fixtures
  Health/                 Colmi protocol, BLE manager, SwiftData store, sync service
  Screens/                Today, metric details, ring onboarding, Gestures, Settings
  Hand/                   the procedural 3D hand renderer
```

## Which Today screen

The handoff's file list points at `1a`/`1c` for Today, but neither is in the shipped
vocabulary — `1a` is light iOS cards and `1c` is a warm editorial layout, both from the
first exploration turn. **`5a` (Today — dark, Health mode) is what's built here.** It is
the newest Today on the canvas, it is the only one in the mono/hairline/single-accent
grammar that `8a`, `9a` and `10a`–`10c` all share, it carries the same header and tab
bar, and turn 10 describes its detail screens as keeping "Today's grammar". Worth
confirming, since it's the one place the handoff's prose and its canvas disagree.

## The gesture animations

`Hand/` is a direct port of the reference renderer, and the capsule tables, pose curves
and camera constants are copied rather than re-derived:

- `HandGeometry.swift` — vector ops, the capsule skeleton (palm, fingers, aimed thumb,
  forearm, ring), and the `pulse` / `hold` easing pair.
- `HandGestures.swift` — the four archetypes with their own camera rigs and pose curves,
  plus cycle durations.
- `HandRenderer.swift` — perspective projection, back-to-front depth sort, and the
  four-pass capsule stroke (ink outline → shadow rim → depth-lit base → inset highlight),
  with the ring's pulsing glow. `GestureTile` drives it from `TimelineView(.animation)`.

Verified by rasterising each gesture at several cycle phases and checking the result
against the design's written description of each shot — side profile for flick up/down,
above-and-behind for left/right, palm-on for snap, stacked mirrored hands for clap.

One behavioural difference from the HTML: SwiftUI's `Canvas` doesn't clip to its bounds
the way `<canvas>` does, so `GestureTile` clips explicitly. Without it the forearm on the
profile shots spills across the neighbouring cell.

## Chart geometry

The design's CSS positions the average/goal rules against the whole chart block, but the
percentages only line up with the data when read against the **plot area**: the steps
average at 40% from the top matches the 59.8% mean bar height, and the heart-rate average
at 53% matches the mean of the resting dots. Both only work plot-relative, so that's how
`MetricCharts.swift` places them — otherwise the "average" line wouldn't sit on the
average.

Production charts are aggregated from the local SwiftData store. `HealthData.swift`
still holds preview-only fixtures so the SwiftUI canvas remains useful without a ring.

## Ring health implementation

This build supports the stock Colmi R02 health firmware only. It lists every nearby R02
by its advertised suffix so households with multiple rings can choose the right one,
then remembers that ring, reconnects whenever possible, restores Core Bluetooth state,
and shows an AirPods-style setup sheet the first time. A successful connection configures
five-minute automatic heart-rate logging and imports battery, heart-rate history, step
buckets, and sleep history. Readings are stored locally and can be exported as CSV from
Settings. Sync runs automatically on connection, whenever the app returns to the
foreground, and every five minutes while the app remains active; there is no manual sync
control. Sync only imports the ring's offline history. Live heart-rate measurement is a
separate user action on the Heart Rate detail screen and starts and stops the optical
sensor explicitly.

The ring clock is initialized only on the first full sync. Colmi command `0x01` clears
accumulated activity on stock firmware, so routine foreground and five-minute syncs must
never resend it; doing so makes steps, periodic heart rate, and sleep appear permanently
empty.

The gesture firmware path is intentionally unchanged. Do not flash or switch firmware
while validating this health build.

## Run it on an iPhone

1. Open `R02Ring.xcodeproj` in Xcode and choose the `R02Ring` scheme.
2. Connect and unlock an iPhone running iOS 17 or newer. Trust the Mac if prompted.
3. In Signing & Capabilities, confirm team `RK84XQQA5U` and bundle ID
   `com.abhayanand.R02Ring`, then press Run.
4. Open the stock R02 ring/put it near the phone, grant Bluetooth permission, and tap
   Connect in the setup sheet. Keep the ring off its charger for live heart-rate tests.

For TestFlight, Product → Archive, then Distribute App → App Store Connect → Upload.
The project includes its Bluetooth background mode, permission string, 1024px app icon,
version 2.8.0, and build 1149. If build 1149 was already uploaded, increment
`CURRENT_PROJECT_VERSION` before archiving.

## Other deviations, all deliberate

- **Fonts.** JetBrains Mono and Instrument Serif aren't bundled; per the handoff these
  resolve to `.monospaced` (SF Mono) and `.serif` (New York). Drop the real faces into
  the target and point `Font.mono` / `Font.serif` at them to close the gap.
- **Safe area.** The 62pt top padding is replaced by the real safe area plus 4pt, and the
  tab bar sits above the home indicator instead of the design's flat 24pt.
- **Tap targets.** The `‹ TODAY` back control is a 44pt target with the label on the
  design's baseline, which puts the headline ~3pt below where the canvas has it.
- **Sleep legend.** In `5a` the stage legend fades in on hover. There's no hover on
  phone, so it's always visible.
- **Grid rules.** Only the left column draws a vertical hairline; the design's CSS puts a
  `border-right` on every cell, which would leave a stray 1px line on the screen edge.

## Relationship to the gesture model

The 11 classes on the Gestures screen are the model's training classes, and the source of
truth for their names is **`whip/registry.py`** — not `corpus/taxonomy.json`, which is the
M2 preference taxonomy and unrelated to the gesture vocabulary. The app's ids match the
registry as of `7a7055d`: `flick_up/down/left/right`, `double_flick_up/down/left/right`,
`snap`, `double_clap`, `wave`.

The vocabulary moves, so re-check the registry rather than trusting this list. It has
already changed once since the app was written: `double_snap` and single `clap` were
retired, because a snap and a clap are the same 2–3 sample shock at the ring and could
not be told apart reliably — the surviving pair is `snap` (single) and `double_clap`
(double). `HandGesture`'s `snap(double:)` and `clap(double:)` builders keep their
parameter even though only one setting of each is now reachable, so restoring a class is
a one-line change.

Two model-side facts the UI does not state. Both belong in a first-run onboarding flow,
which the design canvas does not cover — deliberately deferred rather than bolted onto
the locked Settings and Gestures layouts:

- **Directions are room-referenced, not hand-referenced.** Left/right (and up/down) are
  resolved in a gravity-referenced frame, so they mean the same thing in any hand posture.
  The animations show a canonical posture; they are not describing the axis the classifier
  keys on.
- **The ring must be worn sensor-below, the same way round every time.** Worn inverted,
  left/right flicks resolve backwards. This is a functional prerequisite, not a
  preference, so onboarding is a shipping blocker rather than a nicety.

Live events arrive as `data/live/events_*.jsonl` with a `direction` field. Nothing in the
app consumes them yet: `AppModel.gestureMappings` is static. The merged health build
exposes Today and Settings and uses real BLE synchronization and SwiftData persistence;
the gesture screens and animation assets remain present but are not a live classifier
integration.

## Verification status

Upstream PR #1 reports a successful Xcode 26.3 build and signing for iPhone hardware.
Its protocol tests cover packet checksums, heart-rate epoch decoding and out-of-order
packets, step buckets, fragmented Big Data reassembly, and signed sleep offsets/stages.
The upstream implementation notes report physical-ring checks of discovery, selection
among nearby R02 rings, reconnect, battery, offline steps, periodic and live heart rate,
local persistence, and day-level charts. These are upstream results, not new hardware
checks performed while merging. Overnight sleep end-to-end validation is still pending.

Before the health merge, the gesture UI compiled for the simulator and its screens and
tiles were checked by rasterising through `ImageRenderer` at 393×852. Those historical
checks establish layout, not live gesture animation timing or classifier integration.
Do not apply the earlier mockup-only verification status to the new health screens.

Local merge verification (2026-09-22): main fast-forwarded to `81b67d9` (PR #1),
preserving the local 11-class gesture vocabulary and hand-animation changes. Xcode 27.0
successfully built Debug for both simulator architectures with signing disabled. No
app was launched or deployed and no ring was connected by this build. The pre-merge
iOS-only stash `0b3c0e75ea187cfea0e650edace72f6bd82ca4b6` remains as a recovery copy.

## Health / gesture firmware switch

Settings now exposes an explicit, confirmation-gated Health/Gesture mode switch.
The app bundles hash-pinned stock and V2 images, requires the exact RT02CR hardware
header, a readable battery of at least 40%, and the ring off its charger. Every DFU
frame is written with response and acknowledged; CHECK is the commit gate and END's
reboot/disconnect is expected.

- `HealthSyncService.sync` enables five-minute heart-rate logging when it finds a
  different setting. Connect, foreground and periodic refresh can invoke this. Health
  jobs must be suspended before gesture experiments or flashing; otherwise they can
  restart the optics. Do not run this app against the ring during a battery capture.
- A first/full sync sends clock command `0x01` before importing history. The existing
  code documents that this clears accumulated stock activity. A firmware round-trip
  must not be treated as a new-ring setup automatically; preserving/importing existing
  history needs explicit handling and validation.
- Before Health→Gesture, the app performs a routine (non-clock-resetting) history
  import. In Gesture mode, connection, foreground and five-minute health sync jobs
  are paused. Returning to Health resumes routine sync without treating the same ring
  as new or sending clock command `0x01`.
- Stock is identified by its DIS version. V2 shares its DIS version with the old 25 Hz
  base, so the app uses the same fixed 22-read/244-byte critical-site fingerprint as
  `whip.fwidentity`; unknown or mixed code pauses automatic health work.
- The app button is an explicit fallback. A desktop hotkey is a separate host feature;
  a slow pose/hold at stock's roughly 1 Hz is only a possible switch cue, not the
  trained 25 Hz flick classifier. Receiving stock raw data itself starts the sensor
  front end, so it is not established as a free, passive health-mode gesture detector.
- This does not make health continuous during Gesture mode: V2 deliberately disables
  ordinary optical HR/SpO2 paths, and readings missed during that interval cannot be
  reconstructed. A future single-image reversible optical design remains separate work.
- The Swift implementation and test target compile for both simulator architectures;
  DFU frame vectors match the validated Python implementation. The app-driven physical
  round trip itself remains to be tested; keep the Python flasher as the recovery path.
