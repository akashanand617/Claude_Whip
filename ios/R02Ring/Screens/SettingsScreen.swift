import SwiftUI

/// Settings (9a): the user tag, the ring it's paired to, and the few switches that matter.
struct SettingsScreen: View {
    @EnvironmentObject private var model: AppModel
    @Binding var tab: Tab

    var body: some View {
        Screen(tab: $tab) {
            VStack(spacing: 0) {
                ScreenHeader(title: "Settings") {
                    BatteryPill(percent: model.ring.batteryPercent)
                }

                userTag
                    .padding(.horizontal, Tok.side)
                    .padding(.top, 30)

                rows
                    .padding(.horizontal, Tok.side)
                    .padding(.top, 26)

                Spacer(minLength: 0)

                VStack(alignment: .leading, spacing: 10) {
                    Button {} label: {
                        Text("Sign out").font(.mono(11)).foregroundStyle(Tok.muted)
                    }
                    .buttonStyle(.plain)
                    Text(model.appVersion).font(.mono(10)).foregroundStyle(Tok.dim)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, Tok.side)
                .padding(.bottom, 8)
                .padding(.top, 16)
            }
        }
    }

    private var userTag: some View {
        HStack(spacing: 14) {
            Text(model.user.initials)
                .font(.mono(15))
                .tracking(15 * 0.04)
                .foregroundStyle(Tok.accent)
                .frame(width: 52, height: 52)
                .overlay { Circle().strokeBorder(Tok.dim, lineWidth: Tok.hairlineWidth) }

            VStack(alignment: .leading, spacing: 4) {
                Text(model.user.name).font(.mono(14))
                Text(model.user.email)
                    .font(.mono(11))
                    .foregroundStyle(Tok.muted)
                    .lineLimit(1)
                    .truncationMode(.tail)
            }
            Spacer(minLength: 0)
        }
        .accessibilityElement(children: .combine)
    }

    private var rows: some View {
        VStack(spacing: 0) {
            Hairline()

            SettingsRow(title: "Ring", subtitle: "\(model.ring.id) · firmware \(model.ring.firmware)") {
                Text(model.ring.linked ? "Linked" : "Not linked")
                    .labelType(10)
                    .foregroundStyle(model.ring.linked ? Tok.accent : Tok.muted)
            }

            SettingsRow(title: "Gestures") {
                Text("\(model.mappedCount) mapped ›")
                    .font(.mono(11)).foregroundStyle(Tok.muted)
            } action: {
                tab = .gestures
            }

            SettingsRow(title: "Haptics", isButton: false) {
                RingToggle(isOn: $model.haptics)
            }

            SettingsRow(title: "Continuous PPG", isButton: false) {
                RingToggle(isOn: $model.continuousPPG)
            }

            SettingsRow(title: "Units") {
                Text("\(model.units.rawValue) ›")
                    .font(.mono(11)).foregroundStyle(Tok.muted)
            } action: {
                model.units = model.units == .metric ? .imperial : .metric
            }

            SettingsRow(title: "Export data") {
                Text("›").font(.mono(11)).foregroundStyle(Tok.muted)
            }
        }
    }
}

/// A 52pt row with a hairline beneath it and an `inkRaised` press state.
private struct SettingsRow<Trailing: View>: View {
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
