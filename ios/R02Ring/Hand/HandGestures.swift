import Foundation

// MARK: - Frame

/// Perspective rig: `s = f / (dist − z) · sc`, then offset by (ox, oy) in 72×56 tile units.
struct Rig {
    var ox: Double
    var oy: Double
    var sc: Double
    var dist: Double
    var f: Double
}

struct Spark {
    var at: V3
    var dx: Double
    var dy: Double
    var amount: Double
}

/// One evaluated instant of a gesture, ready to draw.
struct HandFrame {
    var caps: [Cap]
    /// Whole-frame transform. Nil when every capsule carries its own (the clap).
    var xf: ((V3) -> V3)?
    var rig: Rig
    var spark: Spark?
}

// MARK: - Gesture catalogue

enum HandGesture {

    /// Cycle length in seconds, per gesture.
    static func duration(_ id: GestureID) -> Double {
        switch id {
        case .flick_up, .flick_down, .flick_left, .flick_right:
            return 2.2
        case .double_flick_up, .double_flick_down, .double_flick_left, .double_flick_right:
            return 2.8
        case .snap:        return 2.4
        case .double_snap: return 3.0
        case .clap:        return 1.9
        case .double_clap: return 2.6
        case .wave:        return 1.8
        }
    }

    /// Evaluates a gesture at normalized cycle position `p ∈ [0,1)`.
    static func frame(_ id: GestureID, at p: Double) -> HandFrame {
        switch id {
        case .flick_up:            return flick(.up, double: false, p)
        case .flick_down:          return flick(.down, double: false, p)
        case .flick_left:          return flick(.left, double: false, p)
        case .flick_right:         return flick(.right, double: false, p)
        case .double_flick_up:     return flick(.up, double: true, p)
        case .double_flick_down:   return flick(.down, double: true, p)
        case .double_flick_left:   return flick(.left, double: true, p)
        case .double_flick_right:  return flick(.right, double: true, p)
        case .snap:                return snap(double: false, p)
        case .double_snap:         return snap(double: true, p)
        case .clap:                return clap(double: false, p)
        case .double_clap:         return clap(double: true, p)
        case .wave:                return wave(p)
        }
    }

    // MARK: Flick

    enum Direction { case up, down, left, right }

    /// Up/down is pure wrist rotation about x, shot in side profile with the forearm fixed.
    /// Left/right is deviation about z plus a roll about y, shot from above and behind.
    private static func flick(_ dir: Direction, double dbl: Bool, _ p: Double) -> HandFrame {
        let beats: [Double] = dbl ? [0.14, 0.5] : [0.28]
        var a = 0.0, sp = 0.0
        for b in beats {
            a += pulse(p, b, 0.06, 0.26, 1.12)
            sp += sparkAmount(p, b + 0.03, 0.12)
        }

        let ud = (dir == .up || dir == .down)
        let pose: Pose = ud
            ? Pose(f: [Flex(14, 12), Flex(12, 10), Flex(14, 12), Flex(18, 16)],
                   spread: 5, thumb: V3(-15, 12, -3))
            : Pose(f: [Flex(6, 5), Flex(4, 4), Flex(6, 5), Flex(9, 8)],
                   spread: 7, thumb: V3(-15, 13, -2))

        var build = buildHand(pose, ring: true)

        // Side profile reads best off the left hand, so the thumb faces the camera.
        if ud {
            for i in build.caps.indices {
                build.caps[i].a.x = -build.caps[i].a.x
                build.caps[i].b.x = -build.caps[i].b.x
            }
        }

        let A = 30 * D * a

        let cam: (V3) -> V3 = ud
            ? { q in V3(q.y - 6, q.z, -q.x).ry(14 * D).rx(-16 * D) }
            : { q in q.ry((dir == .left ? 10 : -10) * D).rx(-22 * D) }

        let wrist: (V3) -> V3 = { q in
            switch dir {
            case .up:    return q.rx(A)
            case .down:  return q.rx(-A)
            case .left:  return q.rz(A).ry(-A * 0.9)
            case .right: return q.rz(-A).ry(A * 0.9)
            }
        }
        let xf: (V3) -> V3 = { cam(wrist($0)) }

        for i in build.caps.indices where build.caps[i].kind == .forearm {
            build.caps[i].xf = cam          // the forearm stays put; only the hand rotates
            if ud {                         // and reads longer in profile
                build.caps[i].a = V3(0, -30, 0)
                build.caps[i].b = V3(0, -1, 0)
            }
        }

        let sd: (Double, Double)
        switch dir {
        case .up:    sd = (0, -1)
        case .down:  sd = (0, 1)
        case .left:  sd = (-1, 0)
        case .right: sd = (1, 0)
        }

        return HandFrame(
            caps: build.caps,
            xf: xf,
            rig: ud ? Rig(ox: 34, oy: 30, sc: 0.95, dist: 90, f: 105)
                    : Rig(ox: 36, oy: 46, sc: 0.95, dist: 88, f: 100),
            spark: sp > 0 ? Spark(at: build.midTip, dx: sd.0, dy: sd.1, amount: sp) : nil)
    }

    // MARK: Snap

    /// Three moves: a slow squeeze building tension against the thumb, a ~35ms release
    /// where the middle whips past it into the palm, then a long eased settle back.
    private static func snap(double dbl: Bool, _ p: Double) -> HandFrame {
        let beats: [Double] = dbl ? [0.2, 0.55] : [0.34]
        var u = 0.0, sp = 0.0, pre = 0.0, kick = 0.0
        for b in beats {
            u    += hold(p, b, 0.035, dbl ? 0.1 : 0.14, dbl ? 0.2 : 0.44)
            sp   += sparkAmount(p, b + 0.015, 0.14)
            pre  += hold(p, b - 0.24, 0.2, 0.05, 0.02)
            kick += pulse(p, b, 0.05, 0.24, 1)
        }
        u = min(1, u); pre = min(1, pre); kick = min(1, kick)

        // Middle: squeezed on the thumb pad, then whipped into the palm.
        let mcp2 = 50 + 7 * pre + 56 * u
        let pip2 = 45 + 9 * pre + 66 * u
        // A small idle breath on the index keeps the tile alive between beats.
        let idle = sin(p * .pi * 4) * 1.6

        let pose = Pose(
            f: [
                Flex(3 + idle - 2 * pre - 4 * kick + 16 * u,
                     2 + idle * 0.5 - 2 * kick + 20 * u),   // index — stays extended
                Flex(mcp2, pip2),                           // middle — does the snapping
                Flex(7 + 4 * pre + 5 * u, 9 + 6 * u),       // ring finger — extended
                Flex(26 + 6 * pre + 8 * u, 28 + 10 * u),    // pinky — lightly relaxed
            ],
            spread: 9 - 2 * pre + 2.5 * kick,
            thumb: V3(-2.4 - 5.2 * kick + 0.7 * pre,
                      22.4 - 3.4 * kick - 0.9 * pre,
                      -13.5 + 6 * kick),                    // rides its own recoil, clearing the middle
            thumbBase: V3(-7, 13, -2.5))

        let build = buildHand(pose, ring: true)

        // Palm toward the viewer, hand near-vertical, then a screen-space roll so the
        // index rakes up-left and the forearm exits lower-right.
        let xf: (V3) -> V3 = { $0.ry(172 * D).rx(-8 * D).rz(10 * D) }

        return HandFrame(
            caps: build.caps,
            xf: xf,
            rig: Rig(ox: 36, oy: 48, sc: 0.98, dist: 90, f: 110),
            spark: sp > 0 ? Spark(at: build.thumbTip, dx: -0.85, dy: -0.5, amount: sp) : nil)
    }

    // MARK: Clap

    /// Palms stacked; the far hand is the mirror hand (z reflected), scissored open and
    /// closing on the beat about the palm centre so the two stay linked.
    private static func clap(double dbl: Bool, _ p: Double) -> HandFrame {
        let beats: [Double] = dbl ? [0.14, 0.46] : [0.26]
        var c = 0.0, sp = 0.0
        for b in beats {
            c += hold(p, b, 0.08, 0.05, 0.2)
            sp += sparkAmount(p, b + 0.06, 0.12)
        }
        c = min(1, c)

        let pose = Pose(f: [Flex(4, 5), Flex(2, 3), Flex(3, 4), Flex(6, 7)],
                        spread: 6, thumb: V3(-12, 12, -5))

        let near = buildHand(pose, ring: true)
        var farPose = pose
        farPose.forearm = false
        farPose.spread = 7
        let far = buildHand(farPose, ring: false)

        let gap = 5.4 - 2.8 * c
        let scis = (74 - 26 * c) * D     // nearly 90° apart, closing to ~65° on impact
        let nearRoll = (18 - 8 * c) * D

        // Camera swings in from the left and sits further above.
        let camT: (V3) -> V3 = { $0.ry(-26 * D).rx(-22 * D).rz(-62 * D) }

        let xfN: (V3) -> V3 = { q in camT(q.rz(nearRoll) + V3(0, 0, gap)) }
        // The scissor pivots about the palm centre (y = 13), not the wrist.
        let xfF: (V3) -> V3 = { q in
            let mirrored = V3(q.x, q.y, -q.z) + V3(0, -13, 0)
            return camT(mirrored.rz(-scis) + V3(0, 13, 0) + V3(0.5, -1, -gap))
        }

        var all = near.caps.map { cap -> Cap in var c = cap; c.xf = xfN; return c }
        all += far.caps.map { cap -> Cap in var c = cap; c.xf = xfF; return c }

        return HandFrame(
            caps: all,
            xf: nil,
            rig: Rig(ox: 31, oy: 33, sc: 0.86, dist: 95, f: 110),
            // Already in camera space — the renderer projects it without a transform.
            spark: sp > 0 ? Spark(at: camT(V3(2, 21, gap)), dx: 0.75, dy: -0.66, amount: sp) : nil)
    }

    // MARK: Wave

    /// A sine roll about z with a yaw about y, fingers splayed, camera 14° above.
    private static func wave(_ p: Double) -> HandFrame {
        let s = sin(p * .pi * 2)
        let pose = Pose(f: [Flex(6, 6), Flex(4, 4), Flex(5, 5), Flex(8, 8)],
                        spread: 10, thumb: V3(-14, 14, -3))
        let build = buildHand(pose, ring: true)
        let xf: (V3) -> V3 = { $0.rz(-22 * D * s).ry(18 * D * s + 12 * D).rx(-14 * D) }

        return HandFrame(
            caps: build.caps,
            xf: xf,
            rig: Rig(ox: 36, oy: 50, sc: 0.92, dist: 90, f: 110),
            spark: nil)
    }
}
