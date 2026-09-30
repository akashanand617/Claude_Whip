import XCTest
@testable import R02Ring

/// Stands in for `UnifiedModeCoordinator`: records each `setGesture`, can hold
/// an entry open until the test finishes it, and can fail stops in order.
@MainActor
private final class FakeCoordinator {
    var mode: RingRuntimeMode? = .health
    var available = true
    var linkReady = true
    var calls: [Bool] = []
    var willEnterCalls = 0
    /// Thrown by the next stop attempts, in order.
    var stopErrors: [Error] = []
    /// Keeps an entry open until `finishEntry`.
    var holdEntry = false
    private var entry: CheckedContinuation<Void, Error>?
    var isEntering: Bool { entry != nil }

    var isGestureMode: Bool { mode == .gesture || mode == .enteringGesture }

    func setGesture(_ enabled: Bool) async throws {
        calls.append(enabled)
        guard available else { throw UnifiedModeError.unavailable }
        if enabled {
            if holdEntry { try await withCheckedThrowingContinuation { entry = $0 } }
            mode = .gesture
        } else {
            if !stopErrors.isEmpty { throw stopErrors.removeFirst() }
            mode = .health
        }
    }

    /// Completes a held entry; a failure drops control like the coordinator does.
    func finishEntry(throwing error: Error? = nil) {
        let waiting = entry
        entry = nil
        if let error {
            mode = nil
            available = false
            waiting?.resume(throwing: error)
        } else {
            waiting?.resume()
        }
    }
}

/// Readiness the test changes while a start waits in another task.
@MainActor
private final class ReadinessBox {
    var value: GestureStartReadiness
    init(_ value: GestureStartReadiness) { self.value = value }
}

@MainActor
final class GestureSessionSequencerTests: XCTestCase {
    private var fake: FakeCoordinator!
    private var sequencer: GestureSessionSequencer!
    private var statuses: [String] = []
    private var journal: [(String, [String: Any])] = []
    /// Runs inside the injected sleep, i.e. while a start waits or a stop retries.
    private var onSleep: (() -> Void)?

    override func setUp() {
        super.setUp()
        fake = FakeCoordinator()
        statuses = []
        journal = []
        onSleep = nil
        let fake = fake!
        sequencer = GestureSessionSequencer(.init(
            setGesture: { try await fake.setGesture($0) },
            isGestureMode: { fake.isGestureMode },
            modeControlAvailable: { fake.available },
            linkReady: { fake.linkReady },
            willEnter: { fake.willEnterCalls += 1 },
            now: { 100 }, // a fixed clock: waits end only on a final state
            sleep: { [weak self] _ in
                self?.onSleep?()
                await Task.yield()
            }
        ))
        sequencer.onStatus = { [weak self] in self?.statuses.append($0) }
        sequencer.onJournal = { [weak self] kind, fields in self?.journal.append((kind, fields)) }
    }

    /// Lets the other main-actor tasks run until `condition` holds.
    private func settle(_ what: String, file: StaticString = #filePath, line: UInt = #line,
                        _ condition: () -> Bool) async {
        for _ in 0..<20_000 {
            if condition() { return }
            await Task.yield()
        }
        XCTFail("never settled: \(what)", file: file, line: line)
    }

    // MARK: Withdrawing a start that waits for readiness

    func testStopDuringTheReadinessWaitWithdrawsTheStart() async {
        let readiness = ReadinessBox(.connecting)
        let start = Task { await self.sequencer.requestStart(reason: .intent, readinessTimeout: 10) { readiness.value } }
        await settle("start waiting") { sequencer.pendingStarts == 1 }

        let stop = await sequencer.requestStop(reason: .intent)
        XCTAssertEqual(stop, .startCancelled)
        XCTAssertTrue(stop.succeeded, "the ring stays in Health, as asked")
        XCTAssertNotEqual(stop.message, GestureRequestOutcome.alreadyStopped.message)

        readiness.value = .ready // the ring connects afterwards
        let result = await start.value
        XCTAssertEqual(result.outcome, .startCancelled)
        XCTAssertEqual(result.readiness, .cancelled)
        XCTAssertEqual(fake.calls, [], "no A1 04 and no stop packets")
        XCTAssertEqual(fake.willEnterCalls, 0)
        XCTAssertEqual(sequencer.pendingStarts, 0)
        XCTAssertEqual(fake.mode, .health)
    }

    func testStopWithdrawsEveryWaitingStart() async {
        let readiness = ReadinessBox(.identifying)
        let first = Task { await self.sequencer.requestStart(reason: .intent, readinessTimeout: 10) { readiness.value } }
        let second = Task { await self.sequencer.requestStart(reason: .user, readinessTimeout: 10) { readiness.value } }
        await settle("both waiting") { sequencer.pendingStarts == 2 }
        let stop = await sequencer.requestStop(reason: .user)
        readiness.value = .ready
        let firstOutcome = await first.value.outcome
        let secondOutcome = await second.value.outcome
        let outcomes = [firstOutcome, secondOutcome]
        XCTAssertEqual(stop, .startCancelled)
        XCTAssertEqual(outcomes, [.startCancelled, .startCancelled])
        XCTAssertEqual(fake.calls, [])
    }

    func testAStartAfterAWithdrawalStillEnters() async {
        let readiness = ReadinessBox(.connecting)
        let withdrawn = Task { await self.sequencer.requestStart(reason: .intent, readinessTimeout: 10) { readiness.value } }
        await settle("waiting") { sequencer.pendingStarts == 1 }
        _ = await sequencer.requestStop(reason: .intent)
        readiness.value = .ready
        _ = await withdrawn.value

        let again = await sequencer.requestStart(reason: .intent, readinessTimeout: 10) { .ready }
        XCTAssertEqual(again.outcome, .started)
        XCTAssertEqual(fake.calls, [true])
        XCTAssertEqual(fake.willEnterCalls, 1)
    }

    func testInternalStopsNeverWithdrawAWaitingStart() async {
        let readiness = ReadinessBox(.attaching)
        let start = Task { await self.sequencer.requestStart(reason: .intent, readinessTimeout: 10) { readiness.value } }
        await settle("waiting") { sequencer.pendingStarts == 1 }
        let idle = await sequencer.setSession(false, reason: .idle)
        XCTAssertEqual(idle, .alreadyStopped)
        readiness.value = .ready
        let result = await start.value
        XCTAssertEqual(result.outcome, .started)
        XCTAssertEqual(fake.calls, [true])
    }

    func testAStopWithNothingPendingIsStillAlreadyStopped() async {
        let stop = await sequencer.requestStop(reason: .intent)
        XCTAssertEqual(stop, .alreadyStopped)
        XCTAssertEqual(fake.calls, [])
    }

    func testTheOwnersOwnPendingStartIsReportedAsWithdrawn() async {
        // A Shortcut continuation the owner holds outside the sequencer.
        let stop = await sequencer.requestStop(reason: .user, alsoWithdrawing: true)
        XCTAssertEqual(stop, .startCancelled)
    }

    func testRefusalsDoNotEnter() async {
        fake.available = false
        fake.linkReady = false
        var result = await sequencer.requestStart(reason: .user, readinessTimeout: 10) { .ready }
        XCTAssertEqual(result.outcome, .notConnected)
        fake.linkReady = true
        result = await sequencer.requestStart(reason: .user, readinessTimeout: 10) { .ready }
        XCTAssertEqual(result.outcome, .unavailable)
        result = await sequencer.requestStart(reason: .user, readinessTimeout: 10) { .charging }
        XCTAssertEqual(result.outcome, .charging)
        XCTAssertEqual(fake.calls, [])
        XCTAssertEqual(fake.willEnterCalls, 0)
    }

    // MARK: Stops during entry

    func testStopDuringEntryIsHeldAndPerformedOnceEntrySettles() async {
        fake.holdEntry = true
        var order: [String] = []
        sequencer.onTransitionChange = { order.append($0?.rawValue ?? "nil") }
        let start = Task { await self.sequencer.requestStart(reason: .intent, readinessTimeout: 10) { .ready } }
        await settle("entering") { fake.isEntering }
        XCTAssertEqual(sequencer.transition, .entering)
        XCTAssertEqual(sequencer.enteringReason, .intent)
        XCTAssertEqual(fake.willEnterCalls, 1)

        let stop = Task { await self.sequencer.requestStop(reason: .user) }
        await settle("stop held") { sequencer.stopAfterEntry == .user }
        XCTAssertTrue(sequencer.sessionEnding)
        XCTAssertEqual(fake.calls, [true], "the stop waits; nothing is sent over an entry")

        fake.finishEntry()
        let started = await start.value
        let stopped = await stop.value
        XCTAssertEqual(started.outcome, .started)
        XCTAssertEqual(stopped, .stopped)
        XCTAssertEqual(fake.calls, [true, false])
        XCTAssertEqual(fake.mode, .health)
        XCTAssertNil(sequencer.transition)
        XCTAssertNil(sequencer.stopAfterEntry)
        XCTAssertEqual(order, ["entering", "nil", "leaving", "nil"])
        XCTAssertEqual(journal.map(\.0), ["start", "stop"])
    }

    func testStopDuringAFailedEntryResumesWithoutHanging() async {
        fake.holdEntry = true
        let start = Task { await self.sequencer.requestStart(reason: .intent, readinessTimeout: 10) { .ready } }
        await settle("entering") { fake.isEntering }
        let resumed = expectation(description: "held stop resumed")
        let stop = Task {
            let outcome = await self.sequencer.setSession(false, reason: .backgrounded)
            resumed.fulfill()
            return outcome
        }
        await settle("stop held") { sequencer.stopAfterEntry == .backgrounded }
        fake.finishEntry(throwing: UnifiedModeError.staleStream)
        await fulfillment(of: [resumed], timeout: 5)
        let stopOutcome = await stop.value
        XCTAssertEqual(stopOutcome, .alreadyStopped)
        let result = await start.value
        XCTAssertEqual(result.outcome, .failed(UnifiedModeError.staleStream.localizedDescription))
        XCTAssertEqual(statuses, [UnifiedModeError.staleStream.localizedDescription])
        XCTAssertEqual(fake.calls, [true], "control was lost; recovery owns the stop packets")
    }

    // MARK: Stops that retry

    func testASecondStopJoinsTheStopInFlight() async {
        fake.mode = .gesture
        fake.stopErrors = [RingProtocolError.busy, RingProtocolError.busy]
        let first = Task { await self.sequencer.setSession(false, reason: .gestureAction) }
        await settle("leaving") { sequencer.transition == .leaving }
        XCTAssertEqual(sequencer.leavingReason, .gestureAction)
        let second = await sequencer.requestStop(reason: .intent)
        XCTAssertEqual(second, .stopped)
        let firstOutcome = await first.value
        XCTAssertEqual(firstOutcome, .stopped)
        XCTAssertEqual(fake.calls, [false, false, false], "busy retries behind a renewal, then stops once")
        XCTAssertEqual(statuses, [])
    }

    func testLosingControlWhileRetryingEndsQuietlyInsteadOfFailing() async {
        // A renewal holds the gate (busy), then fails during the retry sleep and
        // drops the coordinator; its own stop and recovery send the packets.
        fake.mode = .gesture
        fake.stopErrors = [RingProtocolError.busy]
        onSleep = { [fake] in
            fake?.mode = nil
            fake?.available = false
        }
        let outcome = await sequencer.setSession(false, reason: .idle)
        XCTAssertEqual(outcome, .alreadyStopped)
        XCTAssertTrue(outcome.succeeded)
        XCTAssertEqual(fake.calls, [false], "no second attempt against an unavailable coordinator")
        XCTAssertEqual(statuses, [], "no 'firmware does not support' status for a session that ended")
    }

    func testAStopWhoseOwnWriteFailsIsStillReported() async {
        fake.mode = .gesture
        fake.stopErrors = [RingProtocolError.notReady]
        let outcome = await sequencer.requestStop(reason: .intent)
        XCTAssertEqual(outcome, .notConnected)
        XCTAssertEqual(statuses, [RingProtocolError.notReady.localizedDescription])
    }

    // MARK: The pause gesture

    func testAFailedPauseResumesRoutingSoTheNextSnapRetries() async {
        fake.mode = .gesture
        fake.stopErrors = [RingProtocolError.notReady]
        let generation = UUID()
        var router: GestureActionRouter!
        let performer = PausePerformer { [unowned self] in
            self.sequencer.requestPause { router.cancelEnding(generation: generation) }
        }
        router = GestureActionRouter(performer: performer, haptics: nil)
        router.begin(generation: generation, log: nil)
        router.calibrated(at: 0)
        let context = { GestureActionRouter.Context(foreground: false, hapticsEnabled: false,
                                                    sessionEnding: self.sequencer.sessionEnding) }
        func snap(at time: Double) -> RingGestureEvent {
            RingGestureEvent(name: "snap", direction: "none", time: time, confidence: 0.9, votes: 3,
                             latency: 1, end: time + 0.3)
        }

        XCTAssertEqual(router.route([snap(at: 5)], generation: generation, context: context()).map(\.outcome),
                       [.performed])
        XCTAssertTrue(router.isEnding)
        await settle("failed pause rolled back") { !router.isEnding && sequencer.transition == nil }
        XCTAssertEqual(fake.mode, .gesture, "the stop failed; the session continues")

        XCTAssertEqual(router.route([snap(at: 10)], generation: generation, context: context()).map(\.outcome),
                       [.performed], "the next snap is not suppressed as sessionEnding")
        await settle("second pause") { fake.mode == .health }
        XCTAssertEqual(performer.pauses, 2)
        XCTAssertEqual(fake.calls, [false, false])
    }

    // MARK: Against the real coordinator and A1 transport

    func testStopDuringARealEntrySendsTheAuditedStopsAfterIt() async throws {
        let link = RecordingA1Link()
        let transport = A1UnifiedModeTransport(link: link, charging: { false }, requiresMotionHold: true,
                                               firmwareLeaseSeconds: 10, connectionID: 7)
        let coordinator = UnifiedModeCoordinator(gate: RingOperationGate())
        let stops = [
            ColmiR02Protocol.rawSensorPacket(0x05),
            ColmiR02Protocol.rawSensorPacket(0x02),
            ColmiR02Protocol.gestureMotionHoldPacket(enabled: false),
        ]
        try await coordinator.attach(transport)
        XCTAssertEqual(link.writes, stops)
        let real = GestureSessionSequencer(.init(
            setGesture: { try await coordinator.setGesture($0) },
            isGestureMode: { coordinator.status?.mode == .gesture || coordinator.status?.mode == .enteringGesture },
            modeControlAvailable: { coordinator.available },
            linkReady: { true }
        ))

        let start = Task { await real.requestStart(reason: .intent, readinessTimeout: 10) { .ready } }
        let wrote = await GestureIntentLogic.waitUntil(timeout: 2, poll: .milliseconds(10)) {
            link.writes.count >= stops.count + 2
        }
        XCTAssertTrue(wrote, "A1 04 and 3B 02 01 03 were not written in time")
        XCTAssertEqual(Array(link.writes.dropFirst(stops.count)), [
            ColmiR02Protocol.startRawMotionPacket,
            ColmiR02Protocol.gestureMotionHoldPacket(enabled: true),
        ])
        XCTAssertEqual(real.transition, .entering)

        let stop = Task { await real.requestStop(reason: .intent) }
        let held = await GestureIntentLogic.waitUntil(timeout: 1, poll: .milliseconds(5)) { real.stopAfterEntry != nil }
        XCTAssertTrue(held)
        let beforeMotion = link.writes.count
        let now = ProcessInfo.processInfo.systemUptime
        for value: UInt8 in 1...3 {
            transport.receiveMotion(ColmiR02Protocol.packet(command: 0xa1, payload: [0x03, value]),
                                    at: now + Double(value) * 0.04)
        }
        let started = await start.value
        let stopped = await stop.value
        XCTAssertEqual(started.outcome, .started)
        XCTAssertEqual(stopped, .stopped)
        XCTAssertEqual(Array(link.writes.dropFirst(beforeMotion)), stops,
                       "only A1 05, A1 02, 3B 02 01 00 follow the entry")
        XCTAssertEqual(coordinator.status?.mode, .health)
        XCTAssertNil(real.transition)
    }
    // MARK: The sticky session's heal (restart)

    func testARestartStopsAStaleSessionThenEntersThroughTheAuditedPath() async {
        fake.mode = .gesture
        let outcome = await sequencer.restart(epoch: sequencer.healEpoch)
        XCTAssertEqual(outcome, .started)
        XCTAssertEqual(fake.calls, [false, true], "the stop, then the entry: nothing else")
        XCTAssertEqual(fake.mode, .gesture)
        XCTAssertEqual(journal.map(\.0), ["stop", "start"])
        XCTAssertEqual(journal.map { $0.1["reason"] as? String }, ["heal", "heal"])
        XCTAssertFalse(sequencer.restarting)
        XCTAssertNil(sequencer.transition)
    }

    func testARestartAfterTheRingReturnedToHealthOnlyEnters() async {
        let outcome = await sequencer.restart(epoch: sequencer.healEpoch)
        XCTAssertEqual(outcome, .started)
        XCTAssertEqual(fake.calls, [true])
        XCTAssertEqual(fake.willEnterCalls, 1)
    }

    func testAnyStopWithdrawsARestartCapturedBeforeIt() async {
        let epoch = sequencer.healEpoch
        _ = await sequencer.setSession(false, reason: .idle) // nothing to stop, but still a stop
        let outcome = await sequencer.restart(epoch: epoch)
        XCTAssertEqual(outcome, .startCancelled)
        XCTAssertEqual(fake.calls, [])
    }

    /// A session end withdraws a heal in the same synchronous step, before
    /// its deferred return to Health runs: a restart captured before it, or
    /// one already in its stop half, never sends A1 04.
    func testWithdrawingAHealCancelsItsEntryWithoutStopping() async {
        let epoch = sequencer.healEpoch
        sequencer.withdrawHeal()
        let withdrawn = await sequencer.restart(epoch: epoch)
        XCTAssertEqual(withdrawn, .startCancelled)
        XCTAssertEqual(fake.calls, [], "withdrawing sends nothing itself")

        fake.mode = .gesture
        fake.stopErrors = [RingProtocolError.busy]
        let fake = fake!
        var sequencer: GestureSessionSequencer!
        var withdrew = false
        sequencer = GestureSessionSequencer(.init(
            setGesture: { try await fake.setGesture($0) },
            isGestureMode: { fake.isGestureMode },
            modeControlAvailable: { fake.available },
            linkReady: { fake.linkReady },
            now: { 100 },
            sleep: { _ in
                if !withdrew { withdrew = true; sequencer.withdrawHeal() }
                await Task.yield()
            }
        ))
        let outcome = await sequencer.restart(epoch: sequencer.healEpoch)
        XCTAssertEqual(outcome, .startCancelled)
        XCTAssertEqual(fake.calls, [false, false], "the heal's own stop half finished; no entry followed")
        XCTAssertEqual(fake.mode, .health)
    }

    func testAUserStopDuringTheRestartsStopHalfCancelsItsEntry() async {
        fake.mode = .gesture
        fake.stopErrors = [RingProtocolError.busy] // a renewal holds the gate once
        let fake = fake!
        var userStop: Task<GestureRequestOutcome, Never>?
        var sequencer: GestureSessionSequencer!
        // The retry's sleep lets the user's stop arrive and join the heal's stop.
        sequencer = GestureSessionSequencer(.init(
            setGesture: { try await fake.setGesture($0) },
            isGestureMode: { fake.isGestureMode },
            modeControlAvailable: { fake.available },
            linkReady: { fake.linkReady },
            now: { 100 },
            sleep: { _ in
                if userStop == nil { userStop = Task { await sequencer.requestStop(reason: .user) } }
                for _ in 0..<200 { await Task.yield() }
            }
        ))
        let outcome = await sequencer.restart(epoch: sequencer.healEpoch)
        let stopped = await userStop?.value
        XCTAssertEqual(outcome, .startCancelled)
        XCTAssertEqual(stopped, .stopped, "the user's stop joined the heal's stop and was answered by it")
        XCTAssertEqual(fake.calls, [false, false], "busy, then the stop: no A1 04 after the user asked for Health")
        XCTAssertEqual(fake.mode, .health)
    }

    func testAUserStopDuringTheRestartsEntryIsHeldAndPerformedRightAfter() async {
        fake.holdEntry = true
        let restart = Task { await self.sequencer.restart(epoch: self.sequencer.healEpoch) }
        await settle("entering") { fake.isEntering }
        XCTAssertEqual(sequencer.enteringReason, .heal)
        let stop = Task { await self.sequencer.requestStop(reason: .intent) }
        await settle("stop held") { sequencer.stopAfterEntry == .intent }
        fake.finishEntry()
        let restarted = await restart.value
        let stopped = await stop.value
        XCTAssertEqual(restarted, .started)
        XCTAssertEqual(stopped, .stopped)
        XCTAssertEqual(fake.calls, [true, false])
        XCTAssertEqual(fake.mode, .health)
    }

    func testAHealsFailedEntryReportsNoStatus() async {
        fake.holdEntry = true
        let restart = Task { await self.sequencer.restart(epoch: self.sequencer.healEpoch) }
        await settle("entering") { fake.isEntering }
        fake.finishEntry(throwing: UnifiedModeError.staleStream)
        let outcome = await restart.value
        XCTAssertEqual(outcome, .failed(UnifiedModeError.staleStream.localizedDescription))
        XCTAssertEqual(statuses, [], "a heal reports no failure unless it finally gives up")
    }

    func testARestartWaitsOutAnotherTransition() async {
        fake.holdEntry = true
        let start = Task { await self.sequencer.requestStart(reason: .intent, readinessTimeout: 10) { .ready } }
        await settle("entering") { fake.isEntering }
        let outcome = await sequencer.restart(epoch: sequencer.healEpoch)
        XCTAssertEqual(outcome, .busy)
        fake.finishEntry()
        _ = await start.value
        XCTAssertEqual(fake.calls, [true])
    }

    func testAHealOnTheRealCoordinatorWritesExactlyTheAuditedPackets() async throws {
        let link = RecordingA1Link()
        let transport = A1UnifiedModeTransport(link: link, charging: { false }, requiresMotionHold: true,
                                               firmwareLeaseSeconds: 10, connectionID: 8)
        let coordinator = UnifiedModeCoordinator(gate: RingOperationGate())
        try await coordinator.attach(transport)
        let real = GestureSessionSequencer(.init(
            setGesture: { try await coordinator.setGesture($0) },
            isGestureMode: { coordinator.status?.mode == .gesture || coordinator.status?.mode == .enteringGesture },
            modeControlAvailable: { coordinator.available },
            linkReady: { true }
        ))
        func feedEntry(after count: Int) async {
            let wrote = await GestureIntentLogic.waitUntil(timeout: 3, poll: .milliseconds(10)) {
                link.writes.count >= count
            }
            XCTAssertTrue(wrote, "writes: \(link.writes.count) of \(count)")
            let now = ProcessInfo.processInfo.systemUptime
            for value: UInt8 in 1...3 {
                transport.receiveMotion(ColmiR02Protocol.packet(command: 0xa1, payload: [0x03, value]),
                                        at: now + Double(value) * 0.04)
            }
        }
        // A user session that went stale: the ring still reports Gesture.
        let start = Task { await real.requestStart(reason: .intent, readinessTimeout: 10) { .ready } }
        await feedEntry(after: 5)
        _ = await start.value
        XCTAssertEqual(coordinator.status?.mode, .gesture)
        let before = link.writes.count

        // The heal runs from a task that is cancelled half way: the unstructured
        // restart still writes whole packet sequences.
        let heal = Task { await real.restart(epoch: real.healEpoch) }
        let stopping = await GestureIntentLogic.waitUntil(timeout: 2, poll: .milliseconds(5)) {
            link.writes.count > before
        }
        XCTAssertTrue(stopping)
        heal.cancel()
        await feedEntry(after: before + 5)
        let outcome = await heal.value
        XCTAssertEqual(outcome, .started)
        XCTAssertEqual(Array(link.writes.dropFirst(before)), [
            ColmiR02Protocol.rawSensorPacket(0x05),
            ColmiR02Protocol.rawSensorPacket(0x02),
            ColmiR02Protocol.gestureMotionHoldPacket(enabled: false),
            ColmiR02Protocol.startRawMotionPacket,
            ColmiR02Protocol.gestureMotionHoldPacket(enabled: true),
        ], "A1 05, A1 02, 3B 02 01 00, then A1 04, 3B 02 01 03: nothing else")
        XCTAssertEqual(coordinator.status?.mode, .gesture)
        XCTAssertTrue(coordinator.available)
    }
}

@MainActor
private final class PausePerformer: GestureActionPerforming {
    private let pause: () -> Void
    var pauses = 0
    init(pause: @escaping () -> Void) { self.pause = pause }
    func perform(_ action: GestureActionID) -> GestureActionOutcome {
        guard action == .pause_gestures else { return .performed }
        pauses += 1
        pause()
        return .performed
    }
}

@MainActor
private final class RecordingA1Link: A1ModeLink {
    var isReady = true
    var writes: [Data] = []
    func writeUART(_ data: Data) throws {
        guard isReady else { throw RingProtocolError.notReady }
        writes.append(data)
    }
}
