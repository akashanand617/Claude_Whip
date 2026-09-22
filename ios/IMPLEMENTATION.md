# R02 Ring — SwiftUI implementation

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

## Verification status

Xcode 26.3 successfully builds and signs the app for iPhone hardware. The protocol tests
cover packet checksums, heart-rate epoch decoding and out-of-order packets, step buckets,
fragmented Big Data reassembly, and signed sleep offsets/stages. Physical-ring testing
has verified discovery, selection among multiple nearby R02 rings, reconnect, battery,
offline step import, periodic heart-rate import, live heart-rate measurement, local
persistence, and the day-level chart interactions. Sleep parsing is unit-tested; its
overnight end-to-end check is still pending a recorded night on the test ring.
