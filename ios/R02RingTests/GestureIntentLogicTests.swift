import XCTest
import AppIntents
@testable import R02Ring

/// Answers requests the way `AppModel` does, from the pure readiness rules,
/// and records each call. Never touches Bluetooth.
@MainActor
private final class FakeModeControl: GestureModeControlling {
    struct Request: Equatable {
        let enabled: Bool
        let source: GestureRequestSource
        let timeout: TimeInterval
    }

    var gestureModeSnapshot: GestureModeSnapshot
    var requests: [Request] = []
    /// (kind, decision) per `noteIntent`.
    var intents: [[String]] = []
    /// Overrides the readiness-derived answer.
    var forcedOutcome: GestureRequestOutcome?
    var onRequest: ((FakeModeControl) -> Void)?

    init(_ snapshot: GestureModeSnapshot) { gestureModeSnapshot = snapshot }

    func requestGestureSession(_ enabled: Bool, source: GestureRequestSource,
                               readinessTimeout: TimeInterval) async -> GestureRequestOutcome {
        requests.append(Request(enabled: enabled, source: source, timeout: readinessTimeout))
        onRequest?(self)
        if let forcedOutcome { return forcedOutcome }
        if !enabled {
            if gestureModeSnapshot.gestureActive { return .stopped }
            return gestureModeSnapshot.startPending ? .startCancelled : .alreadyStopped
        }
        return GestureStartReadiness.evaluate(gestureModeSnapshot).outcome ?? .started
    }

    func noteIntent(_ kind: String, decision: String) { intents.append([kind, decision]) }
}

/// Stamps start requests and derives the snapshot's pending age exactly as
/// `AppModel` does with `GestureStartStamp`; a start stays pending while its
/// request runs, and `whileStartPending` runs inside it (a second Back Tap).
@MainActor
private final class StampedModeControl: GestureModeControlling {
    var now = 0.0
    private(set) var stamp = GestureStartStamp()
    var snapshot: GestureModeSnapshot
    var continuationPending = false
    var pendingStarts = 0
    var intents: [[String]] = []
    var whileStartPending: (() async -> Void)?
    var pending: Bool { pendingStarts > 0 || continuationPending }

    init(_ snapshot: GestureModeSnapshot) { self.snapshot = snapshot }

    var gestureModeSnapshot: GestureModeSnapshot {
        var current = self.snapshot
        current.startPending = pending
        current.startPendingAge = stamp.pendingAge(at: now, pending: pending)
        return current
    }

    /// `openGesturesAfterIntent`: the user tapped Continue in R02.
    func userContinued() {
        stamp.userContinued(at: now)
        continuationPending = true
    }

    func requestGestureSession(_ enabled: Bool, source: GestureRequestSource,
                               readinessTimeout: TimeInterval) async -> GestureRequestOutcome {
        guard enabled else {
            let withdrew = pending
            stamp.stopRequested()
            continuationPending = false
            pendingStarts = 0
            return withdrew ? .startCancelled : .alreadyStopped
        }
        stamp.startRequested(at: now, alreadyPending: pending)
        pendingStarts += 1
        defer { pendingStarts = max(0, pendingStarts - 1) }
        if let hook = whileStartPending {
            whileStartPending = nil
            await hook()
        }
        return pending ? .timedOut : .startCancelled
    }

    func noteIntent(_ kind: String, decision: String) { intents.append([kind, decision]) }
}

@MainActor
final class GestureIntentLogicTests: XCTestCase {
    private let health = GestureModeSnapshot(
        link: .ready, connectionSetupComplete: true, unifiedFirmwareInstalled: true,
        modeAttachInFlight: false, modeControlAvailable: true, mode: .health, charging: false,
        transition: nil, ringBusy: false, firmwareSwitching: false, appActive: false,
        keepGesturesInBackground: true
    )

    private let allOutcomes: [GestureRequestOutcome] = [
        .started, .stopped, .alreadyActive, .alreadyStopped, .needsForeground, .unavailable,
        .charging, .busy, .notConnected, .timedOut, .startCancelled, .failed("boom"),
    ]

    private func control(_ change: (inout GestureModeSnapshot) -> Void = { _ in }) -> FakeModeControl {
        var snapshot = health
        change(&snapshot)
        return FakeModeControl(snapshot)
    }

    // MARK: Toggle

    func testToggleStartsFromHealth() async {
        let fake = control()
        let reply = await GestureIntentLogic.toggle(fake)
        XCTAssertEqual(fake.requests, [.init(enabled: true, source: .intent, timeout: 10)])
        XCTAssertEqual(reply.outcome, .started)
        XCTAssertFalse(reply.needsForeground)
    }

    func testToggleStopsARunningOrEnteringSession() async {
        let active: [(inout GestureModeSnapshot) -> Void] = [
            { $0.mode = .gesture }, { $0.mode = .enteringGesture }, { $0.transition = .entering },
        ]
        for change in active {
            let fake = control(change)
            let reply = await GestureIntentLogic.toggle(fake)
            XCTAssertEqual(fake.requests.map(\.enabled), [false])
            XCTAssertEqual(fake.requests.first?.source, .intent)
            XCTAssertEqual(reply.outcome, .stopped)
            XCTAssertFalse(reply.needsForeground)
        }
    }

    func testToggleWhileReturningStartsAgain() async {
        // A second Back Tap during a return asks for Gesture again; the model's
        // readiness wait covers the return, which here outlasts the wait.
        // What the model publishes during a stop: still Gesture, transition leaving.
        let fake = control { $0.mode = .gesture; $0.transition = .leaving }
        XCTAssertFalse(fake.gestureModeSnapshot.gestureActive)
        let reply = await GestureIntentLogic.toggle(fake)
        XCTAssertEqual(fake.requests.map(\.enabled), [true])
        XCTAssertEqual(reply.outcome, .timedOut)
        XCTAssertTrue(reply.needsForeground)
    }

    func testToggleWithdrawsAStartThatIsStillWaiting() async {
        // A first Back Tap is waiting for the ring (or continuing in R02); a
        // second one must cancel it, not queue another start.
        let fake = control { $0.link = .connecting; $0.startPending = true }
        let reply = await GestureIntentLogic.toggle(fake)
        XCTAssertEqual(fake.requests, [.init(enabled: false, source: .intent, timeout: 0)])
        XCTAssertEqual(reply.outcome, .startCancelled)
        XCTAssertEqual(reply.message, "Start cancelled. The ring stays in Health.")
        XCTAssertFalse(reply.needsForeground)
    }

    // MARK: Back Tap debounce and grace

    func testToggleRightAfterAStartRequestKeepsThePendingStart() async {
        // The same Back Tap firing twice, or a re-tap before any feedback.
        let fake = control { $0.link = .connecting; $0.startPending = true; $0.startPendingAge = 1.5 }
        let reply = await GestureIntentLogic.toggle(fake)
        XCTAssertEqual(fake.requests, [])
        XCTAssertEqual(reply.message, GestureIntentLogic.stillStartingMessage)
        XCTAssertFalse(reply.needsForeground)
        XCTAssertEqual(fake.intents, [["toggle", "kept_pending_start"]])
        XCTAssertEqual(GestureIntentLogic.pendingStartDebounce, 2)
    }

    func testToggleAfterTheDebounceStillWithdrawsAPendingStartOrContinuation() async {
        // A Shortcut's continuation can be pending for up to 35 s; Toggle must
        // still cancel it once the debounce has passed.
        for change in [{ (s: inout GestureModeSnapshot) in s.link = .connecting },
                       { (s: inout GestureModeSnapshot) in s.appActive = true }] {
            let fake = control { change(&$0); $0.startPending = true; $0.startPendingAge = 2.5 }
            let reply = await GestureIntentLogic.toggle(fake)
            XCTAssertEqual(fake.requests, [.init(enabled: false, source: .intent, timeout: 0)])
            XCTAssertEqual(reply.outcome, .startCancelled)
            XCTAssertEqual(fake.intents, [["toggle", "stop"]])
        }
    }

    func testToggleRightAfterASessionStartsKeepsIt() async {
        let fake = control { $0.mode = .gesture; $0.sessionAge = 2.4 }
        let reply = await GestureIntentLogic.toggle(fake)
        XCTAssertEqual(fake.requests, [])
        XCTAssertEqual(reply.outcome, .alreadyActive)
        XCTAssertEqual(reply.message, GestureIntentLogic.justStartedMessage)
        XCTAssertEqual(fake.intents, [["toggle", "kept_new_session"]])
    }

    func testToggleAfterTheGraceStopsTheSession() async {
        let fake = control { $0.mode = .gesture; $0.sessionAge = GestureIntentLogic.runningStopGrace }
        let reply = await GestureIntentLogic.toggle(fake)
        XCTAssertEqual(fake.requests.map(\.enabled), [false])
        XCTAssertEqual(reply.outcome, .stopped)
    }

    // MARK: What the debounce measures from

    func testOnlyTheRequestThatCreatesThePendingStartStampsIt() {
        var stamp = GestureStartStamp()
        XCTAssertNil(stamp.pendingAge(at: 5, pending: true))
        stamp.startRequested(at: 10, alreadyPending: false)
        XCTAssertEqual(stamp.pendingAge(at: 11, pending: true), 1)
        // A continuation's own request, or a Start that returns at once.
        stamp.startRequested(at: 30, alreadyPending: true)
        XCTAssertEqual(stamp.pendingAge(at: 31, pending: true), 21)
        XCTAssertNil(stamp.pendingAge(at: 31, pending: false))
        // The user's Continue tap always restarts it.
        stamp.userContinued(at: 40)
        XCTAssertEqual(stamp.pendingAge(at: 40.5, pending: true), 0.5)
        // A stop withdraws every start; a start right after it (before the
        // withdrawn one leaves the pending count) is stamped anew.
        stamp.stopRequested()
        XCTAssertNil(stamp.pendingAge(at: 41, pending: true))
        stamp.startRequested(at: 41, alreadyPending: true)
        XCTAssertEqual(stamp.pendingAge(at: 42, pending: true), 1)
    }

    func testAToggleAfterTheDebounceCancelsAContinuationEvenOnceItsOwnRequestFires() async {
        // Continue at 0; a sync holds the ring, so the continuation's own
        // request fires at ~20 s. A Toggle 1 s later is a deliberate cancel,
        // not the same Back Tap firing twice.
        let fake = StampedModeControl(health)
        fake.snapshot.ringBusy = true
        fake.userContinued()
        var toggled: GestureIntentReply?
        fake.whileStartPending = {
            fake.now += 1
            toggled = await GestureIntentLogic.toggle(fake)
        }
        let outcome = await GestureIntentLogic.startAfterForeground(fake, now: { fake.now }, sleep: { _ in
            fake.now += 0.1
            if fake.now >= 1 { fake.snapshot.appActive = true }
            if fake.now >= 20 { fake.snapshot.ringBusy = false }
        })
        XCTAssertEqual(fake.intents, [["toggle", "stop"]])
        XCTAssertEqual(toggled?.outcome, .startCancelled)
        XCTAssertEqual(outcome, .startCancelled)
        XCTAssertFalse(fake.pending)
    }

    func testAStartThatReturnsAtOnceDoesNotReArmTheDebounceForAnOlderStart() async {
        let fake = StampedModeControl(health)
        fake.userContinued()
        fake.now = 10
        _ = await fake.requestGestureSession(true, source: .app, readinessTimeout: 10)
        fake.now = 10.5
        let reply = await GestureIntentLogic.toggle(fake)
        XCTAssertEqual(fake.intents, [["toggle", "stop"]])
        XCTAssertEqual(reply.outcome, .startCancelled)
    }

    func testAToggleRightAfterTheContinueTapIsStillDebounced() async {
        let fake = StampedModeControl(health)
        fake.userContinued()
        fake.now = 1.5
        let reply = await GestureIntentLogic.toggle(fake)
        XCTAssertEqual(fake.intents, [["toggle", "kept_pending_start"]])
        XCTAssertEqual(reply.message, GestureIntentLogic.stillStartingMessage)
        XCTAssertTrue(fake.pending)
    }

    func testAnAutomaticEndIsTimedOnAClockThatRunsWhileThePhoneSleeps() {
        // Injected continuous time: overnight it moves although uptime barely does.
        let base = ContinuousClock.now
        var elapsed = Duration.zero
        var tracker = GestureModeSnapshot.AutomaticEndTracker(now: { base + elapsed })
        XCTAssertNil(tracker.recent)
        tracker.ended(.staleStream)
        elapsed = .seconds(125)
        XCTAssertEqual(tracker.recent?.reason, .staleStream)
        XCTAssertEqual(tracker.recent?.secondsAgo ?? -1, 125, accuracy: 1e-9)
        elapsed = .seconds(600)
        XCTAssertNotNil(tracker.recent, "the window includes ten minutes")
        elapsed = .seconds(700)
        XCTAssertNil(tracker.recent)
        tracker.ended(.renewal)
        XCTAssertEqual(tracker.recent?.secondsAgo ?? -1, 0, accuracy: 1e-9)
        tracker.clear()
        XCTAssertNil(tracker.recent)

        var live = GestureModeSnapshot.AutomaticEndTracker()
        live.ended(.idle)
        XCTAssertEqual(live.recent?.secondsAgo ?? -1, 0, accuracy: 1)
    }

    func testPauseStopsAtOnceInEveryState() async {
        let states: [(inout GestureModeSnapshot) -> Void] = [
            { $0.mode = .gesture; $0.sessionAge = 0.2 },
            { $0.link = .connecting; $0.startPending = true; $0.startPendingAge = 0.2 },
        ]
        for change in states {
            let fake = control(change)
            _ = await GestureIntentLogic.stop(fake)
            XCTAssertEqual(fake.requests, [.init(enabled: false, source: .intent, timeout: 0)])
            XCTAssertEqual(fake.intents, [["stop", "stop"]])
        }
    }

    func testAStartAfterAnAutomaticEndSaysTheLastSessionStopped() async {
        let ended = GestureModeSnapshot.AutomaticEnd(reason: .staleStream, secondsAgo: 12.4)
        XCTAssertEqual(ended.note, "Gestures had stopped 12 s ago (motion stream went stale).")
        for toggle in [true, false] {
            let fake = control { $0.recentAutomaticEnd = ended }
            let reply: GestureIntentReply
            if toggle { reply = await GestureIntentLogic.toggle(fake) } else { reply = await GestureIntentLogic.start(fake) }
            XCTAssertEqual(reply.outcome, .started)
            XCTAssertTrue(reply.message.hasPrefix(ended.note), reply.message)
            XCTAssertTrue(reply.message.contains("Gesture session started."), reply.message)
            XCTAssertEqual(fake.intents, [[toggle ? "toggle" : "start", "start"]])
        }
        XCTAssertEqual(GestureModeSnapshot.AutomaticEnd(reason: .renewal, secondsAgo: 125).note,
                       "Gestures had stopped 2 min ago (lease renewal failed).")
    }

    func testPauseDuringAPendingStartSaysTheStartWasCancelled() async {
        let reply = await GestureIntentLogic.stop(control { $0.link = .connecting; $0.startPending = true })
        XCTAssertEqual(reply.outcome, .startCancelled)
        XCTAssertNotEqual(reply.message, GestureRequestOutcome.alreadyStopped.message)
    }

    func testToggleWithNoRingAsksToContinueInR02() async {
        for link in [GestureModeSnapshot.Link.bluetoothOff, .unpaired, .recoveryOnly, .connecting] {
            let reply = await GestureIntentLogic.toggle(control { $0.link = link })
            XCTAssertEqual(reply.outcome, .notConnected, link.rawValue)
            XCTAssertTrue(reply.needsForeground, link.rawValue)
            XCTAssertTrue(reply.message.contains("Continue in R02"), link.rawValue)
        }
    }

    // MARK: Start

    func testStartUsesTheTenSecondReadinessTimeout() async {
        XCTAssertEqual(GestureIntentLogic.readinessTimeout, 10)
        let fake = control()
        _ = await GestureIntentLogic.start(fake)
        XCTAssertEqual(fake.requests, [.init(enabled: true, source: .intent, timeout: 10)])
    }

    func testStartOutcomesInTheBackground() {
        let foreground: Set<String> = ["not_connected", "needs_foreground", "timed_out"]
        for outcome in allOutcomes {
            let reply = GestureIntentLogic.startReply(outcome, appActive: false)
            XCTAssertEqual(reply.outcome, outcome)
            XCTAssertEqual(reply.needsForeground, foreground.contains(outcome.journalName), outcome.journalName)
            XCTAssertFalse(reply.message.isEmpty, outcome.journalName)
            if reply.needsForeground {
                XCTAssertTrue(reply.message.contains("Continue in R02"), outcome.journalName)
            } else if outcome != .started {
                XCTAssertEqual(reply.message, outcome.message, outcome.journalName)
            }
        }
    }

    func testStartWithR02InFrontNeverAsksToContinue() {
        for outcome in allOutcomes {
            let reply = GestureIntentLogic.startReply(outcome, appActive: true)
            XCTAssertFalse(reply.needsForeground, outcome.journalName)
            if outcome != .started { XCTAssertEqual(reply.message, outcome.message, outcome.journalName) }
        }
    }

    func testStartedReplyNamesTheCalibration() {
        let reply = GestureIntentLogic.startReply(.started, appActive: false)
        XCTAssertTrue(reply.message.hasPrefix(GestureRequestOutcome.started.message))
        XCTAssertTrue(reply.message.contains("fingers down"))
    }

    func testRefusalsThatR02CannotFixDoNotAskForTheForeground() async {
        let cases: [(GestureRequestOutcome, (inout GestureModeSnapshot) -> Void)] = [
            (.charging, { $0.charging = true }),
            (.busy, { $0.ringBusy = true }),
            (.busy, { $0.firmwareSwitching = true }),
            (.unavailable, { $0.modeControlAvailable = false }),
            (.unavailable, { $0.unifiedFirmwareInstalled = false }),
        ]
        for (expected, change) in cases {
            let reply = await GestureIntentLogic.start(control(change))
            XCTAssertEqual(reply.outcome, expected)
            XCTAssertFalse(reply.needsForeground, expected.journalName)
            XCTAssertEqual(reply.message, expected.message)
        }
    }

    func testBackgroundSettingOff() async {
        // In the background the start is refused and R02 is asked for.
        let background = control { $0.keepGesturesInBackground = false }
        let refused = await GestureIntentLogic.start(background)
        XCTAssertEqual(refused.outcome, .needsForeground)
        XCTAssertTrue(refused.needsForeground)
        XCTAssertTrue(refused.message.contains("Keep gestures active in background"))

        // With R02 in front the same setting does not matter.
        let front = control { $0.keepGesturesInBackground = false; $0.appActive = true }
        let started = await GestureIntentLogic.start(front)
        XCTAssertEqual(started.outcome, .started)
        XCTAssertFalse(started.needsForeground)

        // With the setting on, a background start needs nothing from the user.
        let on = await GestureIntentLogic.start(control())
        XCTAssertEqual(on.outcome, .started)
        XCTAssertFalse(on.needsForeground)
    }

    func testForegroundIsJudgedAfterTheWait() async {
        // The user opened R02 while the start was waiting for the ring.
        let fake = control { $0.link = .connecting }
        fake.onRequest = { $0.gestureModeSnapshot.appActive = true }
        fake.forcedOutcome = .notConnected
        let reply = await GestureIntentLogic.start(fake)
        XCTAssertFalse(reply.needsForeground)
        XCTAssertEqual(reply.message, GestureRequestOutcome.notConnected.message)
    }

    // MARK: Stop

    func testStopNeverNeedsTheForeground() async {
        let snapshots: [(inout GestureModeSnapshot) -> Void] = [
            { _ in }, { $0.mode = .gesture }, { $0.transition = .entering }, { $0.link = .bluetoothOff },
            { $0.mode = .gesture; $0.keepGesturesInBackground = false },
            { $0.mode = .gesture; $0.appActive = true },
        ]
        for change in snapshots {
            let fake = control(change)
            let reply = await GestureIntentLogic.stop(fake)
            XCTAssertEqual(fake.requests.map(\.enabled), [false])
            XCTAssertEqual(fake.requests.first?.source, .intent)
            XCTAssertEqual(fake.requests.first?.timeout, 0)
            XCTAssertFalse(reply.needsForeground)
        }
        for outcome in allOutcomes {
            let fake = control { $0.mode = .gesture }
            fake.forcedOutcome = outcome
            let reply = await GestureIntentLogic.stop(fake)
            XCTAssertEqual(reply.outcome, outcome)
            XCTAssertEqual(reply.message, outcome.message)
            XCTAssertFalse(reply.needsForeground, outcome.journalName)
        }
    }

    // MARK: Foreground continuation

    func testStartAfterForegroundWaitsForTheSceneThenUsesTheLongerTimeout() async {
        var now = 0.0
        let fake = control { $0.keepGesturesInBackground = false }
        var sleeps = 0
        let outcome = await GestureIntentLogic.startAfterForeground(
            fake, now: { now },
            sleep: { _ in
                sleeps += 1
                now += 0.1
                if sleeps == 3 { fake.gestureModeSnapshot.appActive = true }
            }
        )
        XCTAssertEqual(sleeps, 3)
        XCTAssertEqual(outcome, .started)
        XCTAssertEqual(fake.requests, [.init(enabled: true, source: .intent,
                                              timeout: GestureIntentLogic.foregroundReadinessTimeout)])
        XCTAssertGreaterThan(GestureIntentLogic.foregroundReadinessTimeout, GestureIntentLogic.readinessTimeout)
    }

    func testStartAfterForegroundStillRequestsWhenActivationIsLate() async {
        var now = 0.0
        let fake = control { $0.keepGesturesInBackground = false }
        let outcome = await GestureIntentLogic.startAfterForeground(
            fake, activationTimeout: 5, now: { now }, sleep: { _ in now += 0.1 }
        )
        XCTAssertEqual(outcome, .needsForeground)
        XCTAssertEqual(fake.requests.count, 1)
        XCTAssertGreaterThanOrEqual(now, 5)
        XCTAssertLessThan(now, 5.2)
    }

    func testStartAfterForegroundWaitsOutASyncThatActivationStarted() async {
        // Scene activation ran before the continuation and began a history import.
        var now = 0.0
        var polls = 0
        let fake = control { $0.appActive = true; $0.ringBusy = true }
        let outcome = await GestureIntentLogic.startAfterForeground(
            fake, now: { now },
            sleep: { _ in
                polls += 1
                now += 0.1
                if polls == 40 { fake.gestureModeSnapshot.ringBusy = false } // the import finished after 4 s
            }
        )
        XCTAssertEqual(outcome, .started, "not refused as busy")
        XCTAssertEqual(fake.requests.count, 1)
        let timeout = try? XCTUnwrap(fake.requests.first?.timeout)
        XCTAssertEqual(timeout ?? 0, GestureIntentLogic.foregroundReadinessTimeout - 4, accuracy: 1e-6,
                       "the busy wait comes out of the same 30 s budget")
    }

    func testStartAfterForegroundReportsBusyWhenTheSyncOutlastsTheBudget() async {
        var now = 0.0
        let fake = control { $0.appActive = true; $0.ringBusy = true }
        let outcome = await GestureIntentLogic.startAfterForeground(fake, now: { now }, sleep: { _ in now += 0.5 })
        XCTAssertEqual(outcome, .busy)
        XCTAssertEqual(fake.requests.map(\.timeout), [0])
    }

    func testContinuationMessagesSuitR02BeingInFront() {
        let notConnected = GestureIntentLogic.continuationMessage(.notConnected)
        XCTAssertTrue(notConnected.contains("within 30 seconds"))
        XCTAssertFalse(notConnected.contains("Open R02"), "R02 is already open")
        XCTAssertTrue(GestureIntentLogic.continuationMessage(.timedOut).contains("Tap Start"))
        XCTAssertEqual(GestureIntentLogic.continuationMessage(.charging),
                       "No session started: \(GestureRequestOutcome.charging.message)")
        XCTAssertEqual(GestureIntentLogic.continuationMessage(.busy),
                       "No session started: \(GestureRequestOutcome.busy.message)")
    }

    func testCancelledContinuationDoesNotStart() async {
        let fake = control()
        let task = Task { @MainActor in
            await GestureIntentLogic.startAfterForeground(fake, now: { 0 }, sleep: { _ in
                throw CancellationError()
            })
        }
        task.cancel()
        let outcome = await task.value
        XCTAssertNil(outcome)
        XCTAssertTrue(fake.requests.isEmpty)
    }

    // MARK: waitUntil

    func testWaitUntilReturnsOnceTheConditionHolds() async {
        var now = 0.0
        var checks = 0
        var sleeps: [Duration] = []
        let held = await GestureIntentLogic.waitUntil(
            timeout: 5, now: { now }, sleep: { sleeps.append($0); now += 0.1 }
        ) {
            checks += 1
            return checks == 4
        }
        XCTAssertTrue(held)
        XCTAssertEqual(sleeps, Array(repeating: .milliseconds(100), count: 3))
    }

    func testWaitUntilDoesNotSleepWhenAlreadyTrue() async {
        var slept = false
        let held = await GestureIntentLogic.waitUntil(timeout: 5, now: { 0 }, sleep: { _ in slept = true }) { true }
        XCTAssertTrue(held)
        XCTAssertFalse(slept)
    }

    func testWaitUntilTimesOutOnTheInjectedClock() async {
        var now = 50.0
        var checks = 0
        let held = await GestureIntentLogic.waitUntil(
            timeout: 2, poll: .milliseconds(250), now: { now }, sleep: { _ in now += 0.25 }
        ) {
            checks += 1
            return false
        }
        XCTAssertFalse(held)
        XCTAssertEqual(now - 50, 2, accuracy: 1e-9)
        XCTAssertEqual(checks, 9)
    }

    func testWaitUntilZeroTimeoutChecksOnce() async {
        var checks = 0
        let held = await GestureIntentLogic.waitUntil(timeout: 0, now: { 0 }, sleep: { _ in XCTFail("slept") }) {
            checks += 1
            return false
        }
        XCTAssertFalse(held)
        XCTAssertEqual(checks, 1)
    }

    func testCancelledWaitUntilStopsImmediately() async {
        var checks = 0
        let held = await GestureIntentLogic.waitUntil(timeout: 5, now: { 0 }, sleep: { _ in
            throw CancellationError()
        }) {
            checks += 1
            return false
        }
        XCTAssertFalse(held)
        XCTAssertEqual(checks, 2)
    }

    // MARK: Intent surface

    func testIntentTitlesMatchTheBackTapGuide() {
        XCTAssertEqual(String(localized: ToggleGestureSessionIntent.title), "Toggle Gesture Session")
        XCTAssertEqual(String(localized: StartGestureSessionIntent.title), "Start Gesture Session")
        XCTAssertEqual(String(localized: StopGestureSessionIntent.title), "Pause Gestures (Return to Health)")
        XCTAssertNotNil(ToggleGestureSessionIntent.description)
        XCTAssertNotNil(StartGestureSessionIntent.description)
        XCTAssertNotNil(StopGestureSessionIntent.description)
        XCTAssertFalse(StopGestureSessionIntent.openAppWhenRun)
        XCTAssertEqual(R02Shortcuts.appShortcuts.count, 3)
    }
}
