import XCTest
@testable import R02Ring

@MainActor
final class GestureEventLogTests: XCTestCase {
    /// `whip.realtime.GestureEvent.as_dict()` keys plus `action` and `wall`.
    private let pythonKeys: Set<String> = [
        "name", "direction", "t_s", "confidence", "run_length", "latency_s", "end_s", "action", "wall",
    ]
    private var root: URL!

    override func setUp() {
        super.setUp()
        root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
    }

    override func tearDown() {
        try? FileManager.default.removeItem(at: root)
        super.tearDown()
    }

    private func lines(_ url: URL) throws -> [[String: Any]] {
        try String(contentsOf: url, encoding: .utf8).split(separator: "\n").map {
            try XCTUnwrap(JSONSerialization.jsonObject(with: Data($0.utf8)) as? [String: Any])
        }
    }

    /// The same three events the fixture was written from, on a stream that started at uptime 1000.
    private let fixtureEvents: [(RingGestureEvent, GestureActionID?, Double)] = [
        (RingGestureEvent(name: "flick", direction: "right", time: 1_012.3456, confidence: 0.91234,
                          votes: 5, latency: 1.4, end: 1_012.8456), .flag, 1_790_000_012.5),
        (RingGestureEvent(name: "double_flick", direction: "up", time: 1_020.1, confidence: 0.8737,
                          votes: 4, latency: 2.05, end: 1_020.9), .approve, 1_790_000_020.75),
        (RingGestureEvent(name: "wave", direction: "none", time: 1_031, confidence: 0.8,
                          votes: 3, latency: nil, end: nil), nil, 1_790_000_032),
    ]

    func testLineHasExactlyThePythonKeysAndParsesBack() throws {
        XCTAssertEqual(GestureEventLog.keys, pythonKeys)
        let log = GestureEventLog(streamStart: 1_000, root: root, startedWall: 1_790_000_000)
        for (event, action, wall) in fixtureEvents { log.record(event, action: action, wall: wall) }
        log.flush()
        let parsed = try lines(log.url)
        XCTAssertEqual(parsed.count, 3)
        for line in parsed { XCTAssertEqual(Set(line.keys), pythonKeys) }

        let flag = parsed[0]
        XCTAssertEqual(flag["name"] as? String, "flick")
        XCTAssertEqual(flag["direction"] as? String, "right")
        XCTAssertEqual(flag["t_s"] as? Double, 12.346)
        XCTAssertEqual(flag["end_s"] as? Double, 12.846)
        XCTAssertEqual(flag["latency_s"] as? Double, 1.4)
        XCTAssertEqual(flag["confidence"] as? Double, 0.912)
        XCTAssertEqual(flag["run_length"] as? Int, 5)
        XCTAssertEqual(flag["action"] as? String, "flag")
        XCTAssertEqual(flag["wall"] as? Double, 1_790_000_012.5)

        let wave = parsed[2]
        XCTAssertTrue(wave["action"] is NSNull)
        XCTAssertTrue(wave["latency_s"] is NSNull)
        XCTAssertTrue(wave["end_s"] is NSNull)
        XCTAssertEqual(wave["t_s"] as? Double, 31)

        let text = try String(contentsOf: log.url, encoding: .utf8)
        XCTAssertTrue(text.hasSuffix("\n"))
        XCTAssertTrue(text.contains(#""action":null"#))
        // Whole numbers keep Python's float form, so json.loads yields float, not int.
        XCTAssertTrue(text.contains(#""t_s":31.0,"#))
        XCTAssertTrue(text.contains(#""wall":1790000032.0}"#))
        XCTAssertTrue(text.contains(#""run_length":3,"#))
    }

    func testNumbersUsePythonJSONText() throws {
        // Expected strings are CPython `json.dumps(round(x, 3))`.
        let cases: [(Double, String)] = [
            (0.912, "0.912"), (31, "31.0"), (1_790_000_032, "1790000032.0"), (-0.0004, "-0.0"),
            (0.0625, "0.062"), (1.0005, "1.0"), (12.3456, "12.346"), (1e-7, "0.0"), (1_790_000_012.5, "1790000012.5"),
        ]
        for (value, expected) in cases {
            let line = GestureEventLine(name: "snap", direction: "none", tS: GestureEventLog.rounded(value),
                                        confidence: nil, runLength: 1, latencyS: nil, endS: nil, action: nil, wall: nil)
            let text = String(decoding: try line.encoded(), as: UTF8.self)
            XCTAssertTrue(text.contains(#""t_s":\#(expected),"#), "\(value): \(text)")
        }
        let line = GestureEventLine(name: "a\"b\\c/d", direction: "none", tS: nil, confidence: nil, runLength: 0,
                                    latencyS: nil, endS: nil, action: "flag", wall: 1_790_000_000.123456)
        let text = String(decoding: try line.encoded(), as: UTF8.self)
        XCTAssertEqual(text, #"{"action":"flag","confidence":null,"direction":"none","end_s":null,"#
                       + #""latency_s":null,"name":"a\"b\\c/d","run_length":0,"t_s":null,"wall":1790000000.123456}"#)
        let parsed = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any])
        XCTAssertEqual(parsed["name"] as? String, "a\"b\\c/d")
    }

    func testRoundingMatchesPythonRoundToThreePlaces() {
        // Values from CPython `round(x, 3)`; naive `(x * 1000).rounded()` gets the first four wrong.
        let cases: [(Double, Double)] = [
            (0.0625, 0.062), (1.0005, 1.0), (2.0625, 2.062), (0.1235, 0.123),
            (12.3456, 12.346), (1.2345, 1.234), (0.9995, 1.0), (-1.5, -1.5), (3, 3),
        ]
        for (value, expected) in cases {
            XCTAssertEqual(GestureEventLog.rounded(value), expected, "\(value)")
        }
        XCTAssertNil(GestureEventLog.rounded(.nan))
        XCTAssertNil(GestureEventLog.rounded(.infinity))
    }

    func testTimesAreRelativeToStreamStartAndNonFiniteBecomesNull() throws {
        let event = RingGestureEvent(name: "snap", direction: "none", time: 250.25, confidence: .nan,
                                     votes: 2, latency: 0.75, end: 250.5)
        let line = GestureEventLog.line(for: event, action: .pause_gestures, wall: .infinity, streamStart: 200)
        XCTAssertEqual(line, GestureEventLine(name: "snap", direction: "none", tS: 50.25, confidence: nil,
                                              runLength: 2, latencyS: 0.75, endS: 50.5,
                                              action: "pause_gestures", wall: nil))
        let parsed = try XCTUnwrap(JSONSerialization.jsonObject(with: line.encoded()) as? [String: Any])
        XCTAssertEqual(Set(parsed.keys), pythonKeys)
        XCTAssertTrue(parsed["confidence"] is NSNull)
        XCTAssertTrue(parsed["wall"] is NSNull)

        let log = GestureEventLog(streamStart: 200, root: root, startedWall: 1_790_000_000)
        log.record(event, action: nil, wall: .nan)
        log.flush()
        let written = try lines(log.url)
        XCTAssertEqual(written.count, 1)
        XCTAssertTrue(written[0]["wall"] is NSNull)
        XCTAssertTrue(written[0]["action"] is NSNull)
    }

    func testFileIsNamedLikePythonAndCreatedLazily() throws {
        let log = GestureEventLog(streamStart: 0, root: root, startedWall: 1_790_000_000)
        let name = log.url.lastPathComponent
        XCTAssertNotNil(name.range(of: #"^events_\d{8}_\d{6}\.jsonl$"#, options: .regularExpression), name)
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyyMMdd_HHmmss"
        XCTAssertEqual(name, "events_\(formatter.string(from: Date(timeIntervalSince1970: 1_790_000_000))).jsonl")
        XCTAssertEqual(log.url.deletingLastPathComponent().standardizedFileURL, root.standardizedFileURL)
        XCTAssertEqual(GestureEventLog.defaultRoot.lastPathComponent, "GestureEvents")

        log.flush()
        XCTAssertFalse(FileManager.default.fileExists(atPath: log.url.path))
        XCTAssertEqual(GestureEventLog.files(in: root), [])
        log.record(fixtureEvents[0].0, action: .flag, wall: 1)
        log.flush()
        XCTAssertTrue(FileManager.default.fileExists(atPath: log.url.path))
        XCTAssertEqual(GestureEventLog.files(in: root).map(\.lastPathComponent), [name])
    }

    func testAppendsToAnExistingFileAndDropsLinesAfterClose() throws {
        let first = GestureEventLog(streamStart: 1_000, root: root, startedWall: 1_790_000_000)
        first.record(fixtureEvents[0].0, action: .flag, wall: 1)
        first.close()
        first.record(fixtureEvents[1].0, action: .approve, wall: 2)
        first.flush()
        XCTAssertEqual(try lines(first.url).count, 1)

        let second = GestureEventLog(streamStart: 1_000, root: root, startedWall: 1_790_000_000)
        XCTAssertEqual(second.url, first.url)
        second.record(fixtureEvents[2].0, action: nil, wall: 3)
        second.close()
        let parsed = try lines(second.url)
        XCTAssertEqual(parsed.map { $0["wall"] as? Double }, [1, 3])
    }

    func testJournalUsesAPrefixTheJoinNeverReads() throws {
        let journal = GestureSessionJournal(root: root)
        journal.record("session_start", fields: ["reason": "intent", "foreground": false, "bad": Double.nan,
                                                 "kind": "spoofed", "stats": ["max_gap_s": Double.infinity]],
                       wall: 1_790_000_000, uptime: 42.12345)
        journal.flush()
        let url = journal.url(forWall: 1_790_000_000)
        let name = url.lastPathComponent
        XCTAssertNotNil(name.range(of: #"^lifecycle_\d{8}\.jsonl$"#, options: .regularExpression), name)
        XCTAssertFalse(name.hasPrefix("events_"))
        XCTAssertEqual(GestureSessionJournal.files(in: root), [url])
        XCTAssertEqual(GestureEventLog.files(in: root), [])

        let line = try XCTUnwrap(lines(url).first)
        XCTAssertEqual(line["kind"] as? String, "session_start")
        XCTAssertEqual(line["reason"] as? String, "intent")
        XCTAssertEqual(line["foreground"] as? Bool, false)
        XCTAssertEqual(line["wall"] as? Double, 1_790_000_000)
        XCTAssertEqual(line["uptime"] as? Double, 42.123)
        XCTAssertTrue(line["bad"] is NSNull)
        XCTAssertTrue((line["stats"] as? [String: Any])?["max_gap_s"] is NSNull)

        let log = GestureEventLog(streamStart: 0, root: root, startedWall: 1_790_000_000)
        log.record(fixtureEvents[0].0, action: .flag, wall: 1)
        log.flush()
        journal.close()
        XCTAssertEqual(GestureEventLog.files(in: root), [log.url])
        XCTAssertEqual(GestureSessionJournal.files(in: root), [url])
    }

    func testSharedFixtureMatchesTheSwiftLineShape() throws {
        let fixture = try fixtureURL()
        let expected = try lines(fixture)
        XCTAssertEqual(expected.count, 3)
        XCTAssertEqual(expected.compactMap { $0["action"] as? String }, ["flag", "approve"])
        for line in expected { XCTAssertEqual(Set(line.keys), GestureEventLog.keys) }

        let log = GestureEventLog(streamStart: 1_000, root: root, startedWall: 1_790_000_000)
        for (event, action, wall) in fixtureEvents { log.record(event, action: action, wall: wall) }
        log.close()
        // Byte-identical: the fixture is exactly what the app writes.
        XCTAssertEqual(try String(contentsOf: log.url, encoding: .utf8),
                       try String(contentsOf: fixture, encoding: .utf8))
        let written = try lines(log.url)
        for (made, stored) in zip(written, expected) {
            XCTAssertEqual(made as NSDictionary, stored as NSDictionary)
        }
    }

    private func fixtureURL() throws -> URL {
        let bundle = Bundle(for: Self.self)
        if let url = bundle.url(forResource: "ios-event-log-sample", withExtension: "jsonl")
            ?? bundle.url(forResource: "ios-event-log-sample", withExtension: "jsonl", subdirectory: "Fixtures") {
            return url
        }
        let source = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .appendingPathComponent("Fixtures/ios-event-log-sample.jsonl")
        XCTAssertTrue(FileManager.default.fileExists(atPath: source.path), source.path)
        return source
    }
}
