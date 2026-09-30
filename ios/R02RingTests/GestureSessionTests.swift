import XCTest
@testable import R02Ring

final class GestureSessionTests: XCTestCase {
    private var packet: Data {
        ColmiR02Protocol.packet(command: 0xa1, payload: [3, 0x1f, 0x45, 0, 1, 0, 2])
    }

    func testOldQueuedPacketCannotProduceOrRenew() async throws {
        let rejected = expectation(description: "stale packet rejected")
        let output = expectation(description: "no processed callback"); output.isInverted = true
        let classifier = try PinnedGestureClassifier()
        let driver = GestureSession(clock: { 10 }, output: { _ in output.fulfill() }, invalid: { _, _ in rejected.fulfill() })
        driver.start(session: 1, classifier: classifier)
        driver.ingest(packet, session: 1, sequence: 1, receivedAt: 9)
        await fulfillment(of: [rejected, output], timeout: 0.5)
        XCTAssertEqual(driver.lastFault?.check, "age_dequeue")
        XCTAssertEqual(driver.lastFault?.tolerance, "ceiling")
    }

    func testAnAgedFirstSampleIsNeverTolerated() async throws {
        let rejected = expectation(description: "first sample rejected")
        let driver = GestureSession(clock: { 10 }, output: { _ in XCTFail("processed") },
                                    invalid: { _, _ in rejected.fulfill() })
        driver.start(session: 1, classifier: try PinnedGestureClassifier())
        driver.ingest(packet, session: 1, sequence: 1, receivedAt: 9.7)
        await fulfillment(of: [rejected], timeout: 0.5)
        let fault = try XCTUnwrap(driver.lastFault)
        XCTAssertEqual(fault.check, "age_dequeue")
        XCTAssertEqual(fault.tolerance, "first_sample")
        XCTAssertEqual(try XCTUnwrap(fault.value), 0.3, accuracy: 1e-9)
        XCTAssertEqual(fault.limit, GestureFreshness.sampleLimit)
        XCTAssertTrue(JSONSerialization.isValidJSONObject(fault.fields))
    }

    func testQueueOverflowInvalidatesEvenInFlightCallback() async throws {
        let entered = expectation(description: "worker reached clock")
        let rejected = expectation(description: "bounded queue overflow")
        let noOutput = expectation(description: "in-flight result invalidated"); noOutput.isInverted = true
        let release = DispatchSemaphore(value: 0)
        let classifier = try PinnedGestureClassifier()
        var firstClockRead = true
        let driver = GestureSession(clock: {
            if firstClockRead {
                firstClockRead = false
                entered.fulfill()
                _ = release.wait(timeout: .now() + 2)
            }
            return 1
        }, output: { _ in noOutput.fulfill() }, invalid: { _, reason in
            XCTAssertTrue(reason.contains("overflow")); rejected.fulfill()
        })
        driver.start(session: 1, classifier: classifier)
        driver.ingest(packet, session: 1, sequence: 1, receivedAt: 1)
        await fulfillment(of: [entered], timeout: 1)
        // One in flight plus `queueLimit` queued: the next ingest overflows.
        for i in 2...(GestureSession.queueLimit + 1) {
            driver.ingest(packet, session: 1, sequence: UInt32(i), receivedAt: 1)
        }
        // Recorded before `invalid` ran, synchronously on this thread.
        XCTAssertEqual(driver.lastFault?.check, "overflow")
        XCTAssertEqual(driver.lastFault?.queued, GestureSession.queueLimit)
        release.signal()
        await fulfillment(of: [rejected, noOutput], timeout: 0.5)
    }

    func testABurstDeliveredWhileTheWorkerIsBusyIsNotAnOverflow() async throws {
        // A main-queue stall delivers its backlog back to back while the
        // worker may be inside a prediction: ten queued is ordinary.
        let entered = expectation(description: "worker reached clock")
        let allOutputs = expectation(description: "every sample processed")
        allOutputs.expectedFulfillmentCount = 11
        let release = DispatchSemaphore(value: 0)
        var firstClockRead = true
        let driver = GestureSession(clock: {
            if firstClockRead {
                firstClockRead = false
                entered.fulfill()
                _ = release.wait(timeout: .now() + 2)
            }
            return 1
        }, output: { _ in allOutputs.fulfill() }, invalid: { _, reason in XCTFail(reason) })
        driver.start(session: 1, classifier: try PinnedGestureClassifier())
        driver.ingest(packet, session: 1, sequence: 1, receivedAt: 0.98)
        await fulfillment(of: [entered], timeout: 1)
        for i in 2...11 {
            driver.ingest(packet, session: 1, sequence: UInt32(i), receivedAt: 0.98 + Double(i) * 0.001)
        }
        release.signal()
        await fulfillment(of: [allOutputs], timeout: 1)
        XCTAssertNil(driver.lastFault)
    }

    func testReplayClockGapAndChecksumFailClosedButStationarySamplesRemainValid() async throws {
        let classifier = try PinnedGestureClassifier()
        var damaged = packet; damaged[15] ^= 1
        let steady = { (from: Double, count: Int, sequence: UInt32) in
            (0..<count).map { (from + Double($0) * 0.04, sequence + UInt32($0), self.packet) }
        }
        // (name, samples, rejected, tolerated stall episodes)
        let scenarios: [(String, [(Double, UInt32, Data)], Bool, Int)] = [
            ("duplicate", [(1, 1, packet), (1.04, 1, packet)], true, 0),
            ("backwards sequence", [(1, 2, packet), (1.04, 1, packet)], true, 0),
            ("half-range ambiguity", [(1, 1, packet), (1.04, 0x80000001, packet)], true, 0),
            // A gap at or over the stall ceiling always ends the session.
            ("gap beyond ceiling", [(1, 1, packet), (1.55, 2, packet)], true, 0),
            // One gap under the ceiling is dropped with a 3-spacing quarantine,
            // measured from the dropped sample, then processing resumes.
            ("single transient gap", [(1, 1, packet)] + steady(1.28, 5, 2), false, 1),
            // A second episode within 10 s of receipt time ends it.
            ("second gap within 10 s", [(1, 1, packet)] + steady(1.28, 4, 2) + [(1.68, 6, packet)], true, 1),
            ("backwards clock", [(1, 1, packet), (0.96, 2, packet)], true, 0),
            ("checksum", [(1, 1, packet), (1.04, 2, damaged)], true, 0),
            // Identical RT12 values during a still pose remain valid when
            // receipt time and the app-assigned sequence keep advancing.
            ("stationary", steady(1, 14, 1), false, 0),
            ("valid sequence wrap", [(1, UInt32.max, packet), (1.04, 0, packet)], false, 0),
        ]
        for (name, samples, shouldReject, episodes) in scenarios {
            let done = expectation(description: name)
            // Index is confined to the worker after the initial enqueue. Each
            // output or dropped sample schedules the next one, so the test
            // cannot overflow it.
            var index = 0
            var stalls: [GestureSession.Stall] = []
            weak var weakDriver: GestureSession?
            func advance() {
                index += 1
                let next = samples[index]
                weakDriver?.ingest(next.2, session: 1, sequence: next.1, receivedAt: next.0)
            }
            let driver = GestureSession(clock: { samples[index].0 }, output: { _ in
                if index == samples.count - 1 {
                    XCTAssertFalse(shouldReject, name)
                    XCTAssertEqual(stalls.count, episodes, name)
                    done.fulfill(); return
                }
                advance()
            }, invalid: { _, _ in
                XCTAssertTrue(shouldReject, name)
                XCTAssertEqual(index, samples.count - 1, "premature rejection: \(name)")
                XCTAssertEqual(stalls.count, episodes, name)
                done.fulfill()
            }, onStall: { _, stall in stalls.append(stall) }, onDrop: { _, _ in
                guard index < samples.count - 1 else { return XCTFail("last sample dropped: \(name)") }
                advance()
            })
            weakDriver = driver
            driver.start(session: 1, classifier: classifier)
            driver.ingest(samples[0].2, session: 1, sequence: samples[0].1, receivedAt: samples[0].0)
            await fulfillment(of: [done], timeout: 2)
            if name == "single transient gap" {
                XCTAssertEqual(stalls.first?.check, "gap")
                XCTAssertEqual(try XCTUnwrap(stalls.first?.value), 0.28, accuracy: 1e-9)
                XCTAssertEqual(stalls.first?.dropped, 3, "violating sample plus two quarantined")
                XCTAssertEqual(try XCTUnwrap(stalls.first?.releasedAt), 1.40, accuracy: 1e-9)
            }
            if name == "second gap within 10 s" {
                XCTAssertEqual(driver.lastFault?.check, "gap")
                XCTAssertEqual(driver.lastFault?.tolerance, "repeat")
            }
            if name == "gap beyond ceiling" {
                XCTAssertEqual(driver.lastFault?.tolerance, "ceiling")
            }
            driver.stop()
        }
    }

    func testStopInvalidatesAnAlreadyRunningWorker() async throws {
        let entered = expectation(description: "worker running")
        let noOutput = expectation(description: "no output after stop"); noOutput.isInverted = true
        let noFault = expectation(description: "no stale generation error"); noFault.isInverted = true
        let release = DispatchSemaphore(value: 0)
        var first = true
        let driver = GestureSession(clock: {
            if first {
                first = false; entered.fulfill()
                _ = release.wait(timeout: .now() + 2)
            }
            return 1
        }, output: { _ in noOutput.fulfill() }, invalid: { _, _ in noFault.fulfill() })
        driver.start(session: 1, classifier: try PinnedGestureClassifier())
        driver.ingest(packet, session: 1, sequence: 1, receivedAt: 1)
        await fulfillment(of: [entered], timeout: 1)
        driver.stop(); release.signal()
        await fulfillment(of: [noOutput, noFault], timeout: 0.5)
    }
    // MARK: A calibration frame kept across a heal

    func testAKeptFrameIsReadyOnTheFirstSampleAndOnlyKnownFramesAreAccepted() throws {
        var kept = try XCTUnwrap(GestureCalibration(frame: "flip_axis0"))
        let pose = kept.feed(time: 1, counts: [100, -200, 300])
        XCTAssertEqual(pose.frame, "flip_axis0")
        XCTAssertEqual(pose.reason, "Ready")
        XCTAssertNotNil(GestureCalibration(frame: "identity"))
        XCTAssertNil(GestureCalibration(frame: "sideways"))
        var fresh = GestureCalibration()
        XCTAssertNil(fresh.feed(time: 1, counts: [0, 8_000, 0]).frame, "a fresh calibration asks for the pose")
    }

    func testAHealedSegmentStartsWithTheKeptFrameAndAFreshOneAsksAgain() async throws {
        for preset in ["identity", nil] as [String?] {
            let first = expectation(description: "first output")
            var pose: GesturePose?
            let driver = GestureSession(clock: { 1 }, output: { output in
                if pose == nil { pose = output.pose; first.fulfill() }
            }, invalid: { _, reason in XCTFail(reason) })
            driver.start(session: 4, classifier: try PinnedGestureClassifier(), presetFrame: preset)
            driver.ingest(packet, session: 4, sequence: 1, receivedAt: 1)
            await fulfillment(of: [first], timeout: 1)
            XCTAssertEqual(pose?.frame, preset, String(describing: preset))
            XCTAssertEqual(pose?.reason, preset == nil ? "Hold fingers down" : "Ready")
            driver.stop()
        }
    }
}
