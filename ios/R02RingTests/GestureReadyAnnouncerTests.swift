import XCTest
@testable import R02Ring

@MainActor
private final class RecordingNotifications: NotificationPosting {
    var authorization: PermissionState = .authorized
    var posts: [(title: String, body: String, identifier: String?)] = []
    var authorizationRequests = 0

    func refreshAuthorization() async -> PermissionState { authorization }
    func requestAuthorization() async -> PermissionState {
        authorizationRequests += 1
        return authorization
    }
    func post(title: String, body: String) -> GestureActionOutcome {
        post(title: title, body: body, identifier: "")
    }
    func post(title: String, body: String, identifier: String) -> GestureActionOutcome {
        guard authorization == .authorized else { return .failed("off") }
        posts.append((title, body, identifier))
        return .performed
    }
}

/// "Gestures ready ✓": at most once per arm, never in front, never for a
/// heal that kept the calibration, silent without permission.
@MainActor
final class GestureReadyAnnouncerTests: XCTestCase {
    private var notifications: RecordingNotifications!
    private var announcer: GestureReadyAnnouncer!
    private var now = 0.0

    override func setUp() {
        super.setUp()
        notifications = RecordingNotifications()
        now = 0
        announcer = GestureReadyAnnouncer(notifications: notifications, now: { [unowned self] in self.now })
    }

    func testAnIntentThatRepliedBeforeCalibrationPostsReadyExactlyOnce() {
        announcer.intentWaiting(epoch: 3)
        announcer.intentReplied(epoch: 3, calibrated: false)
        XCTAssertTrue(announcer.isArmed)
        XCTAssertEqual(announcer.calibrated(epoch: 3, appActive: false), .notification)
        XCTAssertEqual(notifications.posts.map(\.title), ["Gestures ready ✓"])
        XCTAssertEqual(notifications.posts.first?.identifier, GestureReadyAnnouncer.identifier)
        // Later calibrations (a kept-frame heal, a second segment) post nothing.
        XCTAssertEqual(announcer.calibrated(epoch: 3, appActive: false), .none)
        XCTAssertEqual(notifications.posts.count, 1)
    }

    func testACalibrationDuringTheIntentsWaitIsTheDialogsToAnnounce() {
        announcer.intentWaiting(epoch: 1)
        XCTAssertEqual(announcer.calibrated(epoch: 1, appActive: false), .dialog)
        announcer.intentReplied(epoch: 1, calibrated: true)
        XCTAssertFalse(announcer.isArmed)
        XCTAssertEqual(announcer.calibrated(epoch: 1, appActive: false), .none)
        XCTAssertTrue(notifications.posts.isEmpty)
    }

    func testInFrontTheScreenShowsItAndNothingIsPosted() {
        announcer.intentReplied(epoch: 2, calibrated: false)
        XCTAssertEqual(announcer.calibrated(epoch: 2, appActive: true), .screen)
        XCTAssertFalse(announcer.isArmed)
        XCTAssertTrue(notifications.posts.isEmpty)
    }

    func testWithoutPermissionItStaysSilentAndNeverAsks() {
        for state in [PermissionState.notDetermined, .denied, .restricted] {
            notifications.authorization = state
            announcer.intentReplied(epoch: 4, calibrated: false)
            XCTAssertEqual(announcer.calibrated(epoch: 4, appActive: false), .unauthorized)
            announcer.healNeedsCalibration(epoch: 4, appActive: false)
            XCTAssertEqual(announcer.calibrated(epoch: 4, appActive: false), .unauthorized)
        }
        XCTAssertTrue(notifications.posts.isEmpty)
        XCTAssertEqual(notifications.authorizationRequests, 0)
    }

    func testAHealThatNeededCalibrationAsksOnceAndPostsReadyOnce() {
        announcer.healNeedsCalibration(epoch: 5, appActive: false)
        XCTAssertEqual(notifications.posts.map(\.title), ["Gestures reconnected"])
        XCTAssertEqual(announcer.calibrated(epoch: 5, appActive: false), .notification)
        XCTAssertEqual(notifications.posts.map(\.title), ["Gestures reconnected", "Gestures ready ✓"])
        XCTAssertEqual(Set(notifications.posts.map(\.identifier)), [GestureReadyAnnouncer.identifier],
                       "ready replaces the prompt")
        // Another recalibrating heal soon after: the prompt is rate-limited, ready is not.
        now += 60
        announcer.healNeedsCalibration(epoch: 5, appActive: false)
        XCTAssertEqual(announcer.calibrated(epoch: 5, appActive: false), .notification)
        XCTAssertEqual(notifications.posts.map(\.title),
                       ["Gestures reconnected", "Gestures ready ✓", "Gestures ready ✓"])
        now += GestureReadyAnnouncer.promptSpacing
        announcer.healNeedsCalibration(epoch: 5, appActive: false)
        XCTAssertEqual(notifications.posts.last?.title, "Gestures reconnected")
    }

    func testAHealInFrontOnlyArmsTheScreen() {
        announcer.healNeedsCalibration(epoch: 6, appActive: true)
        XCTAssertTrue(notifications.posts.isEmpty)
        XCTAssertEqual(announcer.calibrated(epoch: 6, appActive: true), .screen)
    }

    func testASilentHealThatKeptTheFramePostsNothing() {
        // Nothing arms the announcer: the kept frame is ready on the first sample.
        XCTAssertEqual(announcer.calibrated(epoch: 7, appActive: false), .none)
        XCTAssertTrue(notifications.posts.isEmpty)
    }

    func testAnotherSessionsCalibrationAndAResetDisarm() {
        announcer.intentReplied(epoch: 8, calibrated: false)
        XCTAssertEqual(announcer.calibrated(epoch: 9, appActive: false), .none, "a later session")
        XCTAssertFalse(announcer.isArmed)
        announcer.intentReplied(epoch: 9, calibrated: false)
        announcer.reset()
        XCTAssertEqual(announcer.calibrated(epoch: 9, appActive: false), .none)
        XCTAssertTrue(notifications.posts.isEmpty)
    }

    // MARK: Heals and concurrent intents during a dialog

    func testAHealDuringTheDialogKeepsItAndPostsNothing() {
        announcer.intentWaiting(epoch: 3)
        announcer.healNeedsCalibration(epoch: 3, appActive: false)
        XCTAssertTrue(notifications.posts.isEmpty, "the dialog is still spinning: no recalibrate prompt")
        XCTAssertEqual(announcer.calibrated(epoch: 3, appActive: false), .dialog)
        announcer.intentReplied(epoch: 3, calibrated: true)
        XCTAssertFalse(announcer.isArmed)
        XCTAssertEqual(announcer.calibrated(epoch: 3, appActive: false), .none)
        XCTAssertTrue(notifications.posts.isEmpty)
    }

    func testAHealDuringTheDialogArmsTheHealNoticeIfTheDialogLeavesFirst() {
        announcer.intentWaiting(epoch: 3)
        announcer.healNeedsCalibration(epoch: 3, appActive: false)
        announcer.intentReplied(epoch: 3, calibrated: false)
        XCTAssertTrue(announcer.isArmed)
        XCTAssertEqual(announcer.calibrated(epoch: 3, appActive: false), .notification)
        XCTAssertEqual(notifications.posts.map(\.title), ["Gestures ready ✓"])
        XCTAssertEqual(notifications.posts.first?.body, "Reconnected and recalibrated. Ring gestures are on.")
    }

    func testTwoWaitingIntentsAnnounceOneCalibrationOnce() {
        // A times out while B still waits; calibration completes inside B's budget.
        announcer.intentWaiting(epoch: 2)
        announcer.intentWaiting(epoch: 2)
        announcer.intentReplied(epoch: 2, calibrated: false)
        XCTAssertFalse(announcer.isArmed, "B's dialog may still announce it")
        XCTAssertEqual(announcer.calibrated(epoch: 2, appActive: false), .dialog)
        announcer.intentReplied(epoch: 2, calibrated: true)
        XCTAssertFalse(announcer.isArmed)
        XCTAssertEqual(announcer.dialogWaiters, 0)
        XCTAssertTrue(notifications.posts.isEmpty)
    }

    func testTwoWaitingIntentsThatBothLeaveEarlyArmOneNotification() {
        announcer.intentWaiting(epoch: 2)
        announcer.intentWaiting(epoch: 2)
        announcer.intentReplied(epoch: 2, calibrated: false)
        announcer.intentReplied(epoch: 2, calibrated: false)
        XCTAssertTrue(announcer.isArmed)
        XCTAssertEqual(announcer.calibrated(epoch: 2, appActive: false), .notification)
        XCTAssertEqual(announcer.calibrated(epoch: 2, appActive: false), .none)
        XCTAssertEqual(notifications.posts.count, 1)
    }

    func testAnIntentThatLeftWithNothingToAnnounceArmsNothing() {
        announcer.intentWaiting(epoch: 4)
        announcer.intentLeft(epoch: 4)
        XCTAssertFalse(announcer.isArmed)
        XCTAssertEqual(announcer.dialogWaiters, 0)
        XCTAssertEqual(announcer.calibrated(epoch: 4, appActive: false), .none)
        XCTAssertTrue(notifications.posts.isEmpty)
    }
}
