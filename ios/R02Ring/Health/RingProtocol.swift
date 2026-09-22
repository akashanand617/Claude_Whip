import Foundation

enum ColmiR02Protocol {
    static let uartService = "6E40FFF0-B5A3-F393-E0A9-E50E24DCCA9E"
    static let uartWrite = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
    static let uartNotify = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"
    static let bigDataService = "DE5BF728-D711-4E47-AF26-65E3012A5DC7"
    static let bigDataWrite = "DE5BF72A-D711-4E47-AF26-65E3012A5DC7"
    static let bigDataNotify = "DE5BF729-D711-4E47-AF26-65E3012A5DC7"
    static let deviceInfoService = "180A"
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
    private var raw = [Int](repeating: 0, count: 288)
    private var expectedPackets = 0
    private var interval = 5
    private var seenIndices = Set<Int>()

    func ingest(_ data: Data) -> Bool {
        guard data.count == 16 else { return false }
        let subtype = Int(data[1])
        if subtype == 255 { return true }
        if subtype == 0 {
            expectedPackets = Int(data[2])
            interval = max(1, Int(data[3]))
            seenIndices.insert(subtype)
            return false
        }
        if subtype == 1 {
            for index in 0..<9 where index < raw.count { raw[index] = Int(data[6 + index]) }
        } else if subtype > 1 {
            let sampleOffset = 9 + (subtype - 2) * 13
            for index in 0..<13 where sampleOffset + index < raw.count {
                raw[sampleOffset + index] = Int(data[2 + index])
            }
        }
        seenIndices.insert(subtype)
        // Current R02 firmware uses 24 packets (indices 0...23). The header can
        // itself arrive late or not at all, so index 23 is also a safe terminal.
        return subtype == 23 || (expectedPackets > 0 && subtype == expectedPackets - 1)
    }

    func result(from packets: [Data]) throws -> HeartRateLog {
        if packets.last?[1] == 255 { throw RingProtocolError.noData }
        if seenIndices.isEmpty {
            for packet in packets { _ = ingest(packet) }
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
    private var newCalorieProtocol = false
    private(set) var buckets: [StepBucket] = []

    func ingest(_ data: Data) -> Bool {
        guard data.count == 16 else { return false }
        if data[1] == 255 { return true }
        if data[1] == 240 {
            newCalorieProtocol = data[3] == 1
            return false
        }
        var calories = ColmiR02Protocol.uint16LE(data[7], data[8])
        if newCalorieProtocol { calories *= 10 }
        buckets.append(.init(
            year: 2000 + ColmiR02Protocol.decimal(data[1]),
            month: ColmiR02Protocol.decimal(data[2]),
            day: ColmiR02Protocol.decimal(data[3]),
            timeIndex: Int(data[4]),
            steps: ColmiR02Protocol.uint16LE(data[9], data[10]),
            calories: calories,
            distanceMeters: ColmiR02Protocol.uint16LE(data[11], data[12])
        ))
        return Int(data[5]) == Int(data[6]) - 1
    }

    func result(from packets: [Data]) throws -> [StepBucket] {
        if packets.last?[1] == 255 { throw RingProtocolError.noData }
        if buckets.isEmpty { for packet in packets { _ = ingest(packet) } }
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
            guard cursor + 6 <= payload.count else { break }
            let daysAgo = Int(payload[cursor])
            let recordLength = Int(payload[cursor + 1])
            let end = min(payload.count, cursor + 2 + recordLength)
            let startMinutes = signed16(payload[cursor + 2], payload[cursor + 3])
            let endMinutes = signed16(payload[cursor + 4], payload[cursor + 5])
            var stages: [RingSleepStage] = []
            var stageCursor = cursor + 6
            while stageCursor + 1 < end {
                if let stage = stage(from: payload[stageCursor]) {
                    stages.append(.init(stage: stage, durationMinutes: Int(payload[stageCursor + 1])))
                }
                stageCursor += 2
            }
            if !stages.isEmpty {
                nights.append(.init(daysAgo: daysAgo, startMinutes: startMinutes,
                                    endMinutes: endMinutes, stages: stages))
            }
            cursor = max(cursor + 6, cursor + 2 + recordLength)
        }
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
