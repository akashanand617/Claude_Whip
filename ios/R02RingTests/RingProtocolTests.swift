import XCTest
@testable import R02Ring

final class RingProtocolTests: XCTestCase {
    func testConnectedRecoveryRejectsUnrelatedAndUnnamedHIDDevices() {
        let airPods = RingRecoveryCandidate(
            id: UUID(), name: "AirPods", matchedRingSpecificService: false
        )
        let unnamedHID = RingRecoveryCandidate(
            id: UUID(), name: nil, matchedRingSpecificService: false
        )
        XCTAssertNil(RingRecoverySelector.select([airPods, unnamedHID], preferredID: nil))
    }

    func testConnectedRecoveryAcceptsOneNamedR02FromHID() {
        let ring = RingRecoveryCandidate(
            id: UUID(), name: "R02_CC07", matchedRingSpecificService: false
        )
        let unrelated = RingRecoveryCandidate(
            id: UUID(), name: "AirPods", matchedRingSpecificService: false
        )
        XCTAssertEqual(RingRecoverySelector.select([unrelated, ring], preferredID: nil), ring.id)
    }

    func testConnectedRecoveryAcceptsUnnamedRingSpecificServiceAndDeduplicatesIt() {
        let id = UUID()
        let hid = RingRecoveryCandidate(id: id, name: nil, matchedRingSpecificService: false)
        let uart = RingRecoveryCandidate(id: id, name: nil, matchedRingSpecificService: true)
        XCTAssertEqual(RingRecoverySelector.select([hid, uart], preferredID: nil), id)
    }

    func testConnectedRecoveryDoesNotGuessBetweenTwoRings() {
        let first = RingRecoveryCandidate(
            id: UUID(), name: "R02_CC07", matchedRingSpecificService: false
        )
        let second = RingRecoveryCandidate(
            id: UUID(), name: nil, matchedRingSpecificService: true
        )
        XCTAssertNil(RingRecoverySelector.select([first, second], preferredID: nil))
        XCTAssertEqual(RingRecoverySelector.select([first, second], preferredID: second.id), second.id)
    }

    func testHistoricalRecoveryAcceptsOnlyExactPerRingKeys() {
        let id = UUID()
        let keys = [
            "lastHealthSync.\(id.uuidString)",
            "ringFirmwareMode.\(id.uuidString)",
            "ringFirmwareMode.unpaired",
            "lastHealthSync.not-a-uuid",
            "unrelated.\(UUID().uuidString)",
        ]
        XCTAssertEqual(RingRecoverySelector.historicalIdentifiers(from: keys), [id])
    }

    func testRevokedUnifiedFirmwareCannotBeInstalled() {
        XCTAssertFalse(BundledFirmware.unifiedInstallEnabled)
    }

    func testPacketHasSixteenBytesAndChecksum() {
        let packet = ColmiR02Protocol.packet(command: 0x16, payload: [2, 1, 5])
        XCTAssertEqual(packet.count, 16)
        XCTAssertEqual(Array(packet.prefix(4)), [0x16, 2, 1, 5])
        XCTAssertTrue(ColmiR02Protocol.isValidPacket(packet))
    }

    func testUnifiedModeUsesOnlyAuditedRawControlPackets() {
        XCTAssertEqual(Array(ColmiR02Protocol.startRawMotionPacket.prefix(2)), [0xa1, 0x04])
        XCTAssertEqual(ColmiR02Protocol.stopRawMotionPackets.map { Array($0.prefix(2)) },
                       [[0xa1, 0x05], [0xa1, 0x02]])
        XCTAssertTrue(ColmiR02Protocol.isValidPacket(ColmiR02Protocol.startRawMotionPacket))
        XCTAssertTrue(ColmiR02Protocol.stopRawMotionPackets.allSatisfy(ColmiR02Protocol.isValidPacket))
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
        XCTAssertFalse(parser.ingest(Data(terminal)))
        XCTAssertThrowsError(try parser.result(from: []))
        // The terminal index must not hide missing packets. Fill every hole.
        for index in 1...22 where index != 7 {
            let packet = ColmiR02Protocol.packet(command: 0x15, payload: [UInt8(index)])
            XCTAssertEqual(parser.ingest(packet), index == 22)
        }

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

    func testSleepRejectsEveryTruncationBeforeReplacingHistory() throws {
        let payload = Data([1, 0, 8, 0xe2, 0xff, 0xa4, 0x01, 2, 45, 3, 90])
        for end in 0..<payload.count { XCTAssertThrowsError(try SleepPayloadParser.parse(payload.prefix(end))) }
        XCTAssertThrowsError(try SleepPayloadParser.parse(payload + Data([0])))
        XCTAssertThrowsError(try SleepPayloadParser.parse(Data([2]) + payload.dropFirst()))
    }

    func testStepTerminalCannotCompleteMissingIndices() throws {
        let parser = StepLogParser()
        let header = ColmiR02Protocol.packet(command: 0x43, payload: [0xf0])
        let last = ColmiR02Protocol.packet(command: 0x43, payload: [0x26, 0x09, 0x22, 1, 1, 2])
        XCTAssertFalse(parser.ingest(header))
        XCTAssertFalse(parser.ingest(last))
        XCTAssertFalse(parser.ingest(last))
        XCTAssertThrowsError(try parser.result(from: []))
        let first = ColmiR02Protocol.packet(command: 0x43, payload: [0x26, 0x09, 0x22, 0, 0, 2])
        XCTAssertTrue(parser.ingest(first))
        XCTAssertEqual(try parser.result(from: []).count, 2)
    }

    func testDFUFramesMatchValidatedPythonImplementation() throws {
        let firmware = Data("abc".utf8)
        XCTAssertEqual(R02DFU.frame(command: 1).hex, "bc010000ffff")
        XCTAssertEqual(try R02DFU.initFrame(firmware: firmware, type: 4).hex,
                       "bc0209000409040300000049572601")
        XCTAssertEqual(try R02DFU.dataFrame(firmware: firmware, index: 0).hex,
                       "bc03050021570100616263")
        XCTAssertEqual(R02DFU.frame(command: 4).hex, "bc040000ffff")
        XCTAssertEqual(R02DFU.frame(command: 5).hex, "bc050000ffff")
    }

    func testFirmwareFingerprintUsesOnlyReviewedReadSites() {
        XCTAssertEqual(FirmwareIdentity.sites.count, 22)
        XCTAssertEqual(FirmwareIdentity.sites.reduce(0) { $0 + $1.length }, 244)
        XCTAssertEqual(FirmwareIdentity.unifiedSites.count, 9)
        XCTAssertEqual(FirmwareIdentity.unifiedSites.reduce(0) { $0 + $1.length }, 72)
        for site in FirmwareIdentity.sites + FirmwareIdentity.unifiedSites {
            let packet = FirmwareIdentity.readPacket(site)
            XCTAssertEqual(packet[0], 0xcd)
            XCTAssertEqual(packet[1], 1)
            XCTAssertTrue(ColmiR02Protocol.isValidPacket(packet))
        }
    }

    func testBundledFirmwareImagesArePinnedAndCompatible() throws {
        let gesture = try BundledFirmware.gesture.load()
        let stock = try BundledFirmware.health.load()
        let unified = try BundledFirmware.unified.load()
        XCTAssertEqual(gesture.count, 137_540)
        XCTAssertEqual(stock.count, 138_016)
        XCTAssertEqual(unified.count, 137_540)
        XCTAssertEqual(try BundledFirmware.gesture.declaredHardware(in: gesture), "RT02CR_V3.1")
        XCTAssertEqual(try BundledFirmware.health.declaredHardware(in: stock), "RT02CR_V3.1")
        XCTAssertEqual(try BundledFirmware.unified.declaredHardware(in: unified), "RT02CR_V3.1")
    }
}

private extension Data {
    var hex: String { map { String(format: "%02x", $0) }.joined() }
}
