import SwiftUI

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
    var percent: Int

    var body: some View {
        HStack(spacing: 6) {
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 2)
                        .strokeBorder(Tok.dim, lineWidth: Tok.hairlineWidth)
                    // Fill sits inside the 1pt outline, so it measures against the inner track.
                    Tok.accent
                        .frame(width: max(0, (geo.size.width - 2) * Double(percent) / 100),
                               height: max(0, geo.size.height - 2))
                        .offset(x: 1)
                }
            }
            .frame(width: 22, height: 10)

            Text("\(percent)%")
                .labelType()
                .foregroundStyle(Tok.text)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Ring battery \(percent) percent")
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

/// The restyled switch: 40×22 track, 18pt knob.
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
            .contentShape(Rectangle())
            .onTapGesture {
                withAnimation(.easeOut(duration: 0.18)) { isOn.toggle() }
            }
            .accessibilityElement()
            .accessibilityAddTraits(.isButton)
            .accessibilityValue(isOn ? "On" : "Off")
    }
}

/// The wide outlined action at the foot of Today and Gestures.
struct OutlineButton: View {
    var title: String
    var action: () -> Void = {}

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.mono(13))
                .tracking(13 * 0.14)
                .textCase(.uppercase)
                .foregroundStyle(Tok.accent)
                .frame(maxWidth: .infinity)
                .frame(minHeight: 48)
                .overlay {
                    Rectangle().strokeBorder(Tok.accent, lineWidth: Tok.hairlineWidth)
                }
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
                ForEach(Tab.allCases) { tab in
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
