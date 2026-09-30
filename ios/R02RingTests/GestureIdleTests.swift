import XCTest
@testable import R02Ring

@MainActor
final class GestureIdleTests: XCTestCase {
    func testPolicyValues() {
        XCTAssertEqual(GestureIdlePause.allCases, [.off, .fiveMinutes, .fifteenMinutes, .thirtyMinutes])
        XCTAssertEqual(GestureIdlePause.allCases.map(\.rawValue), [0, 300, 900, 1_800])
        XCTAssertEqual(GestureIdlePause.allCases.map(\.seconds), [nil, 300, 900, 1_800])
        XCTAssertEqual(GestureIdlePause.allCases.map(\.title), ["Off", "5 minutes", "15 minutes", "30 minutes"])
        XCTAssertEqual(GestureIdlePause.default, .fifteenMinutes)
    }

    func testStoredPolicyDefaultsToFifteenMinutesNotOff() {
        let suite = UUID().uuidString
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        XCTAssertEqual(GestureIdlePause.stored(in: defaults), .fifteenMinutes)
        GestureIdlePause.off.store(in: defaults)
        XCTAssertEqual(GestureIdlePause.stored(in: defaults), .off)
        GestureIdlePause.fiveMinutes.store(in: defaults)
        XCTAssertEqual(GestureIdlePause.stored(in: defaults), .fiveMinutes)
        defaults.set(7, forKey: GestureIdlePause.storageKey)
        XCTAssertEqual(GestureIdlePause.stored(in: defaults), .fifteenMinutes)
        defaults.set("900", forKey: GestureIdlePause.storageKey)
        XCTAssertEqual(GestureIdlePause.stored(in: defaults), .fifteenMinutes)
    }

    func testTrackerDeadlineMovesOnlyForwardWithActivity() {
        var tracker = GestureIdleTracker(policy: .fifteenMinutes)
        XCTAssertNil(tracker.deadline)
        XCTAssertFalse(tracker.isExpired(at: 1_000_000))
        tracker.activity(at: 50) // before start: ignored
        XCTAssertNil(tracker.deadline)

        tracker.start(at: 100)
        XCTAssertEqual(tracker.deadline, 1_000)
        XCTAssertEqual(tracker.remaining(at: 400), 600)
        tracker.activity(at: 500)
        XCTAssertEqual(tracker.deadline, 1_400)
        tracker.activity(at: 400) // older than the last activity
        tracker.activity(at: .nan)
        XCTAssertEqual(tracker.deadline, 1_400)
        XCTAssertFalse(tracker.isExpired(at: 1_399.9))
        XCTAssertTrue(tracker.isExpired(at: 1_400))
        XCTAssertFalse(tracker.isExpired(at: .nan))
        XCTAssertEqual(tracker.remaining(at: 2_000), 0)

        tracker.policy = .fiveMinutes
        XCTAssertEqual(tracker.deadline, 800)
        tracker.policy = .off
        XCTAssertNil(tracker.deadline)
        XCTAssertFalse(tracker.isExpired(at: 1_000_000))

        tracker.policy = .thirtyMinutes
        tracker.stop()
        XCTAssertNil(tracker.deadline)
        XCTAssertFalse(tracker.isExpired(at: 1_000_000))

        tracker.start(at: .infinity)
        XCTAssertNil(tracker.deadline)
    }
}
