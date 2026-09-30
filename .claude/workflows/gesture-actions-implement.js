export const meta = {
  name: 'gesture-actions-implement',
  description: 'Implement ring gesture->action mapping in the iOS app in 4 sequential stages',
  phases: [
    { title: 'Core types', detail: 'actions catalog, mappings store, event log, router, performers + tests' },
    { title: 'Session wiring', detail: 'AppRuntime, BLE stamping, AppModel transitions/recovery/background/idle + router wiring' },
    { title: 'Intents', detail: 'App Intents for Back Tap + intent logic tests' },
    { title: 'UI', detail: 'Gestures screen rewrite, action picker, setup sheets, render checks' },
  ],
}

const REPO = '/Users/akashanand/Claude_Whip'
const PLAN = '/Users/akashanand/.claude/plans/warm-growing-cherny.md'
const SCRATCH = '/private/tmp/claude-501/-Users-akashanand-Claude-Whip/a74645b3-40f6-4afb-ba08-d7866072a65f/scratchpad'
const SIM = '16398E1C-34E6-4BEE-B74D-628E24AACBCF'
const TEST_CMD = `cd ${REPO} && DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcodebuild test -project ios/R02Ring.xcodeproj -scheme R02Ring -destination 'platform=iOS Simulator,id=${SIM}' -derivedDataPath ${SCRATCH}/dd CODE_SIGNING_ALLOWED=NO`

const COMMON = `
You are one stage of a multi-stage implementation in the repo ${REPO} (iOS app under ios/R02Ring, SwiftUI, iOS 17 deployment target, Swift 5 language mode, Xcode project uses PBXFileSystemSynchronizedRootGroup so new .swift files under ios/R02Ring/ or ios/R02RingTests/ need NO pbxproj edits; Info.plist at ios/R02Ring/Info.plist is used directly).

SPEC: the user-approved plan at ${PLAN}. Read it fully before doing anything; it is authoritative for the iOS app work. The plan's separate firmware research track is OUT OF SCOPE — do not do any firmware analysis. Where the plan gives signatures, follow them unless the real code forces a small deviation — record every deviation.

HARD RULES:
- Other Claude sessions are working in this repo concurrently. Only edit files within your stage's scope. Never run git commit/checkout/reset/stash. Never touch firmware/, whip/fw*.py, ios/R02Ring/Health/FirmwareSwitching.swift, ios/R02Ring/Health/UnifiedMode.swift, or the numerics of GestureInference.swift / GestureBurstTracker.swift / GestureSession.swift (a comment-only edit to GestureSession.swift:139-140 is allowed where the plan says so).
- No Bluetooth, no ring/UART commands, no device deployment. Everything is offline + iOS Simulator.
- Keep existing behavior and all existing tests passing; do not weaken or edit existing tests' assertions. Existing freshness thresholds must not change.
- Tests: XCTest only, '@testable import R02Ring', '@MainActor' test classes where needed, isolated 'UserDefaults(suiteName: UUID().uuidString)' + removePersistentDomain, injectable clocks. Tests must NEVER construct AppModel (it creates a CBCentralManager).
- Match surrounding code style (terse, doc comments only where they explain non-obvious constraints). Fix any new compiler warnings in files you touch.

BUILD/TEST (always use this exact private DerivedData path and cloned simulator so you don't collide with other sessions; give Bash a 600000 ms timeout; write full output to a log file and only print the summary lines):
  mkdir -p ${SCRATCH}/logs
  ${TEST_CMD} > ${SCRATCH}/logs/<stage>-<n>.log 2>&1; echo EXIT=$?; grep -E "error:|warning: .*(Gesture|AppModel|AppRuntime|RingManager|Intent)|Test Suite 'All tests'|Executed [0-9]+ test|failed|TEST (SUCCEEDED|FAILED)" ${SCRATCH}/logs/<stage>-<n>.log | tail -40
  Focused run: append  -only-testing:R02RingTests/<ClassName>  to the command.
  Python: ${REPO}/.venv/bin/python -m pytest <paths> -q
If the simulator fails to boot or xcodebuild reports the device busy, retry once after 'xcrun simctl shutdown ${SIM}'.

Return the structured result honestly: if tests fail or something is unfinished, say so.`

const STAGE_SCHEMA = {
  type: 'object',
  properties: {
    filesCreated: { type: 'array', items: { type: 'string' } },
    filesModified: { type: 'array', items: { type: 'string' } },
    apiSummary: { type: 'string', description: 'Concise list of the types, functions and properties this stage added or changed that later stages must use, with exact signatures' },
    testsRun: { type: 'string', description: 'Exact commands and the summary lines (Executed N tests, M failures)' },
    allTestsPassed: { type: 'boolean' },
    totalTestsExecuted: { type: 'number' },
    failures: { type: 'array', items: { type: 'string' } },
    deviationsFromPlan: { type: 'array', items: { type: 'string' } },
    openIssues: { type: 'array', items: { type: 'string' } },
  },
  required: ['filesCreated', 'filesModified', 'apiSummary', 'testsRun', 'allTestsPassed', 'totalTestsExecuted', 'failures', 'deviationsFromPlan', 'openIssues'],
}

phase('Core types')
const s1 = await agent(`${COMMON}

STAGE 1 — Core types (plan "Phase 1" pure files + their tests). Scope: NEW files only, plus the fixture and one Python test. Do NOT edit AppModel.swift or any existing Swift file in this stage.

0. Before any edits, run the FULL existing test suite once and record the baseline (count, failures) in testsRun — label it BASELINE.
1. ios/R02Ring/Gesture/GestureActions.swift: GestureActionID (raw values exactly as the plan: none, pause_gestures, music_next, music_previous, music_play_pause, music_restart, music_toggle_shuffle, music_cycle_repeat, flag, approve, mark, ping_phone, swipe_up, swipe_down), GestureActionCategory (session, appleMusic, research, alerts, needsRingHID), GesturePermission (appleMusic, notifications), GestureActionInfo (title, detail, category, worksInBackground, lockedReason, permission) with honest user-facing detail text (swipe lockedReason: iOS doesn't let apps scroll other apps; would need the ring to act as a Bluetooth HID device — not available yet; does nothing). A code comment listing excluded actions and why (volume/MPVolumeView, torch, HomeKit, Run-Shortcut URL, speech). 'extension GestureID { init?(event: RingGestureEvent); var title: String }' (GestureID is declared in ios/R02Ring/Model/AppModel.swift — extend it, don't redeclare). GestureMappings (defaults: flick_up→swipe_up, flick_down→swipe_down, flick_right→music_next, flick_left→music_previous, snap→pause_gestures, all else none; overrides-only; subscript; reset; requiredPermissions) and GestureMappingStore(defaults: UserDefaults = .standard) with versioned JSON under key 'gestureMappings.v1' and safe fallbacks.
   Also the idle auto-pause policy as pure logic: 'enum GestureIdlePause: Int, CaseIterable, Identifiable { case off = 0, fiveMinutes = 300, fifteenMinutes = 900, thirtyMinutes = 1800 }' with seconds/title (default fifteenMinutes), and a small pure 'GestureIdleTracker' (injectable times, activity(at:), deadline, isExpired(at:)) so AppModel can drive a timer in stage 2.
2. ios/R02Ring/Gesture/GestureEventLog.swift: GestureEventLogging protocol, GestureEventLog (exact 9 Python keys, rounding, NSNull, relative t_s/end_s, wall injected, lazy open, append, serial utility io queue, sortedKeys lines — copy the pattern of ios/R02Ring/Gesture/GestureDiagnosticCapture.swift), GestureSessionJournal (lifecycle_yyyyMMdd.jsonl, never matching events_*), GestureStreamStats. Read whip/realtime.py (GestureEvent.as_dict, EventLog ~lines 55-70 and 468-489) and whip/labeling.py to match the contract exactly (verify rounding etc. against the Python source, don't guess).
3. ios/R02Ring/Gesture/GestureActionRouter.swift: GestureActionOutcome, GestureDispatch, GestureActionPerforming, HapticCue, HapticsPlaying, GestureActionRouter (Timing cooldown 0.75/settle 1.0, Context, begin/calibrated/end/route) implementing the plan's ordered rules exactly, including pause single-fire and stale-generation drop. Provide a way for AppModel to learn that a recognized gesture occurred (for idle reset) — e.g. dispatches with .gesture != nil; document it.
4. ios/R02Ring/Gesture/GestureActionPerformers.swift: PermissionState, MusicCommand, MusicControlling + SystemMusicController (MPMusicPlayerController.systemMusicPlayer created lazily only when authorized; MPMediaLibrary authorization; never prompt from background — requestAuthorization is only called by UI), NotificationPosting + LocalNotificationPoster (NSObject, UNUserNotificationCenterDelegate, immediate trigger nil, default sound, willPresent banner/sound/list), UIKitHaptics, GestureActionPerformer(music:notifications:pause:). Guard UIKit-only code appropriately.
5. Tests (new files in ios/R02RingTests/): GestureMappingTests, GestureActionRouterTests (fakes), GestureEventLogTests (temp dir root injection; parse lines back; key set == Python keys; fixture key parity), GestureStreamStatsTests, GestureIdleTests. Cover every bullet in the plan's Tests section items 1-3 and 6.
6. Fixture ios/R02RingTests/Fixtures/ios-event-log-sample.jsonl (3 lines in the Swift line shape: flag, approve, null) and Python tests/test_ios_event_log_contract.py asserting the key set equals set(GestureEvent(...).as_dict()) | {"action","wall"} and that whip.labeling load/join assigns the flag and approve lines to synthetic slots (read whip/labeling.py + tests/test_labeling.py for the exact API). Run it with the venv pytest together with tests/test_labeling.py.
7. Run focused tests for your new classes, then the FULL suite. All must pass.`, { label: 'stage1:core-types', phase: 'Core types', schema: STAGE_SCHEMA })

phase('Session wiring')
const s2 = await agent(`${COMMON}

STAGE 2 — Session wiring (plan "Phase 0" items 1-9 + "AppModel wiring" + Info.plist key). Stage 1 already created these files/types (use them, don't duplicate):
${JSON.stringify(s1, null, 1)}

Scope: ios/R02Ring/Model/AppRuntime.swift (new), ios/R02Ring/R02RingApp.swift, ios/R02Ring/Health/RingManager.swift (ONLY peripheral(_:didUpdateValueFor:) value/uuid/receivedAt capture before the hop + receiveUART(_:receivedAt:) signature; nothing else), ios/R02Ring/Model/AppModel.swift, a new ios/R02Ring/Model/GestureSessionControl.swift holding GestureSessionReason, GestureRequestOutcome, GestureRequestSource, GestureModeSnapshot, GestureStartReadiness, GestureTransition, ModeRecoveryPolicy and the GestureModeControlling protocol (see plan Phase 2 for the protocol shape — AppModel must conform in this stage so stage 3 can write intents against it), ios/R02Ring/Info.plist (add NSAppleMusicUsageDescription only), the comment update in GestureSession.swift:139-140, and the MINIMAL edits to ios/R02Ring/Screens/GesturesScreen.swift needed to compile (e.g. recentGestures -> lastDispatch, gestureStatus == "Ready" -> gestureReady); stage 4 rewrites that screen fully, so don't redesign it now.

Implement exactly: AppRuntime.shared ownership (ModelContainer with the same 5 record types, model.start(modelContext: container.mainContext), UNUserNotificationCenter delegate), RootView(model:) as @ObservedObject, .onChange(of: scenePhase, initial: true) -> model.scenePhaseChanged; BLE receipt stamping; gestureStatus assign-only-on-change + gestureReady + publish dispatches only when events exist + GestureStreamStats; gestureTransition + stopAfterEntry + setGestureSession(_:reason:) -> GestureRequestOutcome (@discardableResult, default reason .user so existing call sites compile); recoverModeControl + ModeRecoveryPolicy.shouldReattach (600 ms delay, same transport via modes.attach, guards from the plan); scenePhaseChanged background policy with keepGesturesInBackground (UserDefaults key 'gestureKeepActiveInBackground', default true when missing) and diagnostics cancel on background; persist haptics ('hapticsEnabled', default true); idle auto-pause (published 'gestureIdlePause' persisted, default fifteenMinutes, resets on every recognized gesture event, ends session with reason .idle; independent of the existing gestureAutoReturn timer which stays unchanged); gestureStartReadiness + requestGestureSession(_:source:readinessTimeout:) + modeAttachInFlight + deferring the automatic sync/settings refresh when an intent start is pending; router + performer + event log + journal wiring in runtimeModeChanged and the output closure (Context foreground from isAppActive, haptics, diagnostics suppression); replace placeholder GestureAction/gestureMappings/mappedCount with published GestureMappings + setMapping/resetMapping/resetAllMappings/requestPermission(_:) + published musicAuthorization/notificationAuthorization + gestureEventLogFiles()/deleteGestureEventLogs()/lastSessionSummary; Pause-gestures performer closure calls setGestureSession(false, reason: .gestureAction). Update the AppModel.swift:72-74 policy comment. Leave bug (c) charging recheck unfixed (comment it).

Read these first: ios/R02Ring/Model/AppModel.swift (whole file), ios/R02Ring/R02RingApp.swift, ios/R02Ring/Health/UnifiedMode.swift (read-only! understand attach/status/stopRaw/renew/failRenewal/disconnected), ios/R02Ring/Health/RingManager.swift around didUpdateValueFor/receiveUART, ios/R02RingTests/UnifiedModeTests.swift (fakes).

Tests: ModeRecoveryTests (policy truth table; coordinator-level: fake transport renew throws -> available false -> modes.attach(same transport) -> available true + Health; A1-level: A1UnifiedModeTransport with lease 10 driven into gesture, renew guard failure sends no stops, then coordinator.attach writes [A1 05, A1 02, 3B 02 01 00] — use the real packet builders in RingProtocol.swift for expected bytes). Also unit-test any pure helpers you add (readiness computation if extracted as a pure function). Run focused then FULL suite; all must pass.`, { label: 'stage2:session-wiring', phase: 'Session wiring', schema: STAGE_SCHEMA })

phase('Intents')
const s3 = await agent(`${COMMON}

STAGE 3 — App Intents (plan "Phase 2"). Prior stages:
STAGE1: ${JSON.stringify(s1, null, 1)}
STAGE2: ${JSON.stringify(s2, null, 1)}

Scope: ios/R02Ring/Intents/GestureIntentLogic.swift (no AppIntents import: toggle/start/stop -> GestureIntentReply, waitUntil; readiness timeout 10 s), ios/R02Ring/Intents/GestureModeIntents.swift (ToggleGestureSessionIntent + StartGestureSessionIntent: AppIntent & ForegroundContinuableIntent using needsToContinueInForegroundError with a continuation that calls AppRuntime.shared.model.openGesturesAfterIntent(startWhenReady:); StopGestureSessionIntent background-only, title 'Pause Gestures (Return to Health)'; R02Shortcuts: AppShortcutsProvider with phrases each containing \\(.applicationName)), ios/R02RingTests/GestureIntentLogicTests.swift (fake GestureModeControlling). If AppModel needs openGesturesAfterIntent or small conformance fixes, you may make minimal edits to AppModel.swift / GestureSessionControl.swift — record them.
Verify via the local SDK (grep the AppIntents .swiftinterface in the iOS simulator SDK under /Applications/Xcode.app) the exact availability and signatures of ForegroundContinuableIntent, needsToContinueInForegroundError, AppShortcut, AppShortcutsProvider before writing code; ensure no deprecation warnings at iOS 17 deployment target. After building, confirm App Intents metadata extraction ran (look in the build log for 'ExtractAppIntentsMetadata' / appintentsmetadataprocessor and any errors/warnings about phrases). Run focused then FULL suite.`, { label: 'stage3:intents', phase: 'Intents', schema: STAGE_SCHEMA })

phase('UI')
const s4 = await agent(`${COMMON}

STAGE 4 — UI (plan "Phase 3") + SettingsScreen subtitle. Prior stages:
STAGE1: ${JSON.stringify(s1, null, 1)}
STAGE2: ${JSON.stringify(s2, null, 1)}
STAGE3: ${JSON.stringify(s3, null, 1)}

Scope: ios/R02Ring/Design/Components.swift (move ActivityView + SettingsRow from SettingsScreen.swift and make internal; add ActionBadge, SheetScaffold), ios/R02Ring/Screens/SettingsScreen.swift (use moved components; haptics subtitle 'Confirms gesture actions while R02 is open'; do NOT change DFU/firmware text), ios/R02Ring/Screens/GesturesScreen.swift (full rewrite per plan: session panel with Start/Return reflecting gestureTransition, session-timer picker, idle-pause picker, keep-in-background RingToggle + explainer, status, last dispatch line, last session summary, charging note; permission rows only when needed (request if notDetermined, open UIApplication.openSettingsURLString if denied); 11-cell grid with mapped action title + ActionBadge, tap opens picker sheet via .sheet(item:); rows: Back Tap setup, research event log share/delete (confirmation), reset all mappings (confirmation), waveform diagnostics sheet (existing capture workflow moved here, gated on gestureReady); footnotes with the probe.label join hint and a short note that swipe actions are locked because iOS apps can't scroll other apps; keep Health dashboard OutlineButton; remove 'Mappings are previews…'), ios/R02Ring/Screens/GestureActionPicker.swift (new), ios/R02Ring/Screens/GestureSetupSheets.swift (new: BackTapGuideSheet with exact steps using the Shortcuts action names you find in the stage-3 intents; GestureDiagnosticsSheet). Follow the design system strictly: read Tokens.swift, Components.swift, SettingsScreen.swift, GesturesScreen.swift, TodayScreen.swift first; mono/serif fonts, Tok colors, hairlines, 44pt tap targets, dark-only; accessibility labels on every interactive element (include 'works in background' / 'locked').
Keep the existing GestureTile animations in cells. The Gestures tab has no NavigationStack — use sheets.

Render check: add ios/R02RingTests/GestureScreensRenderTests.swift that renders (ImageRenderer, 393x852 @3x, dark) the GestureActionPickerSheet, BackTapGuideSheet and a GestureCell grid preview WITHOUT constructing AppModel (factor views so they take plain values/closures), asserting non-nil images; when the env var WHIP_RENDER_DIR is set, also write PNGs there. Run it with 'TEST_RUNNER_WHIP_RENDER_DIR=${SCRATCH}/renders' prefixed to the xcodebuild command, then open the PNGs with the Read tool and visually check them (spacing, clipping, legibility, alignment with the rest of the app); fix issues you see. Then run the FULL suite; all must pass. Also do a Release build: same command but 'build -configuration Release' instead of 'test'. Report render file paths in apiSummary.`, { label: 'stage4:ui', phase: 'UI', schema: STAGE_SCHEMA })

return { s1, s2, s3, s4 }