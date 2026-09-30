import SwiftUI
#if os(iOS)
import UIKit
#endif

// MARK: - Rules

/// A 1px rule. `1` in the design means one *pixel*, so it thins on retina.
struct Hairline: View {
    var color: Color = Tok.hairline
    var body: some View {
        Rectangle()
            .fill(color)
            .frame(height: Tok.hairlineWidth)
    }
}

/// A horizontal dashed rule — the average / goal lines on the detail charts.
struct DashedRule: View {
    var color: Color
    var opacity: Double = 1
    var dash: [CGFloat] = [3, 3]

    var body: some View {
        GeometryReader { geo in
            Path { p in
                p.move(to: CGPoint(x: 0, y: 0.5))
                p.addLine(to: CGPoint(x: geo.size.width, y: 0.5))
            }
            .stroke(color.opacity(opacity),
                    style: StrokeStyle(lineWidth: Tok.hairlineWidth, dash: dash))
        }
        .frame(height: 1)
    }
}

// MARK: - Press feedback

/// Rows across the app take an `inkRaised` background while held.
struct RowPressStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .background(configuration.isPressed ? Tok.inkRaised : Color.clear)
            .contentShape(Rectangle())
    }
}

// MARK: - Header furniture

/// 22×10 outline pill filled to `percent`, with the reading beside it.
struct BatteryPill: View {
    var percent: Int?

    var body: some View {
        HStack(spacing: 6) {
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 2)
                        .strokeBorder(Tok.dim, lineWidth: Tok.hairlineWidth)
                    // Fill sits inside the 1pt outline, so it measures against the inner track.
                    Tok.accent
                        .frame(width: max(0, (geo.size.width - 2) * Double(percent ?? 0) / 100),
                               height: max(0, geo.size.height - 2))
                        .offset(x: 1)
                }
            }
            .frame(width: 22, height: 10)

            Text(percent.map { "\($0)%" } ?? "—")
                .labelType()
                .foregroundStyle(Tok.text)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(percent.map { "Ring battery \($0) percent" } ?? "Ring battery unavailable")
    }
}

/// `SETTINGS ·············· [██▁] 72%` — the shared screen header.
struct ScreenHeader<Trailing: View>: View {
    var title: String
    @ViewBuilder var trailing: Trailing

    var body: some View {
        HStack {
            Text(title)
                .labelType()
                .foregroundStyle(Tok.muted)
            Spacer(minLength: 8)
            trailing
        }
        .frame(minHeight: 22)
        .padding(.horizontal, Tok.side)
        .padding(.top, Tok.headerTopPad)
    }
}

extension ScreenHeader where Trailing == EmptyView {
    init(title: String) {
        self.init(title: title) { EmptyView() }
    }
}

// MARK: - Controls

/// The restyled switch: 40×22 track, 18pt knob, 44pt hit area.
struct RingToggle: View {
    @Binding var isOn: Bool

    var body: some View {
        Capsule()
            .fill(isOn ? Tok.accent : Tok.hairline)
            .frame(width: 40, height: 22)
            .overlay(alignment: isOn ? .trailing : .leading) {
                Circle()
                    .fill(isOn ? Tok.ink : Tok.dim)
                    .frame(width: 18, height: 18)
                    .padding(2)
            }
            // The drawn track stays 40×22; the hit area meets the 44pt minimum.
            .frame(minWidth: Tok.tapTarget, minHeight: Tok.tapTarget, alignment: .trailing)
            .contentShape(Rectangle())
            .onTapGesture {
                withAnimation(.easeOut(duration: 0.18)) { isOn.toggle() }
            }
            .accessibilityElement()
            .accessibilityAddTraits(.isButton)
            .accessibilityValue(isOn ? "On" : "Off")
    }
}

/// The wide outlined action at the foot of Today and Gestures. Dims when disabled.
struct OutlineButton: View {
    var title: String
    var action: () -> Void = {}
    @Environment(\.isEnabled) private var isEnabled

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.mono(13))
                .tracking(13 * 0.14)
                .textCase(.uppercase)
                .foregroundStyle(isEnabled ? Tok.accent : Tok.dim)
                .frame(maxWidth: .infinity)
                .frame(minHeight: 48)
                .overlay {
                    Rectangle().strokeBorder(isEnabled ? Tok.accent : Tok.hairline, lineWidth: Tok.hairlineWidth)
                }
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .padding(.horizontal, 60)
    }
}

// MARK: - Tab bar

struct RingTabBar: View {
    @Binding var selection: Tab

    var body: some View {
        VStack(spacing: 0) {
            Hairline()
            HStack(spacing: 56) {
                ForEach(Tab.healthTabs) { tab in
                    let active = tab == selection
                    Button {
                        selection = tab
                    } label: {
                        VStack(spacing: 0) {
                            Text(tab.title)
                                .labelType()
                                .foregroundStyle(active ? Tok.text : Tok.dim)
                                .padding(.vertical, 8)
                            // The 2px accent underline only on the active item.
                            Rectangle()
                                .fill(active ? Tok.accent : .clear)
                                .frame(height: 2)
                        }
                        .frame(minWidth: Tok.tapTarget)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityAddTraits(active ? [.isButton, .isSelected] : .isButton)
                }
            }
            .padding(.top, 12)
            .padding(.horizontal, Tok.side)
            .padding(.bottom, 8)
        }
    }
}

// MARK: - Screen chrome

/// Every screen is the same sandwich: ink ground, content, tab bar pinned to the bottom.
struct Screen<Content: View>: View {
    @Binding var tab: Tab
    var showsTabBar: Bool = true
    @ViewBuilder var content: Content

    var body: some View {
        ZStack {
            Tok.ink.ignoresSafeArea()
            VStack(spacing: 0) {
                content
                if showsTabBar {
                    RingTabBar(selection: $tab)
                }
            }
        }
        .foregroundStyle(Tok.text)
        .environment(\.colorScheme, .dark)
    }
}

// MARK: - Legend

/// `▪ Deep  ▪ REM  ▪ Light` — 8×8 square swatches, 10pt muted.
struct LegendRow: View {
    struct Item: Identifiable {
        let id = UUID()
        var color: Color?
        var label: String
    }
    var items: [Item]

    var body: some View {
        HStack(spacing: 16) {
            ForEach(items) { item in
                HStack(spacing: 5) {
                    if let color = item.color {
                        Rectangle().fill(color).frame(width: 8, height: 8)
                    }
                    Text(item.label).font(.mono(10))
                }
            }
            Spacer(minLength: 0)
        }
        .foregroundStyle(Tok.muted)
    }
}

// MARK: - Rows

/// A 52pt row with a hairline beneath it and an `inkRaised` press state.
struct SettingsRow<Trailing: View>: View {
    var title: String
    var subtitle: String? = nil
    var isButton: Bool = true
    @ViewBuilder var trailing: Trailing
    var action: () -> Void = {}

    var body: some View {
        VStack(spacing: 0) {
            Group {
                if isButton {
                    Button(action: action) { content }
                        .buttonStyle(RowPressStyle())
                } else {
                    content
                }
            }
            Hairline()
        }
    }

    private var content: some View {
        HStack {
            VStack(alignment: .leading, spacing: 3) {
                Text(title).font(.mono(12)).foregroundStyle(Tok.text)
                if let subtitle {
                    Text(subtitle).font(.mono(10)).foregroundStyle(Tok.muted)
                }
            }
            Spacer(minLength: 8)
            trailing
        }
        .frame(minHeight: Tok.settingsRowHeight)
        .contentShape(Rectangle())
    }
}

// MARK: - Badges

/// `BACKGROUND` / `LOCKED` / `UNASSIGNED`: a hairline-boxed 8pt label beside an action.
struct ActionBadge: View {
    enum Kind: Equatable {
        case background, locked, unassigned

        var title: String {
            switch self {
            case .background: return "Background"
            case .locked: return "Locked"
            case .unassigned: return "Unassigned"
            }
        }

        /// Spoken in place of the uppercase label.
        var accessibilityText: String {
            switch self {
            case .background: return "works in background"
            case .locked: return "locked"
            case .unassigned: return "unassigned"
            }
        }

        fileprivate var text: Color {
            switch self {
            case .background: return Tok.accentDeep
            case .locked: return Tok.muted
            case .unassigned: return Tok.dim
            }
        }

        fileprivate var rule: Color {
            switch self {
            case .background: return Tok.series3
            case .locked: return Tok.dim
            case .unassigned: return Tok.hairline
            }
        }
    }

    var kind: Kind

    var body: some View {
        Text(kind.title)
            .labelType(8, tracking: 0.1)
            .foregroundStyle(kind.text)
            .lineLimit(1)
            .fixedSize()
            .padding(.horizontal, 4)
            .padding(.vertical, 2)
            .overlay { Rectangle().strokeBorder(kind.rule, lineWidth: Tok.hairlineWidth) }
            .accessibilityLabel(kind.accessibilityText)
    }
}

// MARK: - Sheets

/// Sheet chrome: ink ground, a 34pt serif title with a Done button, a hairline,
/// then scrolling content. Medium and large detents like the Ring sheet.
struct SheetScaffold<Content: View>: View {
    var title: String
    var subtitle: String? = nil
    /// Hidden while dismissing would abandon work, such as a running capture.
    var showsDone = true
    /// Rendering tests turn scrolling off: `ImageRenderer` draws no scroll view contents.
    var scrolls = true
    @ViewBuilder var content: Content
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            Tok.ink.ignoresSafeArea()
            VStack(alignment: .leading, spacing: 0) {
                HStack(alignment: .firstTextBaseline) {
                    Text(title)
                        .font(.serif(34))
                        .lineLimit(2)
                        .minimumScaleFactor(0.7)
                        .accessibilityAddTraits(.isHeader)
                    Spacer(minLength: 12)
                    // Kept in the layout while hidden, so the header doesn't jump.
                    Button("Done") { dismiss() }
                        .font(.mono(11))
                        .foregroundStyle(Tok.accent)
                        .frame(minWidth: Tok.tapTarget, minHeight: Tok.tapTarget, alignment: .trailing)
                        .contentShape(Rectangle())
                        .buttonStyle(.plain)
                        .opacity(showsDone ? 1 : 0)
                        .disabled(!showsDone)
                        .accessibilityHidden(!showsDone)
                }
                .frame(minHeight: Tok.tapTarget)
                if let subtitle {
                    Text(subtitle)
                        .font(.mono(11))
                        .foregroundStyle(Tok.muted)
                        .padding(.bottom, 12)
                }
                Hairline()
                if scrolls {
                    ScrollView {
                        framed(content)
                    }
                    .scrollIndicators(.hidden)
                } else {
                    framed(content).fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: 0)
                }
            }
            .padding(.horizontal, Tok.side)
            .padding(.top, 14)
        }
        .foregroundStyle(Tok.text)
        .environment(\.colorScheme, .dark)
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
        .presentationBackground(Tok.ink)
    }

    private func framed(_ content: Content) -> some View {
        VStack(alignment: .leading, spacing: 0) { content }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.top, 16)
            .padding(.bottom, 28)
    }
}

// MARK: - Sharing

#if os(iOS)
/// The system share sheet for files.
struct ActivityView: UIViewControllerRepresentable {
    let items: [Any]

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }

    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {}
}
#endif
