import SwiftUI

/// The live PPG trace: one beat every 120pt, scrolling left at 120pt/s over a 30pt grid.
/// The beat path is the design's, authored in a 120×96 box and scaled to fit vertically.
struct PulseScope: View {
    var color: Color = Tok.accent
    var lineWidth: CGFloat = 3
    var bpm: Int? = nil

    private static let beatWidth: Double = 120
    private static let beatHeight: Double = 96

    /// One cardiac cycle: baseline, the systolic spike, then the dicrotic notch.
    private static func beat(into path: inout Path, at x: Double, scale: Double) {
        func pt(_ px: Double, _ py: Double) -> CGPoint {
            CGPoint(x: x + px, y: py * scale)
        }
        path.move(to: pt(0, 64))
        path.addCurve(to: pt(20, 60), control1: pt(10, 64), control2: pt(14, 62))
        path.addCurve(to: pt(38, 18), control1: pt(26, 58), control2: pt(30, 20))
        path.addCurve(to: pt(60, 60), control1: pt(46, 16), control2: pt(52, 56))
        path.addCurve(to: pt(76, 52), control1: pt(66, 63), control2: pt(70, 50))
        path.addCurve(to: pt(92, 64), control1: pt(82, 54), control2: pt(86, 64))
        path.addCurve(to: pt(120, 64), control1: pt(100, 64), control2: pt(110, 64))
    }

    var body: some View {
        TimelineView(.animation) { timeline in
            Canvas { ctx, size in
                let scale = size.height / Self.beatHeight

                // The 30pt reference grid the trace runs over.
                var grid = Path()
                var gx = 29.0
                while gx < size.width {
                    grid.move(to: CGPoint(x: gx, y: 0))
                    grid.addLine(to: CGPoint(x: gx, y: size.height))
                    gx += 30
                }
                ctx.stroke(grid, with: .color(Color(hex: 0x0D150F)), lineWidth: 1)

                let t = timeline.date.timeIntervalSinceReferenceDate
                let period = 60.0 / Double(max(35, min(220, bpm ?? 60)))
                let shift = t.truncatingRemainder(dividingBy: period) / period * Self.beatWidth

                var trace = Path()
                var x = -shift
                while x < size.width {
                    Self.beat(into: &trace, at: x, scale: scale)
                    x += Self.beatWidth
                }
                ctx.stroke(trace, with: .color(color),
                           style: StrokeStyle(lineWidth: lineWidth, lineJoin: .round))
            }
        }
        .clipped()
        .accessibilityHidden(true)
    }
}
