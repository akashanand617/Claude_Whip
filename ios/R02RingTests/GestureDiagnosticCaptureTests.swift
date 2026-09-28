import XCTest
@testable import R02Ring

@MainActor
final class GestureDiagnosticCaptureTests: XCTestCase {
    func testPlanCoversEveryGestureThreeTimesWithoutAdjacentRepeats() {
        let prompts = GestureDiagnosticPlan.prompts()
        XCTAssertEqual(prompts.count, GestureID.allCases.count * 3)
        for gesture in GestureID.allCases {
            XCTAssertEqual(prompts.filter { $0.gesture == gesture }.count, 3)
        }
        XCTAssertFalse(zip(prompts, prompts.dropFirst()).contains { $0.gesture == $1.gesture })
        let down = prompts.first { $0.gesture == .double_flick_down }
        XCTAssertEqual(down?.label, "double_flick")
        XCTAssertEqual(down?.direction, "down")
    }

    func testRecorderWritesCompatibleHeaderPacketsMarksAndFrame() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let recorder = try GestureDiagnosticRecorder(
            name: "COLMI R02_DE07", hardware: "RT12COL_V1.0", firmware: "RT12COL_1.00.01_260927",
            deviceID: "device-de07",
            signalCalibration: .init(offsetMG: [1, 2, 3], gain: [1.01, 0.99, 1]),
            root: root, startedUptime: 100, startedWall: 200
        )
        recorder.append(packet: Data([0xa1, 0x03, 0, 1, 0, 2, 0, 3, 0, 0, 0, 0, 0, 0, 0, 0xaa]), receivedAt: 100.04)
        let prompt = GestureDiagnosticPlan.prompts(repetitions: 1).first { $0.gesture == .flick_up }!
        recorder.mark(prompt, at: 101)
        recorder.setFrame("identity")
        XCTAssertEqual(try recorder.finish(cancelled: false), recorder.sessionID)

        let lines = try String(contentsOf: recorder.captureURL, encoding: .utf8)
            .split(separator: "\n").map(String.init)
        XCTAssertEqual(lines.count, 2)
        let header = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(lines[0].utf8)) as? [String: Any])
        let device = try XCTUnwrap(header["device"] as? [String: Any])
        XCTAssertEqual(device["hardware"] as? String, "RT12COL_V1.0")
        XCTAssertEqual(device["device_id"] as? String, "device-de07")
        let signalCalibration = try XCTUnwrap(device["signal_calibration"] as? [String: Any])
        XCTAssertEqual(signalCalibration["offset_mg"] as? [Double], [1, 2, 3])
        XCTAssertEqual(signalCalibration["gain"] as? [Double], [1.01, 0.99, 1])
        let packet = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(lines[1].utf8)) as? [String: Any])
        XCTAssertEqual(packet["p"] as? String, "a10300010002000300000000000000aa")
        XCTAssertEqual(try XCTUnwrap(packet["t"] as? Double), 0.04, accuracy: 0.000001)

        let notes = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: recorder.notesURL)) as? [String: Any])
        let mark = try XCTUnwrap((notes["marks"] as? [[String: Any]])?.first)
        XCTAssertEqual(mark["label"] as? String, "flick")
        XCTAssertEqual(mark["direction"] as? String, "up")
        let frame = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: recorder.frameURL)) as? [String: Any])
        XCTAssertEqual(frame["rotation"] as? String, "identity")
    }
}
