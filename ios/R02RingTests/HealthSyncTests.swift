import XCTest
@testable import R02Ring

@MainActor
final class HealthSyncTests: XCTestCase {
    final class Reader: HealthHistoryReader {
        var stepOffsets: [UInt8] = []
        var heartDays: [Date] = []
        var failStep: UInt8?
        var sleep: [RingSleepNight] = []
        var onSleep: (() -> Void)?
        var returnSteps = false
        func battery() async throws -> RingBattery { .init(percent: 80, charging: false) }
        func steps(dayOffset: UInt8) async throws -> [StepBucket] {
            stepOffsets.append(dayOffset)
            if failStep == dayOffset { throw RingProtocolError.timeout }
            if returnSteps { return [.init(year: 2026, month: 9, day: 22, timeIndex: 0, steps: 100, calories: 1, distanceMeters: 10)] }
            throw RingProtocolError.noData
        }
        func heartRateHistory(day: Date) async throws -> HeartRateLog {
            heartDays.append(day); throw RingProtocolError.noData
        }
        func sleepHistory() async throws -> [RingSleepNight] { onSleep?(); return sleep }
    }
    final class Writer: HealthHistoryWriter {
        var sleepAnchors: [Date] = []
        var failSteps = false
        func saveHeartRates(deviceID: String, day: Date, log: HeartRateLog) throws {}
        func saveSteps(deviceID: String, buckets: [StepBucket]) throws {
            if failSteps { throw RingProtocolError.invalidPacket }
        }
        func saveSleep(deviceID: String, nights: [RingSleepNight], now: Date) throws { sleepAnchors.append(now) }
    }

    func testFullImportIsReadOnlyAndRetriesOnlyIncompleteMetricDepth() async {
        let defaults = UserDefaults(suiteName: UUID().uuidString)!
        let reader = Reader(), writer = Writer()
        let now = Date(timeIntervalSince1970: 1_790_100_000)
        let service = HealthSyncService(client: reader, store: writer, defaults: defaults, clock: { now })
        reader.failStep = 2
        let first = await service.sync(deviceID: "fixture", full: true)
        XCTAssertNotNil(first.stepsError)
        XCTAssertNil(first.heartRateError)
        XCTAssertEqual(reader.stepOffsets, Array(0...6)) // continue independent days after failure
        let ledger = HealthSyncLedger.load(deviceID: "fixture", defaults: defaults)
        XCTAssertNil(ledger.completed["steps"])
        XCTAssertEqual(ledger.completed["heartRate"], now)
        reader.stepOffsets = []; reader.heartDays = []; reader.failStep = nil
        let retry = await service.sync(deviceID: "fixture", full: false)
        XCTAssertFalse(retry.hasAnyError)
        XCTAssertEqual(reader.stepOffsets.count, 7)
        XCTAssertEqual(reader.heartDays.count, 2)
        XCTAssertEqual(writer.sleepAnchors, [now, now])
        // Reader deliberately has no setting/clock methods: sync cannot call them.
    }

    func testSleepCrossingMidnightDoesNotReplaceSavedNight() async {
        let reader = Reader(), writer = Writer()
        var now = Date(timeIntervalSince1970: 1_790_121_599) // choose midnight explicitly below
        var utc = Calendar(identifier: .gregorian); utc.timeZone = TimeZone(secondsFromGMT: 0)!
        now = utc.startOfDay(for: now).addingTimeInterval(86399)
        reader.onSleep = { now = now.addingTimeInterval(2) }
        let service = HealthSyncService(client: reader, store: writer,
                                        defaults: UserDefaults(suiteName: UUID().uuidString)!, clock: { now })
        let result = await service.sync(deviceID: "fixture", full: false)
        XCTAssertNotNil(result.sleepError)
        XCTAssertTrue(writer.sleepAnchors.isEmpty)
    }

    func testCursorOverlapsAndCapsRetention() {
        let now = Date(timeIntervalSince1970: 1_790_100_000)
        var ledger = HealthSyncLedger()
        XCTAssertEqual(ledger.days(metric: "steps", full: false, now: now), 7)
        ledger.completed["steps"] = now
        XCTAssertEqual(ledger.days(metric: "steps", full: false, now: now), 2)
        XCTAssertEqual(ledger.days(metric: "steps", full: false, now: now.addingTimeInterval(86400 * 3)), 5)
        XCTAssertEqual(ledger.days(metric: "steps", full: false, now: now.addingTimeInterval(86400 * 50)), 7)
    }

    func testStorageFailureDoesNotAdvanceCursorAndRetrySurvivesNewService() async {
        let defaults = UserDefaults(suiteName: UUID().uuidString)!
        let reader = Reader(), writer = Writer(), now = Date(timeIntervalSince1970: 1_790_100_000)
        reader.returnSteps = true; writer.failSteps = true
        let first = HealthSyncService(client: reader, store: writer, defaults: defaults, clock: { now })
        let failed = await first.sync(deviceID: "fixture", full: true)
        XCTAssertNotNil(failed.stepsError)
        XCTAssertNil(HealthSyncLedger.load(deviceID: "fixture", defaults: defaults).completed["steps"])
        writer.failSteps = false; reader.stepOffsets = []
        let next = HealthSyncService(client: reader, store: writer, defaults: defaults, clock: { now })
        let retried = await next.sync(deviceID: "fixture", full: false)
        XCTAssertNil(retried.stepsError)
        XCTAssertEqual(reader.stepOffsets, Array(0...6))
        XCTAssertEqual(HealthSyncLedger.load(deviceID: "fixture", defaults: defaults).completed["steps"], now)
    }
}
