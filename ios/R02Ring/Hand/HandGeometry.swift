import Foundation

// MARK: - Vectors
//
// Hand-local frame: wrist at the origin, +y along the fingers, +z out of the back of
// the hand, −x toward the thumb. Every constant below is transcribed from the design
// canvas, which is the spec of record for the geometry.

struct V3 {
    var x: Double
    var y: Double
    var z: Double

    init(_ x: Double, _ y: Double, _ z: Double) { self.x = x; self.y = y; self.z = z }

    static func + (a: V3, b: V3) -> V3 { V3(a.x + b.x, a.y + b.y, a.z + b.z) }
    static func - (a: V3, b: V3) -> V3 { V3(a.x - b.x, a.y - b.y, a.z - b.z) }
    static func * (a: V3, k: Double) -> V3 { V3(a.x * k, a.y * k, a.z * k) }

    var length: Double { (x * x + y * y + z * z).squareRoot() }

    var normalized: V3 {
        let l = length
        return l == 0 ? self : self * (1 / l)
    }

    func lerp(_ b: V3, _ t: Double) -> V3 {
        V3(x + (b.x - x) * t, y + (b.y - y) * t, z + (b.z - z) * t)
    }

    /// Rotation about x — wrist flexion/extension (the up/down flick).
    func rx(_ a: Double) -> V3 {
        let c = cos(a), s = sin(a)
        return V3(x, y * c - z * s, y * s + z * c)
    }
    /// Rotation about y — roll along the forearm.
    func ry(_ a: Double) -> V3 {
        let c = cos(a), s = sin(a)
        return V3(x * c + z * s, y, -x * s + z * c)
    }
    /// Rotation about z — radial/ulnar deviation (the left/right flick).
    func rz(_ a: Double) -> V3 {
        let c = cos(a), s = sin(a)
        return V3(x * c - y * s, x * s + y * c, z)
    }
}

/// Degrees → radians, named to keep the ported expressions close to the originals.
let D = Double.pi / 180

// MARK: - Skeleton

/// One stroked capsule of the hand.
struct Cap {
    enum Kind {
        case palm, finger, forearm, ring
    }
    var a: V3
    var b: V3
    var r: Double
    var kind: Kind
    /// Per-capsule transform override. The forearm uses this to stay put while the
    /// hand rotates at the wrist; the clap uses it to drive two independent hands.
    var xf: ((V3) -> V3)?
}

/// Per-finger flexion: MCP (knuckle) and PIP (middle joint), in degrees.
struct Flex {
    var mcp: Double
    var pip: Double
    init(_ mcp: Double, _ pip: Double) { self.mcp = mcp; self.pip = pip }
}

struct Pose {
    /// Index, middle, ring, pinky.
    var f: [Flex]
    var spread: Double = 0
    /// The point the thumb tip is aimed at.
    var thumb: V3
    var thumbBase: V3? = nil
    var forearm: Bool = true
}

struct HandBuild {
    var caps: [Cap] = []
    /// Middle fingertip — where the flick spark fires.
    var midTip: V3 = V3(0, 0, 0)
    /// Thumb tip — where the snap spark fires.
    var thumbTip: V3 = V3(0, 0, 0)
}

/// Finger table: x base, proximal length, distal length, splay (deg), y base.
private let fingerTable: [(x: Double, l1: Double, l2: Double, splay: Double, y: Double)] = [
    (-7.0, 8.0, 6.0, -1.5, 16.6),   // index — wears the ring
    (-2.4, 9.0, 7.0, -0.3, 17.2),   // middle
    ( 2.4, 8.5, 6.5,  0.6, 16.8),   // ring finger
    ( 7.0, 6.5, 5.0,  1.6, 15.6),   // pinky
]

/// Builds the hand as a list of capsules in the hand-local frame.
func buildHand(_ p: Pose, ring: Bool) -> HandBuild {
    var out = HandBuild()
    func push(_ a: V3, _ b: V3, _ r: Double, _ k: Cap.Kind) {
        out.caps.append(Cap(a: a, b: b, r: r, kind: k, xf: nil))
    }

    // Palm: three metacarpal shafts, the knuckle bar, the thenar wedge, the wrist bar.
    push(V3(-4.6, 3, 0),    V3(-4.6, 15, 0),   2.9, .palm)
    push(V3(0, 2.5, 0),     V3(0, 15.5, 0),    3.0, .palm)
    push(V3(4.6, 3, 0),     V3(4.6, 15, 0),    2.9, .palm)
    push(V3(-6.5, 15.5, 0), V3(6.5, 15.5, 0),  2.4, .palm)
    push(V3(-5.5, 5, -0.5), V3(-8.5, 9, -1.5), 2.5, .palm)
    push(V3(-4.6, 2.2, 0),  V3(4.6, 2.2, 0),   2.9, .palm)

    if p.forearm {
        push(V3(0, -16, 0), V3(0, -1, 0), 3.6, .forearm)
    }

    // Fingers: two flexion angles plus splay build base → mid → tip.
    for (i, f) in fingerTable.enumerated() {
        let fp = p.f[i]
        let sp = p.spread * (Double(i) - 1.5) * D + f.splay * D

        let d1 = V3(0, 1, 0).rx(-fp.mcp * D).rz(-sp)
        let base = V3(f.x, f.y, 0)
        let mid = base + d1 * f.l1

        let d2 = V3(0, 1, 0).rx(-(fp.mcp + fp.pip) * D).rz(-sp)
        let tip = mid + d2 * f.l2

        push(base, mid, 1.6, .finger)
        push(mid, tip, 1.45, .finger)

        // The product: a fat short capsule on the index's proximal segment.
        if i == 0 && ring {
            push(base.lerp(mid, 0.36), base.lerp(mid, 0.6), 2.05, .ring)
        }
        if i == 1 { out.midTip = tip }
    }

    // Thumb: solved by aiming two elbowed segments from the thumb base at a target.
    let tb = p.thumbBase ?? V3(-8, 8.5, -1.5)
    let tgt = p.thumb
    let v = tgt - tb
    let L = v.length
    let dir = v.normalized
    let l1 = min(8.5, L * 0.55)
    let l2 = min(7, L - l1)

    push(tb, tb, 2.4, .finger)                       // the thenar knuckle, drawn as a dot
    let knee = tb + dir * l1 + V3(-1.2, 0, -0.6)
    push(tb, knee, 2.0, .finger)
    push(knee, knee + (tgt - knee).normalized * l2, 1.75, .finger)

    out.thumbTip = tgt
    return out
}

// MARK: - Easing
//
// Two helpers drive every gesture, over a normalized cycle p ∈ [0,1).

/// Rises fast with an overshoot, decays slowly — a flick, a recoil.
func pulse(_ p: Double, _ t0: Double, _ rise: Double, _ fall: Double, _ over: Double = 1) -> Double {
    var e = p - t0
    if e < 0 { return 0 }
    if e < rise {
        let v = e / rise
        return over * v * (2 - v)
    }
    e -= rise
    if e < fall {
        let q = e / fall
        return over * (1 - q * q * (3 - 2 * q))
    }
    return 0
}

/// Smooth rise, hold, smooth fall — a squeeze, a contact.
func hold(_ p: Double, _ t0: Double, _ rise: Double, _ hd: Double, _ fall: Double) -> Double {
    var e = p - t0
    if e < 0 { return 0 }
    if e < rise {
        let v = e / rise
        return v * v * (3 - 2 * v)
    }
    e -= rise
    if e < hd { return 1 }
    e -= hd
    if e < fall {
        let q = e / fall
        return 1 - q * q * (3 - 2 * q)
    }
    return 0
}

/// A linear fade used for the spark flash.
func sparkAmount(_ p: Double, _ t0: Double, _ len: Double) -> Double {
    let e = p - t0
    return (e < 0 || e > len) ? 0 : 1 - e / len
}
