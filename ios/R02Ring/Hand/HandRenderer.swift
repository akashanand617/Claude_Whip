import SwiftUI

// MARK: - Theme

/// The renderer is authored for both grounds (8a dark / 8b light); the app ships dark.
struct HandTheme {
    var base: RGB
    var fore: RGB
    var ring: RGB
    var ink: Color
    /// Lit and shadowed extremes that `base` is mixed toward by depth.
    var hi: Double = 255
    var sh: Double = 0

    static let dark = HandTheme(base: RGB(0x4A6B53), fore: RGB(0x3A5442),
                                ring: RGB(0x3DDC84), ink: Color(hex: 0x070A08))
    static let light = HandTheme(base: RGB(0x98AD9E), fore: RGB(0x86998C),
                                 ring: RGB(0x1F9D55), ink: Color(hex: 0xF4F6F4))
}

struct RGB {
    var r: Double, g: Double, b: Double

    init(_ hex: UInt32) {
        r = Double((hex >> 16) & 0xFF)
        g = Double((hex >> 8) & 0xFF)
        b = Double(hex & 0xFF)
    }
    init(r: Double, g: Double, b: Double) { self.r = r; self.g = g; self.b = b }

    /// Mixes toward a flat grey level (255 = light, 0 = shadow) by weight `w`.
    func mix(toward level: Double, _ w: Double) -> RGB {
        RGB(r: r + (level - r) * w, g: g + (level - g) * w, b: b + (level - b) * w)
    }

    var color: Color {
        Color(.sRGB, red: r / 255, green: g / 255, blue: b / 255, opacity: 1)
    }
}

// MARK: - Renderer

enum HandRenderer {

    private struct Projected {
        var x: Double
        var y: Double
        var s: Double
        var z: Double
    }

    /// Draws one gesture tile. `size` is the tile in points; the design authored it at
    /// 72×56, and everything scales off that so the tiles stay proportional at any size.
    static func draw(_ ctx: inout GraphicsContext,
                     size: CGSize,
                     gesture: GestureID,
                     time: Double,
                     theme: HandTheme = .dark) {

        let duration = HandGesture.duration(gesture)
        let p = (time.truncatingRemainder(dividingBy: duration)) / duration
        let frame = HandGesture.frame(gesture, at: p)
        let rig = frame.rig
        let R = size.width / 72

        func project(_ q: V3, _ per: ((V3) -> V3)?) -> Projected {
            let w = (per ?? frame.xf)?(q) ?? q
            let s = rig.f / (rig.dist - w.z) * rig.sc
            return Projected(x: (rig.ox + w.x * s) * R,
                             y: (rig.oy - w.y * s) * R,
                             s: s * R,
                             z: w.z)
        }

        // Back to front, so nearer capsules overlap the ones behind them.
        let items = frame.caps
            .map { cap -> (cap: Cap, a: Projected, b: Projected, z: Double) in
                let a = project(cap.a, cap.xf)
                let b = project(cap.b, cap.xf)
                return (cap, a, b, (a.z + b.z) / 2)
            }
            .sorted { $0.z < $1.z }

        for item in items {
            let a = item.a, b = item.b
            let s = (a.s + b.s) / 2
            let w = item.cap.r * 2 * s

            // A zero-length capsule (the thumb knuckle) still has to paint its round cap.
            let ax = a.x, ay = a.y
            var bx = b.x, by = b.y
            if abs(bx - ax) < 0.01 && abs(by - ay) < 0.01 { bx += 0.01 }

            func segment(from: CGPoint, to: CGPoint) -> Path {
                var path = Path()
                path.move(to: from)
                path.addLine(to: to)
                return path
            }
            func stroke(_ path: Path, _ color: Color, _ width: Double, opacity: Double = 1) {
                ctx.stroke(path, with: .color(color.opacity(opacity)),
                           style: StrokeStyle(lineWidth: width, lineCap: .round, lineJoin: .round))
            }

            let main = segment(from: CGPoint(x: ax, y: ay), to: CGPoint(x: bx, y: by))

            let depth = max(-0.2, min(0.2, item.z / 120))
            let base = item.cap.kind == .forearm ? theme.fore : theme.base
            let lit = base.mix(toward: depth > 0 ? theme.hi : theme.sh, abs(depth) * 0.9)

            // 1. Ink outline — keeps overlapping forms distinct.
            stroke(main, theme.ink, w + 1.1 * R)

            if item.cap.kind == .ring {
                // The ring glows throughout: a pulsing halo plus a bright core.
                let g = 0.75 + 0.25 * sin(time * 3)
                ctx.drawLayer { layer in
                    layer.addFilter(.shadow(color: theme.ring.color,
                                            radius: 3.5 * R * g, x: 0, y: 0))
                    // Stroked twice, as the reference does, to build the halo up.
                    for _ in 0..<2 {
                        layer.stroke(main, with: .color(theme.ring.color),
                                     style: StrokeStyle(lineWidth: w, lineCap: .round, lineJoin: .round))
                    }
                }
                stroke(main, theme.ring.mix(toward: 255, 0.45).color, w * 0.42)
                continue
            }

            // 2. Shadow rim, offset down-right.
            stroke(segment(from: CGPoint(x: ax + w * 0.06, y: ay + w * 0.08),
                           to:   CGPoint(x: bx + w * 0.06, y: by + w * 0.08)),
                   base.mix(toward: theme.sh, 0.35).color, w)

            // 3. Base, lit by depth.
            stroke(main, lit.color, w)

            // 4. Inset highlight, up-left.
            let dx = bx - ax, dy = by - ay
            let L = (dx * dx + dy * dy).squareRoot()
            if L > w * 0.6 {
                let ux = dx / L, uy = dy / L, inset = w * 0.42
                stroke(segment(from: CGPoint(x: ax + ux * inset - w * 0.12,
                                             y: ay + uy * inset - w * 0.14),
                               to:   CGPoint(x: bx - ux * inset - w * 0.12,
                                             y: by - uy * inset - w * 0.14)),
                       base.mix(toward: theme.hi, 0.22).color, w * 0.26, opacity: 0.6)
            }
        }

        // The three-line spark at the fingertip.
        if let spk = frame.spark {
            let c: Projected
            if frame.xf != nil {
                c = project(spk.at, nil)
            } else {
                // The clap hands its spark over already in camera space.
                let s = rig.f / (rig.dist - spk.at.z) * rig.sc
                c = Projected(x: (rig.ox + spk.at.x * s) * R,
                              y: (rig.oy - spk.at.y * s) * R, s: s * R, z: spk.at.z)
            }

            let dx = spk.dx, dy = spk.dy
            let px = -dy, py = dx
            let L = 6 * R * spk.amount, o = 2.5 * R
            let alpha = min(1, spk.amount * 1.4)

            for (side, len) in [(0.0, 1.0), (-0.7, 0.8), (0.7, 0.8)] {
                let sx = c.x + dx * o + px * side * 4 * R
                let sy = c.y + dy * o + py * side * 4 * R
                var path = Path()
                path.move(to: CGPoint(x: sx, y: sy))
                path.addLine(to: CGPoint(x: sx + dx * L * len + px * side * 2 * R,
                                         y: sy + dy * L * len + py * side * 2 * R))
                ctx.stroke(path, with: .color(theme.ring.color.opacity(alpha)),
                           style: StrokeStyle(lineWidth: 1.6 * R, lineCap: .round))
            }
        }
    }
}

// MARK: - Tile

/// A gesture animating on its own clock. The design's tile is 72×56.
struct GestureTile: View {
    var gesture: GestureID
    var theme: HandTheme = .dark

    var body: some View {
        TimelineView(.animation) { timeline in
            Canvas { ctx, size in
                let t = timeline.date.timeIntervalSinceReferenceDate
                HandRenderer.draw(&ctx, size: size, gesture: gesture, time: t, theme: theme)
            }
        }
        .frame(width: 72, height: 56)
        // A <canvas> clips to its backing store; SwiftUI's Canvas does not, and the
        // forearm reaches well past the tile on the profile shots.
        .clipped()
        .accessibilityHidden(true)
    }
}
