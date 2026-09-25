import Foundation

struct GesturePose {
    let frame: String?
    let reason: String
    let held: Double
}

struct GestureCalibration {
    private var samples: [[Double]] = []
    private var goodSince: Double?
    private(set) var frame: String?

    mutating func feed(time: Double, counts: [Double]) -> GesturePose {
        if let frame { return GesturePose(frame: frame, reason: "Ready", held: 3) }
        samples.append(counts)
        if samples.count > 50 { samples.removeFirst() }
        guard samples.count == 50 else { return GesturePose(frame: nil, reason: "Hold fingers down", held: Double(samples.count) / 25) }
        let g = (0..<3).map { axis in samples.reduce(0.0) { $0 + $1[axis] } / 50 }
        let norm = g.reduce(0.0) { $0 + $1*$1 }.squareRoot()
        guard norm >= 0.000001 else { goodSince = nil; return GesturePose(frame: nil, reason: "No gravity reference", held: 0) }
        let motion = samples.map { row in (0..<3).reduce(0.0) { $0 + pow(row[$1] - g[$1], 2) }.squareRoot() / norm }.max()!
        guard motion <= 0.25, abs(g[1] / norm) >= 0.9 else {
            goodSince = nil
            return GesturePose(frame: nil, reason: motion > 0.25 ? "Hold still" : "Point fingers down", held: 0)
        }
        if goodSince == nil { goodSince = time }
        let held = min(3, 2 + time - goodSince!)
        if held + 1e-9 >= 3 { frame = g[1] > 0 ? "identity" : "flip_axis0" }
        return GesturePose(frame: frame, reason: frame == nil ? "Keep holding" : "Ready", held: held)
    }
}

/// Bounded, off-main inference. All callbacks must be generation-checked by the
/// consumer too. No action router exists: detections are informational only.
final class GestureSession {
    struct Output {
        let generation: UUID
        let session: UInt32
        let sequence: UInt32
        let receivedAt: Double
        let pose: GesturePose
        let events: [RingGestureEvent]
    }
    private let queue = DispatchQueue(label: "whip.gesture.inference", qos: .userInitiated)
    private let lock = NSLock()
    private var queued = 0
    private var generation = UUID()
    private var activeSession: UInt32?
    private var engine: GestureInference?
    private var calibration = GestureCalibration()
    private var lastTime: Double?
    private var lastSequence: UInt32?
    private var lastCounts: [Double]?
    private var lastChanged = 0.0
    private let clock: () -> Double
    private let output: (Output) -> Void
    private let invalid: (UUID, String) -> Void

    init(clock: @escaping () -> Double = { ProcessInfo.processInfo.systemUptime },
         output: @escaping (Output) -> Void, invalid: @escaping (UUID, String) -> Void) {
        self.clock = clock; self.output = output; self.invalid = invalid
    }

    @discardableResult
    func start(session: UInt32, classifier: PinnedGestureClassifier) -> UUID {
        lock.lock()
        let token = UUID()
        generation = token; activeSession = session
        // Enqueue reset while holding the same lock used by ingest, so the first
        // sample cannot overtake initialization on the serial worker.
        queue.async {
            self.engine = GestureInference(predict: classifier.probabilities)
            self.calibration = GestureCalibration()
            self.lastTime = nil; self.lastSequence = nil; self.lastCounts = nil
        }
        lock.unlock()
        return token
    }

    func stop() {
        lock.lock(); generation = UUID(); activeSession = nil; lock.unlock()
        // Invalidates callbacks immediately; old jobs check generation on drain.
    }

    func ingest(_ packet: Data, session: UInt32, sequence: UInt32, receivedAt: Double) {
        lock.lock()
        let token = generation
        guard activeSession == session else { lock.unlock(); return }
        guard queued < 8 else {
            activeSession = nil; generation = UUID(); lock.unlock()
            invalid(token, "Inference queue overflow; Gesture session stopped")
            return
        }
        queued += 1
        queue.async {
            defer { self.lock.lock(); self.queued -= 1; self.lock.unlock() }
            self.lock.lock(); let current = self.generation == token && self.activeSession == session; self.lock.unlock()
            guard current else { return }
            do {
                let age = self.clock() - receivedAt
                guard age >= 0, age <= 0.25, receivedAt.isFinite else { throw UnifiedModeError.staleStream }
                let counts = try GestureContract.decode(packet)
                if let previous = self.lastTime {
                    guard receivedAt > previous, receivedAt - previous <= 0.25 else { throw UnifiedModeError.staleStream }
                }
                if let previous = self.lastSequence {
                    let advance = sequence &- previous
                    guard advance > 0, advance < 0x80000000 else { throw UnifiedModeError.staleStream }
                }
                if self.lastCounts != counts { self.lastChanged = receivedAt }
                guard receivedAt - self.lastChanged <= 0.5 else { throw UnifiedModeError.staleStream }
                self.lastCounts = counts; self.lastTime = receivedAt; self.lastSequence = sequence
                let pose = self.calibration.feed(time: receivedAt, counts: counts)
                var events: [RingGestureEvent] = []
                if let frame = pose.frame {
                    let corrected = frame == "identity" ? counts : [counts[0], -counts[1], -counts[2]]
                    events = try self.engine?.feed(time: receivedAt, counts: corrected) ?? []
                }
                guard self.clock() - receivedAt <= 0.5 else { throw UnifiedModeError.staleStream }
                self.lock.lock(); let stillCurrent = self.generation == token && self.activeSession == session; self.lock.unlock()
                guard stillCurrent else { return }
                self.output(Output(generation: token, session: session, sequence: sequence,
                                   receivedAt: receivedAt, pose: pose, events: events))
            } catch {
                self.lock.lock()
                let current = self.generation == token
                if current { self.activeSession = nil; self.generation = UUID() }
                self.lock.unlock()
                if current { self.invalid(token, error.localizedDescription) }
            }
        }
        lock.unlock()
    }
}
