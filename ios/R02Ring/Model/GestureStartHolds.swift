import Foundation

/// What a start holds outside `GestureSessionSequencer`, and what it leaves
/// behind, for `AppModel`:
/// - the foreground hold an intent sets just before it asks to continue in R02;
/// - that continuation, once R02 is in front;
/// - the automatic health refresh deferred while any start holds the ring;
/// - why the last continuation, or the panel's last Start/Return tap, did not
///   succeed.
/// A session that actually reaches Gesture, from any source, clears both
/// messages; a stop always gives a deferred refresh its chance once it
/// settles. `AppModel` publishes the state; tests drive it without Bluetooth.
@MainActor
final class GestureStartHolds {
    struct Dependencies {
        /// Start requests the sequencer holds (waiting for readiness or entering).
        var pendingStarts: () -> Int
        /// The ring is ready and in Health, so a settings read and sync may run.
        var healthRefreshAllowed: () -> Bool
        /// The deferred settings read and sync, with the `full` flag captured on connection.
        var refreshHealth: (_ full: Bool) -> Void
        /// A sticky Gesture session is desired (running or healing): automatic
        /// health work would take the ring from its heal.
        var sessionHoldsRing: () -> Bool = { false }
        var holdTimeout: TimeInterval = GestureIntentLogic.foregroundHoldTimeout
        var sleep: (Duration) async throws -> Void = { try await Task.sleep(for: $0) }
    }

    /// Why the last Shortcut start that continued in R02 started no session.
    private(set) var continuationMessage: String? {
        didSet { if oldValue != continuationMessage { onChange?() } }
    }
    /// Why the panel's last Start/Return tap did not succeed.
    private(set) var panelMessage: String? {
        didSet { if oldValue != panelMessage { onChange?() } }
    }
    /// The `full` flag of the automatic health refresh deferred for a start.
    private(set) var deferredHealthRefresh: Bool?
    /// A Shortcut's start is continuing in R02.
    var continuationPending: Bool { continuation != nil }
    var foregroundHoldActive: Bool { foregroundHold != nil }
    /// A start request, a Shortcut's continuation, a Shortcut about to ask to
    /// continue in R02, or a desired Gesture session (running or healing):
    /// automatic health syncs wait for any of them.
    var holdsRing: Bool {
        deps.pendingStarts() > 0 || continuation != nil || foregroundHold != nil || deps.sessionHoldsRing()
    }

    /// A message or `continuationPending` changed.
    var onChange: (() -> Void)?

    private let deps: Dependencies
    private var foregroundHold: Task<Void, Never>?
    private var continuation: Task<Void, Never>?
    private var continuationToken: UUID?

    init(_ dependencies: Dependencies) { deps = dependencies }

    // MARK: Intent continuation

    /// Called by a Start or Toggle intent just before it asks to continue in
    /// R02 (still in the background). Scene activation may run before the
    /// continuation does; this keeps its automatic sync off the ring meanwhile.
    /// If the user declines, the hold expires and the deferred refresh runs.
    func expectForegroundStart() {
        foregroundHold?.cancel()
        let sleep = deps.sleep, timeout = deps.holdTimeout
        foregroundHold = Task { [weak self] in
            try? await sleep(.seconds(timeout))
            guard !Task.isCancelled, let self else { return }
            self.foregroundHold = nil
            self.runDeferredHealthRefreshIfNeeded()
        }
    }

    /// Runs `start` as the foreground continuation. Returns at once; the start
    /// shows as pending and publishes why if no session started. Nil from
    /// `start` means it was cancelled first.
    func continueInForeground(_ start: @escaping @MainActor () async -> GestureRequestOutcome?) {
        continuation?.cancel()
        continuationMessage = nil
        let token = UUID()
        continuationToken = token
        continuation = Task { [weak self] in
            guard let self else { return }
            let outcome = await start()
            // A newer continuation, or a stop that withdrew this one, owns the state now.
            guard self.continuationToken == token else { return }
            self.continuationToken = nil
            self.continuation = nil
            self.onChange?()
            if let outcome, !outcome.succeeded {
                self.continuationMessage = GestureIntentLogic.continuationMessage(outcome)
            }
            self.runDeferredHealthRefreshIfNeeded()
        }
        // The continuation holds automatic syncs from here on.
        foregroundHold?.cancel()
        foregroundHold = nil
        onChange?()
    }

    // MARK: Requests

    /// A user or intent stop: drops the foreground hold, withdraws the
    /// continuation, runs `perform` (told whether a continuation was
    /// withdrawn), and only then runs a refresh deferred for the withdrawn
    /// start. When the ring never left Health no mode change follows, so
    /// nothing else would run it.
    func stop(_ perform: @MainActor (_ withdrewContinuation: Bool) async -> GestureRequestOutcome)
        async -> GestureRequestOutcome {
        foregroundHold?.cancel()
        foregroundHold = nil
        let withdrew = continuation != nil
        if withdrew {
            continuation?.cancel()
            continuation = nil
            continuationToken = nil
            onChange?()
        }
        let outcome = await perform(withdrew)
        runDeferredHealthRefreshIfNeeded()
        return outcome
    }

    /// After a start request settles. A session that started, or was already
    /// running, makes an earlier failure moot even when no mode change follows.
    func startFinished(_ outcome: GestureRequestOutcome) {
        if outcome == .started || outcome == .alreadyActive { clearMessages() }
        runDeferredHealthRefreshIfNeeded()
    }

    /// The coordinator published a new mode. Only `.gesture` clears the
    /// messages: a failed entry passes through `.enteringGesture` and returns
    /// to Health, and its failure must stay visible.
    func modeChanged(to mode: RingRuntimeMode?) {
        if mode == .gesture { clearMessages() }
    }

    // MARK: Panel

    /// A new tap supersedes both messages.
    func panelRequestBegan() { clearMessages() }

    func panelRequestFinished(_ outcome: GestureRequestOutcome) {
        if !outcome.succeeded { panelMessage = outcome.message }
    }

    /// The panel left the screen; its own message ends with it. A continuation
    /// failure stays until seen, a new tap, or a session.
    func clearPanelMessage() { panelMessage = nil }

    func clearContinuationMessage() { continuationMessage = nil }

    private func clearMessages() {
        continuationMessage = nil
        panelMessage = nil
    }

    // MARK: Deferred health refresh

    /// On connection: defers the automatic refresh while a start holds the
    /// ring, since a history import would outlast its readiness wait.
    /// Returns whether it was deferred.
    func deferHealthRefresh(full: Bool) -> Bool {
        guard holdsRing else { return false }
        deferredHealthRefresh = full
        return true
    }

    func connectionLost() { deferredHealthRefresh = nil }

    /// Runs the deferred refresh once nothing holds the ring and the ring is
    /// in Health; otherwise keeps it for the next trigger.
    func runDeferredHealthRefreshIfNeeded() {
        guard !holdsRing, let full = deferredHealthRefresh, deps.healthRefreshAllowed() else { return }
        deferredHealthRefresh = nil
        deps.refreshHealth(full)
    }
}
