import XCTest
@testable import R02Ring

@MainActor
private final class RecordingLink: A1ModeLink {
    var isReady = true
    var writes: [Data] = []
    func writeUART(_ data: Data) throws {
        guard isReady else { throw RingProtocolError.notReady }
        writes.append(data)
    }
}

/// Mirrors the A1 transport's status contract: a status read restores Health.
@MainActor
private final class FailingRenewTransport: UnifiedModeTransport {
    var current = ModeStatus(bootID: 1, session: 0, mode: .health, charging: false)
    var renewError: Error? = UnifiedModeError.renewalBoundary
    var statusCalls = 0

    func capabilities() async throws -> FirmwareCapabilities {
        .init(protocolVersion: 1, healthDefault: true, darkGesture: true,
              sequencedMotion: true, leaseSeconds: 30, sampleRate: 25)
    }
    func status(requestID: UInt32) async throws -> ModeReply {
        statusCalls += 1
        current = .init(bootID: 1, session: 0, mode: .health, charging: false)
        return .init(requestID: requestID, status: current)
    }
    func setGesture(_ enabled: Bool, requestID: UInt32) async throws -> ModeReply {
        current = .init(bootID: 1, session: enabled ? current.session + 1 : 0,
                        mode: enabled ? .gesture : .health, charging: false)
        return .init(requestID: requestID, status: current)
    }
    func renew(session: UInt32, processedSequence: UInt32, requestID: UInt32) async throws -> ModeReply {
        if let renewError { throw renewError }
        return .init(requestID: requestID, status: current)
    }
}

@MainActor
final class ModeRecoveryTests: XCTestCase {
    private let lostControl = ModeRecoveryPolicy.Inputs(
        linkReady: true, unifiedFirmwareInstalled: true, modeControlAvailable: false,
        transportIsCurrent: true, attachInFlight: false, firmwareSwitching: false, attempts: 0
    )

    func testPolicyReattachesOnlyWhenControlIsLostOverALiveLink() {
        XCTAssertTrue(ModeRecoveryPolicy.shouldReattach(lostControl))
        let blockers: [(String, (inout ModeRecoveryPolicy.Inputs) -> Void)] = [
            ("link down", { $0.linkReady = false }),
            ("not unified", { $0.unifiedFirmwareInstalled = false }),
            ("still available", { $0.modeControlAvailable = true }),
            ("replaced transport", { $0.transportIsCurrent = false }),
            ("attach in flight", { $0.attachInFlight = true }),
            ("firmware switching", { $0.firmwareSwitching = true }),
            ("attempts exhausted", { $0.attempts = ModeRecoveryPolicy.maxAttempts }),
        ]
        for (name, block) in blockers {
            var inputs = lostControl
            block(&inputs)
            XCTAssertFalse(ModeRecoveryPolicy.shouldReattach(inputs), name)
        }
        var lastTry = lostControl
        lastTry.attempts = ModeRecoveryPolicy.maxAttempts - 1
        XCTAssertTrue(ModeRecoveryPolicy.shouldReattach(lastTry))
    }

    func testPolicyTruthTableHasExactlyOneReattachingRowPerAttemptBudget() {
        for attempts in 0...(ModeRecoveryPolicy.maxAttempts + 1) {
            var reattaching: [ModeRecoveryPolicy.Inputs] = []
            for bits in 0..<(1 << 6) {
                let inputs = ModeRecoveryPolicy.Inputs(
                    linkReady: bits & 1 != 0, unifiedFirmwareInstalled: bits & 2 != 0,
                    modeControlAvailable: bits & 4 != 0, transportIsCurrent: bits & 8 != 0,
                    attachInFlight: bits & 16 != 0, firmwareSwitching: bits & 32 != 0,
                    attempts: attempts
                )
                if ModeRecoveryPolicy.shouldReattach(inputs) { reattaching.append(inputs) }
            }
            if attempts < ModeRecoveryPolicy.maxAttempts {
                var expected = lostControl
                expected.attempts = attempts
                XCTAssertEqual(reattaching, [expected], "attempts \(attempts)")
            } else {
                XCTAssertTrue(reattaching.isEmpty, "attempts \(attempts)")
            }
        }
    }

    /// A failed renewal's own stop sequence is three writes 150 ms apart (plus
    /// up to one 150 ms write slot); re-attaching earlier would interleave them.
    func testRecoveryDelayOutlastsAnInFlightStopSequence() {
        XCTAssertGreaterThan(ModeRecoveryPolicy.delay, .milliseconds(450))
    }

    /// Sticky sessions: a failed renewal gate is a missed renewal. Control and
    /// Gesture stay, so the owner can retry or heal; only an integrity failure
    /// (a reply for another session) drops control and needs the re-attach.
    func testARenewalGateFailureKeepsControlAndOnlyAnIntegrityFailureNeedsReattach() async throws {
        let gate = RingOperationGate(), transport = FailingRenewTransport()
        let coordinator = UnifiedModeCoordinator(gate: gate)
        var observed: [RingRuntimeMode] = []
        coordinator.onModeChange = { _, next in observed.append(next?.mode ?? .unknown) }
        try await coordinator.attach(transport)
        try await coordinator.setGesture(true)
        coordinator.didProcess(session: 1, sequence: 1, at: 10)
        do { try await coordinator.heartbeat(at: 10); XCTFail("renewal should fail") }
        catch { XCTAssertEqual(error as? UnifiedModeError, .renewalBoundary) }
        XCTAssertTrue(coordinator.available)
        XCTAssertEqual(coordinator.status?.mode, .gesture)
        XCTAssertNil(gate.owner)
        XCTAssertEqual(observed.last, .gesture, "no loss of control was published")
        var inputs = lostControl
        inputs.modeControlAvailable = coordinator.available
        XCTAssertFalse(ModeRecoveryPolicy.shouldReattach(inputs), "nothing to recover")
        // The next heartbeat renews the same session.
        transport.renewError = nil
        coordinator.didProcess(session: 1, sequence: 2, at: 15)
        try await coordinator.heartbeat(at: 15)
        XCTAssertEqual(coordinator.status?.mode, .gesture)

        // A reply naming another session still drops control ...
        coordinator.didProcess(session: 1, sequence: 3, at: 20)
        transport.current = .init(bootID: 1, session: 9, mode: .gesture, charging: false)
        do { try await coordinator.heartbeat(at: 20); XCTFail("a mismatched reply renewed") } catch {}
        XCTAssertEqual(coordinator.lastHeartbeatRejection, "reply_mismatch")
        XCTAssertFalse(coordinator.available)
        XCTAssertNil(coordinator.status)
        XCTAssertNil(gate.owner)
        do { try await coordinator.setGesture(true); XCTFail("stuck until re-attached") }
        catch { XCTAssertEqual(error as? UnifiedModeError, .unavailable) }

        inputs.modeControlAvailable = coordinator.available
        XCTAssertTrue(ModeRecoveryPolicy.shouldReattach(inputs))
        // ... and re-attaching the same transport restores Health and Start.
        try await coordinator.attach(transport)
        XCTAssertTrue(coordinator.available)
        XCTAssertEqual(coordinator.status?.mode, .health)
        XCTAssertEqual(transport.statusCalls, 2)
        XCTAssertEqual(observed.last, .health)
        inputs.modeControlAvailable = coordinator.available
        XCTAssertFalse(ModeRecoveryPolicy.shouldReattach(inputs))

        transport.renewError = nil
        try await coordinator.setGesture(true)
        XCTAssertEqual(coordinator.status?.mode, .gesture)
    }

    func testA1RenewalGuardFailureWritesNothingKeepsControlAndReattachSendsAuditedStops() async throws {
        let link = RecordingLink()
        let transport = A1UnifiedModeTransport(
            link: link, charging: { false }, requiresMotionHold: true,
            firmwareLeaseSeconds: 10, connectionID: 41
        )
        let coordinator = UnifiedModeCoordinator(gate: RingOperationGate())
        let stops = [
            ColmiR02Protocol.rawSensorPacket(0x05),
            ColmiR02Protocol.rawSensorPacket(0x02),
            ColmiR02Protocol.gestureMotionHoldPacket(enabled: false),
        ]
        XCTAssertEqual(stops.map { Array($0.prefix(4)) },
                       [[0xa1, 0x05, 0, 0], [0xa1, 0x02, 0, 0], [0x3b, 0x02, 0x01, 0x00]])
        try await coordinator.attach(transport)
        XCTAssertEqual(link.writes, stops)

        let start = Task { try await coordinator.setGesture(true) }
        // Polled, not a fixed sleep: two spaced writes on a loaded simulator
        // can outlast any fixed wait. Ends well inside the 3 s entry timeout.
        let wrote = await GestureIntentLogic.waitUntil(timeout: 2, poll: .milliseconds(10)) {
            link.writes.count >= stops.count + 2
        }
        XCTAssertTrue(wrote, "A1 04 and 3B 02 01 03 were not written in time")
        XCTAssertEqual(Array(link.writes.dropFirst(stops.count)), [
            ColmiR02Protocol.startRawMotionPacket,
            ColmiR02Protocol.gestureMotionHoldPacket(enabled: true),
        ])
        // Fresh enough to enter Gesture, too old for the transport's renewal guard.
        let stamped = ProcessInfo.processInfo.systemUptime - 1
        for value: UInt8 in 1...3 {
            transport.receiveMotion(ColmiR02Protocol.packet(command: 0xa1, payload: [0x03, value]),
                                    at: stamped + Double(value) * 0.04)
        }
        try await start.value
        XCTAssertEqual(coordinator.status?.mode, .gesture)
        let session = try XCTUnwrap(coordinator.status?.session)

        coordinator.didProcess(session: session, sequence: 3, at: 100)
        let beforeRenewal = link.writes.count
        do { try await coordinator.heartbeat(at: 100.1); XCTFail("stale motion renewed the lease") }
        catch { XCTAssertEqual(error as? UnifiedModeError, .staleStream) }
        XCTAssertEqual(link.writes.count, beforeRenewal, "a renewal guard failure writes nothing, not even stops")
        // Sticky sessions: the guard's refusal is a missed renewal. The owner
        // retries while the lease holds, or heals; control is kept.
        XCTAssertTrue(coordinator.available)
        XCTAssertEqual(coordinator.status?.mode, .gesture)
        XCTAssertEqual(coordinator.status?.session, session)

        // A re-attach (recovery after an integrity failure, or a new
        // connection) still sends exactly the audited stops.
        try await coordinator.attach(transport)
        XCTAssertEqual(Array(link.writes.dropFirst(beforeRenewal)), stops)
        XCTAssertTrue(coordinator.available)
        XCTAssertEqual(coordinator.status?.mode, .health)
        XCTAssertEqual(coordinator.status?.session, 0)
    }

    // MARK: Recovery controller

    /// Lets the controller's recovery task run until `condition` holds.
    private func settle(_ what: String, file: StaticString = #filePath, line: UInt = #line,
                        _ condition: () -> Bool) async {
        for _ in 0..<20_000 {
            if condition() { return }
            await Task.yield()
        }
        XCTFail("never settled: \(what)", file: file, line: line)
    }

    private func immediateController() -> (ModeRecoveryController, events: () -> [ModeRecoveryController.Event]) {
        let controller = ModeRecoveryController(sleep: { _ in await Task.yield() })
        var events: [ModeRecoveryController.Event] = []
        controller.onEvent = { events.append($0) }
        return (controller, { events })
    }

    func testControllerStopsAfterTheAttemptBudget() async {
        let (controller, events) = immediateController()
        var attaches = 0
        var inFlight: [Bool] = []
        controller.onInFlightChange = { inFlight.append($0) }
        XCTAssertTrue(controller.schedule(inputs: { self.lostControl }, attach: {
            attaches += 1
            throw UnifiedModeError.unavailable
        }))
        await settle("budget spent") { attaches == ModeRecoveryPolicy.maxAttempts && !controller.attachInFlight }
        for _ in 0..<50 { await Task.yield() }
        XCTAssertEqual(attaches, ModeRecoveryPolicy.maxAttempts, "no attempt beyond the budget")
        XCTAssertFalse(controller.attachInFlight)
        XCTAssertEqual(controller.attempts, ModeRecoveryPolicy.maxAttempts)
        XCTAssertFalse(controller.schedule(inputs: { self.lostControl }, attach: { attaches += 1 }))
        XCTAssertEqual(events().filter { if case .failed = $0 { return true } else { return false } }.count,
                       ModeRecoveryPolicy.maxAttempts)
        XCTAssertEqual(inFlight.last, false)
    }

    func testASuccessRefillsTheBudget() async {
        let (controller, events) = immediateController()
        var available = false
        var failuresLeft = 2
        var attaches = 0
        let inputs = { () -> ModeRecoveryPolicy.Inputs in
            var inputs = self.lostControl
            inputs.modeControlAvailable = available
            return inputs
        }
        let attach = {
            attaches += 1
            if failuresLeft > 0 { failuresLeft -= 1; throw UnifiedModeError.unavailable }
            available = true
        }
        controller.schedule(inputs: inputs, attach: attach)
        await settle("recovered") { available && !controller.attachInFlight }
        XCTAssertEqual(attaches, 3)
        XCTAssertEqual(controller.attempts, 0)
        XCTAssertEqual(events().last, .recovered)

        // Control is lost again later on the same connection: a fresh budget.
        available = false
        failuresLeft = ModeRecoveryPolicy.maxAttempts - 1
        XCTAssertTrue(controller.schedule(inputs: inputs, attach: attach))
        await settle("recovered again") { available && !controller.attachInFlight }
        XCTAssertEqual(attaches, 3 + ModeRecoveryPolicy.maxAttempts)
    }

    func testTheReportAttachMakesItselfIsRefusedWhileInFlight() async {
        let (controller, _) = immediateController()
        var nested: [Bool] = []
        var attaches = 0
        controller.schedule(inputs: { self.lostControl }, attach: {
            attaches += 1
            // `attach` resets the coordinator first, which reports lost control again.
            nested.append(controller.schedule(inputs: { self.lostControl }, attach: { attaches += 100 }))
        })
        await settle("attached") { attaches == 1 && !controller.attachInFlight }
        for _ in 0..<50 { await Task.yield() }
        XCTAssertEqual(nested, [false])
        XCTAssertEqual(attaches, 1)
        XCTAssertFalse(controller.schedule(inputs: {
            var inputs = self.lostControl
            inputs.modeControlAvailable = true
            return inputs
        }, attach: {}))
    }

    func testInputsAreRecheckedAfterTheDelay() async {
        let (controller, _) = immediateController()
        var current = true
        var attaches = 0
        controller.schedule(inputs: {
            var inputs = self.lostControl
            inputs.transportIsCurrent = current
            return inputs
        }, attach: { attaches += 1 })
        XCTAssertTrue(controller.attachInFlight)
        current = false // a reconnect replaced the transport during the delay
        await settle("gave up") { !controller.attachInFlight }
        XCTAssertEqual(attaches, 0)
        XCTAssertEqual(controller.attempts, 0)
    }

    func testResetAndInitialAttachCancelAScheduledRecovery() async {
        let controller = ModeRecoveryController(sleep: { _ in try await Task.sleep(for: .seconds(60)) })
        var attaches = 0
        controller.schedule(inputs: { self.lostControl }, attach: { attaches += 1 })
        XCTAssertTrue(controller.attachInFlight)
        controller.reset()
        XCTAssertFalse(controller.attachInFlight)
        XCTAssertEqual(controller.attempts, 0)

        controller.schedule(inputs: { self.lostControl }, attach: { attaches += 1 })
        controller.beginInitialAttach()
        XCTAssertTrue(controller.attachInFlight, "the initial attach owns the flag now")
        XCTAssertFalse(controller.schedule(inputs: { self.lostControl }, attach: { attaches += 1 }))
        controller.endInitialAttach()
        XCTAssertFalse(controller.attachInFlight)
        for _ in 0..<50 { await Task.yield() }
        XCTAssertEqual(attaches, 0)
    }

    func testControllerRestoresACoordinatorAfterAnIntegrityFailureButNotAfterAGateFailure() async throws {
        let gate = RingOperationGate(), transport = FailingRenewTransport()
        let coordinator = UnifiedModeCoordinator(gate: gate)
        let (controller, events) = immediateController()
        // What AppModel does: every loss of control reports to the controller.
        coordinator.onModeChange = { _, next in
            guard next == nil else { return }
            controller.schedule(inputs: {
                var inputs = self.lostControl
                inputs.modeControlAvailable = coordinator.available
                return inputs
            }, attach: { try await coordinator.attach(transport) })
        }
        // The initial attach owns the in-flight flag, so its own reset is not a loss.
        controller.beginInitialAttach()
        try await coordinator.attach(transport)
        controller.endInitialAttach()
        XCTAssertFalse(controller.attachInFlight)
        XCTAssertEqual(events(), [])
        try await coordinator.setGesture(true)
        coordinator.didProcess(session: 1, sequence: 1, at: 10)
        // A failed gate keeps control: nothing is scheduled.
        do { try await coordinator.heartbeat(at: 10); XCTFail("renewal should fail") } catch {}
        XCTAssertTrue(coordinator.available)
        XCTAssertFalse(controller.attachInFlight)
        XCTAssertEqual(events(), [])
        // An uncorrelated reply drops control and schedules the re-attach.
        transport.renewError = UnifiedModeError.uncorrelated
        coordinator.didProcess(session: 1, sequence: 2, at: 15)
        do { try await coordinator.heartbeat(at: 15); XCTFail("renewal should fail") } catch {}
        XCTAssertFalse(coordinator.available)
        XCTAssertTrue(controller.attachInFlight)

        await settle("recovered") { coordinator.available && !controller.attachInFlight }
        XCTAssertEqual(coordinator.status?.mode, .health)
        XCTAssertEqual(events(), [.scheduled(attempt: 1), .recovered])
        XCTAssertEqual(transport.statusCalls, 2)
    }
    // MARK: Sticky sessions

    func testRetryNowRefillsTheBudgetButNeverRacesAnAttachInFlight() async {
        let (controller, _) = immediateController()
        var attaches = 0
        XCTAssertTrue(controller.schedule(inputs: { self.lostControl }, attach: {
            attaches += 1
            throw UnifiedModeError.unavailable
        }))
        await settle("budget spent") { attaches == ModeRecoveryPolicy.maxAttempts && !controller.attachInFlight }
        XCTAssertFalse(controller.schedule(inputs: { self.lostControl }, attach: { attaches += 1 }))
        // A heal asks again: a fresh budget.
        var recovered = false
        XCTAssertTrue(controller.retryNow(inputs: { self.lostControl }, attach: { recovered = true }))
        XCTAssertTrue(controller.attachInFlight)
        // A second request while one is pending is answered by it, not doubled.
        var doubled = false
        XCTAssertTrue(controller.retryNow(inputs: { self.lostControl }, attach: { doubled = true }))
        await settle("recovered") { recovered && !controller.attachInFlight }
        for _ in 0..<50 { await Task.yield() }
        XCTAssertFalse(doubled)
        XCTAssertEqual(controller.attempts, 0)
    }

    func testOnlyIntegrityFailuresDropControl() {
        let keeps = UnifiedModeCoordinator.keepsControl
        XCTAssertTrue(keeps(UnifiedModeError.renewalBoundary, nil))
        XCTAssertTrue(keeps(UnifiedModeError.staleStream, nil), "the transport's own guard wrote nothing")
        XCTAssertTrue(keeps(RingProtocolError.busy, nil))
        XCTAssertTrue(keeps(CancellationError(), nil))
        XCTAssertFalse(keeps(UnifiedModeError.staleStream, "reply_mismatch"))
        XCTAssertFalse(keeps(UnifiedModeError.uncorrelated, nil))
        XCTAssertFalse(keeps(UnifiedModeError.exhausted, nil))
        XCTAssertFalse(keeps(UnifiedModeError.unavailable, nil))
        XCTAssertFalse(keeps(RingProtocolError.notReady, nil), "a lost link cannot attest Gesture")
        XCTAssertFalse(keeps(RingProtocolError.timeout, nil))
    }

    /// A1 FF (RT02 stock's refusal while charging; unverified on RT12) fails a
    /// pending entry as charging at once, receive-only, and is ignored otherwise.
    func testARefusalFailsAPendingEntryAsChargingAndIsOtherwiseIgnored() async throws {
        let link = RecordingLink()
        let transport = A1UnifiedModeTransport(link: link, charging: { false }, firmwareLeaseSeconds: 10,
                                               connectionID: 51)
        let refusal = ColmiR02Protocol.packet(command: 0xa1, payload: [0xff])
        transport.receiveMotion(refusal, at: ProcessInfo.processInfo.systemUptime) // no entry pending
        XCTAssertEqual(transport.currentStatus.mode, .health)
        XCTAssertTrue(link.writes.isEmpty)
        XCTAssertNil(transport.leaseAge)

        let start = Task { try await transport.setGesture(true, requestID: 1) }
        let wrote = await GestureIntentLogic.waitUntil(timeout: 2, poll: .milliseconds(10)) { !link.writes.isEmpty }
        XCTAssertTrue(wrote)
        XCTAssertNotNil(transport.leaseAge)
        transport.receiveMotion(refusal, at: ProcessInfo.processInfo.systemUptime)
        do { _ = try await start.value; XCTFail("entered despite the refusal") }
        catch FirmwareSwitchError.charging {} catch { XCTFail("unexpected \(error)") }
        XCTAssertEqual(GestureRequestOutcome(error: FirmwareSwitchError.charging), .charging)
        XCTAssertEqual(transport.currentStatus.mode, .health)
        // The failed entry's audited stops follow; nothing else is written.
        let stopped = await GestureIntentLogic.waitUntil(timeout: 2, poll: .milliseconds(10)) { link.writes.count >= 3 }
        XCTAssertTrue(stopped)
        XCTAssertEqual(link.writes, [ColmiR02Protocol.startRawMotionPacket, ColmiR02Protocol.rawSensorPacket(0x05),
                                     ColmiR02Protocol.rawSensorPacket(0x02)])
    }
}
