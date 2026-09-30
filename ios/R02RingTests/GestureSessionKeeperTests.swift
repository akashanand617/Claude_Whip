import XCTest
@testable import R02Ring

/// The heal loop on a fake continuous clock: every sleep advances it at once,
/// so a minute of backoff runs in a few hundred main-actor yields. No
/// Bluetooth: `restart` is scripted and records each call.
@MainActor
final class GestureSessionKeeperTests: XCTestCase {
    private final class World {
        var now = 1_000.0
        var desired = true
        var linkReady = true
        var readiness: GestureStartReadiness = .alreadyActive
        var lease = true
        var hadFrame = true
        var lastGoodAt: Double?
        var background = false
        var deadline: GestureEndReason?
        var reattach = false
        /// Clock times of each restart.
        var restarts: [Double] = []
        /// Answers restarts in order; the last repeats.
        var outcomes: [GestureRequestOutcome] = [.timedOut]
        /// Runs inside a restart (e.g. the owner resuming on success).
        var onRestart: ((World) -> Void)?
        var giveUps: [(GestureEndReason, GestureHealCause, String?)] = []
        var journal: [(String, [String: Any])] = []
        var statuses: [GestureHealStatus?] = []
        var active: [Bool] = []
        /// When set, sleeps block until the test resumes them (an app iOS suspended).
        var frozen = false
    }

    private var world: World!
    private var keeper: GestureSessionKeeper!

    override func setUp() {
        super.setUp()
        let world = World()
        self.world = world
        keeper = GestureSessionKeeper(.init(
            now: { world.now },
            sleep: { duration in
                while world.frozen { await Task.yield() }
                // A loop replaced while it slept never advances the clock.
                if Task.isCancelled { throw CancellationError() }
                let parts = duration.components
                world.now += Double(parts.seconds) + Double(parts.attoseconds) / 1e18
                await Task.yield()
            },
            isDesired: { world.desired },
            linkReady: { world.linkReady },
            readiness: { world.readiness },
            leaseBackstop: { world.lease },
            restart: {
                world.restarts.append(world.now)
                world.onRestart?(world)
                let outcome = world.outcomes.count > 1 ? world.outcomes.removeFirst() : world.outcomes[0]
                await Task.yield()
                return outcome
            },
            requestReattach: { world.reattach },
            sessionDeadline: { world.deadline },
            hadFrame: { world.hadFrame },
            lastGoodAt: { world.lastGoodAt },
            inBackground: { world.background }
        ))
        keeper.onGiveUp = { world.giveUps.append(($0, $1, $2)) }
        keeper.onJournal = { world.journal.append(($0, $1)) }
        keeper.onStatusChange = { world.statuses.append($0) }
        keeper.onEpisodeActive = { world.active.append($0) }
    }

    private func settle(_ what: String, file: StaticString = #filePath, line: UInt = #line,
                        _ condition: () -> Bool) async {
        for _ in 0..<50_000 {
            if condition() { return }
            await Task.yield()
        }
        XCTFail("never settled: \(what)", file: file, line: line)
    }

    private func drain() async { for _ in 0..<200 { await Task.yield() } }

    private func kinds() -> [String] { world.journal.map(\.0) }

    // MARK: Heal instead of exit

    func testAStaleStreamHealsThroughTheAuditedRestartAndNeverEndsTheSession() async throws {
        world.outcomes = [.started]
        world.onRestart = { [unowned self] _ in XCTAssertTrue(self.keeper.resumed(), "quick heal, link up: frame kept") }
        keeper.fault(.staleStream, detail: "gap:ceiling")
        XCTAssertTrue(keeper.isHealing)
        await settle("resumed") { keeper.inProbation }
        await drain()
        XCTAssertEqual(world.restarts.count, 1)
        XCTAssertTrue(world.giveUps.isEmpty)
        XCTAssertFalse(keeper.isHealing)
        XCTAssertNil(keeper.status)
        XCTAssertEqual(Array(kinds().prefix(1)), ["heal_started"])
        XCTAssertTrue(kinds().contains("heal_succeeded"))
        let started = try XCTUnwrap(world.journal.first { $0.0 == "heal_started" }?.1)
        XCTAssertEqual(started["cause"] as? String, "stale_stream")
        XCTAssertEqual(started["detail"] as? String, "gap:ceiling")
        let attempt = try XCTUnwrap(world.journal.first { $0.0 == "heal_attempt" }?.1)
        XCTAssertEqual(attempt["action"] as? String, "restart")
        XCTAssertEqual(attempt["attempt"] as? Int, 1)
        XCTAssertEqual(world.active, [true], "the background task is held until the episode closes")
    }

    func testFailingAttemptsBackOffAndGiveUpExactlyOnceAfterTheWindow() async {
        world.readiness = .ready
        world.outcomes = [.timedOut]
        let opened = world.now
        keeper.fault(.sourceStopped, detail: nil)
        await settle("gave up") { !world.giveUps.isEmpty }
        await drain()
        let offsets = world.restarts.map { $0 - opened }
        XCTAssertEqual(Array(offsets.prefix(6)), [0, 0.5, 1.5, 3.5, 7.5, 15.5])
        for (earlier, later) in zip(offsets, offsets.dropFirst()) {
            XCTAssertLessThanOrEqual(later - earlier, 8 + 1e-9, "the backoff is capped at 8 s")
        }
        XCTAssertLessThan(offsets.last ?? .infinity, 60, "no attempt at or after the window")
        XCTAssertEqual(world.giveUps.count, 1)
        XCTAssertEqual(world.giveUps.first?.0, .healGaveUp)
        XCTAssertEqual(world.giveUps.first?.1, .sourceStopped)
        XCTAssertGreaterThanOrEqual(world.now - opened, 60)
        XCTAssertLessThan(world.now - opened, 68.5)
        XCTAssertEqual(world.active, [true, false])
        XCTAssertEqual(kinds().last, "heal_gave_up")
        XCTAssertFalse(keeper.hasEpisode)
    }

    func testBackoffIsShorterInTheBackground() async {
        world.background = true
        world.outcomes = [.timedOut]
        let opened = world.now
        keeper.fault(.staleStream, detail: nil)
        await settle("gave up") { !world.giveUps.isEmpty }
        let offsets = world.restarts.map { $0 - opened }
        XCTAssertEqual(Array(offsets.prefix(6)), [0, 0.5, 1.5, 3.5, 7.5, 11.5])
    }

    func testARingGoneForTheWindowGivesUpWithoutAnAttempt() async {
        world.linkReady = false
        let lost = world.now
        keeper.linkLost()
        XCTAssertTrue(keeper.hasEpisode, "a disconnect alone opens an episode")
        await settle("ring gone") { !world.giveUps.isEmpty }
        XCTAssertEqual(world.restarts, [])
        XCTAssertEqual(world.giveUps.count, 1)
        XCTAssertEqual(world.giveUps.first?.0, .ringGone)
        XCTAssertGreaterThanOrEqual(world.now - lost, 60)
        XCTAssertLessThan(world.now - lost, 60.6)
        XCTAssertEqual(keeper.status, nil)
        XCTAssertTrue(world.statuses.contains { $0?.phase == .waitingForLink })
    }

    func testAReconnectAfterTheWindowNeverReentersGesture() async {
        // iOS suspends R02 right after the disconnect (its loop never runs);
        // the ring comes back 70 s later and wakes it.
        world.frozen = true
        world.linkReady = false
        keeper.linkLost()
        world.now += 70
        world.linkReady = true
        keeper.linkUsable()
        world.frozen = false
        await drain()
        XCTAssertEqual(world.restarts, [], "a late reconnect never re-enters Gesture")
        XCTAssertEqual(world.giveUps.map(\.0), [.ringGone])
    }

    func testAReconnectInsideTheWindowHealsAndRecalibrates() async {
        world.linkReady = false
        world.outcomes = [.started]
        world.onRestart = { [unowned self] _ in
            XCTAssertFalse(self.keeper.resumed(), "the link dropped: the calibration is asked for again")
        }
        keeper.linkLost()
        world.now += 30
        world.linkReady = true
        keeper.linkUsable()
        await settle("resumed") { keeper.inProbation }
        XCTAssertEqual(world.restarts.count, 1)
        XCTAssertTrue(world.giveUps.isEmpty)
    }

    func testAfterAReconnectAFailingHealGetsTheGraceBeforeGivingUp() async {
        world.linkReady = false
        world.outcomes = [.failed("entry")]
        let opened = world.now
        keeper.linkLost()
        world.now = opened + 50
        world.linkReady = true
        keeper.linkUsable()
        await settle("gave up") { !world.giveUps.isEmpty }
        XCTAssertEqual(world.giveUps.first?.0, .healGaveUp)
        XCTAssertGreaterThanOrEqual(world.now - opened, 70, "20 s after the link came back")
        XCTAssertFalse(world.restarts.isEmpty)
        XCTAssertLessThan((world.restarts.last ?? .infinity) - opened, 70)
    }

    func testWaitingForTheRingIsNeverAFailedAttempt() async throws {
        world.readiness = .identifying
        world.outcomes = [.started]
        world.onRestart = { [unowned self] _ in _ = self.keeper.resumed() }
        keeper.fault(.controlLost, detail: nil)
        await settle("waiting") { world.now >= 1_030 }
        XCTAssertEqual(world.restarts, [])
        XCTAssertEqual(keeper.attempts, 0)
        XCTAssertEqual(keeper.status?.phase, .waitingForRing)
        world.readiness = .ready
        await settle("resumed") { keeper.inProbation }
        await drain()
        let attempt = try XCTUnwrap(world.journal.first { $0.0 == "heal_attempt" }?.1)
        XCTAssertEqual(attempt["attempt"] as? Int, 1)
        XCTAssertEqual(attempt["action"] as? String, "enter")
    }

    func testABusyRingIsAWaitNotAFailure() async {
        world.outcomes = [.busy, .busy, .started]
        world.onRestart = { [unowned self] world in if world.restarts.count == 3 { _ = self.keeper.resumed() } }
        keeper.fault(.staleStream, detail: nil)
        await settle("resumed") { keeper.inProbation }
        await drain()
        XCTAssertEqual(world.restarts.count, 3)
        let attempts = world.journal.filter { $0.0 == "heal_attempt" }.compactMap { $0.1["attempt"] as? Int }
        XCTAssertEqual(attempts, [1, 1, 1])
    }

    // MARK: The charger

    func testTwoChargingRefusalsEndAsChargingOneDoesNot() async {
        world.outcomes = [.charging, .timedOut, .charging, .charging]
        keeper.fault(.staleStream, detail: nil)
        await settle("gave up") { !world.giveUps.isEmpty }
        XCTAssertEqual(world.restarts.count, 4, "a single refusal is one failed attempt; two in a row end it")
        XCTAssertEqual(world.giveUps.first?.0, .charging)
    }

    func testChargingReadinessEndsWithoutAnyWrite() async {
        world.readiness = .charging
        keeper.fault(.unexpectedHealth, detail: nil)
        await settle("gave up") { !world.giveUps.isEmpty }
        XCTAssertEqual(world.restarts, [])
        XCTAssertEqual(world.giveUps.first?.0, .charging)
    }

    // MARK: What stops a heal

    func testEndingTheSessionDuringABackoffStopsEveryAttempt() async {
        world.outcomes = [.timedOut]
        world.onRestart = { world in world.desired = false }
        keeper.fault(.staleStream, detail: nil)
        await settle("first attempt") { world.restarts.count == 1 }
        await drain()
        XCTAssertEqual(world.restarts.count, 1)
        XCTAssertTrue(world.giveUps.isEmpty, "the owner ended it; the keeper announces nothing")
        keeper.cancel()
        XCTAssertFalse(keeper.hasEpisode)
        XCTAssertEqual(kinds().last, "heal_cancelled")
        XCTAssertEqual(world.active, [true, false])
    }

    func testNothingHappensWhenNoSessionIsWanted() async {
        world.desired = false
        keeper.fault(.staleStream, detail: nil)
        keeper.linkLost()
        await drain()
        XCTAssertFalse(keeper.hasEpisode)
        XCTAssertEqual(world.restarts, [])
        XCTAssertTrue(world.journal.isEmpty)
    }

    func testAPassedUserTimerEndsWithItsOwnReasonInsteadOfHealing() async {
        world.deadline = .autoReturn
        keeper.fault(.sourceStopped, detail: nil)
        await settle("ended") { !world.giveUps.isEmpty }
        XCTAssertEqual(world.restarts, [])
        XCTAssertEqual(world.giveUps.first?.0, .autoReturn)
    }

    func testFirmwareWithoutALeaseIsNeverHealed() async {
        world.lease = false
        keeper.fault(.staleStream, detail: nil)
        await settle("gave up") { !world.giveUps.isEmpty }
        XCTAssertEqual(world.restarts, [])
        XCTAssertEqual(world.giveUps.first?.0, .healGaveUp)
        XCTAssertEqual(world.giveUps.first?.2, "no_lease")
    }

    func testAWakeLongAfterTheLastGoodDataGivesUpWithoutAnAttempt() async {
        // The stream died while iOS had R02 suspended; the next BLE wake is two hours later.
        world.lastGoodAt = world.now - 7_200
        keeper.fault(.sourceStopped, detail: "heartbeat:processed_age=7200.000")
        await settle("gave up") { !world.giveUps.isEmpty }
        XCTAssertEqual(world.restarts, [])
        XCTAssertEqual(world.giveUps.first?.0, .healGaveUp)
    }

    func testMissingModeControlAsksForARecoveryAttach() async {
        world.readiness = .unavailable
        world.reattach = true
        keeper.fault(.controlLost, detail: nil)
        await settle("waiting") { world.now >= 1_005 }
        XCTAssertEqual(world.restarts, [])
        XCTAssertEqual(keeper.attempts, 0, "a pending re-attach is a wait")
        world.reattach = false
        await settle("counted") { keeper.attempts >= 2 }
        XCTAssertEqual(world.restarts, [])
    }

    // MARK: Probation, flapping and kicks

    func testAFaultBeforeTheHealIsStableReopensTheSameEpisode() async throws {
        world.outcomes = [.started]
        world.onRestart = { [unowned self] _ in _ = self.keeper.resumed() }
        let opened = world.now
        keeper.fault(.staleStream, detail: nil)
        await settle("resumed") { keeper.inProbation }
        world.now += 10
        keeper.heartbeatPassed()
        XCTAssertTrue(keeper.inProbation, "one pass, 10 s: not stable yet")
        world.onRestart = nil
        world.outcomes = [.timedOut]
        let refault = world.now
        keeper.fault(.staleStream, detail: "again")
        XCTAssertTrue(keeper.isHealing)
        let reopened = try XCTUnwrap(world.journal.last { $0.0 == "heal_started" }?.1)
        XCTAssertEqual(reopened["reopened"] as? Int, 1)
        XCTAssertEqual(reopened["episode"] as? Int, 1, "the same episode")
        await settle("gave up") { !world.giveUps.isEmpty }
        XCTAssertGreaterThanOrEqual(world.now - refault, 60, "the reopening's own window: the heal before it worked")
        XCTAssertLessThan(world.now - refault, 68.5)
        XCTAssertGreaterThan(world.restarts.filter { $0 >= refault }.count, 1, "its own attempts failed first")
        XCTAssertGreaterThan(world.now - opened, 60)
    }

    /// A stream that stalls but heals every time: faults at 0, 28, 56 and 70
    /// (the last inside the probation of the heal at 58) never give up.
    func testAStreamThatStallsButHealsEveryTimeNeverGivesUp() async {
        world.outcomes = [.started]
        world.onRestart = { [unowned self] world in
            world.now += 2
            _ = self.keeper.resumed()
        }
        let opened = world.now
        for offset in [0.0, 28, 56, 70] {
            world.now = opened + offset
            world.lastGoodAt = world.now
            keeper.fault(.staleStream, detail: "gap:ceiling")
            await settle("healed at \(offset)") { keeper.inProbation }
            world.now += 1
            keeper.heartbeatPassed()
        }
        await drain()
        XCTAssertTrue(world.giveUps.isEmpty, "every heal worked: nothing failed to reconnect")
        XCTAssertEqual(world.restarts.count, 4, "each fault got its attempt")
        XCTAssertFalse(kinds().contains("heal_gave_up"))
        keeper.cancel()
    }

    /// After a 40 s outage and a successful reconnect heal, one stale fault
    /// inside probation gets a full window of its own.
    func testAFaultAfterASuccessfulReconnectHealGetsAFullWindow() async {
        world.linkReady = false
        world.outcomes = [.started]
        world.onRestart = { [unowned self] world in
            world.now += 1.5
            _ = self.keeper.resumed()
        }
        let lost = world.now
        keeper.linkLost()
        world.now = lost + 40
        world.linkReady = true
        keeper.linkUsable()
        await settle("reconnected") { keeper.inProbation }
        world.now = lost + 62
        world.lastGoodAt = world.now - 0.3
        keeper.fault(.staleStream, detail: "gap:ceiling")
        await settle("healed again") { world.restarts.count == 2 }
        await drain()
        XCTAssertTrue(world.giveUps.isEmpty, "the reconnect worked; this fault is not a minute of failures")
        XCTAssertTrue(keeper.inProbation)
        keeper.cancel()
    }

    /// A reopening that is waiting for the ring, never attempting, is not a
    /// failure either; only the cap bounds it.
    func testAReopeningWithoutAFailedAttemptGivesUpOnlyAtTheCap() async {
        world.outcomes = [.started]
        world.onRestart = { [unowned self] _ in _ = self.keeper.resumed() }
        keeper.fault(.staleStream, detail: nil)
        await settle("resumed") { keeper.inProbation }
        world.readiness = .identifying
        let refault = world.now
        keeper.fault(.controlLost, detail: nil)
        await settle("gave up") { !world.giveUps.isEmpty }
        XCTAssertEqual(world.restarts.count, 1)
        XCTAssertGreaterThanOrEqual(world.now - refault, GestureHealPolicy.episodeCap)
        XCTAssertEqual(world.giveUps.first?.0, .healGaveUp)
    }

    /// A failed entry schedules a mode re-attach; its recovery must not cut
    /// the backoff short.
    func testARecoveryAttachDuringABackoffWaitsItOut() async {
        world.outcomes = [.timedOut]
        let opened = world.now
        keeper.fault(.sourceStopped, detail: nil)
        await settle("third attempt") { world.restarts.count == 3 }
        // Sleeps hold from here: the loop parks in the 2 s backoff after attempt 3.
        world.frozen = true
        await drain()
        XCTAssertEqual(keeper.status?.phase, .backingOff)
        keeper.controlRestored()
        await drain()
        keeper.controlRestored()
        await drain()
        XCTAssertEqual(world.restarts.count, 3, "a re-attach is not a reason to attempt early")
        world.frozen = false
        await settle("fourth attempt") { world.restarts.count == 4 }
        XCTAssertEqual(world.restarts.map { $0 - opened }, [0, 0.5, 1.5, 3.5],
                       "the wake slept out the rest of the backoff")
        keeper.cancel()
    }

    func testARecoveryAttachStillWakesALoopWaitingForTheRing() async {
        world.readiness = .unavailable
        world.reattach = true
        world.frozen = true
        keeper.fault(.controlLost, detail: nil)
        await drain()
        XCTAssertEqual(keeper.status?.phase, .waitingForRing)
        world.readiness = .ready
        world.outcomes = [.started]
        world.onRestart = { [unowned self] _ in _ = self.keeper.resumed() }
        keeper.controlRestored()
        await settle("attempted at once") { world.restarts.count == 1 }
        XCTAssertEqual(world.restarts, [1_000])
        keeper.cancel()
        world.frozen = false
        await drain()
    }

    func testANoLeaseGiveUpCarriesItsOwnDetail() async throws {
        world.lease = false
        keeper.fault(.staleStream, detail: nil)
        await settle("gave up") { !world.giveUps.isEmpty }
        let (reason, cause, detail) = try XCTUnwrap(world.giveUps.first)
        XCTAssertFalse(GestureGiveUpNotice.body(reason, cause: cause, detail: detail, time: "9:41")
            .contains("for a minute"))
    }

    func testAnEpisodeClosesAfterTwoPassesAndThirtySeconds() async {
        world.outcomes = [.started]
        world.onRestart = { [unowned self] _ in _ = self.keeper.resumed() }
        keeper.fault(.staleStream, detail: nil)
        await settle("resumed") { keeper.inProbation }
        keeper.heartbeatPassed()
        keeper.heartbeatPassed()
        XCTAssertTrue(keeper.inProbation, "two passes inside 30 s are not enough")
        world.now += 30
        keeper.heartbeatPassed()
        XCTAssertFalse(keeper.hasEpisode)
        XCTAssertEqual(kinds().last, "heal_stable")
        XCTAssertEqual(world.active, [true, false])
        // A later fault is a new episode with its own window.
        world.onRestart = nil
        keeper.fault(.leaseLapsed, detail: nil)
        XCTAssertEqual(world.journal.last { $0.0 == "heal_started" }?.1["episode"] as? Int, 2)
        keeper.cancel()
    }

    func testAKickSkipsTheBackoffButNotTheWindow() async {
        world.outcomes = [.timedOut]
        // Sleeps hold until released: the loop parks in its first backoff.
        world.frozen = true
        keeper.fault(.staleStream, detail: nil)
        await settle("first attempt") { world.restarts.count == 1 }
        await drain()
        keeper.kick()
        await drain()
        XCTAssertEqual(world.restarts.count, 1, "a Start right after an attempt waits for the backoff")
        world.now += 2.5
        keeper.kick()
        await settle("kicked") { world.restarts.count == 2 }
        XCTAssertEqual(world.restarts, [1_000, 1_002.5], "attempted at once, without the backoff's sleep")
        XCTAssertEqual(keeper.giveUpDeadline, 1_060, "the window still runs from the fault")
        keeper.cancel()
        world.frozen = false
        await drain()
        XCTAssertEqual(world.restarts.count, 2)
    }

    func testTheCalibrationFrameIsKeptOnlyForAQuickHealWithTheLinkUp() {
        world.hadFrame = true
        keeper.fault(.staleStream, detail: nil)
        world.now += 5
        XCTAssertTrue(keeper.resumed())
        keeper.cancel()

        keeper.fault(.staleStream, detail: nil)
        world.now += 61
        XCTAssertFalse(keeper.resumed(), "over a minute")
        keeper.cancel()

        world.hadFrame = false
        keeper.fault(.staleStream, detail: nil)
        XCTAssertFalse(keeper.resumed(), "never calibrated")
        keeper.cancel()

        world.hadFrame = true
        keeper.fault(.staleStream, detail: nil)
        world.linkReady = false
        keeper.linkLost()
        world.linkReady = true
        keeper.linkUsable()
        XCTAssertFalse(keeper.resumed(), "the link dropped")
        keeper.cancel()
    }

    func testTheGiveUpDeadlineFollowsTheLink() {
        let opened = world.now
        keeper.fault(.staleStream, detail: nil)
        XCTAssertEqual(keeper.giveUpDeadline, opened + 60)
        world.now += 10
        world.linkReady = false
        keeper.linkLost()
        XCTAssertEqual(keeper.giveUpDeadline, opened + 70)
        world.now += 5
        world.linkReady = true
        keeper.linkUsable()
        XCTAssertEqual(keeper.giveUpDeadline, opened + 60)
        _ = keeper.resumed()
        XCTAssertNil(keeper.giveUpDeadline, "nothing to give up while the session runs")
        keeper.cancel()
    }
}
