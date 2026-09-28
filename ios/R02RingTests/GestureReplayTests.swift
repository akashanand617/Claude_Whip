import XCTest
@testable import R02Ring

final class GestureReplayTests: XCTestCase {
    private final class LockedClock: @unchecked Sendable {
        private let lock = NSLock()
        private var value = 0.0
        func set(_ next: Double) { lock.lock(); value = next; lock.unlock() }
        func get() -> Double { lock.lock(); defer { lock.unlock() }; return value }
    }

    private struct Fixture: Decodable {
        struct Window: Decodable { let start: Int; let features: [Float]; let probabilities: [Float] }
        struct Event: Decodable {
            let name: String; let direction: String; let t_s: Double; let confidence: Double
            let run_length: Int; let latency_s: Double?; let end_s: Double?
        }
        let samples: [[Double]]
        let windows: [Window]
        let events: [Event]
    }

    private func fixture() throws -> Fixture {
        let bundle = Bundle(for: Self.self)
        let url = try XCTUnwrap(bundle.url(forResource: "gesture-replay", withExtension: "json")
                                ?? bundle.url(forResource: "gesture-replay", withExtension: "json", subdirectory: "Fixtures"))
        return try JSONDecoder().decode(Fixture.self, from: Data(contentsOf: url))
    }

    func testFloat32PreprocessingAndCoreMLProbabilitiesMatchPython() throws {
        let fixture = try fixture(), classifier = try PinnedGestureClassifier()
        for window in fixture.windows {
            let samples = fixture.samples[window.start..<(window.start + 50)].map { Array($0.dropFirst()) }
            let features = try GestureContract.features(samples)
            XCTAssertEqual(features.count, 450)
            for i in features.indices { XCTAssertEqual(features[i], window.features[i], accuracy: 1e-6, "sample \(window.start) feature \(i)") }
            let probabilities = try classifier.probabilities(features)
            for i in probabilities.indices { XCTAssertEqual(probabilities[i], window.probabilities[i], accuracy: 1e-5) }
        }
    }

    func testFullRecordedStreamHasIdenticalPythonEvents() throws {
        let fixture = try fixture(), classifier = try PinnedGestureClassifier()
        let engine = GestureInference(predict: classifier.probabilities)
        var actual: [RingGestureEvent] = []
        for row in fixture.samples { actual += try engine.feed(time: row[0], counts: Array(row.dropFirst())) }
        XCTAssertEqual(actual.count, fixture.events.count)
        for (got, want) in zip(actual, fixture.events) {
            XCTAssertEqual(got.name, want.name); XCTAssertEqual(got.direction, want.direction)
            XCTAssertEqual(got.time, want.t_s, accuracy: 1e-8)
            XCTAssertEqual(got.votes, want.run_length)
            XCTAssertEqual(got.confidence, want.confidence, accuracy: 1e-5)
            XCTAssertEqual(got.latency ?? -1, want.latency_s ?? -1, accuracy: 1e-8)
            XCTAssertEqual(got.end ?? -1, want.end_s ?? -1, accuracy: 1e-8)
        }
    }

    func testDecodeAxisOrderSignAndChecksum() throws {
        let data = ColmiR02Protocol.packet(command: 0xa1, payload: [3, 0xff, 0xff, 0x80, 0, 0x7f, 0xff])
        XCTAssertEqual(try GestureContract.decode(data), [32767, -1, -32768])
        XCTAssertThrowsError(try GestureContract.decode(data.dropLast()))
    }

    func testCalibrationNeedsThreeSecondsAndDetectsReverseWearing() {
        var calibration = GestureCalibration()
        var pose: GesturePose?
        for index in 0..<74 { pose = calibration.feed(time: Double(index) * 0.04, counts: [0, -8005, 0]) }
        XCTAssertNil(pose?.frame)
        pose = calibration.feed(time: 2.96, counts: [0, -8005, 0])
        XCTAssertEqual(pose?.frame, "flip_axis0")
        var wrongPose = GestureCalibration()
        for index in 0..<100 { pose = wrongPose.feed(time: Double(index) * 0.04, counts: [8005, 0, 0]) }
        XCTAssertNil(pose?.frame)
        XCTAssertEqual(pose?.reason, "Point fingers down")
    }

    func testRepeatedStationaryRT12SamplesCanCompleteCalibration() throws {
        let clock = LockedClock(), delivered = DispatchSemaphore(value: 0)
        let classifier = try PinnedGestureClassifier()
        var lastPose: GesturePose?
        var invalidReason: String?
        let session = GestureSession(signalAdapter: .rt12col(), clock: clock.get, output: { output in
            lastPose = output.pose
            delivered.signal()
        }, invalid: { _, reason in
            invalidReason = reason
            delivered.signal()
        })
        _ = session.start(session: 7, classifier: classifier)
        // RT12COL may quantize a motionless calibration pose to the exact same
        // counts repeatedly. Packet receipt time and sequence still advance.
        // GestureContract.decode returns [packet 6..7, 2..3, 4..5]. A physical
        // RT12 fingertips-down capture puts gravity on the third of those;
        // the RT12 rotation moves it to canonical model axis 1.
        let packet = ColmiR02Protocol.packet(
            command: 0xa1, payload: [0x03, 0, 0, 0xe0, 0xbb, 0, 0]
        )
        for index in 0..<75 {
            let time = Double(index) * 0.04
            clock.set(time)
            session.ingest(packet, session: 7, sequence: UInt32(index + 1), receivedAt: time)
            XCTAssertEqual(delivered.wait(timeout: .now() + 1), .success)
            XCTAssertNil(invalidReason)
        }
        XCTAssertEqual(lastPose?.frame, "flip_axis0")
        XCTAssertEqual(lastPose?.reason, "Ready")
    }

    func testHardwareAxisMapsAreExactPermutations() throws {
        let decoded = [11.0, 22.0, 33.0]
        XCTAssertEqual(try GestureAxisMap.rt02cr.apply(decoded), decoded)
        XCTAssertEqual(try GestureAxisMap.rt12col.apply(decoded), [11, 33, -22])
    }

    func testSignalAdaptersNormalizeInMGThenReturnRT02EquivalentCounts() throws {
        let decoded = [11.0, 22.0, 33.0]
        XCTAssertEqual(try GestureSignalAdapter.rt02cr().modelCounts(decodedCounts: decoded), decoded)
        XCTAssertEqual(try GestureSignalAdapter.rt12col().modelCounts(decodedCounts: decoded), [11, 33, -22])

        let mg = try GestureSignalAdapter.rt12col().canonicalMG(decodedCounts: [32_767, -32_768, 4])
        XCTAssertEqual(mg[0], GestureSignalAdapter.rt02MaxMG, accuracy: 1e-12)
        XCTAssertEqual(mg[1], 4 * GestureSignalAdapter.rt02MGPerCount, accuracy: 1e-12)
        XCTAssertEqual(mg[2], GestureSignalAdapter.rt02MaxMG, accuracy: 1e-12)

        let fractional = try GestureSignalAdapter.rt12col().modelCounts(
            decodedCounts: [1.25, 2.5, 3.75]
        )
        XCTAssertEqual(fractional, [1.25, 3.75, -2.5])
    }

    func testPerRingCalibrationIsAppliedAfterRotationAndPersistsByDevice() throws {
        let calibration = GestureSensorCalibration(
            offsetMG: [1, 2, 3], gain: [2, 1, 0.5]
        )
        let adapter = GestureSignalAdapter.rt12col(calibration: calibration)
        let raw = [800.0, 1_600.0, 2_400.0]
        let mg = try adapter.canonicalMG(decodedCounts: raw)
        let grid = GestureSignalAdapter.rt02MGPerCount
        XCTAssertEqual(mg[0], (800 * grid - 1) * 2, accuracy: 1e-9)
        XCTAssertEqual(mg[1], 2_400 * grid - 2, accuracy: 1e-9)
        XCTAssertEqual(mg[2], (-1_600 * grid - 3) * 0.5, accuracy: 1e-9)

        let suite = "GestureSignalAdapterTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        try calibration.store(for: "ring-a", defaults: defaults)
        XCTAssertEqual(GestureSensorCalibration.stored(for: "ring-a", defaults: defaults), calibration)
        XCTAssertEqual(GestureSensorCalibration.stored(for: "ring-b", defaults: defaults), .identity)

        let saturating = GestureSignalAdapter.rt02cr(calibration: .init(
            offsetMG: [0, 0, 0], gain: [2, 2, 2]
        ))
        let rails = try saturating.canonicalMG(decodedCounts: [32_767, -32_768, 0])
        XCTAssertEqual(rails, [
            GestureSignalAdapter.rt02MaxMG,
            GestureSignalAdapter.rt02MinMG,
            0,
        ])
    }

    func testRT12ForwardPoseIsRejectedByDownOnlyGate() throws {
        var calibration = GestureCalibration()
        var pose: GesturePose?
        let forward = try GestureAxisMap.rt12col.apply([8005, 0, 0])
        for index in 0..<100 {
            pose = calibration.feed(time: Double(index) * 0.04, counts: forward)
        }
        XCTAssertNil(pose?.frame)
        XCTAssertEqual(pose?.reason, "Point fingers down")
    }

    func testResetDiscardsPendingEventsInsteadOfFlushing() throws {
        var calls = 0
        let engine = GestureInference { _ in calls += 1; return [1] + Array(repeating: 0, count: 11) }
        for index in 0..<49 { _ = try engine.feed(time: Double(index) * 0.04, counts: [0, 8005, 0]) }
        XCTAssertEqual(calls, 0)
        engine.reset()
        for index in 0..<50 { XCTAssertTrue(try engine.feed(time: Double(index) * 0.04, counts: [0, 8005, 0]).isEmpty) }
        XCTAssertEqual(calls, 1)
    }
}
