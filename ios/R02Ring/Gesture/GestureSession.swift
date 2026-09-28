import Foundation

struct GesturePose {
    let frame: String?
    let reason: String
    let held: Double
}

/// Converts a hardware family's decoded sensor axes into the RT02 coordinate
/// system used by calibration and the pinned gesture model. A physical RT12
/// down-pose capture puts gravity on source axis 2; the proper rotation into
/// RT02 coordinates is [source0, source2, -source1].
struct GestureAxisMap: Equatable {
    let canonicalSources: [Int]
    let canonicalSigns: [Double]

    static let rt02cr = GestureAxisMap(canonicalSources: [0, 1, 2], canonicalSigns: [1, 1, 1])
    static let rt12col = GestureAxisMap(canonicalSources: [0, 2, 1], canonicalSigns: [1, 1, -1])

    func apply(_ counts: [Double]) throws -> [Double] {
        guard counts.count == 3, canonicalSources.count == 3, canonicalSigns.count == 3,
              Set(canonicalSources) == Set(0..<3),
              canonicalSigns.allSatisfy({ $0 == -1 || $0 == 1 }) else {
            throw RingProtocolError.invalidPacket
        }
        return zip(canonicalSources, canonicalSigns).map { counts[$0.0] * $0.1 }
    }
}

/// Per-device accelerometer calibration in the canonical RT02 coordinate
/// frame. Identity is deliberate until a physical calibration is measured;
/// never invent gains or offsets from a different ring.
struct GestureSensorCalibration: Codable, Equatable {
    let offsetMG: [Double]
    let gain: [Double]

    static let identity = GestureSensorCalibration(
        offsetMG: [0, 0, 0], gain: [1, 1, 1]
    )

    var isValid: Bool {
        offsetMG.count == 3 && gain.count == 3
            && offsetMG.allSatisfy { $0.isFinite && abs($0) <= 1_000 }
            && gain.allSatisfy { $0.isFinite && (0.5...2.0).contains($0) }
    }

    func apply(_ canonicalMG: [Double]) throws -> [Double] {
        guard isValid, canonicalMG.count == 3, canonicalMG.allSatisfy(\.isFinite) else {
            throw RingProtocolError.invalidPacket
        }
        return (0..<3).map { (canonicalMG[$0] - offsetMG[$0]) * gain[$0] }
    }

    private static let keyPrefix = "gestureSensorCalibration.v1."

    static func stored(for deviceID: String?, defaults: UserDefaults = .standard) -> Self {
        guard let deviceID, !deviceID.isEmpty,
              let data = defaults.data(forKey: keyPrefix + deviceID),
              let value = try? JSONDecoder().decode(Self.self, from: data), value.isValid else {
            return .identity
        }
        return value
    }

    func store(for deviceID: String, defaults: UserDefaults = .standard) throws {
        guard isValid, !deviceID.isEmpty else { throw RingProtocolError.invalidPacket }
        defaults.set(try JSONEncoder().encode(self), forKey: Self.keyPrefix + deviceID)
    }
}

/// Normalizes either board without changing the pinned model's numerical
/// contract. Both sensors nominally encode 8192 packet counts/g at +/-4 g,
/// and the corpus uses the measured common 8005 counts/g. ADC bit depth is not
/// a reason to round packets: RT02 empirically uses all low bits, while RT12's
/// four-count steps are already present in its decoded input.
struct GestureSignalAdapter: Equatable {
    static let mgPerG = 1_000.0
    static let rt02CountsPerG = GestureContract.countsPerG
    static let rt02MGPerCount = mgPerG / rt02CountsPerG
    static let rt02MinMG = -32_768.0 * rt02MGPerCount
    static let rt02MaxMG = 32_767.0 * rt02MGPerCount

    let axisMap: GestureAxisMap
    let calibration: GestureSensorCalibration

    static func rt02cr(calibration: GestureSensorCalibration = .identity) -> Self {
        .init(axisMap: .rt02cr, calibration: calibration)
    }

    static func rt12col(calibration: GestureSensorCalibration = .identity) -> Self {
        .init(axisMap: .rt12col, calibration: calibration)
    }

    func canonicalMG(decodedCounts: [Double]) throws -> [Double] {
        guard decodedCounts.count == 3, decodedCounts.allSatisfy(\.isFinite) else {
            throw RingProtocolError.invalidPacket
        }
        let sourceMG = decodedCounts.map {
            min(Self.rt02MaxMG, max(Self.rt02MinMG, $0 * Self.rt02MGPerCount))
        }
        let canonicalMG = try axisMap.apply(sourceMG).map {
            min(Self.rt02MaxMG, max(Self.rt02MinMG, $0))
        }
        return try calibration.apply(canonicalMG).map {
            min(Self.rt02MaxMG, max(Self.rt02MinMG, $0))
        }
    }

    func modelCounts(decodedCounts: [Double]) throws -> [Double] {
        try canonicalMG(decodedCounts: decodedCounts).map { $0 / Self.rt02MGPerCount }
    }
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
    private let signalAdapter: GestureSignalAdapter
    private let clock: () -> Double
    private let output: (Output) -> Void
    private let invalid: (UUID, String) -> Void

    init(signalAdapter: GestureSignalAdapter = .rt02cr(),
         clock: @escaping () -> Double = { ProcessInfo.processInfo.systemUptime },
         output: @escaping (Output) -> Void, invalid: @escaping (UUID, String) -> Void) {
        self.signalAdapter = signalAdapter; self.clock = clock; self.output = output; self.invalid = invalid
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
            self.lastTime = nil; self.lastSequence = nil
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
                let counts = try self.signalAdapter.modelCounts(
                    decodedCounts: GestureContract.decode(packet)
                )
                if let previous = self.lastTime {
                    guard receivedAt > previous, receivedAt - previous <= 0.25 else { throw UnifiedModeError.staleStream }
                }
                if let previous = self.lastSequence {
                    let advance = sequence &- previous
                    guard advance > 0, advance < 0x80000000 else { throw UnifiedModeError.staleStream }
                }
                // Calibration deliberately asks the wearer to hold completely
                // still for three seconds. RT12COL can legitimately quantize
                // that pose to repeated identical XYZ values, so payload
                // equality is not a delivery-freshness signal. The transport
                // already requires distinct payloads before entering Gesture;
                // here freshness is established by checksum-valid packets,
                // BLE receipt timestamps, bounded gaps and monotonic sequence.
                self.lastTime = receivedAt; self.lastSequence = sequence
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
