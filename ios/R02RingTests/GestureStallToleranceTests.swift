import XCTest
@testable import R02Ring

/// A running session survives one bounded stall (a main-queue or worker
/// delay), drops the late samples and a quarantine after them, then restarts
/// its inference window; larger or repeated stalls still end it.
final class GestureStallToleranceTests: XCTestCase {
    private final class LockedClock: @unchecked Sendable {
        private let lock = NSLock()
        private var value = 0.0
        func set(_ next: Double) { lock.lock(); value = next; lock.unlock() }
        func get() -> Double { lock.lock(); defer { lock.unlock() }; return value }
    }

    /// Counts predictions; answers "none" with certainty.
    private final class SpyClassifier: GestureProbabilities, @unchecked Sendable {
        private let lock = NSLock()
        private var calls = 0
        var count: Int { lock.lock(); defer { lock.unlock() }; return calls }
        func probabilities(_ features: [Float]) throws -> [Float] {
            lock.lock(); calls += 1; lock.unlock()
            return [1] + [Float](repeating: 0, count: 11)
        }
    }

    /// Answers one label with certainty for every window; switchable mid-stream.
    private final class LabelClassifier: GestureProbabilities, @unchecked Sendable {
        private let lock = NSLock()
        private var index = 0
        func answer(_ label: String) {
            lock.lock(); index = GestureContract.labels.firstIndex(of: label)!; lock.unlock()
        }
        func probabilities(_ features: [Float]) throws -> [Float] {
            lock.lock(); defer { lock.unlock() }
            var probabilities = [Float](repeating: 0, count: 12)
            probabilities[index] = 1
            return probabilities
        }
    }

    /// Feeds one sample at a time and waits for its fate.
    private final class Probe: @unchecked Sendable {
        enum Fate: Equatable { case output(predicted: Bool, frame: Bool), dropped, invalid }
        let clock = LockedClock()
        let settled = DispatchSemaphore(value: 0)
        private let lock = NSLock()
        private var fates: [Fate] = []
        private var emitted: [String] = []
        private(set) var stalls: [GestureSession.Stall] = []
        var session: GestureSession!
        /// Every gesture event the session emitted, by name.
        var events: [String] { lock.lock(); defer { lock.unlock() }; return emitted }

        init() {
            session = GestureSession(clock: clock.get, output: { [unowned self] output in
                self.lock.lock(); self.emitted += output.events.map(\.name); self.lock.unlock()
                self.record(.output(predicted: output.predictSeconds != nil, frame: output.pose.frame != nil))
            }, invalid: { [unowned self] _, _ in
                self.record(.invalid)
            }, onStall: { [unowned self] _, stall in
                self.lock.lock(); self.stalls.append(stall); self.lock.unlock()
            }, onDrop: { [unowned self] _, _ in
                self.record(.dropped)
            })
        }

        private func record(_ fate: Fate) {
            lock.lock(); fates.append(fate); lock.unlock()
            settled.signal()
        }

        private var sequence: UInt32 = 0

        /// Stamps `receivedAt`, reads the clock as `now` (default: receipt).
        @discardableResult
        func feed(_ packet: Data, at receivedAt: Double, now: Double? = nil) -> Fate? {
            clock.set(now ?? receivedAt)
            sequence += 1
            session.ingest(packet, session: 1, sequence: sequence, receivedAt: receivedAt)
            guard settled.wait(timeout: .now() + 2) == .success else { return nil }
            lock.lock(); defer { lock.unlock() }
            return fates.last
        }
    }

    /// Fingers-down RT02 packet: decoded axis 1 is 8005 counts (1 g).
    private let down = ColmiR02Protocol.packet(command: 0xa1, payload: [3, 0x1f, 0x45, 0, 1, 0, 2])

    private struct UnexpectedFate: Error { let fate: Probe.Fate? }

    /// Calibrates and runs until the first prediction; returns the next receipt time.
    private func warm(_ probe: Probe) throws -> Double {
        var time = 100.0
        for _ in 0..<200 {
            let fate = probe.feed(down, at: time)
            time += 0.04
            if case .output(predicted: true, frame: true) = fate { return time }
            guard case .output = fate else { throw UnexpectedFate(fate: fate) }
        }
        XCTFail("no prediction within 200 samples")
        return time
    }

    func testAnAgedBacklogIsDroppedThenTheWindowRestartsWithoutAnyPredictionSpanningIt() throws {
        let probe = Probe(), spy = SpyClassifier()
        probe.session.start(session: 1, classifier: spy)
        var time = try warm(probe)
        let last = time - 0.04
        let predictionsBefore = spy.count

        // Five samples reach the worker 0.30-0.46 s old (a slow prediction or
        // a main-queue stall before the hop): all dropped, one episode.
        let late = last + 0.50
        for _ in 0..<5 {
            XCTAssertEqual(probe.feed(down, at: time, now: late), .dropped)
            time += 0.04
        }
        // Quarantine: dropped until three spacings of at least 20 ms.
        XCTAssertEqual(probe.feed(down, at: time), .dropped); time += 0.04
        XCTAssertEqual(probe.feed(down, at: time), .dropped); time += 0.04
        XCTAssertEqual(probe.feed(down, at: time), .output(predicted: false, frame: true))
        time += 0.04
        XCTAssertEqual(probe.stalls.count, 1)
        let stall = try XCTUnwrap(probe.stalls.first)
        XCTAssertEqual(stall.check, "age_dequeue")
        XCTAssertEqual(stall.dropped, 7)
        XCTAssertEqual(stall.value, 0.46, accuracy: 1e-9)

        // The window restarted at the release sample: 49 more samples predict
        // nothing, the 50th post-reset sample predicts once.
        for _ in 0..<48 {
            XCTAssertEqual(probe.feed(down, at: time), .output(predicted: false, frame: true))
            time += 0.04
        }
        XCTAssertEqual(spy.count, predictionsBefore)
        XCTAssertEqual(probe.feed(down, at: time), .output(predicted: true, frame: true))
        XCTAssertEqual(spy.count, predictionsBefore + 1)
        XCTAssertNil(probe.session.lastFault)
    }

    func testAStallJustUnderTheCeilingIsToleratedOnceAndJustOverIsFatal() throws {
        let under = Probe()
        under.session.start(session: 1, classifier: SpyClassifier())
        under.feed(down, at: 10)
        XCTAssertNil(under.session.openStallSince)
        XCTAssertEqual(under.feed(down, at: 10.49), .dropped)
        XCTAssertNil(under.session.lastFault)
        XCTAssertEqual(under.session.openStallSince, 10.49, "the episode is open until release")
        XCTAssertEqual(under.feed(down, at: 10.53), .dropped)
        XCTAssertEqual(under.feed(down, at: 10.57), .dropped)
        XCTAssertEqual(under.feed(down, at: 10.61), .output(predicted: false, frame: false))
        XCTAssertNil(under.session.openStallSince, "released")

        let over = Probe()
        over.session.start(session: 1, classifier: SpyClassifier())
        over.feed(down, at: 10)
        XCTAssertEqual(over.feed(down, at: 10.51), .invalid)
        let fault = try XCTUnwrap(over.session.lastFault)
        XCTAssertEqual(fault.check, "gap")
        XCTAssertEqual(fault.tolerance, "ceiling")
        XCTAssertEqual(try XCTUnwrap(fault.value), 0.51, accuracy: 1e-9)
        XCTAssertEqual(try XCTUnwrap(fault.previousReceivedAt), 10, accuracy: 1e-9)
        XCTAssertEqual(try XCTUnwrap(fault.sinceFirstSample), 0.51, accuracy: 1e-9)

        let aged = Probe()
        aged.session.start(session: 1, classifier: SpyClassifier())
        aged.feed(down, at: 10)
        XCTAssertEqual(aged.feed(down, at: 10.04, now: 10.56), .invalid)
        XCTAssertEqual(aged.session.lastFault?.check, "age_dequeue")
        XCTAssertEqual(aged.session.lastFault?.tolerance, "ceiling")
        XCTAssertNil(aged.session.openStallSince)
    }

    func testAHoleOverTheCeilingIsFatalEvenWhenItsSampleIsAlsoLate() throws {
        // S1 reaches the worker 0.30 s after receipt and 0.80 s after S0: the
        // first post-stall sample of a main-queue stall often carries both.
        // The late hop must not turn a 0.8 s hole into a tolerated episode.
        let late = Probe()
        late.session.start(session: 1, classifier: SpyClassifier())
        late.feed(down, at: 10.00)
        XCTAssertEqual(late.feed(down, at: 10.80, now: 11.10), .invalid)
        let fault = try XCTUnwrap(late.session.lastFault)
        XCTAssertEqual(fault.check, "gap")
        XCTAssertEqual(fault.tolerance, "ceiling")
        XCTAssertEqual(try XCTUnwrap(fault.value), 0.80, accuracy: 1e-9)
        XCTAssertEqual(fault.limit, GestureFreshness.stallCeiling)
        XCTAssertTrue(late.stalls.isEmpty)

        // Mirrored: a tolerable gap, an age over the ceiling.
        let aged = Probe()
        aged.session.start(session: 1, classifier: SpyClassifier())
        aged.feed(down, at: 10.00)
        XCTAssertEqual(aged.feed(down, at: 10.30, now: 10.85), .invalid)
        XCTAssertEqual(aged.session.lastFault?.check, "age_dequeue")
        XCTAssertEqual(aged.session.lastFault?.tolerance, "ceiling")
        XCTAssertEqual(try XCTUnwrap(aged.session.lastFault?.value), 0.55, accuracy: 1e-9)

        // The same rule while an episode is open: extending it cannot hide a hole either.
        let open = Probe()
        open.session.start(session: 1, classifier: SpyClassifier())
        open.feed(down, at: 10.00)
        XCTAssertEqual(open.feed(down, at: 10.30), .dropped)
        XCTAssertEqual(open.feed(down, at: 11.00, now: 11.30), .invalid)
        XCTAssertEqual(open.session.lastFault?.check, "gap")
        XCTAssertEqual(open.session.lastFault?.tolerance, "ceiling")
        XCTAssertEqual(try XCTUnwrap(open.session.lastFault?.value), 0.70, accuracy: 1e-9)

        // Both under the ceiling: the larger names the tolerated episode.
        let both = Probe()
        both.session.start(session: 1, classifier: SpyClassifier())
        both.feed(down, at: 10.00)
        XCTAssertEqual(both.feed(down, at: 10.40, now: 10.70), .dropped)
        for time in [10.44, 10.48] { XCTAssertEqual(both.feed(down, at: time), .dropped) }
        XCTAssertEqual(both.feed(down, at: 10.52), .output(predicted: false, frame: false))
        let stall = try XCTUnwrap(both.stalls.first)
        XCTAssertEqual(stall.check, "gap")
        XCTAssertEqual(stall.value, 0.40, accuracy: 1e-9)
    }

    func testAnEpisodeThatKeepsViolatingPastOneSecondIsFatal() throws {
        let probe = Probe()
        probe.session.start(session: 1, classifier: SpyClassifier())
        probe.feed(down, at: 10)
        var time = 10.3
        // Every sample 0.3 s apart: each violates and extends the episode.
        while time < 11.3 {
            XCTAssertEqual(probe.feed(down, at: time), .dropped)
            time += 0.3
        }
        XCTAssertEqual(probe.feed(down, at: time), .invalid)
        XCTAssertEqual(probe.session.lastFault?.tolerance, "episode_length")
        XCTAssertTrue(probe.stalls.isEmpty)
    }

    func testAnEpisodeTenSecondsAfterThePreviousIsToleratedAgain() throws {
        let probe = Probe()
        probe.session.start(session: 1, classifier: SpyClassifier())
        var time = 10.0
        func steady(_ count: Int) {
            for _ in 0..<count { probe.feed(down, at: time); time += 0.04 }
        }
        steady(1)
        time += 0.26
        XCTAssertEqual(probe.feed(down, at: time), .dropped)
        time += 0.04
        steady(3)
        XCTAssertEqual(probe.stalls.count, 1)
        steady(250) // 10 s of receipt time
        time += 0.26
        XCTAssertEqual(probe.feed(down, at: time), .dropped)
        time += 0.04
        steady(3)
        XCTAssertEqual(probe.stalls.count, 2)
        XCTAssertNil(probe.session.lastFault)
    }

    func testOrderingFailuresStayFatalDuringAStallEpisode() throws {
        let probe = Probe()
        probe.session.start(session: 1, classifier: SpyClassifier())
        probe.feed(down, at: 10)
        XCTAssertEqual(probe.feed(down, at: 10.3), .dropped)
        XCTAssertEqual(probe.feed(down, at: 10.3), .invalid, "equal receipt time")
        XCTAssertEqual(probe.session.lastFault?.check, "nonmonotonic")
    }

    func testDispatchAgeBoundsActionLatency() {
        XCTAssertEqual(GestureFreshness.dispatchLimit, 0.75)
        XCTAssertTrue(GestureFreshness.dispatchable(receivedAt: 10, now: 10.75))
        XCTAssertFalse(GestureFreshness.dispatchable(receivedAt: 10, now: 10.76))
        XCTAssertFalse(GestureFreshness.dispatchable(receivedAt: .nan, now: 10))
        XCTAssertEqual(GestureFreshness.stallCeiling, GestureFreshness.postInferenceLimit)
    }

    // MARK: Sustained gestures across a stall

    /// Feeds `count` samples 40 ms apart from `time`, each of which must be processed.
    private func steady(_ probe: Probe, _ time: inout Double, _ count: Int,
                        file: StaticString = #filePath, line: UInt = #line) {
        for _ in 0..<count {
            let fate = probe.feed(down, at: time)
            guard case .output = fate else {
                return XCTFail("sample at \(time) was \(String(describing: fate))", file: file, line: line)
            }
            time += 0.04
        }
    }

    /// A tolerated 0.30 s gap: the violating sample and two quarantined ones are dropped.
    private func toleratedStall(_ probe: Probe, _ time: inout Double,
                                file: StaticString = #filePath, line: UInt = #line) {
        time += 0.26
        for _ in 0..<3 {
            XCTAssertEqual(probe.feed(down, at: time), .dropped, file: file, line: line)
            time += 0.04
        }
    }

    func testOneContinuousWaveAcrossAToleratedStallFiresOnce() throws {
        let probe = Probe(), classifier = LabelClassifier()
        classifier.answer("wave")
        probe.session.start(session: 1, classifier: classifier)
        var time = 100.0
        steady(probe, &time, 200) // calibrate, then wave long enough to fire
        XCTAssertEqual(probe.events, ["wave"])

        // The same wave continues through a tolerated stall. The restarted
        // window must not judge it as a new wave (a mapped play/pause would
        // toggle back).
        toleratedStall(probe, &time)
        steady(probe, &time, 100)
        XCTAssertEqual(probe.stalls.count, 1)
        XCTAssertEqual(probe.events, ["wave"], "one wave, one event")

        // Control: the wave ends, and a new one more than 2 s later still fires.
        classifier.answer("none")
        steady(probe, &time, 100)
        classifier.answer("wave")
        steady(probe, &time, 100)
        XCTAssertEqual(probe.events, ["wave", "wave"])
        XCTAssertNil(probe.session.lastFault)
    }

    func testAWaveNotYetJudgedAtAStallFiresOnceAfterIt() throws {
        // One or two wave windows before the stall fired nothing, so the
        // judgement after the release is the wave's only event.
        let probe = Probe(), classifier = LabelClassifier()
        classifier.answer("none")
        probe.session.start(session: 1, classifier: classifier)
        var time = 100.0
        steady(probe, &time, 200)
        classifier.answer("wave")
        steady(probe, &time, 7)
        XCTAssertEqual(probe.events, [])
        toleratedStall(probe, &time)
        steady(probe, &time, 100)
        XCTAssertEqual(probe.events, ["wave"])
        XCTAssertEqual(probe.stalls.count, 1)
    }

    // MARK: Classifier sharing

    func testWarmUpRunsOneRealPredictionAndConcurrentCallsAgree() throws {
        let classifier = try PinnedGestureClassifier()
        let warm = try classifier.warmUp()
        XCTAssertEqual(warm.count, 12)
        XCTAssertTrue(warm.allSatisfy { $0.isFinite && $0 >= 0 && $0 <= 1 })
        let features = (0..<450).map { Float(sin(Double($0) * 0.1)) * 0.5 }
        let expected = try classifier.probabilities(features)
        let group = DispatchGroup(), lock = NSLock()
        var results: [[Float]] = []
        for label in ["a", "b"] {
            DispatchQueue(label: "classifier.\(label)").async(group: group) {
                for _ in 0..<20 {
                    let result = try? classifier.probabilities(features)
                    lock.lock(); results.append(result ?? []); lock.unlock()
                }
            }
        }
        XCTAssertEqual(group.wait(timeout: .now() + 10), .success)
        XCTAssertEqual(results.count, 40)
        XCTAssertTrue(results.allSatisfy { $0 == expected })
    }
}
