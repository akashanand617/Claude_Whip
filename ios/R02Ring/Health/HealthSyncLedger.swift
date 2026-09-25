import Foundation

/// Import cursors are NOT evidence that the ring acquired continuous health data.
/// A failed metric retries its older range; every success still overlaps two days.
struct HealthSyncLedger: Codable {
    var completed: [String: Date] = [:]

    func days(metric: String, full: Bool, now: Date) -> Int {
        guard !full, let previous = completed[metric] else { return 7 }
        var utc = Calendar(identifier: .gregorian)
        utc.timeZone = TimeZone(secondsFromGMT: 0)!
        let elapsed = utc.dateComponents([.day], from: utc.startOfDay(for: previous),
                                          to: utc.startOfDay(for: now)).day ?? 0
        return min(7, max(2, elapsed + 2))
    }

    static func load(deviceID: String, defaults: UserDefaults) -> Self {
        guard let data = defaults.data(forKey: "healthImportCursor.\(deviceID)"),
              let value = try? JSONDecoder().decode(Self.self, from: data) else { return Self() }
        return value
    }

    func save(deviceID: String, defaults: UserDefaults) {
        if let data = try? JSONEncoder().encode(self) { defaults.set(data, forKey: "healthImportCursor.\(deviceID)") }
    }
}

/// A narrow read-only interface makes it impossible for sync to reset the clock,
/// change measurement settings or enter raw streaming through its dependency.
@MainActor
protocol HealthHistoryReader {
    func battery() async throws -> RingBattery
    func steps(dayOffset: UInt8) async throws -> [StepBucket]
    func heartRateHistory(day: Date) async throws -> HeartRateLog
    func sleepHistory() async throws -> [RingSleepNight]
}

@MainActor
protocol HealthHistoryWriter {
    func saveHeartRates(deviceID: String, day: Date, log: HeartRateLog) throws
    func saveSteps(deviceID: String, buckets: [StepBucket]) throws
    func saveSleep(deviceID: String, nights: [RingSleepNight], now: Date) throws
}

extension ColmiR02Client: HealthHistoryReader {}
extension HealthStore: HealthHistoryWriter {}
