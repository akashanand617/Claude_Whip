import XCTest
@testable import R02Ring

final class GestureReplayTests: XCTestCase {
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
            XCTAssertEqual(features.count, 400)
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
