import Foundation

enum GestureSuppression: String, CaseIterable {
    case diagnostics, sessionEnding, settling, cooldown

    var title: String {
        switch self {
        case .diagnostics: return "skipped during capture"
        case .sessionEnding: return "session ending"
        case .settling: return "settling after calibration"
        case .cooldown: return "too soon after the last gesture"
        }
    }
}

enum GestureActionOutcome: Equatable {
    case performed
    case failed(String)
    case locked(String)
    case unassigned
    case unrecognized
    case suppressed(GestureSuppression)

    var label: String {
        switch self {
        case .performed: return "done"
        case .failed(let reason): return reason
        case .locked: return "locked"
        case .unassigned: return "no action assigned"
        case .unrecognized: return "not recognized"
        case .suppressed(let reason): return reason.title
        }
    }
}

struct GestureDispatch: Identifiable, Equatable {
    let id = UUID()
    let generation: UUID
    let event: RingGestureEvent
    let gesture: GestureID?
    /// The mapped action; nil only when the event was not a known gesture.
    let action: GestureActionID?
    let outcome: GestureActionOutcome
    let wall: Double

    /// Any recognized gesture, including suppressed and unassigned ones, is
    /// wearer activity: the owner resets the idle pause from this.
    var isActivity: Bool { gesture != nil }

    var summary: String {
        guard let gesture, let action else {
            let direction = event.direction == "none" ? "" : " \(event.direction)"
            return "\(event.name.replacingOccurrences(of: "_", with: " "))\(direction) · \(outcome.label)"
        }
        if outcome == .unassigned { return "\(gesture.title) · \(outcome.label)" }
        return "\(gesture.title) → \(action.title) · \(outcome.label)"
    }
}

enum HapticCue: Equatable {
    case performed, paused, refused
}

@MainActor
protocol HapticsPlaying: AnyObject {
    func play(_ cue: HapticCue)
}

@MainActor
protocol GestureActionPerforming: AnyObject {
    /// Returns `.performed` or `.failed`. Must never prompt for a permission:
    /// it can run while R02 is in the background.
    func perform(_ action: GestureActionID) -> GestureActionOutcome
}

/// Turns engine events into at most one action each, synchronously. Rules per
/// event, in order: drop a stale generation unlogged; log an unknown gesture
/// as `.unrecognized`; suppress for diagnostics, a session that is ending,
/// the settle window after calibration, then the cooldown on the stream-clock
/// onset; `.none` is `.unassigned`; a locked action is logged by name and
/// refused without calling the performer; `pause_gestures` marks the session
/// ending before it runs so it fires once (a failed pause, or
/// `cancelEnding`, clears the mark). Every routed event is logged: the
/// action name when one was resolved, JSON null when unrecognized, suppressed
/// or unassigned. Haptics play only in the foreground with haptics enabled.
@MainActor
final class GestureActionRouter: ObservableObject {
    struct Timing: Equatable {
        var cooldown: Double = 0.75
        var settle: Double = 1.0
        static let standard = Timing()
    }

    struct Context: Equatable {
        var foreground: Bool
        var hapticsEnabled: Bool
        var diagnosticsRunning = false
        var sessionEnding = false
    }

    static let recentLimit = 20

    @Published private(set) var lastDispatch: GestureDispatch?
    @Published private(set) var recentDispatches: [GestureDispatch] = []

    var mappings: GestureMappings
    let timing: Timing
    private(set) var generation: UUID?
    private(set) var isEnding = false
    private(set) var calibratedAt: Double?
    private var lastActedOnset: Double?
    private var log: GestureEventLogging?
    private let performer: GestureActionPerforming
    private let haptics: HapticsPlaying?
    private let wall: () -> Double

    init(mappings: GestureMappings = GestureMappings(), performer: GestureActionPerforming,
         haptics: HapticsPlaying?, timing: Timing = .standard,
         wall: @escaping () -> Double = { Date().timeIntervalSince1970 }) {
        self.mappings = mappings; self.performer = performer; self.haptics = haptics
        self.timing = timing; self.wall = wall
    }

    /// Starts routing for one Gesture session. The router owns `log` until `end()`.
    func begin(generation: UUID, log: GestureEventLogging?) {
        self.log?.close()
        self.generation = generation
        self.log = log
        isEnding = false; calibratedAt = nil; lastActedOnset = nil
    }

    /// First call per session wins. `time` is on the stream clock (BLE receipt uptime).
    func calibrated(at time: Double) {
        guard generation != nil, calibratedAt == nil, time.isFinite else { return }
        calibratedAt = time
    }

    /// The owner's asynchronous return to Health after `pause_gestures` failed
    /// and the session continues: routing resumes, so a later pause can retry.
    func cancelEnding(generation: UUID) {
        guard self.generation == generation else { return }
        isEnding = false
    }

    /// A sticky session's recognition paused for a heal: late events of the
    /// old segment are dropped unlogged; the log stays open.
    func suspend() {
        generation = nil
        isEnding = false; calibratedAt = nil; lastActedOnset = nil
    }

    /// The healed segment's generation. The settle after calibration and the
    /// cooldown start again, so nothing dispatches on the heal's first samples.
    func resume(generation: UUID) {
        self.generation = generation
        isEnding = false; calibratedAt = nil; lastActedOnset = nil
    }

    /// Invalidates the session and closes its log; late events are dropped unlogged.
    func end() {
        log?.close()
        log = nil
        generation = nil
        isEnding = false; calibratedAt = nil; lastActedOnset = nil
    }

    @discardableResult
    func route(_ events: [RingGestureEvent], generation: UUID, context: Context) -> [GestureDispatch] {
        var dispatches: [GestureDispatch] = []
        for event in events {
            // Re-checked per event: a performer may end the session synchronously.
            guard let current = self.generation, current == generation else { break }
            dispatches.append(dispatch(event, generation: current, context: context))
        }
        guard let last = dispatches.last else { return [] }
        recentDispatches.append(contentsOf: dispatches)
        if recentDispatches.count > Self.recentLimit {
            recentDispatches.removeFirst(recentDispatches.count - Self.recentLimit)
        }
        lastDispatch = last
        return dispatches
    }

    private func dispatch(_ event: RingGestureEvent, generation: UUID, context: Context) -> GestureDispatch {
        let wall = self.wall()
        func result(_ gesture: GestureID?, _ action: GestureActionID?, _ outcome: GestureActionOutcome) -> GestureDispatch {
            GestureDispatch(generation: generation, event: event, gesture: gesture, action: action,
                            outcome: outcome, wall: wall)
        }
        guard let gesture = GestureID(event: event) else {
            log?.record(event, action: nil, wall: wall)
            return result(nil, nil, .unrecognized)
        }
        let action = mappings[gesture]
        if let suppression = suppression(for: event, context: context) {
            log?.record(event, action: nil, wall: wall)
            return result(gesture, action, .suppressed(suppression))
        }
        lastActedOnset = event.time
        guard action != GestureActionID.none else {
            log?.record(event, action: nil, wall: wall)
            return result(gesture, action, .unassigned)
        }
        log?.record(event, action: action, wall: wall)
        if let reason = action.info.lockedReason {
            play(.refused, context: context)
            return result(gesture, action, .locked(reason))
        }
        if action == .pause_gestures { isEnding = true }
        let outcome = performer.perform(action)
        // A pause that did not happen must not leave the session deaf.
        if action == .pause_gestures, outcome != .performed, self.generation == generation { isEnding = false }
        switch outcome {
        case .performed: play(action == .pause_gestures ? .paused : .performed, context: context)
        case .failed: play(.refused, context: context)
        default: break
        }
        return result(gesture, action, outcome)
    }

    private func suppression(for event: RingGestureEvent, context: Context) -> GestureSuppression? {
        if context.diagnosticsRunning { return .diagnostics }
        if isEnding || context.sessionEnding { return .sessionEnding }
        // Lifting the hand out of the fingers-down pose reads as a flick.
        guard let calibratedAt, event.time >= calibratedAt + timing.settle else { return .settling }
        if let lastActedOnset, abs(event.time - lastActedOnset) < timing.cooldown { return .cooldown }
        return nil
    }

    private func play(_ cue: HapticCue, context: Context) {
        guard context.foreground, context.hapticsEnabled else { return }
        haptics?.play(cue)
    }
}
