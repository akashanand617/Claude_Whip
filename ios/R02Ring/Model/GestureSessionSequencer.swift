import Foundation

/// Orders every Gesture start and stop for `AppModel`, so an owner that asked
/// for Health never leaves the ring streaming:
/// - a stop request during a start's readiness wait withdraws that start, which
///   then never sends A1 04;
/// - a stop during entry is held and performed as soon as the entry settles;
/// - a stop during a stop joins it;
/// - a stop blocked by a heartbeat renewal retries briefly, and ends quietly if
///   mode control is lost meanwhile (recovery then sends the stop packets);
/// - a sticky session's heal (`restart`) is withdrawn by any stop: a stop
///   during its stop half cancels its entry, and a stop during its entry is
///   held and performed right after it.
/// The coordinator, clock and sleep are injected, so tests drive it without Bluetooth.
@MainActor
final class GestureSessionSequencer {
    struct Dependencies {
        /// `UnifiedModeCoordinator.setGesture`, which sends only the audited packets.
        var setGesture: (Bool) async throws -> Void
        /// The coordinator reports Gesture, or Gesture being entered.
        var isGestureMode: () -> Bool
        var modeControlAvailable: () -> Bool
        var linkReady: () -> Bool
        /// Runs synchronously just before an entry sends its first packet, while
        /// nothing streams yet.
        var willEnter: () -> Void = {}
        var now: () -> Double = { ProcessInfo.processInfo.systemUptime }
        var sleep: (Duration) async throws -> Void = { try await Task.sleep(for: $0) }
    }

    struct StartResult: Equatable {
        let outcome: GestureRequestOutcome
        let readiness: GestureStartReadiness
        let waited: Double
    }

    /// How long a stop keeps retrying while a heartbeat renewal holds the mode gate.
    static let stopRetryWindow: TimeInterval = 2.5

    private(set) var transition: GestureTransition? {
        didSet { if oldValue != transition { onTransitionChange?(transition) } }
    }
    /// A stop that arrived while a start was entering; performed once entry settles.
    private(set) var stopAfterEntry: GestureSessionReason?
    /// Why the entry or stop in flight was requested (read by the session record).
    private(set) var enteringReason: GestureSessionReason?
    private(set) var leavingReason: GestureSessionReason?
    /// Start requests waiting for readiness or entering.
    private(set) var pendingStarts = 0 {
        didSet { if oldValue != pendingStarts { onPendingStartsChange?(pendingStarts) } }
    }

    var onTransitionChange: ((GestureTransition?) -> Void)?
    var onPendingStartsChange: ((Int) -> Void)?
    /// Error text for the status line.
    var onStatus: ((String) -> Void)?
    /// Lifecycle journal records: "start" and "stop".
    var onJournal: ((String, [String: Any]) -> Void)?

    /// A pause or other internal stop is under way; the router suppresses events meanwhile.
    var sessionEnding: Bool { transition == .leaving || stopAfterEntry != nil }

    /// Advanced by every stop: a heal restart captured before it is withdrawn.
    private(set) var healEpoch = 0
    /// A heal restart (its stop half or its entry) is running.
    private(set) var restarting = false

    private let deps: Dependencies
    private var startEpoch = 0
    private var stopWaiters: [CheckedContinuation<GestureRequestOutcome, Never>] = []

    init(_ dependencies: Dependencies) { deps = dependencies }

    // MARK: Requests (the app's Start/Return button and App Intents)

    /// Waits up to `readinessTimeout` for `readiness` to become final, then
    /// enters, unless a stop request withdrew this start meanwhile.
    func requestStart(reason: GestureSessionReason, readinessTimeout: TimeInterval,
                      readiness: () -> GestureStartReadiness) async -> StartResult {
        let epoch = startEpoch
        pendingStarts += 1
        defer { pendingStarts -= 1 }
        let (state, waited) = await GestureStartReadiness.wait(
            timeout: readinessTimeout, now: deps.now, sleep: deps.sleep,
            evaluate: { self.startEpoch == epoch ? readiness() : .cancelled }
        )
        let outcome: GestureRequestOutcome
        if startEpoch != epoch { outcome = .startCancelled }
        else if let refusal = state.outcome { outcome = refusal }
        else { outcome = await enter(reason: reason, epoch: epoch) }
        return StartResult(outcome: outcome, readiness: startEpoch != epoch ? .cancelled : state, waited: waited)
    }

    /// Withdraws every start still waiting for readiness (`alsoWithdrawing`
    /// reports starts the owner holds elsewhere, such as a Shortcut's
    /// continuation), then stops any session. A withdrawn start with nothing
    /// else to stop answers `.startCancelled`, not "already in Health".
    func requestStop(reason: GestureSessionReason, alsoWithdrawing: Bool = false) async -> GestureRequestOutcome {
        let withdrew = pendingStarts > 0 || alsoWithdrawing
        if withdrew { startEpoch &+= 1 }
        let outcome = await leave(reason: reason)
        return withdrew && outcome == .alreadyStopped ? .startCancelled : outcome
    }

    // MARK: Internal owners (timers, idle, stale stream, pause gesture, backgrounding)

    /// Never withdraws a pending start: only a user or intent stop does that.
    @discardableResult
    func setSession(_ enabled: Bool, reason: GestureSessionReason) async -> GestureRequestOutcome {
        enabled ? await enter(reason: reason, epoch: nil) : await leave(reason: reason)
    }

    /// The pause gesture's return to Health. Called inside the router's
    /// dispatch, so it only schedules the stop; `onFailure` runs when the
    /// return did not happen, so routing can resume and a later pause retry.
    func requestPause(onFailure: @escaping () -> Void) {
        Task { [weak self] in
            guard let self else { return }
            let outcome = await self.setSession(false, reason: .gestureAction)
            if !outcome.succeeded { onFailure() }
        }
    }

    // MARK: The sticky session's heal

    /// Re-enters Gesture for a session the user still wants, through the same
    /// audited packets as any start and stop: if the ring still reports
    /// Gesture (a stale or stalled stream), the stop first, then the entry.
    /// `epoch` is `healEpoch` read by the caller with no suspension since it
    /// checked that the session is still wanted; any stop since withdraws the
    /// restart. A heal reports no failure through `onStatus`. The work runs
    /// unstructured, so a cancelled caller never abandons half a packet
    /// sequence.
    func restart(epoch: Int) async -> GestureRequestOutcome {
        guard transition == nil else { return .busy }
        guard epoch == healEpoch else { return .startCancelled }
        restarting = true
        defer { restarting = false }
        return await Task { @MainActor in await self.performRestart(epoch: epoch) }.value
    }

    private func performRestart(epoch: Int) async -> GestureRequestOutcome {
        if deps.isGestureMode() {
            guard transition == nil else { return .busy }
            guard epoch == healEpoch else { return .startCancelled }
            transition = .leaving
            leavingReason = .heal
            let stopped = await stopWithRetry(reportsStatus: false)
            transition = nil
            leavingReason = nil
            onJournal?("stop", ["reason": GestureSessionReason.heal.rawValue, "outcome": stopped.journalName])
            // A user stop that joined this stop half is answered by it.
            resumeStopWaiters(stopped)
            guard stopped == .stopped || stopped == .alreadyStopped else { return stopped }
        }
        // A stop during the stop half withdrew the entry.
        guard epoch == healEpoch else { return .startCancelled }
        return await enter(reason: .heal, epoch: nil, healEpoch: epoch)
    }

    /// Withdraws a heal restart already under way (or queued as its own
    /// main-actor job) without stopping anything: the owner's session ended
    /// and its return to Health follows separately. Its entry then never
    /// sends A1 04.
    func withdrawHeal() { healEpoch &+= 1 }

    // MARK: Transitions

    private func enter(reason: GestureSessionReason, epoch: Int?, healEpoch heal: Int? = nil) async
        -> GestureRequestOutcome {
        switch transition {
        case .entering: return .alreadyActive
        case .leaving: return .busy
        case nil: break
        }
        if deps.isGestureMode() { return .alreadyActive }
        guard deps.modeControlAvailable() else { return deps.linkReady() ? .unavailable : .notConnected }
        // Nothing since the caller's own check suspends, so a stop cannot slip
        // between this test and `.entering`; a later stop is held for the entry.
        if let epoch, epoch != startEpoch { return .startCancelled }
        if let heal, heal != healEpoch { return .startCancelled }
        transition = .entering
        enteringReason = reason
        deps.willEnter()
        var outcome = GestureRequestOutcome.started
        do { try await deps.setGesture(true) }
        catch {
            outcome = GestureRequestOutcome(error: error)
            // A heal's failed attempt is not the user's failure.
            if heal == nil { onStatus?(error.localizedDescription) }
        }
        transition = nil
        enteringReason = nil
        onJournal?("start", ["reason": reason.rawValue, "outcome": outcome.journalName])
        if let stopReason = stopAfterEntry {
            stopAfterEntry = nil
            if deps.isGestureMode() { _ = await leave(reason: stopReason) } // resumes the waiters
            else { resumeStopWaiters(.alreadyStopped) }
        }
        return outcome
    }

    private func leave(reason: GestureSessionReason) async -> GestureRequestOutcome {
        // Every stop withdraws a heal in flight.
        healEpoch &+= 1
        switch transition {
        case .entering:
            if stopAfterEntry == nil { stopAfterEntry = reason }
            return await withCheckedContinuation { stopWaiters.append($0) }
        case .leaving:
            return await withCheckedContinuation { stopWaiters.append($0) }
        case nil: break
        }
        // With mode control lost there is no confirmed Gesture session to stop;
        // mode recovery re-attaches and sends the stop packets.
        guard deps.isGestureMode() else { return .alreadyStopped }
        transition = .leaving
        leavingReason = reason
        // Unstructured on purpose: a cancelled caller must not abandon the stop.
        let outcome = await Task { @MainActor in await self.stopWithRetry(reportsStatus: true) }.value
        transition = nil
        leavingReason = nil
        onJournal?("stop", ["reason": reason.rawValue, "outcome": outcome.journalName])
        resumeStopWaiters(outcome)
        return outcome
    }

    /// A heartbeat renewal holds the mode gate for up to about a second; wait
    /// it out rather than failing a pause.
    private func stopWithRetry(reportsStatus: Bool) async -> GestureRequestOutcome {
        let deadline = deps.now() + Self.stopRetryWindow
        while true {
            // Control lost while waiting (a renewal failed and the coordinator
            // dropped the session): recovery, or the failed renewal's own stop,
            // now owns the audited stop packets. Nothing failed for this caller.
            guard deps.isGestureMode() else { return .alreadyStopped }
            do {
                try await deps.setGesture(false)
                return .stopped
            } catch {
                let outcome = GestureRequestOutcome(error: error)
                if outcome == .busy, !deps.isGestureMode() { return .alreadyStopped }
                guard outcome == .busy, deps.modeControlAvailable(), deps.now() < deadline else {
                    // This stop's own attempt failed (for example the link dropped mid-write).
                    if reportsStatus { onStatus?(error.localizedDescription) }
                    return outcome
                }
                try? await deps.sleep(.milliseconds(100))
            }
        }
    }

    private func resumeStopWaiters(_ outcome: GestureRequestOutcome) {
        let waiters = stopWaiters
        stopWaiters.removeAll()
        waiters.forEach { $0.resume(returning: outcome) }
    }
}
