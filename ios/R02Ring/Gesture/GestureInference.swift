import CoreML
import Foundation

struct RingGestureEvent: Equatable {
    let name: String
    let direction: String
    let time: Double
    let confidence: Double
    let votes: Int
    let latency: Double?
    let end: Double?
}

enum GestureContract {
    static let checkpointSHA = "77ed774f03ce3eaddbb8ac29ac8dfc1be32fdd7bef997b56c54157891aff26d5"
    static let labels = ["none", "flick_up", "flick_down", "flick_left", "flick_right",
                         "double_flick_up", "double_flick_down", "double_flick_left", "double_flick_right",
                         "snap", "double_clap", "wave"]
    static let collapsed = ["none", "flick", "double_flick", "snap", "double_clap", "wave"]
    static let countsPerG = 8005.0

    static func decode(_ packet: Data) throws -> [Double] {
        guard ColmiR02Protocol.isValidPacket(packet), packet[0] == 0xa1, packet[1] == 3 else {
            throw RingProtocolError.invalidPacket
        }
        return [6, 2, 4].map { Double(Int16(bitPattern: UInt16(packet[$0]) << 8 | UInt16(packet[$0 + 1]))) }
    }

    /// Shape/scale/saturation/room, channel-major float32 [1, 8, 50]. Python
    /// removes the mean in float64, then casts to float32 before deriving channels.
    static func features(_ samples: [[Double]]) throws -> [Float] {
        guard samples.count == 50, samples.allSatisfy({ $0.count == 3 && $0.allSatisfy(\.isFinite) }) else {
            throw RingProtocolError.invalidPacket
        }
        let means = (0..<3).map { axis in samples.reduce(0.0) { $0 + $1[axis] } / 50 }
        let x = (0..<3).map { axis in samples.map { Float(($0[axis] - means[axis]) / countsPerG) } }
        var peak: Float = 0.001
        for t in 0..<50 { peak = max(peak, (x[0][t]*x[0][t] + x[1][t]*x[1][t] + x[2][t]*x[2][t]).squareRoot()) }
        var result = x.flatMap { row in row.map { $0 / peak } }
        result += Array(repeating: log10(peak), count: 50)
        let clipped = (0..<50).filter { t in (0..<3).contains { abs(x[$0][t]) >= Float(0.98 * 32767 / countsPerG) } }.count
        result += Array(repeating: Float(Double(clipped) / 50), count: 50)
        var g = means.map { Float($0 / countsPerG) }
        let norm = max(Float(0.001), (g[0]*g[0] + g[1]*g[1] + g[2]*g[2]).squareRoot())
        g = g.map { $0 / norm }
        var lateral: [Float] = [-g[2], 0, g[0]] // cross(g, along-finger unit axis 1)
        let ln = (lateral[0]*lateral[0] + lateral[2]*lateral[2]).squareRoot()
        lateral = ln > 0.05 ? lateral.map { $0 / max(ln, 0.000001) } : [0, 0, 0]
        let forward: [Float] = [lateral[1]*g[2] - lateral[2]*g[1],
                                lateral[2]*g[0] - lateral[0]*g[2], lateral[0]*g[1] - lateral[1]*g[0]]
        let linear: [[Double]] = (0..<3).map { axis in
            (0..<50).map { t in
                var mean = 0.0
                for offset in -4...4 {
                    var i = t + offset
                    if i < 0 { i = -i }
                    if i >= 50 { i = 98 - i }
                    mean += Double(x[axis][i]) / 9
                }
                return Double(x[axis][t]) - mean
            }
        }
        for basis in [g, lateral, forward] {
            for t in 0..<50 {
                let dot = (0..<3).reduce(0.0) { $0 + linear[$1][t] * Double(basis[$1]) }
                result.append(Float(dot / Double(peak)))
            }
        }
        return result
    }
}

final class PinnedGestureClassifier {
    private let model: MLModel
    init(bundle: Bundle = .main) throws {
        guard let url = bundle.url(forResource: "GestureClassifier", withExtension: "mlmodelc") else {
            throw FirmwareSwitchError.missingImage("GestureClassifier.mlmodelc")
        }
        let config = MLModelConfiguration()
        config.computeUnits = .cpuOnly // parity gate currently covers float32 CPU only
        model = try MLModel(contentsOf: url, configuration: config)
        let metadata = model.modelDescription.metadata[.creatorDefinedKey] as? [String: String]
        guard metadata?["checkpoint_sha256"] == GestureContract.checkpointSHA else { throw RingProtocolError.invalidPacket }
    }

    func probabilities(_ features: [Float]) throws -> [Float] {
        guard features.count == 400, features.allSatisfy(\.isFinite) else { throw RingProtocolError.invalidPacket }
        let input = try MLMultiArray(shape: [1, 8, 50], dataType: .float32)
        for i in features.indices { input[i] = NSNumber(value: features[i]) }
        let result = try model.prediction(from: MLDictionaryFeatureProvider(dictionary: ["samples": input]))
        guard let values = result.featureValue(for: "probabilities")?.multiArrayValue, values.count == 12 else {
            throw RingProtocolError.invalidPacket
        }
        let output = (0..<12).map { values[$0].floatValue }
        guard output.allSatisfy({ $0.isFinite && $0 >= 0 && $0 <= 1 }) else { throw RingProtocolError.invalidPacket }
        return output
    }
}

/// Single-queue engine; retained samples/windows/bursts have bounded lifetimes.
/// Calibration/lifecycle gates are outside this replay-equivalent numerical core.
final class GestureInference {
    private let predict: ([Float]) throws -> [Float]
    private var samples: [[Double]] = []
    private var times: [Double] = []
    private var sinceWindow = 0
    private var tracker = GestureBurstTracker()
    init(predict: @escaping ([Float]) throws -> [Float]) { self.predict = predict }

    func reset() {
        samples.removeAll(keepingCapacity: true)
        times.removeAll(keepingCapacity: true)
        sinceWindow = 0
        tracker = GestureBurstTracker() // deliberately do NOT flush pending events
    }

    func feed(time: Double, counts: [Double]) throws -> [RingGestureEvent] {
        guard time.isFinite, counts.count == 3, counts.allSatisfy(\.isFinite) else { throw RingProtocolError.invalidPacket }
        samples.append(counts); times.append(time); sinceWindow += 1
        let tail = samples.suffix(25)
        let gravity = (0..<3).map { axis in tail.reduce(0.0) { $0 + $1[axis] / 8005 } / Double(tail.count) }
        let mag = (0..<3).reduce(0.0) { value, axis in value + pow(counts[axis] / 8005 - gravity[axis], 2) }.squareRoot()
        var events = tracker.sample(time, magnitude: mag)
        if samples.count > 50 { samples.removeFirst(); times.removeFirst() }
        guard samples.count == 50, sinceWindow >= 6 else { return events }
        sinceWindow = 0
        let probabilities = try predict(GestureContract.features(samples))
        guard probabilities.count == 12 else { throw RingProtocolError.invalidPacket }
        var collapsed: [Float] = [probabilities[0], 0, 0, probabilities[9], probabilities[10], probabilities[11]]
        for i in 1...4 { collapsed[1] += probabilities[i] }
        for i in 5...8 { collapsed[2] += probabilities[i] }
        let raw = probabilities.indices.max { probabilities[$0] == probabilities[$1] ? $0 > $1 : probabilities[$0] < probabilities[$1] }!
        let winner = collapsed.indices.max { collapsed[$0] == collapsed[$1] ? $0 > $1 : collapsed[$0] < collapsed[$1] }!
        let label = winner != 0 && collapsed[winner] >= 0.5 ? GestureContract.collapsed[winner] : "none"
        let direction = label != "none" && (1...8).contains(raw) ? ["up", "down", "left", "right"][(raw - 1) % 4] : "none"
        events += tracker.window(times[0], label: label, confidence: Double(collapsed[winner]), direction: direction)
        return events
    }
}
