import Foundation

/// Heal timing: pure constants and decisions, all on `GestureContinuousTime`.
enum GestureHealPolicy {
    /// A heal gives up after failing this long with the link up, or when the
    /// ring stays disconnected this long.
    static let healWindow: Double = 60
    /// After the link comes back, identification and attach get this long
    /// before a failing heal may give up.
    static let postReconnectGrace: Double = 20
    /// No episode outlives this, however the link flapped.
    static let episodeCap: Double = 180
    /// A calibration frame survives a heal that resumed this soon after the
    /// last good processing, with the link up throughout.
    static let keepFrameWindow: Double = 60
    /// An episode closes after this many passed renewals, at least
    /// `probationSeconds` after the heal resumed. A fault before that reopens
    /// it (same episode and journal attempt count) with a fresh give-up clock
    /// from the reopening fault: a heal that worked is never counted against
    /// the next one, and a reopening with the link up never gives up before
    /// one of its own attempts has failed.
    static let probationPasses = 2
    static let probationSeconds: Double = 30
    /// Consecutive charging refusals (A1 FF, or readiness) that end the session.
    static let chargingRefusals = 2
    /// A user Start during a heal skips the backoff, at most this often.
    static let kickSpacing: Double = 2

    /// 0.5, 1, 2, 4, 8, 8 ... s; capped at 4 s in the background, so attempts
    /// fall inside iOS's background-task grant.
    static func backoff(attempt: Int, background: Bool) -> Double {
        let exponent = Double(max(1, attempt) - 1)
        return min(0.5 * pow(2, exponent), background ? 4 : 8)
    }

    /// Nil while the heal may continue. `startedAt` is anchored at the last
    /// good processing, so a first opening woken after a long suspension gives
    /// up at once. `awaitingFailure` (a reopened episode none of whose own
    /// attempts has failed yet) never gives up with the link up before the
    /// cap: a heal that keeps working is not a failure to reconnect.
    static func giveUp(startedAt: Double, linkDownSince: Double?, linkUsableSince: Double?,
                       now: Double, awaitingFailure: Bool = false) -> GestureEndReason? {
        if let down = linkDownSince, now - down >= healWindow { return .ringGone }
        if now - startedAt >= episodeCap { return linkDownSince == nil ? .healGaveUp : .ringGone }
        if linkDownSince == nil, !awaitingFailure, now - startedAt >= healWindow,
           now - (linkUsableSince ?? startedAt) >= postReconnectGrace {
            return .healGaveUp
        }
        return nil
    }

    /// The earliest time `giveUp` can answer, for a notification scheduled
    /// ahead in case iOS suspends the app.
    static func giveUpDeadline(startedAt: Double, linkDownSince: Double?, linkUsableSince: Double?,
                               awaitingFailure: Bool = false) -> Double {
        let cap = startedAt + episodeCap
        if let down = linkDownSince { return min(cap, down + healWindow) }
        if awaitingFailure { return cap }
        return min(cap, max(startedAt + healWindow, (linkUsableSince ?? startedAt) + postReconnectGrace))
    }

    static func keepsFrame(hadFrame: Bool, linkDropped: Bool, faultAt: Double, resumedAt: Double) -> Bool {
        hadFrame && !linkDropped && resumedAt - faultAt <= keepFrameWindow
    }
}

/// What the panel shows while a heal runs.
struct GestureHealStatus: Equatable {
    enum Phase: String {
        case waitingForLink = "waiting_for_link"
        case waitingForRing = "waiting_for_ring"
        case backingOff = "backing_off"
        case attempting
    }

    var cause: GestureHealCause
    var attempt: Int
    var phase: Phase

    var statusText: String {
        switch phase {
        case .waitingForLink: return "Reconnecting gestures · waiting for the ring"
        case .waitingForRing: return "Reconnecting gestures · preparing the ring"
        case .backingOff, .attempting: return "Reconnecting gestures…"
        }
    }
}

/// Heals a sticky Gesture session: while the user still wants gestures, it
/// re-enters Gesture after the ring left it, using only the sequencer's
/// audited restart (optional stop A1 05, A1 02, 3B 02 01 00, then A1 04,
/// 3B 02 01 03), with bounded backoff, and gives up only after sustained
/// failure. It never ends a session itself: `onGiveUp` names the reason and
/// the owner ends it. Every dependency is injected, so tests run it on a
/// fake clock without Bluetooth.
@MainActor
final class GestureSessionKeeper {
    struct Dependencies {
        var now: () -> Double = { GestureContinuousTime.now() }
        var sleep: (Duration) async throws -> Void = { try await Task.sleep(for: $0) }
        /// The owner's desired state: false stops everything at once.
        var isDesired: () -> Bool
        var linkReady: () -> Bool
        /// Start readiness with the desired state ignored.
        var readiness: () -> GestureStartReadiness
        /// The attached firmware returns to Health by itself when the app
        /// stops renewing. Without that backstop a heal is never attempted.
        var leaseBackstop: () -> Bool
        /// `GestureSessionSequencer.restart` at the current heal epoch.
        var restart: () async -> GestureRequestOutcome
        /// Asks mode recovery to re-attach now; false when nothing could be scheduled.
        var requestReattach: () -> Bool = { false }
        /// A user timer (session timer, idle pause) that has already passed.
        var sessionDeadline: () -> GestureEndReason? = { nil }
        /// A calibration frame existed when the fault happened.
        var hadFrame: () -> Bool = { false }
        /// `GestureContinuousTime` of the last processed output or passed renewal.
        var lastGoodAt: () -> Double? = { nil }
        var inBackground: () -> Bool = { false }
    }

    /// (kind, fields) for the lifecycle journal.
    var onJournal: ((String, [String: Any]) -> Void)?
    /// The session must end: the reason, the episode's first cause, a detail.
    var onGiveUp: ((GestureEndReason, GestureHealCause, String?) -> Void)?
    var onStatusChange: ((GestureHealStatus?) -> Void)?
    /// An episode opened (true) or closed (false): the owner holds a
    /// background task meanwhile.
    var onEpisodeActive: ((Bool) -> Void)?

    private(set) var status: GestureHealStatus? {
        didSet { if oldValue != status { onStatusChange?(status) } }
    }

    /// An episode is open and the session is not running yet.
    var isHealing: Bool { episode != nil && episode?.resumedAt == nil }
    /// The heal resumed; the episode closes once renewals pass.
    var inProbation: Bool { episode?.resumedAt != nil }
    var isWaitingForLink: Bool { isHealing && status?.phase == .waitingForLink }
    var hasEpisode: Bool { episode != nil }
    /// When the running episode may give up, for a notification scheduled ahead.
    var giveUpDeadline: Double? {
        guard let episode, episode.resumedAt == nil else { return nil }
        return GestureHealPolicy.giveUpDeadline(startedAt: episode.startedAt, linkDownSince: episode.linkDownSince,
                                                linkUsableSince: episode.linkUsableSince,
                                                awaitingFailure: episode.awaitingFailure)
    }
    var attempts: Int { episode?.attempts ?? 0 }
    var cause: GestureHealCause? { episode?.cause }

    private struct Episode {
        let id: Int
        var cause: GestureHealCause
        var detail: String?
        /// The first fault, for journal durations.
        let openedAt: Double
        /// The give-up clock: anchored at the last good processing, never
        /// later than the fault; moved to the reopening fault (never earlier
        /// than the heal it follows) when a fault reopens the episode.
        var startedAt: Double
        var faultAt: Double
        /// All attempts of the episode, for the journal.
        var attempts = 0
        /// Failed attempts since the episode opened or last reopened.
        var attemptsThisOpening = 0
        /// The earliest time the next attempt may run: a wake (a re-attach,
        /// a reopened loop) never cuts a backoff short; a user kick may.
        var nextAttemptAt: Double?
        var hadFrame: Bool
        var linkDropped = false
        var linkDownSince: Double?
        var linkUsableSince: Double?
        var reopened = 0
        var chargingRefusals = 0
        var lastAttemptAt: Double?
        /// Set once the heal re-entered Gesture (probation).
        var resumedAt: Double?
        var passes = 0

        var awaitingFailure: Bool { reopened > 0 && attemptsThisOpening == 0 }

        mutating func countAttempt(at now: Double) {
            attempts += 1
            attemptsThisOpening += 1
            lastAttemptAt = now
        }
    }

    private let deps: Dependencies
    private var episode: Episode?
    private var nextEpisodeID = 0
    private var loop: Task<Void, Never>?
    /// The episode whose restart is in flight.
    private var attemptingEpisode: Int?
    private var attempting: Bool { attemptingEpisode != nil && attemptingEpisode == episode?.id }

    init(_ dependencies: Dependencies) { deps = dependencies }

    // MARK: Events from the owner

    /// Recognition stopped for a heal cause. Opens an episode, reopens one in
    /// probation, or (while one runs) only records the detail.
    func fault(_ cause: GestureHealCause, detail: String?) {
        guard deps.isDesired() else { return }
        let now = deps.now()
        if var current = episode {
            guard current.resumedAt != nil else {
                current.detail = detail ?? current.detail
                episode = current
                // An episode is never left without its loop.
                if loop == nil, !attempting { startLoop() }
                return
            }
            let resumedAt = current.resumedAt ?? now
            current.resumedAt = nil
            current.passes = 0
            current.reopened += 1
            current.faultAt = min(now, deps.lastGoodAt() ?? now)
            // A fresh give-up clock: the heal before this one worked.
            current.startedAt = min(now, max(current.faultAt, resumedAt))
            current.attemptsThisOpening = 0
            current.linkDownSince = nil
            current.linkUsableSince = nil
            current.linkDropped = false
            current.chargingRefusals = 0
            current.nextAttemptAt = nil
            current.hadFrame = deps.hadFrame()
            current.detail = detail
            episode = current
            journalStarted(current, trigger: cause)
            startLoop()
            return
        }
        open(cause, detail: detail, now: now)
    }

    /// The BLE link went down. Opens an episode when none runs, so a
    /// disconnect always reaches ring-gone even if nothing else faults.
    func linkLost() {
        guard deps.isDesired() else { return }
        let now = deps.now()
        if episode == nil { open(.disconnected, detail: "link_lost", now: now) }
        else if episode?.resumedAt != nil { fault(.disconnected, detail: "link_lost") }
        guard var current = episode else { return }
        current.linkDropped = true
        if current.linkDownSince == nil { current.linkDownSince = now }
        current.linkUsableSince = nil
        episode = current
        wake()
    }

    /// The link is back, identified and attached. A reconnect after the heal
    /// window never re-enters Gesture: the window is judged on the link-down
    /// state first.
    func linkUsable() {
        guard var current = episode, current.resumedAt == nil else { return }
        let now = deps.now()
        if let reason = GestureHealPolicy.giveUp(startedAt: current.startedAt, linkDownSince: current.linkDownSince,
                                                 linkUsableSince: current.linkUsableSince, now: now,
                                                 awaitingFailure: current.awaitingFailure) {
            return finish(reason, detail: "reconnected_late")
        }
        // After a real reconnect the next attempt runs at once.
        if current.linkDownSince != nil { current.nextAttemptAt = nil }
        current.linkDownSince = nil
        current.linkUsableSince = now
        episode = current
        wake()
    }

    /// Mode control was re-attached. Wakes a loop that waits for the ring;
    /// a backoff after a failed attempt still runs to its end
    /// (`nextAttemptAt`), since a failed entry itself schedules the re-attach.
    func controlRestored() { wake() }

    /// The heal re-entered Gesture. Returns whether the calibration frame is kept.
    func resumed() -> Bool {
        guard var current = episode else { return false }
        let now = deps.now()
        let keep = GestureHealPolicy.keepsFrame(hadFrame: current.hadFrame, linkDropped: current.linkDropped,
                                                faultAt: current.faultAt, resumedAt: now)
        current.resumedAt = now
        current.passes = 0
        current.chargingRefusals = 0
        episode = current
        status = nil
        journal("heal_succeeded", current, [
            "attempt": current.attempts, "duration_s": Self.rounded(now - current.openedAt),
            "calibration": keep ? "kept" : "recalibrate", "reopened": current.reopened,
        ])
        loop?.cancel()
        loop = nil
        return keep
    }

    /// A renewal passed. Closes an episode in probation once it is stable.
    func heartbeatPassed() {
        guard var current = episode, let resumedAt = current.resumedAt else { return }
        current.passes += 1
        let now = deps.now()
        guard current.passes >= GestureHealPolicy.probationPasses,
              now - resumedAt >= GestureHealPolicy.probationSeconds else {
            episode = current
            return
        }
        journal("heal_stable", current, ["attempt": current.attempts, "passes": current.passes,
                                         "duration_s": Self.rounded(now - current.openedAt)])
        close()
    }

    /// A user Start while healing: attempt now instead of after the backoff.
    /// The give-up clocks are untouched.
    func kick() {
        guard var current = episode, current.resumedAt == nil, !attempting else { return }
        let now = deps.now()
        if let last = current.lastAttemptAt, now - last < GestureHealPolicy.kickSpacing { return }
        current.nextAttemptAt = nil
        episode = current
        wake()
    }

    /// The session ended for another reason: stop without an attempt or a give-up.
    func cancel() {
        loop?.cancel()
        loop = nil
        guard let current = episode else { return }
        journal("heal_cancelled", current, ["attempt": current.attempts])
        close()
    }

    // MARK: Episode

    private func open(_ cause: GestureHealCause, detail: String?, now: Double) {
        nextEpisodeID += 1
        let anchor = min(now, deps.lastGoodAt() ?? now)
        let current = Episode(id: nextEpisodeID, cause: cause, detail: detail, openedAt: anchor, startedAt: anchor,
                              faultAt: anchor, hadFrame: deps.hadFrame())
        episode = current
        onEpisodeActive?(true)
        journalStarted(current, trigger: cause)
        startLoop()
    }

    private func close() {
        loop?.cancel()
        loop = nil
        episode = nil
        status = nil
        onEpisodeActive?(false)
    }

    private func finish(_ reason: GestureEndReason, detail: String?) {
        guard let current = episode else { return }
        let now = deps.now()
        journal("heal_gave_up", current, [
            "attempt": current.attempts, "reason": reason.rawValue,
            "duration_s": Self.rounded(now - current.openedAt),
            "link_down_s": current.linkDownSince.map { Self.rounded(now - $0) as Any } ?? NSNull(),
            "detail": detail.map { $0 as Any } ?? NSNull(),
        ])
        // Usually called from inside the loop, which returns next.
        loop?.cancel()
        loop = nil
        episode = nil
        status = nil
        onEpisodeActive?(false)
        onGiveUp?(reason, current.cause, detail ?? current.detail)
    }

    private func journalStarted(_ current: Episode, trigger: GestureHealCause) {
        journal("heal_started", current, [
            "trigger": trigger.rawValue, "detail": current.detail.map { $0 as Any } ?? NSNull(),
            "attempt": current.attempts, "reopened": current.reopened, "link_ready": deps.linkReady(),
            "had_frame": current.hadFrame,
            "since_last_good_s": Self.rounded(deps.now() - current.faultAt),
        ])
    }

    private func journal(_ kind: String, _ current: Episode, _ fields: [String: Any]) {
        var fields = fields
        fields["episode"] = current.id
        fields["cause"] = current.cause.rawValue
        onJournal?(kind, fields)
    }

    private static func rounded(_ value: Double) -> Double { (value * 1_000).rounded() / 1_000 }

    // MARK: Loop

    /// Restarts the loop so a sleeping backoff or wait ends now. Never while
    /// an attempt runs: its outcome decides what happens next.
    private func wake() {
        guard episode != nil, !attempting else { return }
        startLoop()
    }

    private func startLoop() {
        guard let id = episode?.id else { return }
        loop?.cancel()
        loop = Task { [weak self] in await self?.run(id) }
    }

    private func setPhase(_ phase: GestureHealStatus.Phase) {
        guard let current = episode else { return }
        status = GestureHealStatus(cause: current.cause, attempt: current.attempts, phase: phase)
    }

    private func nap(_ seconds: Double) async {
        try? await deps.sleep(.milliseconds(Int((max(0, seconds) * 1_000).rounded())))
    }

    private func isCurrent(_ id: Int) -> Bool {
        !Task.isCancelled && episode?.id == id && episode?.resumedAt == nil
    }

    private func run(_ id: Int) async {
        while isCurrent(id) {
            // The owner cancels on every end; this is a second guard.
            guard deps.isDesired() else { return }
            let now = deps.now()
            // A user timer that passed while the app slept ends the session with its own reason.
            if let reason = deps.sessionDeadline() { return finish(reason, detail: "deadline") }
            guard var current = episode else { return }
            if let reason = GestureHealPolicy.giveUp(startedAt: current.startedAt, linkDownSince: current.linkDownSince,
                                                     linkUsableSince: current.linkUsableSince, now: now,
                                                     awaitingFailure: current.awaitingFailure) {
                return finish(reason, detail: nil)
            }
            if !deps.linkReady() {
                current.linkDropped = true
                if current.linkDownSince == nil { current.linkDownSince = now }
                current.linkUsableSince = nil
                episode = current
                setPhase(.waitingForLink)
                let untilGone = GestureHealPolicy.healWindow - (now - (current.linkDownSince ?? now))
                await nap(min(0.5, max(0.05, untilGone)))
                continue
            }
            if current.linkDownSince != nil {
                // The link came back without a linkUsable() (no reconnect callback).
                current.linkDownSince = nil
                current.linkUsableSince = now
                current.nextAttemptAt = nil
                episode = current
            }
            // A wake during a backoff (a re-attach after the failed entry)
            // sleeps out the rest of it: attempts stay bounded.
            if let next = current.nextAttemptAt, next > now {
                setPhase(.backingOff)
                await nap(next - now)
                continue
            }
            let readiness = deps.readiness()
            switch readiness {
            case .connecting, .notConnected, .identifying, .attaching, .returning, .busy, .needsForeground:
                // Waiting for the ring is never a failed attempt.
                setPhase(.waitingForRing)
                await nap(0.25)
                continue
            case .cancelled:
                return
            case .unavailable:
                if deps.requestReattach() {
                    setPhase(.waitingForRing)
                    await nap(0.25)
                    continue
                }
                current.countAttempt(at: now)
                episode = current
                onJournal?("heal_attempt", ["episode": id, "attempt": current.attempts,
                                            "action": "reattach", "readiness": readiness.rawValue,
                                            "outcome": "unavailable"])
            case .charging:
                current.chargingRefusals += 1
                current.countAttempt(at: now)
                episode = current
                onJournal?("heal_attempt", ["episode": id, "attempt": current.attempts,
                                            "action": "none", "readiness": readiness.rawValue, "outcome": "charging"])
                if current.chargingRefusals >= GestureHealPolicy.chargingRefusals {
                    return finish(.charging, detail: "readiness")
                }
            case .ready, .alreadyActive:
                guard deps.leaseBackstop() else { return finish(.healGaveUp, detail: GestureGiveUpNotice.noLeaseDetail) }
                // Checked with no suspension before the restart captures its epoch.
                guard deps.isDesired() else { return }
                current.countAttempt(at: now)
                episode = current
                setPhase(.attempting)
                attemptingEpisode = id
                let outcome = await deps.restart()
                if attemptingEpisode == id { attemptingEpisode = nil }
                onJournal?("heal_attempt", ["episode": id, "attempt": current.attempts,
                                            "action": readiness == .alreadyActive ? "restart" : "enter",
                                            "readiness": readiness.rawValue, "outcome": outcome.journalName])
                // resumed() closed the attempt, or the owner cancelled.
                guard episode?.id == id, var after = episode, after.resumedAt == nil else { return }
                switch outcome {
                case .busy, .alreadyActive:
                    // Another transition owns the ring: a wait, not a failure.
                    after.attempts -= 1
                    after.attemptsThisOpening -= 1
                    episode = after
                    await nap(0.25)
                    continue
                case .charging:
                    after.chargingRefusals += 1
                    episode = after
                    if after.chargingRefusals >= GestureHealPolicy.chargingRefusals {
                        return finish(.charging, detail: "refused")
                    }
                default:
                    // Includes .started without a resume and .startCancelled
                    // while still desired: the next attempt restarts cleanly.
                    after.chargingRefusals = 0
                    episode = after
                }
            }
            guard isCurrent(id), var latest = episode else { return }
            let backoff = GestureHealPolicy.backoff(attempt: latest.attempts, background: deps.inBackground())
            latest.nextAttemptAt = deps.now() + backoff
            episode = latest
            setPhase(.backingOff)
            await nap(backoff)
        }
    }
}
