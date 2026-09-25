import Foundation

@MainActor
final class ColmiR02Client {
    private let manager: RingManager

    init(manager: RingManager) {
        self.manager = manager
    }

    func setClock(_ date: Date = .now) throws {
        try manager.writeUART(ColmiR02Protocol.setTimePacket(date))
    }

    func battery() async throws -> RingBattery {
        let packets = try await manager.requestUART(
            ColmiR02Protocol.batteryPacket,
            command: ColmiR02Protocol.batteryCommand
        ) { _, _ in true }
        guard let data = packets.last, data.count == 16 else { throw RingProtocolError.invalidPacket }
        return RingBattery(percent: min(100, Int(data[1])), charging: data[2] != 0)
    }

    func heartRateLoggingSettings() async throws -> (enabled: Bool, interval: Int) {
        let packets = try await manager.requestUART(
            ColmiR02Protocol.readHeartRateSettingsPacket,
            command: ColmiR02Protocol.heartRateSettingsCommand
        ) { _, _ in true }
        guard let data = packets.last else { throw RingProtocolError.invalidPacket }
        return (data[2] == 1, Int(data[3]))
    }

    func setHeartRateLogging(enabled: Bool, intervalMinutes: UInt8 = 5) async throws {
        _ = try await manager.requestUART(
            ColmiR02Protocol.writeHeartRateSettingsPacket(enabled: enabled, intervalMinutes: intervalMinutes),
            command: ColmiR02Protocol.heartRateSettingsCommand
        ) { _, _ in true }
    }

    func heartRateHistory(day: Date) async throws -> HeartRateLog {
        let parser = HeartRateLogParser()
        let packets = try await manager.requestUART(
            ColmiR02Protocol.heartRateHistoryPacket(day: day),
            command: ColmiR02Protocol.heartRateLogCommand,
            timeout: 8
        ) { _, latest in parser.ingest(latest) }
        return try parser.result(from: packets)
    }

    func steps(dayOffset: UInt8) async throws -> [StepBucket] {
        let parser = StepLogParser()
        let packets = try await manager.requestUART(
            ColmiR02Protocol.stepsPacket(dayOffset: dayOffset),
            command: ColmiR02Protocol.stepsCommand,
            timeout: 8
        ) { _, latest in parser.ingest(latest) }
        return try parser.result(from: packets)
    }

    func sleepHistory() async throws -> [RingSleepNight] {
        guard manager.canReadSleep else { throw RingProtocolError.notReady }
        let payload = try await manager.requestBigData(
            ColmiR02Protocol.sleepHistoryPacket,
            dataID: ColmiR02Protocol.sleepDataID,
            timeout: 15
        )
        return try SleepPayloadParser.parse(payload)
    }

    func measureHeartRate(onReading: @escaping (Int) -> Void) async throws -> Int {
        do {
            let bpm = try await manager.collectRealtimeHeartRate(onReading: onReading)
            try manager.writeUART(ColmiR02Protocol.stopRealtimeHeartRatePacket)
            return bpm
        } catch {
            try? manager.writeUART(ColmiR02Protocol.stopRealtimeHeartRatePacket)
            throw error
        }
    }

    func cancelHeartRateMeasurement() {
        manager.cancelRealtimeHeartRate()
        try? manager.writeUART(ColmiR02Protocol.stopRealtimeHeartRatePacket)
    }
}

struct HealthSyncResult {
    var battery: RingBattery?
    var heartRateError: String?
    var stepsError: String?
    var sleepError: String?

    var hasAnyError: Bool { heartRateError != nil || stepsError != nil || sleepError != nil }

    var errorSummary: String? {
        if let stepsError { return "Steps: \(stepsError)" }
        if let heartRateError { return "Heart rate: \(heartRateError)" }
        if let sleepError { return "Sleep: \(sleepError)" }
        return nil
    }
}

@MainActor
final class HealthSyncService {
    private let client: any HealthHistoryReader
    private let store: any HealthHistoryWriter
    private let defaults: UserDefaults
    private let clock: () -> Date
    private var ringCalendar: Calendar {
        var value = Calendar(identifier: .gregorian)
        value.timeZone = TimeZone(secondsFromGMT: 0)!
        return value
    }

    init(client: any HealthHistoryReader, store: any HealthHistoryWriter,
         defaults: UserDefaults = .standard, clock: @escaping () -> Date = { .now }) {
        self.client = client
        self.store = store
        self.defaults = defaults
        self.clock = clock
    }

    func sync(deviceID: String, full: Bool,
              onProgress: (String, RingBattery?) -> Void = { _, _ in }) async -> HealthSyncResult {
        var result = HealthSyncResult()
        // Full means history depth only. Provisioning/settings are separate user actions.
        let started = clock()
        var ledger = HealthSyncLedger.load(deviceID: deviceID, defaults: defaults)
        result.battery = try? await client.battery()
        onProgress(result.battery == nil ? "Connected · battery unavailable" : "Connected · reading history",
                   result.battery)

        let stepDays = ledger.days(metric: "steps", full: full, now: started)
        // Current steps are the fastest useful dashboard value, so import them before
        // the longer multi-day heart-rate history.
        for offset in 0..<stepDays {
            onProgress("Syncing steps · \(offset + 1)/\(stepDays)", nil)
            do {
                let requested = clock()
                let buckets = try await client.steps(dayOffset: UInt8(offset))
                // Relative offsets are ambiguous if midnight passed in flight.
                guard ringCalendar.isDate(requested, inSameDayAs: clock()) else {
                    throw RingProtocolError.invalidPacket
                }
                try store.saveSteps(deviceID: deviceID, buckets: buckets)
            } catch RingProtocolError.noData {
                continue
            } catch {
                result.stepsError = error.localizedDescription
            }
        }
        if result.stepsError == nil { ledger.completed["steps"] = started }
        onProgress(result.stepsError.map { "Steps unavailable · \($0)" } ?? "Steps imported", nil)

        let ringToday = ringCalendar.startOfDay(for: started)
        let heartDays = ledger.days(metric: "heartRate", full: full, now: started)
        for offset in 0..<heartDays {
            onProgress("Syncing heart rate · \(offset + 1)/\(heartDays)", nil)
            guard let day = ringCalendar.date(byAdding: .day, value: -offset,
                                              to: ringToday) else { continue }
            do {
                let log = try await client.heartRateHistory(day: day)
                try store.saveHeartRates(deviceID: deviceID, day: day, log: log)
            } catch RingProtocolError.noData {
                continue
            } catch {
                result.heartRateError = error.localizedDescription
            }
        }
        if result.heartRateError == nil { ledger.completed["heartRate"] = started }
        onProgress(result.heartRateError.map { "Heart rate unavailable · \($0)" }
                   ?? "Heart-rate history imported", nil)

        do {
            onProgress("Syncing sleep", nil)
            let requested = clock()
            let nights = try await client.sleepHistory()
            guard ringCalendar.isDate(requested, inSameDayAs: clock()) else {
                throw RingProtocolError.invalidPacket
            }
            try store.saveSleep(deviceID: deviceID, nights: nights, now: requested)
        } catch RingProtocolError.noData {
            // An empty sleep history is valid for a new or unworn ring.
        } catch {
            result.sleepError = error.localizedDescription
        }
        if result.sleepError == nil { ledger.completed["sleep"] = started }
        ledger.save(deviceID: deviceID, defaults: defaults)
        onProgress(result.sleepError.map { "Sleep unavailable · \($0)" } ?? "Sleep imported", nil)
        return result
    }
}
