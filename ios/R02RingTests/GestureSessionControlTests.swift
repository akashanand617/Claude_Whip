import XCTest
@testable import R02Ring

@MainActor
final class GestureSessionControlTests: XCTestCase {
    private let ready = GestureModeSnapshot(
        link: .ready, connectionSetupComplete: true, unifiedFirmwareInstalled: true,
        modeAttachInFlight: false, modeControlAvailable: true, mode: .health, charging: false,
        transition: nil, ringBusy: false, firmwareSwitching: false, appActive: false,
        keepGesturesInBackground: true
    )

    private func readiness(_ change: (inout GestureModeSnapshot) -> Void) -> GestureStartReadiness {
        var snapshot = ready
        change(&snapshot)
        return .evaluate(snapshot)
    }

    func testReadyInTheBackgroundWhenBackgroundSessionsAreOn() {
        XCTAssertEqual(GestureStartReadiness.evaluate(ready), .ready)
        XCTAssertFalse(ready.gestureActive)
        XCTAssertTrue(ready.isConnected)
        XCTAssertEqual(readiness { $0.keepGesturesInBackground = false; $0.appActive = true }, .ready)
    }

    func testEachStateMapsToItsReadiness() {
        let cases: [(GestureStartReadiness, (inout GestureModeSnapshot) -> Void)] = [
            (.alreadyActive, { $0.mode = .gesture }),
            (.alreadyActive, { $0.mode = .enteringGesture }),
            (.alreadyActive, { $0.transition = .entering }),
            (.returning, { $0.transition = .leaving }),
            // What the model actually publishes while a stop runs: the coordinator
            // still reports Gesture until the stop completes.
            (.returning, { $0.mode = .gesture; $0.transition = .leaving }),
            (.returning, { $0.mode = .returningHealth }),
            (.needsForeground, { $0.keepGesturesInBackground = false }),
            (.notConnected, { $0.link = .bluetoothOff }),
            (.notConnected, { $0.link = .unpaired }),
            (.notConnected, { $0.link = .recoveryOnly }),
            (.connecting, { $0.link = .connecting }),
            (.identifying, { $0.connectionSetupComplete = false }),
            (.attaching, { $0.modeAttachInFlight = true }),
            (.busy, { $0.firmwareSwitching = true }),
            (.unavailable, { $0.unifiedFirmwareInstalled = false }),
            (.unavailable, { $0.modeControlAvailable = false }),
            (.unavailable, { $0.mode = nil }),
            (.unavailable, { $0.mode = .fault }),
            (.charging, { $0.charging = true }),
            (.busy, { $0.ringBusy = true }),
        ]
        for (expected, change) in cases {
            XCTAssertEqual(readiness(change), expected)
        }
    }

    func testAStopInFlightIsNotAnActiveSession() {
        var stopping = ready
        stopping.mode = .gesture
        stopping.transition = .leaving
        XCTAssertFalse(stopping.gestureActive, "a Start waits for the return instead of answering 'already running'")
        XCTAssertTrue(GestureStartReadiness.evaluate(stopping).isWaiting)
        stopping.transition = nil
        XCTAssertTrue(stopping.gestureActive)
        stopping.transition = .entering
        stopping.mode = .health
        XCTAssertTrue(stopping.gestureActive)
    }

    func testAPendingStartIsNotItselfActive() {
        // The waiting start reads this snapshot; it must not see itself as running.
        var pending = ready
        pending.startPending = true
        XCTAssertFalse(pending.gestureActive)
        XCTAssertEqual(GestureStartReadiness.evaluate(pending), .ready)
        pending.link = .connecting
        XCTAssertEqual(GestureStartReadiness.evaluate(pending), .connecting)
    }

    func testUnavailableReasonNamesTheActualCause() {
        func reason(_ change: (inout GestureModeSnapshot) -> Void) -> String {
            var snapshot = ready
            change(&snapshot)
            return snapshot.unavailableReason
        }
        let firmware = "Gesture sessions need the verified unified image. Firmware maintenance is under Settings."
        XCTAssertEqual(reason { $0.link = .bluetoothOff }, "Bluetooth isn't available · check it's on and allowed for R02.")
        XCTAssertEqual(reason { $0.link = .unpaired }, "No ring paired yet.")
        XCTAssertTrue(reason { $0.link = .recoveryOnly }.contains("recovery"))
        XCTAssertEqual(reason { $0.link = .connecting; $0.unifiedFirmwareInstalled = false },
                       "Ring not connected · R02 reconnects when it's in range.")
        XCTAssertEqual(reason { $0.connectionSetupComplete = false; $0.unifiedFirmwareInstalled = false },
                       "Checking ring firmware…")
        XCTAssertEqual(reason { $0.unifiedFirmwareInstalled = false }, firmware)
        XCTAssertEqual(reason { $0.modeControlAvailable = false; $0.modeAttachInFlight = true },
                       "Preparing gesture control…")
        XCTAssertEqual(reason { $0.modeControlAvailable = false; $0.mode = nil },
                       "Gesture control unavailable · reconnect the ring to recover.")
        XCTAssertEqual(reason { $0.mode = .fault }, "Gesture control unavailable · reconnect the ring to recover.")
        // Only an identified, non-unified ring is sent to firmware maintenance.
        for link in [GestureModeSnapshot.Link.bluetoothOff, .unpaired, .recoveryOnly, .connecting] {
            XCTAssertNotEqual(reason { $0.link = link; $0.unifiedFirmwareInstalled = false }, firmware, link.rawValue)
        }
    }

    func testWaitingNotes() {
        XCTAssertEqual(GestureStartReadiness.connecting.waitingNote, "Starting · waiting for the ring to connect")
        XCTAssertEqual(GestureStartReadiness.identifying.waitingNote, "Starting · checking ring firmware")
        XCTAssertEqual(GestureStartReadiness.attaching.waitingNote, "Starting · preparing gesture control")
        XCTAssertEqual(GestureStartReadiness.returning.waitingNote, "Starting · waiting for the return to Health")
        XCTAssertEqual(GestureStartReadiness.ready.waitingNote, "Starting…")
    }

    func testBackgroundSessionsDefaultOnAndPersist() {
        let suite = UUID().uuidString
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        XCTAssertEqual(GestureBackgroundSessions.storageKey, "gestureKeepActiveInBackground")
        XCTAssertTrue(GestureBackgroundSessions.stored(in: defaults), "a missing key means ON")
        GestureBackgroundSessions.store(false, in: defaults)
        XCTAssertFalse(GestureBackgroundSessions.stored(in: defaults))
        GestureBackgroundSessions.store(true, in: defaults)
        XCTAssertTrue(GestureBackgroundSessions.stored(in: defaults))
        defaults.set("no", forKey: GestureBackgroundSessions.storageKey)
        XCTAssertTrue(GestureBackgroundSessions.stored(in: defaults), "garbage falls back to the default")
    }

    // MARK: Idle pause wait

    func testIdleWaitExpiresAtTheDeadlineAndActivityPostponesIt() async {
        var now = 0.0
        var tracker = GestureIdleTracker(policy: .fiveMinutes)
        tracker.start(at: 0)
        var sleeps: [Double] = []
        let expired = await GestureIdleTracker.sleepUntilExpired(
            remaining: { tracker.remaining(at: now) },
            sleep: { duration in
                let seconds = Double(duration.components.seconds)
                    + Double(duration.components.attoseconds) / 1e18
                sleeps.append(seconds)
                now += seconds
                if sleeps.count == 1 { tracker.activity(at: 200) } // a gesture during the first sleep
            }
        )
        XCTAssertTrue(expired)
        XCTAssertEqual(sleeps.count, 2)
        XCTAssertEqual(sleeps[0], 300, accuracy: 1e-9)
        XCTAssertEqual(sleeps[1], 200, accuracy: 1e-9, "the deadline moved to 200 + 300")
        XCTAssertTrue(tracker.isExpired(at: now))
    }

    func testIdleWaitEndsWithoutExpiringWhenStoppedOrCancelled() async {
        var tracker = GestureIdleTracker(policy: .fifteenMinutes)
        tracker.start(at: 0)
        let stopped = await GestureIdleTracker.sleepUntilExpired(
            remaining: { tracker.remaining(at: 10) }, sleep: { _ in tracker.stop() }
        )
        XCTAssertFalse(stopped)
        tracker.start(at: 0)
        let cancelled = await GestureIdleTracker.sleepUntilExpired(
            remaining: { tracker.remaining(at: 10) }, sleep: { _ in throw CancellationError() }
        )
        XCTAssertFalse(cancelled)
        tracker.policy = .off
        let off = await GestureIdleTracker.sleepUntilExpired(remaining: { tracker.remaining(at: 10) },
                                                             sleep: { _ in XCTFail("slept with idle pause off") })
        XCTAssertFalse(off)
    }

    func testRuleOrder() {
        // An active session answers before anything about the link.
        XCTAssertEqual(readiness { $0.mode = .gesture; $0.link = .bluetoothOff }, .alreadyActive)
        // Foreground is asked for before waiting on a reconnect.
        XCTAssertEqual(readiness { $0.keepGesturesInBackground = false; $0.link = .connecting }, .needsForeground)
        // A connecting link has no meaningful setup, attach or firmware state yet.
        XCTAssertEqual(readiness { $0.link = .connecting; $0.connectionSetupComplete = false;
                                   $0.unifiedFirmwareInstalled = false }, .connecting)
        // Identification finishes before availability is judged.
        XCTAssertEqual(readiness { $0.connectionSetupComplete = false; $0.modeControlAvailable = false },
                       .identifying)
        // A scheduled recovery is waited for, not reported as unavailable.
        XCTAssertEqual(readiness { $0.modeAttachInFlight = true; $0.modeControlAvailable = false }, .attaching)
        XCTAssertEqual(readiness { $0.charging = true; $0.ringBusy = true }, .charging)
    }

    func testWaitingStatesAndOutcomes() {
        let waiting: Set<GestureStartReadiness> = [.connecting, .identifying, .attaching, .returning]
        let expected: [GestureStartReadiness: GestureRequestOutcome?] = [
            .ready: nil, .alreadyActive: .alreadyActive, .connecting: .notConnected,
            .identifying: .timedOut, .attaching: .timedOut, .returning: .timedOut,
            .needsForeground: .needsForeground, .notConnected: .notConnected,
            .unavailable: .unavailable, .charging: .charging, .busy: .busy,
            .cancelled: .startCancelled,
        ]
        let all: [GestureStartReadiness] = [.ready, .alreadyActive, .connecting, .identifying, .attaching,
                                            .returning, .needsForeground, .notConnected, .unavailable,
                                            .charging, .busy, .cancelled]
        XCTAssertEqual(Set(expected.keys), Set(all))
        for readiness in all {
            XCTAssertEqual(readiness.isWaiting, waiting.contains(readiness), readiness.rawValue)
            XCTAssertEqual(readiness.outcome, expected[readiness]!, readiness.rawValue)
        }
    }

    func testWaitReturnsAsSoonAsReadinessIsFinal() async {
        var now = 0.0
        var sequence: [GestureStartReadiness] = [.connecting, .identifying, .attaching, .ready]
        var sleeps: [Duration] = []
        let result = await GestureStartReadiness.wait(
            timeout: 10, now: { now },
            sleep: { sleeps.append($0); now += 0.1 },
            evaluate: { sequence.removeFirst() }
        )
        XCTAssertEqual(result.readiness, .ready)
        XCTAssertEqual(result.waited, 0.3, accuracy: 1e-9)
        XCTAssertEqual(sleeps, Array(repeating: .milliseconds(100), count: 3))
    }

    func testWaitDoesNotSleepForAFinalState() async {
        var slept = false
        let result = await GestureStartReadiness.wait(
            timeout: 10, now: { 5 }, sleep: { _ in slept = true }, evaluate: { .charging }
        )
        XCTAssertEqual(result.readiness, .charging)
        XCTAssertEqual(result.waited, 0)
        XCTAssertFalse(slept)
    }

    func testWaitTimesOutOnTheInjectedClock() async {
        var now = 100.0
        var evaluations = 0
        let result = await GestureStartReadiness.wait(
            timeout: 10, now: { now }, sleep: { _ in now += 0.1 },
            evaluate: { evaluations += 1; return .connecting }
        )
        XCTAssertEqual(result.readiness, .connecting)
        XCTAssertGreaterThanOrEqual(result.waited, 10)
        XCTAssertLessThan(result.waited, 10.2)
        XCTAssertEqual(result.readiness.outcome, .notConnected)
        XCTAssertLessThanOrEqual(evaluations, 102)
    }

    func testCancelledWaitStopsImmediately() async {
        var evaluations = 0
        let result = await GestureStartReadiness.wait(
            timeout: 10, now: { 0 }, sleep: { _ in throw CancellationError() },
            evaluate: { evaluations += 1; return .identifying }
        )
        XCTAssertEqual(result.readiness, .identifying)
        XCTAssertEqual(evaluations, 1)
        XCTAssertEqual(result.readiness.outcome, .timedOut)
    }

    func testErrorsMapToRequestOutcomes() {
        XCTAssertEqual(GestureRequestOutcome(error: FirmwareSwitchError.charging), .charging)
        XCTAssertEqual(GestureRequestOutcome(error: RingProtocolError.busy), .busy)
        XCTAssertEqual(GestureRequestOutcome(error: RingProtocolError.notReady), .notConnected)
        XCTAssertEqual(GestureRequestOutcome(error: UnifiedModeError.unavailable), .unavailable)
        XCTAssertEqual(GestureRequestOutcome(error: UnifiedModeError.staleStream),
                       .failed(UnifiedModeError.staleStream.localizedDescription))
        XCTAssertEqual(GestureRequestOutcome(error: RingProtocolError.timeout),
                       .failed(RingProtocolError.timeout.localizedDescription))
        XCTAssertEqual(GestureRequestOutcome(error: FirmwareSwitchError.batteryTooLow(10)),
                       .failed(FirmwareSwitchError.batteryTooLow(10).localizedDescription))
    }

    func testOutcomeSuccessNamesAndMessages() {
        let all: [GestureRequestOutcome] = [.started, .stopped, .alreadyActive, .alreadyStopped,
                                            .needsForeground, .unavailable, .charging, .busy,
                                            .notConnected, .timedOut, .startCancelled, .failed("boom")]
        XCTAssertEqual(all.filter(\.succeeded), [.started, .stopped, .alreadyActive, .alreadyStopped,
                                                 .startCancelled])
        XCTAssertEqual(GestureRequestOutcome.startCancelled.journalName, "start_cancelled")
        XCTAssertEqual(GestureRequestOutcome.startCancelled.message, "Start cancelled. The ring stays in Health.")
        XCTAssertEqual(Set(all.map(\.journalName)).count, all.count)
        XCTAssertTrue(all.allSatisfy { !$0.message.isEmpty })
        XCTAssertEqual(GestureRequestOutcome.failed("boom").message, "boom")
    }

    func testSourcesMapToReasons() {
        XCTAssertEqual(GestureRequestSource.app.reason, .user)
        XCTAssertEqual(GestureRequestSource.intent.reason, .intent)
        XCTAssertEqual(Set(GestureSessionReason.allCases.map(\.rawValue)).count, GestureSessionReason.allCases.count)
        let required: [GestureSessionReason] = [.intent, .gestureAction, .autoReturn, .idle, .backgrounded,
                                                .staleStream, .renewal]
        XCTAssertTrue(required.allSatisfy { !$0.endTitle.isEmpty })
    }

    func testSessionSummaryText() {
        XCTAssertEqual(GestureSessionSummary.text(duration: 42.4, recognized: 1, performed: 1, reason: .idle),
                       "Last session 42 s · 1 gesture, 1 action · idle pause")
        XCTAssertEqual(GestureSessionSummary.text(duration: 252, recognized: 7, performed: 5,
                                                  reason: .gestureAction),
                       "Last session 4 min 12 s · 7 gestures, 5 actions · paused by gesture")
        XCTAssertEqual(GestureSessionSummary.text(duration: 3_725, recognized: 0, performed: 0,
                                                  reason: .disconnected),
                       "Last session 1 h 2 min · 0 gestures, 0 actions · ring disconnected")
        XCTAssertEqual(GestureSessionSummary.text(duration: -.infinity, recognized: 0, performed: 0, reason: .user),
                       "Last session 0 s · 0 gestures, 0 actions · stopped in R02")
    }
}
