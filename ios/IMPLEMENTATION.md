# R02 Ring — SwiftUI implementation

## 2026-09-29: Instagram Switch Control swipe keys (app-only)

Instagram's iPhone UI did not register Arrow/Page commands during the physical
test, and the system kept the mouse service not-ready while AssistiveTouch was
off. That leaves neither existing path able to advance Reels: an app may ignore
keyboard navigation, while wheel and relative-mouse drag remain pointer input.

Apple's current iPhone accessibility documentation provides a third route:
Switch Control can use external Bluetooth inputs, recipes and saved/custom
gestures, including scroll. The app now exposes two dedicated V9/V10 keyboard
actions for that one-time setup:

- `hid_switch_swipe_up` sends F5 (`A2 BE`);
- `hid_switch_swipe_down` sends F6 (`A2 BF`).

F5 already existed in the app/firmware contract; F6 is USB keycode `0x3f`,
which was already inside V9/V10's accepted direct-key range `0x20...0x52`.
There is no firmware, image, descriptor, GATT or fingerprint change. The Ring
controls sheet explains how to add the two keys as external Switch Control
inputs, attach custom swipe gestures through a recipe, and keep Switch Control
on the side-button Accessibility Shortcut. Wheel actions are now named
"Mouse wheel" so they are not confused with this touch-gesture route.

This route has no floating AssistiveTouch button, but Switch Control can show a
scanning highlight and changes normal touch behavior while enabled. Whether
iOS accepts the ring's F5/F6 reports as external switches and whether the
resulting recipe advances Instagram are physical gates; the app does not claim
success before that test. Apple references:
[external switches, recipes and saved gestures](https://support.apple.com/guide/iphone/iph400b2f114/ios)
and [Switch Control scrolling](https://support.apple.com/en-au/119835).

## 2026-09-29: V10 keyboard-primary route and HID/renewal serialization

V10 (`RT12COL_1.00.10_260929`, SHA-256
`7e04ae9973341233d2dbbe06fc6eb4c228aab625b1c3687462416edbe7d21ce2`)
is now the newest guarded RT12COL target. It keeps V9's sender and A2 wire
actions but makes Keyboard the first Application collection in both complete
HID maps. This addresses the physical iOS log that ignored a secondary
Keyboard usage; V10 host behavior remains untested.

- Installed V9 remains exactly recognized but is no longer offered as a target.
  Exact V8 remains the rollback. V9→V10 is eligible despite both being Unified.
- The existing history, Health-mode, battery, charging, hash/header/version and
  destructive-confirmation gates remain. V10 capability is granted only after
  an 855-byte fingerprint covers every stock→V10 changed application byte.
- The setup flow requires forget/reconnect after reboot so iOS replaces its
  cached V9 map. V10 uses V9's exact command values and wheel amount setting.
- `sendHIDCommand` now waits behind a renewal rather than dropping the action as
  `busy`, then revalidates connection, Gesture ownership and stop state. A stop
  revokes queued HID before retrying a renewal-held mode gate. Focused
  `UnifiedModeTests` pass 26/26 with both race regressions.
- Full XCTest passes 397/397 with no skips. The selected firmware/event-log
  Python set passes 40/40, a fresh V10 build matches the pinned artifact, and
  Release simulator plus unsigned generic-iPhone builds succeed.

No V10 phone deploy, BLE connection, DFU or ring write occurred. Do not call
V10 safe or physically validated.

## 2026-09-29: V9 keyboard + mouse controls (offline)

V9 is bundled as a guarded same-mode upgrade and V8 remains selectable as an
exact rollback. V9 is `RT12COL_1.00.09_260929`, SHA-256
`27fdfa741407da90def1a1124f8f551503d519d8ef730d30e61fa195476339ef`.
The route saves pending Health history, requires the ring in Health, battery at
least 40% and not charging, validates bundle hash/header/version, asks for
destructive confirmation and enables commands only after a 707-byte post-reboot
fingerprint. No phone deployment, ring connection or DFU occurred.

- `RingHIDAction` is now logical. It resolves to V8 or V9 wire commands only
  after the exact installed revision is known. V8 keeps its original Consumer
  indices; V9 uses Consumer actions `0x20...0x29` and direct keyboard actions
  `0x80 | keycode`.
- The picker exposes V9 wheel up/down plus arrows, Page Up/Down, Home/End,
  Space, Return, Escape, Tab, Backspace, Forward Delete and F5. It also exposes
  media stop, Search, Home and a named camera-shutter mapping (Volume Up).
  Rows remain locked until the exact V9 fingerprint is present.
- Wheel amount is persisted independently at 1...5 (default 3); the app encodes
  it into the bounded V9 actions. HID writes still share the session's UART
  serialization and require a calibrated, non-healing Gesture segment.
- The setup sheet separates keyboard/Consumer input, which does not use
  AssistiveTouch, from mouse drags/wheel, whose iPhone delivery may still need
  AssistiveTouch/pointer support. Because V9 changes the HID report map, the
  sheet warns that iPhone may need the old ring pairing forgotten and
  reconnected after reboot.
- The firmware report map is structurally standards-shaped, but actual iOS
  keyboard classification, embedded Consumer fields, rebonding, mouse wheel,
  foreground-app handling, background use and Health return remain physical
  gates. Do not describe V9 as safe or validated.
- Offline evidence: seven V9 firmware proofs and the selected 35-test Python
  set pass. Full XCTest passes 393/393 with no skips. Release simulator and
  unsigned generic-iPhone builds succeed with the exact V9 bundle. The broader
  RT12 Python run stops in this environment on a Unicorn illegal instruction;
  it is not counted as a pass.

## 2026-09-29: fingerprint-gated ring HID actions (off-ring)

This supersedes the 2026-09-28 statements that swipe actions are locked and
that only A1/3B packets exist. The implementation is complete offline but V8
has **not** been flashed, the updated app has not been installed on the phone,
and no HID behavior has been physically tested.

- Exact RT12COL V8 (`RT12COL_1.00.08_260929`, SHA-256 `a8be4e…83fc6`) is V6's
  selected 200 Hz/wide-band Gesture source plus a size-neutral UART-to-stock-HID
  bridge. At the user's 2026-09-29 request, Firmware maintenance now offers the
  exact V8 bundle for a recognized RT12COL identity, including V7→V8 even though
  both images are Unified. It checks SHA-256, hardware and declared V8 version,
  requires Health mode, saved history, battery at least 40% and not charging,
  then asks for destructive confirmation. HID is enabled only after the rebooted
  image matches all 423 fingerprinted bytes, including the complete bridge and
  both retired call edges. The route is prepared; no phone deploy or flash has
  occurred.
- `A2 <action>` is the only new packet. It is not authenticated or Gesture-gated
  by firmware; the exact-fingerprint app path supplies those restrictions.
  Actions 0–3 select the stock relative-mouse trajectories (up/down/left/right)
  using transport 1; `0x20...0x37` select the stock 24-bit
  Consumer Control report. Unknown actions are consumed without HID. Older
  images never receive A2.
- The corrected 80-byte bridge explicitly calls the exact stock 3B handler at
  `0x5c82`. This restores the taken branch overwritten with the dispatcher
  comparison. An earlier unflashed draft omitted that branch and used touch
  transport 2; it is revoked and rejected by the complete bridge fingerprint.
- Swipe up/down are now live mappings, and swipe left/right, media next/
  previous/play-pause, volume up/down/mute and navigation back/forward are
  offered as remappable Ring controls. Existing flick right/left defaults stay
  Apple Music next/previous; existing up/down defaults now become functional
  only on an exactly verified V8 image.
- iPhone swipes require AssistiveTouch. The Gestures screen includes the exact
  Settings path and distinguishes mouse drags from Consumer Control actions,
  which do not require AssistiveTouch.
- `A1UnifiedModeTransport.sendHIDCommand` shares the serialized 150 ms UART lane
  with entry, stop and lease renewal. It accepts an action only in a fresh
  Gesture segment. Entry, Health, healing, disconnect and a stop reject or
  cancel it. Lifecycle logs record `hid_action` sent/failed results.
- Seven static firmware proofs pass, including a concrete 3B dispatcher
  regression, and the combined Python set passes 28/28. Full iOS XCTest passes
  388/388 with no skips. Release simulator and unsigned generic-iPhone builds
  succeed with the corrected V8 artifact copied into the app. Physical gates
  include iOS HID bonding/reconnection, all
  four drag directions in several foreground apps, Consumer Control behavior,
  background delivery, coexistence with 25 Hz notifications/renewal, stop
  priority, Health return and battery impact.

Detailed static offsets, descriptors, command values and limitations are in
`docs/RING_HID_RESEARCH.md`.

## Later 2026-09-28: sticky Gesture sessions and "Gestures ready ✓"

This supersedes every line below that says a stale stream, a stall, a failed
renewal/lease or a disconnect ends a session or "returns the ring to Health".
The work was done offline and has not been run on the phone or the ring.

**The only ways a session ends** (`Model/GestureSessionPolicy.swift`,
`GestureEndReason`; `GestureDesire.end` takes nothing else):

| End reason | Trigger |
|---|---|
| user / intent / gesture_action | Return or Cancel (also while reconnecting), Toggle off or Pause Gestures, a gesture mapped to Pause |
| auto_return / idle | the user's Session timer or Pause when idle (both now timed on `ContinuousClock`, from the session start; heals do not move them) |
| charging | two consecutive charging refusals in heals (a checksum-valid `A1 FF` while an entry is pending, or charging readiness) |
| ring_gone | the link stays down 60 s |
| heal_gave_up | heals keep failing 60 s with the link up (plus 20 s after a reconnect; 180 s cap), or the firmware has no lease |
| backgrounded / ring_forgotten | kept from before: Keep-in-background Off and R02 leaves the screen; Settings › Forget ring |

`GestureSessionPolicy.disposition` maps every `GestureSessionTrigger` with
no default branch. Stale/stalled data, a bad or stopped source, a lapsed
lease, lost mode control, a reply mismatch, a disconnect and a model failure
map to a heal. Finishing a waveform capture no longer ends the session.

**Heal** (`Model/GestureSessionKeeper.swift`): recognition, routing and
renewal stop for the segment; late events are dropped. Then
`GestureSessionSequencer.restart` runs, using only the audited packets. If the
ring still reports Gesture it sends `A1 05, A1 02, 3B 02 01 00`, then
`A1 04, 3B 02 01 03`. Backoff is 0.5, 1, 2, 4, 8 s (4 s cap in the
background). Waits for connect, identify, attach or busy are not counted as
attempts. Any stop bumps `healEpoch` and withdraws a heal that is under way.
The keeper runs its restart in an unstructured task, so cancelling it never
leaves half a packet sequence. The episode clock starts at the last good
processing (`ContinuousClock`), so a wake long after the stream died gives
up with no attempt. A reconnect after the window never re-enters Gesture.
An episode closes after 2 passed renewals and 30 s. A fault before that
reopens it (same episode and journal attempt count) with a fresh give-up
clock from the reopening fault, and with the link up a reopening never gives
up before one of its own attempts has failed (180 s cap), so a stream that
stalls but heals every time never ends as "couldn't reconnect". A backoff
runs to its end: a mode re-attach after a failed entry wakes the loop but no
longer cuts the backoff short (only a user Start may, at most every 2 s).
No heal happens on firmware without the 10 s lease; that give-up says so
("this ring's firmware can't reconnect gestures automatically") instead of
"couldn't reconnect for a minute". Calibration is kept only if the heal resumed within 60 s of
the last good data and the link never dropped; otherwise the wearer is asked
to recalibrate. Health sync, HR settings, manual HR and firmware switching are
off for the whole desired session. A background task and a pre-scheduled
"Gestures turned off" notice cover suspension. A give-up posts exactly one
notification that names the reason and the time.

**Renewal** (`Health/UnifiedMode.swift`): a failed gate no longer calls
`stopRaw`, and the coordinator keeps control (`keepsControl`). Control is
still dropped on `reply_mismatch`, uncorrelated, exhausted, notReady and
unknown errors. `RenewalVerdict` classifies each failure:
- Timing misses (`rate_high`, `max_gap`, nonmonotonic, a timeout with at least
  10 samples) retry at the next heartbeat however often they repeat (each one
  wrote A1 04, which restarted the lease). They heal only as `lease_lapsed`,
  when `leaseAge + 5 >= 9`; they never call the stop path.
- A bad or stopped source (`duplicates`, `rate_low`, a timeout with fewer than
  10 samples, no processed data) heals.
- Pre-write refusals retry after 1 s while `leaseAge + 1 < 9`, otherwise they
  heal as `lease_lapsed`.

Nothing renews without fresh processed data. A heartbeat that was not yet
due on the uptime clock (`HeartbeatOutcome.notDue`, e.g. the phone slept in
the 5 s wait) renews and checks nothing, so it is never credited as a pass
(no `lastGoodAt`, no probation pass); it retries when due. Entry evidence
counts only A1 03 packets after the A1 04 was written, so the backlog of a
stream a heal just stopped never confirms its re-entry; an RT12 hold write
that fails after entry was confirmed returns the transport to Health.

**Intents**: after a start, Start and Toggle wait for calibration until 8 s
after the tap. The readiness wait (up to 10 s) and the A1 04 entry (up to
3 s) come first and are not cut by that budget, so a slow reconnect can hold
the reply for about 13 s, still inside the background intent budget. The reply is then "Gestures ready ✓", or "Gestures on — hold
fingers down to finish calibrating". In the second case one "Gestures ready ✓"
notification follows when calibration completes, only if R02 is not in front,
and only if notifications are authorized; the app never prompts. During a heal
the reply is "Gestures on — reconnecting to the ring". A heal that needed
recalibration also posts "Gestures ready ✓"; a silent heal posts nothing
(`GestureReadyAnnouncer`), which counts concurrent waiting intents per epoch
so one calibration is announced once, and keeps a dialog that is waiting when
a heal needs recalibration (no background prompt; the heal's notification is
armed only if the dialog leaves first). A start that joined another start's
entry answers "Still starting" at its deadline, and "No Gesture session
started" (not "turned off") if that entry failed. The wait and its decision
are `GestureCalibrationWaiter`, which the tests run directly. A Toggle during
a heal turns gestures off (after the 3 s grace). The Toggle grace runs from
the later of the session start and the last start intent's reply, so a Back
Tap iOS queued behind the first run's wait is still one tap; "Still
calibrating" is only answered inside that grace. A start that a held stop cancelled now answers "Start cancelled"
instead of "started", which fixes Open (1) below.

**Journal**: `session_start`/`session_end` (with epoch, heals, segments),
`segment_start`/`segment_end`, `heal_started`/`heal_attempt`/`heal_succeeded`/
`heal_stable`/`heal_gave_up`/`heal_cancelled` (cause, attempt, episode),
`renewal_missed`, `calibrated_ready` (announce: dialog, notification, screen,
unauthorized or none), `intent_calibration`, `orphan_gesture`,
`return_skipped`, and `session_end` with reason `app_terminated`.

**Orphan Gesture**: Gesture no session wants is judged without a waiting
start's own arming (`GestureOwnership.orphan`), so that start waits
`.returning` for the return to Health instead of answering "already running";
the Health enforcement keeps retrying while the orphan lasts and is not
cancelled by a new arm. A start that ends without a session re-arms it. A
session end's deferred return to Health is skipped when a newer session is
on or a newer start is entering from Health (`returnToHealthApplies`), and
the end withdraws any heal restart synchronously (`withdrawHeal`).

**App termination**: while a session is on, a small `GestureSessionMarker`
(epoch, start, last renewal) is kept in UserDefaults and cleared by every
end. A launch that finds it (iOS terminated R02) journals `session_end`
`app_terminated` and posts one "Gestures turned off" notification. The
desired state is never restored: nothing restarts Gesture on its own.

**UI**: the panel shows "Reconnecting" with a Return to Health button, and the
summary counts reconnects.

**Tests**: 382 executed, 0 failures, no skips, no Swift warnings (356 before
the review fixes of 2026-09-29; 278 before this work). The review fixes
changed `testAFaultBeforeTheHealIsStableReopensTheSameEpisode` (the give-up
clock now runs from the reopening), the timing-miss policy test (no third-miss
escalation), the second-Toggle test (kept only inside the grace), and
`testANewSessionOrReattachStartsWithoutAnEarlierRejection` (feeds entry
motion only after the A1 04 is written).
The Release simulator build succeeds. `tests/test_ios_event_log_contract.py`:
4 passed. Existing tests changed because the spec now forbids stopping on a
renewal failure:
- `UnifiedModeTests` duplicate burst: now keeps Gesture.
- `UnifiedRenewalGateTests`: 7 gate failures now assert that no stop packets
  are sent and Gesture is kept, instead of `assertStopped`.
- `ModeRecoveryTests`: three tests. A gate failure keeps control; a reply
  mismatch still drops it and recovery re-attaches.

**Not done, or needs your decision**:
- A rolling heal-rate valve (flapping that keeps healing is not bounded by
  any end, by design; only the 180 s cap per opening bounds a stuck heal).
- A termination that is never followed by a relaunch is reported only at the
  next launch.
- A Toggle right after a snap pause answering "just paused".
- `AppModel` glue is not unit-tested: it has no `AppModel` harness. Its
  pieces (`GestureOwnership`, `GestureCalibrationWaiter`,
  `GestureSessionMarker`, `GestureGiveUpNotice`) are.

**Physical checks owed**: heals after a stall, a lease lapse, a walk out of
range and back within and after 60 s, and the charger; whether RT12 V6/V7
answer `A1 04` with `A1 FF` on the charger (unverified, so a charger
mid-session may end as `heal_gave_up`); heal timing in the background and
the screen-locked case; the calibrated reply and the one ready notification;
battery during longer sticky sessions.

## 2026-09-28: gesture actions, Back Tap and background sessions

This supersedes the 2026-09-25 line below that backgrounding fails back toward
Health: background sessions are now a setting, "Keep gestures active in
background", **on by default**. The idle pause (Off/5/15/30 min, default 15,
reset by every recognized gesture), the Return-to-Health timer (Off/1/5/15/30),
stale stream, lease/renewal failure, disconnect and explicit stop still return
the ring to Health; with the setting off, leaving R02 does too. The app sends
only the audited `A1 04`, `A1 05`, `A1 02` and `3B 02 01 03/00`.

**Actions** (`Gesture/GestureActions.swift`; performed by
`GestureActionPerformers.swift`, routed by `GestureActionRouter.swift`):

| Action | Default gesture | Background | Notes |
|---|---|---|---|
| Pause gestures | snap | yes | Ends the session: ring to Health, CNN stops. Remappable. |
| Next track | flick right | yes | Apple Music `systemMusicPlayer`; needs Apple Music access. After the last song Music is expected to return to the first and pause (device check below). |
| Previous track | flick left | yes | On the first song (or an unknown index) it restarts the song instead of `skipToPreviousItem`, which would end playback. |
| Play / pause, Restart song, Shuffle on/off, Cycle repeat | none | yes | Apple Music, same access. |
| Flag, Approve, Mark | none | yes | Research labels: only the event-log line. |
| Ping phone | none | yes | Local notification with sound; Silent/Focus can mute it. |
| Swipe up / Swipe down | flick up / down | locked | An iOS app cannot scroll other apps; needs ring-sent Bluetooth HID. Never performed. |
| No action | double flicks, double clap, wave | — | Recognized and logged only. |

Not offered: volume (hidden `MPVolumeView` only), torch (background unverified),
HomeKit (entitlement), Run Shortcut (`shortcuts://` is foreground-only) and
speech (needs the `audio` background mode, which R02 does not declare).

**Intents** (`Intents/`): Toggle Gesture Session and Start Gesture Session
(foreground-continuable), and Pause Gestures (Return to Health), listed under
"R02Ring" in Shortcuts. A background start waits 10 s for the ring; not
connected, not ready or background sessions off then asks to continue in R02,
which tries for 30 s and says on the Gestures screen why nothing started. A stop,
a second Toggle or the panel's "Cancel start" withdraws a start that is still
waiting, so A1 04 is never sent after the user asked for Health.
`GestureSessionSequencer` owns this ordering and is unit-tested without Bluetooth.
Once A1 04 is out, a stop is held and sent as soon as entry settles; see Open
for two reply/Toggle gaps around that window. Intents reach the model through
`Model/AppRuntime.swift`: the `@MainActor` singleton `AppRuntime.shared` owns the
SwiftData container and `AppModel` and calls `model.start`, so a cold background
launch by an intent or Bluetooth state restoration starts the ring manager
without any view.

**Back Tap**: in Shortcuts create a shortcut with "R02Ring › Toggle Gesture
Session", name it "R02 Gestures"; then Settings › Accessibility › Touch › Back
Tap › Double or Triple Tap › R02 Gestures. The Action Button can run it too.

**Logs**: `Documents/GestureEvents/events_*.jsonl` (Python EventLog's nine keys,
joined unchanged by `python -m probe.label join`) and `lifecycle_*.jsonl`
(starts/stops, readiness, renewals, 5 s stream-gap windows, scene changes,
mode recovery, and `music_slow` for any Apple Music call over 100 ms).
Every judged event gets a line: the action name when one resolved (locked
swipes included), JSON null when unrecognized, suppressed or unassigned. `t_s`
and `end_s` are relative to the session's stream start, `wall` is epoch seconds
at dispatch; `tests/test_ios_event_log_contract.py` checks the fixture against
`GestureEvent.as_dict()` keys plus `{action, wall}` and the flag/approve join.

**Bugs fixed with this change**:
- Entry-window race: a stop during entry (A1 04 sent, three-sample gate not yet
  passed) is held and sent once entry settles; a stop during the readiness wait
  withdraws the start. An integration test on the real coordinator and A1
  transport sees exactly `A1 05, A1 02, 3B 02 01 00` after the entry.
- Renewal failure left mode control unavailable until reconnect, and a
  renewal-guard failure wrote no stop packets. `ModeRecoveryController`
  re-attaches the same A1 transport after 600 ms (at most 3 consecutive failures
  per connection); attach sends the audited stops and re-enables Start.
- `RingManager.peripheral(_:didUpdateValueFor:)` read `characteristic.value`
  after the main-actor hop, where the next notification could overwrite it.
  Value, UUID and receipt uptime are now captured before the hop.
- Follow-up fixes (`Model/GestureStartHolds.swift`, which now owns the
  foreground hold, the continuation, the deferred health refresh and both
  failure messages; 13 tests in `GestureStartHoldsTests`): (a) the continuation's
  "no session started" message, and the panel's own tap message (now
  `AppModel.panelRequestMessage`, not view `@State`), are cleared by the model
  whenever the coordinator publishes `.gesture` from any source, before the
  charging guard, or when a start returns `.started`/`.alreadyActive`. A failed
  entry (`.enteringGesture` then Health) keeps them; the panel's tap message
  also ends when the panel leaves the screen. (b) A user or intent stop drops
  the hold, withdraws the continuation, and runs the deferred health refresh
  only after the stop settles. Previously a stop that dropped only a
  foreground-start hold never ran it, and the continuation case ran it before
  the stop.

**Open** (not fixed):
- Charging is checked only when a session starts, never mid-session: a
  re-check needs a battery query that is unvalidated during raw streaming. The
  Gestures screen says so.
- Low-severity review findings: (1) `GestureSessionSequencer.requestStart`
  (line 82) returns `.started` when a held stop ran right after entry, so the
  intent says the session started while the ring is back in Health and the
  journal's `request` has readiness=cancelled with outcome=started; (2)
  `GestureModeSnapshot.gestureActive` (`GestureSessionControl.swift:150`)
  excludes `.leaving`, so a Toggle during a stop waits and re-enters Gesture,
  e.g. an "off" Back Tap right after a background snap pause (no background
  haptic) restarts streaming. The other two findings of that review (stale
  continuation message, stranded deferred refresh) are fixed above.
- CoreBluetooth callbacks and gesture ingest still run on the main queue; only
  a Music warm-up (`SystemMusicController.prepare()`) and the `music_slow`
  journal were added.
- No unit test covers the receipt-time capture (`CBPeripheral` cannot be
  constructed in tests) or the `AppModel` glue that ends a session on idle
  expiry (`GestureIdleTracker.sleepUntilExpired` itself is tested), or the
  one-line `AppModel` calls into `GestureStartHolds` (the controller is tested).
- `ForegroundContinuableIntent` is deprecated in the iOS 26 SDK; it builds
  without warning at the iOS 17 target but needs migrating if the target rises.

**Offline evidence** (latest fix-stage run, iOS Simulator SDK 27.0): full XCTest
suite 229 executed (88 before this feature), 0 failures, no skips, zero Swift
warnings (the old `GestureDiagnosticCapture.swift:106` warning is fixed); Release
simulator build succeeds; `tests/test_labeling.py` plus
`tests/test_ios_event_log_contract.py` 21 passed. A DEBUG-only launch argument,
`-R02InitialTab gestures`, opened the Gestures tab for a simulator smoke launch
with no crash. Nothing was installed on the phone or connected to a ring.

**Verifiable only on the physical iPhone and ring** (none has been done):
- Back Tap from inside Instagram and Music, warm and cold launch; start latency.
- Background delivery at 25 Hz for 15+ minutes in another app and with the
  screen locked; lease renewals pass; compare the journal's gap/hop stats.
- All six Apple Music commands from the background, and whether access is
  really required. First music gesture after an R02 cold launch, and a music
  gesture with Music force-quit: check the journal for `music_slow` and for a
  `stale_stream` session end right after the dispatch (Music's synchronous IPC
  runs on the main queue, which also stamps BLE receipt times).
- Previous track on the first song restarts it; next on the last song.
- Ping under Silent and Focus.
- Snap → pause → Back Tap resume ×10; accidental-snap rate.
- A Pause or second Back Tap while a start waits for the ring: no session starts.
  (A stop landing during entry is sent after it, but the start's reply still
  says "started"; see Open.)
- Toggle with the ring out of range → "Continue in R02": R02 opens on Gestures,
  starts if the ring is ready within the 30 s budget or says why not, and no
  automatic health sync runs first. Scene-activation timing against the
  continuation is unverified.
- Idle pause fires; going out of range returns the ring to Health.
- Recovery after a renewal failure (`mode_recovery_*` in the journal).
- Phone and ring battery during background sessions.

**Later 2026-09-28: sessions ending seconds after Back Tap.** Diagnosis of the
iPhone 14 + RT12COL V7 journal (20 sessions): of 15 Back Tap sessions, 12 ended
on their own (8 `stale_stream`, 4 `renewal`) and one by a second Toggle 2.4 s
in. 6 of 52 renewals failed (11.5%). The phone's link delivers on a ~30 ms
connection-event grid, and the old renewal limits sat on it (120 ms max = 4
events, 1.5x median = 45/30), so ordinary missed events decided the gate.
Stale endings matched main-queue gaps (BLE is delivered on `.main`) at scene
changes and mid-background; which check fired was never journaled. The
`receivedAt` capture change did not cause either. Changes, entirely offline:
- Renewal gate (`UnifiedMode.swift`): pass/fail now uses the mean post-write
  spacing (24-64 ms, i.e. 0.6-1.6x the pinned 25 Hz), max spacing <=
  `GestureFreshness.stallCeiling` (0.5 s) and the unchanged duplicate rule;
  medians and boundary spacing are journaled only. No retry, no new command.
  A lease-age guard refuses to renew more than 9 s after the last `A1 04`.
- `GestureSession` survives one stall under 0.5 s (gap or dequeue age) per
  10 s once a sample has been processed: late samples and a quarantine (until
  three >= 20 ms spacings or 0.5 s) are dropped, then the inference window
  restarts (calibration kept). First-sample, >= 0.5 s, repeated or > 1 s
  episodes, ordering, sequence, decode and post-inference failures still end
  the session. Queue bound 8 -> 24 (age bounds staleness). Events older than
  0.75 s at dispatch run no action (`event_dropped_stale`).
- Model loaded and warmed once off the main thread (`warmUp`, lock-shared).
- Journal: `stale_detail` (check, value, limit, tolerance), `session_end.detail`,
  `renewal` per attempt (spacings on failure), `renewal_failed` with report and
  guard names, `stream_stall`, `main_stall` (50 ms watchdog), `calibrated`,
  `first_predict`, `intent`, and per-window lattice/predict/queue/repeat counts.
- Back Tap: a Toggle within 2 s of a pending start, or 3 s of a session
  starting, says so instead of stopping (a user-visible policy change; Pause,
  the app button and a mapped gesture still stop at once). An automatic end in
  the background posts a notification, and the next intent start names it.
Full suite 259 executed, 0 failures, no skips; Release build succeeds; Python
contract tests 21 passed. Physical acceptance is the next phone journal.

Review corrections (same day, offline):
- `GestureSession` judges receipt gap and dequeue age together before either
  is tolerated; the larger names the check. A late sample can no longer hide
  a hole of 0.5 s or more behind a 0.25-0.5 s hop delay.
- A stall reset keeps the wave refractory: one continuous wave across a
  tolerated stall fires once (the Python-parity `reset()` is unchanged).
- The heartbeat no longer ends a session on `processed_age` while processing
  is paused by a stall the session tolerates: it retries every 100 ms while the
  newest processed sample is at most 2.25 s old (gap, 1 s episode, 0.5 s
  quarantine, hop), and never renews before processing resumes
  (`heartbeat_retry` records it). A stopped stream now ends at about 2.3 s of
  processing age instead of 0.5 s; the 9 s lease-age guard is unchanged.
- The renewal gate no longer judges pre-write backlog: after a post-write
  spacing over 150 ms, the ten judged spacings start after the bunched
  backlog (three spacings >= 20 ms, or 0.5 s). A spacing over 0.5 s fails at
  once; the timeout rose from 1 s to 1.75 s. A stopped, half-rate or frozen
  producer behind a stall across the write now fails; bunching under 150 ms
  (at most three samples) can still bias the mean low. Reports add
  `judged_from`, `stalls` and `back_to_back_after_write`.
- `renewal_failed` carries the transport's report and rejection only when that
  heartbeat reached `renew` (`reached_renew`); `session_end.detail` falls back
  to `heartbeat_error:<error>`. A new session or re-attach clears the
  transport's last rejection.
- The Toggle debounce is stamped only by the request that creates the pending
  start or by the Continue tap, and cleared by a stop, so a Shortcut
  continuation's own late request cannot re-arm it.
- Automatic endings are timed on `ContinuousClock`, which keeps running while
  the phone sleeps, for the 10-minute window and its "N s ago" text.
Full suite 278 executed, 0 failures, no skips; Release build succeeds.

## 2026-09-27: RT12COL exact images and hardware-family routing

Firmware maintenance routes from both Device Information fields and fails
closed unless hardware and firmware identify the same known family. RT02CR sees
only RT02CR images. RT12COL sees its independently acquired stock application
restore and exact-source Health-default / temporary-Gesture candidate. Both are
SHA-pinned and their outer hardware header must remain `RT12COL_V1.0`; unknown
versions, missing identity and cross-family combinations expose no image. The
transfer path repeats routing before any Health import, battery check or DFU
write. The revoked RT02 unified-V1 descriptor remains disabled.

V1 (`RT12COL_1.00.01_260927`) physically booted and streamed, but retained the
stock 25 Hz LIS2DW12 source. V3 (`CTRL1=0x62`) is revoked: both `0x62` and stock
`0x32` select LP mode 3, and its repeated `A1 04` re-entered sensor/timer setup.
Its install descriptor is disabled. V5-LP1 (`0x60`) subsequently booted in a
bounded physical test but is also revoked: 49.0% of adjacent payloads were
duplicates in an almost strict pair pattern. It was rolled back to verified V1
and has no app descriptor. V4-LP2 (`0x61`) was then physically tested and
revoked for the same failure: 49.3976% paired duplicates during its active
lease. It was also rolled back to verified V1. Neither image is bundled as an
install choice.

Static analysis then confirmed that stock writes `WAKE_UP_THS=0x41`
(`SLEEP_ON=1`), `WAKE_UP_DUR=0x40` (`SLEEP_DUR=0`) and `CTRL7=0x20`
(`INTERRUPTS_ENABLE=1`). V6 is an off-ring single-variable experiment: Gesture
writes `WAKE_UP_THS=0x01`, while explicit stop, disconnect and lease expiry
restore exact stock 0x41. It retains V4's LP2 configuration and lease-only
renewal. V6 is hash-pinned in firmware provenance but is not bundled and has no
app descriptor or install route. A separate guarded CLI deployment passed DFU
CHECK and reboot identity. Its first bounded source test subsequently passed
with 250/250 distinct payloads at 25.0004 Hz, but Health continuity remains
unvalidated. A later 20-second run crossed two physical lease renewals with
501/501 distinct payloads and no boundary duplicates. The intended snap was
still classified as `flick left`, so firmware admission and RT12 model/domain
adaptation must remain separate gates.

The corrected firmware gate makes `A1 04` lease-only once Gesture is active:
only the lease byte changes, with no register writes, one-shot producer, or
timer restart. The app also waits for ten packets after renewal and compares
packet spacing and consecutive duplicates across the boundary; write success
alone is not accepted. Failure requests `A1 05` / `A1 02`, while the ten-second
firmware lease remains the final Health-return backstop.

The ten-second firmware lease is not a user-facing session limit. While the app
is active and successfully processing fresh motion, it renews V6 continuously.
The Gesture screen now persists a separate **Return to Health** policy: Off by
default, or 1/5/15/30 minutes. Off means no app timer; explicit return remains
available. App suspension, stale inference or disconnect still stops renewal
and therefore fails back to Health because no phone-side CNN can run then. The
future gesture-to-Health action belongs at the same explicit return boundary;
it is not enabled before RT12 classification is qualified. App version is
2.8.1 (1150); the focused 21-test UnifiedMode suite passes on iPhone 18 Pro
Simulator.

The first physical V1 deployment passed DFU CHECK/END, reboot, identity,
fingerprint and app-recognized Health default. Archived exact RT02 controls
measured 0.0333%-0.0556% duplicates. V4 and V5 failed the corrected-source gate
and were rolled back; neither validates any continuity gate. V6 must first pass
a separately authorized, bounded source-freshness test before optical Health,
long-term continuity or stock rollback testing is justified.
See `../docs/RT12COL_FIRMWARE.md` for provenance, exact patches and device gates.

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

RT12COL motion is rotated into the RT02/model coordinate system as
`[source0, source2, -source1]`. This is based on paired physical forward and
fingertips-down captures, not a hardware-label guess. Calibration remains a
down-only gate. Packet equality alone is not treated as stale delivery because
RT12 can quantize a stationary pose to repeated values; checksum, receipt age,
bounded gaps, monotonic sequence and the initial distinct-motion gate remain.

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

The Python engine (`probe.serve` / `probe.live`) writes live events to
`data/live/events_*.jsonl` with a `direction` field. Superseded 2026-09-28: the earlier
statement here that nothing in the app consumes events and that
`AppModel.gestureMappings` is static is historical. During a Gesture session the app
runs the pinned model itself, `GestureActionRouter` consumes every judged event through
the user's persisted mappings (`gestureMappings.v1`), and the app writes its own
`Documents/GestureEvents/events_*.jsonl` in the same nine-key format, which
`python -m probe.label join` reads unchanged. See the 2026-09-28 section at the top.

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
