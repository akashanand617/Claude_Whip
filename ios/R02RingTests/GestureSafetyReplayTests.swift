import XCTest
@testable import R02Ring

final class GestureSafetyReplayTests: XCTestCase {
    private struct Fixture: Decodable {
        struct Window: Decodable {
            let name: String; let label: String; let rotation: String
            let counts: [[Double]]; let features: [Float]; let probabilities: [Float]
        }
        struct Event: Decodable {
            let name: String; let direction: String; let t_s: Double; let confidence: Double
            let run_length: Int; let latency_s: Double?; let end_s: Double?
        }
        struct Trace: Decodable {
            let name: String; let samples: [[Double]]; let probabilities: [[Float]]
            let reset_indices: [Int]; let events: [Event]
        }
        struct Replay: Decodable { let name: String; let samples: [[Double]]; let events: [Event] }
        let windows: [Window]; let traces: [Trace]; let replays: [Replay]
    }

    private func fixture() throws -> Fixture {
        let bundle = Bundle(for: Self.self)
        let url = try XCTUnwrap(bundle.url(forResource: "gesture-safety-replay", withExtension: "json")
                               ?? bundle.url(forResource: "gesture-safety-replay", withExtension: "json", subdirectory: "Fixtures"))
        return try JSONDecoder().decode(Fixture.self, from: Data(contentsOf: url))
    }

    private func compare(_ actual: [RingGestureEvent], _ expected: [Fixture.Event], _ name: String,
                         file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(actual.count, expected.count, name, file: file, line: line)
        for (got, want) in zip(actual, expected) {
            XCTAssertEqual(got.name, want.name, name, file: file, line: line)
            XCTAssertEqual(got.direction, want.direction, name, file: file, line: line)
            XCTAssertEqual(got.time, want.t_s, accuracy: 1e-8, name, file: file, line: line)
            XCTAssertEqual(got.votes, want.run_length, name, file: file, line: line)
            XCTAssertEqual(got.confidence, want.confidence, accuracy: 1e-5, name, file: file, line: line)
            XCTAssertEqual(got.latency ?? -1, want.latency_s ?? -1, accuracy: 1e-8, name, file: file, line: line)
            XCTAssertEqual(got.end ?? -1, want.end_s ?? -1, accuracy: 1e-8, name, file: file, line: line)
        }
    }

    func testAllClassesAndThreeFrameVariantsMatchPythonNumerically() throws {
        let fixture = try fixture(), classifier = try PinnedGestureClassifier()
        XCTAssertEqual(fixture.windows.count, 108)
        XCTAssertEqual(Set(fixture.windows.map(\.label)), Set(GestureContract.labels))
        XCTAssertEqual(Set(fixture.windows.map(\.rotation)), ["identity", "flip_axis0", "quarter_spin"])
        for window in fixture.windows {
            let features = try GestureContract.features(window.counts)
            XCTAssertEqual(features.count, window.features.count)
            for (got, want) in zip(features, window.features) {
                XCTAssertEqual(got, want, accuracy: 1e-6, window.name)
            }
            let probabilities = try classifier.probabilities(features)
            for (got, want) in zip(probabilities, window.probabilities) {
                XCTAssertEqual(got, want, accuracy: 1e-5, window.name)
            }
        }
    }

    private func replay(_ trace: Fixture.Trace) throws {
        var index = 0
        let engine = GestureInference { _ in
            guard index < trace.probabilities.count else {
                XCTFail("extra model call: \(trace.name)"); throw RingProtocolError.invalidPacket
            }
            defer { index += 1 }
            return trace.probabilities[index]
        }
        var actual: [RingGestureEvent] = []
        for (i, row) in trace.samples.enumerated() {
            if trace.reset_indices.contains(i) { engine.reset() }
            actual += try engine.feed(time: row[0], counts: Array(row.dropFirst()))
        }
        XCTAssertEqual(index, trace.probabilities.count, trace.name)
        compare(actual, trace.events, trace.name)
    }

    func testEverySyntheticClassConsecutiveMovementsAndResetMatchPython() throws {
        for trace in try fixture().traces where !trace.name.hasPrefix("direction_vote_tie") { try replay(trace) }
    }

    func testDirectionVoteTieMatchesPinnedPythonOracle() throws {
        let expected = ["direction_vote_tie": "up", "direction_vote_tie_reversed": "down",
                        "direction_vote_tie_horizontal": "right", "direction_vote_tie_horizontal_reversed": "left"]
        for (name, direction) in expected {
            let trace = try XCTUnwrap(fixture().traces.first { $0.name == name })
            XCTAssertEqual(trace.events.count, 1)
            XCTAssertEqual(trace.events.first?.direction, direction, "Earliest tied vote must win")
            try replay(trace)
        }
    }

    func testSustainedDirectionUsesMajorityThenFirstNonNoneVote() {
        for (directions, expected) in [(["up", "down", "none"], "up"),
                                       (["down", "up", "none"], "down"),
                                       (["up", "down", "down"], "down"),
                                       (["none", "none", "none"], "none")] {
            let tracker = GestureBurstTracker()
            var actual: [RingGestureEvent] = []
            for (index, direction) in directions.enumerated() {
                actual += tracker.window(Double(index) * 0.24, label: "wave", confidence: 0.8, direction: direction)
            }
            XCTAssertEqual(actual.count, 1)
            XCTAssertEqual(actual.first?.direction, expected)
        }
    }

    func testRecordedPostureAndSustainedWaveStreamsMatchPython() throws {
        let classifier = try PinnedGestureClassifier()
        for trace in try fixture().replays {
            let engine = GestureInference(predict: classifier.probabilities)
            var actual: [RingGestureEvent] = []
            for row in trace.samples { actual += try engine.feed(time: row[0], counts: Array(row.dropFirst())) }
            compare(actual, trace.events, trace.name)
        }
    }
}
