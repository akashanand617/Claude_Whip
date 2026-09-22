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
    private let client: ColmiR02Client
    private let store: HealthStore
    private var ringCalendar: Calendar {
        var value = Calendar(identifier: .gregorian)
        value.timeZone = TimeZone(secondsFromGMT: 0)!
        return value
    }

    init(client: ColmiR02Client, store: HealthStore) {
        self.client = client
        self.store = store
    }

    func sync(deviceID: String, full: Bool,
              onProgress: (String, RingBattery?) -> Void = { _, _ in }) async -> HealthSyncResult {
        var result = HealthSyncResult()
        // Command 0x01 is not a harmless clock refresh on stock Colmi firmware:
        // it clears accumulated activity history. Initialize a new ring once, before
        // it begins collecting for this app, and never send it during routine syncs.
        if full {
            try? client.setClock()
        }
        result.battery = try? await client.battery()
        onProgress(result.battery == nil ? "Connected · battery unavailable" : "Connected · reading history",
                   result.battery)

        if let settings = try? await client.heartRateLoggingSettings(),
           !settings.enabled || settings.interval != 5 {
            try? await client.setHeartRateLogging(enabled: true, intervalMinutes: 5)
        }

        let dayCount = full ? 7 : 2
        // Current steps are the fastest useful dashboard value, so import them before
        // the longer multi-day heart-rate history.
        do {
            for offset in 0..<dayCount {
                onProgress("Syncing steps · \(offset + 1)/\(dayCount)", nil)
                do {
                    let buckets = try await client.steps(dayOffset: UInt8(offset))
                    try store.saveSteps(deviceID: deviceID, buckets: buckets)
                } catch RingProtocolError.noData {
                    continue
                }
            }
        } catch {
            result.stepsError = error.localizedDescription
        }
        onProgress(result.stepsError.map { "Steps unavailable · \($0)" } ?? "Steps imported", nil)

        do {
            let ringToday = ringCalendar.startOfDay(for: .now)
            for offset in 0..<dayCount {
                onProgress("Syncing heart rate · \(offset + 1)/\(dayCount)", nil)
                guard let day = ringCalendar.date(byAdding: .day, value: -offset,
                                                  to: ringToday) else { continue }
                do {
                    let log = try await client.heartRateHistory(day: day)
                    try store.saveHeartRates(deviceID: deviceID, day: day, log: log)
                } catch RingProtocolError.noData {
                    continue
                }
            }
        } catch {
            result.heartRateError = error.localizedDescription
        }
        onProgress(result.heartRateError.map { "Heart rate unavailable · \($0)" }
                   ?? "Heart-rate history imported", nil)

        do {
            onProgress("Syncing sleep", nil)
            let nights = try await client.sleepHistory()
            try store.saveSleep(deviceID: deviceID, nights: nights)
        } catch RingProtocolError.noData {
            // An empty sleep history is valid for a new or unworn ring.
        } catch {
            result.sleepError = error.localizedDescription
        }
        onProgress(result.sleepError.map { "Sleep unavailable · \($0)" } ?? "Sleep imported", nil)
        return result
    }
}
