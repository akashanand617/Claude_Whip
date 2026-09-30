import XCTest
@testable import R02Ring

/// The lease-renewal gate on the fingerprinted V6/V7 A1 transport: it must
/// pass the ~30 ms connection-event lattice and stall-then-burst delivery the
/// iPhone journal showed, and still reject a stopped, half-rate, paired or
/// long-stalled producer, also when a stall across the write delivers
/// pre-write backlog first. Timestamps are synthetic; the write is real.
@MainActor
final class UnifiedRenewalGateTests: XCTestCase {
    private final class Link: A1ModeLink {
        var isReady = true
        var writes: [Data] = []
        func writeUART(_ data: Data) throws {
            guard isReady else { throw RingProtocolError.notReady }
            writes.append(data)
        }
    }

    private final class Clock {
        var offset = 0.0
        func now() -> Double { ProcessInfo.processInfo.systemUptime + offset }
    }

    private struct Harness {
        let link: Link
        let transport: A1UnifiedModeTransport
        let clock: Clock
        let session: UInt32
        /// Synthetic receipt time of the newest sample.
        var time: Double
        var value = 10
    }

    private func motion(_ value: Int) -> Data {
        ColmiR02Protocol.packet(command: 0xa1, payload: [0x03, UInt8(value & 0xff), UInt8(value >> 8 & 0xff)])
    }

    /// Enters leased Gesture with ten baseline samples at `baselineMS`
    /// spacings (nine values), the last one stamped now.
    private func enter(baselineMS: [Double] = [Double](repeating: 40, count: 9),
                       requiresMotionHold: Bool = false) async throws -> Harness {
        XCTAssertEqual(baselineMS.count, 9)
        let link = Link(), clock = Clock()
        let transport = A1UnifiedModeTransport(
            link: link, charging: { false }, requiresMotionHold: requiresMotionHold,
            firmwareLeaseSeconds: 10, connectionID: 77, clock: clock.now
        )
        let start = Task { try await transport.setGesture(true, requestID: 1) }
        // With the RT12 hold, let its write finish so later writes are ordered.
        try await Task.sleep(for: .milliseconds(requiresMotionHold ? 350 : 10))
        var time = clock.now() - baselineMS.reduce(0, +) / 1_000
        for (index, spacing) in ([0] + baselineMS).enumerated() {
            time += spacing / 1_000
            transport.receiveMotion(motion(index + 1), at: time)
        }
        let started = try await start.value
        XCTAssertEqual(started.status.mode, .gesture)
        return Harness(link: link, transport: transport, clock: clock, session: started.status.session, time: time)
    }

    /// Starts a renewal, waits for its write, feeds post-write samples at
    /// `postMS` spacings (distinct payloads unless `payloads` is given) and
    /// returns the renewal's result.
    private func renew(_ harness: inout Harness, postMS: [Double], payloads: [Int]? = nil,
                       requestID: UInt32 = 2) async -> Result<ModeReply, Error> {
        let transport = harness.transport, session = harness.session
        let renewal = Task { try await transport.renew(session: session, processedSequence: 1, requestID: requestID) }
        try? await Task.sleep(for: .milliseconds(170))
        for (index, spacing) in postMS.enumerated() {
            harness.time += spacing / 1_000
            harness.value += 1
            transport.receiveMotion(motion(payloads?[index] ?? harness.value), at: harness.time)
        }
        do { return .success(try await renewal.value) } catch { return .failure(error) }
    }

    private func leaseWrites(_ link: Link) -> Int {
        link.writes.filter { $0 == ColmiR02Protocol.startRawMotionPacket }.count
    }

    /// Sticky sessions: a failed gate is a missed renewal, never the stop
    /// path. After as long as the old stop sequence took, no A1 05, A1 02 or
    /// hold release was written and the transport still reports Gesture; the
    /// owner retries or heals, and the firmware lease stays the backstop.
    private func assertKeptGesture(_ harness: Harness, hold: Bool = false,
                                   file: StaticString = #filePath, line: UInt = #line) async {
        try? await Task.sleep(for: .milliseconds(hold ? 700 : 400))
        let stops = [ColmiR02Protocol.rawSensorPacket(0x05), ColmiR02Protocol.rawSensorPacket(0x02),
                     ColmiR02Protocol.gestureMotionHoldPacket(enabled: false)]
        XCTAssertFalse(harness.link.writes.contains { stops.contains($0) }, "a renewal failure sent stop packets",
                       file: file, line: line)
        XCTAssertEqual(harness.link.writes.last, ColmiR02Protocol.startRawMotionPacket, file: file, line: line)
        XCTAssertEqual(harness.transport.currentStatus.mode, .gesture, file: file, line: line)
        XCTAssertEqual(harness.transport.currentStatus.session, harness.session, file: file, line: line)
    }

    // MARK: Passes on ordinary link timing

    func testThirtyMillisecondLatticePassesThoughItsMediansDiffer() async throws {
        var harness = try await enter(baselineMS: [30, 30, 60, 30, 30, 60, 30, 30, 30])
        let result = await renew(&harness, postMS: [60, 60, 30, 60, 30, 60, 30, 60, 30, 60])
        XCTAssertNoThrow(try result.get())
        let metrics = try XCTUnwrap(harness.transport.lastRenewalMetrics)
        // The retired rule (renewal median <= 1.5x baseline median) would fail: 60 vs 30 ms.
        XCTAssertEqual(metrics.baselineMedianSpacing, 0.030, accuracy: 1e-6)
        XCTAssertEqual(metrics.renewalMedianSpacing, 0.060, accuracy: 1e-6)
        XCTAssertEqual(metrics.renewalMeanSpacing, 0.048, accuracy: 1e-6)
        let report = try XCTUnwrap(harness.transport.lastRenewalReport)
        XCTAssertTrue(report.passed)
        XCTAssertNil(report.cause)
        XCTAssertEqual(report.renewalSpacingsMS.count, 10)
        XCTAssertNil(report.fields["renewal_spacings_ms"], "spacings are journaled only on failure")
        XCTAssertTrue(JSONSerialization.isValidJSONObject(report.fields))
        XCTAssertEqual(report.judgedFrom, 0, "no stall: the first ten post-write spacings")
        XCTAssertEqual(report.stalls, 0)
        XCTAssertEqual(leaseWrites(harness.link), 2)
    }

    func testSameEventBurstsAndAFourEventGapPass() async throws {
        var harness = try await enter()
        // 1 ms boundary (the retired minimum was 10 ms), a 1 ms same-event
        // pair and a 120 ms gap (the retired maximum).
        let result = await renew(&harness, postMS: [1, 60, 30, 120, 1, 30, 60, 30, 60, 40])
        XCTAssertNoThrow(try result.get())
        let metrics = try XCTUnwrap(harness.transport.lastRenewalMetrics)
        XCTAssertEqual(metrics.boundarySpacing, 0.001, accuracy: 1e-6)
        XCTAssertEqual(metrics.renewalMaximumSpacing, 0.120, accuracy: 1e-6)
    }

    func testAStallBelowTheSessionCeilingPassesInOneAttemptOnTheDeliveryAfterIt() async throws {
        var harness = try await enter()
        // A 300 ms stall, its bunched backlog, then ten healthy spacings.
        let result = await renew(&harness, postMS: [40, 300, 1, 1, 1, 1] + [Double](repeating: 40, count: 10))
        XCTAssertNoThrow(try result.get())
        XCTAssertEqual(leaseWrites(harness.link), 2, "exactly one renewal A1 04")
        XCTAssertFalse(harness.link.writes.contains(ColmiR02Protocol.rawSensorPacket(0x05)))
        XCTAssertEqual(A1UnifiedModeTransport.renewalMaximumSpacing, GestureFreshness.stallCeiling)
        let report = try XCTUnwrap(harness.transport.lastRenewalReport)
        XCTAssertEqual(report.judgedFrom, 6, "judged from the last backlog sample")
        XCTAssertEqual(report.stalls, 1)
        let metrics = try XCTUnwrap(harness.transport.lastRenewalMetrics)
        XCTAssertEqual(metrics.renewalMeanSpacing, 0.040, accuracy: 1e-6)
        XCTAssertEqual(metrics.renewalMaximumSpacing, 0.300, accuracy: 1e-6)
    }

    func testAStallBurstThenHealthyDeliveryPassesWithOneWrite() async throws {
        // The stall straddles the write: every backlog sample predates it.
        var harness = try await enter()
        let result = await renew(&harness, postMS: [400] + [Double](repeating: 1, count: 9)
                                 + [Double](repeating: 40, count: 10))
        XCTAssertNoThrow(try result.get())
        XCTAssertEqual(leaseWrites(harness.link), 2)
        XCTAssertEqual(harness.transport.lastRenewalReport?.judgedFrom, 10)
    }

    // MARK: Still rejects producer failures

    func testAStallAboveTheCeilingFailsOnceAndKeepsGestureAndTheHold() async throws {
        var harness = try await enter(requiresMotionHold: true)
        let result = await renew(&harness, postMS: [600, 1, 1, 1, 1, 1, 1, 1, 1, 1])
        guard case .failure(UnifiedModeError.renewalBoundary) = result else {
            return XCTFail("expected renewalBoundary, got \(result)")
        }
        let report = try XCTUnwrap(harness.transport.lastRenewalReport)
        XCTAssertFalse(report.passed)
        XCTAssertEqual(report.cause, .criteria)
        XCTAssertEqual(report.failedChecks, ["max_gap"])
        // Failed as soon as the 600 ms spacing arrived.
        XCTAssertEqual(report.renewalSpacingsMS.count, 1)
        XCTAssertEqual(report.renewalSpacingsMS.first ?? 0, 600, accuracy: 1e-3)
        XCTAssertNil(harness.transport.lastRenewalMetrics)
        XCTAssertNotNil(report.fields["renewal_spacings_ms"])
        XCTAssertTrue(JSONSerialization.isValidJSONObject(report.fields))
        XCTAssertEqual(leaseWrites(harness.link), 2, "no retry")
        await assertKeptGesture(harness, hold: true)
    }

    func testAHalfRateProducerFails() async throws {
        var harness = try await enter()
        let result = await renew(&harness, postMS: [Double](repeating: 80, count: 10))
        guard case .failure(UnifiedModeError.renewalBoundary) = result else {
            return XCTFail("expected renewalBoundary, got \(result)")
        }
        XCTAssertEqual(harness.transport.lastRenewalReport?.failedChecks, ["rate_low"])
        XCTAssertEqual(leaseWrites(harness.link), 2)
        await assertKeptGesture(harness)
    }

    func testABurstingProducerFails() async throws {
        var harness = try await enter()
        let result = await renew(&harness, postMS: [Double](repeating: 20, count: 10))
        guard case .failure(UnifiedModeError.renewalBoundary) = result else {
            return XCTFail("expected renewalBoundary, got \(result)")
        }
        XCTAssertEqual(harness.transport.lastRenewalReport?.failedChecks, ["rate_high"])
    }

    // MARK: A stall across the write cannot pass on pre-write backlog

    func testABacklogAfterAStallAcrossTheWriteThenSilenceTimesOut() async throws {
        // Ten samples bunched behind a 400 ms stall, then nothing: the old
        // gate passed this (mean 40.9 ms) although all ten predate the write.
        var harness = try await enter()
        let result = await renew(&harness, postMS: [400] + [Double](repeating: 1, count: 9))
        guard case .failure(UnifiedModeError.renewalBoundary) = result else {
            return XCTFail("a stopped producer passed on backlog: \(result)")
        }
        let report = try XCTUnwrap(harness.transport.lastRenewalReport)
        XCTAssertEqual(report.cause, .timeout(samplesAfterWrite: 10))
        XCTAssertNil(report.judgedFrom)
        XCTAssertEqual(report.stalls, 1)
        XCTAssertEqual(report.backToBackAfterWrite, 9)
        XCTAssertEqual(report.fields["back_to_back_after_write"] as? Int, 9)
        XCTAssertTrue(JSONSerialization.isValidJSONObject(report.fields))
        XCTAssertEqual(leaseWrites(harness.link), 2)
        await assertKeptGesture(harness)
    }

    func testFrozenPayloadsAfterAStallBurstFail() async throws {
        var harness = try await enter()
        let backlog = Array(101...110), frozen = [Int](repeating: 111, count: 12)
        let result = await renew(&harness, postMS: [420] + [Double](repeating: 1, count: 9)
                                 + [Double](repeating: 40, count: 12),
                                 payloads: backlog + frozen)
        guard case .failure(UnifiedModeError.renewalBoundary) = result else {
            return XCTFail("a frozen producer passed on backlog: \(result)")
        }
        XCTAssertEqual(harness.transport.lastRenewalReport?.failedChecks, ["duplicates"])
        XCTAssertEqual(harness.transport.lastRenewalReport?.judgedFrom, 10)
        XCTAssertEqual(harness.transport.lastRenewalMetrics?.renewalDuplicates, 9)
        XCTAssertEqual(leaseWrites(harness.link), 2)
        await assertKeptGesture(harness)
    }

    func testAHalfRateProducerAfterAStallBurstFails() async throws {
        // The old gate's first ten (250, five 1 ms, four 80 ms) averaged 57.5 ms.
        var harness = try await enter()
        let result = await renew(&harness, postMS: [250] + [Double](repeating: 1, count: 5)
                                 + [Double](repeating: 80, count: 12))
        guard case .failure(UnifiedModeError.renewalBoundary) = result else {
            return XCTFail("a half-rate producer passed on backlog: \(result)")
        }
        XCTAssertEqual(harness.transport.lastRenewalReport?.failedChecks, ["rate_low"])
        XCTAssertEqual(harness.transport.lastRenewalReport?.judgedFrom, 6)
        XCTAssertEqual(try XCTUnwrap(harness.transport.lastRenewalMetrics?.renewalMeanSpacing), 0.080, accuracy: 1e-6)
        await assertKeptGesture(harness)
    }

    func testJudgedStartFollowsTheLastStallsBacklog() {
        func times(_ spacingsMS: [Double]) -> [TimeInterval] {
            var time = 100.0
            return [time] + spacingsMS.map { time += $0 / 1_000; return time }
        }
        let start = A1UnifiedModeTransport.judgedStart
        XCTAssertEqual(A1UnifiedModeTransport.renewalStallSpacing, 0.15)
        XCTAssertEqual(start(times([40, 40, 140, 40])), 0, "140 ms is ordinary missed events")
        XCTAssertEqual(start(times([40, 300, 1, 1, 40, 40, 40])), 4)
        XCTAssertNil(start(times([40, 300, 1, 1, 40, 40])), "not known until three spacings follow")
        // A second stall moves the start past its own backlog.
        XCTAssertEqual(start(times([300, 40, 40, 40, 200, 1, 40, 40, 40])), 6)
        // Paired delivery that never gives three clean spacings: the 0.5 s fallback.
        let paired = times([300] + (0..<20).flatMap { _ in [1.0, 40.0] })
        let expected = paired.indices.first { $0 >= 1 && paired[$0] - paired[1] >= GestureFreshness.quarantine }
        XCTAssertNotNil(expected)
        XCTAssertEqual(start(paired), expected)
    }

    func testFourStrictPairsOfTenFailAgainstACleanBaseline() async throws {
        var harness = try await enter()
        let result = await renew(&harness, postMS: [Double](repeating: 40, count: 10),
                                 payloads: [11, 11, 12, 12, 13, 13, 14, 14, 15, 16])
        guard case .failure(UnifiedModeError.renewalBoundary) = result else {
            return XCTFail("a 4/10 pairing crossed the gate: \(result)")
        }
        let metrics = try XCTUnwrap(harness.transport.lastRenewalMetrics)
        XCTAssertEqual(metrics.renewalDuplicates, 4)
        XCTAssertEqual(metrics.baselineDuplicates, 0)
        XCTAssertEqual(harness.transport.lastRenewalReport?.failedChecks, ["duplicates"])
        XCTAssertEqual(leaseWrites(harness.link), 2, "duplicates are never retried")
        await assertKeptGesture(harness)
    }

    func testATimeoutClearsThePreviousPassAndReportsHowManySamplesArrived() async throws {
        var harness = try await enter()
        let first = await renew(&harness, postMS: [Double](repeating: 40, count: 10))
        XCTAssertNoThrow(try first.get())
        XCTAssertNotNil(harness.transport.lastRenewalMetrics)
        let second = await renew(&harness, postMS: [Double](repeating: 40, count: 5), requestID: 3)
        guard case .failure(UnifiedModeError.renewalBoundary) = second else {
            return XCTFail("expected renewalBoundary, got \(second)")
        }
        XCTAssertNil(harness.transport.lastRenewalMetrics, "a timed-out renewal must not show the previous pass")
        let report = try XCTUnwrap(harness.transport.lastRenewalReport)
        XCTAssertEqual(report.cause, .timeout(samplesAfterWrite: 5))
        XCTAssertEqual(report.fields["samples_after_write"] as? Int, 5)
        XCTAssertEqual(leaseWrites(harness.link), 3)
        await assertKeptGesture(harness)
    }

    func testEveryAttemptIsPublishedBeforeItsCallerResumes() async throws {
        var harness = try await enter()
        var published: [A1UnifiedModeTransport.RenewalReport] = []
        harness.transport.onRenewalReport = { published.append($0) }
        _ = await renew(&harness, postMS: [Double](repeating: 40, count: 10))
        XCTAssertEqual(published.map(\.passed), [true])
        _ = await renew(&harness, postMS: [Double](repeating: 80, count: 10), requestID: 3)
        XCTAssertEqual(published.map(\.passed), [true, false])
    }

    // MARK: Guards before the write

    func testAPreArmRejectionNamesItsGuardAndClearsThePreviousReport() async throws {
        var harness = try await enter()
        _ = await renew(&harness, postMS: [Double](repeating: 40, count: 10))
        XCTAssertNotNil(harness.transport.lastRenewalReport)
        do {
            _ = try await harness.transport.renew(session: harness.session &+ 1, processedSequence: 1, requestID: 9)
            XCTFail("wrong session renewed")
        } catch UnifiedModeError.staleStream {} catch { XCTFail("unexpected \(error)") }
        XCTAssertEqual(harness.transport.lastRejection, "session_mismatch")
        XCTAssertNil(harness.transport.lastRenewalReport)
        XCTAssertNil(harness.transport.lastRenewalMetrics)
        XCTAssertEqual(leaseWrites(harness.link), 2)
    }

    func testALeaseOlderThanNineSecondsIsNotRenewed() async throws {
        let harness = try await enter()
        XCTAssertEqual(harness.transport.leaseRenewalDeadline, 9)
        // Fresh motion, but the last lease write is 9.5 s old: the firmware
        // may already have returned to Health, and A1 04 would re-enter.
        harness.clock.offset = 9.5
        var time = harness.clock.now() - 0.4
        for value in 100..<110 {
            time += 0.04
            harness.transport.receiveMotion(motion(value), at: time)
        }
        let writes = harness.link.writes.count
        do {
            _ = try await harness.transport.renew(session: harness.session, processedSequence: 1, requestID: 5)
            XCTFail("renewed an expired lease")
        } catch UnifiedModeError.staleStream {} catch { XCTFail("unexpected \(error)") }
        XCTAssertEqual(harness.link.writes.count, writes, "no UART write")
        XCTAssertTrue(harness.transport.lastRejection?.hasPrefix("lease_age=") == true,
                      harness.transport.lastRejection ?? "nil")
    }

    func testANewSessionOrReattachStartsWithoutAnEarlierRejection() async throws {
        let harness = try await enter()
        let transport = harness.transport
        func refuse(_ requestID: UInt32) async {
            do { _ = try await transport.renew(session: harness.session &+ 1, processedSequence: 1, requestID: requestID) }
            catch {}
        }
        await refuse(5)
        XCTAssertEqual(transport.lastRejection, "session_mismatch")
        // What a mode recovery sends when it re-attaches this transport.
        _ = try await transport.status(requestID: 6)
        XCTAssertNil(transport.lastRejection)

        await refuse(7)
        XCTAssertEqual(transport.lastRejection, "not_gesture")
        let writesBefore = harness.link.writes.count
        let start = Task { try await transport.setGesture(true, requestID: 8) }
        try await Task.sleep(for: .milliseconds(10))
        XCTAssertNil(transport.lastRejection, "a new Gesture session starts clean")
        // Entry evidence counts only after the A1 04, which waits out the
        // write slot after the re-attach's stops.
        let written = await GestureIntentLogic.waitUntil(timeout: 1, poll: .milliseconds(5)) {
            harness.link.writes.count > writesBefore
        }
        XCTAssertTrue(written)
        var time = harness.clock.now()
        for value in 200..<203 { time += 0.04; transport.receiveMotion(motion(value), at: time) }
        _ = try await start.value

        await refuse(9)
        XCTAssertNotNil(transport.lastRejection)
        transport.disconnected()
        XCTAssertNil(transport.lastRejection)
    }

    func testMotionAgeAndHistoryRejectionsAreNamed() async throws {
        let link = Link()
        let transport = A1UnifiedModeTransport(link: link, charging: { false }, firmwareLeaseSeconds: 10)
        do { _ = try await transport.renew(session: 0, processedSequence: 1, requestID: 1); XCTFail("renewed") }
        catch {}
        XCTAssertEqual(transport.lastRejection, "not_gesture")
        let harness = try await enter()
        harness.clock.offset = 0.8
        do { _ = try await harness.transport.renew(session: harness.session, processedSequence: 1, requestID: 3) }
        catch {}
        XCTAssertTrue(harness.transport.lastRejection?.hasPrefix("motion_age=") == true,
                      harness.transport.lastRejection ?? "nil")
    }

    func testFailedChecksArePure() {
        func metrics(mean: Double, max: Double, baselineDup: Double = 0, dup: Double = 0)
            -> A1UnifiedModeTransport.RenewalBoundaryMetrics {
            .init(baselineMedianSpacing: 0.04, renewalMedianSpacing: 0.04, boundarySpacing: 0.04,
                  renewalMaximumSpacing: max, baselineDuplicateFraction: baselineDup,
                  renewalDuplicateFraction: dup, baselineMeanSpacing: 0.04, renewalMeanSpacing: mean,
                  baselineDuplicates: 0, renewalDuplicates: 0)
        }
        XCTAssertEqual(A1UnifiedModeTransport.failedRenewalChecks(metrics(mean: 0.040, max: 0.5)), [])
        XCTAssertEqual(A1UnifiedModeTransport.failedRenewalChecks(metrics(mean: 0.024, max: 0.1)), [])
        XCTAssertEqual(A1UnifiedModeTransport.failedRenewalChecks(metrics(mean: 0.064, max: 0.1)), [])
        XCTAssertEqual(A1UnifiedModeTransport.failedRenewalChecks(metrics(mean: 0.0239, max: 0.1)), ["rate_high"])
        XCTAssertEqual(A1UnifiedModeTransport.failedRenewalChecks(metrics(mean: 0.0641, max: 0.1)), ["rate_low"])
        XCTAssertEqual(A1UnifiedModeTransport.failedRenewalChecks(metrics(mean: 0.04, max: 0.501)), ["max_gap"])
        XCTAssertEqual(A1UnifiedModeTransport.failedRenewalChecks(metrics(mean: 0.04, max: 0.1, dup: 0.1)), [])
        XCTAssertEqual(A1UnifiedModeTransport.failedRenewalChecks(metrics(mean: 0.04, max: 0.1, dup: 0.2)),
                       ["duplicates"])
        XCTAssertEqual(A1UnifiedModeTransport.failedRenewalChecks(
            metrics(mean: 0.04, max: 0.1, baselineDup: 1, dup: 1)), [])
    }

    // MARK: Coordinator heartbeat

    func testHeartbeatNamesTheGuardThatRefused() async throws {
        let transport = UnifiedModeTests.Transport()
        let coordinator = UnifiedModeCoordinator(gate: RingOperationGate())
        try await coordinator.attach(transport)
        try await coordinator.setGesture(true)
        do { try await coordinator.heartbeat(at: 5); XCTFail("no processing") } catch {}
        XCTAssertEqual(coordinator.lastHeartbeatRejection, "not_processed")
        coordinator.didProcess(session: 1, sequence: 7, at: 5)
        do { try await coordinator.heartbeat(at: 5.8); XCTFail("stale processing") } catch {}
        XCTAssertEqual(coordinator.lastHeartbeatRejection, "processed_age=0.800")
        try await coordinator.heartbeat(at: 5.2)
        XCTAssertNil(coordinator.lastHeartbeatRejection)
    }

    func testTheCoordinatorSaysWhetherAHeartbeatReachedRenew() async throws {
        let transport = UnifiedModeTests.Transport()
        let coordinator = UnifiedModeCoordinator(gate: RingOperationGate())
        try await coordinator.attach(transport)
        try await coordinator.setGesture(true)
        coordinator.didProcess(session: 1, sequence: 7, at: 5)
        try await coordinator.heartbeat(at: 5.2)
        XCTAssertTrue(coordinator.lastHeartbeatReachedRenew)
        coordinator.didProcess(session: 1, sequence: 8, at: 10.3)
        do { try await coordinator.heartbeat(at: 11); XCTFail("stale processing") } catch {}
        XCTAssertFalse(coordinator.lastHeartbeatReachedRenew, "refused before renew")
        XCTAssertEqual(coordinator.lastHeartbeatRejection, "processed_age=0.700")
        XCTAssertEqual(transport.renewals, 1)
    }

    func testAFailedHeartbeatCarriesOnlyItsOwnRenewalDiagnostics() async throws {
        var harness = try await enter()
        _ = await renew(&harness, postMS: [Double](repeating: 40, count: 10))
        let passed = try XCTUnwrap(harness.transport.lastRenewalReport)
        XCTAssertTrue(passed.passed)

        // The next heartbeat is refused before renew: the transport still
        // holds the previous pass, which must not appear as this failure's.
        let refused = HeartbeatFailure(reachedRenew: false, heartbeatRejection: "processed_age=0.700",
                                       transportRejection: harness.transport.lastRejection,
                                       report: harness.transport.lastRenewalReport, error: "staleStream")
        XCTAssertEqual(refused.detail, "heartbeat:processed_age=0.700")
        XCTAssertNil(refused.fields["report"])
        XCTAssertNil(refused.fields["rejection"])
        XCTAssertEqual(refused.fields["reached_renew"] as? Bool, false)
        XCTAssertTrue(JSONSerialization.isValidJSONObject(refused.fields))

        // The mode gate or the request counter refused: the error still names it.
        let busy = HeartbeatFailure(reachedRenew: false, error: String(describing: RingProtocolError.busy))
        XCTAssertEqual(busy.detail, "heartbeat_error:" + String(describing: RingProtocolError.busy))

        // A renewal this heartbeat ran and failed.
        _ = await renew(&harness, postMS: [Double](repeating: 80, count: 10), requestID: 3)
        let failed = HeartbeatFailure(reachedRenew: true, transportRejection: harness.transport.lastRejection,
                                      report: harness.transport.lastRenewalReport, error: "renewalBoundary", retries: 2)
        XCTAssertEqual(failed.detail, "renewal:criteria:rate_low")
        XCTAssertEqual((failed.fields["report"] as? [String: Any])?["outcome"] as? String, "failed")
        XCTAssertEqual(failed.fields["retries"] as? Int, 2)
        XCTAssertTrue(JSONSerialization.isValidJSONObject(failed.fields))

        // A passing renewal whose reply did not match, and a transport guard.
        XCTAssertEqual(HeartbeatFailure(reachedRenew: true, heartbeatRejection: "reply_mismatch",
                                        report: passed).detail, "heartbeat:reply_mismatch")
        XCTAssertEqual(HeartbeatFailure(reachedRenew: true, transportRejection: "motion_age=0.612").detail,
                       "renewal:motion_age=0.612")
    }

    // MARK: Heartbeat during a tolerated stall

    /// A real GestureSession fed one sample at a time; each output reaches the
    /// coordinator's `didProcess`, as AppModel hands it over.
    private final class SessionFeed: @unchecked Sendable {
        private final class NoGesture: GestureProbabilities, @unchecked Sendable {
            func probabilities(_ features: [Float]) throws -> [Float] { [1] + [Float](repeating: 0, count: 11) }
        }
        private let lock = NSLock()
        private var clockValue = 0.0
        private var produced: (sequence: UInt32, receivedAt: Double)?
        private let settled = DispatchSemaphore(value: 0)
        private var sequence: UInt32 = 0
        private(set) var session: GestureSession!
        private let packet = ColmiR02Protocol.packet(command: 0xa1, payload: [3, 0x1f, 0x45, 0, 1, 0, 2])

        init() {
            session = GestureSession(clock: { [unowned self] in
                self.lock.lock(); defer { self.lock.unlock() }
                return self.clockValue
            }, output: { [unowned self] output in
                self.settle((output.sequence, output.receivedAt))
            }, invalid: { [unowned self] _, _ in
                self.settle(nil)
            }, onDrop: { [unowned self] _, _ in
                self.settle(nil)
            })
            session.start(session: 1, classifier: NoGesture())
        }

        private func settle(_ value: (UInt32, Double)?) {
            lock.lock(); produced = value; lock.unlock()
            settled.signal()
        }

        /// One sample received, and dequeued, at `time`; its output, if any.
        func feed(at time: Double) -> (sequence: UInt32, receivedAt: Double)? {
            lock.lock(); clockValue = time; produced = nil; lock.unlock()
            sequence += 1
            session.ingest(packet, session: 1, sequence: sequence, receivedAt: time)
            guard settled.wait(timeout: .now() + 2) == .success else { return nil }
            lock.lock(); defer { lock.unlock() }
            return produced
        }
    }

    private func gestureCoordinator() async throws -> (UnifiedModeCoordinator, UnifiedModeTests.Transport) {
        let transport = UnifiedModeTests.Transport()
        let coordinator = UnifiedModeCoordinator(gate: RingOperationGate())
        try await coordinator.attach(transport)
        try await coordinator.setGesture(true)
        return (coordinator, transport)
    }

    private func deliver(_ feed: SessionFeed, to coordinator: UnifiedModeCoordinator, at time: Double) {
        if let output = feed.feed(at: time) {
            coordinator.didProcess(session: 1, sequence: output.sequence, at: output.receivedAt)
        }
    }

    /// Twenty clean samples 40 ms apart; returns the last one's receipt time.
    private func warm(_ feed: SessionFeed, _ coordinator: UnifiedModeCoordinator) -> Double {
        var time = 100.0
        for _ in 0..<20 { deliver(feed, to: coordinator, at: time); time += 0.04 }
        return time - 0.04
    }

    func testAHeartbeatInsideAToleratedStallWaitsForProcessingThenRenewsOnce() async throws {
        var paired: [Double] = [0.30]
        for event in 1...25 {
            let at: Double = 0.30 + 0.03 * Double(event)
            paired += [at, at + 0.001]
        }
        // (stall and delivery after the last output, heartbeat time, retries)
        let cases: [(String, [Double], Double, Int)] = [
            ("0.42 s gap", [0.42, 0.46, 0.50, 0.54, 0.58, 0.62, 0.66], 0.525, 1),
            ("0.49 s gap", [0.49, 0.53, 0.57, 0.61, 0.65, 0.69, 0.73], 0.60, 1),
            // Pairs per connection event never give three clean spacings:
            // the quarantine ends on its 0.5 s fallback.
            ("0.30 s gap, paired catch-up", paired, 0.53, 3),
        ]
        for (name, offsets, beat, expectedRetries) in cases {
            let (coordinator, transport) = try await gestureCoordinator()
            let feed = SessionFeed()
            let last = warm(feed, coordinator)
            var upcoming = offsets.map { last + $0 }
            var now = last + beat
            func deliverDue() {
                while let next = upcoming.first, next <= now {
                    upcoming.removeFirst()
                    deliver(feed, to: coordinator, at: next)
                }
            }
            deliverDue()
            XCTAssertNotNil(feed.session.openStallSince, "\(name): the heartbeat lands inside the episode")
            var attempts: [Bool] = []
            let retries = try await coordinator.heartbeat(now: { now }, sleep: { _ in
                now += 0.1
                deliverDue()
            }, inFlight: { attempts.append($0) })
            XCTAssertEqual(retries, expectedRetries, name)
            XCTAssertEqual(coordinator.lastHeartbeatRetries, expectedRetries, name)
            XCTAssertEqual(attempts, [true, false].cycled(expectedRetries + 1), "\(name): in flight only while an attempt runs")
            XCTAssertEqual(transport.renewals, 1, "\(name): renewed once, after processing resumed")
            XCTAssertNil(coordinator.lastHeartbeatRejection, name)
            XCTAssertNil(feed.session.openStallSince, name)
            XCTAssertNil(feed.session.lastFault, name)
            XCTAssertTrue(coordinator.available, name)
        }
    }

    func testAStoppedStreamStillEndsOnceThePauseOutlastsAnyToleratedStall() async throws {
        let (coordinator, transport) = try await gestureCoordinator()
        let feed = SessionFeed()
        let last = warm(feed, coordinator)
        var now = last + 0.52
        do {
            try await coordinator.heartbeat(now: { now }, sleep: { _ in now += 0.1 })
            XCTFail("renewed without processing")
        } catch UnifiedModeError.staleStream {} catch { XCTFail("unexpected \(error)") }
        XCTAssertEqual(transport.renewals, 0)
        XCTAssertTrue(coordinator.lastHeartbeatRejection?.hasPrefix("processed_age=") == true)
        // 0.52, 0.62 ... 2.22 s were within the 2.25 s pause limit; 2.32 s ends it.
        XCTAssertEqual(GestureFreshness.processingPauseLimit, 2.25, accuracy: 1e-9)
        XCTAssertEqual(coordinator.lastHeartbeatRetries, 18)
        XCTAssertGreaterThan(now - last, GestureFreshness.processingPauseLimit)
        XCTAssertLessThan(now - last, GestureFreshness.processingPauseLimit + 0.1 + 1e-9)
    }

    func testOnlyAProcessedAgeRefusalWaits() async throws {
        let (coordinator, _) = try await gestureCoordinator()
        do {
            try await coordinator.heartbeat(now: { 5 }, sleep: { _ in XCTFail("waited") })
            XCTFail("no processing")
        } catch {}
        XCTAssertEqual(coordinator.lastHeartbeatRejection, "not_processed")
        XCTAssertEqual(coordinator.lastHeartbeatRetries, 0)
        // Older than any tolerated stall at the first attempt.
        coordinator.didProcess(session: 1, sequence: 3, at: 5)
        do {
            try await coordinator.heartbeat(now: { 8 }, sleep: { _ in XCTFail("waited") })
            XCTFail("stale processing")
        } catch {}
        XCTAssertEqual(coordinator.lastHeartbeatRejection, "processed_age=3.000")
        XCTAssertEqual(coordinator.lastHeartbeatRetries, 0)
    }
}

private extension Array {
    /// The elements repeated `count` times.
    func cycled(_ count: Int) -> [Element] { (0..<count).flatMap { _ in self } }
}
