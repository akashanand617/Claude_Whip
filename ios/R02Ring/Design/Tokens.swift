import SwiftUI

/// Design tokens from the R02 handoff. Dark is the primary (and only shipped) theme;
/// the light values are kept because the gesture renderer is authored for both.
enum Tok {
    // MARK: Color
    static let ink        = Color(hex: 0x070A08) // screen ground
    static let inkRaised  = Color(hex: 0x0B110D) // row press background
    static let hairline   = Color(hex: 0x16241B) // 1px rules, inactive toggle track
    static let dim        = Color(hex: 0x3D5A45) // tertiary text, chevrons, goal line
    static let muted      = Color(hex: 0x6F8A76) // secondary/label text
    static let text       = Color(hex: 0xE8F2EA) // primary text
    static let accent     = Color(hex: 0x3DDC84) // active state, primary series, average line
    static let accentDeep = Color(hex: 0x2B8F5C) // secondary series
    static let series3    = Color(hex: 0x27482F) // tertiary series (light sleep)

    // Today's hypnogram uses its own ramp (5a) — brighter than the detail-screen series.
    static let sleepDeep  = Color(hex: 0x3DDC84)
    static let sleepLight = Color(hex: 0x27965A)
    static let sleepREM   = Color(hex: 0x1F5C38)
    static let sleepAwake = Color(hex: 0x16241B)

    // MARK: Metrics
    static let side: CGFloat = 20          // screen side margin
    static let hairlineWidth: CGFloat = 1
    static let rowMinHeight: CGFloat = 46
    static let settingsRowHeight: CGFloat = 52
    static let tapTarget: CGFloat = 44

    /// The design's 62pt top padding stands in for the safe area; on device the status bar
    /// eats 59 of it, so content sits this far below the safe-area top.
    static let headerTopPad: CGFloat = 4
}

// MARK: - Type
//
// JetBrains Mono and Instrument Serif are not bundled; the handoff sanctions
// SF Mono / New York as substitutes, which is what `.monospaced` / `.serif` resolve to.

extension Font {
    static func mono(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .monospaced)
    }
    static func serif(_ size: CGFloat) -> Font {
        .system(size: size, weight: .regular, design: .serif)
    }
}

extension View {
    /// 11pt uppercase mono with the design's 0.08em tracking — nav and section labels.
    func labelType(_ size: CGFloat = 11, tracking: CGFloat = 0.08) -> some View {
        self.font(.mono(size)).tracking(size * tracking).textCase(.uppercase)
    }
}

extension Color {
    init(hex: UInt32) {
        self.init(
            .sRGB,
            red:   Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8)  & 0xFF) / 255,
            blue:  Double( hex        & 0xFF) / 255,
            opacity: 1
        )
    }
}
