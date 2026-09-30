import XCTest
@testable import R02Ring

/// `GestureStartHolds`: the foreground hold, a Shortcut's continuation in R02,
/// the health refresh deferred while a start holds the ring, and the failure
/// messages a start leaves behind. No Bluetooth, no `AppModel`.
@MainActor
final class GestureStartHoldsTests: XCTestCase {
    private var pendingStarts = 0
    private var refreshAllowed = true
    private var refreshes: [Bool] = []
    private var changes = 0

    override func setUp() {
        super.setUp()
        pendingStarts = 0
        refreshAllowed = true
        refreshes = []
        changes = 0
    }

    /// By default the foreground hold lasts until cancelled (an hour).
    private func makeHolds(pendingStarts: (() -> Int)? = nil,
                           holdSleep: @escaping (Duration) async throws -> Void = { _ in
                               try await Task.sleep(for: .seconds(3_600))
                           }) -> GestureStartHolds {
        let holds = GestureStartHolds(.init(
            pendingStarts: pendingStarts ?? { [unowned self] in self.pendingStarts },
            healthRefreshAllowed: { [unowned self] in self.refreshAllowed },
            refreshHealth: { [unowned self] in self.refreshes.append($0) },
            sleep: holdSleep
        ))
        holds.onChange = { [unowned self] in self.changes += 1 }
        return holds
    }

    /// Lets the other main-actor tasks run until `condition` holds.
    private func settle(_ what: String, file: StaticString = #filePath, line: UInt = #line,
                        _ condition: () -> Bool) async {
        for _ in 0..<20_000 {
            if condition() { return }
            await Task.yield()
        }
        XCTFail("never settled: \(what)", file: file, line: line)
    }

    /// A continuation in R02 that started no session.
    private func failContinuation(_ holds: GestureStartHolds, _ outcome: GestureRequestOutcome = .notConnected,
                                  file: StaticString = #filePath, line: UInt = #line) async {
        holds.continueInForeground { outcome }
        await settle("continuation finished", file: file, line: line) { !holds.continuationPending }
        XCTAssertEqual(holds.continuationMessage, GestureIntentLogic.continuationMessage(outcome),
                       file: file, line: line)
    }

    // MARK: Failure messages

    func testReachingGestureFromAnySourceClearsBothFailureMessages() async {
        // A continuation failed while R02 was in front; the user went back to
        // another app, and a later Back Tap started a session there. The panel
        // was not on screen, so only the model saw the mode change.
        let holds = makeHolds()
        await failContinuation(holds)
        holds.panelRequestFinished(.timedOut)
        XCTAssertEqual(holds.panelMessage, GestureRequestOutcome.timedOut.message)
        let published = changes

        holds.modeChanged(to: .enteringGesture)
        XCTAssertNotNil(holds.continuationMessage, "entering is not yet a session")
        holds.modeChanged(to: .gesture)
        XCTAssertNil(holds.continuationMessage)
        XCTAssertNil(holds.panelMessage)
        XCTAssertGreaterThan(changes, published, "AppModel republishes both messages")
    }

    func testAFailedEntryKeepsTheFailureMessage() async {
        let holds = makeHolds()
        await failContinuation(holds, .timedOut)
        holds.panelRequestFinished(.notConnected)
        // A failed entry passes through the entering mode, loses control and
        // recovers to Health: no session ran, so the failure still stands.
        for mode: RingRuntimeMode? in [.enteringGesture, nil, .health] {
            holds.modeChanged(to: mode)
        }
        XCTAssertEqual(holds.continuationMessage, GestureIntentLogic.continuationMessage(.timedOut))
        XCTAssertEqual(holds.panelMessage, GestureRequestOutcome.notConnected.message)
    }

    func testAStartThatJoinsARunningSessionClearsTheMessages() async {
        // No mode change follows when the session was already running.
        let holds = makeHolds()
        await failContinuation(holds)
        holds.panelRequestFinished(.busy)
        holds.startFinished(.alreadyActive)
        XCTAssertNil(holds.continuationMessage)
        XCTAssertNil(holds.panelMessage)

        await failContinuation(holds)
        holds.startFinished(.started)
        XCTAssertNil(holds.continuationMessage)
    }

    func testAStartThatStartedNothingKeepsTheMessages() async {
        let holds = makeHolds()
        await failContinuation(holds)
        for outcome: GestureRequestOutcome in [.timedOut, .notConnected, .startCancelled, .busy, .failed("x")] {
            holds.startFinished(outcome)
            XCTAssertNotNil(holds.continuationMessage, "\(outcome)")
        }
    }

    func testPanelTapMessages() async {
        let holds = makeHolds()
        await failContinuation(holds)
        holds.panelRequestFinished(.startCancelled)
        XCTAssertNil(holds.panelMessage, "a withdrawn start is what the tap asked for")
        holds.panelRequestFinished(.charging)
        XCTAssertEqual(holds.panelMessage, GestureRequestOutcome.charging.message)

        holds.clearPanelMessage() // the panel left the screen
        XCTAssertNil(holds.panelMessage)
        XCTAssertNotNil(holds.continuationMessage, "an unseen continuation failure stays")

        holds.panelRequestFinished(.charging)
        holds.panelRequestBegan() // a new tap supersedes both
        XCTAssertNil(holds.panelMessage)
        XCTAssertNil(holds.continuationMessage)
    }

    func testAWithdrawnContinuationPublishesNoFailure() async {
        let holds = makeHolds()
        var finished = false
        holds.continueInForeground {
            try? await Task.sleep(for: .seconds(3_600))
            finished = true
            return .notConnected
        }
        _ = await holds.stop { _ in .startCancelled }
        await settle("withdrawn continuation ended") { finished }
        for _ in 0..<10 { await Task.yield() }
        XCTAssertNil(holds.continuationMessage)
        XCTAssertFalse(holds.continuationPending)
    }

    // MARK: Deferred health refresh

    func testStopThatDropsOnlyTheForegroundHoldRunsTheDeferredRefreshAfterTheStop() async {
        // An intent got .notConnected and asked to continue in R02; the ring
        // then reconnected while the hold was active, so the refresh was
        // deferred. A Pause (or a Toggle that stops) arrives with no session and
        // no continuation: the ring never leaves Health, so no mode change will
        // run the refresh later.
        let holds = makeHolds()
        holds.expectForegroundStart()
        XCTAssertTrue(holds.holdsRing)
        XCTAssertTrue(holds.deferHealthRefresh(full: true))
        holds.runDeferredHealthRefreshIfNeeded()
        XCTAssertEqual(refreshes, [], "held")

        var refreshedBeforeStopSettled = true
        let outcome = await holds.stop { withdrewContinuation in
            XCTAssertFalse(withdrewContinuation)
            XCTAssertFalse(holds.foregroundHoldActive, "the hold is dropped before the stop")
            refreshedBeforeStopSettled = !self.refreshes.isEmpty
            return .alreadyStopped
        }
        XCTAssertEqual(outcome, .alreadyStopped)
        XCTAssertFalse(refreshedBeforeStopSettled, "the refresh waits for the stop")
        XCTAssertEqual(refreshes, [true])
        XCTAssertNil(holds.deferredHealthRefresh)
        XCTAssertFalse(holds.holdsRing)

        for _ in 0..<10 { await Task.yield() }
        XCTAssertEqual(refreshes, [true], "the cancelled hold runs nothing more")
    }

    func testStopThatWithdrawsAContinuationRunsTheDeferredRefreshAfterTheStop() async {
        let holds = makeHolds()
        holds.expectForegroundStart()
        holds.continueInForeground {
            try? await Task.sleep(for: .seconds(3_600))
            return .notConnected
        }
        XCTAssertFalse(holds.foregroundHoldActive, "the continuation takes over the hold")
        XCTAssertTrue(holds.continuationPending)
        XCTAssertTrue(holds.deferHealthRefresh(full: false))

        var refreshedBeforeStopSettled = true
        let outcome = await holds.stop { withdrewContinuation in
            XCTAssertTrue(withdrewContinuation)
            XCTAssertFalse(holds.continuationPending)
            refreshedBeforeStopSettled = !self.refreshes.isEmpty
            return .startCancelled
        }
        XCTAssertEqual(outcome, .startCancelled)
        XCTAssertFalse(refreshedBeforeStopSettled)
        XCTAssertEqual(refreshes, [false])
        XCTAssertNil(holds.deferredHealthRefresh)
    }

    func testHoldOnlyStopThroughTheSequencerRunsTheDeferredRefresh() async {
        // The AppModel stop branch, with the real sequencer and a ring in Health.
        var calls: [Bool] = []
        let sequencer = GestureSessionSequencer(.init(
            setGesture: { calls.append($0) },
            isGestureMode: { false },
            modeControlAvailable: { true },
            linkReady: { true },
            now: { 100 },
            sleep: { _ in await Task.yield() }
        ))
        let holds = makeHolds(pendingStarts: { sequencer.pendingStarts })
        holds.expectForegroundStart()
        XCTAssertTrue(holds.deferHealthRefresh(full: true))

        let outcome = await holds.stop { continuation in
            await sequencer.requestStop(reason: .intent, alsoWithdrawing: continuation)
        }
        XCTAssertEqual(outcome, .alreadyStopped, "nothing was pending in the sequencer or continuing in R02")
        XCTAssertEqual(calls, [], "no packets for a ring already in Health")
        XCTAssertEqual(refreshes, [true])
        XCTAssertNil(holds.deferredHealthRefresh)
    }

    func testStopLeavesTheRefreshDeferredWhileASequencerStartStillHoldsTheRing() async {
        let holds = makeHolds()
        pendingStarts = 1
        XCTAssertTrue(holds.deferHealthRefresh(full: true))
        _ = await holds.stop { _ in .startCancelled }
        XCTAssertEqual(refreshes, [])
        XCTAssertEqual(holds.deferredHealthRefresh, true)

        // The withdrawn start returns from its readiness wait.
        pendingStarts = 0
        holds.startFinished(.startCancelled)
        XCTAssertEqual(refreshes, [true])
    }

    func testDeferredRefreshWaitsForTheRingToBeInHealth() async {
        // A failed stop, or a start that entered Gesture, must not consume it.
        let holds = makeHolds()
        holds.expectForegroundStart()
        XCTAssertTrue(holds.deferHealthRefresh(full: false))
        refreshAllowed = false
        _ = await holds.stop { _ in .busy }
        XCTAssertEqual(refreshes, [])
        XCTAssertEqual(holds.deferredHealthRefresh, false)

        refreshAllowed = true // the later return to Health
        holds.runDeferredHealthRefreshIfNeeded()
        XCTAssertEqual(refreshes, [false])
    }

    func testExpiredHoldRunsTheDeferredRefresh() async {
        // The user declined to continue in R02.
        let holds = makeHolds(holdSleep: { _ in await Task.yield() })
        holds.expectForegroundStart()
        XCTAssertTrue(holds.deferHealthRefresh(full: true))
        await settle("hold expired") { !holds.foregroundHoldActive }
        XCTAssertEqual(refreshes, [true])
    }

    func testNothingHeldMeansNothingDeferred() async {
        let holds = makeHolds()
        XCTAssertFalse(holds.holdsRing)
        XCTAssertFalse(holds.deferHealthRefresh(full: true), "the caller refreshes at once")
        XCTAssertNil(holds.deferredHealthRefresh)

        holds.expectForegroundStart()
        XCTAssertTrue(holds.deferHealthRefresh(full: true))
        holds.connectionLost()
        XCTAssertNil(holds.deferredHealthRefresh)

        _ = await holds.stop { _ in .alreadyStopped } // ends the hour-long hold
        XCTAssertEqual(refreshes, [], "a lost connection's refresh is gone")
    }
    // MARK: Sticky sessions

    func testADesiredSessionHoldsTheRingThroughItsHealsAndReleasesTheRefreshAfter() {
        var desired = true
        let holds = GestureStartHolds(.init(
            pendingStarts: { 0 },
            healthRefreshAllowed: { [unowned self] in self.refreshAllowed },
            refreshHealth: { [unowned self] in self.refreshes.append($0) },
            sessionHoldsRing: { desired }
        ))
        XCTAssertTrue(holds.holdsRing, "a heal's Health window is not a free ring")
        XCTAssertTrue(holds.deferHealthRefresh(full: false), "a reconnect during a heal defers the history import")
        holds.runDeferredHealthRefreshIfNeeded()
        XCTAssertEqual(refreshes, [])
        desired = false // the session ended (any allowed reason, a give-up included)
        XCTAssertFalse(holds.holdsRing)
        holds.runDeferredHealthRefreshIfNeeded()
        XCTAssertEqual(refreshes, [false])
    }
}
