import XCTest
@testable import R02Ring

/// Transport-free parser tests. Valid history is not evidence of acquisition.
final class HealthProtocolStressTests: XCTestCase {
    private struct Random {
        var state: UInt64 = 0x12345678
        mutating func next(_ bound: Int) -> Int {
            state = state &* 6364136223846793005 &+ 1442695040888963407
            return Int((state >> 32) % UInt64(bound))
        }
        mutating func shuffled<T>(_ input: [T]) -> [T] {
            var a = input
            for i in stride(from: a.count - 1, through: 1, by: -1) { a.swapAt(i, next(i + 1)) }
            return a
        }
    }

    private var heart: [Data] {
        [ColmiR02Protocol.packet(command: 0x15, payload: [0, 24, 5])] + (1...23).map {
            ColmiR02Protocol.packet(command: 0x15, payload: [UInt8($0)] + Array(repeating: 70, count: 13))
        }
    }
    private var steps: [Data] {
        [ColmiR02Protocol.packet(command: 0x43, payload: [0xf0])] + (0..<4).map {
            ColmiR02Protocol.packet(command: 0x43, payload: [0x26, 0x09, 0x22, UInt8($0), UInt8($0), 4, 1, 0, 100, 0, 10, 0])
        }
    }

    func testOneHundredPacketOrdersAndDuplicatesPreserveHistory() throws {
        var rng = Random()
        for _ in 0..<100 {
            let hr = HeartRateLogParser(), step = StepLogParser()
            for packet in rng.shuffled(heart) { _ = hr.ingest(packet); _ = hr.ingest(packet) }
            let log = try hr.result(from: [])
            XCTAssertEqual(log.intervalMinutes, 5)
            XCTAssertEqual(log.samples, Array(repeating: 70, count: 288))
            for packet in rng.shuffled(steps) { _ = step.ingest(packet); _ = step.ingest(packet) }
            let buckets = try step.result(from: [])
            XCTAssertEqual(buckets.map(\.timeIndex), [0, 1, 2, 3])
            XCTAssertEqual(buckets.map(\.steps), [100, 100, 100, 100])
        }
    }

    func testEveryMissingHistoryPacketAndConflictingDuplicateFails() {
        for missing in heart.indices {
            let parser = HeartRateLogParser()
            for i in heart.indices where i != missing { _ = parser.ingest(heart[i]) }
            XCTAssertThrowsError(try parser.result(from: []), "missing HR \(missing)")
        }
        for missing in steps.indices {
            let parser = StepLogParser()
            for i in steps.indices where i != missing { _ = parser.ingest(steps[i]) }
            XCTAssertThrowsError(try parser.result(from: []), "missing steps \(missing)")
        }
        for index in 1..<heart.count {
            let parser = HeartRateLogParser()
            for packet in heart { _ = parser.ingest(packet) }
            var corrupt = heart[index]; corrupt[8] ^= 1
            corrupt[15] = ColmiR02Protocol.checksum(corrupt.prefix(15))
            _ = parser.ingest(corrupt)
            XCTAssertThrowsError(try parser.result(from: []))
        }
        for index in 1..<steps.count {
            let parser = StepLogParser()
            for packet in steps { _ = parser.ingest(packet) }
            var corrupt = steps[index]; corrupt[9] ^= 1
            corrupt[15] = ColmiR02Protocol.checksum(corrupt.prefix(15))
            _ = parser.ingest(corrupt)
            XCTAssertThrowsError(try parser.result(from: []))
        }
    }

    func testEverySingleByteChecksumCorruptionFails() {
        for index in 0..<16 {
            var hr = heart[1], step = steps[1]
            hr[index] ^= 1; step[index] ^= 1
            let hp = HeartRateLogParser(), sp = StepLogParser()
            _ = hp.ingest(hr); _ = sp.ingest(step)
            XCTAssertThrowsError(try hp.result(from: heart))
            XCTAssertThrowsError(try sp.result(from: steps))
        }
    }

    func testSleepRejectsUnknownStagesDuplicateDaysAndZeroDurations() {
        let valid = Data([1, 0, 8, 0xe2, 0xff, 0xa4, 1, 2, 45, 3, 90])
        for code in 0...255 where !(2...5).contains(code) {
            var malformed = valid; malformed[7] = UInt8(code)
            XCTAssertThrowsError(try SleepPayloadParser.parse(malformed))
        }
        XCTAssertThrowsError(try SleepPayloadParser.parse(Data([2]) + valid.dropFirst() + valid.dropFirst()))
        for index in [8, 10] {
            var malformed = valid; malformed[index] = 0
            XCTAssertThrowsError(try SleepPayloadParser.parse(malformed))
        }
    }

    func testBigDataAllTwoFragmentBoundariesAndReset() throws {
        let full = Data([0xbc, 0x27, 11, 0, 0xff, 0xff, 1, 0, 8, 0xe2, 0xff, 0xa4, 1, 2, 45, 3, 90])
        for split in 1..<full.count {
            let parser = BigDataReassembler()
            XCTAssertNil(parser.ingest(full.prefix(split)))
            let message = try XCTUnwrap(parser.ingest(full.suffix(full.count - split)))
            XCTAssertEqual(message.payload, full.dropFirst(6))
            XCTAssertEqual(message.dataID, 0x27)
            _ = parser.ingest(full.prefix(8)); parser.reset()
            XCTAssertEqual(parser.ingest(full)?.payload, full.dropFirst(6))
        }
    }

    func testTenThousandMalformedInputsNeverManufactureIncompleteHistory() {
        var rng = Random()
        for _ in 0..<10_000 {
            let bytes = Data((0..<rng.next(128)).map { _ in UInt8(rng.next(256)) })
            let hr = HeartRateLogParser(), steps = StepLogParser()
            _ = hr.ingest(bytes); _ = steps.ingest(bytes)
            XCTAssertThrowsError(try hr.result(from: []))
            XCTAssertThrowsError(try steps.result(from: []))
            // Random sleep bytes can occasionally form a valid record. Check
            // its structural contract rather than demanding every byte string fail.
            if let nights = try? SleepPayloadParser.parse(bytes) {
                XCTAssertFalse(nights.isEmpty)
                XCTAssertEqual(Set(nights.map(\.daysAgo)).count, nights.count)
                XCTAssertTrue(nights.allSatisfy { !$0.stages.isEmpty && $0.stages.allSatisfy { $0.durationMinutes > 0 } })
            }
        }
    }
}
