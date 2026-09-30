import XCTest
import Combine
import SwiftData
@testable import R02Ring

@MainActor
final class UnifiedModeTests: XCTestCase {
    func testGestureAutoReturnPolicyDefaultsOffAndMapsVisibleDurations() {
        XCTAssertNil(GestureAutoReturn.off.seconds)
        XCTAssertEqual(GestureAutoReturn.oneMinute.seconds, 60)
        XCTAssertEqual(GestureAutoReturn.fiveMinutes.seconds, 300)
        XCTAssertEqual(GestureAutoReturn.fifteenMinutes.seconds, 900)
        XCTAssertEqual(GestureAutoReturn.thirtyMinutes.seconds, 1_800)
        XCTAssertEqual(GestureAutoReturn.allCases.map(\.title),
                       ["Off", "1 minute", "5 minutes", "15 minutes", "30 minutes"])
    }
    final class A1Link: A1ModeLink {
        var isReady = true
        var writes: [Data] = []
        var onWrite: ((Data) -> Void)?
        func writeUART(_ data: Data) throws {
            guard isReady else { throw RingProtocolError.notReady }
            writes.append(data)
            onWrite?(data)
        }
    }

    final class Transport: UnifiedModeTransport {
        var current = ModeStatus(bootID: 1, session: 0, mode: .health, charging: false)
        var renewals = 0
        var mismatch = false
        var offered: FirmwareCapabilities?
        var statusCalls = 0
        var setCalls = 0
        var onSet: (() -> Void)?
        var onRenew: (() -> Void)?
        func capabilities() async throws -> FirmwareCapabilities {
            offered ?? .init(protocolVersion: 1, healthDefault: true, darkGesture: true,
                  sequencedMotion: true, leaseSeconds: 30, sampleRate: 25)
        }
        func status(requestID: UInt32) async throws -> ModeReply {
            statusCalls += 1
            return .init(requestID: requestID, status: current)
        }
        func setGesture(_ enabled: Bool, requestID: UInt32) async throws -> ModeReply {
            setCalls += 1
            current = .init(bootID: 1, session: enabled ? 1 : 0, mode: enabled ? .gesture : .health, charging: false)
            onSet?()
            return .init(requestID: mismatch ? requestID + 1 : requestID, status: current)
        }
        func renew(session: UInt32, processedSequence: UInt32, requestID: UInt32) async throws -> ModeReply {
            renewals += 1
            onRenew?()
            return .init(requestID: mismatch ? requestID + 1 : requestID, status: current)
        }
    }

    func testNoSpeculativeCapabilityQueriesOrLegacyCommands() async {
        let coordinator = UnifiedModeCoordinator(gate: RingOperationGate())
        XCTAssertFalse(coordinator.available)
        XCTAssertNil(coordinator.status)
        do { try await coordinator.setGesture(true); XCTFail("unapproved firmware") } catch {}
    }

    func testExactA1TransportRequiresFreshMotionAndRestoresHealthWithBothStops() async throws {
        let link = A1Link()
        let transport = A1UnifiedModeTransport(link: link, charging: { false }, connectionID: 7)
        let start = Task { try await transport.setGesture(true, requestID: 11) }
        try await Task.sleep(for: .milliseconds(10))
        for value: UInt8 in 1...3 {
            var packet = ColmiR02Protocol.packet(command: 0xa1, payload: [0x03, value, 0, 0, 0, 0, 0])
            packet[15] = ColmiR02Protocol.checksum(packet.prefix(15))
            transport.receiveMotion(packet, at: ProcessInfo.processInfo.systemUptime)
        }
        let reply = try await start.value
        XCTAssertEqual(reply.requestID, 11)
        XCTAssertEqual(reply.status.mode, .gesture)
        XCTAssertEqual(Array(link.writes.first!.prefix(2)), [0xa1, 0x04])

        var delivered: (UInt32, UInt32)?
        transport.onMotion = { _, session, sequence, _ in delivered = (session, sequence) }
        let packet = ColmiR02Protocol.packet(command: 0xa1, payload: [0x03, 4, 0, 0, 0, 0, 0])
        transport.receiveMotion(packet, at: ProcessInfo.processInfo.systemUptime)
        XCTAssertEqual(delivered?.0, reply.status.session)
        XCTAssertEqual(delivered?.1, 4)

        let stopped = try await transport.setGesture(false, requestID: 12)
        XCTAssertEqual(stopped.status.mode, .health)
        XCTAssertEqual(link.writes.suffix(2).map { Array($0.prefix(2)) },
                       [[0xa1, 0x05], [0xa1, 0x02]])
    }

    func testHIDActionsShareTheModeWriteLaneAndFailClosedOutsideFreshGesture() async throws {
        let link = A1Link()
        let transport = A1UnifiedModeTransport(
            link: link, charging: { false }, firmwareLeaseSeconds: 10, connectionID: 70
        )
        do {
            try await transport.sendHIDCommand(.init(code: 0x00))
            XCTFail("Health must reject HID")
        } catch {
            guard let error = error as? RingProtocolError, case .busy = error else {
                return XCTFail("unexpected error: \(error)")
            }
        }

        let start = Task { try await transport.setGesture(true, requestID: 1) }
        try await Task.sleep(for: .milliseconds(10))
        for value: UInt8 in 1...3 {
            transport.receiveMotion(
                ColmiR02Protocol.packet(command: 0xa1,
                                        payload: [0x03, value, 0, 0, 0, 0, 0]),
                at: ProcessInfo.processInfo.systemUptime
            )
        }
        _ = try await start.value
        let volumeUp = try XCTUnwrap(RingHIDAction.volumeUp.command(hidVersion: 8))
        try await transport.sendHIDCommand(volumeUp)
        XCTAssertEqual(link.writes.last, ColmiR02Protocol.hidActionPacket(volumeUp))

        _ = try await transport.setGesture(false, requestID: 2)
        let countAfterStop = link.writes.count
        do {
            try await transport.sendHIDCommand(.init(code: 0x01))
            XCTFail("Health must reject HID")
        } catch {
            guard let error = error as? RingProtocolError, case .busy = error else {
                return XCTFail("unexpected error: \(error)")
            }
        }
        XCTAssertEqual(link.writes.count, countAfterStop)
    }

    func testHIDActionWaitsForRenewalThenUsesTheSameWriteLane() async throws {
        let link = A1Link()
        let transport = A1UnifiedModeTransport(
            link: link, charging: { false }, firmwareLeaseSeconds: 10, connectionID: 71
        )
        var timestamp = ProcessInfo.processInfo.systemUptime - 0.36
        let start = Task { try await transport.setGesture(true, requestID: 1) }
        try await Task.sleep(for: .milliseconds(10))
        for value: UInt8 in 1...10 {
            transport.receiveMotion(
                ColmiR02Protocol.packet(command: 0xa1, payload: [0x03, value]),
                at: timestamp
            )
            timestamp += 0.04
        }
        let started = try await start.value
        let renewal = Task {
            try await transport.renew(
                session: started.status.session, processedSequence: 10, requestID: 2
            )
        }
        try await Task.sleep(for: .milliseconds(170))
        XCTAssertEqual(link.writes.filter { $0.first == 0xa1 }.count, 2)

        let command = RingHIDCommand(code: 0xD1)
        let action = Task { try await transport.sendHIDCommand(command) }
        try await Task.sleep(for: .milliseconds(30))
        XCTAssertFalse(link.writes.contains(ColmiR02Protocol.hidActionPacket(command)),
                       "the action must wait while renewal is collecting evidence")

        for value: UInt8 in 11...20 {
            transport.receiveMotion(
                ColmiR02Protocol.packet(command: 0xa1, payload: [0x03, value]),
                at: timestamp
            )
            timestamp += 0.04
        }
        _ = try await renewal.value
        try await action.value
        XCTAssertEqual(link.writes.last, ColmiR02Protocol.hidActionPacket(command))
    }

    func testStopWithdrawsHIDActionQueuedBehindRenewal() async throws {
        let link = A1Link()
        let transport = A1UnifiedModeTransport(
            link: link, charging: { false }, firmwareLeaseSeconds: 10, connectionID: 72
        )
        var timestamp = ProcessInfo.processInfo.systemUptime - 0.36
        let start = Task { try await transport.setGesture(true, requestID: 1) }
        try await Task.sleep(for: .milliseconds(10))
        for value: UInt8 in 1...10 {
            transport.receiveMotion(
                ColmiR02Protocol.packet(command: 0xa1, payload: [0x03, value]),
                at: timestamp
            )
            timestamp += 0.04
        }
        let started = try await start.value
        let renewal = Task {
            try await transport.renew(
                session: started.status.session, processedSequence: 10, requestID: 2
            )
        }
        try await Task.sleep(for: .milliseconds(170))

        let command = RingHIDCommand(code: 0xD1)
        let action = Task { try await transport.sendHIDCommand(command) }
        try await Task.sleep(for: .milliseconds(20))
        do {
            _ = try await transport.setGesture(false, requestID: 3)
            XCTFail("the renewal still owns the mode gate")
        } catch RingProtocolError.busy {} catch {
            XCTFail("unexpected stop error: \(error)")
        }
        do {
            try await action.value
            XCTFail("a stopped session emitted its queued HID action")
        } catch RingProtocolError.busy {} catch {
            XCTFail("unexpected action error: \(error)")
        }
        XCTAssertFalse(link.writes.contains(ColmiR02Protocol.hidActionPacket(command)))

        for value: UInt8 in 11...20 {
            transport.receiveMotion(
                ColmiR02Protocol.packet(command: 0xa1, payload: [0x03, value]),
                at: timestamp
            )
            timestamp += 0.04
        }
        _ = try await renewal.value
        _ = try await transport.setGesture(false, requestID: 4)
        XCTAssertFalse(link.writes.contains(ColmiR02Protocol.hidActionPacket(command)))
        XCTAssertEqual(transport.currentStatus.mode, .health)
    }

    /// A heal's entry follows its own stop by one write slot. Notifications
    /// still in flight from the stream it stopped arrive in that slot and must
    /// never confirm the entry: only packets after A1 04 count.
    func testAnEntryIsConfirmedOnlyByPacketsAfterItsA104() async throws {
        let link = A1Link()
        let transport = A1UnifiedModeTransport(link: link, charging: { false }, connectionID: 12)
        _ = try await transport.status(requestID: 1) // the stop half: A1 05, A1 02
        let stops = link.writes.count
        func motion(_ value: UInt8) -> Data {
            ColmiR02Protocol.packet(command: 0xa1, payload: [0x03, value, 0, 0, 0, 0, 0])
        }
        final class Box { var resolved = false }
        let box = Box()
        let start = Task { () throws -> ModeReply in
            let reply = try await transport.setGesture(true, requestID: 2)
            box.resolved = true
            return reply
        }
        try await Task.sleep(for: .milliseconds(20))
        XCTAssertEqual(link.writes.count, stops, "A1 04 waits for its write slot")
        for value: UInt8 in 1...4 { transport.receiveMotion(motion(value), at: ProcessInfo.processInfo.systemUptime) }
        try await Task.sleep(for: .milliseconds(10))
        XCTAssertFalse(box.resolved, "the stopped stream's backlog never confirms the entry")
        let written = await GestureIntentLogic.waitUntil(timeout: 1, poll: .milliseconds(5)) { link.writes.count > stops }
        XCTAssertTrue(written)
        XCTAssertEqual(link.writes.last, ColmiR02Protocol.startRawMotionPacket)
        XCTAssertFalse(box.resolved)
        for value: UInt8 in 5...7 { transport.receiveMotion(motion(value), at: ProcessInfo.processInfo.systemUptime) }
        let reply = try await start.value
        XCTAssertEqual(reply.status.mode, .gesture)
    }

    func testAHeartbeatThatIsNotDueRenewsNothingAndSaysSo() async throws {
        let transport = Transport(), coordinator = UnifiedModeCoordinator(gate: RingOperationGate())
        try await coordinator.attach(transport)
        try await coordinator.setGesture(true)
        coordinator.didProcess(session: 1, sequence: 100, at: 5)
        let renewed = try await coordinator.heartbeat(at: 5.1)
        XCTAssertEqual(renewed, .renewed)
        XCTAssertEqual(coordinator.lastHeartbeatOutcome, .renewed)
        coordinator.didProcess(session: 1, sequence: 200, at: 8)
        let early = try await coordinator.heartbeat(at: 8.1)
        guard case .notDue(let remaining) = early else { return XCTFail("renewed early: \(early)") }
        XCTAssertEqual(remaining, 2, accuracy: 1e-9)
        XCTAssertEqual(coordinator.lastHeartbeatOutcome, early)
        XCTAssertEqual(transport.renewals, 1, "nothing was written or checked")
        _ = try await coordinator.heartbeat(now: { 8.1 })
        XCTAssertNotEqual(coordinator.lastHeartbeatOutcome, .renewed, "heartbeat(now:) reports it too")
    }

    func testExactA1CapabilitiesAreNarrowAndChargingBlocksStart() async throws {
        let link = A1Link()
        let transport = A1UnifiedModeTransport(link: link, charging: { true }, connectionID: 8)
        let capabilities = try await transport.capabilities()
        XCTAssertTrue(capabilities.supported)
        XCTAssertEqual(capabilities.profile, .exactA1)
        XCTAssertFalse(capabilities.sequencedMotion)
        XCTAssertEqual(capabilities.leaseSeconds, 0)
        do { _ = try await transport.setGesture(true, requestID: 1); XCTFail("charging") }
        catch FirmwareSwitchError.charging {} catch { XCTFail("unexpected error: \(error)") }
        XCTAssertTrue(link.writes.isEmpty)
    }

    func testRT12ExactA1AddsVolatileMotionHoldAndReleasesItAfterBothStops() async throws {
        let link = A1Link()
        let transport = A1UnifiedModeTransport(
            link: link, charging: { false }, requiresMotionHold: true, connectionID: 9
        )
        let start = Task { try await transport.setGesture(true, requestID: 21) }
        try await Task.sleep(for: .milliseconds(320))
        XCTAssertEqual(link.writes.prefix(2), [
            ColmiR02Protocol.startRawMotionPacket,
            ColmiR02Protocol.gestureMotionHoldPacket(enabled: true),
        ])
        for value: UInt8 in 1...3 {
            transport.receiveMotion(
                ColmiR02Protocol.packet(command: 0xa1, payload: [0x03, value]),
                at: ProcessInfo.processInfo.systemUptime
            )
        }
        let started = try await start.value
        XCTAssertEqual(started.status.mode, .gesture)
        _ = try await transport.setGesture(false, requestID: 22)
        XCTAssertEqual(Array(link.writes.suffix(3)), [
            ColmiR02Protocol.rawSensorPacket(0x05),
            ColmiR02Protocol.rawSensorPacket(0x02),
            ColmiR02Protocol.gestureMotionHoldPacket(enabled: false),
        ])
    }

    func testCorrectedExactA1RenewalWaitsForContinuousFreshBoundary() async throws {
        let link = A1Link()
        let transport = A1UnifiedModeTransport(
            link: link, charging: { false }, firmwareLeaseSeconds: 10, connectionID: 10
        )
        let capabilities = try await transport.capabilities()
        XCTAssertTrue(capabilities.supported)
        XCTAssertEqual(capabilities.leaseSeconds, 10)

        var timestamp = ProcessInfo.processInfo.systemUptime - 0.36
        let start = Task { try await transport.setGesture(true, requestID: 31) }
        try await Task.sleep(for: .milliseconds(10))
        for value: UInt8 in 1...3 {
            transport.receiveMotion(
                ColmiR02Protocol.packet(command: 0xa1, payload: [0x03, value]),
                at: timestamp
            )
            timestamp += 0.04
        }
        let started = try await start.value
        XCTAssertEqual(started.status.mode, .gesture)
        XCTAssertEqual(link.writes, [ColmiR02Protocol.startRawMotionPacket])

        for value: UInt8 in 4...10 {
            transport.receiveMotion(
                ColmiR02Protocol.packet(command: 0xa1, payload: [0x03, value]),
                at: timestamp
            )
            timestamp += 0.04
        }
        let renewal = Task {
            try await transport.renew(
                session: started.status.session, processedSequence: 10, requestID: 32
            )
        }
        try await Task.sleep(for: .milliseconds(170))
        XCTAssertEqual(link.writes, [
            ColmiR02Protocol.startRawMotionPacket,
            ColmiR02Protocol.startRawMotionPacket,
        ])
        for value: UInt8 in 11...20 {
            transport.receiveMotion(
                ColmiR02Protocol.packet(command: 0xa1, payload: [0x03, value]),
                at: timestamp
            )
            timestamp += 0.04
        }
        let renewed = try await renewal.value
        XCTAssertEqual(renewed.requestID, 32)
        let metrics = try XCTUnwrap(transport.lastRenewalMetrics)
        XCTAssertEqual(metrics.baselineMedianSpacing, 0.04, accuracy: 1e-6)
        XCTAssertEqual(metrics.renewalMedianSpacing, 0.04, accuracy: 1e-6)
        XCTAssertEqual(metrics.renewalDuplicateFraction, 0, accuracy: 1e-12)
    }

    func testRenewalArmsPostBoundaryCollectorBeforeUARTWriteCanReturnMotion() async throws {
        let link = A1Link()
        let transport = A1UnifiedModeTransport(
            link: link, charging: { false }, firmwareLeaseSeconds: 10, connectionID: 13
        )
        var timestamp = ProcessInfo.processInfo.systemUptime - 0.36
        let start = Task { try await transport.setGesture(true, requestID: 61) }
        try await Task.sleep(for: .milliseconds(10))
        for value: UInt8 in 1...10 {
            transport.receiveMotion(
                ColmiR02Protocol.packet(command: 0xa1, payload: [0x03, value]),
                at: timestamp
            )
            timestamp += 0.04
        }
        let started = try await start.value

        var injected = false
        link.onWrite = { packet in
            guard !injected, Array(packet.prefix(2)) == [0xa1, 0x04] else { return }
            injected = true
            transport.receiveMotion(
                ColmiR02Protocol.packet(command: 0xa1, payload: [0x03, 11]),
                at: timestamp
            )
            timestamp += 0.04
        }
        let renewal = Task {
            try await transport.renew(
                session: started.status.session, processedSequence: 10, requestID: 62
            )
        }
        try await Task.sleep(for: .milliseconds(170))
        for value: UInt8 in 12...20 {
            transport.receiveMotion(
                ColmiR02Protocol.packet(command: 0xa1, payload: [0x03, value]),
                at: timestamp
            )
            timestamp += 0.04
        }
        let renewed = try await renewal.value
        XCTAssertEqual(renewed.requestID, 62)
        XCTAssertTrue(injected)
        let metrics = try XCTUnwrap(transport.lastRenewalMetrics)
        XCTAssertEqual(metrics.boundarySpacing, 0.04, accuracy: 1e-6)
        XCTAssertEqual(metrics.renewalDuplicateFraction, 0, accuracy: 1e-12)
    }

    func testCorrectedExactA1RenewalRejectsDuplicateBurstAndKeepsGesture() async throws {
        let link = A1Link()
        let transport = A1UnifiedModeTransport(
            link: link, charging: { false }, firmwareLeaseSeconds: 10, connectionID: 11
        )
        var timestamp = ProcessInfo.processInfo.systemUptime - 0.36
        let start = Task { try await transport.setGesture(true, requestID: 41) }
        try await Task.sleep(for: .milliseconds(10))
        for value: UInt8 in 1...10 {
            transport.receiveMotion(
                ColmiR02Protocol.packet(command: 0xa1, payload: [0x03, value]),
                at: timestamp
            )
            timestamp += 0.04
        }
        let started = try await start.value
        let renewal = Task {
            try await transport.renew(
                session: started.status.session, processedSequence: 10, requestID: 42
            )
        }
        try await Task.sleep(for: .milliseconds(170))
        let duplicate = ColmiR02Protocol.packet(command: 0xa1, payload: [0x03, 10])
        for _ in 0..<10 {
            transport.receiveMotion(duplicate, at: timestamp)
            timestamp += 0.04
        }
        do {
            _ = try await renewal.value
            XCTFail("duplicate burst crossed renewal gate")
        } catch UnifiedModeError.renewalBoundary {} catch {
            XCTFail("unexpected error: \(error)")
        }
        let metrics = try XCTUnwrap(transport.lastRenewalMetrics)
        XCTAssertEqual(metrics.renewalDuplicateFraction, 1, accuracy: 1e-12)
        // Sticky sessions: the gate still rejects the frozen burst, but a
        // renewal failure never calls the stop path. The owner heals a bad
        // source with a fresh start; the lease is the hardware backstop.
        try await Task.sleep(for: .milliseconds(320))
        XCTAssertEqual(link.writes.map { Array($0.prefix(2)) }, [[0xa1, 0x04], [0xa1, 0x04]],
                       "entry and renewal only: no A1 05 or A1 02")
        XCTAssertEqual(transport.currentStatus.mode, .gesture)
    }

    func testA1RenewalCannotWriteOutsideActiveGesture() async {
        let link = A1Link()
        let transport = A1UnifiedModeTransport(
            link: link, charging: { false }, firmwareLeaseSeconds: 10, connectionID: 12
        )
        do {
            _ = try await transport.renew(session: 0, processedSequence: 1, requestID: 51)
            XCTFail("renewed outside Gesture")
        } catch {}
        XCTAssertTrue(link.writes.isEmpty)
    }

    func testLeaseRequiresFreshProcessedSequenceNotMerelyConnection() async throws {
        let transport = Transport(), coordinator = UnifiedModeCoordinator(gate: RingOperationGate())
        try await coordinator.attach(transport)
        XCTAssertEqual(coordinator.status?.mode, .health)
        try await coordinator.setGesture(true)
        do { try await coordinator.heartbeat(at: 5); XCTFail("no processing") } catch {}
        coordinator.didProcess(session: 1, sequence: 100, at: 5)
        try await coordinator.heartbeat(at: 5.1)
        XCTAssertEqual(transport.renewals, 1)
        coordinator.didProcess(session: 1, sequence: 100, at: 10) // same packet cannot renew
        do { try await coordinator.heartbeat(at: 10.2); XCTFail("stale processing") } catch {}
        XCTAssertEqual(transport.renewals, 1)
        coordinator.didProcess(session: 1, sequence: 200, at: 10.2)
        try await coordinator.heartbeat(at: 10.3)
        XCTAssertEqual(transport.renewals, 2)
        coordinator.disconnected()
        XCTAssertNil(coordinator.status) // do not pretend the unreachable ring confirmed Health
        XCTAssertFalse(coordinator.available)
    }

    func testMismatchedReplyInvalidatesControlAndGateSerializesOwners() async throws {
        let gate = RingOperationGate(), transport = Transport()
        let coordinator = UnifiedModeCoordinator(gate: gate)
        let owner = try XCTUnwrap(gate.begin(.sync))
        do { try await coordinator.attach(transport); XCTFail("sync owns ring") } catch {}
        gate.end(UUID())
        XCTAssertNotNil(gate.owner)
        gate.end(owner)
        try await coordinator.attach(transport)
        transport.mismatch = true
        do { try await coordinator.setGesture(true); XCTFail("mismatched reply") } catch {}
        XCTAssertFalse(coordinator.available)
        XCTAssertNil(gate.owner)
    }

    func testNewConnectionDoesNotAdoptPreviousGestureSession() async throws {
        let transport = Transport()
        transport.current = .init(bootID: 1, session: 1, mode: .gesture, charging: false)
        let coordinator = UnifiedModeCoordinator(gate: RingOperationGate())
        try await coordinator.attach(transport)
        XCTAssertEqual(coordinator.status?.mode, .health)
        XCTAssertEqual(transport.renewals, 0)
    }

    func testEveryUnsupportedCapabilityRefusesBeforeStatusOrModeCommands() async {
        for field in 0..<6 {
            let transport = Transport(), coordinator = UnifiedModeCoordinator(gate: RingOperationGate())
            transport.offered = .init(protocolVersion: field == 0 ? 2 : 1, healthDefault: field != 1,
                                      darkGesture: field != 2, sequencedMotion: field != 3,
                                      leaseSeconds: field == 4 ? 60 : 30, sampleRate: field == 5 ? 1 : 25)
            do { try await coordinator.attach(transport); XCTFail("unsupported capability \(field)") } catch {}
            XCTAssertFalse(coordinator.available)
            XCTAssertNil(coordinator.status)
            XCTAssertEqual(transport.statusCalls, 0)
            XCTAssertEqual(transport.setCalls, 0)
        }
    }

    func testChargingRefusesGestureWithoutSendingCommand() async throws {
        let transport = Transport(), gate = RingOperationGate()
        transport.current = .init(bootID: 1, session: 0, mode: .health, charging: true)
        let coordinator = UnifiedModeCoordinator(gate: gate)
        try await coordinator.attach(transport)
        do { try await coordinator.setGesture(true); XCTFail("charging") } catch {}
        XCTAssertEqual(transport.setCalls, 0)
        XCTAssertEqual(coordinator.status?.mode, .health)
        XCTAssertNil(gate.owner)
    }

    func testDisconnectDuringModeReplyCannotResurrectSession() async throws {
        let transport = Transport(), gate = RingOperationGate()
        let coordinator = UnifiedModeCoordinator(gate: gate)
        try await coordinator.attach(transport)
        transport.onSet = { coordinator.disconnected() }
        do { try await coordinator.setGesture(true); XCTFail("late disconnected response") } catch {}
        XCTAssertFalse(coordinator.available)
        XCTAssertNil(coordinator.status)
        XCTAssertNil(gate.owner)
    }

    func testRenewalRejectsChangedBootSessionModeAndCharging() async throws {
        let wrong = [ModeStatus(bootID: 2, session: 1, mode: .gesture, charging: false),
                     ModeStatus(bootID: 1, session: 2, mode: .gesture, charging: false),
                     ModeStatus(bootID: 1, session: 1, mode: .fault, charging: false),
                     ModeStatus(bootID: 1, session: 1, mode: .health, charging: false),
                     ModeStatus(bootID: 1, session: 1, mode: .gesture, charging: true)]
        for status in wrong {
            let transport = Transport(), gate = RingOperationGate()
            let coordinator = UnifiedModeCoordinator(gate: gate)
            try await coordinator.attach(transport)
            try await coordinator.setGesture(true)
            var observed: [ModeStatus?] = [], published: [ModeStatus?] = []
            coordinator.onModeChange = { _, next in observed.append(next) }
            let subscription = coordinator.$status.dropFirst().sink { published.append($0) }
            defer { subscription.cancel() }
            coordinator.didProcess(session: 1, sequence: 1, at: 10)
            transport.onRenew = { transport.current = status }
            do { try await coordinator.heartbeat(at: 10); XCTFail("invalid renewal \(status)") } catch {}
            XCTAssertFalse(coordinator.available)
            XCTAssertNil(coordinator.status)
            XCTAssertNil(gate.owner)
            XCTAssertEqual(observed, [nil], "Rejected status must never reach mode observers")
            XCTAssertEqual(published, [nil], "Rejected status must never reach Combine subscribers")
        }
    }

    func testSequenceWrapPermittedButHalfRangeReplayAndWrongSessionCannotRenew() async throws {
        let transport = Transport(), coordinator = UnifiedModeCoordinator(gate: RingOperationGate())
        try await coordinator.attach(transport)
        try await coordinator.setGesture(true)
        coordinator.didProcess(session: 1, sequence: UInt32.max, at: 10)
        try await coordinator.heartbeat(at: 10)
        coordinator.didProcess(session: 1, sequence: 0, at: 15)
        try await coordinator.heartbeat(at: 15)
        XCTAssertEqual(transport.renewals, 2)
        coordinator.didProcess(session: 1, sequence: 0x80000000, at: 20)
        coordinator.didProcess(session: 2, sequence: 1, at: 20)
        coordinator.didProcess(session: 1, sequence: UInt32.max, at: 20)
        do { try await coordinator.heartbeat(at: 20); XCTFail("replay/wrong session") } catch {}
        XCTAssertEqual(transport.renewals, 2)
    }

    func testSuspensionAndFutureTimestampsDoNotRenew() async throws {
        let transport = Transport(), coordinator = UnifiedModeCoordinator(gate: RingOperationGate())
        try await coordinator.attach(transport)
        try await coordinator.setGesture(true)
        coordinator.didProcess(session: 1, sequence: 1, at: 10)
        do { try await coordinator.heartbeat(at: 50); XCTFail("suspended processing") } catch {}
        coordinator.didProcess(session: 1, sequence: 2, at: 60)
        do { try await coordinator.heartbeat(at: 55); XCTFail("future sample") } catch {}
        XCTAssertEqual(transport.renewals, 0)
    }

    func testInvalidRenewalMustNotPublishHealthBeforeItIsRejected() async throws {
        let transport = Transport(), coordinator = UnifiedModeCoordinator(gate: RingOperationGate())
        try await coordinator.attach(transport)
        try await coordinator.setGesture(true)
        let container = try ModelContainer(for: HealthCoverageRecord.self,
                                           configurations: ModelConfiguration(isStoredInMemoryOnly: true))
        let store = HealthCoverageStore(context: container.mainContext)
        let start = Date(timeIntervalSince1970: 1_790_100_000)
        try store.observe(deviceID: "fixture", mode: .gesture, firmware: "fixture", at: start)
        var published: [RingRuntimeMode] = []
        coordinator.onModeChange = { _, next in
            published.append(next?.mode ?? .unknown)
            // Same persistence side effect as AppModel.runtimeModeChanged.
            guard let next else { return }
            do {
                try store.observe(deviceID: "fixture", mode: next.mode, firmware: "fixture",
                                  at: start.addingTimeInterval(10))
            } catch { XCTFail("Could not persist coverage: \(error)") }
        }
        coordinator.didProcess(session: 1, sequence: 1, at: 10)
        transport.onRenew = {
            transport.current = .init(bootID: 2, session: 0, mode: .health, charging: false)
        }
        do { try await coordinator.heartbeat(at: 10); XCTFail("new boot invalidates this renewal") } catch {}
        XCTAssertFalse(published.contains(.health), "An unvalidated reply must not close the health-coverage gap")
        XCTAssertNil(coordinator.status)
        let reloaded = HealthCoverageStore(context: ModelContext(container))
        let intervals = try reloaded.uncertainIntervals(deviceID: "fixture")
        XCTAssertEqual(intervals.count, 1)
        XCTAssertEqual(intervals.first?.started, start)
        XCTAssertNil(intervals.first?.ended, "Rejected renewal must leave the persisted gap open")
        XCTAssertFalse(try XCTUnwrap(intervals.first).opticalMeasurementsAvailable)
        XCTAssertFalse(try XCTUnwrap(intervals.first).stepsAndSleepVerified)
    }

    func testUncorrelatedAndDisconnectedRenewalsNeverPublish() async throws {
        for disconnect in [false, true] {
            let transport = Transport(), gate = RingOperationGate()
            let coordinator = UnifiedModeCoordinator(gate: gate)
            try await coordinator.attach(transport)
            try await coordinator.setGesture(true)
            var published: [ModeStatus?] = []
            let subscription = coordinator.$status.dropFirst().sink { published.append($0) }
            defer { subscription.cancel() }
            coordinator.didProcess(session: 1, sequence: 1, at: 10)
            if disconnect { transport.onRenew = { coordinator.disconnected() } }
            else { transport.mismatch = true }
            do { try await coordinator.heartbeat(at: 10); XCTFail("Uncorrelated renewal") }
            catch { XCTAssertEqual(error as? UnifiedModeError, .uncorrelated) }
            XCTAssertEqual(published, [nil])
            XCTAssertFalse(coordinator.available)
            XCTAssertNil(gate.owner)
        }
    }

    func testValidRenewalKeepsCoverageOpenUntilConfirmedHealthReturn() async throws {
        let transport = Transport(), coordinator = UnifiedModeCoordinator(gate: RingOperationGate())
        let container = try ModelContainer(for: HealthCoverageRecord.self,
                                           configurations: ModelConfiguration(isStoredInMemoryOnly: true))
        let store = HealthCoverageStore(context: container.mainContext)
        var now = Date(timeIntervalSince1970: 1_790_100_000)
        coordinator.onModeChange = { _, next in
            guard let next else { return }
            do { try store.observe(deviceID: "fixture", mode: next.mode, firmware: "fixture", at: now) }
            catch { XCTFail("Could not persist coverage: \(error)") }
        }
        try await coordinator.attach(transport)
        try await coordinator.setGesture(true)
        coordinator.didProcess(session: 1, sequence: 1, at: 10)
        now = now.addingTimeInterval(10)
        try await coordinator.heartbeat(at: 10)
        XCTAssertEqual(transport.renewals, 1)
        XCTAssertEqual(coordinator.status?.mode, .gesture)
        XCTAssertNil(try store.uncertainIntervals(deviceID: "fixture").first?.ended)
        now = now.addingTimeInterval(10)
        try await coordinator.setGesture(false)
        let reloaded = HealthCoverageStore(context: ModelContext(container))
        XCTAssertEqual(try reloaded.uncertainIntervals(deviceID: "fixture").first?.ended, now)
    }
}
