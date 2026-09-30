import XCTest
@testable import R02Ring

@MainActor
private final class CountingNotifications: NotificationPosting {
    var authorization: PermissionState = .authorized
    var posts: [(title: String, body: String)] = []
    func refreshAuthorization() async -> PermissionState { authorization }
    func requestAuthorization() async -> PermissionState { authorization }
    func post(title: String, body: String) -> GestureActionOutcome { post(title: title, body: body, identifier: "") }
    func post(title: String, body: String, identifier: String) -> GestureActionOutcome {
        posts.append((title, body))
        return .performed
    }
    func schedule(title: String, body: String, identifier: String, after seconds: Double) -> Bool { true }
    func cancel(identifier: String) {}
}

/// A control whose start succeeds and whose calibration wait runs the real
/// `GestureCalibrationWaiter` (the one `AppModel.awaitCalibration` uses) and
/// ready announcer, on a fake clock with a scripted session.
@MainActor
private final class CalibratingControl: GestureModeControlling {
    var gestureModeSnapshot: GestureModeSnapshot
    var clock = 0.0
    /// Seconds the start request itself takes (readiness and entry).
    var requestTakes = 1.0
    var startOutcome: GestureRequestOutcome = .started
    /// When calibration completes, on `clock`; nil never.
    var calibratesAt: Double?
    /// A heal is running (with the link up unless `waitingForLink`).
    var healing = false
    var waitingForLink = false
    var endsAt: Double?
    /// The start this intent joined is still entering (desire arming) until then.
    var armingUntil: Double?
    /// The desire never turned on: it went back to off at `endsAt`.
    var neverOn = false
    /// Runs once, at the wait's first poll.
    var onWaitStarted: ((CalibratingControl) -> Void)?
    var requests: [(enabled: Bool, timeout: TimeInterval)] = []
    var waits: [TimeInterval] = []
    var replies: [GestureCalibrationWait] = []
    var intents: [String] = []
    let notifications = CountingNotifications()
    lazy var announcer = GestureReadyAnnouncer(notifications: notifications, now: { [unowned self] in self.clock })

    init(_ snapshot: GestureModeSnapshot) { gestureModeSnapshot = snapshot }

    func requestGestureSession(_ enabled: Bool, source: GestureRequestSource,
                               readinessTimeout: TimeInterval) async -> GestureRequestOutcome {
        requests.append((enabled, readinessTimeout))
        guard enabled else { return .stopped }
        clock += requestTakes
        return startOutcome
    }

    func noteIntent(_ kind: String, decision: String) { intents.append(decision) }

    private var ended: Bool { endsAt.map { clock >= $0 } ?? false }
    private var arming: Bool { !ended && (neverOn || (armingUntil.map { clock < $0 } ?? false)) }

    func awaitCalibration(timeout: TimeInterval) async -> GestureCalibrationWait {
        waits.append(timeout)
        let began = clock
        let waiter = GestureCalibrationWaiter(
            probes: .init(
                epoch: { 1 },
                isOn: { [unowned self] in !self.ended && !self.arming },
                isArming: { [unowned self] in self.arming },
                ready: { [unowned self] in self.calibratesAt.map { self.clock >= $0 } ?? false },
                healing: { [unowned self] in self.healing },
                waitingForLink: { [unowned self] in self.healing && self.waitingForLink }
            ),
            announcer: announcer, now: { [unowned self] in self.clock },
            sleep: { [unowned self] _ in
                if let hook = self.onWaitStarted { self.onWaitStarted = nil; hook(self) }
                self.clock += 0.1
            }
        )
        let result = await waiter.wait(timeout: timeout)
        replies.append(result)
        XCTAssertLessThanOrEqual(clock - began, timeout + 0.1 + 1e-9)
        return result
    }
}

@MainActor
final class GestureIntentCalibrationTests: XCTestCase {
    private let health = GestureModeSnapshot(
        link: .ready, connectionSetupComplete: true, unifiedFirmwareInstalled: true,
        modeAttachInFlight: false, modeControlAvailable: true, mode: .health, charging: false,
        transition: nil, ringBusy: false, firmwareSwitching: false, appActive: false,
        keepGesturesInBackground: true
    )

    private func control(_ change: (inout GestureModeSnapshot) -> Void = { _ in }) -> CalibratingControl {
        var snapshot = health
        change(&snapshot)
        return CalibratingControl(snapshot)
    }

    func testCalibratedWithinTheBudgetRepliesReady() async {
        let fake = control()
        fake.calibratesAt = 4
        let reply = await GestureIntentLogic.start(fake, now: { fake.clock })
        XCTAssertEqual(reply.message, "Gestures ready ✓")
        XCTAssertEqual(reply.outcome, .started)
        XCTAssertFalse(reply.needsForeground)
        XCTAssertEqual(fake.waits, [7], "8 s in all, 1 s of it spent starting")
        XCTAssertEqual(fake.replies, [.calibrated])
        XCTAssertLessThan(fake.clock, 4.2, "replied as soon as calibration completed")
    }

    func testNotCalibratedByTheBudgetRepliesAtItAndNotifiesLater() async {
        let fake = control()
        fake.calibratesAt = 20
        let reply = await GestureIntentLogic.toggle(fake, now: { fake.clock })
        XCTAssertEqual(reply.message, "Gestures on — hold fingers down to finish calibrating")
        XCTAssertEqual(fake.replies, [.pending], "the model arms the one notification with this reply")
        XCTAssertEqual(fake.clock, 8, accuracy: 0.15, "exactly the 8 s budget")
    }

    func testReadinessThatUsedTheBudgetLeavesNoCalibrationWait() async {
        let fake = control()
        fake.requestTakes = 9
        fake.calibratesAt = 9.5
        let reply = await GestureIntentLogic.start(fake, now: { fake.clock })
        XCTAssertEqual(fake.waits, [0])
        XCTAssertEqual(reply.message, GestureIntentLogic.calibratingMessage)
        XCTAssertLessThanOrEqual(fake.clock, 9.1)
    }

    func testAHealWaitingForTheLinkRepliesReconnectingAtOnce() async {
        let fake = control { $0.gestureDesired = true; $0.healing = true; $0.sessionAge = 60 }
        fake.healing = true
        fake.waitingForLink = true
        fake.startOutcome = .alreadyActive
        let reply = await GestureIntentLogic.start(fake, now: { fake.clock })
        XCTAssertEqual(reply.message, "Gestures on — reconnecting to the ring")
        XCTAssertEqual(reply.outcome, .alreadyActive)
        XCTAssertEqual(fake.clock, 1, accuracy: 1e-9, "no wait on a link that is down")
        XCTAssertTrue(fake.announcer.isArmed, "the ready notification follows the reconnect")
    }

    func testAHealWithTheLinkUpIsWaitedOut() async {
        let fake = control { $0.gestureDesired = true; $0.healing = true; $0.sessionAge = 60 }
        fake.healing = true
        fake.startOutcome = .alreadyActive
        let reply = await GestureIntentLogic.start(fake, now: { fake.clock })
        XCTAssertEqual(reply.message, GestureIntentLogic.reconnectingMessage)
        XCTAssertEqual(fake.clock, 8, accuracy: 0.15, "the heal may resume and calibrate in time")

        let resumes = control { $0.gestureDesired = true; $0.healing = true; $0.sessionAge = 60 }
        resumes.healing = true
        resumes.startOutcome = .alreadyActive
        resumes.calibratesAt = 5
        let ready = await GestureIntentLogic.start(resumes, now: { resumes.clock })
        XCTAssertEqual(ready.message, GestureIntentLogic.readyMessage)
    }

    func testAHealDuringTheWaitIsAnnouncedOnceByTheDialog() async {
        let fake = control()
        fake.calibratesAt = 5
        fake.onWaitStarted = { fake in
            // A recalibrating heal lands inside the wait, R02 in the background.
            fake.announcer.healNeedsCalibration(epoch: 1, appActive: false)
        }
        let reply = await GestureIntentLogic.start(fake, now: { fake.clock })
        XCTAssertEqual(reply.message, GestureIntentLogic.readyMessage)
        XCTAssertEqual(fake.announcer.calibrated(epoch: 1, appActive: false), .none, "already announced")
        XCTAssertTrue(fake.notifications.posts.isEmpty, "no recalibrate prompt, no second ready")
    }

    func testAJoinedStartThatNeverReachedGestureDoesNotSayTurnedOff() async {
        let fake = control()
        fake.startOutcome = .alreadyActive
        fake.neverOn = true
        fake.endsAt = 2
        let reply = await GestureIntentLogic.start(fake, now: { fake.clock })
        XCTAssertEqual(fake.replies, [.notStarted])
        XCTAssertEqual(reply.message, GestureIntentLogic.notStartedMessage)
        XCTAssertFalse(fake.announcer.isArmed)
        XCTAssertEqual(fake.announcer.dialogWaiters, 0, "no dialog state is left behind")
    }

    func testAJoinedStartStillEnteringAtTheDeadlineSaysStillStarting() async {
        let fake = control()
        fake.startOutcome = .alreadyActive
        fake.armingUntil = 100
        let reply = await GestureIntentLogic.start(fake, now: { fake.clock })
        XCTAssertEqual(fake.replies, [.starting])
        XCTAssertEqual(reply.message, GestureIntentLogic.stillStartingMessage)
        XCTAssertFalse(fake.announcer.isArmed, "nothing is on yet: no ready notification is promised")
    }

    func testASessionThatEndsDuringTheWaitSaysSo() async {
        let fake = control()
        fake.endsAt = 3
        let reply = await GestureIntentLogic.start(fake, now: { fake.clock })
        XCTAssertEqual(reply.message, "Gestures turned off.")
    }

    func testAStartThatFailedDoesNotWaitForCalibration() async {
        let fake = control()
        fake.startOutcome = .charging
        let reply = await GestureIntentLogic.start(fake, now: { fake.clock })
        XCTAssertEqual(fake.waits, [])
        XCTAssertEqual(reply.message, GestureRequestOutcome.charging.message)
    }

    func testAnAutomaticEndIsStillNamedFirst() async {
        let ended = GestureModeSnapshot.AutomaticEnd(reason: .ringGone, secondsAgo: 30)
        let fake = control { $0.recentAutomaticEnd = ended }
        fake.calibratesAt = 3
        let reply = await GestureIntentLogic.start(fake, now: { fake.clock })
        XCTAssertEqual(reply.message, "\(ended.note) Gestures ready ✓")
        XCTAssertTrue(reply.message.contains("ring out of range"))
    }

    // MARK: Toggle during sticky sessions

    func testToggleDuringAHealTurnsGesturesOff() async {
        // The ring is in Health while the session reconnects: still a running session.
        let fake = control { $0.gestureDesired = true; $0.healing = true; $0.mode = .health; $0.sessionAge = 90 }
        let reply = await GestureIntentLogic.toggle(fake, now: { fake.clock })
        XCTAssertEqual(fake.requests.map(\.enabled), [false])
        XCTAssertEqual(fake.intents, ["stop"])
        XCTAssertEqual(reply.outcome, .stopped)
    }

    func testASecondToggleInsideTheGraceDuringAnotherStartsCalibrationWaitIsKept() async {
        let fake = control { $0.gestureDesired = true; $0.mode = .gesture; $0.sessionAge = 2; $0.startIntentWaiting = true }
        let reply = await GestureIntentLogic.toggle(fake, now: { fake.clock })
        XCTAssertEqual(fake.requests.count, 0, "neither a stop nor a second start")
        XCTAssertEqual(fake.intents, ["kept_calibrating"])
        XCTAssertEqual(reply.message, GestureIntentLogic.stillCalibratingMessage)
    }

    func testAToggleAfterTheGraceStopsEvenWhileAnotherStartWaits() async {
        let fake = control { $0.gestureDesired = true; $0.mode = .gesture; $0.sessionAge = 5; $0.startIntentWaiting = true }
        let reply = await GestureIntentLogic.toggle(fake, now: { fake.clock })
        XCTAssertEqual(fake.requests.map(\.enabled), [false], "a deliberate Back Tap off at 5 s stops")
        XCTAssertEqual(fake.intents, ["stop"])
        XCTAssertEqual(reply.outcome, .stopped)
    }

    func testAToggleDuringAHealStopsEvenWhileAStartWaits() async {
        let fake = control {
            $0.gestureDesired = true; $0.healing = true; $0.mode = .health; $0.sessionAge = 1
            $0.startIntentWaiting = true
        }
        _ = await GestureIntentLogic.toggle(fake, now: { fake.clock })
        XCTAssertEqual(fake.intents, ["kept_new_session"], "only the ordinary 3 s grace, never 'still calibrating'")
        let later = control {
            $0.gestureDesired = true; $0.healing = true; $0.mode = .health; $0.sessionAge = 4
            $0.startIntentWaiting = true
        }
        _ = await GestureIntentLogic.toggle(later, now: { later.clock })
        XCTAssertEqual(later.intents, ["stop"])
    }

    func testAToggleJustAfterAStartIntentRepliedIsTheSameBackTap() async {
        // A double fire iOS queued behind the first run's 8 s wait.
        let fake = control {
            $0.gestureDesired = true; $0.mode = .gesture; $0.sessionAge = 7.5; $0.startIntentRepliedAge = 0.3
        }
        let reply = await GestureIntentLogic.toggle(fake, now: { fake.clock })
        XCTAssertEqual(fake.requests.count, 0)
        XCTAssertEqual(fake.intents, ["kept_new_session"])
        XCTAssertEqual(reply.message, GestureIntentLogic.justStartedMessage)
        let later = control {
            $0.gestureDesired = true; $0.mode = .gesture; $0.sessionAge = 12; $0.startIntentRepliedAge = 4
        }
        _ = await GestureIntentLogic.toggle(later, now: { later.clock })
        XCTAssertEqual(later.intents, ["stop"])
    }

    func testAToggleRightAfterTheSessionStartedReportsReadyWhenCalibrated() async {
        let fake = control { $0.gestureDesired = true; $0.mode = .gesture; $0.sessionAge = 2; $0.calibrated = true }
        let reply = await GestureIntentLogic.toggle(fake, now: { fake.clock })
        XCTAssertEqual(fake.requests.count, 0)
        XCTAssertEqual(reply.message, "Gestures ready ✓")
        let uncalibrated = control { $0.gestureDesired = true; $0.mode = .gesture; $0.sessionAge = 2 }
        let early = await GestureIntentLogic.toggle(uncalibrated, now: { uncalibrated.clock })
        XCTAssertEqual(early.message, GestureIntentLogic.justStartedMessage)
    }

    func testAToggleWhileTheRingStreamsForNoSessionStartsOne() async {
        // A pause whose stop is still being enforced: gestures are off for the user.
        let fake = control { $0.mode = .gesture; $0.orphanGesture = true }
        fake.calibratesAt = 2
        let reply = await GestureIntentLogic.toggle(fake, now: { fake.clock })
        XCTAssertEqual(fake.requests.map(\.enabled), [true])
        XCTAssertEqual(reply.message, "Gestures ready ✓")
    }

    func testControlsThatDoNotWaitKeepThePlainReply() {
        XCTAssertNil(GestureIntentLogic.calibratedReply(.started, .unsupported))
        XCTAssertEqual(GestureIntentLogic.calibratedReply(.started, .calibrated)?.message, "Gestures ready ✓")
        XCTAssertEqual(GestureIntentLogic.calibratedReply(.alreadyActive, .pending)?.outcome, .alreadyActive)
        XCTAssertEqual(GestureIntentLogic.calibrationBudget, 8)
        XCTAssertEqual(GestureIntentLogic.calibratedReply(.alreadyActive, .notStarted)?.message,
                       GestureIntentLogic.notStartedMessage)
        XCTAssertEqual(GestureIntentLogic.calibratedReply(.alreadyActive, .starting)?.message,
                       GestureIntentLogic.stillStartingMessage)
    }
}
