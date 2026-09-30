import Foundation

/// How a start intent's calibration wait ended, decided together with the
/// ready announcer so a calibration is announced exactly once: by the
/// intent's dialog, the screen, or one notification.
enum GestureCalibrationWait: String {
    /// Calibrated within the budget: the dialog says "Gestures ready ✓".
    case calibrated
    /// Still calibrating: one notification follows when it completes.
    case pending
    /// The session is healing (reconnecting); the notification follows too.
    case reconnecting
    /// The session ended during the wait.
    case ended
    /// The start this intent joined never reached Gesture: nothing was on.
    case notStarted = "not_started"
    /// Another start this intent joined is still entering at the deadline.
    case starting
    /// The control does not wait (test fakes): the reply is the plain start reply.
    case unsupported
}

/// A start intent's calibration wait and its decision, kept apart from
/// `AppModel` so it runs under XCTest on a fake clock. The reply and the
/// ready announcer are settled in one synchronous step after the wait, so a
/// calibration is announced exactly once. The wait ends early when the
/// session calibrates, ends, or its heal is waiting for the link; a heal with
/// the link up is waited out (it may resume and calibrate in time).
@MainActor
struct GestureCalibrationWaiter {
    /// The owner's state, read at each poll.
    struct Probes {
        var epoch: () -> Int
        var isOn: () -> Bool
        var isArming: () -> Bool
        /// The desired session's calibration is complete.
        var ready: () -> Bool
        var healing: () -> Bool
        var waitingForLink: () -> Bool
    }

    var probes: Probes
    var announcer: GestureReadyAnnouncer
    var now: () -> Double = { ProcessInfo.processInfo.systemUptime }
    var sleep: (Duration) async throws -> Void = { try await Task.sleep(for: $0) }

    func wait(timeout: TimeInterval) async -> GestureCalibrationWait {
        let probes = probes
        guard probes.isOn() || probes.isArming() else { return .ended }
        let epoch = probes.epoch()
        var sawOn = probes.isOn()
        announcer.intentWaiting(epoch: epoch)
        _ = await GestureIntentLogic.waitUntil(timeout: timeout, now: now, sleep: sleep) {
            let current = probes.epoch() == epoch
            if current, probes.isOn() { sawOn = true }
            return !current || !(probes.isOn() || probes.isArming())
                || (probes.isOn() && (probes.ready() || probes.waitingForLink()))
        }
        let result: GestureCalibrationWait
        if probes.epoch() != epoch || !(probes.isOn() || probes.isArming()) {
            result = sawOn ? .ended : .notStarted
        } else if probes.isArming() {
            result = .starting
        } else if probes.ready() {
            result = .calibrated
        } else if probes.healing() {
            result = .reconnecting
        } else {
            result = .pending
        }
        switch result {
        case .calibrated, .pending, .reconnecting:
            announcer.intentReplied(epoch: epoch, calibrated: result == .calibrated)
        case .ended, .notStarted, .starting, .unsupported:
            announcer.intentLeft(epoch: epoch)
        }
        return result
    }
}

/// Posts "Gestures ready ✓" at most once per arm: after a start intent
/// replied before calibration finished, or after a heal that needed a fresh
/// calibration. Never while R02 is in front (the screen shows it), never for
/// a heal that kept the calibration, and silently nothing when notifications
/// are not authorized: it never asks for permission.
@MainActor
final class GestureReadyAnnouncer {
    enum Why: String {
        case intentStart = "intent_start"
        case healRecalibration = "heal_recalibration"
    }

    /// How one calibration was announced, for `calibrated_ready`.
    enum Announcement: String {
        case dialog, notification, screen, unauthorized, none
    }

    static let identifier = "r02.gestures.ready"
    static let readyTitle = "Gestures ready ✓"
    static let recalibrateTitle = "Gestures reconnected"
    static let recalibrateBody = "Hold your fingers down for 3 seconds to recalibrate."
    /// A background recalibration prompt is posted at most this often.
    static let promptSpacing: Double = 600

    private enum State: Equatable {
        case idle
        /// Start intents are waiting to answer in their dialogs: `waiters` of
        /// them, for one epoch. `announced`: a dialog has the calibration to
        /// announce (or announced it). `pending`: the notification to arm
        /// once the last waiter leaves without announcing.
        case dialog(epoch: Int, waiters: Int, announced: Bool, pending: Why?)
        case armed(epoch: Int, why: Why)
    }

    private var state: State = .idle
    private var lastPromptAt: Double?
    private let notifications: NotificationPosting
    private let now: () -> Double

    init(notifications: NotificationPosting, now: @escaping () -> Double = { GestureContinuousTime.now() }) {
        self.notifications = notifications
        self.now = now
    }

    var isArmed: Bool { if case .armed = state { return true } else { return false } }
    /// Start intents still waiting to answer in their dialogs.
    var dialogWaiters: Int { if case .dialog(_, let waiters, _, _) = state { return waiters } else { return 0 } }

    /// A start intent is waiting for calibration: a calibration now is
    /// announced by a dialog. Concurrent waiters of one epoch are counted, so
    /// one that leaves early never arms a notification another's dialog will
    /// duplicate.
    func intentWaiting(epoch: Int) {
        switch state {
        case .dialog(let waiting, let waiters, let announced, let pending) where waiting == epoch:
            state = .dialog(epoch: epoch, waiters: waiters + 1, announced: announced, pending: pending)
        case .armed(let armed, let why) where armed == epoch:
            state = .dialog(epoch: epoch, waiters: 1, announced: false, pending: why)
        default:
            state = .dialog(epoch: epoch, waiters: 1, announced: false, pending: nil)
        }
    }

    /// An intent decided its reply, in the same synchronous step that read
    /// `calibrated`. Calibrated: the dialog announces it. Otherwise the one
    /// notification is armed once no other dialog of the epoch is waiting.
    func intentReplied(epoch: Int, calibrated: Bool) {
        guard case .dialog(let waiting, let waiters, let announced, let pending) = state, waiting == epoch else {
            if !calibrated { state = .armed(epoch: epoch, why: .intentStart) }
            return
        }
        settle(epoch: epoch, waiters: waiters - 1, announced: announced || calibrated,
               pending: calibrated ? pending : (pending ?? .intentStart))
    }

    /// An intent's wait ended with nothing to announce (the session ended,
    /// never started, or is still starting): it leaves without arming.
    func intentLeft(epoch: Int) {
        guard case .dialog(let waiting, let waiters, let announced, let pending) = state, waiting == epoch else { return }
        settle(epoch: epoch, waiters: waiters - 1, announced: announced, pending: pending)
    }

    private func settle(epoch: Int, waiters: Int, announced: Bool, pending: Why?) {
        if waiters > 0 {
            state = .dialog(epoch: epoch, waiters: waiters, announced: announced, pending: pending)
        } else if !announced, let pending {
            state = .armed(epoch: epoch, why: pending)
        } else {
            state = .idle
        }
    }

    /// A heal re-entered Gesture with a fresh calibration. In the background
    /// the wearer is asked once (rate-limited) to hold their fingers down,
    /// unless a start intent's dialog is still waiting: it answers, and the
    /// heal's notification is armed only if it leaves before calibration.
    func healNeedsCalibration(epoch: Int, appActive: Bool) {
        if case .dialog(let waiting, let waiters, _, _) = state, waiting == epoch {
            state = .dialog(epoch: epoch, waiters: waiters, announced: false, pending: .healRecalibration)
            return
        }
        state = .armed(epoch: epoch, why: .healRecalibration)
        guard !appActive else { return }
        let time = now()
        if let lastPromptAt, time - lastPromptAt < Self.promptSpacing { return }
        if notifications.post(title: Self.recalibrateTitle, body: Self.recalibrateBody,
                              identifier: Self.identifier) == .performed {
            lastPromptAt = time
        }
    }

    /// The first calibration of a Gesture segment. Disarms whatever happens.
    @discardableResult
    func calibrated(epoch: Int, appActive: Bool) -> Announcement {
        switch state {
        case .idle:
            return .none
        case .dialog(let waiting, let waiters, _, _):
            guard waiting == epoch else { return .none }
            // A waiting dialog reads it right away and announces it.
            state = .dialog(epoch: epoch, waiters: waiters, announced: true, pending: nil)
            return .dialog
        case .armed(let armed, let why):
            state = .idle
            guard armed == epoch else { return .none }
            if appActive { return .screen }
            let body = why == .intentStart
                ? "Calibration finished. Ring gestures are on."
                : "Reconnected and recalibrated. Ring gestures are on."
            let outcome = notifications.post(title: Self.readyTitle, body: body, identifier: Self.identifier)
            return outcome == .performed ? .notification : .unauthorized
        }
    }

    /// The session ended, or a new one began.
    func reset() { state = .idle }
}
