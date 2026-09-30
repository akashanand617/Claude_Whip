# RT12COL Bluetooth HID bridge

Date: 2026-09-29
Status: offline static analysis and implementation; **not flashed or physically validated**

## Instagram touch swipes through iOS Switch Control (app-only)

Plain Arrow/Page keys remain ordinary keyboard reports: the foreground app has
to implement them. Mouse wheel and relative drag remain ordinary pointer input,
which iPhone may leave inactive while AssistiveTouch is off. Neither is a
general way to synthesize a touch swipe in Instagram.

The app therefore adds two logical actions for an iOS Switch Control recipe:
F5 (`A2 BE`) for a custom upward swipe and F6 (`A2 BF`) for a custom downward
swipe. V9/V10 already accept both USB usages through their direct-key range, so
this is only an app catalog/setup change; the firmware artifacts, hashes and
fingerprints are unchanged. Switch Control can use external Bluetooth inputs,
recipes and custom gestures without the floating AssistiveTouch button, though
it can show its own scanning highlight. External-switch capture and Instagram
behavior remain physical tests.

## V10 keyboard-primary full maps (offline)

The V9 forget/re-pair succeeded: iOS read the exact V9 report map and
`[0x04, 0x01]` Report Reference, created an `IOHIDUserDevice` and subscribed
to ID4. The decisive log was `Ignoring service with secondary keyboard usage`.
The full iPhone map began with stock Mouse ID1 and appended the replacement
Keyboard ID4 descriptor, so iOS selected Mouse as the primary usage and ignored
the secondary Keyboard service role. Keyboard actions were exercised only
before the re-pair; after it, only a wheel action was tried. The proven V9 defect
is therefore descriptor classification, not a demonstrated sender failure.

V10 corrects only that ordering. Each complete selectable report map is
replaced with the same bytes in keyboard-primary order:

- `0x1fdfc...0x1fe8e` (147 bytes): exact V9 81-byte Keyboard descriptor,
  followed by the exact original 66-byte Mouse descriptor; and
- `0x1fe8f...0x1ff31` (163 bytes): exact V9 81-byte Keyboard descriptor,
  followed by the exact original 82-byte Digitizer descriptor.

Application order is now Keyboard→Mouse or Keyboard→Digitizer. V10 invents no
report or field: ID4 remains ten Consumer bits, six constant bits and one 8-bit
Keyboard Array; ID1 remains the original mouse/touch report. The V9 sender,
release entry, wheel helper, bridge, action contract and runtime behavior are
byte-identical.

V10 does **not** repurpose the stock Boot Mouse Input characteristic. That is a
separate boot-protocol transport, while the new commands use report-mode ID4.
The `[ID 4, Input]` Report Reference and the complete HID service database stay
byte-identical. Replacing Boot Mouse would remove stock behavior without
evidence that it fixes the observed primary-usage rejection.

Artifact:

```
firmware/rt12col-25hz-health-default-gesture-v10-hid-keyboard-primary-experimental.bin
RT12COL_1.00.10_260929
SHA-256 7e04ae9973341233d2dbbe06fc6eb4c228aab625b1c3687462416edbe7d21ce2
```

Builder revision is `v10-hid-keyboard-primary-experimental`. The firmware build
performed no phone deploy, BLE connection, DFU or ring write. V10 has not been
interpreted by iOS; primary Keyboard classification, ID4 input delivery, mouse
coexistence and all earlier runtime/Health gates remain physical tests.

## V9 keyboard + mouse extension

V9 is the first physically installed keyboard-map candidate. It retains the V8/V6 motion, lease,
dispatcher and mouse-drag behavior and changes only reviewed HID regions:

- the adjacent 28-byte retired STK helper sends bounded signed wheel deltas;
- the exact 82-byte ID4 press/release span becomes a combined sender while
  preserving the stock HID-enabled gate and GATT pointers;
- both 81-byte ID4 report-map copies become a Keyboard Application report with
  ten one-bit Consumer controls, six constant bits and one 8-bit Keyboard
  Array; and
- the three native release calls target the new common release entry. Native
  Play/Pause (index 3) and Volume Down (index 9) keep their meanings.

The V9 A2 action contract is:

| Action | Result |
|---:|---|
| `0x00...0x03` | V8 mouse drags up/down/left/right |
| `0x04...0x08` | wheel `+5...+1` |
| `0x09` | no report |
| `0x0a...0x0e` | wheel `-1...-5` |
| `0x20...0x29` | Consumer bits 0...9 |
| `0xa0...0xd2` | when the low 7 bits are USB keycode `0x20...0x52`, one Keyboard Array press and release |
| anything else | consumed without HID output |

The Consumer usages are next, previous, stop, play/pause, mute, Search, Home,
Back, volume up and volume down. The app uses the direct-key path for arrows,
Page Up/Down, Home/End, Space, Return, Escape, Tab, Backspace, Forward Delete
and F5. It uses A2 codes `0x80 | keycode`; for example Return is `0xa8` and Up
Arrow is `0xd2`.

Artifact:

```
firmware/rt12col-25hz-health-default-gesture-v9-hid-experimental.bin
RT12COL_1.00.09_260929
SHA-256 27fdfa741407da90def1a1124f8f551503d519d8ef730d30e61fa195476339ef
```

Reproducible sources are `firmware/rt12col_hid_bridge_v9.S`,
`firmware/rt12col_hid_sender_v9.S` and builder revision
`v9-hid-experimental`. The app bundles V9 behind its existing guarded DFU path
and enables V9 actions only after a 707-byte changed-region fingerprint.

Changing the report map may leave iOS using its cached V8 map until the ring is
forgotten and reconnected. Keyboard and Consumer reports do not use
AssistiveTouch. The mouse wheel and mouse drags are ordinary mouse input; their
iPhone delivery may still require AssistiveTouch/pointer support. All of these
host behaviors remain untested. No phone deploy, connection or flash occurred.

## Result

The stock RT12COL application already contains and registers a complete HID
service. V8 reuses it. It does not add or replace a BLE service and does not
change the HID report map.

The stock phone-OS byte at `0x208c1e` selects which report map is served. A
value of 2 selects the touch-digitizer map; every other value selects the map
used by iPhone, which contains:

- report ID 1 mouse input: five buttons, signed relative 16-bit X/Y and an
  8-bit wheel;
- report ID 4 Consumer Control: 24 one-bit usages.

The alternate map contains report ID 1 touch-digitizer input with X/Y and
contact count. These are alternatives, not simultaneous descriptions of report
ID 1.

The same report map and send paths are present in stock, V6 and V7. The stock
firmware already has four mouse and touch trajectories, but before V8 only its
native detector could schedule them. There was no UART command route to those
senders. A2 is not authenticated and has no firmware-side Gesture-mode check;
the app enables it only after exact V8 fingerprinting and only inside a fresh,
calibrated Gesture segment.

## Pinned stock code

All offsets are application-file offsets in `rt12col-stock-1.00.00.bin`; add
the normal `0x825fb0` bias for runtime addresses.

| Purpose | Offset |
|---|---:|
| HID service registration | `0x14160` (startup call at `0x74da`) |
| HID report map | `0x1fdfc...0x1ff31` |
| mouse/button/X/Y/wheel sender | `0x3d70` |
| mouse release | `0x3da6` |
| touch digitizer sender | `0x3dd0` |
| Consumer Control one-hot press | `0x3e1e` |
| Consumer Control all-zero release | `0x3e48` |
| mouse/touch trajectory scheduler | `0x12366` |
| mouse up/down/left/right tables | `0x1f8ea`, `0x1f952`, `0x1f9ba`, `0x1fa1a` |

The trajectory scheduler takes signed X direction, signed Y direction and a
transport selector. V8 deliberately uses transport 1, the stock relative-mouse
path used by iPhone: up `(0,-1,1)`, down `(0,+1,1)`, left `(-1,0,1)` and right
`(+1,0,1)`. The alternate transport 2 is the touch-digitizer path and is not
used by A2. Stock schedules the points at 60 ms intervals.

Consumer bits 0–4 are next track, previous track, stop, play/pause and mute;
bits 8–9 are volume up/down; bits 18–23 are search, home, back, forward, stop
and refresh. V8 exposes the entire 0–23 range in the wire protocol. The app UI
offers only the reviewed, useful subset; more mappings can be added without a
firmware change.

## V8 wire contract

V8 uses the existing checksum-valid 16-byte UART envelope:

```
byte 0   0xA2
byte 1   action
2...14   zero/reserved
byte 15  additive checksum of bytes 0...14
```

| Action | Result |
|---:|---|
| `0x00` | relative-mouse drag up |
| `0x01` | relative-mouse drag down |
| `0x02` | relative-mouse drag left |
| `0x03` | relative-mouse drag right |
| `0x20...0x37` | Consumer Control descriptor bit 0...23, then release |
| anything else | consumed without emitting HID |

The hook is after the stock UART parser has accepted the normal packet. Its four
bytes at dispatcher offset `0x637e` replace both `cmp r1,#0x3b` and the taken
branch to `0x641a`. The corrected bridge therefore does more than restore the
comparison: for command 3B it explicitly calls the exact stock handler at
`0x5c82`, sets `r1` to zero and returns at the stock compare-chain tail. Every
other non-A2 command returns unchanged. A concrete dispatcher regression traces
all 256 command bytes and pins this control flow.

## Placement and fail-closed identity

The exact `RT12COL_V1.0` board uses LIS2DW12 identity `0x44`. The stock
STK8321-identity-`0x23` initializer occupies exactly 80 bytes at
`0xbf30...0xbf7f`. Its only two selector edges (`0xbfda` and `0xc21a`) are
retired before V8 places the 80-byte bridge there. No code cave is assumed and
no live RT12 sensor path is overwritten.

The reproducible assembly source is `firmware/rt12col_hid_bridge.S`; the builder
is `python -m probe.build_rt12col_unified --revision v8-hid`. The resulting
137,996-byte OTA application is:

```
firmware/rt12col-25hz-health-default-gesture-v8-hid-experimental.bin
RT12COL_1.00.08_260929
SHA-256 a8be4e97051b25adffaadfd7f23632c54f396c6711960edf7dd0bfce9d683fc6
```

An earlier unflashed V8 draft is revoked: it returned after recreating the 3B
comparison without recreating its taken branch, and selected touch transport 2.
It was replaced before any phone deploy or ring write. Only the exact hash
above is eligible for the app catalog; the full 80-byte bridge fingerprint also
rejects the draft despite its matching V8 version text.

The iOS app now exposes this exact image through the guarded RT12COL firmware
maintenance catalog. This includes a same-mode V7→V8 upgrade. Before DFU it
checks the bundle SHA-256, image hardware and declared V8 version, requires the
ring in Health with saved history, at least 40% battery and no charging, and
asks for destructive confirmation. Version text remains insufficient after
reboot: the app checks every byte changed by V6 plus the dispatcher hook,
complete bridge, and both retired selector edges before
`ringHIDFirmwareInstalled` becomes true. No phone deploy or V8 flash has yet
occurred.

## App behavior and extension point

The app exposes four swipes plus generic media next/previous/play-pause,
volume up/down/mute and navigation back/forward. `RingHIDAction` already names
additional descriptor usages (media stop, search, home, navigation stop and
refresh), so a later mapping is an app/catalog change rather than a new wire
protocol or firmware patch.

Actions are accepted only after Gesture calibration, outside healing, with the
same exact transport still in Gesture. HID writes use the mode transport's
spacing clock. Stop disables queued HID before sending the Health-return
sequence. A lease renewal and an HID action cannot write concurrently.

On iPhone, the relative-mouse drags require AssistiveTouch to be enabled under
Settings › Accessibility › Touch › AssistiveTouch. Consumer Control keys
do not require AssistiveTouch. The app now includes this setup sheet. The stock
drag is short and may start near an app edge, so some apps may ignore it or
interpret it as navigation; that remains a physical gate.

## Verification and open physical gates

Offline proofs pin the exact 80-byte ARMv6-M assembly, absence of relocations,
all call targets, four direction argument paths, the full Consumer Control
range, unchanged report map/trajectories, changed-byte allowlist, OTA container
checks and artifact hash. Focused iOS tests cover packet encoding, every app
mapping, fail-closed absence of a controller, full V8 fingerprint coverage and
mode-lane serialization.

Seven firmware proofs pass, including concrete 3B control-flow coverage. The
combined V8/event-log/labeling Python set passes 28/28. Full iOS XCTest passes
388/388 with no skips. Release simulator and unsigned generic-iPhone builds
succeed, and the device app bundle contains the exact corrected V8 hash.

None of that proves iOS will accept the stock HID service as intended on the
physical ring. During the first bounded deployment, test bonding and
reconnection, AssistiveTouch mouse-drag semantics in representative apps, all
Consumer Control keys, background
operation, 25 Hz stream/renewal coexistence, stop priority, Health return,
optical/steps/sleep continuity and stock rollback.
