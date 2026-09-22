import XCTest
@testable import R02Ring

final class RingProtocolTests: XCTestCase {
    func testPacketHasSixteenBytesAndChecksum() {
        let packet = ColmiR02Protocol.packet(command: 0x16, payload: [2, 1, 5])
        XCTAssertEqual(packet.count, 16)
        XCTAssertEqual(Array(packet.prefix(4)), [0x16, 2, 1, 5])
        XCTAssertTrue(ColmiR02Protocol.isValidPacket(packet))
    }

    func testHeartRateRequestEncodesEpochLittleEndian() {
        let date = Date(timeIntervalSince1970: 1_730_332_800)
        let packet = ColmiR02Protocol.heartRateHistoryPacket(day: date)
        XCTAssertEqual(ColmiR02Protocol.uint32LE(packet, at: 1), 1_730_332_800)
    }

    func testHeartRateParserPlacesOutOfOrderPacketsByIndexAndIgnoresDuplicates() throws {
        let parser = HeartRateLogParser()

        var packetSeven = [UInt8](repeating: 0, count: 16)
        packetSeven[0] = 0x15
        packetSeven[1] = 7
        packetSeven[2] = 90
        packetSeven[3] = 105
        packetSeven[15] = ColmiR02Protocol.checksum(packetSeven.prefix(15))
        XCTAssertFalse(parser.ingest(Data(packetSeven)))
        XCTAssertFalse(parser.ingest(Data(packetSeven)))

        var header = [UInt8](repeating: 0, count: 16)
        header[0] = 0x15
        header[1] = 0
        header[2] = 24
        header[3] = 5
        header[15] = ColmiR02Protocol.checksum(header.prefix(15))
        XCTAssertFalse(parser.ingest(Data(header)))

        var terminal = [UInt8](repeating: 0, count: 16)
        terminal[0] = 0x15
        terminal[1] = 23
        terminal[15] = ColmiR02Protocol.checksum(terminal.prefix(15))
        XCTAssertTrue(parser.ingest(Data(terminal)))

        let log = try parser.result(from: [])
        let packetSevenOffset = 9 + (7 - 2) * 13
        XCTAssertEqual(log.samples[packetSevenOffset], 90)
        XCTAssertEqual(log.samples[packetSevenOffset + 1], 105)
        XCTAssertEqual(log.intervalMinutes, 5)
    }

    func testStepParserReadsOneFifteenMinuteBucket() throws {
        let parser = StepLogParser()
        var header = [UInt8](repeating: 0, count: 16)
        header[0] = 0x43
        header[1] = 0xf0
        header[15] = ColmiR02Protocol.checksum(header.prefix(15))
        XCTAssertFalse(parser.ingest(Data(header)))

        var detail = [UInt8](repeating: 0, count: 16)
        detail[0] = 0x43
        detail[1] = 0x24
        detail[2] = 0x06
        detail[3] = 0x01
        detail[4] = 4
        detail[5] = 0
        detail[6] = 1
        detail[7] = 10
        detail[9] = 100
        detail[11] = 50
        detail[15] = ColmiR02Protocol.checksum(detail.prefix(15))
        XCTAssertTrue(parser.ingest(Data(detail)))
        let bucket = try XCTUnwrap(parser.buckets.first)
        XCTAssertEqual(bucket, StepBucket(year: 2024, month: 6, day: 1, timeIndex: 4,
                                           steps: 100, calories: 10, distanceMeters: 50))
    }

    func testBigDataReassemblesFragments() throws {
        let reassembler = BigDataReassembler()
        let full = Data([0xbc, 0x27, 3, 0, 0xff, 0xff, 10, 20, 30])
        XCTAssertNil(reassembler.ingest(full.prefix(4)))
        XCTAssertNil(reassembler.ingest(full.subdata(in: 4..<7)))
        let message = try XCTUnwrap(reassembler.ingest(full.suffix(2)))
        XCTAssertEqual(message.dataID, 0x27)
        XCTAssertEqual(message.payload, Data([10, 20, 30]))
    }

    func testSleepParserHandlesSignedStartAndStages() throws {
        // One record: daysAgo, byte count, start=-30, end=420, light=45, deep=90.
        let payload = Data([1, 0, 8, 0xe2, 0xff, 0xa4, 0x01, 2, 45, 3, 90])
        let night = try XCTUnwrap(SleepPayloadParser.parse(payload).first)
        XCTAssertEqual(night.daysAgo, 0)
        XCTAssertEqual(night.startMinutes, -30)
        XCTAssertEqual(night.endMinutes, 420)
        XCTAssertEqual(night.stages, [
            RingSleepStage(stage: .light, durationMinutes: 45),
            RingSleepStage(stage: .deep, durationMinutes: 90),
        ])
    }

    func testEmptySleepPayloadIsNoData() {
        XCTAssertThrowsError(try SleepPayloadParser.parse(Data([0]))) { error in
            guard case RingProtocolError.noData = error else {
                return XCTFail("Expected no-data error, got \(error)")
            }
        }
    }
}
