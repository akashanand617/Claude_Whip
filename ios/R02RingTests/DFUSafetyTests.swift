import CryptoKit
import XCTest
@testable import R02Ring

/// Pure byte construction only. No BLE transfer or firmware installation.
final class DFUSafetyTests: XCTestCase {
    func testEveryFrameOfEveryBundledImageMatchesPython() throws {
        // SHA-256 over START + INIT + all 135 DATA frames + CHECK + END,
        // independently generated with whip.dfu from the pinned input images.
        let cases: [(BundledFirmware, String)] = [
            (.health, "a4de7893489d03b98a42914d93e5af1c3ff03c68eca6b0f8c1817855a84d4fbe"),
            (.gesture, "ededabc9b9341f9ef80837454ad8b9a5afb3950c4965df59314823451f85054c"),
            (.unified, "9f25a9bb00938b64e5341c08860a09c284db37b7f66c602b92c08871fc9ac81c"),
        ]
        for (image, expected) in cases {
            let firmware = try image.load()
            let chunks = (firmware.count + R02DFU.chunkSize - 1) / R02DFU.chunkSize
            XCTAssertEqual(chunks, 135)
            var stream = R02DFU.frame(command: 1)
            stream.append(try R02DFU.initFrame(firmware: firmware, type: image.initType))
            var rebuilt = Data()
            for index in 0..<chunks {
                let frame = try R02DFU.dataFrame(firmware: firmware, index: index)
                XCTAssertEqual(Int(frame[6]) | Int(frame[7]) << 8, index + 1)
                rebuilt.append(frame.dropFirst(8))
                stream.append(frame)
            }
            stream.append(R02DFU.frame(command: 4)); stream.append(R02DFU.frame(command: 5))
            XCTAssertEqual(rebuilt, firmware)
            let digest = SHA256.hash(data: stream).map { String(format: "%02x", $0) }.joined()
            XCTAssertEqual(digest, expected, image.resource)
        }
    }

    func testAllErrorStatusesTruncationsAndSingleBitCorruptionsAreRejected() throws {
        for command: UInt8 in 1...5 {
            let ok = R02DFU.frame(command: command, payload: Data([0]))
            XCTAssertNoThrow(try R02DFU.validateResponse(ok, command: command))
            for status: UInt8 in 1...255 {
                XCTAssertThrowsError(try R02DFU.validateResponse(
                    R02DFU.frame(command: command, payload: Data([status])), command: command))
            }
            for length in 0..<ok.count {
                XCTAssertThrowsError(try R02DFU.validateResponse(ok.prefix(length), command: command))
            }
            for index in ok.indices {
                for bit in 0..<8 {
                    var corrupt = ok; corrupt[index] ^= 1 << bit
                    XCTAssertThrowsError(try R02DFU.validateResponse(corrupt, command: command))
                }
            }
            XCTAssertThrowsError(try R02DFU.validateResponse(ok + ok, command: command))
        }
    }
}
