import Foundation

struct GestureDiagnosticPrompt: Equatable {
    let gesture: GestureID
    let label: String
    let direction: String
    let repetition: Int

    var spoken: String { gesture.rawValue.replacingOccurrences(of: "_", with: " ") }
}

enum GestureDiagnosticPlan {
    /// Deterministic interleaving keeps adjacent repetitions apart while making
    /// a capture reproducible. Three repetitions are for domain diagnosis, not
    /// enough evidence to approve a retrained production checkpoint.
    static func prompts(repetitions: Int = 3) -> [GestureDiagnosticPrompt] {
        guard repetitions > 0 else { return [] }
        let gestures = GestureID.allCases
        return (0..<repetitions).flatMap { repetition in
            let shift = (repetition * 4) % gestures.count
            return (0..<gestures.count).map { offset in
                make(gestures[(offset + shift) % gestures.count], repetition: repetition + 1)
            }
        }
    }

    private static func make(_ gesture: GestureID, repetition: Int) -> GestureDiagnosticPrompt {
        let parts = gesture.rawValue.split(separator: "_").map(String.init)
        if gesture.rawValue.hasPrefix("double_flick_") {
            return .init(gesture: gesture, label: "double_flick", direction: parts.last!, repetition: repetition)
        }
        if gesture.rawValue.hasPrefix("flick_") {
            return .init(gesture: gesture, label: "flick", direction: parts.last!, repetition: repetition)
        }
        return .init(gesture: gesture, label: gesture.rawValue, direction: "any", repetition: repetition)
    }
}

/// Writes a production-compatible capture and notes sidecar into Documents.
/// File I/O is serialized separately from BLE receipt and inference. Each JSONL
/// record is complete before it is appended, so a killed app can at worst lose
/// the final queued line; the already-written raw evidence stays readable.
@MainActor
final class GestureDiagnosticRecorder {
    let sessionID: String
    let captureURL: URL
    let notesURL: URL
    let frameURL: URL

    private let startedUptime: Double
    private let startedWall: Double
    private let io = DispatchQueue(label: "whip.gesture.diagnostic-file", qos: .utility)
    private let handle: FileHandle
    private var marks: [[String: Any]] = []
    private var frame: String?
    private var closed = false

    init(name: String, hardware: String, firmware: String,
         deviceID: String? = nil,
         signalCalibration: GestureSensorCalibration = .identity,
         root: URL? = nil,
         startedUptime: Double = ProcessInfo.processInfo.systemUptime,
         startedWall: Double = Date().timeIntervalSince1970) throws {
        guard signalCalibration.isValid else { throw RingProtocolError.invalidPacket }
        self.startedUptime = startedUptime
        self.startedWall = startedWall
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyyMMdd_HHmmss"
        sessionID = "phone_domain_\(formatter.string(from: Date(timeIntervalSince1970: startedWall)))"

        let base = root ?? FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("GestureDiagnostics", isDirectory: true)
        try FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        captureURL = base.appendingPathComponent("\(sessionID).jsonl")
        notesURL = base.appendingPathComponent("\(sessionID).notes.json")
        frameURL = base.appendingPathComponent("\(sessionID).frame.json")
        guard FileManager.default.createFile(atPath: captureURL.path, contents: nil) else {
            throw CocoaError(.fileWriteUnknown)
        }
        handle = try FileHandle(forWritingTo: captureURL)

        let iso = ISO8601DateFormatter().string(from: Date(timeIntervalSince1970: startedWall))
        let header: [String: Any] = [
            "kind": "header", "label": sessionID, "session_kind": "phone_domain",
            "started_wall": startedWall, "started_iso": iso, "stream_t0": startedUptime,
            "param": 4, "hand": "unknown", "ring_position": "unknown",
            "device": [
                "name": name, "hardware": hardware, "firmware": firmware,
                "device_id": deviceID ?? "",
                "signal_calibration": [
                    "offset_mg": signalCalibration.offsetMG,
                    "gain": signalCalibration.gain,
                ],
            ]
        ]
        try Self.writeLine(header, to: handle)
        try handle.synchronize()
    }

    func append(packet: Data, receivedAt: Double) {
        guard !closed, receivedAt.isFinite, receivedAt >= startedUptime else { return }
        let relative = receivedAt - startedUptime
        let hex = packet.map { String(format: "%02x", $0) }.joined()
        let record: [String: Any] = ["t": relative, "p": hex]
        io.async { [handle] in try? Self.writeLine(record, to: handle) }
    }

    func mark(_ prompt: GestureDiagnosticPrompt, at uptime: Double) {
        guard !closed, uptime.isFinite, uptime >= startedUptime else { return }
        marks.append([
            "index": marks.count, "label": prompt.label, "direction": prompt.direction,
            "repetition": prompt.repetition, "cue_at": uptime - startedUptime,
            "amplitude": "natural", "windup": "natural", "posture": "as you are", "tempo": "natural"
        ])
    }

    func setFrame(_ value: String?) {
        if let value { frame = value }
    }

    @discardableResult
    func finish(cancelled: Bool) throws -> String {
        guard !closed else { return sessionID }
        closed = true
        try io.sync {
            try handle.synchronize()
            try handle.close()
        }
        let notes: [String: Any] = [
            "session_id": sessionID, "started_wall": startedWall, "kind": "phone_domain",
            "hand": "unknown", "ring_position": "unknown", "note": cancelled ? "cancelled" : "",
            "marks": marks
        ]
        try Self.writeJSON(notes, to: notesURL)
        if let frame {
            try Self.writeJSON([
                "session_id": sessionID, "rotation": frame,
                "evidence": "phone fingers-down calibration"
            ], to: frameURL)
        }
        return sessionID
    }

    /// Pure I/O on its arguments, so the io queue may call it off the main actor.
    private nonisolated static func writeLine(_ value: [String: Any], to handle: FileHandle) throws {
        var data = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
        data.append(0x0a)
        try handle.write(contentsOf: data)
    }

    private static func writeJSON(_ value: [String: Any], to url: URL) throws {
        let data = try JSONSerialization.data(withJSONObject: value, options: [.prettyPrinted, .sortedKeys])
        try data.write(to: url, options: .atomic)
    }
}
