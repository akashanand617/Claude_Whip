import Foundation

enum ColmiR02Protocol {
    static let uartService = "6E40FFF0-B5A3-F393-E0A9-E50E24DCCA9E"
    static let uartWrite = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
    static let uartNotify = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"
    static let bigDataService = "DE5BF728-D711-4E47-AF26-65E3012A5DC7"
    static let bigDataWrite = "DE5BF72A-D711-4E47-AF26-65E3012A5DC7"
    static let bigDataNotify = "DE5BF729-D711-4E47-AF26-65E3012A5DC7"
    static let deviceInfoService = "180A"
    // The stock image also exposes HID and the legacy WeChat service. They are
    // useful only for finding a ring that iOS already owns and therefore no
    // longer advertises; neither is specific enough to identify an unnamed ring.
    static let hidService = "1812"
    static let legacyWeChatService = "FEE7"
    static let firmwareRevision = "2A26"
    static let hardwareRevision = "2A27"

    static let batteryCommand: UInt8 = 0x03
    static let heartRateLogCommand: UInt8 = 0x15
    static let heartRateSettingsCommand: UInt8 = 0x16
    static let realTimeHeartRateCommand: UInt8 = 0x1E
    static let stepsCommand: UInt8 = 0x43
    static let startRealtimeCommand: UInt8 = 0x69
    static let stopRealtimeCommand: UInt8 = 0x6A
    static let sleepDataID: UInt8 = 0x27

    static func rawSensorPacket(_ mode: UInt8) -> Data {
        packet(command: 0xa1, payload: [mode])
    }

    static var startRawMotionPacket: Data { rawSensorPacket(0x04) }
    static var stopRawMotionPackets: [Data] {
        [rawSensorPacket(0x05), rawSensorPacket(0x02)]
    }

    static func checksum<S: Sequence>(_ bytes: S) -> UInt8 where S.Element == UInt8 {
        UInt8(truncatingIfNeeded: bytes.reduce(0) { $0 + Int($1) })
    }

    static func packet(command: UInt8, payload: [UInt8] = []) -> Data {
        precondition(payload.count <= 14)
        var bytes = [UInt8](repeating: 0, count: 16)
        bytes[0] = command
        for (index, byte) in payload.enumerated() { bytes[index + 1] = byte }
        bytes[15] = checksum(bytes.prefix(15))
        return Data(bytes)
    }

    static func isValidPacket(_ data: Data) -> Bool {
        data.count == 16 && checksum(data.prefix(15)) == data[15]
    }

    static func setTimePacket(_ date: Date) -> Data {
        let c = Calendar(identifier: .gregorian).dateComponents(in: TimeZone(secondsFromGMT: 0)!, from: date)
        return packet(command: 0x01, payload: [
            bcd((c.year ?? 2000) % 2000), bcd(c.month ?? 1), bcd(c.day ?? 1),
            bcd(c.hour ?? 0), bcd(c.minute ?? 0), bcd(c.second ?? 0), 1,
        ])
    }

    static var batteryPacket: Data { packet(command: batteryCommand) }

    static func heartRateHistoryPacket(day: Date) -> Data {
        let epoch = UInt32(max(0, Int64(day.timeIntervalSince1970)))
        return packet(command: heartRateLogCommand, payload: [
            UInt8(epoch & 0xff), UInt8((epoch >> 8) & 0xff),
            UInt8((epoch >> 16) & 0xff), UInt8((epoch >> 24) & 0xff),
        ])
    }

    static var readHeartRateSettingsPacket: Data {
        packet(command: heartRateSettingsCommand, payload: [1])
    }

    static func writeHeartRateSettingsPacket(enabled: Bool, intervalMinutes: UInt8 = 5) -> Data {
        packet(command: heartRateSettingsCommand, payload: [2, enabled ? 1 : 2, intervalMinutes])
    }

    static func stepsPacket(dayOffset: UInt8) -> Data {
        packet(command: stepsCommand, payload: [dayOffset, 0x0f, 0x00, 0x5f, 0x01])
    }

    static var startRealtimeHeartRatePacket: Data {
        packet(command: startRealtimeCommand, payload: [1, 1])
    }

    static var continueRealtimeHeartRatePacket: Data {
        packet(command: startRealtimeCommand, payload: [1, 3])
    }

    static var stopRealtimeHeartRatePacket: Data {
        packet(command: stopRealtimeCommand, payload: [1, 0, 0])
    }

    static var sleepHistoryPacket: Data {
        Data([0xbc, sleepDataID, 0x01, 0x00, 0xff, 0x00, 0xff])
    }

    static func bcd(_ value: Int) -> UInt8 {
        UInt8(((value / 10) << 4) | (value % 10))
    }

    static func decimal(_ bcd: UInt8) -> Int {
        Int((bcd >> 4) * 10 + (bcd & 0x0f))
    }

    static func uint16LE(_ lo: UInt8, _ hi: UInt8) -> Int {
        Int(lo) | (Int(hi) << 8)
    }

    static func uint32LE(_ bytes: Data, at offset: Int) -> UInt32 {
        UInt32(bytes[offset])
            | (UInt32(bytes[offset + 1]) << 8)
            | (UInt32(bytes[offset + 2]) << 16)
            | (UInt32(bytes[offset + 3]) << 24)
    }

}

/// A value-only view of a peripheral returned by CoreBluetooth's
/// `retrieveConnectedPeripherals`. Keeping selection independent of
/// CoreBluetooth makes the safety rule directly testable.
struct RingRecoveryCandidate: Equatable {
    let id: UUID
    let name: String?
    let matchedRingSpecificService: Bool

    var hasR02Name: Bool {
        name?.uppercased().contains("R02") == true
    }

    var isEligible: Bool {
        matchedRingSpecificService || hasR02Name
    }
}

enum RingRecoverySelector {
    /// Prefer the app's saved peripheral when it still identifies as a ring.
    /// Without that identity, attach automatically only when exactly one safe
    /// candidate remains. An unnamed HID/FEE7 device is never eligible.
    static func select(_ candidates: [RingRecoveryCandidate], preferredID: UUID?) -> UUID? {
        var merged: [UUID: RingRecoveryCandidate] = [:]
        for candidate in candidates {
            if let old = merged[candidate.id] {
                merged[candidate.id] = RingRecoveryCandidate(
                    id: candidate.id,
                    name: candidate.name ?? old.name,
                    matchedRingSpecificService: old.matchedRingSpecificService
                        || candidate.matchedRingSpecificService
                )
            } else {
                merged[candidate.id] = candidate
            }
        }

        let eligible = merged.values.filter(\.isEligible)
        if let preferredID,
           eligible.contains(where: { $0.id == preferredID }) {
            return preferredID
        }
        return eligible.count == 1 ? eligible[0].id : nil
    }

    /// Health and firmware-mode state is written only after a real R02 link has
    /// supplied a CoreBluetooth identifier. Those per-ring keys can therefore
    /// restore the identifier accidentally removed by the app's Forget action.
    static func historicalIdentifiers(from keys: [String]) -> [UUID] {
        let prefixes = ["lastHealthSync.", "ringFirmwareMode."]
        var result = Set<UUID>()
        for key in keys {
            for prefix in prefixes where key.hasPrefix(prefix) {
                let suffix = String(key.dropFirst(prefix.count))
                if let id = UUID(uuidString: suffix), suffix == id.uuidString {
                    result.insert(id)
                }
            }
        }
        return result.sorted { $0.uuidString < $1.uuidString }
    }
}

enum RingProtocolError: LocalizedError {
    case notReady
    case busy
    case timeout
    case invalidPacket
    case peripheral(String)
    case noData

    var errorDescription: String? {
        switch self {
        case .notReady: return "The ring is not ready."
        case .busy: return "The ring is already handling another request."
        case .timeout: return "The ring did not respond in time."
        case .invalidPacket: return "The ring returned an invalid packet."
        case let .peripheral(message): return message
        case .noData: return "No data is stored for this period."
        }
    }
}

struct RingBattery: Equatable {
    let percent: Int
    let charging: Bool
}

struct HeartRateLog {
    let samples: [Int]
    let intervalMinutes: Int
}

final class HeartRateLogParser {
    // A day contains 288 five-minute slots. D507 can deliver the packets out of
    // order and may repeat the same packet, so address samples by packet index
    // instead of advancing a sequential cursor.
    private var received: [Int: Data] = [:]
    private var invalid = false
    private var noData = false

    private var complete: Bool {
        guard let header = received[0] else { return false }
        let count = Int(header[2])
        return count >= 2 && count <= 113 && received.count == count
            && (0..<count).allSatisfy { received[$0] != nil }
    }

    func ingest(_ data: Data) -> Bool {
        guard ColmiR02Protocol.isValidPacket(data), data[0] == 0x15 else {
            invalid = true; return true
        }
        let subtype = Int(data[1])
        if subtype == 255 { noData = true; return true }
        if subtype > 112 || (subtype == 0 && (data[2] < 2 || data[2] > 113 || data[3] == 0)) {
            invalid = true; return true
        }
        if let old = received[subtype], old != data { invalid = true; return true }
        received[subtype] = data
        // Seeing the last index does NOT prove the preceding packets arrived.
        return complete
    }

    func result(from packets: [Data]) throws -> HeartRateLog {
        if received.isEmpty && !noData { for packet in packets { _ = ingest(packet) } }
        guard !invalid else { throw RingProtocolError.invalidPacket }
        if noData {
            guard received.isEmpty else { throw RingProtocolError.invalidPacket }
            throw RingProtocolError.noData
        }
        guard complete, let header = received[0] else { throw RingProtocolError.invalidPacket }
        let interval = Int(header[3])
        let slots = (1440 + interval - 1) / interval
        guard 9 + (Int(header[2]) - 2) * 13 >= slots else { throw RingProtocolError.invalidPacket }
        var raw = [Int](repeating: 0, count: slots)
        for subtype in 1..<Int(header[2]) {
            guard let packet = received[subtype] else { throw RingProtocolError.invalidPacket }
            let offset = subtype == 1 ? 0 : 9 + (subtype - 2) * 13
            let source = subtype == 1 ? 6 : 2
            for i in 0..<(15 - source) where offset + i < slots { raw[offset + i] = Int(packet[source + i]) }
        }
        return HeartRateLog(samples: raw, intervalMinutes: interval)
    }
}

struct StepBucket: Equatable {
    let year: Int
    let month: Int
    let day: Int
    let timeIndex: Int
    let steps: Int
    let calories: Int
    let distanceMeters: Int
}

final class StepLogParser {
    private var header: Data?
    private var details: [Int: Data] = [:]
    private var expected = 0
    private var invalid = false
    private var noData = false

    var buckets: [StepBucket] {
        details.sorted { $0.key < $1.key }.map { _, data in
            StepBucket(year: 2000 + ColmiR02Protocol.decimal(data[1]),
                       month: ColmiR02Protocol.decimal(data[2]), day: ColmiR02Protocol.decimal(data[3]),
                       timeIndex: Int(data[4]), steps: ColmiR02Protocol.uint16LE(data[9], data[10]),
                       calories: ColmiR02Protocol.uint16LE(data[7], data[8]) * (header?[3] == 1 ? 10 : 1),
                       distanceMeters: ColmiR02Protocol.uint16LE(data[11], data[12]))
        }
    }

    private var complete: Bool {
        header != nil && expected > 0 && details.count == expected
            && (0..<expected).allSatisfy { details[$0] != nil }
    }

    func ingest(_ data: Data) -> Bool {
        guard ColmiR02Protocol.isValidPacket(data), data[0] == 0x43 else { invalid = true; return true }
        if data[1] == 255 { noData = true; return true }
        if data[1] == 240 {
            if let header, header != data { invalid = true }
            header = data
            return invalid || complete
        }
        let count = Int(data[6]), index = Int(data[5])
        var utc = Calendar(identifier: .gregorian)
        utc.timeZone = TimeZone(secondsFromGMT: 0)!
        let parts = DateComponents(year: 2000 + ColmiR02Protocol.decimal(data[1]),
                                   month: ColmiR02Protocol.decimal(data[2]), day: ColmiR02Protocol.decimal(data[3]))
        guard (1...96).contains(count), index < count, data[4] < 96,
              (1...3).allSatisfy({ data[$0] >> 4 <= 9 && data[$0] & 15 <= 9 }),
              let date = utc.date(from: parts), utc.dateComponents([.year, .month, .day], from: date) == parts,
              expected == 0 || expected == count else { invalid = true; return true }
        if let old = details[index], old != data { invalid = true; return true }
        if let other = details.values.first, other[1...3] != data[1...3] { invalid = true; return true }
        expected = count
        details[index] = data
        return complete
    }

    func result(from packets: [Data]) throws -> [StepBucket] {
        if details.isEmpty && !noData { for packet in packets { _ = ingest(packet) } }
        guard !invalid else { throw RingProtocolError.invalidPacket }
        if noData {
            guard details.isEmpty else { throw RingProtocolError.invalidPacket }
            throw RingProtocolError.noData
        }
        guard complete, Set(buckets.map(\.timeIndex)).count == buckets.count else { throw RingProtocolError.invalidPacket }
        return buckets
    }
}

struct BigDataMessage {
    let dataID: UInt8
    let payload: Data
}

final class BigDataReassembler {
    private var buffer = Data()

    func reset() { buffer.removeAll(keepingCapacity: true) }

    func ingest(_ chunk: Data) -> BigDataMessage? {
        buffer.append(chunk)
        guard buffer.count <= 65_541, buffer.first == 0xbc else { reset(); return nil }
        guard buffer.count >= 6 else { return nil }
        let length = Int(buffer[2]) | (Int(buffer[3]) << 8)
        guard buffer.count >= 6 + length else { return nil }
        let message = BigDataMessage(dataID: buffer[1], payload: buffer.subdata(in: 6..<(6 + length)))
        reset()
        return message
    }
}

struct RingSleepStage: Equatable {
    let stage: SleepStage
    let durationMinutes: Int
}

struct RingSleepNight: Equatable {
    let daysAgo: Int
    let startMinutes: Int
    let endMinutes: Int
    let stages: [RingSleepStage]
}

enum SleepPayloadParser {
    static func parse(_ payload: Data) throws -> [RingSleepNight] {
        guard let count = payload.first else { throw RingProtocolError.invalidPacket }
        if count == 0 { throw RingProtocolError.noData }
        var nights: [RingSleepNight] = []
        var cursor = 1
        for _ in 0..<Int(count) {
            guard cursor + 6 <= payload.count else { throw RingProtocolError.invalidPacket }
            let daysAgo = Int(payload[cursor])
            let recordLength = Int(payload[cursor + 1])
            let end = cursor + 2 + recordLength
            guard recordLength >= 6, recordLength.isMultiple(of: 2), end <= payload.count,
                  !nights.contains(where: { $0.daysAgo == daysAgo }) else { throw RingProtocolError.invalidPacket }
            let startMinutes = signed16(payload[cursor + 2], payload[cursor + 3])
            let endMinutes = signed16(payload[cursor + 4], payload[cursor + 5])
            var stages: [RingSleepStage] = []
            var stageCursor = cursor + 6
            while stageCursor + 1 < end {
                guard let stage = stage(from: payload[stageCursor]), payload[stageCursor + 1] > 0 else {
                    throw RingProtocolError.invalidPacket
                }
                stages.append(.init(stage: stage, durationMinutes: Int(payload[stageCursor + 1])))
                stageCursor += 2
            }
            if !stages.isEmpty {
                nights.append(.init(daysAgo: daysAgo, startMinutes: startMinutes,
                                    endMinutes: endMinutes, stages: stages))
            }
            cursor = end
        }
        guard cursor == payload.count else { throw RingProtocolError.invalidPacket }
        return nights
    }

    private static func signed16(_ lo: UInt8, _ hi: UInt8) -> Int {
        Int(Int16(bitPattern: UInt16(lo) | (UInt16(hi) << 8)))
    }

    private static func stage(from value: UInt8) -> SleepStage? {
        switch value {
        case 2: return .light
        case 3: return .deep
        case 4: return .rem
        case 5: return .awake
        default: return nil
        }
    }
}
