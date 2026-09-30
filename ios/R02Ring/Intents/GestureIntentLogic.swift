import Foundation

/// What a gesture App Intent tells the user, and whether it should ask to
/// continue in R02 instead of finishing in the background.
struct GestureIntentReply: Equatable {
    let outcome: GestureRequestOutcome
    let message: String
    /// Only a start can ask for the foreground; stop never does.
    let needsForeground: Bool
}

/// The decisions behind the Toggle, Start and Stop intents, kept free of
/// AppIntents so they run under XCTest against a fake model.
enum GestureIntentLogic {
    /// How long a background start waits for the ring to connect and attach.
    static let readinessTimeout: TimeInterval = 10
    /// Once R02 is in front, the start may wait longer for a slow reconnect.
    static let foregroundReadinessTimeout: TimeInterval = 30
    /// A foreground continuation can run before SwiftUI reports the scene active.
    static let activationTimeout: TimeInterval = 5
    /// How long automatic health syncs wait for a continuation the user may
    /// still be deciding on, from the moment an intent asks to continue in R02.
    static let foregroundHoldTimeout: TimeInterval = 30

    /// A Toggle this soon after the pending start was requested is taken as
    /// the same Back Tap firing twice, or a re-tap before any feedback: it
    /// reports the start instead of withdrawing it. Later, Toggle cancels.
    static let pendingStartDebounce: TimeInterval = 2
    /// A Toggle this soon after a session reached Gesture reports it instead
    /// of stopping it. Pause Gestures, R02's button and a mapped gesture still
    /// stop at once.
    static let runningStopGrace: TimeInterval = 3
    static let stillStartingMessage =
        "Still starting. Gestures turn on when the ring is ready; use Pause Gestures to cancel."
    static let justStartedMessage =
        "Gestures just turned on. Back Tap again in a few seconds to turn them off, or use Pause Gestures."
    /// How long after the tap a start intent may still wait for the
    /// fingers-down calibration: the calibration wait gets what is left of
    /// this. The readiness wait (up to `readinessTimeout`) and the A1 04 entry
    /// (up to 3 s) come first and are not cut by it, so a slow reconnect can
    /// hold the reply for about 13 s, inside the background intent budget.
    static let calibrationBudget: TimeInterval = 8
    static let readyMessage = "Gestures ready ✓"
    static let calibratingMessage = "Gestures on — hold fingers down to finish calibrating"
    static let reconnectingMessage = "Gestures on — reconnecting to the ring"
    static let turnedOffMessage = "Gestures turned off."
    static let notStartedMessage = "No Gesture session started. Check the ring and try again."
    static let stillCalibratingMessage =
        "Still calibrating. Hold your fingers down; use Pause Gestures to turn gestures off."

    /// Toggle stops a session that is running or still entering, and withdraws
    /// a start that is still waiting; otherwise it starts one. A session that
    /// is being stopped is not active, so a Toggle then starts again. Within
    /// `pendingStartDebounce` of a start request, or `runningStopGrace` of a
    /// session starting, it says so and changes nothing.
    /// The running-stop grace is measured from the later of the session's
    /// start and the last start intent's reply, so a Back Tap that fired twice
    /// is still one tap when iOS queued the second behind the first's
    /// calibration wait. A Toggle inside that grace while another start
    /// intent still waits reports "still calibrating"; past it, it stops.
    /// A desired session that is healing counts as running, so a Toggle then
    /// turns gestures off.
    @MainActor
    static func toggle(_ control: any GestureModeControlling,
                       timeout: TimeInterval = readinessTimeout,
                       now: () -> Double = { ProcessInfo.processInfo.systemUptime }) async -> GestureIntentReply {
        let began = now()
        let snapshot = control.gestureModeSnapshot
        if snapshot.startPending, let age = snapshot.startPendingAge, age <= pendingStartDebounce {
            control.noteIntent("toggle", decision: "kept_pending_start")
            return GestureIntentReply(outcome: .alreadyActive, message: stillStartingMessage, needsForeground: false)
        }
        let graceAge = [snapshot.sessionAge, snapshot.startIntentRepliedAge].compactMap { $0 }.min()
        if snapshot.gestureActive, snapshot.startIntentWaiting, !snapshot.healing,
           let age = graceAge, age < runningStopGrace {
            control.noteIntent("toggle", decision: "kept_calibrating")
            return GestureIntentReply(outcome: .alreadyActive, message: stillCalibratingMessage, needsForeground: false)
        }
        if snapshot.gestureActive, !snapshot.startPending,
           let age = graceAge, age < runningStopGrace {
            control.noteIntent("toggle", decision: "kept_new_session")
            return GestureIntentReply(outcome: .alreadyActive,
                                      message: snapshot.calibrated ? readyMessage : justStartedMessage,
                                      needsForeground: false)
        }
        if snapshot.gestureActive || snapshot.startPending {
            control.noteIntent("toggle", decision: "stop")
            return await requestStop(control)
        }
        control.noteIntent("toggle", decision: "start")
        return await requestStart(control, timeout: timeout, before: snapshot, began: began, now: now)
    }

    @MainActor
    static func start(_ control: any GestureModeControlling,
                      timeout: TimeInterval = readinessTimeout,
                      now: () -> Double = { ProcessInfo.processInfo.systemUptime }) async -> GestureIntentReply {
        let began = now()
        let snapshot = control.gestureModeSnapshot
        control.noteIntent("start", decision: "start")
        return await requestStart(control, timeout: timeout, before: snapshot, began: began, now: now)
    }

    @MainActor
    static func stop(_ control: any GestureModeControlling) async -> GestureIntentReply {
        control.noteIntent("stop", decision: "stop")
        return await requestStop(control)
    }

    /// A session that ended on its own since the last one is named first, so
    /// a Back Tap meant to stop a session the user thought was running is
    /// not silently read as a start.
    /// After a start (or a session already running), waits for the
    /// fingers-down calibration with what is left of `calibrationBudget`
    /// since `began`, so the dialog can say "Gestures ready ✓".
    @MainActor
    private static func requestStart(_ control: any GestureModeControlling, timeout: TimeInterval,
                                     before snapshot: GestureModeSnapshot, began: Double,
                                     now: () -> Double) async -> GestureIntentReply {
        let outcome = await control.requestGestureSession(true, source: .intent, readinessTimeout: timeout)
        // Read after the wait: the user may have opened R02 meanwhile.
        var reply = startReply(outcome, appActive: control.gestureModeSnapshot.appActive)
        if outcome == .started || outcome == .alreadyActive {
            let remaining = max(0, calibrationBudget - (now() - began))
            let wait = await control.awaitCalibration(timeout: remaining)
            if let calibrated = calibratedReply(outcome, wait) { reply = calibrated }
        }
        guard let ended = snapshot.recentAutomaticEnd else { return reply }
        return GestureIntentReply(outcome: reply.outcome, message: "\(ended.note) \(reply.message)",
                                  needsForeground: reply.needsForeground)
    }

    @MainActor
    private static func requestStop(_ control: any GestureModeControlling) async -> GestureIntentReply {
        let outcome = await control.requestGestureSession(false, source: .intent, readinessTimeout: 0)
        return GestureIntentReply(outcome: outcome, message: outcome.message, needsForeground: false)
    }

    /// Not connected, background sessions off, or a setup that outlasted the
    /// wait: each can still start once R02 is in front, so a background run asks
    /// to continue there. With R02 already active there is nothing to ask for.
    static func startReply(_ outcome: GestureRequestOutcome, appActive: Bool) -> GestureIntentReply {
        let continuation: String?
        switch outcome {
        case .notConnected:
            continuation = "The ring isn't connected. Continue in R02 to reconnect and start gestures."
        case .needsForeground:
            continuation = "Keep gestures active in background is off. Continue in R02 to start gestures."
        case .timedOut:
            continuation = "The ring isn't ready yet. Continue in R02 to start gestures once it is."
        default:
            continuation = nil
        }
        if let continuation, !appActive {
            return GestureIntentReply(outcome: outcome, message: continuation, needsForeground: true)
        }
        let message = outcome == .started
            ? "\(outcome.message) Hold your fingers down for 3 seconds to calibrate."
            : outcome.message
        return GestureIntentReply(outcome: outcome, message: message, needsForeground: false)
    }

    /// The reply once a start intent's calibration wait decided; nil when the
    /// control does not wait (the plain start reply stands).
    static func calibratedReply(_ outcome: GestureRequestOutcome, _ wait: GestureCalibrationWait) -> GestureIntentReply? {
        let message: String
        switch wait {
        case .calibrated: message = readyMessage
        case .pending: message = calibratingMessage
        case .reconnecting: message = reconnectingMessage
        case .ended: message = turnedOffMessage
        case .notStarted: message = notStartedMessage
        case .starting: message = stillStartingMessage
        case .unsupported: return nil
        }
        return GestureIntentReply(outcome: outcome, message: message, needsForeground: false)
    }

    /// The start behind a foreground continuation: waits for the scene to go
    /// active, then for any health sync or settings read that activation began
    /// before this ran (those end on their own), then requests with what is
    /// left of the longer foreground timeout. Nil when the caller was cancelled
    /// first (a newer continuation or a stop replaced it).
    @MainActor
    static func startAfterForeground(_ control: any GestureModeControlling,
                                     activationTimeout: TimeInterval = GestureIntentLogic.activationTimeout,
                                     readinessTimeout: TimeInterval = GestureIntentLogic.foregroundReadinessTimeout,
                                     now: () -> Double = { ProcessInfo.processInfo.systemUptime },
                                     sleep: (Duration) async throws -> Void = { try await Task.sleep(for: $0) })
        async -> GestureRequestOutcome? {
        _ = await waitUntil(timeout: activationTimeout, now: now, sleep: sleep) {
            control.gestureModeSnapshot.appActive
        }
        guard !Task.isCancelled else { return nil }
        let began = now()
        _ = await waitUntil(timeout: readinessTimeout, now: now, sleep: sleep) {
            !control.gestureModeSnapshot.ringBusy
        }
        guard !Task.isCancelled else { return nil }
        let remaining = max(0, readinessTimeout - (now() - began))
        return await control.requestGestureSession(true, source: .intent, readinessTimeout: remaining)
    }

    /// What the Gestures screen says when a continued start began no session.
    /// R02 is in front by then, so "open R02" advice would be wrong.
    static func continuationMessage(_ outcome: GestureRequestOutcome,
                                    timeout: TimeInterval = foregroundReadinessTimeout) -> String {
        let seconds = Int(timeout.rounded())
        switch outcome {
        case .notConnected:
            return "The ring didn't connect within \(seconds) seconds, so no session started. Tap Start once it's connected."
        case .timedOut:
            return "The ring wasn't ready within \(seconds) seconds, so no session started. Tap Start once it is."
        default:
            return "No session started: \(outcome.message)"
        }
    }

    /// Polls `condition` every `poll` until it holds or `timeout` passes on
    /// `now`, and returns whether it held. A cancelled caller stops at once.
    @MainActor
    static func waitUntil(timeout: TimeInterval, poll: Duration = .milliseconds(100),
                          now: () -> Double = { ProcessInfo.processInfo.systemUptime },
                          sleep: (Duration) async throws -> Void = { try await Task.sleep(for: $0) },
                          _ condition: () -> Bool) async -> Bool {
        let began = now()
        while !condition() {
            guard now() - began < timeout else { return false }
            do { try await sleep(poll) } catch { return condition() }
        }
        return true
    }
}
