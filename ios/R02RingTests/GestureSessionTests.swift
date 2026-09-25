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
        for i in 2...9 { driver.ingest(packet, session: 1, sequence: UInt32(i), receivedAt: 1) }
        release.signal()
        await fulfillment(of: [rejected, noOutput], timeout: 0.5)
    }

    func testReplayClockGapChecksumAndFrozenSamplesFailClosed() async throws {
        let classifier = try PinnedGestureClassifier()
        var damaged = packet; damaged[15] ^= 1
        let scenarios: [(String, [(Double, UInt32, Data)], Bool)] = [
            ("duplicate", [(1, 1, packet), (1.04, 1, packet)], true),
            ("backwards sequence", [(1, 2, packet), (1.04, 1, packet)], true),
            ("half-range ambiguity", [(1, 1, packet), (1.04, 0x80000001, packet)], true),
            ("delivery gap", [(1, 1, packet), (1.28, 2, packet)], true),
            ("backwards clock", [(1, 1, packet), (0.96, 2, packet)], true),
            ("checksum", [(1, 1, packet), (1.04, 2, damaged)], true),
            ("frozen", (0..<14).map { (1 + Double($0) * 0.04, UInt32($0 + 1), packet) }, true),
            ("valid sequence wrap", [(1, UInt32.max, packet), (1.04, 0, packet)], false),
        ]
        for (name, samples, shouldReject) in scenarios {
            let done = expectation(description: name)
            // Index is confined to the worker after the initial enqueue. Each
            // output schedules the next sample, so the test cannot overflow it.
            var index = 0
            weak var weakDriver: GestureSession?
            let driver = GestureSession(clock: { samples[index].0 }, output: { _ in
                if index == samples.count - 1 {
                    XCTAssertFalse(shouldReject, name); done.fulfill(); return
                }
                index += 1
                let next = samples[index]
                weakDriver?.ingest(next.2, session: 1, sequence: next.1, receivedAt: next.0)
            }, invalid: { _, _ in
                XCTAssertTrue(shouldReject, name)
                XCTAssertEqual(index, samples.count - 1, "premature rejection: \(name)")
                done.fulfill()
            })
            weakDriver = driver
            driver.start(session: 1, classifier: classifier)
            driver.ingest(samples[0].2, session: 1, sequence: samples[0].1, receivedAt: samples[0].0)
            await fulfillment(of: [done], timeout: 2)
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
}
