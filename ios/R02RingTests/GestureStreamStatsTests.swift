import XCTest
@testable import R02Ring

@MainActor
final class GestureStreamStatsTests: XCTestCase {
    func testGapHopAndRate() {
        var stats = GestureStreamStats()
        XCTAssertEqual(stats.total.samples, 0)
        XCTAssertNil(stats.total.rateHz)
        for (received, processed) in [(10.00, 10.01), (10.04, 10.06), (10.08, 10.085), (10.20, 10.50)] {
            stats.record(receivedAt: received, processedAt: processed)
        }
        XCTAssertEqual(stats.total.samples, 4)
        XCTAssertEqual(stats.total.maxGap, 0.12, accuracy: 1e-9)
        XCTAssertEqual(stats.total.maxHop, 0.30, accuracy: 1e-9)
        XCTAssertEqual(stats.total.duration, 0.20, accuracy: 1e-9)
        XCTAssertEqual(try XCTUnwrap(stats.total.rateHz), 15, accuracy: 1e-6)
        XCTAssertEqual(stats.window, stats.total)
    }

    func testOutOfOrderNonFiniteAndNegativeHop() {
        var stats = GestureStreamStats()
        stats.record(receivedAt: 5, processedAt: 4.9) // hop clamps to zero
        stats.record(receivedAt: 4.96, processedAt: 5.1) // older receipt: ignored
        stats.record(receivedAt: .nan, processedAt: 5.1)
        stats.record(receivedAt: 5.04, processedAt: .infinity)
        XCTAssertEqual(stats.total.samples, 1)
        XCTAssertEqual(stats.total.maxHop, 0)
        XCTAssertEqual(stats.total.maxGap, 0)
        stats.record(receivedAt: 5.04, processedAt: 5.05)
        XCTAssertEqual(stats.total.samples, 2)
        XCTAssertEqual(stats.total.maxGap, 0.04, accuracy: 1e-9)
    }

    func testWindowsCloseEveryFiveSecondsAndGapSpansWindows() {
        var stats = GestureStreamStats()
        XCTAssertEqual(GestureStreamStats.summaryInterval, 5)
        var t = 100.0
        while t < 104.99 {
            stats.record(receivedAt: t, processedAt: t + 0.002)
            t += 0.04
        }
        XCTAssertFalse(stats.windowDue)
        stats.record(receivedAt: 105.0, processedAt: 105.002)
        XCTAssertTrue(stats.windowDue)
        let first = stats.closeWindow()
        XCTAssertEqual(first.samples, stats.total.samples)
        XCTAssertEqual(stats.window.samples, 0)
        XCTAssertFalse(stats.windowDue)

        stats.record(receivedAt: 105.5, processedAt: 105.51) // 0.5 s stall across the boundary
        XCTAssertEqual(stats.window.samples, 1)
        XCTAssertEqual(stats.window.maxGap, 0.5, accuracy: 1e-9)
        XCTAssertEqual(stats.total.maxGap, 0.5, accuracy: 1e-9)
        XCTAssertEqual(stats.total.samples, first.samples + 1)

        stats.reset()
        XCTAssertEqual(stats, GestureStreamStats())
    }

    func testSummaryFieldsAreRoundedJSON() throws {
        var stats = GestureStreamStats()
        let empty = stats.total.fields
        XCTAssertTrue(empty["rate_hz"] is NSNull)
        XCTAssertEqual(empty["samples"] as? Int, 0)
        stats.record(receivedAt: 1, processedAt: 1.0004)
        stats.record(receivedAt: 1.0625, processedAt: 1.07)
        let fields = stats.total.fields
        XCTAssertEqual(Set(fields.keys), ["samples", "duration_s", "rate_hz", "max_gap_s", "max_hop_s",
                                          "gaps_over_120ms", "gaps_under_10ms", "max_predict_ms",
                                          "max_queue", "max_same_run"])
        XCTAssertEqual(fields["samples"] as? Int, 2)
        XCTAssertEqual(fields["max_gap_s"] as? Double, 0.062)
        XCTAssertEqual(fields["duration_s"] as? Double, 0.062)
        XCTAssertEqual(fields["rate_hz"] as? Double, 16)
        XCTAssertEqual(fields["max_hop_s"] as? Double, 0.008)
        XCTAssertTrue(JSONSerialization.isValidJSONObject(fields))
        XCTAssertTrue(fields["max_predict_ms"] is NSNull)
        XCTAssertTrue(fields["max_queue"] is NSNull)
    }

    func testConnectionLatticeInferenceAndRepeatCounters() throws {
        var stats = GestureStreamStats()
        let receipts = [0.0, 0.030, 0.031, 0.141, 0.142, 0.252, 0.282]
        for (index, time) in receipts.enumerated() {
            stats.record(receivedAt: time, processedAt: time + 0.001,
                         predictSeconds: index == 3 ? 0.0123 : nil, queued: index == 5 ? 3 : 1,
                         sameRun: index == 6 ? 4 : 1)
        }
        // Spacings: 30, 1, 110, 1, 110, 30 ms.
        XCTAssertEqual(stats.total.gapsOver120ms, 0)
        XCTAssertEqual(stats.total.gapsUnder10ms, 2)
        stats.record(receivedAt: 0.412, processedAt: 0.413) // 130 ms
        XCTAssertEqual(stats.total.gapsOver120ms, 1)
        let fields = stats.total.fields
        XCTAssertEqual(fields["max_predict_ms"] as? Double, 12.3)
        XCTAssertEqual(fields["max_queue"] as? Int, 3)
        XCTAssertEqual(fields["max_same_run"] as? Int, 4)
        XCTAssertEqual(fields["gaps_over_120ms"] as? Int, 1)
        XCTAssertTrue(JSONSerialization.isValidJSONObject(fields))
        let window = stats.closeWindow()
        XCTAssertEqual(window.gapsUnder10ms, 2)
        XCTAssertEqual(stats.window.gapsUnder10ms, 0)
    }
}
