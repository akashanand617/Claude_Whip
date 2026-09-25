import XCTest
import Combine
import SwiftData
@testable import R02Ring

@MainActor
final class UnifiedModeTests: XCTestCase {
    final class A1Link: A1ModeLink {
        var isReady = true
        var writes: [Data] = []
        func writeUART(_ data: Data) throws {
            guard isReady else { throw RingProtocolError.notReady }
            writes.append(data)
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
