import Foundation

/// Seconds on `ContinuousClock`, which keeps running while the phone sleeps
/// (`ProcessInfo.systemUptime` does not). The sticky session's heal windows,
/// give-up deadlines and user timers are measured on it, so a wake after a
/// long suspension sees the real elapsed time.
enum GestureContinuousTime {
    private static let origin = ContinuousClock.now

    static func now() -> Double {
        let elapsed = origin.duration(to: .now).components
        return Double(elapsed.seconds) + Double(elapsed.attoseconds) / 1e18
    }
}

/// The only reasons a user's Gesture session may end. Everything else (a
/// stale or stalled stream, a failed renewal, a lapsed lease, a brief
/// reconnect, lost mode control) heals instead. `GestureDesire.end` takes
/// this type, so no other cause can clear the desired state.
enum GestureEndReason: String, CaseIterable {
    /// R02's Return button, Cancel start, or a stop while reconnecting.
    case user
    /// Toggle (off) or Pause Gestures.
    case intent
    /// A gesture mapped to Pause gestures (snap by default).
    case gestureAction = "gesture_action"
    /// The user's Session timer.
    case autoReturn = "auto_return"
    /// The user's Pause-when-idle setting.
    case idle
    /// Keep gestures active in background is off and R02 left the screen.
    case backgrounded
    /// The firmware refused Gesture on its charger.
    case charging
    /// Disconnected for longer than the heal window.
    case ringGone = "ring_gone"
    /// Heal attempts kept failing for longer than the heal window.
    case healGaveUp = "heal_gave_up"
    /// Settings › Forget ring.
    case ringForgotten = "ring_forgotten"

    /// The sequencer's and summary's name for this end.
    var sessionReason: GestureSessionReason {
        switch self {
        case .user: return .user
        case .intent: return .intent
        case .gestureAction: return .gestureAction
        case .autoReturn: return .autoReturn
        case .idle: return .idle
        case .backgrounded: return .backgrounded
        case .charging: return .charging
        case .ringGone: return .ringGone
        case .healGaveUp: return .healGaveUp
        case .ringForgotten: return .ringForgotten
        }
    }

    /// Not a request: named in the next intent's start reply, and in a
    /// notification when R02 is not in front.
    var isAutomatic: Bool {
        switch self {
        case .autoReturn, .idle, .charging, .ringGone, .healGaveUp: return true
        case .user, .intent, .gestureAction, .backgrounded, .ringForgotten: return false
        }
    }

    /// A give-up: exactly one notification names it, even with R02 in front.
    var alwaysNotifies: Bool {
        switch self {
        case .charging, .ringGone, .healGaveUp: return true
        default: return false
        }
    }
}

/// Whether the user wants a Gesture session, owned by `AppModel`, per app
/// process. A start arms it; the ring reaching Gesture for that start turns
/// it on; only a `GestureEndReason` turns a session off. A start that never
/// reached Gesture returns to off without ending anything.
struct GestureDesire: Equatable {
    enum State: Equatable {
        case off
        case arming(epoch: Int)
        case on(epoch: Int)
    }

    private(set) var state: State = .off
    /// Advanced by every new arm; stale work (a defensive stop, a timer) is
    /// recognized by a different epoch.
    private(set) var epoch = 0
    /// Starts of the arming epoch still in flight.
    private(set) var pendingStarts = 0
    /// `GestureContinuousTime` when the session turned on.
    private(set) var onSince: Double?
    /// The last end, for the journal and tests.
    private(set) var lastEnd: GestureEndReason?

    var isOn: Bool { if case .on = state { return true } else { return false } }
    var isArming: Bool { if case .arming = state { return true } else { return false } }
    var isOff: Bool { state == .off }

    /// A user or intent start. Off: a new epoch starts arming. Arming: joins
    /// it. On: the running session's epoch (the start answers alreadyActive).
    mutating func arm() -> Int {
        switch state {
        case .off:
            epoch &+= 1
            state = .arming(epoch: epoch)
            pendingStarts = 1
        case .arming:
            pendingStarts += 1
        case .on:
            break
        }
        return epoch
    }

    /// The ring reached Gesture for a user or intent start of `epoch`. True
    /// when this began a session.
    @discardableResult
    mutating func reached(epoch arming: Int, at now: Double) -> Bool {
        guard case .arming(let current) = state, current == arming else { return false }
        state = .on(epoch: arming)
        onSince = now
        pendingStarts = 0
        return true
    }

    /// One start of `epoch` returned, whatever its outcome. When the last
    /// start of an arming epoch returns without reaching Gesture, nothing
    /// started: back to off, with no end reason and no notification.
    mutating func startFinished(epoch arming: Int) {
        guard case .arming(let current) = state, current == arming else { return }
        pendingStarts = max(0, pendingStarts - 1)
        if pendingStarts == 0 { state = .off }
    }

    /// Ends the session, or withdraws a start still arming. True only when a
    /// session was on: the caller then journals, summarizes and notifies,
    /// exactly once however many ends race.
    @discardableResult
    mutating func end(_ reason: GestureEndReason) -> Bool {
        switch state {
        case .off:
            return false
        case .arming:
            state = .off
            pendingStarts = 0
            return false
        case .on:
            state = .off
            onSince = nil
            pendingStarts = 0
            lastEnd = reason
            return true
        }
    }
}

/// Why a heal re-enters Gesture. Journal names are the raw values.
enum GestureHealCause: String, CaseIterable {
    case staleStream = "stale_stream"
    case sourceStopped = "source_stopped"
    case badSource = "bad_source"
    case leaseLapsed = "lease_lapsed"
    case controlLost = "control_lost"
    case disconnected
    case unexpectedHealth = "unexpected_health"
    case modelUnavailable = "model_unavailable"

    /// Named in a give-up notification.
    var title: String {
        switch self {
        case .staleStream: return "the motion stream went stale"
        case .sourceStopped: return "the motion stream stopped"
        case .badSource: return "the motion stream was frozen or slow"
        case .leaseLapsed: return "the Gesture lease lapsed"
        case .controlLost: return "gesture control was lost"
        case .disconnected: return "the ring disconnected"
        case .unexpectedHealth: return "the ring returned to Health"
        case .modelUnavailable: return "the gesture model was unavailable"
        }
    }
}

/// Every event that could end a Gesture session or take the ring out of
/// Gesture. `GestureSessionPolicy.disposition` maps each one; the table is
/// the sticky-session contract and is tested exhaustively.
enum GestureSessionTrigger: String, CaseIterable {
    // The user and their settings.
    case appReturn, intentStop, pauseGesture, ringForgotten, sessionTimer, idleTimer
    case backgroundedWithSettingOff
    // The ring, after the heal window.
    case chargingRefusal, ringGoneTimeout, healExhausted
    // Everything below heals, retries or is ignored.
    case streamFault, sourceStopped, renewalTiming, renewalWriteFailed, renewalPreWriteRefusal
    case renewalBadSource, leaseLapsed, replyMismatch, controlLost, linkLost
    case unexpectedHealth, modelUnavailable, diagnosticsFinished, reconnectAttach
}

enum GestureSessionDisposition: Equatable {
    /// The user's session ends (the only way it does).
    case end(GestureEndReason)
    /// Recognition pauses; the keeper re-enters Gesture through the audited path.
    case heal(GestureHealCause)
    /// The lease was not renewed this time; processing continues and the
    /// heartbeat retries while the lease is still valid.
    case missedRenewal
    /// Journal only.
    case none
}

enum GestureSessionPolicy {
    /// No default branch: a new trigger must be placed here explicitly.
    static func disposition(_ trigger: GestureSessionTrigger) -> GestureSessionDisposition {
        switch trigger {
        case .appReturn: return .end(.user)
        case .intentStop: return .end(.intent)
        case .pauseGesture: return .end(.gestureAction)
        case .ringForgotten: return .end(.ringForgotten)
        case .sessionTimer: return .end(.autoReturn)
        case .idleTimer: return .end(.idle)
        case .backgroundedWithSettingOff: return .end(.backgrounded)
        case .chargingRefusal: return .end(.charging)
        case .ringGoneTimeout: return .end(.ringGone)
        case .healExhausted: return .end(.healGaveUp)
        case .streamFault: return .heal(.staleStream)
        case .sourceStopped: return .heal(.sourceStopped)
        case .renewalBadSource: return .heal(.badSource)
        case .leaseLapsed: return .heal(.leaseLapsed)
        case .replyMismatch: return .heal(.controlLost)
        case .controlLost: return .heal(.controlLost)
        case .linkLost: return .heal(.disconnected)
        case .unexpectedHealth: return .heal(.unexpectedHealth)
        case .modelUnavailable: return .heal(.modelUnavailable)
        case .renewalTiming: return .missedRenewal
        case .renewalWriteFailed: return .missedRenewal
        case .renewalPreWriteRefusal: return .missedRenewal
        case .diagnosticsFinished: return .none
        case .reconnectAttach: return .none
        }
    }
}

/// What a failed heartbeat means for the sticky session. Pure. No verdict
/// ever ends a session: a renewal is either missed (processing continues and
/// the heartbeat retries while the firmware lease is still valid) or its
/// trigger heals through `GestureSessionPolicy`.
enum RenewalVerdict: Equatable {
    case missed(GestureSessionTrigger, retryIn: Double)
    case act(GestureSessionTrigger)

    /// The next heartbeat after a post-write timing miss: the failed
    /// attempt's A1 04 already restarted the firmware lease.
    static let normalRetry: Double = 5
    /// After a refusal that wrote nothing.
    static let quickRetry: Double = 1

    /// `leaseAge`: seconds since the last lease write, when known;
    /// `leaseDeadline`: the transport's renewal deadline (9 s on V6/V7).
    /// A post-write timing miss (max gap, high rate, nonmonotonic, a timeout
    /// with ten or more samples) never heals however often it repeats: only
    /// the lease's age can turn a miss into a heal. The stop path is reserved
    /// for a bad or stopped source and a lapsed lease.
    static func classify(_ error: Error, failure: HeartbeatFailure, linkReady: Bool,
                         leaseAge: Double?, leaseDeadline: Double) -> RenewalVerdict {
        if !linkReady { return .act(.linkLost) }
        /// A miss retried after `retry` s, unless the lease would lapse first.
        func missed(_ trigger: GestureSessionTrigger, retry: Double) -> RenewalVerdict {
            if let leaseAge, leaseAge.isFinite, leaseAge + retry >= leaseDeadline { return .act(.leaseLapsed) }
            return .missed(trigger, retryIn: retry)
        }
        // A refusal that wrote nothing: retry soon.
        func quick(_ trigger: GestureSessionTrigger) -> RenewalVerdict { missed(trigger, retry: quickRetry) }
        // A post-write timing miss: its A1 04 restarted the lease.
        func timingMiss() -> RenewalVerdict { missed(.renewalTiming, retry: normalRetry) }
        if let protocolError = error as? RingProtocolError {
            switch protocolError {
            case .busy: return quick(.renewalPreWriteRefusal)
            case .notReady: return .act(.linkLost)
            default: return .act(.controlLost)
            }
        }
        if error is CancellationError { return quick(.renewalPreWriteRefusal) }
        guard let modeError = error as? UnifiedModeError else { return .act(.controlLost) }
        switch modeError {
        case .uncorrelated, .exhausted, .unavailable:
            return .act(.replyMismatch)
        case .renewalBoundary:
            guard let report = failure.report, failure.reachedRenew else { return .act(.controlLost) }
            switch report.cause {
            case .criteria?:
                if report.failedChecks.contains("duplicates") || report.failedChecks.contains("rate_low") {
                    return .act(.renewalBadSource)
                }
                return timingMiss()
            case .timeout(let samples)?:
                if samples == 0 { return .act(.sourceStopped) }
                // Any post-write spacing over 0.5 s fails at once, so a timeout
                // with fewer than ten samples means a half-rate or stopped source.
                if samples < 10 { return .act(.renewalBadSource) }
                return timingMiss()
            case .nonmonotonic?:
                return timingMiss()
            case .writeError?:
                return quick(.renewalWriteFailed)
            case .disconnected?:
                return .act(.linkLost)
            case nil:
                return .act(.controlLost)
            }
        case .staleStream:
            if let rejection = failure.heartbeatRejection {
                if rejection == "reply_mismatch" { return .act(.replyMismatch) }
                if rejection == "not_processed" || rejection.hasPrefix("processed_age=") { return .act(.sourceStopped) }
                if rejection == "not_gesture" || rejection == "session_mismatch" { return .act(.controlLost) }
                return quick(.renewalPreWriteRefusal) // same_sequence
            }
            if failure.reachedRenew, let rejection = failure.transportRejection {
                if rejection.hasPrefix("lease_age=") { return .act(.leaseLapsed) }
                if rejection == "not_gesture" || rejection == "session_mismatch" { return .act(.controlLost) }
                return quick(.renewalPreWriteRefusal) // history, processed_seq, motion_age
            }
            return quick(.renewalPreWriteRefusal)
        }
    }
}

/// The body of the one "Gestures turned off" notification a give-up posts.
/// Names the time: a notification can be delivered late.
enum GestureGiveUpNotice {
    /// A keeper detail for firmware without a Health-return lease: no heal is
    /// ever attempted there, so the notice must not say it retried.
    static let noLeaseDetail = "no_lease"

    static func body(_ reason: GestureEndReason, cause: GestureHealCause?, detail: String? = nil,
                     time: String) -> String {
        switch reason {
        case .charging:
            return "At \(time) the ring was on its charger. It is back in Health."
        case .ringGone:
            return "At \(time) the ring had been out of range for over a minute. It returns to Health on its own."
        default:
            if let detail, detail == noLeaseDetail || detail.hasSuffix(":\(noLeaseDetail)") {
                let why = cause.map { " after \($0.title)" } ?? ""
                return "At \(time) gestures stopped\(why): this ring's firmware can't reconnect gestures automatically. The ring is back in Health."
            }
            let why = cause.map { " (\($0.title))" } ?? ""
            return "At \(time) gestures couldn't reconnect for a minute\(why). The ring may be on its charger. It is back in Health."
        }
    }
}
