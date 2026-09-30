import Foundation

/// Why a Gesture session was started or ended. Raw values are written to the
/// lifecycle journal.
enum GestureSessionReason: String, CaseIterable {
    case user
    case intent
    case gestureAction = "gesture_action"
    case autoReturn = "auto_return"
    case idle
    case backgrounded
    case staleStream = "stale_stream"
    case renewal
    case diagnostics
    case modelUnavailable = "model_unavailable"
    case disconnected
    /// The ring refused Gesture on its charger.
    case charging
    /// Disconnected for longer than the heal window.
    case ringGone = "ring_gone"
    /// Heal attempts failed for longer than the heal window.
    case healGaveUp = "heal_gave_up"
    case ringForgotten = "ring_forgotten"
    /// A sticky session's own restart (journal only; it ends nothing).
    case heal
    /// The ring reached Gesture with no session wanting it (a stop won the
    /// race): returned to Health.
    case orphan

    /// How the last-session summary names the end of a session.
    var endTitle: String {
        switch self {
        case .user: return "stopped in R02"
        case .intent: return "stopped by Shortcut"
        case .gestureAction: return "paused by gesture"
        case .autoReturn: return "session timer"
        case .idle: return "idle pause"
        case .backgrounded: return "R02 left the screen"
        case .staleStream: return "motion stream went stale"
        case .renewal: return "lease renewal failed"
        case .diagnostics: return "capture finished"
        case .modelUnavailable: return "gesture model unavailable"
        case .disconnected: return "ring disconnected"
        case .charging: return "ring on charger"
        case .ringGone: return "ring out of range"
        case .healGaveUp: return "couldn't reconnect"
        case .ringForgotten: return "ring forgotten"
        case .heal: return "reconnecting"
        case .orphan: return "no session running"
        }
    }
}

enum GestureRequestSource: String {
    case app, intent

    var reason: GestureSessionReason { self == .intent ? .intent : .user }
    /// A stop request's end reason.
    var endReason: GestureEndReason { self == .intent ? .intent : .user }
}

enum GestureTransition: String {
    case entering, leaving
}

enum GestureRequestOutcome: Equatable {
    case started
    case stopped
    case alreadyActive
    case alreadyStopped
    case needsForeground
    case unavailable
    case charging
    case busy
    case notConnected
    case timedOut
    /// A stop withdrew a start that was still waiting for the ring; it stays in Health.
    case startCancelled
    case failed(String)

    init(error: Error) {
        if let error = error as? FirmwareSwitchError, case .charging = error {
            self = .charging
        } else if let error = error as? RingProtocolError, case .busy = error {
            self = .busy
        } else if let error = error as? RingProtocolError, case .notReady = error {
            self = .notConnected
        } else if let error = error as? UnifiedModeError, error == .unavailable {
            self = .unavailable
        } else {
            self = .failed(error.localizedDescription)
        }
    }

    /// Nothing to report as a failure: the requested mode holds (or is being
    /// reached), or a later stop withdrew the start, which is what its owner asked for.
    var succeeded: Bool {
        switch self {
        case .started, .stopped, .alreadyActive, .alreadyStopped, .startCancelled: return true
        default: return false
        }
    }

    var journalName: String {
        switch self {
        case .started: return "started"
        case .stopped: return "stopped"
        case .alreadyActive: return "already_active"
        case .alreadyStopped: return "already_stopped"
        case .needsForeground: return "needs_foreground"
        case .unavailable: return "unavailable"
        case .charging: return "charging"
        case .busy: return "busy"
        case .notConnected: return "not_connected"
        case .timedOut: return "timed_out"
        case .startCancelled: return "start_cancelled"
        case .failed: return "failed"
        }
    }

    var message: String {
        switch self {
        case .started: return "Gesture session started."
        case .stopped: return "Returned to Health."
        case .alreadyActive: return "A Gesture session is already running."
        case .alreadyStopped: return "The ring is already in Health."
        case .needsForeground: return "Open R02 to start gestures, or turn on Keep gestures active in background."
        case .unavailable: return "Gesture mode isn't available on this ring right now."
        case .charging: return "Take the ring off its charger to start gestures."
        case .busy: return "The ring is busy. Try again in a moment."
        case .notConnected: return "The ring isn't connected. Open R02 to reconnect."
        case .timedOut: return "The ring didn't get ready in time."
        case .startCancelled: return "Start cancelled. The ring stays in Health."
        case .failed(let reason): return reason
        }
    }
}

/// Everything start readiness depends on, read from the model at one instant.
struct GestureModeSnapshot: Equatable {
    enum Link: String {
        case bluetoothOff, unpaired, recoveryOnly, connecting, ready
    }

    var link: Link
    /// Identification and the first mode attach finished for this connection.
    var connectionSetupComplete: Bool
    var unifiedFirmwareInstalled: Bool
    /// An attach, or a scheduled mode-control recovery, is pending.
    var modeAttachInFlight: Bool
    var modeControlAvailable: Bool
    var mode: RingRuntimeMode?
    var charging: Bool
    var transition: GestureTransition?
    /// Another operation (sync, settings, live heart rate, mode, firmware) owns the ring.
    var ringBusy: Bool
    var firmwareSwitching: Bool
    var appActive: Bool
    var keepGesturesInBackground: Bool
    /// A start request is waiting for readiness or entering, or a Shortcut's
    /// start is continuing in R02. Kept apart from `gestureActive`: readiness
    /// reads that, and a waiting start must not see itself as already active.
    var startPending = false
    /// Seconds since the newest pending start was requested; nil when none
    /// is pending or the time is unknown.
    var startPendingAge: TimeInterval? = nil
    /// Seconds since the running session reached Gesture; nil when none runs.
    var sessionAge: TimeInterval? = nil
    /// Seconds since the last start intent answered after its calibration
    /// wait; nil when none has. The Toggle grace also runs from it.
    var startIntentRepliedAge: TimeInterval? = nil
    /// A session that ended on its own (timers, charger, ring gone, heal
    /// given up) in the last ten minutes, not yet followed by another.
    var recentAutomaticEnd: AutomaticEnd? = nil
    /// The user wants gestures (`GestureDesire` on): a sticky session, running
    /// or healing. Only an allowed end reason clears it.
    var gestureDesired = false
    /// A heal is re-entering Gesture for the desired session.
    var healing = false
    /// The desired session's fingers-down calibration is complete.
    var calibrated = false
    /// The ring is in (or entering) Gesture with no session wanting it, while
    /// its return to Health is enforced: a start waits for that return.
    var orphanGesture = false
    /// A start intent is waiting for calibration to answer in its dialog.
    var startIntentWaiting = false

    struct AutomaticEnd: Equatable {
        static let reportWindow: TimeInterval = 600

        let reason: GestureSessionReason
        let secondsAgo: TimeInterval

        /// e.g. "Gestures had stopped 12 s ago (motion stream went stale)."
        var note: String {
            let seconds = secondsAgo.isFinite ? max(0, Int(secondsAgo.rounded())) : 0
            let ago = seconds < 60 ? "\(seconds) s" : "\(seconds / 60) min"
            return "Gestures had stopped \(ago) ago (\(reason.endTitle))."
        }
    }

    /// The last automatic end, timed on a clock that keeps running while the
    /// phone sleeps. `ProcessInfo.systemUptime` stops during sleep, and an
    /// app kept alive in the background by its Bluetooth link barely advances
    /// it overnight, so it would report a night-old end as minutes old.
    struct AutomaticEndTracker {
        private var last: (reason: GestureSessionReason, at: ContinuousClock.Instant)?
        private let now: () -> ContinuousClock.Instant

        init(now: @escaping () -> ContinuousClock.Instant = { ContinuousClock.now }) { self.now = now }

        mutating func ended(_ reason: GestureSessionReason) { last = (reason, now()) }
        mutating func clear() { last = nil }

        /// The end, while it is at most `AutomaticEnd.reportWindow` old.
        var recent: AutomaticEnd? {
            guard let last else { return nil }
            let elapsed = last.at.duration(to: now()).components
            let ago = Double(elapsed.seconds) + Double(elapsed.attoseconds) / 1e18
            return ago <= AutomaticEnd.reportWindow ? AutomaticEnd(reason: last.reason, secondsAgo: ago) : nil
        }
    }

    var isConnected: Bool { link == .ready }

    /// Active, or on its way. A desired session is active while it heals. A
    /// session being stopped is not, nor Gesture no session wants: a start
    /// then waits for the return (`.returning`) and enters again.
    var gestureActive: Bool {
        if gestureDesired { return true }
        return !orphanGesture && ringGestureActive
    }

    /// The ring itself is in Gesture or on its way, whoever wants it.
    var ringGestureActive: Bool {
        transition != .leaving && (transition == .entering || mode == .gesture || mode == .enteringGesture)
    }

    /// Why Start is unavailable, naming the actual cause. Firmware maintenance
    /// is suggested only once the ring has identified as a non-unified image.
    var unavailableReason: String {
        switch link {
        // Also covers denied permission and unsupported hardware, so name neither alone.
        case .bluetoothOff: return "Bluetooth isn't available · check it's on and allowed for R02."
        case .unpaired: return "No ring paired yet."
        case .recoveryOnly: return "Only the ring's firmware recovery service is reachable · see Settings."
        case .connecting: return "Ring not connected · R02 reconnects when it's in range."
        case .ready: break
        }
        if !connectionSetupComplete { return "Checking ring firmware…" }
        if !unifiedFirmwareInstalled {
            return "Gesture sessions need the verified unified image. Firmware maintenance is under Settings."
        }
        if modeAttachInFlight { return "Preparing gesture control…" }
        return "Gesture control unavailable · reconnect the ring to recover."
    }
}

/// When the pending start the user is waiting on was requested, for the
/// Toggle debounce (`GestureModeSnapshot.startPendingAge`). Only the request
/// that creates the pending state, or the user's Continue tap in R02, sets
/// it: a request made while a start is already pending (a Shortcut
/// continuation's own request after its activation and busy waits, or a Start
/// that returns at once) must not re-arm the debounce for the older start. A
/// stop withdraws every pending start, so it clears the stamp, and the next
/// start sets it even before a withdrawn start has left the pending count.
struct GestureStartStamp: Equatable {
    private(set) var requestedAt: Double?

    mutating func startRequested(at now: Double, alreadyPending: Bool) {
        if !alreadyPending || requestedAt == nil { requestedAt = now }
    }

    mutating func userContinued(at now: Double) { requestedAt = now }

    mutating func stopRequested() { requestedAt = nil }

    func pendingAge(at now: Double, pending: Bool) -> TimeInterval? {
        pending ? requestedAt.map { now - $0 } : nil
    }
}

enum GestureStartReadiness: String {
    case ready
    case alreadyActive
    case connecting, identifying, attaching, returning
    case needsForeground, notConnected, unavailable, charging, busy
    /// A stop withdrew the start while it waited. Never produced by `evaluate`.
    case cancelled

    /// Pure: order matters, and the first matching rule wins. The keeper
    /// passes `ignoringDesire` to judge whether the ring itself is ready.
    static func evaluate(_ s: GestureModeSnapshot, ignoringDesire: Bool = false) -> Self {
        if !ignoringDesire {
            // A sticky session is running or healing: it is the session.
            if s.gestureDesired { return .alreadyActive }
            if s.orphanGesture { return .returning }
        }
        if s.transition == .leaving || s.mode == .returningHealth { return .returning }
        if ignoringDesire ? s.ringGestureActive : s.gestureActive { return .alreadyActive }
        if !s.appActive && !s.keepGesturesInBackground { return .needsForeground }
        switch s.link {
        case .bluetoothOff, .unpaired, .recoveryOnly: return .notConnected
        case .connecting: return .connecting
        case .ready: break
        }
        if !s.connectionSetupComplete { return .identifying }
        if s.modeAttachInFlight { return .attaching }
        if s.firmwareSwitching { return .busy }
        guard s.unifiedFirmwareInstalled, s.modeControlAvailable, s.mode == .health else { return .unavailable }
        if s.charging { return .charging }
        if s.ringBusy { return .busy }
        return .ready
    }

    /// Worth waiting for; anything else is final.
    var isWaiting: Bool {
        switch self {
        case .connecting, .identifying, .attaching, .returning: return true
        default: return false
        }
    }

    /// The request's result when starting cannot proceed now; for a waiting
    /// state, the result once the wait has timed out. Nil only for `.ready`.
    var outcome: GestureRequestOutcome? {
        switch self {
        case .ready: return nil
        case .alreadyActive: return .alreadyActive
        case .connecting, .notConnected: return .notConnected
        case .identifying, .attaching, .returning: return .timedOut
        case .needsForeground: return .needsForeground
        case .unavailable: return .unavailable
        case .charging: return .charging
        case .busy: return .busy
        case .cancelled: return .startCancelled
        }
    }

    /// The session panel's status line while a start waits.
    var waitingNote: String {
        switch self {
        case .connecting: return "Starting · waiting for the ring to connect"
        case .identifying: return "Starting · checking ring firmware"
        case .attaching: return "Starting · preparing gesture control"
        case .returning: return "Starting · waiting for the return to Health"
        default: return "Starting…"
        }
    }

    /// Re-evaluates every `poll` until the state is final or `timeout` passes
    /// on `now`. A cancelled caller stops waiting at once.
    @MainActor
    static func wait(timeout: TimeInterval, poll: Duration = .milliseconds(100),
                     now: () -> Double,
                     sleep: (Duration) async throws -> Void,
                     evaluate: () -> Self) async -> (readiness: Self, waited: Double) {
        let began = now()
        var readiness = evaluate()
        while readiness.isWaiting, now() - began < timeout {
            do { try await sleep(poll) } catch { break }
            readiness = evaluate()
        }
        return (readiness, now() - began)
    }
}

enum GestureSessionSummary {
    /// e.g. "Last session 4 min 12 s · 7 gestures, 5 actions · paused by gesture".
    static func text(duration: TimeInterval, recognized: Int, performed: Int,
                     reason: GestureSessionReason, reconnects: Int = 0) -> String {
        let seconds = duration.isFinite ? max(0, Int(duration.rounded())) : 0
        let length: String
        if seconds < 60 { length = "\(seconds) s" }
        else if seconds < 3_600 { length = "\(seconds / 60) min \(seconds % 60) s" }
        else { length = "\(seconds / 3_600) h \(seconds / 60 % 60) min" }
        let gestures = recognized == 1 ? "1 gesture" : "\(recognized) gestures"
        let actions = performed == 1 ? "1 action" : "\(performed) actions"
        let healed = reconnects == 0 ? "" : (reconnects == 1 ? " · 1 reconnect" : " · \(reconnects) reconnects")
        return "Last session \(length) · \(gestures), \(actions)\(healed) · \(reason.endTitle)"
    }
}

/// Mode-control recovery after the coordinator dropped its transport while
/// the BLE link stayed up (a renewal, start or stop failure). Re-attaching the
/// same A1 transport sends the audited stop packets and re-enables Start. The
/// delay lets an in-flight `stopRaw` from the failed operation finish first,
/// so two stop sequences never interleave on the UART.
enum ModeRecoveryPolicy {
    static let delay = Duration.milliseconds(600)
    /// Consecutive failed re-attaches per connection; a success resets the count.
    static let maxAttempts = 3

    struct Inputs: Equatable {
        var linkReady: Bool
        var unifiedFirmwareInstalled: Bool
        var modeControlAvailable: Bool
        /// The transport that lost control is still the one for this connection.
        var transportIsCurrent: Bool
        var attachInFlight: Bool
        var firmwareSwitching: Bool
        var attempts: Int
    }

    static func shouldReattach(_ inputs: Inputs) -> Bool {
        inputs.linkReady && inputs.unifiedFirmwareInstalled && !inputs.modeControlAvailable
            && inputs.transportIsCurrent && !inputs.attachInFlight && !inputs.firmwareSwitching
            && inputs.attempts < maxAttempts
    }
}

/// Runs `ModeRecoveryPolicy` for one connection: owns the attempt budget, the
/// in-flight flag (which also blocks the nested report that `attach` itself
/// makes when it resets the coordinator) and the delayed re-attach.
@MainActor
final class ModeRecoveryController {
    enum Event: Equatable {
        case scheduled(attempt: Int)
        case recovered
        case failed(String, attempt: Int)
    }

    /// Consecutive failed re-attaches; a success or a new connection resets it.
    private(set) var attempts = 0
    /// The initial attach, or a scheduled or running recovery.
    private(set) var attachInFlight = false {
        didSet { if oldValue != attachInFlight { onInFlightChange?(attachInFlight) } }
    }
    var onInFlightChange: ((Bool) -> Void)?
    var onEvent: ((Event) -> Void)?

    private let delay: Duration
    private let sleep: (Duration) async throws -> Void
    private var task: Task<Void, Never>?

    init(delay: Duration = ModeRecoveryPolicy.delay,
         sleep: @escaping (Duration) async throws -> Void = { try await Task.sleep(for: $0) }) {
        self.delay = delay
        self.sleep = sleep
    }

    /// A new connection's first attach: cancels any recovery and refills the budget.
    func beginInitialAttach() {
        cancelScheduled()
        attempts = 0
        attachInFlight = true
    }

    func endInitialAttach() { attachInFlight = false }

    /// A sticky session's heal needs mode control back: refills the budget
    /// and schedules a re-attach unless one is already pending or running
    /// (never a second attach racing the first). True when one is pending.
    @discardableResult
    func retryNow(inputs: @escaping () -> ModeRecoveryPolicy.Inputs,
                  attach: @escaping () async throws -> Void) -> Bool {
        if attachInFlight { return true }
        cancelScheduled()
        attempts = 0
        return schedule(inputs: inputs, attach: attach)
    }

    /// The link dropped: nothing to recover on this connection any more.
    func reset() {
        cancelScheduled()
        attempts = 0
        attachInFlight = false
    }

    /// The coordinator lost control. `inputs` is read now and again after the
    /// delay (this controller supplies `attempts` and `attachInFlight`);
    /// `attach` re-attaches the same transport. False when nothing was scheduled.
    @discardableResult
    func schedule(inputs: @escaping () -> ModeRecoveryPolicy.Inputs,
                  attach: @escaping () async throws -> Void) -> Bool {
        guard ModeRecoveryPolicy.shouldReattach(filled(inputs(), attachInFlight: attachInFlight)) else { return false }
        attachInFlight = true
        onEvent?(.scheduled(attempt: attempts + 1))
        let sleep = self.sleep, delay = self.delay
        task = Task { [weak self] in
            do { try await sleep(delay) } catch { return }
            await self?.attempt(inputs: inputs, attach: attach)
        }
        return true
    }

    private func attempt(inputs: @escaping () -> ModeRecoveryPolicy.Inputs,
                         attach: @escaping () async throws -> Void) async {
        task = nil
        // This recovery owns the in-flight flag; every other guard is re-checked after the delay.
        guard ModeRecoveryPolicy.shouldReattach(filled(inputs(), attachInFlight: false)) else {
            attachInFlight = false
            return
        }
        attempts += 1
        do {
            try await attach()
            attempts = 0
            attachInFlight = false
            onEvent?(.recovered)
        } catch {
            attachInFlight = false
            onEvent?(.failed(error.localizedDescription, attempt: attempts))
            schedule(inputs: inputs, attach: attach)
        }
    }

    private func filled(_ inputs: ModeRecoveryPolicy.Inputs, attachInFlight: Bool) -> ModeRecoveryPolicy.Inputs {
        var inputs = inputs
        inputs.attempts = attempts
        inputs.attachInFlight = attachInFlight
        return inputs
    }

    private func cancelScheduled() {
        task?.cancel()
        task = nil
    }
}

/// The "Keep gestures active in background" setting. Default ON: a session
/// keeps running while R02 is not in front.
enum GestureBackgroundSessions {
    static let storageKey = "gestureKeepActiveInBackground"

    static func stored(in defaults: UserDefaults = .standard) -> Bool {
        defaults.object(forKey: storageKey) as? Bool ?? true
    }

    static func store(_ enabled: Bool, in defaults: UserDefaults = .standard) {
        defaults.set(enabled, forKey: storageKey)
    }
}

extension GestureIdleTracker {
    /// Sleeps until the idle deadline, following it as recognized gestures move
    /// it later. True once expired; false when the tracker stopped (`remaining`
    /// is nil) or the sleep was cancelled.
    @MainActor
    static func sleepUntilExpired(remaining: () -> Double?,
                                  sleep: (Duration) async throws -> Void) async -> Bool {
        while true {
            guard let left = remaining() else { return false }
            if left <= 0 { return true }
            do { try await sleep(.seconds(left)) } catch { return false }
        }
    }
}

/// What App Intents need from the model. `AppModel` conforms. A stop request
/// also withdraws every start still waiting (`snapshot.startPending`).
@MainActor
protocol GestureModeControlling: AnyObject {
    var gestureModeSnapshot: GestureModeSnapshot { get }
    /// Start waits up to `readinessTimeout` for the ring to connect and attach;
    /// stop never waits for readiness.
    @discardableResult
    func requestGestureSession(_ enabled: Bool, source: GestureRequestSource,
                               readinessTimeout: TimeInterval) async -> GestureRequestOutcome
    /// Journals what an intent saw (this snapshot) and what it decided, before
    /// any request. `kind` is toggle, start or stop.
    func noteIntent(_ kind: String, decision: String)
    /// After a start intent's request returned `.started` or `.alreadyActive`:
    /// waits up to `timeout` for the fingers-down calibration, then decides,
    /// in one synchronous step, the reply and whether one "Gestures ready ✓"
    /// notification follows.
    func awaitCalibration(timeout: TimeInterval) async -> GestureCalibrationWait
}

extension GestureModeControlling {
    func noteIntent(_ kind: String, decision: String) {}
    func awaitCalibration(timeout: TimeInterval) async -> GestureCalibrationWait { .unsupported }
}

/// Who owns a ring that is in, or entering, Gesture. Pure, so the rules the
/// model applies (start readiness, Health enforcement, a deferred return to
/// Health) are tested without Bluetooth.
enum GestureOwnership {
    /// A user or intent start of the arming desire is entering Gesture from
    /// Health: that start's own Gesture, never an orphan.
    static func ownStartEntering(desireArming: Bool, transition: GestureTransition?,
                                 enteringReason: GestureSessionReason?) -> Bool {
        desireArming && transition == .entering && (enteringReason == .user || enteringReason == .intent)
    }

    /// Gesture (or an entry) that no session wants. Judged without the
    /// arming of a start that is still waiting for readiness, so that start
    /// sees `.returning` and waits for the return instead of reading the
    /// orphan as its own running session.
    static func orphan(desireOn: Bool, desireArming: Bool, ringInGesture: Bool,
                       transition: GestureTransition?, enteringReason: GestureSessionReason?) -> Bool {
        guard !desireOn, ringInGesture || transition == .entering else { return false }
        return !ownStartEntering(desireArming: desireArming, transition: transition, enteringReason: enteringReason)
    }

    /// A return to Health scheduled when a session ended still applies: no
    /// session turned on since, and no start is entering (the ring was then
    /// already in Health for it, and a stop now would be held and sent right
    /// after that start's A1 04).
    static func returnToHealthApplies(desireOn: Bool, desireArming: Bool, transition: GestureTransition?,
                                      enteringReason: GestureSessionReason?) -> Bool {
        !desireOn && !ownStartEntering(desireArming: desireArming, transition: transition,
                                       enteringReason: enteringReason)
    }
}

/// A record, kept in `UserDefaults` while a Gesture session is on, so a
/// launch after iOS terminated R02 reports that silent end exactly once. The
/// desired state itself is never restored: nothing starts Gesture on its own.
struct GestureSessionMarker: Codable, Equatable {
    static let key = "gestureSessionMarker.v1"
    static let noticeIdentifier = "r02.gestures.terminated"

    var epoch: Int
    var startedAt: Date
    /// The last passed renewal (or the start): about when R02 was last alive.
    var lastAliveAt: Date

    static func load(from defaults: UserDefaults) -> GestureSessionMarker? {
        guard let data = defaults.data(forKey: key) else { return nil }
        return try? JSONDecoder().decode(GestureSessionMarker.self, from: data)
    }

    func save(to defaults: UserDefaults) {
        guard let data = try? JSONEncoder().encode(self) else { return }
        defaults.set(data, forKey: Self.key)
    }

    static func clear(in defaults: UserDefaults) { defaults.removeObject(forKey: key) }

    /// The marker a previous process left, removed so it is reported once.
    static func take(from defaults: UserDefaults) -> GestureSessionMarker? {
        let marker = load(from: defaults)
        if defaults.object(forKey: key) != nil { clear(in: defaults) }
        return marker
    }

    var noticeTitle: String { "Gestures turned off" }

    func noticeBody(lastAlive: String? = nil) -> String {
        let time = lastAlive ?? lastAliveAt.formatted(date: .omitted, time: .shortened)
        return "iOS closed R02 while gestures were on (last active at \(time)). The ring returns to Health."
    }
}
