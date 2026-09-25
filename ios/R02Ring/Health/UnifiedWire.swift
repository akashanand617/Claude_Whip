import Foundation

/// OFFLINE protocol candidate. No CoreBluetooth, UART writes, UUID registration,
/// discovery authorization or production attachment. CRC is not authentication.
enum UnifiedWire {
    enum Failure: Error { case invalid, rejected }
    enum Kind: UInt8 { case request = 1, reply = 2, motion = 3 }
    enum Operation: UInt8 { case status = 1, health = 2, gesture = 3, renew = 4 }
    static let frameBytes = 20
    static let fragmentTimeoutMS: UInt32 = 1000

    static func crc(_ data: [UInt8]) -> UInt16 {
        var result: UInt16 = 0xffff
        for byte in data {
            result ^= UInt16(byte) << 8
            for _ in 0..<8 { result = (result &<< 1) ^ (result & 0x8000 != 0 ? 0x1021 : 0) }
        }
        return result
    }
    static func word(_ bytes: [UInt8], _ offset: Int) -> UInt32 {
        (0..<4).reduce(0) { $0 | (UInt32(bytes[offset + $1]) << (8 * $1)) }
    }
    static func put(_ value: UInt32, into bytes: inout [UInt8], at offset: Int) {
        for i in 0..<4 { bytes[offset + i] = UInt8(truncatingIfNeeded: value >> (8 * i)) }
    }
    static func seal(_ bytes: inout [UInt8]) {
        let sum = crc(Array(bytes.prefix(18)))
        bytes[18] = UInt8(truncatingIfNeeded: sum)
        bytes[19] = UInt8(sum >> 8)
    }
    static func validFrame(_ bytes: [UInt8], kind: Kind) -> Bool {
        guard bytes.count == frameBytes, bytes[0] == 0x57, bytes[1] == 1,
              bytes[2] == kind.rawValue else { return false }
        return crc(Array(bytes.prefix(18))) == UInt16(bytes[18]) | (UInt16(bytes[19]) << 8)
    }
    static func validBody(_ bytes: [UInt8], kind: Kind, bootID: UInt64) -> Bool {
        guard bytes.count == 20, bootID != 0, let operation = Operation(rawValue: bytes[0]) else { return false }
        let lo = UInt32(truncatingIfNeeded: bootID), hi = UInt32(bootID >> 32)
        if kind == .request {
            guard bytes[1] == 0, bytes[18] == 0, bytes[19] == 0,
                  word(bytes, 2) == lo, word(bytes, 6) == hi else { return false }
            let session = word(bytes, 10), sequence = word(bytes, 14)
            return operation == .renew ? session != 0 && sequence != 0 : session == 0 && sequence == 0
        }
        guard kind == .reply, bytes[1] <= 4, bytes[2] <= 4, bytes[3] <= 1,
              word(bytes, 4) == lo, word(bytes, 8) == hi, word(bytes, 16) == 0 else { return false }
        if (bytes[2] == 1 || bytes[2] == 2) && word(bytes, 12) == 0 { return false }
        if bytes[2] == 2 && bytes[3] != 0 { return false }
        if bytes[1] != 0 || operation == .status { return true }
        return operation == .health ? bytes[2] == 0 : bytes[2] == 2
    }
    static func control(kind: Kind, requestID: UInt32, body: [UInt8]) throws -> [[UInt8]] {
        guard kind != .motion, body.count == 20, requestID != 0 else { throw Failure.invalid }
        let offset = kind == .request ? 2 : 4
        let boot = UInt64(word(body, offset)) | (UInt64(word(body, offset + 4)) << 32)
        guard validBody(body, kind: kind, bootID: boot) else { throw Failure.invalid }
        return (0..<2).map { part in
            var bytes = [UInt8](repeating: 0, count: frameBytes)
            bytes[0] = 0x57; bytes[1] = 1; bytes[2] = kind.rawValue; bytes[3] = UInt8(part)
            put(requestID, into: &bytes, at: 4)
            bytes.replaceSubrange(8..<18, with: body[(part * 10)..<(part * 10 + 10)])
            seal(&bytes)
            return bytes
        }
    }
    static func request(_ operation: Operation, requestID: UInt32, bootID: UInt64,
                        session: UInt32 = 0, processedSequence: UInt32 = 0) throws -> [[UInt8]] {
        var body = [UInt8](repeating: 0, count: 20)
        body[0] = operation.rawValue
        put(UInt32(truncatingIfNeeded: bootID), into: &body, at: 2)
        put(UInt32(bootID >> 32), into: &body, at: 6)
        put(session, into: &body, at: 10); put(processedSequence, into: &body, at: 14)
        return try control(kind: .request, requestID: requestID, body: body)
    }
    struct Receiver {
        private let kind: Kind, operation: Operation
        private let requestID: UInt32, connection: UInt32, started: UInt32
        private let bootID: UInt64
        private var next: UInt8 = 0
        private var closed = false
        private var body = [UInt8](repeating: 0, count: 20)

        init(kind: Kind, operation: Operation, requestID: UInt32, connection: UInt32,
             bootID: UInt64, now: UInt32) throws {
            guard kind != .motion, requestID != 0, connection != 0, bootID != 0 else { throw Failure.invalid }
            self.kind = kind; self.operation = operation; self.requestID = requestID
            self.connection = connection; self.bootID = bootID; started = now
        }
        /// Connection is captured at callback scheduling. Never relabel old data.
        /// The caller may publish only the complete result, never the first fragment.
        mutating func feed(_ bytes: [UInt8], connection: UInt32, now: UInt32) throws -> [UInt8]? {
            guard !closed, connection == self.connection, now &- started <= fragmentTimeoutMS,
                  validFrame(bytes, kind: kind), bytes[3] == next, word(bytes, 4) == requestID else {
                closed = true; body = [UInt8](repeating: 0, count: 20); throw Failure.rejected
            }
            body.replaceSubrange(Int(next) * 10..<Int(next) * 10 + 10, with: bytes[8..<18])
            next += 1
            if next == 1 { return nil }
            closed = true
            guard body[0] == operation.rawValue, validBody(body, kind: kind, bootID: bootID) else {
                body = [UInt8](repeating: 0, count: 20); throw Failure.rejected
            }
            return body
        }
    }
    struct Motion: Equatable {
        let session: UInt32, sequence: UInt32
        let x: Int16, y: Int16, z: Int16
    }
    static func motion(_ value: Motion) throws -> [UInt8] {
        guard value.session != 0, value.sequence != 0 else { throw Failure.invalid }
        var bytes = [UInt8](repeating: 0, count: frameBytes)
        bytes[0] = 0x57; bytes[1] = 1; bytes[2] = Kind.motion.rawValue
        put(value.session, into: &bytes, at: 4); put(value.sequence, into: &bytes, at: 8)
        for (i, signed) in [value.x, value.y, value.z].enumerated() {
            let raw = UInt16(bitPattern: signed)
            bytes[12 + 2 * i] = UInt8(truncatingIfNeeded: raw); bytes[13 + 2 * i] = UInt8(raw >> 8)
        }
        seal(&bytes)
        return bytes
    }
    /// Representation only. Binding must independently check boot/connection,
    /// committed Gesture, increasing sequence and freshness before inference.
    static func decodeMotion(_ bytes: [UInt8], session: UInt32) throws -> Motion {
        guard validFrame(bytes, kind: .motion), bytes[3] == 0, session != 0,
              word(bytes, 4) == session, word(bytes, 8) != 0 else { throw Failure.invalid }
        func axis(_ offset: Int) -> Int16 {
            Int16(bitPattern: UInt16(bytes[offset]) | (UInt16(bytes[offset + 1]) << 8))
        }
        return .init(session: session, sequence: word(bytes, 8), x: axis(12), y: axis(14), z: axis(16))
    }
}
