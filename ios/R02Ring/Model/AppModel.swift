import SwiftUI
import SwiftData
#if canImport(UIKit)
import UIKit
#endif

// MARK: - Navigation

enum Tab: String, CaseIterable, Identifiable {
    case today, gestures, settings
    var id: String { rawValue }
    static let healthTabs: [Tab] = [.today, .gestures, .settings]
    var title: String {
        switch self {
        case .today:    return "Today"
        case .gestures: return "Gestures"
        case .settings: return "Settings"
        }
    }
}

enum Metric: String, Hashable, Identifiable, CaseIterable {
    case sleep, heartRate, steps
    var id: String { rawValue }

    /// Uppercased by the label style; stored in sentence case so it reads in code.
    var title: String {
        switch self {
        case .sleep:     return "Sleep"
        case .heartRate: return "Heart rate"
        case .steps:     return "Steps"
        }
    }

    /// Health details open on a day-by-day week. Longer ranges remain available
    /// from the range picker and intentionally aggregate to keep their charts legible.
    var defaultRange: MetricRange {
        switch self {
        case .sleep:     return .week
        case .heartRate: return .week
        case .steps:     return .week
        }
    }
}

enum MetricRange: String, CaseIterable, Identifiable {
    case week, month, sixMonths, year
    var id: String { rawValue }
    var label: String {
        switch self {
        case .week:      return "W"
        case .month:     return "M"
        case .sixMonths: return "6M"
        case .year:      return "Y"
        }
    }
}

enum Units: String, CaseIterable {
    case metric = "Metric", imperial = "Imperial"
}

// MARK: - Gestures

enum GestureID: String, CaseIterable, Identifiable {
    case flick_up, flick_down, flick_left, flick_right
    case double_flick_up, double_flick_down, double_flick_left, double_flick_right
    case snap
    case double_clap
    case wave

    var id: String { rawValue }
}

/// User-facing session timer. The firmware's short lease remains an invisible
/// crash backstop; while a session is wanted (in front, or in the background
/// when `keepGesturesInBackground` is on) the app renews Gesture, and heals it
/// after stale data, a failed renewal, a lapsed lease or a brief disconnect,
/// until this timer, the idle pause, the Return button, an App Intent, a
/// gesture mapped to Pause gestures, the charger, or the ring staying gone
/// past the heal window ends the session (`GestureEndReason`).
enum GestureAutoReturn: Int, CaseIterable, Identifiable {
    case off = 0
    case oneMinute = 60
    case fiveMinutes = 300
    case fifteenMinutes = 900
    case thirtyMinutes = 1_800

    var id: Int { rawValue }
    var seconds: TimeInterval? { self == .off ? nil : TimeInterval(rawValue) }
    var title: String {
        switch self {
        case .off: return "Off"
        case .oneMinute: return "1 minute"
        case .fiveMinutes: return "5 minutes"
        case .fifteenMinutes: return "15 minutes"
        case .thirtyMinutes: return "30 minutes"
        }
    }
}

// MARK: - Device & user

struct RingDevice {
    var id = "No ring"
    var firmware = "—"
    var hardware = "—"
    var batteryPercent: Int?
    var charging = false
    var linked = false
    var lastSync: Date?
}

struct User {
    var name = "Maya Kestrel"
    var email = "maya.kestrel@hey.com"
    var initials = "MK"
}

// MARK: - App state

@MainActor
final class AppModel: ObservableObject {
    @Published var selectedTab: Tab = .today
    @Published var selectedMetric: Metric?

    @Published var haptics: Bool {
        didSet { UserDefaults.standard.set(haptics, forKey: Self.hapticsKey) }
    }
    @Published var heartRateLogging = false
    @Published private(set) var heartRateSettingsKnown = false
    @Published private(set) var heartRateIntervalMinutes = 5
    @Published var units: Units = .metric
    @Published var gestureAutoReturn: GestureAutoReturn {
        didSet {
            UserDefaults.standard.set(gestureAutoReturn.rawValue, forKey: Self.gestureAutoReturnKey)
            scheduleGestureAutoReturn(fromNow: true)
        }
    }
    /// Off restores the old policy: leaving R02 returns the ring to Health.
    @Published var keepGesturesInBackground: Bool {
        didSet { GestureBackgroundSessions.store(keepGesturesInBackground) }
    }
    /// Independent of `gestureAutoReturn`: this deadline moves with every recognized gesture.
    @Published var gestureIdlePause: GestureIdlePause {
        didSet {
            gestureIdlePause.store()
            idleTracker.policy = gestureIdlePause
            scheduleIdlePause()
        }
    }
    @Published private(set) var gestureMappings: GestureMappings {
        didSet {
            mappingStore.save(gestureMappings)
            router.mappings = gestureMappings
        }
    }
    @Published private(set) var musicAuthorization: PermissionState = .notDetermined
    @Published private(set) var notificationAuthorization: PermissionState = .notDetermined

    @Published var ring = RingDevice()
    @Published var user = User()
    @Published var today = HealthData.emptyToday()
    @Published var isSyncing = false
    @Published var isMeasuringHeartRate = false
    @Published var liveHeartRate: Int?
    @Published var syncMessage = "Not synced"
    @Published private(set) var firmwareMode: RingFirmwareMode = .unknown
    @Published private(set) var firmwareFamily: RingHardwareFamily?
    @Published private(set) var unifiedFirmwareInstalled = false
    /// True only after the installed V8 code and every changed source/lease/HID
    /// region match the pinned bundle. Version text alone never enables A2.
    @Published private(set) var ringHIDFirmwareInstalled = false
    /// 0 when unavailable, otherwise the exact fingerprinted A2 wire revision.
    @Published private(set) var ringHIDVersion = 0
    @Published private(set) var isFirmwareSwitching = false
    @Published private(set) var firmwareProgress = 0.0
    @Published private(set) var lastFirmwareSwitchDuration: TimeInterval?
    @Published private(set) var lastFirmwareTransferDuration: TimeInterval?
    @Published private(set) var dataRevision = 0
    @Published private(set) var gestureStatus = "Health is the default. Start a Gesture session when needed."
    /// The fingers-down calibration completed for the running session.
    @Published private(set) var gestureReady = false
    /// Mirrors the sequencer, for the session panel.
    @Published private(set) var gestureTransition: GestureTransition?
    /// A start is waiting for the ring or entering, or a Shortcut's start is
    /// continuing in R02. A stop request withdraws it.
    @Published private(set) var gestureStartPending = false
    /// Why the last Shortcut start that continued in R02 started no session.
    /// Mirrors `GestureStartHolds`; a session reaching Gesture clears it.
    @Published private(set) var intentStartMessage: String?
    /// Why the panel's last Start/Return tap did not succeed. Model-owned so a
    /// session started elsewhere (a Back Tap while R02 is in the background)
    /// clears it even when the panel missed the mode change.
    @Published private(set) var panelRequestMessage: String?
    @Published private(set) var lastDispatch: GestureDispatch?
    @Published private(set) var lastSessionSummary: String?
    /// An attach, or a scheduled mode-control recovery, is pending.
    @Published private(set) var modeAttachInFlight = false
    @Published private(set) var isAppActive = false
    /// Identification and the first mode attach finished for this connection.
    @Published private(set) var connectionSetupComplete = false
    @Published private(set) var diagnosticPrompt = ""
    @Published private(set) var diagnosticProgress = ""
    @Published private(set) var diagnosticCaptureName: String?
    @Published private(set) var diagnosticRecording = false
    @Published private(set) var healthCoverageMessage: String?
    /// The user wants gestures: a sticky session, running or healing. Only a
    /// `GestureEndReason` clears it (see `GestureSessionPolicy`).
    @Published private(set) var gestureDesired = false
    /// A heal is re-entering Gesture for the desired session.
    @Published private(set) var gestureHealing: GestureHealStatus?
    let modes: UnifiedModeCoordinator

    let ringManager = RingManager()
    let musicController = SystemMusicController()
    /// Retained here: the notification center holds its delegate weakly.
    let notificationPoster = LocalNotificationPoster()
    private var healthStore: HealthStore?
    private var coverageStore: HealthCoverageStore?
    private var ringClient: ColmiR02Client?
    private var syncService: HealthSyncService?
    private var measurementTask: Task<Void, Never>?
    private var lastSyncSucceeded = false
    private let operations: RingOperationGate
    private var firmwareOperation: UUID?
    private var gestureDriver: GestureSession?
    private var gestureGeneration: UUID?
    private var diagnosticRecorder: GestureDiagnosticRecorder?
    private var diagnosticTask: Task<Void, Never>?
    private var gestureSensorCalibration: GestureSensorCalibration = .identity
    private var heartbeatTask: Task<Void, Never>?
    private var gestureAutoReturnTask: Task<Void, Never>?
    private var started = false
    private var pendingFirmwareTarget: RingFirmwareMode?
    private var firmwareSwitchStartedAt: Date?
    private var a1ModeTransport: A1UnifiedModeTransport?
    private let lastSyncKeyPrefix = "lastHealthSync."
    private static let gestureAutoReturnKey = "gestureAutoReturnSeconds"
    private static let hapticsKey = "hapticsEnabled"
    /// DEBUG-only launch argument (`-R02InitialTab gestures`) for simulator smoke tests.
    private static let initialTabArgument = "R02InitialTab"

    /// The running ring session's recognition (one segment of a user session).
    private var sessionRecord: SessionRecord?
    /// Whether the user wants gestures; see `GestureDesire`.
    private var desire = GestureDesire()
    /// The user's session, across heals.
    private var userSession: UserSession?
    /// The calibration frame found in the running user session.
    private var sessionFrame: String?
    /// `GestureContinuousTime` of the last processed output or passed renewal.
    private var lastGoodAt: Double?
    private var autoReturnDeadline: Double?
    private var consecutiveRenewalMisses = 0
    private var intentCalibrationWaits = 0
    /// Uptime when a start intent last answered after its calibration wait.
    private var lastStartIntentReplyAt: Double?
    private var enforceTask: Task<Void, Never>?
    /// Bumped by each `enforceHealth`, so a finished loop clears `enforcing` only for itself.
    private var enforceGeneration = 0
    private var enforcing = false
    /// The event log of a user session whose first segment has not begun.
    private var pendingEventLog: GestureEventLog?
    private var giveUpNoticeAt: Double?
    private var isRouting = false
    private var pauseRequested = false
    #if canImport(UIKit)
    private var healBackgroundTask: UIBackgroundTaskIdentifier = .invalid
    #endif
    /// Loaded and warmed off the main thread once, then shared by sessions.
    private var gestureClassifier: PinnedGestureClassifier?
    private var gestureClassifierLoading = false
    private var gestureClassifierLoadMS: Int?
    /// How the running session got its model, for `session_start`.
    private var gestureModelSource = "unknown"
    private var lastScenePhase = "unknown"
    private var lastScenePhaseAt = ProcessInfo.processInfo.systemUptime
    private var lastIntentAt: Double?
    private var startStamp = GestureStartStamp()
    private var automaticEnd = GestureModeSnapshot.AutomaticEndTracker()
    private lazy var mainWatchdog = MainQueueWatchdog { [weak self] delay in
        MainActor.assumeIsolated { self?.mainQueueStalled(delay) }
    }
    private static let buildConfiguration: String = {
        #if DEBUG
        return "debug"
        #else
        return "release"
        #endif
    }()
    private var streamStats = GestureStreamStats()
    private var idleTracker: GestureIdleTracker
    private var idleTask: Task<Void, Never>?
    private var activeEventLogURL: URL?
    private let journal = GestureSessionJournal()
    private let mappingStore = GestureMappingStore()

    /// The foreground hold, a Shortcut's continuation in R02, the health
    /// refresh deferred while either (or a sequencer start) holds the ring, and
    /// the failure messages a start leaves behind.
    private lazy var startHolds: GestureStartHolds = {
        let holds = GestureStartHolds(.init(
            pendingStarts: { [unowned self] in self.sessions.pendingStarts },
            healthRefreshAllowed: { [unowned self] in self.ringManager.isReady && self.healthSyncEnabled },
            refreshHealth: { [unowned self] full in
                Task {
                    await self.refreshHealthSettings()
                    await self.sync(full: full)
                }
            },
            sessionHoldsRing: { [unowned self] in self.desire.isOn }
        ))
        holds.onChange = { [unowned self] in self.startHoldsChanged() }
        return holds
    }()

    private lazy var sessions: GestureSessionSequencer = {
        let sequencer = GestureSessionSequencer(.init(
            setGesture: { [unowned self] in try await self.modes.setGesture($0) },
            isGestureMode: { [unowned self] in self.isRuntimeGestureMode },
            modeControlAvailable: { [unowned self] in self.modes.available },
            linkReady: { [unowned self] in self.ringManager.isReady },
            willEnter: { [unowned self] in self.prepareMusicIfMapped(beforeEntry: true) }
        ))
        sequencer.onTransitionChange = { [unowned self] transition in
            if self.gestureTransition != transition { self.gestureTransition = transition }
        }
        sequencer.onPendingStartsChange = { [unowned self] _ in self.updateStartPending() }
        sequencer.onStatus = { [unowned self] in self.setGestureStatus($0) }
        sequencer.onJournal = { [unowned self] kind, fields in
            var fields = fields
            fields["foreground"] = self.isAppActive
            self.journal.record(kind, fields: fields)
        }
        return sequencer
    }()

    private lazy var modeRecovery: ModeRecoveryController = {
        let controller = ModeRecoveryController()
        controller.onInFlightChange = { [unowned self] inFlight in
            if self.modeAttachInFlight != inFlight { self.modeAttachInFlight = inFlight }
        }
        controller.onEvent = { [unowned self] event in self.modeRecoveryEvent(event) }
        return controller
    }()

    /// One ring session (segment): the user's session's first entry, or a heal.
    private struct SessionRecord {
        let session: UInt32
        let startedUptime: Double
        /// start or heal.
        let trigger: String
        var firstPredictLogged = false
        var mainStalls = 0
    }

    /// The user's session, from desire on to its end, across heals.
    private struct UserSession {
        let epoch: Int
        let reason: GestureSessionReason
        let startedUptime: Double
        var segments = 0
        var heals = 0
        var recognized = 0
        var performed = 0
        var renewals = 0
    }

    private lazy var keeper: GestureSessionKeeper = {
        let keeper = GestureSessionKeeper(.init(
            isDesired: { [unowned self] in self.desire.isOn },
            linkReady: { [unowned self] in self.ringManager.isReady },
            readiness: { [unowned self] in
                GestureStartReadiness.evaluate(self.gestureModeSnapshot, ignoringDesire: true)
            },
            leaseBackstop: { [unowned self] in (self.a1ModeTransport?.leaseSeconds ?? 0) > 0 },
            // healEpoch is read here, with no suspension since the keeper
            // checked that the session is still wanted.
            restart: { [unowned self] in await self.sessions.restart(epoch: self.sessions.healEpoch) },
            requestReattach: { [unowned self] in self.requestReattach() },
            sessionDeadline: { [unowned self] in self.passedSessionDeadline() },
            hadFrame: { [unowned self] in self.sessionFrame != nil },
            lastGoodAt: { [unowned self] in self.lastGoodAt },
            inBackground: { [unowned self] in !self.isAppActive }
        ))
        keeper.onJournal = { [unowned self] kind, fields in
            var fields = self.phaseFields(fields)
            fields["epoch"] = self.desire.epoch
            self.journal.record(kind, fields: fields)
        }
        keeper.onGiveUp = { [unowned self] reason, cause, detail in
            self.healGaveUp(reason, cause: cause, detail: detail)
        }
        keeper.onStatusChange = { [unowned self] status in self.healStatusChanged(status) }
        keeper.onEpisodeActive = { [unowned self] active in self.setHealBackgroundTask(active) }
        return keeper
    }()

    /// "Gestures ready ✓", at most once per arm.
    private lazy var announcer = GestureReadyAnnouncer(notifications: notificationPoster)

    private lazy var router: GestureActionRouter = {
        let performer = GestureActionPerformer(
            music: self.musicController, notifications: self.notificationPoster,
            ringHID: self,
            pause: { [weak self] in self?.pauseFromGesture() }
        )
        #if canImport(UIKit)
        let haptics: HapticsPlaying? = UIKitHaptics()
        #else
        let haptics: HapticsPlaying? = nil
        #endif
        return GestureActionRouter(mappings: self.gestureMappings, performer: performer, haptics: haptics)
    }()

    var recentDispatches: [GestureDispatch] { router.recentDispatches }

    var firmwareOptions: [BundledFirmware] {
        let installedVersion = ringManager.firmware ?? ring.firmware
        return BundledFirmware.routedCatalog(
            hardware: ringManager.hardware ?? ring.hardware,
            firmware: installedVersion
        ).filter { !$0.isInstalled(mode: firmwareMode, version: installedVersion) }
    }

    var firmwareRoutingMessage: String {
        let hardware = ringManager.hardware ?? ring.hardware
        let firmware = ringManager.firmware ?? ring.firmware
        guard let family = RingHardwareFamily.route(hardware: hardware, firmware: firmware) else {
            return "Connect a ring with a consistent hardware and firmware identity. Unknown or conflicting identities cannot be flashed."
        }
        return "Only images for the detected \(family.title) family are shown."
    }

    let appVersion = "R02 · 2.8.1 (1150)"

    init() {
        let defaults = UserDefaults.standard
        gestureAutoReturn = GestureAutoReturn(
            rawValue: defaults.integer(forKey: Self.gestureAutoReturnKey)
        ) ?? .off
        haptics = defaults.object(forKey: Self.hapticsKey) as? Bool ?? true
        keepGesturesInBackground = GestureBackgroundSessions.stored(in: defaults)
        let idlePause = GestureIdlePause.stored(in: defaults)
        gestureIdlePause = idlePause
        idleTracker = GestureIdleTracker(policy: idlePause)
        gestureMappings = GestureMappingStore(defaults: defaults).load()
        let gate = RingOperationGate()
        operations = gate
        modes = UnifiedModeCoordinator(gate: gate)
        modes.onModeChange = { [weak self] previous, current in
            self?.runtimeModeChanged(previous: previous, current: current)
        }
        // A session a previous process left on ended when iOS closed R02:
        // report it once. Nothing is restarted.
        if let marker = GestureSessionMarker.take(from: defaults) {
            Task { [weak self] in await self?.reportTerminatedSession(marker) }
        }
        #if DEBUG
        // Read once, from the launch arguments only: never persisted, no effect in Release.
        if let raw = defaults.volatileDomain(forName: UserDefaults.argumentDomain)[Self.initialTabArgument] as? String,
           let tab = Tab(rawValue: raw) {
            selectedTab = tab
        }
        #endif
    }

    // MARK: Gesture session control

    private var isRuntimeGestureMode: Bool {
        modes.status?.mode == .gesture || modes.status?.mode == .enteringGesture
    }

    /// Every event that could end a session or take the ring out of Gesture
    /// goes through `GestureSessionPolicy`: only an allowed `GestureEndReason`
    /// ends the user's session; stale data, failed renewals, a lapsed lease,
    /// reconnects and lost control pause recognition and heal.
    private func handle(_ trigger: GestureSessionTrigger, detail: String? = nil) {
        switch GestureSessionPolicy.disposition(trigger) {
        case .end(let reason):
            beginEnd(reason, detail: detail)
        case .heal(let cause):
            guard desire.isOn else { return }
            stopSegment(cause: trigger.rawValue)
            if trigger == .linkLost { keeper.linkLost() } else { keeper.fault(cause, detail: detail) }
            if keeper.isHealing { setGestureStatus(keeper.status?.statusText ?? "Reconnecting gestures…") }
        case .missedRenewal, .none:
            journal.record("session_trigger", fields: phaseFields([
                "trigger": trigger.rawValue, "detail": detail.map { $0 as Any } ?? NSNull(),
            ]))
        }
    }

    /// Ends the user's session: the desired state clears synchronously, so no
    /// heal, renewal or recognition follows, then the ring returns to Health.
    private func beginEnd(_ reason: GestureEndReason, detail: String?, healCause: GestureHealCause? = nil) {
        endUserSession(reason, detail: detail, healCause: healCause)
        Task { await self.returnToHealth(reason.sessionReason) }
    }

    /// Skipped when a session turned on, or a start began entering from
    /// Health, since the end: that start owns the ring, and a stop now would
    /// be held and sent right after its A1 04. An orphan left meanwhile is
    /// still enforced (`enforceHealth`), and the lease backs it.
    private func returnToHealth(_ reason: GestureSessionReason) async {
        guard GestureOwnership.returnToHealthApplies(
            desireOn: desire.isOn, desireArming: desire.isArming,
            transition: sessions.transition, enteringReason: sessions.enteringReason
        ) else {
            journal.record("return_skipped", fields: phaseFields(["reason": reason.rawValue,
                                                                  "desire": "\(desire.state)"]))
            startHolds.runDeferredHealthRefreshIfNeeded()
            return
        }
        let outcome = await sessions.setSession(false, reason: reason)
        if !outcome.succeeded { enforceHealth() }
        startHolds.runDeferredHealthRefreshIfNeeded()
    }

    /// Gesture no session wants (`GestureOwnership.orphan`), judged without
    /// the arming of a start that waits for readiness.
    private var orphanGesture: Bool {
        GestureOwnership.orphan(desireOn: desire.isOn, desireArming: desire.isArming,
                                ringInGesture: isRuntimeGestureMode, transition: sessions.transition,
                                enteringReason: sessions.enteringReason)
    }

    /// The ring streams Gesture that no session wants (a pause whose stop
    /// failed, or an entry a stop won): retries the audited stop while it
    /// stays an orphan. A start that arms meanwhile does not cancel it (it
    /// waits `.returning` for this return); a session turning on, or a start
    /// entering from Health, ends it. The firmware lease returns the ring
    /// anyway once nothing renews.
    private func enforceHealth() {
        guard !desire.isOn else { return }
        enforceGeneration &+= 1
        let generation = enforceGeneration
        enforcing = true
        enforceTask?.cancel()
        enforceTask = Task { [weak self] in
            defer { if let self, self.enforceGeneration == generation { self.enforcing = false } }
            for attempt in 0..<5 {
                if attempt > 0 {
                    do { try await Task.sleep(for: .seconds(1)) } catch { return }
                }
                guard let self, self.orphanGesture else { return }
                let outcome = await self.sessions.setSession(false, reason: .orphan)
                if outcome.succeeded { return }
            }
        }
    }

    /// Makes sure an orphan is being returned to Health, without restarting
    /// an enforcement already under way.
    private func ensureHealthEnforced() {
        guard orphanGesture, !enforcing else { return }
        enforceHealth()
    }

    /// The pause gesture: runs inside the router's dispatch, so the end is
    /// taken right after routing returns (its counts are kept); the router
    /// already suppresses later events.
    private func pauseFromGesture() {
        guard desire.isOn else { return }
        if isRouting { pauseRequested = true } else { handle(.pauseGesture) }
    }

    private func setGestureStatus(_ text: String) {
        if gestureStatus != text { gestureStatus = text }
    }

    private func publishDesire() {
        if gestureDesired != desire.isOn { gestureDesired = desire.isOn }
    }

    /// The exact-image A1 adapter assigns a connection-bound monotonic sequence
    /// to each checksum-valid accelerometer notification at BLE receipt.
    func acceptMotionSample(_ packet: Data, session: UInt32, sequence: UInt32, receivedAt: Double) {
        guard modes.available, modes.status?.mode == .gesture, modes.status?.session == session else { return }
        diagnosticRecorder?.append(packet: packet, receivedAt: receivedAt)
        gestureDriver?.ingest(packet, session: session, sequence: sequence, receivedAt: receivedAt)
    }

    func startGestureDiagnosticWorkflow(repetitions: Int = 3) {
        guard !diagnosticRecording, modes.status?.mode == .gesture, gestureReady else {
            diagnosticProgress = "Start Gesture mode and complete the fingers-down calibration first."
            return
        }
        do {
            let recorder = try GestureDiagnosticRecorder(
                name: ring.id,
                hardware: ringManager.hardware ?? ring.hardware,
                firmware: ringManager.firmware ?? ring.firmware,
                deviceID: activeDeviceID,
                signalCalibration: gestureSensorCalibration
            )
            diagnosticRecorder = recorder
            diagnosticRecording = true
            diagnosticCaptureName = nil
            let prompts = GestureDiagnosticPlan.prompts(repetitions: repetitions)
            diagnosticTask = Task { [weak self] in
                guard let self else { return }
                do {
                    self.diagnosticPrompt = "Get ready"
                    self.diagnosticProgress = "Recording a quiet pre-roll"
                    try await Task.sleep(for: .seconds(2))
                    for (index, prompt) in prompts.enumerated() {
                        for count in stride(from: 3, through: 1, by: -1) {
                            try Task.checkCancellation()
                            self.diagnosticPrompt = "Next: \(prompt.spoken) · \(count)"
                            self.diagnosticProgress = "\(index + 1) of \(prompts.count)"
                            try await Task.sleep(for: .seconds(1))
                        }
                        try Task.checkCancellation()
                        self.diagnosticRecorder?.mark(prompt, at: ProcessInfo.processInfo.systemUptime)
                        self.diagnosticPrompt = "NOW: \(prompt.spoken)"
                        try await Task.sleep(for: .seconds(3))
                    }
                    self.diagnosticPrompt = "Natural movement"
                    self.diagnosticProgress = "30-second ambient tail"
                    try await Task.sleep(for: .seconds(30))
                    // Saving the capture ends nothing: the session stays on until the user stops it.
                    self.finishGestureDiagnostic(cancelled: false)
                    self.handle(.diagnosticsFinished)
                } catch is CancellationError {
                    self.finishGestureDiagnostic(cancelled: true)
                } catch {
                    self.diagnosticProgress = error.localizedDescription
                    self.finishGestureDiagnostic(cancelled: true)
                }
            }
        } catch {
            diagnosticProgress = "Could not start capture: \(error.localizedDescription)"
        }
    }

    func cancelGestureDiagnosticWorkflow() {
        diagnosticTask?.cancel()
        diagnosticTask = nil
        finishGestureDiagnostic(cancelled: true)
    }

    private func finishGestureDiagnostic(cancelled: Bool) {
        let recorder = diagnosticRecorder
        diagnosticRecorder = nil
        diagnosticRecording = false
        diagnosticTask = nil
        diagnosticPrompt = ""
        guard let recorder else { return }
        do {
            diagnosticCaptureName = try recorder.finish(cancelled: cancelled)
            diagnosticProgress = cancelled ? "Saved partial capture \(recorder.sessionID)" : "Saved \(recorder.sessionID)"
        } catch {
            diagnosticProgress = "Capture close failed: \(error.localizedDescription)"
        }
    }

    private func runtimeModeChanged(previous: ModeStatus?, current: ModeStatus?) {
        // Before the charging guard, so a charging-refused entry counts too:
        // the ring did reach Gesture, whatever started it.
        startHolds.modeChanged(to: current?.mode)
        // Read before anything else: the entry in flight that published this.
        let enteringReason = sessions.enteringReason
        // Recognition, routing and renewal belong to one ring session (a
        // segment); the user's session, its timers and log outlive it.
        stopSegment(cause: current.map { "mode_\($0.mode.rawValue)" } ?? "control_lost")
        if let current, let deviceID = activeDeviceID {
            do { try coverageStore?.observe(deviceID: deviceID, mode: current.mode, firmware: ring.firmware, at: .now) }
            catch { syncMessage = "Could not record health coverage: \(error.localizedDescription)" }
        }
        if current == nil { scheduleModeRecovery() }
        guard let current, current.mode == .gesture, !current.charging else {
            if diagnosticRecording { cancelGestureDiagnosticWorkflow() }
            if desire.isOn {
                modeLeftWhileDesired(current)
            } else {
                setGestureStatus(current?.mode == .health ? "Health mode · gesture recognition off" : "Gesture recognition paused")
                if current?.mode == .health { startHolds.runDeferredHealthRefreshIfNeeded() }
            }
            return
        }
        switch desire.state {
        case .arming(let epoch) where enteringReason == .user || enteringReason == .intent:
            desire.reached(epoch: epoch, at: GestureContinuousTime.now())
            publishDesire()
            beginUserSession(current, reason: enteringReason ?? .user)
            beginSegment(current, trigger: "start", presetFrame: nil)
        case .on where enteringReason != nil:
            // A heal re-entered Gesture: keep the calibration frame only when
            // the heal was quick and the link never dropped.
            let keep = keeper.hasEpisode ? keeper.resumed() : false
            let preset = keep ? sessionFrame : nil
            if preset == nil {
                sessionFrame = nil
                announcer.healNeedsCalibration(epoch: desire.epoch, appActive: isAppActive)
                setGestureStatus("Reconnected · hold fingers down to recalibrate")
            }
            beginSegment(current, trigger: "heal", presetFrame: preset)
        default:
            // No session wants Gesture (a stop won the race): never recognize,
            // and make sure the ring returns to Health.
            setGestureStatus("Returning to Health")
            journal.record("orphan_gesture", fields: phaseFields([
                "session": Int(current.session), "desire": "\(desire.state)",
                "entering": enteringReason?.rawValue ?? NSNull(),
            ]))
            enforceHealth()
        }
    }

    /// The ring left Gesture, or control was lost, while the user still wants
    /// gestures. A heal's own stop half and re-attach are expected; anything
    /// else heals. Disconnects were reported by `onDisconnect` already.
    private func modeLeftWhileDesired(_ current: ModeStatus?) {
        if current == nil {
            if ringManager.isReady { handle(.controlLost) } else { keeper.linkLost() }
        } else if current?.mode == .health {
            if !sessions.restarting { handle(.unexpectedHealth) }
        } else if current?.mode != .enteringGesture {
            handle(.controlLost, detail: current.map { "mode_\($0.mode.rawValue)" })
        }
        if keeper.isHealing { setGestureStatus(keeper.status?.statusText ?? "Reconnecting gestures…") }
    }

    /// The user's session begins: desire just turned on.
    private func beginUserSession(_ status: ModeStatus, reason: GestureSessionReason) {
        let now = ProcessInfo.processInfo.systemUptime
        let continuous = GestureContinuousTime.now()
        let log = GestureEventLog(streamStart: now)
        pendingEventLog?.close()
        pendingEventLog = log
        activeEventLogURL = log.url
        userSession = UserSession(epoch: desire.epoch, reason: reason, startedUptime: now)
        GestureSessionMarker(epoch: desire.epoch, startedAt: .now, lastAliveAt: .now).save(to: .standard)
        sessionFrame = nil
        lastGoodAt = continuous
        consecutiveRenewalMisses = 0
        idleTracker.start(at: continuous)
        automaticEnd.clear()
        journal.record("session_start", fields: [
            "epoch": desire.epoch, "session": Int(status.session), "reason": reason.rawValue,
            "foreground": isAppActive,
            "keep_in_background": keepGesturesInBackground, "idle_pause_s": gestureIdlePause.rawValue,
            "auto_return_s": gestureAutoReturn.rawValue, "family": (firmwareFamily?.rawValue).map { $0 as Any } ?? NSNull(),
            "build": Self.buildConfiguration,
            "model": gestureModelSource,
            "firmware": ringManager.firmware.map { $0 as Any } ?? NSNull(),
            "lease_s": a1ModeTransport?.leaseSeconds ?? 0,
        ])
        mainWatchdog.start()
        scheduleGestureAutoReturn(fromNow: false)
        scheduleIdlePause()
    }

    /// Recognition for one ring session of the user's session: `trigger` is
    /// start or heal; `presetFrame` a calibration frame kept across a heal.
    private func beginSegment(_ current: ModeStatus, trigger: String, presetFrame: String?) {
        let classifier: PinnedGestureClassifier
        do { classifier = try cachedGestureClassifier() }
        catch {
            setGestureStatus("Gesture model unavailable: \(error.localizedDescription)")
            handle(.modelUnavailable, detail: error.localizedDescription)
            return
        }
        let calibration = GestureSensorCalibration.stored(for: activeDeviceID)
        gestureSensorCalibration = calibration
        let signalAdapter: GestureSignalAdapter = firmwareFamily == .rt12col
            ? .rt12col(calibration: calibration) : .rt02cr(calibration: calibration)
        let driver = GestureSession(signalAdapter: signalAdapter, output: { [weak self] output in
            Task { @MainActor in
                guard let self, self.gestureGeneration == output.generation else { return }
                self.handleGestureOutput(output)
            }
        }, invalid: { [weak self] generation, _ in
            Task { @MainActor in
                guard let self, self.gestureGeneration == generation else { return }
                // Stale or stalled data never drives an action: the driver has
                // already dropped the sample; recognition pauses and heals.
                let detail = self.recordStaleDetail()
                self.handle(.streamFault, detail: detail)
            }
        }, onStall: { [weak self] generation, stall in
            Task { @MainActor in
                guard let self, self.gestureGeneration == generation else { return }
                self.journal.record("stream_stall", fields: self.phaseFields([
                    "session": Int(current.session), "check": stall.check,
                    "value_s": GestureLogFormat.json(GestureEventLog.rounded(stall.value)),
                    "duration_s": GestureLogFormat.json(GestureEventLog.rounded(stall.duration)),
                    "dropped": stall.dropped,
                ]))
            }
        })
        gestureDriver = driver
        let generation = driver.start(session: current.session, classifier: classifier, presetFrame: presetFrame)
        gestureGeneration = generation
        if let log = pendingEventLog {
            pendingEventLog = nil
            router.begin(generation: generation, log: log)
        } else {
            router.resume(generation: generation)
        }
        streamStats.reset()
        consecutiveRenewalMisses = 0
        sessionRecord = SessionRecord(session: current.session, startedUptime: ProcessInfo.processInfo.systemUptime,
                                      trigger: trigger)
        userSession?.segments += 1
        if trigger == "heal" { userSession?.heals += 1 }
        journal.record("segment_start", fields: phaseFields([
            "epoch": desire.epoch, "session": Int(current.session), "trigger": trigger,
            "frame": presetFrame == nil ? "new" : "kept",
        ]))
        startHeartbeat(segment: generation)
    }

    /// Ends the running ring session's recognition: no output, routing or
    /// renewal survives it. The user's session is untouched.
    private func stopSegment(cause: String) {
        gestureDriver?.stop()
        gestureGeneration = nil
        heartbeatTask?.cancel()
        heartbeatTask = nil
        if gestureReady { gestureReady = false }
        router.suspend()
        guard let record = sessionRecord else { return }
        sessionRecord = nil
        var fields = streamStats.total.fields
        fields["epoch"] = desire.epoch
        fields["session"] = Int(record.session)
        fields["trigger"] = record.trigger
        fields["cause"] = cause
        fields["segment_s"] = GestureLogFormat.json(GestureEventLog.rounded(
            max(0, ProcessInfo.processInfo.systemUptime - record.startedUptime)))
        journal.record("segment_end", fields: phaseFields(fields))
        streamStats.reset()
    }

    private func handleGestureOutput(_ output: GestureSession.Output) {
        let processedAt = ProcessInfo.processInfo.systemUptime
        lastGoodAt = GestureContinuousTime.now()
        streamStats.record(receivedAt: output.receivedAt, processedAt: processedAt,
                           predictSeconds: output.predictSeconds, queued: output.queued,
                           sameRun: output.sameRun)
        if streamStats.windowDue, let record = sessionRecord {
            var fields = streamStats.closeWindow().fields
            fields["session"] = Int(record.session)
            fields["foreground"] = isAppActive
            journal.record("stream", fields: fields)
        }
        setGestureStatus(output.pose.reason)
        let ready = output.pose.frame != nil
        if let frame = output.pose.frame, sessionFrame != frame { sessionFrame = frame }
        if gestureReady != ready {
            gestureReady = ready
            if ready { calibrationCompleted(output) }
        }
        if ready { router.calibrated(at: output.receivedAt) }
        recordSessionMilestones(output)
        diagnosticRecorder?.setFrame(output.pose.frame)
        modes.didProcess(session: output.session, sequence: output.sequence, at: output.receivedAt)
        guard !output.events.isEmpty else { return }
        // The inference queue bounds age after prediction, not the hop to this
        // actor or delay before the BLE delegate stamped receipt; a late
        // action (music next/previous) is worse than none.
        guard GestureFreshness.dispatchable(receivedAt: output.receivedAt, now: processedAt) else {
            for event in output.events {
                journal.record("event_dropped_stale", fields: phaseFields([
                    "session": Int(output.session), "name": event.name, "direction": event.direction,
                    "age_s": GestureLogFormat.json(GestureEventLog.rounded(processedAt - output.receivedAt)),
                ]))
            }
            return
        }
        let context = GestureActionRouter.Context(
            foreground: isAppActive, hapticsEnabled: haptics,
            diagnosticsRunning: diagnosticRecording,
            sessionEnding: sessions.sessionEnding || !desire.isOn
        )
        isRouting = true
        let dispatches = router.route(output.events, generation: output.generation, context: context)
        isRouting = false
        if let last = dispatches.last {
            lastDispatch = last
            let recognized = dispatches.filter(\.isActivity).count
            userSession?.recognized += recognized
            userSession?.performed += dispatches.filter { $0.outcome == .performed }.count
            if recognized > 0 { idleTracker.activity(at: GestureContinuousTime.now()) }
        }
        if pauseRequested {
            pauseRequested = false
            handle(.pauseGesture)
        }
    }

    /// The fingers-down calibration completed for this segment: announced
    /// once, by an intent's dialog, the screen or one notification.
    private func calibrationCompleted(_ output: GestureSession.Output) {
        let announced = announcer.calibrated(epoch: desire.epoch, appActive: isAppActive)
        guard let record = sessionRecord else { return }
        journal.record("calibrated_ready", fields: phaseFields([
            "epoch": desire.epoch, "session": Int(record.session), "trigger": record.trigger,
            "since_start_s": GestureLogFormat.json(GestureEventLog.rounded(output.receivedAt - record.startedUptime)),
            "announce": announced.rawValue,
        ]))
    }

    /// First prediction of the running segment.
    private func recordSessionMilestones(_ output: GestureSession.Output) {
        guard var record = sessionRecord else { return }
        let since = GestureLogFormat.json(GestureEventLog.rounded(output.receivedAt - record.startedUptime))
        if let predict = output.predictSeconds, !record.firstPredictLogged {
            record.firstPredictLogged = true
            journal.record("first_predict", fields: [
                "session": Int(record.session), "since_start_s": since,
                "predict_ms": (predict * 10_000).rounded() / 10, "queued": output.queued,
                "foreground": isAppActive,
            ])
        }
        sessionRecord = record
    }

    /// The GestureSession check that paused recognition, journaled before the
    /// heal; returns it as a short detail.
    @discardableResult
    private func recordStaleDetail() -> String? {
        guard let fault = gestureDriver?.lastFault else { return nil }
        let detail = fault.tolerance.map { "\(fault.check):\($0)" } ?? fault.check
        var fields = phaseFields(fault.fields)
        fields["session"] = sessionRecord.map { Int($0.session) as Any } ?? NSNull()
        fields["since_start_s"] = sessionRecord.map {
            GestureLogFormat.json(GestureEventLog.rounded(ProcessInfo.processInfo.systemUptime - $0.startedUptime))
        } ?? NSNull()
        journal.record("stale_detail", fields: fields)
        return detail
    }

    private func mainQueueStalled(_ delay: Double) {
        guard var record = sessionRecord, record.mainStalls < 200 else { return }
        record.mainStalls += 1
        sessionRecord = record
        journal.record("main_stall", fields: phaseFields([
            "session": Int(record.session), "delay_ms": Int((delay * 1_000).rounded()),
            "since_start_s": GestureLogFormat.json(GestureEventLog.rounded(
                ProcessInfo.processInfo.systemUptime - record.startedUptime)),
        ]))
    }

    /// Adds the scene phase and seconds since it last changed.
    private func phaseFields(_ fields: [String: Any]) -> [String: Any] {
        var fields = fields
        fields["phase"] = lastScenePhase
        fields["since_phase_s"] = GestureLogFormat.json(
            GestureEventLog.rounded(ProcessInfo.processInfo.systemUptime - lastScenePhaseAt))
        fields["foreground"] = isAppActive
        return fields
    }

    /// Every lease renewal attempt, passed or failed.
    private func journalRenewal(_ report: A1UnifiedModeTransport.RenewalReport) {
        var fields = report.fields
        fields["session"] = sessionRecord.map { Int($0.session) as Any } ?? NSNull()
        fields["foreground"] = isAppActive
        journal.record("renewal", fields: fields)
    }

    /// The model is loaded and warmed once, off the main thread, so a session
    /// start neither blocks the main queue (which stamps BLE receipt) on the
    /// MLModel load nor pays the first prediction's cost on its inference queue.
    private func prewarmGestureClassifier() {
        guard gestureClassifier == nil, !gestureClassifierLoading else { return }
        gestureClassifierLoading = true
        DispatchQueue.global(qos: .utility).async { [weak self] in
            let began = ProcessInfo.processInfo.systemUptime
            let classifier = try? PinnedGestureClassifier()
            let warmed = (try? classifier?.warmUp()) != nil
            let ms = Int(((ProcessInfo.processInfo.systemUptime - began) * 1_000).rounded())
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.gestureClassifierLoading = false
                guard warmed, let classifier, self.gestureClassifier == nil else { return }
                self.gestureClassifier = classifier
                self.gestureClassifierLoadMS = ms
            }
        }
    }

    /// The prewarmed model, or (before the prewarm finished) one loaded here
    /// on the main actor and kept for later sessions.
    private func cachedGestureClassifier() throws -> PinnedGestureClassifier {
        if let gestureClassifier {
            gestureModelSource = gestureClassifierLoadMS.map { "prewarmed_\($0)ms" } ?? "cached"
            return gestureClassifier
        }
        let began = ProcessInfo.processInfo.systemUptime
        let classifier = try PinnedGestureClassifier()
        gestureClassifier = classifier
        gestureModelSource = "loaded_on_start_\(Int(((ProcessInfo.processInfo.systemUptime - began) * 1_000).rounded()))ms"
        return classifier
    }

    /// Clears the desired state and tears down the user's session: timers,
    /// heal, renewal and recognition stop here, synchronously, before any
    /// stop is awaited (a pending renewal then cannot write). Journals,
    /// summarizes and notifies only when a session was on. Returns that.
    @discardableResult
    private func endUserSession(_ reason: GestureEndReason, detail: String? = nil,
                                healCause: GestureHealCause? = nil) -> Bool {
        let wasOn = desire.end(reason)
        publishDesire()
        keeper.cancel()
        // In the same step: a heal restart already queued never enters.
        sessions.withdrawHeal()
        GestureSessionMarker.clear(in: .standard)
        stopSegment(cause: "session_end_\(reason.rawValue)")
        gestureAutoReturnTask?.cancel()
        gestureAutoReturnTask = nil
        autoReturnDeadline = nil
        idleTask?.cancel()
        idleTask = nil
        idleTracker.stop()
        announcer.reset()
        sessionFrame = nil
        consecutiveRenewalMisses = 0
        if gestureHealing != nil { gestureHealing = nil }
        // A give-up at the deadline of the notice scheduled for it keeps that
        // notice (it is being delivered); every other end withdraws it.
        let noticeDelivered = reason.alwaysNotifies
            && (giveUpNoticeAt.map { GestureContinuousTime.now() >= $0 - 0.5 } ?? false)
        if noticeDelivered { giveUpNoticeAt = nil } else { cancelGiveUpNotice() }
        pendingEventLog?.close()
        pendingEventLog = nil
        guard wasOn, let record = userSession else {
            userSession = nil
            return false
        }
        userSession = nil
        finishUserSession(record, reason: reason, detail: detail, healCause: healCause,
                          noticeDelivered: noticeDelivered)
        return true
    }

    private func finishUserSession(_ record: UserSession, reason: GestureEndReason, detail: String?,
                                   healCause: GestureHealCause?, noticeDelivered: Bool) {
        mainWatchdog.stop()
        let duration = max(0, ProcessInfo.processInfo.systemUptime - record.startedUptime)
        var fields: [String: Any] = [
            "epoch": record.epoch, "reason": reason.rawValue, "start_reason": record.reason.rawValue,
            "session_s": GestureLogFormat.json(GestureEventLog.rounded(duration)),
            "foreground": isAppActive, "recognized": record.recognized, "performed": record.performed,
            "renewals": record.renewals, "heals": record.heals, "segments": record.segments,
        ]
        if let healCause { fields["heal_cause"] = healCause.rawValue }
        if let detail { fields["detail"] = detail }
        journal.record("session_end", fields: fields)
        router.end()
        activeEventLogURL = nil
        lastSessionSummary = GestureSessionSummary.text(duration: duration, recognized: record.recognized,
                                                        performed: record.performed, reason: reason.sessionReason,
                                                        reconnects: record.heals)
        guard reason.isAutomatic else { return }
        automaticEnd.ended(reason.sessionReason)
        if reason.alwaysNotifies {
            // Exactly one notification names a give-up, also with R02 in front.
            // One scheduled ahead may already have been delivered.
            guard !noticeDelivered else { return }
            _ = notificationPoster.post(title: "Gestures turned off",
                                        body: Self.giveUpBody(reason, cause: healCause, detail: detail, at: .now),
                                        identifier: Self.giveUpNoticeID)
        } else if !isAppActive {
            // A session started by Back Tap usually ends out of sight; say so
            // rather than leave the user to Toggle it back into the wrong state.
            _ = notificationPoster.post(
                title: "Gestures turned off",
                body: "The session ended: \(reason.sessionReason.endTitle). The ring is back in Health."
            )
        }
    }

    private static let giveUpNoticeID = "r02.gestures.gave-up"

    /// About when R02 was last alive with the session on, for a relaunch
    /// after iOS terminated it.
    private func touchSessionMarker() {
        guard var marker = GestureSessionMarker.load(from: .standard), marker.epoch == desire.epoch else { return }
        marker.lastAliveAt = .now
        marker.save(to: .standard)
    }

    /// iOS terminated R02 while a session was on: the session ended with no
    /// reason, journal record or notification. Records it and posts one
    /// notification (never asking for permission).
    private func reportTerminatedSession(_ marker: GestureSessionMarker) async {
        journal.record("session_end", fields: [
            "epoch": marker.epoch, "reason": "app_terminated",
            "session_s": GestureLogFormat.json(GestureEventLog.rounded(
                max(0, marker.lastAliveAt.timeIntervalSince(marker.startedAt)))),
            "last_alive": ISO8601DateFormatter().string(from: marker.lastAliveAt),
        ])
        await notificationPoster.refreshAuthorization()
        _ = notificationPoster.post(title: marker.noticeTitle, body: marker.noticeBody(),
                                    identifier: GestureSessionMarker.noticeIdentifier)
    }

    /// Names the time: a notification can be delivered late.
    private static func giveUpBody(_ reason: GestureEndReason, cause: GestureHealCause?, detail: String? = nil,
                                   at date: Date) -> String {
        GestureGiveUpNotice.body(reason, cause: cause, detail: detail,
                                 time: date.formatted(date: .omitted, time: .shortened))
    }

    /// A heal gave up, or a user timer passed while it ran.
    private func healGaveUp(_ reason: GestureEndReason, cause: GestureHealCause, detail: String?) {
        let trigger: GestureSessionTrigger
        switch reason {
        case .ringGone: trigger = .ringGoneTimeout
        case .charging: trigger = .chargingRefusal
        case .autoReturn: trigger = .sessionTimer
        case .idle: trigger = .idleTimer
        default: trigger = .healExhausted
        }
        guard case .end(let allowed) = GestureSessionPolicy.disposition(trigger) else { return }
        beginEnd(allowed, detail: detail.map { "\(cause.rawValue):\($0)" } ?? cause.rawValue, healCause: cause)
    }

    private func healStatusChanged(_ status: GestureHealStatus?) {
        if gestureHealing != status { gestureHealing = status }
        if let status { setGestureStatus(status.statusText) }
        updateGiveUpNotice(status)
    }

    /// While a heal waits or backs off with R02 out of sight, a "Gestures
    /// turned off" notification is scheduled for its give-up deadline, so the
    /// user hears of it even if iOS suspends R02 first; withdrawn before each
    /// attempt, on success, in front, and on any other end.
    private func updateGiveUpNotice(_ status: GestureHealStatus?) {
        guard desire.isOn, !isAppActive, let status, status.phase != .attempting,
              let deadline = keeper.giveUpDeadline else {
            cancelGiveUpNotice()
            return
        }
        guard giveUpNoticeAt != deadline else { return }
        let seconds = deadline - GestureContinuousTime.now()
        guard seconds > 1 else { return }
        let reason: GestureEndReason = status.phase == .waitingForLink ? .ringGone : .healGaveUp
        let body = Self.giveUpBody(reason, cause: status.cause, at: Date.now.addingTimeInterval(seconds))
        cancelGiveUpNotice()
        if notificationPoster.schedule(title: "Gestures turned off", body: body,
                                       identifier: Self.giveUpNoticeID, after: seconds) {
            giveUpNoticeAt = deadline
        }
    }

    private func cancelGiveUpNotice() {
        guard giveUpNoticeAt != nil else { return }
        notificationPoster.cancel(identifier: Self.giveUpNoticeID)
        giveUpNoticeAt = nil
    }

    /// Holds a background task while a heal episode is open, so its backoff
    /// and give-up deadline run; the expiration handler always ends it.
    private func setHealBackgroundTask(_ active: Bool) {
        #if canImport(UIKit)
        if active {
            guard healBackgroundTask == .invalid else { return }
            healBackgroundTask = UIApplication.shared.beginBackgroundTask(withName: "R02 gesture heal") { [weak self] in
                MainActor.assumeIsolated { self?.setHealBackgroundTask(false) }
            }
        } else if healBackgroundTask != .invalid {
            UIApplication.shared.endBackgroundTask(healBackgroundTask)
            healBackgroundTask = .invalid
        }
        #endif
    }

    /// What the last heartbeat reached and why it failed. The transport's
    /// report and rejection are used only when that heartbeat reached `renew`.
    private func heartbeatFailure(_ error: Error?) -> HeartbeatFailure {
        HeartbeatFailure(
            reachedRenew: modes.lastHeartbeatReachedRenew,
            heartbeatRejection: modes.lastHeartbeatRejection,
            transportRejection: a1ModeTransport?.lastRejection,
            report: a1ModeTransport?.lastRenewalReport,
            error: error.map { String(describing: $0) } ?? modes.lastHeartbeatError,
            retries: modes.lastHeartbeatRetries
        )
    }

    /// Renews the firmware lease every 5 s while the segment runs and fresh
    /// processed data exists. A failed renewal never ends the session: a miss
    /// keeps processing and retries while the lease is valid; a bad or stopped
    /// source, a lapsed lease or lost control heals. The loop never leaves a
    /// current segment without a verdict.
    private func startHeartbeat(segment: UUID) {
        heartbeatTask?.cancel()
        heartbeatTask = Task { [weak self] in
            var delay: Double = RenewalVerdict.normalRetry
            while true {
                do { try await Task.sleep(for: .seconds(delay)) } catch { return }
                guard !Task.isCancelled, let self, self.desire.isOn, self.gestureGeneration == segment else { return }
                do {
                    // Waits out a processing pause a tolerated stall causes.
                    let retries = try await self.modes.heartbeat(now: { ProcessInfo.processInfo.systemUptime })
                    guard !Task.isCancelled, self.gestureGeneration == segment else { return }
                    // Not due on the uptime clock (the phone slept inside the
                    // wait): nothing was renewed or checked, so nothing is
                    // credited; retry when it is due.
                    if case .notDue(let remaining) = self.modes.lastHeartbeatOutcome {
                        delay = min(RenewalVerdict.normalRetry, max(0.1, remaining))
                        continue
                    }
                    delay = RenewalVerdict.normalRetry
                    self.consecutiveRenewalMisses = 0
                    self.userSession?.renewals += 1
                    self.lastGoodAt = GestureContinuousTime.now()
                    self.keeper.heartbeatPassed()
                    self.touchSessionMarker()
                    if retries > 0, let record = self.sessionRecord {
                        self.journal.record("heartbeat_retry", fields: self.phaseFields([
                            "session": Int(record.session), "retries": retries,
                            "stall_open": self.gestureDriver?.openStallSince != nil,
                        ]))
                    }
                } catch {
                    // A failure that outlived its segment (a heal or stop replaced
                    // it) must not touch the segment that runs now.
                    guard !Task.isCancelled, self.gestureGeneration == segment, self.desire.isOn else { return }
                    let failure = self.heartbeatFailure(error)
                    var fields = failure.fields
                    fields["error"] = error.localizedDescription
                    fields["foreground"] = self.isAppActive
                    fields["mode_control"] = self.modes.available
                    fields["error_type"] = String(describing: error)
                    fields["stall_open"] = self.gestureDriver?.openStallSince != nil
                    self.journal.record("renewal_failed", fields: fields)
                    let transport = self.a1ModeTransport
                    let verdict = RenewalVerdict.classify(
                        error, failure: failure, linkReady: self.ringManager.isReady,
                        leaseAge: transport?.leaseAge, leaseDeadline: transport?.leaseRenewalDeadline ?? 9
                    )
                    switch verdict {
                    case .missed(let trigger, let retryIn):
                        if trigger == .renewalTiming { self.consecutiveRenewalMisses += 1 }
                        delay = retryIn
                        self.journal.record("renewal_missed", fields: self.phaseFields([
                            "session": self.sessionRecord.map { Int($0.session) as Any } ?? NSNull(),
                            "trigger": trigger.rawValue,
                            "detail": failure.detail.map { $0 as Any } ?? NSNull(),
                            "consecutive": self.consecutiveRenewalMisses,
                            "lease_age_s": GestureLogFormat.json(transport?.leaseAge.flatMap { GestureEventLog.rounded($0) }),
                            "retry_in_s": retryIn,
                        ]))
                    case .act(let trigger):
                        self.handle(trigger, detail: failure.detail)
                        return
                    }
                }
            }
        }
    }

    /// The user's Session timer, from the session's start (or from a setting
    /// change during it); heals do not move it.
    private func scheduleGestureAutoReturn(fromNow: Bool) {
        gestureAutoReturnTask?.cancel()
        gestureAutoReturnTask = nil
        guard desire.isOn, let seconds = gestureAutoReturn.seconds else {
            autoReturnDeadline = nil
            return
        }
        let now = GestureContinuousTime.now()
        let deadline = fromNow ? now + seconds : (desire.onSince ?? now) + seconds
        autoReturnDeadline = deadline
        let epoch = desire.epoch
        gestureAutoReturnTask = Task { [weak self] in
            do { try await Task.sleep(for: .seconds(max(0, deadline - now))) }
            catch { return }
            guard !Task.isCancelled, let self, self.desire.isOn, self.desire.epoch == epoch else { return }
            self.gestureAutoReturnTask = nil
            self.setGestureStatus("Session timer ended · returning to Health")
            self.handle(.sessionTimer)
        }
    }

    /// Wakes at the idle deadline, which recognized gestures keep moving later.
    private func scheduleIdlePause() {
        idleTask?.cancel()
        idleTask = nil
        guard desire.isOn, idleTracker.deadline != nil else { return }
        let epoch = desire.epoch
        idleTask = Task { [weak self] in
            let expired = await GestureIdleTracker.sleepUntilExpired(
                remaining: { self?.idleTracker.remaining(at: GestureContinuousTime.now()) },
                sleep: { try await Task.sleep(for: $0) }
            )
            guard expired, !Task.isCancelled, let self, self.desire.isOn, self.desire.epoch == epoch,
                  self.idleTracker.isExpired(at: GestureContinuousTime.now()) else { return }
            self.idleTask = nil
            self.setGestureStatus("No gestures for \(self.gestureIdlePause.title) · returning to Health")
            self.handle(.idleTimer)
        }
    }

    /// A user timer already past, checked before every heal attempt: after a
    /// suspension the timer's own task may wake later than the heal.
    private func passedSessionDeadline() -> GestureEndReason? {
        let now = GestureContinuousTime.now()
        if let autoReturnDeadline, now >= autoReturnDeadline { return .autoReturn }
        if idleTracker.isExpired(at: now) { return .idle }
        return nil
    }

    // MARK: Intents and scene

    var gestureModeSnapshot: GestureModeSnapshot {
        let now = ProcessInfo.processInfo.systemUptime
        var snapshot = GestureModeSnapshot(
            link: linkState,
            connectionSetupComplete: connectionSetupComplete,
            unifiedFirmwareInstalled: unifiedFirmwareInstalled,
            modeAttachInFlight: modeAttachInFlight,
            modeControlAvailable: modes.available,
            mode: modes.status?.mode,
            charging: modes.status?.charging ?? ring.charging,
            transition: sessions.transition,
            ringBusy: operations.owner != nil || isSyncing || isMeasuringHeartRate,
            firmwareSwitching: isFirmwareSwitching,
            appActive: isAppActive,
            keepGesturesInBackground: keepGesturesInBackground,
            startPending: startPending,
            startPendingAge: startStamp.pendingAge(at: now, pending: startPending),
            // Measured from the user's session, not a healed segment.
            sessionAge: desire.onSince.map { GestureContinuousTime.now() - $0 },
            recentAutomaticEnd: automaticEnd.recent
        )
        snapshot.gestureDesired = desire.isOn
        snapshot.healing = desire.isOn && keeper.isHealing
        snapshot.calibrated = desire.isOn && gestureReady
        snapshot.orphanGesture = orphanGesture
        snapshot.startIntentWaiting = intentCalibrationWaits > 0
        snapshot.startIntentRepliedAge = lastStartIntentReplyAt.map { now - $0 }
        return snapshot
    }

    private var startPending: Bool { sessions.pendingStarts > 0 || startHolds.continuationPending }

    /// Journals what an intent saw and decided (Back Tap diagnosis).
    func noteIntent(_ kind: String, decision: String) {
        let now = ProcessInfo.processInfo.systemUptime
        let snapshot = gestureModeSnapshot
        func seconds(_ value: Double?) -> Any { GestureLogFormat.json(value.flatMap { GestureEventLog.rounded($0) }) }
        journal.record("intent", fields: phaseFields([
            "intent": kind, "decision": decision,
            "gesture_active": snapshot.gestureActive, "start_pending": snapshot.startPending,
            "desired": snapshot.gestureDesired, "healing": snapshot.healing, "calibrated": snapshot.calibrated,
            "transition": snapshot.transition?.rawValue ?? NSNull(),
            "mode": snapshot.mode?.rawValue ?? NSNull(),
            "session_age_s": seconds(snapshot.sessionAge),
            "start_pending_s": seconds(snapshot.startPendingAge),
            "since_previous_intent_s": seconds(lastIntentAt.map { now - $0 }),
            "recent_automatic_end": snapshot.recentAutomaticEnd?.reason.rawValue ?? NSNull(),
        ]))
        lastIntentAt = now
    }

    /// The start intent's calibration wait (see `GestureModeControlling`).
    /// The reply and the ready announcer are settled in one synchronous step
    /// after the wait, so a calibration is announced exactly once.
    func awaitCalibration(timeout: TimeInterval) async -> GestureCalibrationWait {
        guard desire.isOn || desire.isArming else { return .ended }
        let epoch = desire.epoch
        let waiter = GestureCalibrationWaiter(probes: .init(
            epoch: { [unowned self] in self.desire.epoch },
            isOn: { [unowned self] in self.desire.isOn },
            isArming: { [unowned self] in self.desire.isArming },
            ready: { [unowned self] in self.gestureReady },
            healing: { [unowned self] in self.keeper.isHealing },
            waitingForLink: { [unowned self] in self.keeper.isWaitingForLink }
        ), announcer: announcer)
        intentCalibrationWaits += 1
        let began = ProcessInfo.processInfo.systemUptime
        let result = await waiter.wait(timeout: timeout)
        intentCalibrationWaits -= 1
        lastStartIntentReplyAt = ProcessInfo.processInfo.systemUptime
        journal.record("intent_calibration", fields: phaseFields([
            "epoch": epoch, "result": result.rawValue,
            "waited_s": GestureLogFormat.json(GestureEventLog.rounded(ProcessInfo.processInfo.systemUptime - began)),
            "budget_s": GestureLogFormat.json(GestureEventLog.rounded(timeout)),
        ]))
        return result
    }

    private var linkState: GestureModeSnapshot.Link {
        if ringManager.isReady { return .ready }
        switch ringManager.state {
        case .recoveryReady: return .recoveryOnly
        case .bluetoothUnavailable: return .bluetoothOff
        default: return ringManager.pairedIdentifier == nil ? .unpaired : .connecting
        }
    }

    /// Start waits for the ring to connect, identify and attach mode control;
    /// while it waits, the automatic health refresh on connection is deferred
    /// so the start is not queued behind a history import. Stop never waits,
    /// clears the desired state first (no heal or renewal follows), and
    /// withdraws every start still waiting (including a Shortcut's
    /// continuation in R02), so a stop always leaves the ring in Health.
    @discardableResult
    func requestGestureSession(_ enabled: Bool, source: GestureRequestSource,
                               readinessTimeout: TimeInterval = 10) async -> GestureRequestOutcome {
        guard enabled else {
            // Every pending start is withdrawn: nothing is left to debounce.
            startStamp.stopRequested()
            let wasOn = desire.isOn
            endUserSession(source.endReason)
            // Drops the foreground hold and withdraws the continuation, then,
            // once the stop has settled, runs a health refresh deferred for the
            // withdrawn start (a hold-only cancel has no mode change to run it).
            return await startHolds.stop { continuation in
                var outcome = await self.sessions.requestStop(reason: source.reason, alsoWithdrawing: continuation)
                if !outcome.succeeded { self.enforceHealth() }
                // A session that was healing (ring already in Health) still turned off.
                if wasOn, outcome == .alreadyStopped || outcome == .startCancelled { outcome = .stopped }
                self.journal.record("request", fields: ["enabled": false, "source": source.rawValue,
                                                        "outcome": outcome.journalName, "was_on": wasOn,
                                                        "foreground": self.isAppActive])
                return outcome
            }
        }
        // A cold background launch has had no scene to ask for the ring yet.
        ringManager.begin()
        // The model is checked before anything is sent: a session that could
        // recognize nothing is never started, and never healed.
        do { _ = try cachedGestureClassifier() } catch {
            let outcome = GestureRequestOutcome.failed("Gesture model unavailable: \(error.localizedDescription)")
            journal.record("request", fields: ["enabled": true, "source": source.rawValue,
                                               "outcome": outcome.journalName, "foreground": isAppActive])
            return outcome
        }
        // Before `requestStart` counts this request as pending.
        startStamp.startRequested(at: ProcessInfo.processInfo.systemUptime, alreadyPending: startPending)
        let wasOn = desire.isOn
        let epoch = desire.arm()
        // Gesture no session wants: this start waits `.returning` for its
        // return to Health, which must be under way.
        ensureHealthEnforced()
        let result = await sessions.requestStart(reason: source.reason, readinessTimeout: readinessTimeout) {
            GestureStartReadiness.evaluate(self.gestureModeSnapshot)
        }
        if !wasOn { desire.startFinished(epoch: epoch) }
        publishDesire()
        // A start that ended without a session never leaves an orphan unenforced.
        ensureHealthEnforced()
        var outcome = result.outcome
        // A held stop ran right after the entry: no session is running.
        if outcome == .started, !desire.isOn { outcome = .startCancelled }
        if outcome == .alreadyActive, desire.isOn { keeper.kick() }
        journal.record("request", fields: [
            "enabled": true, "source": source.rawValue, "readiness": result.readiness.rawValue,
            "waited_s": GestureLogFormat.json(GestureEventLog.rounded(result.waited)),
            "outcome": outcome.journalName, "desired": desire.isOn, "epoch": epoch, "foreground": isAppActive,
        ])
        // A start that joined a running session clears old failures too, and a
        // refresh deferred for this start runs if nothing else holds the ring.
        startHolds.startFinished(outcome)
        return outcome
    }

    /// Called by a Start or Toggle intent just before it asks to continue in
    /// R02 (still in the background). Scene activation may run before the
    /// continuation does; this keeps its automatic sync off the ring meanwhile.
    func expectForegroundStart() {
        startHolds.expectForegroundStart()
    }

    /// The foreground continuation of a Start or Toggle intent. Returns at once
    /// so the intent finishes; the start runs on its own, shows as a pending
    /// start on the Gestures screen, and publishes why if no session started.
    func openGesturesAfterIntent(startWhenReady: Bool) {
        selectedTab = .gestures
        guard startWhenReady else { return }
        // The user's Continue tap; the continuation's own request later does not restamp.
        startStamp.userContinued(at: ProcessInfo.processInfo.systemUptime)
        startHolds.continueInForeground { [weak self] in
            guard let self else { return nil }
            return await GestureIntentLogic.startAfterForeground(self)
        }
    }

    func clearIntentStartMessage() {
        startHolds.clearContinuationMessage()
    }

    /// The panel's Start/Return tap: a new tap supersedes both messages; a
    /// failure is kept until a session starts, the next tap, or the panel leaves.
    func panelRequestBegan() {
        startHolds.panelRequestBegan()
    }

    func panelRequestFinished(_ outcome: GestureRequestOutcome) {
        startHolds.panelRequestFinished(outcome)
    }

    func clearPanelRequestMessage() {
        startHolds.clearPanelMessage()
    }

    private func startHoldsChanged() {
        if intentStartMessage != startHolds.continuationMessage { intentStartMessage = startHolds.continuationMessage }
        if panelRequestMessage != startHolds.panelMessage { panelRequestMessage = startHolds.panelMessage }
        updateStartPending()
    }

    private func updateStartPending() {
        let pending = sessions.pendingStarts > 0 || startHolds.continuationPending
        if gestureStartPending != pending { gestureStartPending = pending }
    }

    /// A start request, a Shortcut's continuation, or a Shortcut about to ask
    /// to continue in R02: automatic health syncs wait for any of them.
    private var startHoldsRing: Bool { startHolds.holdsRing }

    func scenePhaseChanged(_ phase: ScenePhase) {
        let active = phase == .active
        if isAppActive != active { isAppActive = active }
        lastScenePhase = "\(phase)"
        lastScenePhaseAt = ProcessInfo.processInfo.systemUptime
        if gestureModeSnapshot.gestureActive || sessions.transition != nil || gestureStartPending {
            journal.record("scene", fields: ["phase": "\(phase)", "keep_in_background": keepGesturesInBackground,
                                             "desired": desire.isOn, "healing": keeper.isHealing])
        }
        // The give-up notice is scheduled only while R02 is out of sight.
        updateGiveUpNotice(keeper.status)
        switch phase {
        case .active:
            ringManager.begin()
            refreshPermissionStates()
            automaticHealthSync()
            prepareMusicIfMapped()
        case .background:
            stopHeartRateMeasurement()
            // The capture's prompts are on screen; a backgrounded capture is meaningless.
            if diagnosticRecording { cancelGestureDiagnosticWorkflow() }
            if !keepGesturesInBackground, gestureModeSnapshot.gestureActive {
                handle(.backgroundedWithSettingOff)
            }
        default: break
        }
    }

    /// Foreground and periodic sync; skipped while a start holds the ring.
    func automaticHealthSync() {
        guard !startHoldsRing, ringManager.isReady, healthSyncEnabled else { return }
        Task { await sync() }
    }

    private func runDeferredHealthRefreshIfNeeded() {
        startHolds.runDeferredHealthRefreshIfNeeded()
    }

    /// Opens the Apple Music connection ahead of time, only while no Gesture
    /// stream runs: in Health, or just before an entry sends A1 04. The first
    /// call into the system player blocks the main queue, which also stamps
    /// BLE receipt times; during a stream a long block reads as a stall and
    /// ends the session.
    private func prepareMusicIfMapped(beforeEntry: Bool = false) {
        guard gestureMappings.requiredPermissions.contains(.appleMusic),
              musicController.authorization == .authorized,
              beforeEntry || sessions.transition == nil,
              !isRuntimeGestureMode else { return }
        musicController.prepare()
    }

    // MARK: Mappings, permissions and logs

    func setMapping(_ action: GestureActionID, for gesture: GestureID) {
        gestureMappings[gesture] = action
        if action.info.permission == .appleMusic { prepareMusicIfMapped() }
    }

    func resetMapping(_ gesture: GestureID) {
        gestureMappings.reset(gesture)
    }

    func resetAllMappings() {
        gestureMappings.resetAll()
    }

    func refreshPermissionStates() {
        let music = musicController.authorization
        if musicAuthorization != music { musicAuthorization = music }
        Task {
            let notifications = await notificationPoster.refreshAuthorization()
            if notificationAuthorization != notifications { notificationAuthorization = notifications }
        }
    }

    /// Foreground UI only: this can show the system prompt.
    @discardableResult
    func requestPermission(_ permission: GesturePermission) async -> PermissionState {
        switch permission {
        case .appleMusic:
            let current = musicController.authorization
            musicAuthorization = current == .notDetermined ? await musicController.requestAuthorization() : current
            prepareMusicIfMapped()
            return musicAuthorization
        case .notifications:
            notificationAuthorization = await notificationPoster.requestAuthorization()
            return notificationAuthorization
        }
    }

    /// Research event logs, then the lifecycle journals.
    func gestureEventLogFiles() -> [URL] {
        journal.flush()
        return GestureEventLog.files() + GestureSessionJournal.files()
    }

    /// Deletes every log except the open event log of a running session.
    @discardableResult
    func deleteGestureEventLogs() -> Int {
        journal.close()
        let open = activeEventLogURL?.lastPathComponent
        var deleted = 0
        for url in GestureEventLog.files() + GestureSessionJournal.files() where url.lastPathComponent != open {
            if (try? FileManager.default.removeItem(at: url)) != nil { deleted += 1 }
        }
        return deleted
    }

    func start(modelContext: ModelContext) {
        guard !started else { return }
        started = true
        // Device check for the main-queue cost of Apple Music's synchronous IPC:
        // BLE receipt times are stamped on the same queue.
        musicController.onSlowCall = { [weak self] command, seconds in
            guard let self else { return }
            self.journal.record("music_slow", fields: [
                "command": command, "ms": Int((seconds * 1_000).rounded()),
                "streaming": self.isRuntimeGestureMode, "foreground": self.isAppActive,
            ])
        }
        let store = HealthStore(context: modelContext)
        let client = ColmiR02Client(manager: ringManager)
        healthStore = store
        coverageStore = HealthCoverageStore(context: modelContext)
        ringClient = client
        syncService = HealthSyncService(client: client, store: store)
        ringManager.onReady = { [weak self] in
            Task { @MainActor [weak self] in
                guard let self, let deviceID = self.ringManager.connectedIdentifier else { return }
                self.connectionSetupComplete = false
                self.ring.lastSync = UserDefaults.standard.object(
                    forKey: self.lastSyncKeyPrefix + deviceID
                ) as? Date
                await self.identifyFirmwareMode()
                let returningFromFirmwareSwitch = self.pendingFirmwareTarget == self.firmwareMode
                if returningFromFirmwareSwitch {
                    // Release the firmware owner before the unified transport
                    // acquires the mode owner on this post-DFU connection.
                    self.finishFirmwareSwitch()
                } else if self.pendingFirmwareTarget != nil {
                    if let operation = self.firmwareOperation { self.operations.end(operation) }
                    self.firmwareOperation = nil
                    self.isFirmwareSwitching = false
                    self.pendingFirmwareTarget = nil
                    self.firmwareSwitchStartedAt = nil
                    self.syncMessage = "Firmware return did not match the requested image"
                }
                if self.unifiedFirmwareInstalled { await self.attachUnifiedMode() }
                self.connectionSetupComplete = self.ringManager.isReady
                // A desired session heals on this connection (identified and attached).
                if self.connectionSetupComplete, self.desire.isOn { self.keeper.linkUsable() }
                do {
                    try self.coverageStore?.observe(deviceID: deviceID,
                        mode: self.unifiedFirmwareInstalled
                            ? (self.modes.status?.mode ?? .unknown)
                            : (self.firmwareMode == .health ? .health : .unknown),
                        firmware: self.ring.firmware, at: .now)
                } catch { self.syncMessage = "Could not record health coverage: \(error.localizedDescription)" }
                if self.firmwareMode == .health || self.firmwareMode == .unified {
                    // A firmware return is not a newly provisioned ring. In particular,
                    // never send the full-sync clock command merely because this is a
                    // fresh app install: that command clears activity held by the ring.
                    let full = returningFromFirmwareSwitch ? false : self.ring.lastSync == nil
                    // Deferred while a start request waits for this connection; a
                    // history import would hold the ring past its readiness timeout.
                    if !self.startHolds.deferHealthRefresh(full: full) {
                        await self.refreshHealthSettings()
                        await self.sync(full: full)
                    }
                } else if self.firmwareMode == .gesture {
                    self.ring.linked = true
                    self.syncMessage = "Gesture mode · health sync paused"
                    self.ringManager.showsOnboarding = false
                }
            }
        }
        ringManager.onDisconnect = { [weak self] in
            // First, so the loss is judged as a disconnect (ring-gone window),
            // not as lost control. Disconnect ends no session by itself.
            self?.keeper.linkLost()
            self?.connectionSetupComplete = false
            self?.startHolds.connectionLost()
            self?.modeRecovery.reset()
            self?.a1ModeTransport?.disconnected()
            // Cleared before the coordinator reports the loss, so no recovery is scheduled.
            self?.a1ModeTransport = nil
            self?.ringManager.onRawMotion = nil
            self?.modes.disconnected()
            self?.heartRateSettingsKnown = false
            self?.ring.linked = false
            self?.syncMessage = self?.isFirmwareSwitching == true
                ? "Firmware installed · waiting for ring to restart"
                : "Waiting for ring"
        }
        refreshFromStore()
        refreshPermissionStates()
        ringManager.begin()
        prewarmGestureClassifier()
    }

    func connectCandidate() {
        ringManager.connectCandidate()
    }

    func beginPairing() {
        ringManager.scan()
    }

    func sync(full: Bool = false) async {
        guard healthSyncEnabled,
              !isSyncing, let syncService, let deviceID = ringManager.connectedIdentifier else {
            if !ringManager.isReady { ringManager.scan() }
            return
        }
        guard let operation = operations.begin(.sync) else { return }
        defer { operations.end(operation) }
        await importHistory(syncService: syncService, deviceID: deviceID, full: full)
    }

    private func importHistory(syncService: HealthSyncService, deviceID: String, full: Bool) async {
        isSyncing = true
        syncMessage = "Syncing…"
        ring.linked = true
        ring.id = ringManager.connectedName ?? ringManager.candidate?.name ?? "Colmi R02"
        ring.firmware = ringManager.firmware ?? ring.firmware
        ring.hardware = ringManager.hardware ?? ring.hardware
        let result = await syncService.sync(deviceID: deviceID, full: full) { [weak self] message, battery in
            guard let self else { return }
            self.syncMessage = message
            if let battery {
                self.ring.batteryPercent = battery.percent
                self.ring.charging = battery.charging
            }
            self.refreshFromStore()
        }
        if let battery = result.battery {
            ring.batteryPercent = battery.percent
            ring.charging = battery.charging
        }
        ring.firmware = ringManager.firmware ?? ring.firmware
        ring.hardware = ringManager.hardware ?? ring.hardware
        if !result.hasAnyError {
            ring.lastSync = .now
            UserDefaults.standard.set(ring.lastSync, forKey: lastSyncKeyPrefix + deviceID)
        }
        isSyncing = false
        syncMessage = result.errorSummary ?? "Synced just now"
        lastSyncSucceeded = !result.hasAnyError
        ringManager.showsOnboarding = false
        refreshFromStore()
    }

    func series(for metric: Metric, range: MetricRange) -> MetricSeries {
        _ = dataRevision
        return healthStore?.series(deviceID: activeDeviceID, metric: metric, range: range)
            ?? .empty(for: metric)
    }

    func setHeartRateLogging(_ enabled: Bool) async {
        guard healthSyncEnabled, let ringClient, ringManager.isReady else {
            syncMessage = "Switch to Health mode and connect the ring first"
            return
        }
        guard let operation = operations.begin(.settings) else { syncMessage = "Ring is busy"; return }
        defer { operations.end(operation) }
        do {
            try await ringClient.setHeartRateLogging(enabled: enabled,
                                                     intervalMinutes: UInt8(clamping: heartRateIntervalMinutes))
            heartRateLogging = enabled
            heartRateSettingsKnown = true
        } catch {
            syncMessage = error.localizedDescription
        }
    }

    private func refreshHealthSettings() async {
        heartRateSettingsKnown = false
        guard healthSyncEnabled, let ringClient, let operation = operations.begin(.settings) else { return }
        defer { operations.end(operation) }
        do {
            let settings = try await ringClient.heartRateLoggingSettings()
            heartRateLogging = settings.enabled
            heartRateIntervalMinutes = settings.interval > 0 ? settings.interval : 5
            heartRateSettingsKnown = true
        } catch { syncMessage = "Heart-rate settings unavailable: \(error.localizedDescription)" }
    }

    func measureHeartRate() {
        guard healthSyncEnabled, !isMeasuringHeartRate, let ringClient, let store = healthStore,
              let deviceID = activeDeviceID else { return }
        guard let operation = operations.begin(.liveHeartRate) else { return }
        measurementTask?.cancel()
        isMeasuringHeartRate = true
        liveHeartRate = nil
        syncMessage = "Measuring live heart rate…"
        measurementTask = Task { [weak self] in
            defer { self?.operations.end(operation) }
            do {
                let bpm = try await ringClient.measureHeartRate { reading in
                    self?.liveHeartRate = reading
                }
                try store.saveLiveHeartRate(deviceID: deviceID, timestamp: .now, bpm: bpm)
                self?.liveHeartRate = bpm
                self?.syncMessage = "Heart rate saved"
                self?.refreshFromStore()
            } catch is CancellationError {
                // Leaving the screen intentionally stops the optical sensor.
            } catch RingProtocolError.timeout {
                self?.syncMessage = "No heart-rate reading · adjust the ring and try again"
            } catch {
                self?.syncMessage = error.localizedDescription
            }
            self?.isMeasuringHeartRate = false
            self?.measurementTask = nil
        }
    }

    func stopHeartRateMeasurement() {
        guard isMeasuringHeartRate else { return }
        ringClient?.cancelHeartRateMeasurement()
        measurementTask?.cancel()
        measurementTask = nil
        isMeasuringHeartRate = false
    }

    func forgetRing() {
        stopHeartRateMeasurement()
        // Ended before the link drops, so no heal follows.
        if desire.isOn || desire.isArming { handle(.ringForgotten) }
        ringManager.forget()
        ring = RingDevice()
        syncMessage = "Ring forgotten; local history was kept"
        refreshFromStore()
    }

    func exportFiles() throws -> [URL] {
        try healthStore?.exportFiles(deviceID: activeDeviceID) ?? []
    }

    /// Off for the whole of a desired Gesture session, heals included: health
    /// work would take the ring from its heal and send non-audited packets.
    var healthSyncEnabled: Bool {
        !isFirmwareSwitching && !desire.isOn && (unifiedFirmwareInstalled
            ? modes.available && modes.status?.mode == .health
            : (modes.available ? modes.status?.mode == .health : firmwareMode == .health))
    }

    func switchFirmware(to requestedDescriptor: BundledFirmware) async {
        let target = requestedDescriptor.mode
        guard firmwareMode != .unknown, target != .unknown,
              !isFirmwareSwitching, !isSyncing, !desire.isOn,
              (!modes.available || modes.status?.mode == .health),
              let ringClient, ringManager.isReady else {
            if !ringManager.isReady { syncMessage = "Connect the ring before switching modes" }
            return
        }

        let actualHardware = ringManager.hardware ?? ring.hardware
        let actualFirmware = ringManager.firmware ?? ring.firmware
        guard let family = RingHardwareFamily.route(
            hardware: actualHardware, firmware: actualFirmware
        ) else {
            syncMessage = FirmwareSwitchError.unroutableIdentity(
                hardware: actualHardware, firmware: actualFirmware
            ).localizedDescription
            return
        }
        guard let descriptor = BundledFirmware.routedCatalog(
            hardware: actualHardware, firmware: actualFirmware
        ).first(where: {
            $0.resource == requestedDescriptor.resource && $0.sha256 == requestedDescriptor.sha256
        }) else {
            syncMessage = FirmwareSwitchError.noCompatibleImage(
                mode: target, family: family
            ).localizedDescription
            return
        }
        guard !descriptor.isInstalled(mode: firmwareMode, version: actualFirmware) else {
            syncMessage = "\(descriptor.label) is already installed"
            return
        }
        guard descriptor.installEnabled else {
            syncMessage = descriptor.disabledReason ?? "This firmware image is disabled"
            return
        }

        guard let operation = operations.begin(.firmware) else { syncMessage = "Ring is busy"; return }
        firmwareOperation = operation

        pendingFirmwareTarget = target
        firmwareSwitchStartedAt = .now
        do {
            stopHeartRateMeasurement()
            // Stock holds the only copy of unsynced history. Import it before the
            // image is replaced; routine sync never sends the destructive clock command.
            if firmwareMode == .health || firmwareMode == .unified {
                syncMessage = "Saving health history before switching…"
                guard let syncService, let deviceID = activeDeviceID else { throw RingProtocolError.notReady }
                await importHistory(syncService: syncService, deviceID: deviceID, full: false)
                guard lastSyncSucceeded else {
                    throw FirmwareSwitchError.healthSyncFailed(syncMessage)
                }
            }

            isFirmwareSwitching = true
            firmwareProgress = 0
            let battery = try await ringClient.battery()
            ring.batteryPercent = battery.percent
            ring.charging = battery.charging
            guard !battery.charging else { throw FirmwareSwitchError.charging }
            guard battery.percent >= 40 else { throw FirmwareSwitchError.batteryTooLow(battery.percent) }

            let firmware = try descriptor.load()
            let expectedHardware = try descriptor.declaredHardware(in: firmware)
            let actualHardware = ringManager.hardware ?? ring.hardware
            guard expectedHardware == actualHardware else {
                throw FirmwareSwitchError.incompatibleHardware(expected: expectedHardware, actual: actualHardware)
            }

            syncMessage = "Preparing \(descriptor.label)…"
            let transferStartedAt = Date()
            try await ringManager.flashFirmware(firmware, initType: descriptor.initType) { [weak self] progress, message in
                self?.firmwareProgress = progress
                self?.syncMessage = message
            }
            lastFirmwareTransferDuration = Date().timeIntervalSince(transferStartedAt)
            print(String(format: "R02 DFU TRANSFER %.2f s target=%@", lastFirmwareTransferDuration ?? 0, target.rawValue))
            syncMessage = "\(descriptor.label) installed · reconnecting"
        } catch {
            operations.end(operation)
            firmwareOperation = nil
            syncMessage = error.localizedDescription
            isFirmwareSwitching = false
            pendingFirmwareTarget = nil
            firmwareSwitchStartedAt = nil
        }
    }

    var activeDeviceID: String? {
        ringManager.connectedIdentifier ?? ringManager.pairedIdentifier?.uuidString
    }

    var connectionLabel: String {
        isFirmwareSwitching ? "Updating firmware" : (isSyncing ? "Syncing" : ringManager.state.label)
    }

    private var firmwareModeKey: String {
        "ringFirmwareMode." + (activeDeviceID ?? "unpaired")
    }

    private func identifyFirmwareMode() async {
        unifiedFirmwareInstalled = false
        ringHIDFirmwareInstalled = false
        ringHIDVersion = 0
        firmwareFamily = nil
        ring.linked = true
        ring.id = ringManager.connectedName ?? ringManager.candidate?.name ?? "Colmi R02"

        // DIS reads can finish just after UART discovery. The two 25 Hz images
        // deliberately report the same version and are fingerprinted below.
        for _ in 0..<10 where ringManager.firmware == nil || ringManager.hardware == nil {
            try? await Task.sleep(for: .milliseconds(100))
        }
        ring.firmware = ringManager.firmware ?? ring.firmware
        ring.hardware = ringManager.hardware ?? ring.hardware
        guard let family = RingHardwareFamily.route(
            hardware: ringManager.hardware, firmware: ringManager.firmware
        ) else {
            firmwareMode = .unknown
            syncMessage = "Unknown or conflicting ring identity · firmware actions and automatic health sync paused"
            return
        }
        firmwareFamily = family

        if family == .rt12col {
            guard let version = ringManager.firmware else {
                firmwareMode = .unknown
                syncMessage = "Unknown RT12COL firmware · firmware actions and automatic health sync paused"
                return
            }
            if version == FirmwareIdentity.rt12colStockVersion {
                firmwareMode = .health
                UserDefaults.standard.set(firmwareMode.rawValue, forKey: firmwareModeKey)
                return
            }
            if version == FirmwareIdentity.rt12colUnifiedHIDV10Version {
                do {
                    let candidate = try BundledFirmware.rt12colUnifiedHIDV10.load()
                    guard try await imageMatches(
                        candidate, sites: FirmwareIdentity.rt12colUnifiedHIDV10Sites
                    ) else { throw FirmwareSwitchError.unrecognizedFirmware }
                    firmwareMode = .unified
                    unifiedFirmwareInstalled = true
                    ringHIDFirmwareInstalled = true
                    ringHIDVersion = 10
                    syncMessage = "RT12COL V10 verified · keyboard-primary controls ready"
                    UserDefaults.standard.set(firmwareMode.rawValue, forKey: firmwareModeKey)
                    return
                } catch {
                    firmwareMode = .unknown
                    syncMessage = "RT12COL V10 fingerprint uncertain · HID and health sync paused"
                    return
                }
            }
            if version == FirmwareIdentity.rt12colUnifiedHIDV9Version {
                do {
                    let candidate = try BundledFirmware.rt12colUnifiedHIDV9.load()
                    guard try await imageMatches(
                        candidate, sites: FirmwareIdentity.rt12colUnifiedHIDV9Sites
                    ) else { throw FirmwareSwitchError.unrecognizedFirmware }
                    firmwareMode = .unified
                    unifiedFirmwareInstalled = true
                    ringHIDFirmwareInstalled = true
                    ringHIDVersion = 9
                    syncMessage = "RT12COL V9 verified · keyboard and mouse controls ready"
                    UserDefaults.standard.set(firmwareMode.rawValue, forKey: firmwareModeKey)
                    return
                } catch {
                    firmwareMode = .unknown
                    syncMessage = "RT12COL V9 fingerprint uncertain · HID and health sync paused"
                    return
                }
            }
            if version == FirmwareIdentity.rt12colUnifiedHIDVersion {
                do {
                    let candidate = try BundledFirmware.rt12colUnifiedHID.load()
                    guard try await imageMatches(
                        candidate, sites: FirmwareIdentity.rt12colUnifiedHIDSites
                    ) else { throw FirmwareSwitchError.unrecognizedFirmware }
                    firmwareMode = .unified
                    unifiedFirmwareInstalled = true
                    ringHIDFirmwareInstalled = true
                    ringHIDVersion = 8
                    syncMessage = "RT12COL V8 verified · unified Gesture and ring controls ready"
                    UserDefaults.standard.set(firmwareMode.rawValue, forKey: firmwareModeKey)
                    return
                } catch {
                    firmwareMode = .unknown
                    syncMessage = "RT12COL V8 fingerprint uncertain · HID and health sync paused"
                    return
                }
            }
            if version == FirmwareIdentity.rt12colUnifiedVersion {
                do {
                    let candidate = try BundledFirmware.rt12colUnified.load()
                    guard try await imageMatches(
                        candidate, sites: FirmwareIdentity.rt12colUnifiedSites
                    ) else { throw FirmwareSwitchError.unrecognizedFirmware }
                    firmwareMode = .unified
                    unifiedFirmwareInstalled = true
                    UserDefaults.standard.set(firmwareMode.rawValue, forKey: firmwareModeKey)
                    return
                } catch {
                    firmwareMode = .unknown
                    syncMessage = "RT12COL firmware fingerprint uncertain · health sync paused"
                    return
                }
            }
            if version == FirmwareIdentity.rt12colUnifiedV6Version {
                do {
                    let candidate = try BundledFirmware.rt12colUnifiedLegacyV6.load()
                    guard try await imageMatches(
                        candidate, sites: FirmwareIdentity.rt12colUnifiedV6Sites
                    ) else { throw FirmwareSwitchError.unrecognizedFirmware }
                    firmwareMode = .unified
                    unifiedFirmwareInstalled = true
                    syncMessage = "RT12COL V6 verified · unified Health/Gesture ready"
                    UserDefaults.standard.set(firmwareMode.rawValue, forKey: firmwareModeKey)
                    return
                } catch {
                    firmwareMode = .unknown
                    syncMessage = "RT12COL firmware fingerprint uncertain · health sync paused"
                    return
                }
            }
            if version == FirmwareIdentity.rt12colUnifiedV3Version {
                do {
                    let candidate = try BundledFirmware.rt12colUnifiedLegacyV3.load()
                    guard try await imageMatches(
                        candidate, sites: FirmwareIdentity.rt12colUnifiedV3Sites
                    ) else { throw FirmwareSwitchError.unrecognizedFirmware }
                    firmwareMode = .unified
                    // Legacy images may be recovered or replaced, not entered.
                    unifiedFirmwareInstalled = false
                    syncMessage = "RT12COL V3 revoked · use stock recovery before a reviewed update"
                    UserDefaults.standard.set(firmwareMode.rawValue, forKey: firmwareModeKey)
                    return
                } catch {
                    firmwareMode = .unknown
                    syncMessage = "RT12COL firmware fingerprint uncertain · health sync paused"
                    return
                }
            }
            if version == FirmwareIdentity.rt12colUnifiedV2Version {
                do {
                    let candidate = try BundledFirmware.rt12colUnifiedLegacyV2.load()
                    guard try await imageMatches(
                        candidate, sites: FirmwareIdentity.rt12colUnifiedV2Sites
                    ) else { throw FirmwareSwitchError.unrecognizedFirmware }
                    firmwareMode = .unified
                    // Legacy images may be recovered or replaced, not entered.
                    unifiedFirmwareInstalled = false
                    syncMessage = "RT12COL V2 draft detected · wide-band leased update available"
                    UserDefaults.standard.set(firmwareMode.rawValue, forKey: firmwareModeKey)
                    return
                } catch {
                    firmwareMode = .unknown
                    syncMessage = "RT12COL firmware fingerprint uncertain · health sync paused"
                    return
                }
            }
            if version == FirmwareIdentity.rt12colUnifiedV1Version {
                do {
                    let candidate = try BundledFirmware.rt12colUnifiedLegacyV1.load()
                    guard try await imageMatches(
                        candidate, sites: FirmwareIdentity.rt12colUnifiedV1Sites
                    ) else { throw FirmwareSwitchError.unrecognizedFirmware }
                    firmwareMode = .unified
                    // Legacy images may be recovered or replaced, not entered.
                    unifiedFirmwareInstalled = false
                    syncMessage = "RT12COL V1 detected · wide-band leased V3 update available"
                    UserDefaults.standard.set(firmwareMode.rawValue, forKey: firmwareModeKey)
                    return
                } catch {
                    firmwareMode = .unknown
                    syncMessage = "RT12COL firmware fingerprint uncertain · health sync paused"
                    return
                }
            }
            firmwareMode = .unknown
            syncMessage = "Unknown RT12COL firmware · firmware actions and automatic health sync paused"
            return
        }

        if ringManager.firmware == FirmwareIdentity.stockVersion {
            firmwareMode = .health
            UserDefaults.standard.set(firmwareMode.rawValue, forKey: firmwareModeKey)
            return
        }
        guard ringManager.firmware == FirmwareIdentity.gestureVersion else {
            firmwareMode = .unknown
            syncMessage = "Unknown firmware · automatic health sync paused"
            return
        }

        do {
            let unified = try BundledFirmware.unified.load()
            if try await imageMatches(unified, sites: FirmwareIdentity.unifiedSites) {
                firmwareMode = .unified
                unifiedFirmwareInstalled = true
                UserDefaults.standard.set(firmwareMode.rawValue, forKey: firmwareModeKey)
                return
            }
            let candidate = try BundledFirmware.gesture.load()
            guard try await imageMatches(candidate, sites: FirmwareIdentity.sites) else {
                throw FirmwareSwitchError.unrecognizedFirmware
            }
            firmwareMode = .gesture
            UserDefaults.standard.set(firmwareMode.rawValue, forKey: firmwareModeKey)
        } catch {
            firmwareMode = .unknown
            syncMessage = "Firmware identity uncertain · health sync paused"
        }
    }

    private func imageMatches(_ image: Data, sites: [FirmwareIdentity.Site]) async throws -> Bool {
        for site in sites {
            let replies = try await ringManager.requestUART(
                FirmwareIdentity.readPacket(site), command: 0xcd, timeout: 3
            ) { _, _ in true }
            guard let reply = replies.last, reply.count == 16,
                  reply[1..<(1 + site.length)].elementsEqual(
                    image[site.offset..<(site.offset + site.length)]
                  ) else { return false }
        }
        return true
    }

    private func attachUnifiedMode() async {
        let leaseSafeRT12 = ringManager.firmware == FirmwareIdentity.rt12colUnifiedVersion
            || ringManager.firmware == FirmwareIdentity.rt12colUnifiedV6Version
            || ringManager.firmware == FirmwareIdentity.rt12colUnifiedHIDVersion
            || ringManager.firmware == FirmwareIdentity.rt12colUnifiedHIDV9Version
            || ringManager.firmware == FirmwareIdentity.rt12colUnifiedHIDV10Version
        let transport = A1UnifiedModeTransport(link: ringManager, charging: { [weak self] in
            self?.ring.charging ?? false
        }, requiresMotionHold: firmwareFamily == .rt12col,
           firmwareLeaseSeconds: leaseSafeRT12 ? 10 : 0)
        transport.onMotion = { [weak self] packet, session, sequence, time in
            self?.acceptMotionSample(packet, session: session, sequence: sequence, receivedAt: time)
        }
        transport.onRenewalReport = { [weak self] report in self?.journalRenewal(report) }
        ringManager.onRawMotion = { [weak transport] packet, time in
            transport?.receiveMotion(packet, at: time)
        }
        a1ModeTransport = transport
        modeRecovery.beginInitialAttach()
        defer { modeRecovery.endInitialAttach() }
        do { try await modes.attach(transport) }
        catch {
            a1ModeTransport = nil
            ringManager.onRawMotion = nil
            syncMessage = "Unified mode control unavailable: \(error.localizedDescription)"
        }
    }

    /// Everything but the attempt budget and in-flight flag, which the controller owns.
    private func recoveryInputs(for transport: A1UnifiedModeTransport) -> ModeRecoveryPolicy.Inputs {
        .init(linkReady: ringManager.isReady, unifiedFirmwareInstalled: unifiedFirmwareInstalled,
              modeControlAvailable: modes.available, transportIsCurrent: a1ModeTransport === transport,
              attachInFlight: false, firmwareSwitching: isFirmwareSwitching, attempts: 0)
    }

    /// Runs whenever the coordinator drops its transport. A BLE disconnect
    /// clears `a1ModeTransport` first, so only lost control with a live link
    /// (a failed renewal, start or stop) reaches the policy. Without this the
    /// coordinator stays unavailable until reconnect, and a renewal that failed
    /// its own guard never sent the stop packets. Re-attaching the same A1
    /// transport sends the audited stops (A1 05, A1 02, plus 3B 02 01 00 on
    /// RT12) and re-enables Start.
    private func scheduleModeRecovery() {
        guard let transport = a1ModeTransport else { return }
        modeRecovery.schedule(inputs: recoveryInputsProvider(transport), attach: recoveryAttach(transport))
    }

    /// A heal needs mode control back now; refills the recovery budget.
    private func requestReattach() -> Bool {
        guard let transport = a1ModeTransport, ringManager.isReady else { return false }
        return modeRecovery.retryNow(inputs: recoveryInputsProvider(transport), attach: recoveryAttach(transport))
    }

    private func recoveryInputsProvider(_ transport: A1UnifiedModeTransport) -> () -> ModeRecoveryPolicy.Inputs {
        { [weak self] in
            self?.recoveryInputs(for: transport)
                ?? .init(linkReady: false, unifiedFirmwareInstalled: false, modeControlAvailable: false,
                         transportIsCurrent: false, attachInFlight: false, firmwareSwitching: false, attempts: 0)
        }
    }

    private func recoveryAttach(_ transport: A1UnifiedModeTransport) -> () async throws -> Void {
        { [weak self] in
            guard let self else { throw CancellationError() }
            try await self.modes.attach(transport)
        }
    }

    private func modeRecoveryEvent(_ event: ModeRecoveryController.Event) {
        switch event {
        case .scheduled(let attempt):
            journal.record("mode_recovery_scheduled", fields: ["attempt": attempt, "foreground": isAppActive])
        case .recovered:
            journal.record("mode_recovered", fields: ["foreground": isAppActive])
            // The re-attach published Health before the coordinator was available
            // again, so a refresh deferred for a start could not run until now.
            runDeferredHealthRefreshIfNeeded()
            keeper.controlRestored()
        case .failed(let error, let attempt):
            journal.record("mode_recovery_failed", fields: ["error": error, "attempt": attempt])
            syncMessage = "Unified mode control unavailable: \(error)"
        }
    }

    private func finishFirmwareSwitch() {
        if let operation = firmwareOperation { operations.end(operation) }
        firmwareOperation = nil
        if let startedAt = firmwareSwitchStartedAt {
            let duration = Date().timeIntervalSince(startedAt)
            lastFirmwareSwitchDuration = duration
            print(String(format: "R02 SWITCH VERIFIED %.2f s target=%@ transfer=%.2f s",
                         duration, firmwareMode.rawValue, lastFirmwareTransferDuration ?? 0))
            syncMessage = String(format: "%@ mode verified in %.1f s", firmwareMode.title, duration)
        }
        isFirmwareSwitching = false
        firmwareProgress = 1
        pendingFirmwareTarget = nil
        firmwareSwitchStartedAt = nil
    }

    private func refreshFromStore() {
        today = healthStore?.today(deviceID: activeDeviceID) ?? HealthData.emptyToday()
        if let deviceID = activeDeviceID {
            do {
                let startOfToday = Calendar.autoupdatingCurrent.startOfDay(for: .now)
                let uncertain = try coverageStore?.uncertainIntervals(deviceID: deviceID)
                    .contains { $0.ended == nil || $0.ended! >= startOfToday } ?? false
                healthCoverageMessage = uncertain
                    ? "Some health coverage is unverified. Gesture sessions may leave gaps in heart rate, steps and sleep."
                    : nil
            } catch { healthCoverageMessage = "Health coverage could not be checked." }
        } else { healthCoverageMessage = nil }
        dataRevision &+= 1
    }
}

extension AppModel: RingHIDControlling {
    func perform(_ action: RingHIDAction) -> GestureActionOutcome {
        guard ringHIDFirmwareInstalled else {
            return .failed("install and verify Ring controls firmware first")
        }
        guard let command = action.command(
            hidVersion: ringHIDVersion,
            wheelAmount: RingHIDWheelSettingsStore().load().amount
        ) else {
            return .failed("this ring control needs verified V9 or V10 firmware")
        }
        guard desire.isOn, gestureReady, gestureHealing == nil,
              modes.available, modes.status?.mode == .gesture,
              let transport = a1ModeTransport else {
            return .failed("ring controls are paused until gestures are ready")
        }

        let epoch = desire.epoch
        let code = String(format: "0x%02X", command.code)
        Task { @MainActor [weak self, weak transport] in
            guard let self, let transport,
                  self.ringHIDFirmwareInstalled,
                  action.command(hidVersion: self.ringHIDVersion,
                                 wheelAmount: RingHIDWheelSettingsStore().load().amount) == command,
                  self.desire.isOn,
                  self.desire.epoch == epoch, self.gestureReady,
                  self.gestureHealing == nil,
                  self.a1ModeTransport === transport,
                  self.modes.status?.mode == .gesture else { return }
            do {
                try await transport.sendHIDCommand(command)
                self.journal.record("hid_action", fields: self.phaseFields([
                    "action": code, "result": "sent", "epoch": epoch,
                ]))
            } catch {
                self.journal.record("hid_action", fields: self.phaseFields([
                    "action": code, "result": "failed", "epoch": epoch,
                    "error": error.localizedDescription,
                ]))
            }
        }
        return .performed
    }
}

/// Intents drive sessions through the same entry points as the Gestures screen.
extension AppModel: GestureModeControlling {}
