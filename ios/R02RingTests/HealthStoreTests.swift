import XCTest
import SwiftData
@testable import R02Ring

@MainActor
final class HealthStoreTests: XCTestCase {
    private func container() throws -> ModelContainer {
        try ModelContainer(for: HeartRateRecord.self, StepRecord.self, SleepSessionRecord.self,
                           SleepStageRecord.self, HealthCoverageRecord.self,
                           configurations: ModelConfiguration(isStoredInMemoryOnly: true))
    }

    func testOverlapUpsertsWithoutDoublingAndInvalidSleepPreservesStages() throws {
        let container = try container(), context = container.mainContext
        let store = HealthStore(context: context)
        let bucket = StepBucket(year: 2026, month: 9, day: 22, timeIndex: 5, steps: 100, calories: 10, distanceMeters: 50)
        try store.saveSteps(deviceID: "fixture", buckets: [bucket])
        try store.saveSteps(deviceID: "fixture", buckets: [bucket])
        let steps = try context.fetch(FetchDescriptor<StepRecord>())
        XCTAssertEqual(steps.count, 1); XCTAssertEqual(steps.first?.steps, 100)
        let anchor = Date(timeIntervalSince1970: 1_790_100_000)
        let night = RingSleepNight(daysAgo: 0, startMinutes: -30, endMinutes: 420,
                                   stages: [.init(stage: .light, durationMinutes: 45), .init(stage: .deep, durationMinutes: 90)])
        try store.saveSleep(deviceID: "fixture", nights: [night], now: anchor)
        try store.saveSleep(deviceID: "fixture", nights: [night], now: anchor)
        XCTAssertEqual(try context.fetch(FetchDescriptor<SleepSessionRecord>()).count, 1)
        XCTAssertEqual(try context.fetch(FetchDescriptor<SleepStageRecord>()).count, 2)
        let invalid = RingSleepNight(daysAgo: 0, startMinutes: 0, endMinutes: 420, stages: [])
        XCTAssertThrowsError(try store.saveSleep(deviceID: "fixture", nights: [invalid], now: anchor))
        XCTAssertEqual(try context.fetch(FetchDescriptor<SleepStageRecord>()).count, 2)
        var utc = Calendar(identifier: .gregorian); utc.timeZone = TimeZone(secondsFromGMT: 0)!
        let saved = try XCTUnwrap(context.fetch(FetchDescriptor<SleepSessionRecord>()).first)
        XCTAssertEqual(saved.wakeDay, utc.startOfDay(for: anchor))
        XCTAssertEqual(saved.start, saved.wakeDay.addingTimeInterval(-1800))
    }

    func testCoverageStaysUncertainAcrossReconnectUntilHealthConfirmed() throws {
        let container = try container()
        let store = HealthCoverageStore(context: container.mainContext)
        let now = Date(timeIntervalSince1970: 1_790_100_000)
        try store.observe(deviceID: "fixture", mode: .gesture, firmware: "fixture", at: now)
        try store.observe(deviceID: "fixture", mode: .unknown, firmware: "fixture", at: now.addingTimeInterval(10))
        let intervals = try store.uncertainIntervals(deviceID: "fixture")
        XCTAssertEqual(intervals.count, 1); XCTAssertNil(intervals[0].ended)
        XCTAssertFalse(intervals[0].opticalMeasurementsAvailable)
        XCTAssertFalse(intervals[0].stepsAndSleepVerified)
        try store.observe(deviceID: "fixture", mode: .health, firmware: "fixture", at: now.addingTimeInterval(30))
        XCTAssertEqual(intervals[0].ended, now.addingTimeInterval(30))
    }
}
