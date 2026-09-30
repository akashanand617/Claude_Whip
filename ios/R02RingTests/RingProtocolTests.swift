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

    func testIntentionalForgetSuppressesAutomaticButNotExplicitDiscovery() {
        let old = RingRecoveryCandidate(
            id: UUID(), name: "R02_CC07", matchedRingSpecificService: true
        )
        let replacement = RingRecoveryCandidate(
            id: UUID(), name: "R02_DE07", matchedRingSpecificService: true
        )
        XCTAssertEqual(
            RingRecoverySelector.select(
                [old, replacement], preferredID: old.id, excluding: [old.id]
            ),
            replacement.id
        )
        XCTAssertNil(RingRecoverySelector.select(
            [old], preferredID: old.id, excluding: [old.id]
        ))
        let keys = ["lastHealthSync.\(old.id.uuidString)",
                    "ringFirmwareMode.\(replacement.id.uuidString)"]
        XCTAssertEqual(
            RingRecoverySelector.historicalIdentifiers(from: keys, excluding: [old.id]),
            [replacement.id]
        )
    }

    func testRevokedUnifiedFirmwareCannotBeInstalled() {
        XCTAssertFalse(BundledFirmware.unifiedInstallEnabled)
    }

    func testFirmwareRoutingRequiresMatchingHardwareAndFirmwareFamilies() {
        XCTAssertEqual(
            RingHardwareFamily.route(
                hardware: "RT02CR_V3.1", firmware: FirmwareIdentity.stockVersion
            ),
            .rt02cr
        )
        XCTAssertEqual(
            RingHardwareFamily.route(
                hardware: "RT12COL_V1.0", firmware: "RT12COL_1.00.00_260520"
            ),
            .rt12col
        )
        XCTAssertNil(RingHardwareFamily.route(
            hardware: "RT12COL_V1.0", firmware: FirmwareIdentity.stockVersion
        ))
        XCTAssertNil(RingHardwareFamily.route(
            hardware: "RT02CR_V3.1", firmware: "future_unknown_1.0"
        ))
        XCTAssertNil(RingHardwareFamily.route(hardware: nil, firmware: FirmwareIdentity.stockVersion))
        XCTAssertTrue(BundledFirmware.routedCatalog(
            hardware: "RT02CR_V3.1", firmware: "RT02CR_future_unknown"
        ).isEmpty)
    }

    func testFirmwareCatalogRoutesOnlyImagesForItsExactFamily() {
        let rt02cr = BundledFirmware.routedCatalog(
            hardware: "RT02CR_V3.1", firmware: FirmwareIdentity.stockVersion
        )
        XCTAssertEqual(Set(rt02cr.map(\.family)), [.rt02cr])
        XCTAssertEqual(Set(rt02cr.map(\.mode)), [.health, .gesture, .unified])

        let rt12col = BundledFirmware.routedCatalog(
            hardware: "RT12COL_V1.0", firmware: "RT12COL_1.00.00_260520"
        )
        XCTAssertEqual(Set(rt12col.map(\.family)), [.rt12col])
        XCTAssertEqual(Set(rt12col.map(\.mode)), [.health, .unified])
        XCTAssertEqual(BundledFirmware.routedImage(
            for: .unified,
            hardware: "RT12COL_V1.0",
            firmware: "RT12COL_1.00.00_260520"
        )?.sha256, BundledFirmware.rt12colUnifiedHIDV10.sha256)
        XCTAssertFalse(rt12col.contains { $0.family == .rt02cr })
    }

    func testRT12COLV6IsARecognizedInstalledIdentity() throws {
        XCTAssertTrue(FirmwareIdentity.isKnownInstalledVersion(
            FirmwareIdentity.rt12colUnifiedV6Version, family: .rt12col
        ))
        XCTAssertEqual(
            RingHardwareFamily.route(
                hardware: "RT12COL_V1.0",
                firmware: FirmwareIdentity.rt12colUnifiedV6Version
            ),
            .rt12col
        )
        let image = try BundledFirmware.rt12colUnifiedLegacyV6.load()
        XCTAssertEqual(
            String(data: image[0x10..<0x30], encoding: .utf8)?
                .trimmingCharacters(in: .controlCharacters),
            FirmwareIdentity.rt12colUnifiedV6Version
        )
    }

    func testRT12COLV8HIDIsRecognizedAndRoutedForGuardedInstallation() throws {
        XCTAssertTrue(FirmwareIdentity.isKnownInstalledVersion(
            FirmwareIdentity.rt12colUnifiedHIDVersion, family: .rt12col
        ))
        XCTAssertTrue(BundledFirmware.rt12colUnifiedHID.installEnabled)
        XCTAssertTrue(BundledFirmware.rt12colCatalog.contains {
            $0.resource == BundledFirmware.rt12colUnifiedHID.resource
        })
        XCTAssertEqual(
            BundledFirmware.routedImage(
                for: .unified,
                hardware: "RT12COL_V1.0",
                firmware: FirmwareIdentity.rt12colUnifiedVersion
            )?.resource,
            BundledFirmware.rt12colUnifiedHIDV10.resource
        )
        XCTAssertFalse(BundledFirmware.rt12colUnifiedHID.isInstalled(
            mode: .unified, version: FirmwareIdentity.rt12colUnifiedVersion
        ))
        XCTAssertTrue(BundledFirmware.rt12colUnifiedHID.isInstalled(
            mode: .unified, version: FirmwareIdentity.rt12colUnifiedHIDVersion
        ))
        let image = try BundledFirmware.rt12colUnifiedHID.load()
        XCTAssertEqual(
            try BundledFirmware.rt12colUnifiedHID.declaredFirmware(in: image),
            FirmwareIdentity.rt12colUnifiedHIDVersion
        )
    }

    func testRT12COLV9KeyboardHIDRemainsRecognizedButIsNotAnInstallTarget() throws {
        XCTAssertTrue(FirmwareIdentity.isKnownInstalledVersion(
            FirmwareIdentity.rt12colUnifiedHIDV9Version, family: .rt12col
        ))
        XCTAssertFalse(BundledFirmware.rt12colUnifiedHIDV9.installEnabled)
        XCTAssertFalse(BundledFirmware.rt12colCatalog.contains {
            $0.resource == BundledFirmware.rt12colUnifiedHIDV9.resource
        })
        XCTAssertFalse(BundledFirmware.rt12colUnifiedHIDV9.isInstalled(
            mode: .unified, version: FirmwareIdentity.rt12colUnifiedHIDVersion
        ))
        XCTAssertTrue(BundledFirmware.rt12colUnifiedHIDV9.isInstalled(
            mode: .unified, version: FirmwareIdentity.rt12colUnifiedHIDV9Version
        ))
        let image = try BundledFirmware.rt12colUnifiedHIDV9.load()
        XCTAssertEqual(
            try BundledFirmware.rt12colUnifiedHIDV9.declaredFirmware(in: image),
            FirmwareIdentity.rt12colUnifiedHIDV9Version
        )
        XCTAssertEqual(try BundledFirmware.rt12colUnifiedHIDV9.declaredHardware(in: image),
                       "RT12COL_V1.0")
    }

    func testRT12COLV10IsTheGuardedUpgradeFromInstalledV9() throws {
        XCTAssertTrue(FirmwareIdentity.isKnownInstalledVersion(
            FirmwareIdentity.rt12colUnifiedHIDV10Version, family: .rt12col
        ))
        XCTAssertTrue(BundledFirmware.rt12colUnifiedHIDV10.installEnabled)
        XCTAssertTrue(BundledFirmware.rt12colCatalog.contains {
            $0.resource == BundledFirmware.rt12colUnifiedHIDV10.resource
        })
        XCTAssertFalse(BundledFirmware.rt12colUnifiedHIDV10.isInstalled(
            mode: .unified, version: FirmwareIdentity.rt12colUnifiedHIDV9Version
        ), "an installed V9 must be eligible for the V10 same-mode upgrade")
        XCTAssertTrue(BundledFirmware.rt12colUnifiedHIDV10.isInstalled(
            mode: .unified, version: FirmwareIdentity.rt12colUnifiedHIDV10Version
        ))
        XCTAssertEqual(BundledFirmware.routedImage(
            for: .unified,
            hardware: "RT12COL_V1.0",
            firmware: FirmwareIdentity.rt12colUnifiedHIDV9Version
        )?.resource, BundledFirmware.rt12colUnifiedHIDV10.resource)
        let image = try BundledFirmware.rt12colUnifiedHIDV10.load()
        XCTAssertEqual(try BundledFirmware.rt12colUnifiedHIDV10.declaredFirmware(in: image),
                       FirmwareIdentity.rt12colUnifiedHIDV10Version)
        XCTAssertEqual(try BundledFirmware.rt12colUnifiedHIDV10.declaredHardware(in: image),
                       "RT12COL_V1.0")
        XCTAssertEqual(BundledFirmware.rt12colUnifiedHIDV10.sha256,
                       "7e04ae9973341233d2dbbe06fc6eb4c228aab625b1c3687462416edbe7d21ce2")
    }

    func testFirmwareCatalogFailsClosedOnIdentityConflict() {
        XCTAssertTrue(BundledFirmware.routedCatalog(
            hardware: "RT12COL_V1.0", firmware: FirmwareIdentity.gestureVersion
        ).isEmpty)
        XCTAssertNil(BundledFirmware.routedImage(
            for: .gesture,
            hardware: "RT12COL_V1.0",
            firmware: FirmwareIdentity.gestureVersion
        ))
    }

    func testRT12COLCandidateAndRollbackAreSeparatelyPinned() throws {
        XCTAssertEqual(BundledFirmware.rt12colUnified.initType, 4)
        XCTAssertFalse(BundledFirmware.rt12colUnified.installEnabled)
        XCTAssertTrue(BundledFirmware.rt12colUnifiedHID.installEnabled)
        XCTAssertFalse(BundledFirmware.rt12colUnifiedHIDV9.installEnabled)
        XCTAssertTrue(BundledFirmware.rt12colUnifiedHIDV10.installEnabled)
        XCTAssertFalse(BundledFirmware.rt12colUnifiedLegacyV6.installEnabled)
        XCTAssertFalse(BundledFirmware.rt12colUnifiedLegacyV3.installEnabled)
        XCTAssertFalse(BundledFirmware.rt12colUnifiedLegacyV1.installEnabled)
        XCTAssertEqual(BundledFirmware.rt12colHealth.initType, 4)
        XCTAssertNotEqual(BundledFirmware.rt12colUnified.sha256,
                          BundledFirmware.rt12colHealth.sha256)
        XCTAssertNotEqual(BundledFirmware.rt12colUnified.sha256,
                          BundledFirmware.rt12colUnifiedLegacyV1.sha256)
        XCTAssertNotEqual(BundledFirmware.rt12colUnified.sha256,
                          BundledFirmware.rt12colUnifiedLegacyV3.sha256)
        XCTAssertNotEqual(BundledFirmware.rt12colUnified.sha256,
                          BundledFirmware.rt12colUnifiedLegacyV6.sha256)
        XCTAssertNotEqual(BundledFirmware.rt12colUnifiedHID.sha256,
                          BundledFirmware.rt12colUnified.sha256)
        XCTAssertNotEqual(BundledFirmware.rt12colUnifiedHIDV9.sha256,
                          BundledFirmware.rt12colUnifiedHID.sha256)
        XCTAssertNotEqual(BundledFirmware.rt12colUnifiedHIDV10.sha256,
                          BundledFirmware.rt12colUnifiedHIDV9.sha256)
        XCTAssertEqual(try BundledFirmware.rt12colUnifiedHID.declaredHardware(
            in: BundledFirmware.rt12colUnifiedHID.load()
        ), "RT12COL_V1.0")
        XCTAssertEqual(try BundledFirmware.rt12colUnified.declaredHardware(
            in: BundledFirmware.rt12colUnified.load()
        ), "RT12COL_V1.0")
        XCTAssertEqual(try BundledFirmware.rt12colUnifiedLegacyV1.declaredHardware(
            in: BundledFirmware.rt12colUnifiedLegacyV1.load()
        ), "RT12COL_V1.0")
        XCTAssertEqual(try BundledFirmware.rt12colUnifiedLegacyV3.declaredHardware(
            in: BundledFirmware.rt12colUnifiedLegacyV3.load()
        ), "RT12COL_V1.0")
        XCTAssertEqual(try BundledFirmware.rt12colUnifiedLegacyV6.declaredHardware(
            in: BundledFirmware.rt12colUnifiedLegacyV6.load()
        ), "RT12COL_V1.0")
        XCTAssertEqual(try BundledFirmware.rt12colHealth.declaredHardware(
            in: BundledFirmware.rt12colHealth.load()
        ), "RT12COL_V1.0")
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

    func testEveryExposedHIDActionUsesOneChecksumValidA2Packet() {
        for version in [8, 9] {
            let commands = RingHIDAction.allCases.compactMap {
                $0.command(hidVersion: version, wheelAmount: 3)
            }
            XCTAssertFalse(commands.isEmpty)
            for command in commands {
                let packet = ColmiR02Protocol.hidActionPacket(command)
                XCTAssertEqual(packet.count, 16)
                XCTAssertEqual(packet[0], 0xa2)
                XCTAssertEqual(packet[1], command.code)
                XCTAssertTrue(packet[2..<15].allSatisfy { $0 == 0 })
                XCTAssertTrue(ColmiR02Protocol.isValidPacket(packet))
            }
        }
        let swipe = RingHIDAction.swipeUp.command(hidVersion: 9)!
        let volume = RingHIDAction.volumeUp.command(hidVersion: 9)!
        XCTAssertEqual(Array(ColmiR02Protocol.hidActionPacket(swipe)),
                       [0xa2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0xa2])
        XCTAssertEqual(Array(ColmiR02Protocol.hidActionPacket(volume).prefix(2)),
                       [0xa2, 0x28])
        XCTAssertEqual(RingHIDAction.wheelUp.command(hidVersion: 9, wheelAmount: 1)?.code, 0x08)
        XCTAssertEqual(RingHIDAction.wheelUp.command(hidVersion: 9, wheelAmount: 5)?.code, 0x04)
        XCTAssertEqual(RingHIDAction.wheelDown.command(hidVersion: 9, wheelAmount: 1)?.code, 0x0a)
        XCTAssertEqual(RingHIDAction.wheelDown.command(hidVersion: 9, wheelAmount: 5)?.code, 0x0e)
        XCTAssertEqual(RingHIDAction.keyUp.command(hidVersion: 9)?.code, 0xd2)
        XCTAssertEqual(RingHIDAction.keyF6.command(hidVersion: 9)?.code, 0xbf)
        XCTAssertNil(RingHIDAction.keyUp.command(hidVersion: 8))
    }

    func testV9KeyboardCommandsMatchTheDirectUSBKeycodeContract() {
        let expected: [(RingHIDAction, UInt8)] = [
            (.keyEnter, 0xa8), (.keyEscape, 0xa9), (.keyBackspace, 0xaa),
            (.keyTab, 0xab), (.keySpace, 0xac), (.keyRefresh, 0xbe), (.keyF6, 0xbf),
            (.keyHome, 0xca), (.keyPageUp, 0xcb), (.keyDelete, 0xcc),
            (.keyEnd, 0xcd), (.keyPageDown, 0xce), (.keyRight, 0xcf),
            (.keyLeft, 0xd0), (.keyDown, 0xd1), (.keyUp, 0xd2),
        ]
        for (action, code) in expected {
            XCTAssertEqual(action.command(hidVersion: 9)?.code, code)
            XCTAssertEqual(action.command(hidVersion: 10)?.code, code)
            XCTAssertEqual(code & 0x7f, code - 0x80)
        }
        XCTAssertEqual(RingHIDAction.nextTrack.command(hidVersion: 9)?.code, 0x20)
        XCTAssertEqual(RingHIDAction.volumeDown.command(hidVersion: 9)?.code, 0x29)
        XCTAssertEqual(RingHIDAction.search.command(hidVersion: 9)?.code, 0x25)
        XCTAssertEqual(RingHIDAction.home.command(hidVersion: 9)?.code, 0x26)
        XCTAssertEqual(RingHIDAction.back.command(hidVersion: 9)?.code, 0x27)
        for action in RingHIDAction.allCases {
            XCTAssertEqual(action.command(hidVersion: 10, wheelAmount: 4),
                           action.command(hidVersion: 9, wheelAmount: 4),
                           "V10 changes HID classification, not the A2 wire action for \(action)")
        }
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
        XCTAssertEqual(FirmwareIdentity.rt12colUnifiedV1Sites.count, 11)
        XCTAssertEqual(FirmwareIdentity.rt12colUnifiedV1Sites.reduce(0) { $0 + $1.length }, 92)
        XCTAssertEqual(FirmwareIdentity.rt12colUnifiedV2Sites.count, 24)
        XCTAssertEqual(FirmwareIdentity.rt12colUnifiedV2Sites.reduce(0) { $0 + $1.length }, 266)
        XCTAssertEqual(FirmwareIdentity.rt12colUnifiedV3Sites.count, 31)
        XCTAssertEqual(FirmwareIdentity.rt12colUnifiedV3Sites.reduce(0) { $0 + $1.length }, 364)
        XCTAssertEqual(FirmwareIdentity.rt12colUnifiedSites.count, 41)
        XCTAssertEqual(FirmwareIdentity.rt12colUnifiedSites.reduce(0) { $0 + $1.length }, 335)
        XCTAssertEqual(FirmwareIdentity.rt12colUnifiedHIDSites.count, 50)
        XCTAssertEqual(FirmwareIdentity.rt12colUnifiedHIDSites.reduce(0) { $0 + $1.length }, 423)
        XCTAssertEqual(FirmwareIdentity.rt12colUnifiedHIDV9Sites.count, 73)
        XCTAssertEqual(FirmwareIdentity.rt12colUnifiedHIDV9Sites.reduce(0) { $0 + $1.length }, 707)
        XCTAssertEqual(FirmwareIdentity.rt12colUnifiedHIDV10Sites.count, 84)
        XCTAssertEqual(FirmwareIdentity.rt12colUnifiedHIDV10Sites.reduce(0) { $0 + $1.length }, 855)
        for site in FirmwareIdentity.sites + FirmwareIdentity.unifiedSites
                + FirmwareIdentity.rt12colUnifiedV1Sites
                + FirmwareIdentity.rt12colUnifiedV2Sites
                + FirmwareIdentity.rt12colUnifiedV3Sites
                + FirmwareIdentity.rt12colUnifiedSites
                + FirmwareIdentity.rt12colUnifiedHIDSites
                + FirmwareIdentity.rt12colUnifiedHIDV9Sites
                + FirmwareIdentity.rt12colUnifiedHIDV10Sites {
            XCTAssertLessThanOrEqual(site.length, 14)
            let packet = FirmwareIdentity.readPacket(site)
            XCTAssertEqual(packet[0], 0xcd)
            XCTAssertEqual(packet[1], 1)
            XCTAssertTrue(ColmiR02Protocol.isValidPacket(packet))
        }
    }

    func testRT12COLV9FingerprintCoversEveryChangedApplicationByte() throws {
        let stock = try BundledFirmware.rt12colHealth.load()
        let v9 = try BundledFirmware.rt12colUnifiedHIDV9.load()
        XCTAssertEqual(stock.count, v9.count)
        let covered = Set(FirmwareIdentity.rt12colUnifiedHIDV9Sites.flatMap { site in
            site.offset..<(site.offset + site.length)
        })
        let changedApplication = Set((0x450..<v9.count).filter { stock[$0] != v9[$0] })
        XCTAssertFalse(changedApplication.isEmpty)
        XCTAssertTrue(changedApplication.isSubset(of: covered))
        XCTAssertEqual(covered.count, 707)
    }

    func testRT12COLV10FingerprintCoversEveryChangedApplicationByte() throws {
        let stock = try BundledFirmware.rt12colHealth.load()
        let v10 = try BundledFirmware.rt12colUnifiedHIDV10.load()
        XCTAssertEqual(stock.count, v10.count)
        let covered = Set(FirmwareIdentity.rt12colUnifiedHIDV10Sites.flatMap { site in
            site.offset..<(site.offset + site.length)
        })
        let changedApplication = Set((0x450..<v10.count).filter { stock[$0] != v10[$0] })
        XCTAssertFalse(changedApplication.isEmpty)
        XCTAssertTrue(changedApplication.isSubset(of: covered))
        XCTAssertEqual(covered.count, 855)
    }

    func testRT12COLV6FingerprintCoversEveryChangedApplicationByte() throws {
        let stock = try BundledFirmware.rt12colHealth.load()
        let v6 = try BundledFirmware.rt12colUnifiedLegacyV6.load()
        XCTAssertEqual(stock.count, v6.count)
        let covered = Set(FirmwareIdentity.rt12colUnifiedV6Sites.flatMap { site in
            site.offset..<(site.offset + site.length)
        })
        let changedApplication = Set((0x450..<v6.count).filter { stock[$0] != v6[$0] })
        XCTAssertFalse(changedApplication.isEmpty)
        XCTAssertTrue(changedApplication.isSubset(of: covered))
        XCTAssertEqual(covered.count, 335)
    }

    func testRT12COLV7FingerprintCoversEveryChangedApplicationByte() throws {
        let stock = try BundledFirmware.rt12colHealth.load()
        let v7 = try BundledFirmware.rt12colUnified.load()
        XCTAssertEqual(stock.count, v7.count)
        let covered = Set(FirmwareIdentity.rt12colUnifiedSites.flatMap { site in
            site.offset..<(site.offset + site.length)
        })
        let changedApplication = Set((0x450..<v7.count).filter { stock[$0] != v7[$0] })
        XCTAssertFalse(changedApplication.isEmpty)
        XCTAssertTrue(changedApplication.isSubset(of: covered))
        XCTAssertEqual(covered.count, 335)
    }

    func testRT12COLV8FingerprintCoversEveryChangedApplicationByte() throws {
        let stock = try BundledFirmware.rt12colHealth.load()
        let v8 = try BundledFirmware.rt12colUnifiedHID.load()
        XCTAssertEqual(stock.count, v8.count)
        let covered = Set(FirmwareIdentity.rt12colUnifiedHIDSites.flatMap { site in
            site.offset..<(site.offset + site.length)
        })
        let changedApplication = Set((0x450..<v8.count).filter { stock[$0] != v8[$0] })
        XCTAssertFalse(changedApplication.isEmpty)
        XCTAssertTrue(changedApplication.isSubset(of: covered))
        XCTAssertEqual(covered.count, 423)
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
