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
    /// The two frames the fingers-down pose can produce.
    static let frames: Set<String> = ["identity", "flip_axis0"]

    private var samples: [[Double]] = []
    private var goodSince: Double?
    private(set) var frame: String?

    init() {}

    /// Starts calibrated with a frame found earlier in the same user session
    /// (a heal that kept it); nil for anything but a known frame.
    init?(frame: String) {
        guard Self.frames.contains(frame) else { return nil }
        self.frame = frame
    }

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

/// Freshness limits shared by the inference session, the renewal gate and
/// action dispatch. CoreBluetooth delivers on the main queue, so a main-queue
/// stall shows as a receipt gap followed by a burst (late, in order), and a
/// slow prediction as dequeue age. A running session survives one such stall
/// below `stallCeiling` per `stallInterval`; anything larger or more frequent,
/// and every ordering, sequence, decode or post-inference failure, still ends it.
enum GestureFreshness {
    /// Per-sample limit on receipt spacing and on age at dequeue.
    static let sampleLimit: Double = 0.25
    /// A stall at or above this ends the session. Both measures are checked on
    /// every sample before either is tolerated: the first sample after a
    /// main-queue stall often carries a large receipt gap and a hop delay at
    /// once, and the gap must not hide behind the smaller delay. Also the
    /// renewal gate's largest post-write spacing. It equals the heartbeat's
    /// processed freshness, but a tolerated stall keeps outputs away for
    /// longer than its gap (see `processingPauseLimit`).
    static let stallCeiling: Double = 0.5
    /// Age after inference; also bounds how late an output reaches the main actor's queue.
    static let postInferenceLimit: Double = 0.5
    /// At most one tolerated stall episode per this much receipt time.
    static let stallInterval: Double = 10
    /// Longest episode, first violation to the last violation it absorbs.
    static let maxEpisode: Double = 1
    /// After a violation, samples are dropped until `quarantineSpacings`
    /// consecutive spacings of at least `quarantineMinSpacing` arrive (the
    /// time-compressed backlog has passed) or `quarantine` passes without a
    /// new violation; only then does the inference window restart.
    static let quarantine: Double = 0.5
    static let quarantineMinSpacing: Double = 0.020
    static let quarantineSpacings = 3
    /// Longest a tolerated stall can keep outputs from the main actor, from
    /// the last sample processed before it: a gap just under the ceiling, an
    /// episode extended to `maxEpisode`, a full `quarantine`, and
    /// `sampleLimit` for the release output's hop. The heartbeat waits this
    /// long for processing to resume instead of ending the session; it never
    /// renews without fresh processing.
    static var processingPauseLimit: Double { stallCeiling + maxEpisode + quarantine + sampleLimit }
    /// An event older than this (receipt to main-actor dispatch) runs no action.
    static let dispatchLimit: Double = 0.75

    static func dispatchable(receivedAt: Double, now: Double) -> Bool {
        receivedAt.isFinite && now.isFinite && now - receivedAt <= dispatchLimit
    }
}

/// Bounded, off-main inference. All callbacks must be generation-checked by the
/// consumer too. This class never performs actions: AppModel hands each
/// output's events to `GestureActionRouter` on the main actor.
final class GestureSession {
    struct Output {
        let generation: UUID
        let session: UInt32
        let sequence: UInt32
        let receivedAt: Double
        let pose: GesturePose
        let events: [RingGestureEvent]
        /// This sample's model prediction time, when it ran one.
        var predictSeconds: Double?
        /// Inference queue depth when this sample was enqueued.
        var queued = 0
        /// Consecutive identical XYZ payloads ending at this sample (1 = changed).
        var sameRun = 1
    }

    /// Why the session was invalidated. Recorded before `invalid` is called;
    /// read it from the consumer's generation-checked callback.
    struct Fault: Equatable {
        /// overflow, clock, decode, nonmonotonic, sequence, age_dequeue, gap, engine or age_post.
        let check: String
        let value: Double?
        let limit: Double?
        /// For gap/age_dequeue: first_sample, ceiling, repeat or episode_length.
        let tolerance: String?
        let queued: Int
        let previousReceivedAt: Double?
        let receivedAt: Double?
        let sinceFirstSample: Double?
        let sinceCalibration: Double?
        let predictions: Int
        let lastPredictSeconds: Double?
        let maxPredictSeconds: Double?
        let detail: String?

        var fields: [String: Any] {
            func round(_ value: Double?, _ scale: Double = 1_000) -> Any {
                guard let value, value.isFinite else { return NSNull() }
                return (value * scale).rounded() / scale
            }
            var fields: [String: Any] = [
                "check": check, "value_s": round(value), "limit_s": round(limit),
                "queued": queued, "received_at": round(receivedAt),
                "previous_received_at": round(previousReceivedAt),
                "since_first_s": round(sinceFirstSample), "since_calibration_s": round(sinceCalibration),
                "predictions": predictions,
                "last_predict_ms": round(lastPredictSeconds.map { $0 * 1_000 }, 10),
                "max_predict_ms": round(maxPredictSeconds.map { $0 * 1_000 }, 10),
            ]
            if let tolerance { fields["tolerance"] = tolerance }
            if let detail { fields["detail"] = detail }
            return fields
        }
    }

    /// One tolerated stall episode, reported when processing resumes.
    struct Stall: Equatable {
        /// gap or age_dequeue: the episode's first violation.
        let check: String
        /// The largest violating gap or age in the episode.
        let value: Double
        /// Samples dropped, violating or quarantined.
        let dropped: Int
        let startedAt: Double
        let releasedAt: Double
        var duration: Double { releasedAt - startedAt }
    }

    /// Worker-side reason a sample ends the session.
    private struct Rejection: Error {
        let check: String
        var value: Double?
        var limit: Double?
        var tolerance: String?
        var detail: String?
        var receivedAt: Double?
        var previous: Double?
    }

    private struct Episode {
        let check: String
        let startedAt: Double
        var value: Double
        var dropped: Int
        var lastViolationAt: Double
        var goodSpacings = 0
    }

    /// Lock-protected progress, readable from `ingest` for an overflow fault.
    private struct Progress {
        var firstReceivedAt: Double?
        var calibratedAt: Double?
        var predictions = 0
        var lastPredictSeconds: Double?
        var maxPredictSeconds: Double?
    }

    /// Deep enough that dequeue age, not depth, bounds a backlog: a main-queue
    /// stall delivers its queued notifications back to back while the worker
    /// may be inside a prediction.
    static let queueLimit = 24

    private let queue = DispatchQueue(label: "whip.gesture.inference", qos: .userInitiated)
    private let lock = NSLock()
    // Lock-protected.
    private var queued = 0
    private var generation = UUID()
    private var activeSession: UInt32?
    private var progress = Progress()
    private var fault: Fault?
    private var stallOpenSince: Double?
    // Worker-confined.
    private var engine: GestureInference?
    private var calibration = GestureCalibration()
    private var lastTime: Double?
    private var lastSequence: UInt32?
    private var processedAny = false
    private var episode: Episode?
    private var lastEpisodeStart: Double?
    private var lastPayload: Data?
    private var sameRun = 0
    private var samplePredictSeconds: Double?

    private let signalAdapter: GestureSignalAdapter
    private let clock: () -> Double
    private let output: (Output) -> Void
    private let invalid: (UUID, String) -> Void
    private let onStall: ((UUID, Stall) -> Void)?
    private let onDrop: ((UUID, UInt32) -> Void)?

    /// `onStall` reports each tolerated episode once processing resumes;
    /// `onDrop` sees every sample dropped by an episode (tests, diagnostics).
    /// Both run on the inference queue for the current generation only.
    init(signalAdapter: GestureSignalAdapter = .rt02cr(),
         clock: @escaping () -> Double = { ProcessInfo.processInfo.systemUptime },
         output: @escaping (Output) -> Void, invalid: @escaping (UUID, String) -> Void,
         onStall: ((UUID, Stall) -> Void)? = nil, onDrop: ((UUID, UInt32) -> Void)? = nil) {
        self.signalAdapter = signalAdapter; self.clock = clock; self.output = output; self.invalid = invalid
        self.onStall = onStall; self.onDrop = onDrop
    }

    /// The fault that invalidated the current or last session, if any.
    var lastFault: Fault? {
        lock.lock(); defer { lock.unlock() }
        return fault
    }

    /// Receipt time of the first violation of the tolerated stall episode that
    /// is still dropping samples; nil when none is open (journal, tests).
    var openStallSince: Double? {
        lock.lock(); defer { lock.unlock() }
        return stallOpenSince
    }

    /// `presetFrame`: a calibration frame kept across a heal; the first
    /// sample is then already Ready. Everything else starts fresh.
    @discardableResult
    func start(session: UInt32, classifier: any GestureProbabilities, presetFrame: String? = nil) -> UUID {
        lock.lock()
        let token = UUID()
        generation = token; activeSession = session
        progress = Progress(); fault = nil; stallOpenSince = nil
        // Enqueue reset while holding the same lock used by ingest, so the first
        // sample cannot overtake initialization on the serial worker.
        queue.async { [self] in
            // Timed on the real clock: the injectable clock is for freshness.
            // Weak: the engine is owned by this session.
            engine = GestureInference(predict: { [weak self] features in
                let began = DispatchTime.now().uptimeNanoseconds
                let result = try classifier.probabilities(features)
                self?.notePrediction(Double(DispatchTime.now().uptimeNanoseconds &- began) / 1e9)
                return result
            })
            calibration = presetFrame.flatMap { GestureCalibration(frame: $0) } ?? GestureCalibration()
            lastTime = nil; lastSequence = nil
            processedAny = false; episode = nil; lastEpisodeStart = nil
            lastPayload = nil; sameRun = 0; samplePredictSeconds = nil
        }
        lock.unlock()
        return token
    }

    func stop() {
        lock.lock(); generation = UUID(); activeSession = nil; stallOpenSince = nil; lock.unlock()
        // Invalidates callbacks immediately; old jobs check generation on drain.
    }

    func ingest(_ packet: Data, session: UInt32, sequence: UInt32, receivedAt: Double) {
        lock.lock()
        let token = generation
        guard activeSession == session else { lock.unlock(); return }
        guard queued < Self.queueLimit else {
            activeSession = nil; generation = UUID()
            // Recorded before `invalid`, which runs synchronously on the caller.
            fault = makeFault(Rejection(check: "overflow", value: Double(queued),
                                        limit: Double(Self.queueLimit), receivedAt: receivedAt),
                              queued: queued)
            lock.unlock()
            invalid(token, "Inference queue overflow; Gesture session stopped")
            return
        }
        queued += 1
        let depth = queued
        queue.async {
            defer { self.lock.lock(); self.queued -= 1; self.lock.unlock() }
            guard self.isCurrent(token, session) else { return }
            do {
                try self.process(packet, token: token, session: session, sequence: sequence,
                                 receivedAt: receivedAt, queued: depth)
            } catch let rejection as Rejection {
                self.fail(token, rejection, queued: depth)
            } catch {
                self.fail(token, Rejection(check: "engine", detail: error.localizedDescription,
                                           receivedAt: receivedAt), queued: depth)
            }
        }
        lock.unlock()
    }

    // MARK: Worker

    private func process(_ packet: Data, token: UUID, session: UInt32, sequence: UInt32,
                         receivedAt: Double, queued: Int) throws {
        let age = clock() - receivedAt
        guard receivedAt.isFinite, age >= 0 else {
            throw Rejection(check: "clock", value: age, limit: 0, receivedAt: receivedAt, previous: lastTime)
        }
        let counts: [Double]
        do {
            counts = try signalAdapter.modelCounts(decodedCounts: GestureContract.decode(packet))
        } catch {
            throw Rejection(check: "decode", detail: error.localizedDescription, receivedAt: receivedAt)
        }
        let previous = lastTime
        if let previous, receivedAt <= previous {
            throw Rejection(check: "nonmonotonic", value: receivedAt - previous, limit: 0,
                            receivedAt: receivedAt, previous: previous)
        }
        if let previous = lastSequence {
            let advance = sequence &- previous
            guard advance > 0, advance < 0x80000000 else {
                throw Rejection(check: "sequence", value: Double(advance), receivedAt: receivedAt)
            }
        }
        // Calibration deliberately asks the wearer to hold completely
        // still for three seconds. RT12COL can legitimately quantize
        // that pose to repeated identical XYZ values, so payload
        // equality is not a delivery-freshness signal. The transport
        // already requires distinct payloads before entering Gesture;
        // here freshness is established by checksum-valid packets,
        // BLE receipt timestamps, bounded gaps and monotonic sequence.
        // The run length is journaled only.
        let payload = Data(packet[2..<8])
        sameRun = payload == lastPayload ? sameRun + 1 : 1
        lastPayload = payload
        // Ordering state advances for dropped samples too, so the next gap is
        // measured from this receipt, not from before the stall.
        lastTime = receivedAt; lastSequence = sequence
        let gap = previous.map { receivedAt - $0 }
        lock.lock()
        if progress.firstReceivedAt == nil { progress.firstReceivedAt = receivedAt }
        lock.unlock()

        // Both measures are judged before either is tolerated, whether this
        // starts an episode or extends one; the larger names the check (a
        // tie names the gap). A hop delay under the ceiling must not let a
        // receipt hole over it through.
        let gapValue = gap ?? 0
        let (check, value) = gapValue >= age ? ("gap", gapValue) : ("age_dequeue", age)
        guard value < GestureFreshness.stallCeiling else {
            throw Rejection(check: check, value: value, limit: GestureFreshness.stallCeiling,
                            tolerance: "ceiling", receivedAt: receivedAt, previous: previous)
        }
        if value > GestureFreshness.sampleLimit {
            try absorbStall(check, value: value, receivedAt: receivedAt, previous: previous,
                            token: token, session: session)
            return drop(token, session: session, sequence: sequence)
        }
        if var current = episode {
            if let gap, gap >= GestureFreshness.quarantineMinSpacing { current.goodSpacings += 1 }
            else { current.goodSpacings = 0 }
            guard current.goodSpacings >= GestureFreshness.quarantineSpacings
                    || receivedAt - current.lastViolationAt >= GestureFreshness.quarantine else {
                current.dropped += 1
                episode = current
                return drop(token, session: session, sequence: sequence)
            }
            // No inference window spans the discontinuity: the next prediction
            // needs 50 samples received after this point. Pending burst
            // decisions are dropped, not flushed; a wave already judged keeps
            // its refractory, so one continuous wave fires once. A completed
            // calibration frame is kept; an incomplete hold starts again.
            episode = nil
            setStallOpen(nil, token: token, session: session)
            engine?.reset(releasedAt: receivedAt)
            if calibration.frame == nil { calibration = GestureCalibration() }
            if isCurrent(token, session) {
                onStall?(token, Stall(check: current.check, value: current.value, dropped: current.dropped,
                                      startedAt: current.startedAt, releasedAt: receivedAt))
            }
        }

        samplePredictSeconds = nil
        let pose = calibration.feed(time: receivedAt, counts: counts)
        if pose.frame != nil {
            lock.lock()
            if progress.calibratedAt == nil { progress.calibratedAt = receivedAt }
            lock.unlock()
        }
        var events: [RingGestureEvent] = []
        if let frame = pose.frame {
            let corrected = frame == "identity" ? counts : [counts[0], -counts[1], -counts[2]]
            do { events = try engine?.feed(time: receivedAt, counts: corrected) ?? [] }
            catch { throw Rejection(check: "engine", detail: error.localizedDescription, receivedAt: receivedAt) }
        }
        let postAge = clock() - receivedAt
        guard postAge <= GestureFreshness.postInferenceLimit else {
            throw Rejection(check: "age_post", value: postAge, limit: GestureFreshness.postInferenceLimit,
                            receivedAt: receivedAt, previous: previous)
        }
        processedAny = true
        guard isCurrent(token, session) else { return }
        output(Output(generation: token, session: session, sequence: sequence,
                      receivedAt: receivedAt, pose: pose, events: events,
                      predictSeconds: samplePredictSeconds, queued: queued, sameRun: sameRun))
    }

    /// Starts or extends a stall episode, or throws when it cannot be
    /// tolerated. The caller has already refused `value` at the ceiling.
    private func absorbStall(_ check: String, value: Double, receivedAt: Double, previous: Double?,
                             token: UUID, session: UInt32) throws {
        var rejection = Rejection(check: check, value: value, limit: GestureFreshness.sampleLimit,
                                  receivedAt: receivedAt, previous: previous)
        guard processedAny else { rejection.tolerance = "first_sample"; throw rejection }
        if var current = episode {
            guard receivedAt - current.startedAt <= GestureFreshness.maxEpisode else {
                rejection.tolerance = "episode_length"; throw rejection
            }
            current.value = max(current.value, value)
            current.dropped += 1
            current.lastViolationAt = receivedAt
            current.goodSpacings = 0
            episode = current
            return
        }
        if let lastEpisodeStart, receivedAt - lastEpisodeStart < GestureFreshness.stallInterval {
            rejection.tolerance = "repeat"; throw rejection
        }
        lastEpisodeStart = receivedAt
        episode = Episode(check: check, startedAt: receivedAt, value: value, dropped: 1, lastViolationAt: receivedAt)
        setStallOpen(receivedAt, token: token, session: session)
    }

    /// A stopped or restarted session's worker must not publish its episode.
    private func setStallOpen(_ since: Double?, token: UUID, session: UInt32) {
        lock.lock(); defer { lock.unlock() }
        if generation == token && activeSession == session { stallOpenSince = since }
    }

    private func drop(_ token: UUID, session: UInt32, sequence: UInt32) {
        if isCurrent(token, session) { onDrop?(token, sequence) }
    }

    private func notePrediction(_ seconds: Double) {
        samplePredictSeconds = seconds
        lock.lock()
        progress.predictions += 1
        progress.lastPredictSeconds = seconds
        progress.maxPredictSeconds = max(progress.maxPredictSeconds ?? 0, seconds)
        lock.unlock()
    }

    private func isCurrent(_ token: UUID, _ session: UInt32) -> Bool {
        lock.lock(); defer { lock.unlock() }
        return generation == token && activeSession == session
    }

    private func fail(_ token: UUID, _ rejection: Rejection, queued: Int) {
        lock.lock()
        let current = generation == token
        if current {
            activeSession = nil; generation = UUID(); stallOpenSince = nil
            fault = makeFault(rejection, queued: queued)
        }
        lock.unlock()
        guard current else { return }
        let reason: String
        switch rejection.check {
        case "decode", "engine": reason = rejection.detail ?? UnifiedModeError.staleStream.localizedDescription
        default: reason = UnifiedModeError.staleStream.localizedDescription
        }
        invalid(token, reason)
    }

    /// Call with `lock` held.
    private func makeFault(_ rejection: Rejection, queued: Int) -> Fault {
        Fault(check: rejection.check, value: rejection.value, limit: rejection.limit,
              tolerance: rejection.tolerance, queued: queued,
              previousReceivedAt: rejection.previous, receivedAt: rejection.receivedAt,
              sinceFirstSample: Self.elapsed(from: progress.firstReceivedAt, to: rejection.receivedAt),
              sinceCalibration: Self.elapsed(from: progress.calibratedAt, to: rejection.receivedAt),
              predictions: progress.predictions,
              lastPredictSeconds: progress.lastPredictSeconds, maxPredictSeconds: progress.maxPredictSeconds,
              detail: rejection.detail)
    }

    private static func elapsed(from start: Double?, to end: Double?) -> Double? {
        guard let start, let end else { return nil }
        return end - start
    }
}
