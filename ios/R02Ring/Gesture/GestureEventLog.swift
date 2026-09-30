import Foundation

@MainActor
protocol GestureEventLogging: AnyObject {
    /// `action` is nil when the router resolved no action; it is written as JSON null.
    func record(_ event: RingGestureEvent, action: GestureActionID?, wall: Double)
    /// Flushes and releases the file; later records are dropped.
    func close()
}

/// One research-log line: `whip.realtime.GestureEvent.as_dict()` plus
/// `action` and `wall`. Every key is always written; nil is JSON null.
struct GestureEventLine: Equatable {
    let name: String
    let direction: String
    let tS: Double?
    let confidence: Double?
    let runLength: Int
    let latencyS: Double?
    let endS: Double?
    let action: String?
    let wall: Double?

    enum Key: String, CaseIterable {
        case name, direction, tS = "t_s", confidence, runLength = "run_length"
        case latencyS = "latency_s", endS = "end_s", action, wall
    }

    /// Compact, sorted keys, no trailing newline. Numbers are Swift's shortest
    /// round-trip `description`, which is exactly Python's `json.dumps` text
    /// for finite doubles (0.912, 31.0, -0.0, 1e-05), so `json.loads` yields
    /// the float/int types `EventLog` writes. `JSONEncoder` would write 31.0
    /// as the integer 31; `JSONSerialization` writes 0.912 as 0.91200000000000003.
    func encoded() throws -> Data {
        let values: [Key: String] = [
            .name: try Self.json(name), .direction: try Self.json(direction),
            .tS: Self.json(tS), .confidence: Self.json(confidence), .runLength: String(runLength),
            .latencyS: Self.json(latencyS), .endS: Self.json(endS),
            .action: try action.map(Self.json) ?? "null", .wall: Self.json(wall),
        ]
        let body = Key.allCases.sorted { $0.rawValue < $1.rawValue }
            .map { "\"\($0.rawValue)\":\(values[$0] ?? "null")" }
            .joined(separator: ",")
        return Data("{\(body)}".utf8)
    }

    private static func json(_ value: Double?) -> String {
        guard let value, value.isFinite else { return "null" }
        return value.description
    }

    private static func json(_ value: String) throws -> String {
        let data = try JSONSerialization.data(withJSONObject: value,
                                              options: [.fragmentsAllowed, .withoutEscapingSlashes])
        return String(decoding: data, as: UTF8.self)
    }
}

/// Research log with exactly the keys, values and JSON types of
/// `whip.realtime.EventLog.write` (key order and spacing differ), one object
/// per line, so `python -m probe.label join --events …/events_*.jsonl` reads
/// it unchanged. `t_s`/`end_s` are seconds since the stream start, `wall` is
/// epoch seconds at dispatch, and non-finite numbers are null. The file is
/// created on the first event; a session without events leaves none.
@MainActor
final class GestureEventLog: GestureEventLogging {
    nonisolated static let directoryName = "GestureEvents"
    nonisolated static let filePrefix = "events_"
    nonisolated static let keys = Set(GestureEventLine.Key.allCases.map(\.rawValue))

    let url: URL
    let streamStart: Double
    private let file: GestureJSONLinesFile

    init(streamStart: Double, root: URL? = nil, startedWall: Double = Date().timeIntervalSince1970) {
        self.streamStart = streamStart
        let base = root ?? Self.defaultRoot
        url = base.appendingPathComponent(
            "\(Self.filePrefix)\(GestureLogFormat.stamp(startedWall, format: "yyyyMMdd_HHmmss")).jsonl"
        )
        file = GestureJSONLinesFile(url: url, label: "whip.gesture.event-log")
    }

    nonisolated static var defaultRoot: URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent(directoryName, isDirectory: true)
    }

    /// Python rounds with `round(x, 3)`: correctly rounded from the exact
    /// binary value. `%.3f` is correctly rounded too; `(x * 1000).rounded()`
    /// is not (1.0005 would become 1.001 instead of 1.0). Non-finite is nil.
    nonisolated static func rounded(_ value: Double) -> Double? {
        guard value.isFinite else { return nil }
        return Double(String(format: "%.3f", value))
    }

    nonisolated static func line(for event: RingGestureEvent, action: GestureActionID?,
                                 wall: Double, streamStart: Double) -> GestureEventLine {
        GestureEventLine(
            name: event.name,
            direction: event.direction,
            tS: rounded(event.time - streamStart),
            confidence: rounded(event.confidence),
            runLength: event.votes,
            latencyS: event.latency.flatMap { rounded($0) },
            endS: event.end.flatMap { rounded($0 - streamStart) },
            action: action?.rawValue,
            wall: wall.isFinite ? wall : nil
        )
    }

    func record(_ event: RingGestureEvent, action: GestureActionID?, wall: Double) {
        guard let data = try? Self.line(for: event, action: action, wall: wall, streamStart: streamStart).encoded()
        else { return }
        file.append(line: data)
    }

    /// Blocks until queued lines are on disk.
    func flush() { file.flush() }

    func close() { file.close() }

    /// Only files the Python join would glob; the lifecycle journal is excluded.
    nonisolated static func files(in root: URL = defaultRoot) -> [URL] {
        let names = (try? FileManager.default.contentsOfDirectory(atPath: root.path)) ?? []
        return names.filter { $0.hasPrefix(filePrefix) && $0.hasSuffix(".jsonl") }
            .sorted().map { root.appendingPathComponent($0) }
    }
}

/// Lifecycle evidence for background behavior: session starts/ends, readiness,
/// renewals and scene changes. Named `lifecycle_yyyyMMdd.jsonl` in the same
/// folder so a shared folder carries it, but it never matches `events_*`.
@MainActor
final class GestureSessionJournal {
    nonisolated static let filePrefix = "lifecycle_"

    private let root: URL
    private var file: GestureJSONLinesFile?

    init(root: URL? = nil) {
        self.root = root ?? GestureEventLog.defaultRoot
    }

    func url(forWall wall: Double) -> URL {
        root.appendingPathComponent(
            "\(Self.filePrefix)\(GestureLogFormat.stamp(wall, format: "yyyyMMdd")).jsonl"
        )
    }

    /// `kind`, `wall` and `uptime` always win over same-named `fields`.
    /// Non-finite numbers become null so a line is never invalid JSON.
    func record(_ kind: String, fields: [String: Any] = [:],
                wall: Double = Date().timeIntervalSince1970,
                uptime: Double = ProcessInfo.processInfo.systemUptime) {
        var line = fields.mapValues(GestureLogFormat.sanitized)
        line["kind"] = kind
        line["wall"] = wall.isFinite ? wall : NSNull()
        line["uptime"] = GestureLogFormat.json(GestureEventLog.rounded(uptime))
        let target = url(forWall: wall.isFinite ? wall : Date().timeIntervalSince1970)
        if file?.url != target {
            file?.close()
            file = GestureJSONLinesFile(url: target, label: "whip.gesture.journal")
        }
        file?.append(jsonObject: line)
    }

    func flush() { file?.flush() }

    func close() { file?.close(); file = nil }

    nonisolated static func files(in root: URL = GestureEventLog.defaultRoot) -> [URL] {
        let names = (try? FileManager.default.contentsOfDirectory(atPath: root.path)) ?? []
        return names.filter { $0.hasPrefix(filePrefix) && $0.hasSuffix(".jsonl") }
            .sorted().map { root.appendingPathComponent($0) }
    }
}

/// Receipt-to-main-actor stream health for the journal. `gap` is the largest
/// interval between consecutive processed BLE receipts (a tolerated stall
/// shows here in full; a fatal one ends the session first and is in its
/// `stale_detail`); `hop` is the largest delay from receipt to processing.
/// Spacing counts above 120 ms and below 10 ms show the connection-event
/// lattice. The window closes every `summaryInterval` seconds while gap
/// continuity spans windows.
struct GestureStreamStats: Equatable {
    static let summaryInterval: Double = 5

    struct Summary: Equatable {
        private(set) var samples = 0
        private(set) var first: Double?
        private(set) var last: Double?
        private(set) var maxGap = 0.0
        private(set) var maxHop = 0.0
        private(set) var gapsOver120ms = 0
        private(set) var gapsUnder10ms = 0
        private(set) var maxPredict: Double?
        private(set) var maxQueue: Int?
        private(set) var maxSameRun: Int?

        var duration: Double {
            guard let first, let last else { return 0 }
            return last - first
        }

        var rateHz: Double? {
            guard samples > 1, duration > 0 else { return nil }
            return Double(samples - 1) / duration
        }

        fileprivate mutating func add(receivedAt: Double, gap: Double?, hop: Double,
                                      predict: Double?, queued: Int?, sameRun: Int?) {
            samples += 1
            if first == nil { first = receivedAt }
            last = receivedAt
            if let gap {
                maxGap = max(maxGap, gap)
                if gap > 0.120 { gapsOver120ms += 1 }
                if gap < 0.010 { gapsUnder10ms += 1 }
            }
            maxHop = max(maxHop, hop)
            if let predict, predict.isFinite { maxPredict = max(maxPredict ?? 0, predict) }
            if let queued { maxQueue = max(maxQueue ?? 0, queued) }
            if let sameRun { maxSameRun = max(maxSameRun ?? 0, sameRun) }
        }

        var fields: [String: Any] {
            [
                "samples": samples,
                "duration_s": GestureLogFormat.json(GestureEventLog.rounded(duration)),
                "rate_hz": GestureLogFormat.json(rateHz.flatMap { GestureEventLog.rounded($0) }),
                "max_gap_s": GestureLogFormat.json(GestureEventLog.rounded(maxGap)),
                "max_hop_s": GestureLogFormat.json(GestureEventLog.rounded(maxHop)),
                "gaps_over_120ms": gapsOver120ms,
                "gaps_under_10ms": gapsUnder10ms,
                "max_predict_ms": GestureLogFormat.json(maxPredict.map { ($0 * 10_000).rounded() / 10 }),
                "max_queue": maxQueue.map { $0 as Any } ?? NSNull(),
                "max_same_run": maxSameRun.map { $0 as Any } ?? NSNull(),
            ]
        }
    }

    private(set) var total = Summary()
    private(set) var window = Summary()
    private var lastReceivedAt: Double?

    /// Out-of-order or non-finite receipts are ignored rather than producing
    /// a negative gap; a negative hop counts as zero. `predictSeconds`,
    /// `queued` and `sameRun` come from `GestureSession.Output`.
    mutating func record(receivedAt: Double, processedAt: Double, predictSeconds: Double? = nil,
                         queued: Int? = nil, sameRun: Int? = nil) {
        guard receivedAt.isFinite, processedAt.isFinite else { return }
        if let lastReceivedAt, receivedAt < lastReceivedAt { return }
        let gap = lastReceivedAt.map { receivedAt - $0 }
        let hop = max(0, processedAt - receivedAt)
        lastReceivedAt = receivedAt
        total.add(receivedAt: receivedAt, gap: gap, hop: hop,
                  predict: predictSeconds, queued: queued, sameRun: sameRun)
        window.add(receivedAt: receivedAt, gap: gap, hop: hop,
                   predict: predictSeconds, queued: queued, sameRun: sameRun)
    }

    /// True once the open window spans `summaryInterval` of receipts.
    var windowDue: Bool { window.duration >= Self.summaryInterval }

    mutating func closeWindow() -> Summary {
        defer { window = Summary() }
        return window
    }

    mutating func reset() { self = GestureStreamStats() }
}

/// Measures main-queue delay while a Gesture session runs. CoreBluetooth
/// delivers notifications on the main queue, so a main-queue stall is a BLE
/// receipt gap. Every `interval` a utility-queue timer posts one block to the
/// main queue (never more than one outstanding) and `report` receives, on the
/// main queue, any delay above `threshold`.
final class MainQueueWatchdog: @unchecked Sendable {
    private let queue = DispatchQueue(label: "whip.main-watchdog", qos: .utility)
    private let interval: DispatchTimeInterval
    private let threshold: Double
    private let report: (Double) -> Void
    private var timer: DispatchSourceTimer? // queue only
    private var outstanding = false         // queue only

    init(interval: DispatchTimeInterval = .milliseconds(50), threshold: Double = 0.1,
         report: @escaping (Double) -> Void) {
        self.interval = interval
        self.threshold = threshold
        self.report = report
    }

    func start() {
        queue.async { [self] in
            guard timer == nil else { return }
            let source = DispatchSource.makeTimerSource(queue: queue)
            source.schedule(deadline: .now() + interval, repeating: interval, leeway: .milliseconds(10))
            source.setEventHandler { [weak self] in self?.tick() }
            timer = source
            source.resume()
        }
    }

    func stop() {
        queue.async { [self] in
            timer?.cancel()
            timer = nil
            outstanding = false
        }
    }

    private func tick() {
        guard timer != nil, !outstanding else { return }
        outstanding = true
        let sent = ProcessInfo.processInfo.systemUptime
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            let delay = ProcessInfo.processInfo.systemUptime - sent
            self.queue.async { self.outstanding = false }
            if delay > self.threshold { self.report(delay) }
        }
    }
}

enum GestureLogFormat {
    static func stamp(_ wall: Double, format: String) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.dateFormat = format
        return formatter.string(from: Date(timeIntervalSince1970: wall.isFinite ? wall : 0))
    }

    static func json(_ value: Double?) -> Any { value ?? NSNull() }

    static func sanitized(_ value: Any) -> Any {
        switch value {
        case let number as Double: return number.isFinite ? number : NSNull()
        case let number as Float: return number.isFinite ? Double(number) : NSNull()
        case let dictionary as [String: Any]: return dictionary.mapValues(sanitized)
        case let array as [Any]: return array.map(sanitized)
        default: return value
        }
    }
}

/// Serial, lazily opened JSONL appender. Lines are encoded on the caller so
/// only `Data` crosses to the io queue; a failed write drops that line and
/// never throws into BLE receipt or inference. JSONSerialization raises an
/// uncatchable exception for NaN/inf, so invalid objects are dropped first.
final class GestureJSONLinesFile: @unchecked Sendable {
    let url: URL
    private let io: DispatchQueue
    private var handle: FileHandle? // io queue only
    private var closed = false      // io queue only

    init(url: URL, label: String) {
        self.url = url
        io = DispatchQueue(label: label, qos: .utility)
    }

    func append(jsonObject record: [String: Any]) {
        guard JSONSerialization.isValidJSONObject(record),
              let data = try? JSONSerialization.data(withJSONObject: record, options: [.sortedKeys]) else { return }
        append(line: data)
    }

    /// `line` is one complete JSON value without its newline.
    func append(line: Data) {
        var data = line
        data.append(0x0a)
        io.async { [self] in
            guard !closed, let handle = openIfNeeded() else { return }
            try? handle.write(contentsOf: data)
        }
    }

    func flush() {
        io.sync { [self] in try? handle?.synchronize() }
    }

    func close() {
        io.sync { [self] in
            closed = true
            try? handle?.synchronize()
            try? handle?.close()
            handle = nil
        }
    }

    private func openIfNeeded() -> FileHandle? {
        if let handle { return handle }
        let manager = FileManager.default
        do {
            try manager.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            if !manager.fileExists(atPath: url.path) {
                guard manager.createFile(atPath: url.path, contents: nil) else { return nil }
            }
            let opened = try FileHandle(forWritingTo: url)
            try opened.seekToEnd()
            handle = opened
            return opened
        } catch {
            return nil
        }
    }
}
