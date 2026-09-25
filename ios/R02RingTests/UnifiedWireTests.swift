import XCTest
@testable import R02Ring

final class UnifiedWireTests: XCTestCase {
    let boot: UInt64 = 0xfedcba9876543210

    func body(op: UInt8 = 3, result: UInt8 = 0, mode: UInt8 = 2) -> [UInt8] {
        var b = [UInt8](repeating: 0, count: 20)
        b[0] = op; b[1] = result; b[2] = mode
        UnifiedWire.put(UInt32(truncatingIfNeeded: boot), into: &b, at: 4)
        UnifiedWire.put(UInt32(boot >> 32), into: &b, at: 8)
        UnifiedWire.put(123, into: &b, at: 12)
        return b
    }
    func testFullReplyRoundtripIntoExistingModeContract() throws {
        let expected = body(), frames = try UnifiedWire.control(kind: .reply, requestID: 99, body: expected)
        var rx = try UnifiedWire.Receiver(kind: .reply, operation: .gesture, requestID: 99,
                                          connection: 7, bootID: boot, now: 100)
        XCTAssertNil(try rx.feed(frames[0], connection: 7, now: 101))
        let decoded = try XCTUnwrap(rx.feed(frames[1], connection: 7, now: 102))
        let reply = try UnifiedWire.modeReply(decoded, requestID: 99, operation: .gesture, bootID: boot)
        XCTAssertEqual(reply.requestID, 99)
        XCTAssertEqual(reply.status, .init(bootID: boot, session: 123, mode: .gesture, charging: false))
        XCTAssertThrowsError(try rx.feed(frames[1], connection: 7, now: 103))
    }
    func testNegativeOrUncommittedReplyNeverBecomesModeStatus() {
        for result: UInt8 in 1...4 {
            XCTAssertThrowsError(try UnifiedWire.modeReply(body(result: result), requestID: 99,
                                                          operation: .gesture, bootID: boot))
        }
        for mode: UInt8 in [0, 1, 3, 4] {
            XCTAssertThrowsError(try UnifiedWire.modeReply(body(mode: mode), requestID: 99,
                                                          operation: .gesture, bootID: boot))
        }
        XCTAssertThrowsError(try UnifiedWire.modeReply(body(), requestID: 99, operation: .health, bootID: boot))
        XCTAssertThrowsError(try UnifiedWire.modeReply(body(), requestID: 99, operation: .gesture, bootID: boot ^ 1))
        XCTAssertThrowsError(try UnifiedWire.modeReply(body(), requestID: 0, operation: .gesture, bootID: boot))
    }
    func testWrongConnectionOrOrderPoisonsReceiver() throws {
        let frames = try UnifiedWire.control(kind: .reply, requestID: 99, body: body())
        for wrongConnection in [false, true] {
            var rx = try UnifiedWire.Receiver(kind: .reply, operation: .gesture, requestID: 99,
                                              connection: 7, bootID: boot, now: 100)
            XCTAssertThrowsError(try rx.feed(frames[wrongConnection ? 0 : 1],
                                             connection: wrongConnection ? 8 : 7, now: 101))
            XCTAssertThrowsError(try rx.feed(frames[0], connection: 7, now: 102))
        }
    }
    func testRequestShapeAndCRC() throws {
        XCTAssertEqual(UnifiedWire.crc(Array("123456789".utf8)), 0x29b1)
        XCTAssertThrowsError(try UnifiedWire.request(.renew, requestID: 99, bootID: boot))
        XCTAssertThrowsError(try UnifiedWire.request(.health, requestID: 99, bootID: boot, session: 1))
        let f = try UnifiedWire.request(.renew, requestID: 99, bootID: boot, session: 123, processedSequence: 456)
        XCTAssertEqual(f.map(\.count), [20, 20])
        var rx = try UnifiedWire.Receiver(kind: .request, operation: .renew, requestID: 99,
                                          connection: 7, bootID: boot, now: 0xfffffff0)
        XCTAssertNil(try rx.feed(f[0], connection: 7, now: 0x10))
        XCTAssertNotNil(try rx.feed(f[1], connection: 7, now: 0x20))
    }
    func testMotionPreservesSignedCountsAndRequiresSession() throws {
        let sample = UnifiedWire.Motion(session: 123, sequence: 456, x: -32768, y: 8005, z: 32767)
        var bytes = try UnifiedWire.motion(sample)
        XCTAssertEqual(bytes.count, 20)
        XCTAssertEqual(try UnifiedWire.decodeMotion(bytes, session: 123), sample)
        XCTAssertThrowsError(try UnifiedWire.decodeMotion(bytes, session: 124))
        bytes[12] ^= 1
        XCTAssertThrowsError(try UnifiedWire.decodeMotion(bytes, session: 123))
    }
}
