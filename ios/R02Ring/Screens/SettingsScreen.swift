import SwiftUI
#if os(iOS)
import UIKit
#endif

/// Settings (9a): the user tag, the ring it's paired to, and the few switches that matter.
struct SettingsScreen: View {
    @EnvironmentObject private var model: AppModel
    @Binding var tab: Tab
    @State private var showsRing = false
    @State private var exportURLs: [URL] = []
    @State private var showsExport = false

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
        .sheet(isPresented: $showsRing) { ringSheet }
        #if os(iOS)
        .sheet(isPresented: $showsExport) { ActivityView(items: exportURLs) }
        #endif
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

            SettingsRow(title: "Ring", subtitle: ringSubtitle) {
                Text(model.connectionLabel)
                    .labelType(10)
                    .foregroundStyle(model.ring.linked ? Tok.accent : Tok.muted)
            } action: { showsRing = true }

            SettingsRow(title: "Haptics", isButton: false) {
                RingToggle(isOn: $model.haptics)
            }

            SettingsRow(title: "Heart-rate logging", subtitle: "Every 5 minutes", isButton: false) {
                RingToggle(isOn: Binding(
                    get: { model.heartRateLogging },
                    set: { enabled in Task { await model.setHeartRateLogging(enabled) } }
                ))
            }

            SettingsRow(title: "Units") {
                Text("\(model.units.rawValue) ›")
                    .font(.mono(11)).foregroundStyle(Tok.muted)
            } action: {
                model.units = model.units == .metric ? .imperial : .metric
            }

            SettingsRow(title: "Export data") {
                Text("›").font(.mono(11)).foregroundStyle(Tok.muted)
            } action: {
                do {
                    exportURLs = try model.exportFiles()
                    showsExport = !exportURLs.isEmpty
                } catch {
                    model.syncMessage = error.localizedDescription
                }
            }
        }
    }

    private var ringSubtitle: String {
        guard model.ringManager.pairedIdentifier != nil else { return "No R02 paired" }
        return "\(model.ring.id) · firmware \(model.ring.firmware)"
    }

    private var ringSheet: some View {
        ZStack {
            Tok.ink.ignoresSafeArea()
            VStack(alignment: .leading, spacing: 18) {
                HStack {
                    Text("Ring").font(.serif(34))
                    Spacer()
                    BatteryPill(percent: model.ring.batteryPercent)
                }
                Hairline()
                infoRow("Status", model.connectionLabel)
                infoRow("Device", model.ring.id)
                infoRow("Hardware", model.ring.hardware)
                infoRow("Firmware", model.ring.firmware)
                infoRow("Last sync", model.syncMessage)
                Spacer()
                if model.ringManager.pairedIdentifier == nil {
                    OutlineButton(title: "Add R02") {
                        showsRing = false
                        model.beginPairing()
                    }
                } else {
                    Button("Forget ring") {
                        showsRing = false
                        model.forgetRing()
                    }
                    .font(.mono(11))
                    .foregroundStyle(.red.opacity(0.8))
                    .frame(maxWidth: .infinity, minHeight: 44)
                }
            }
            .padding(Tok.side)
        }
        .foregroundStyle(Tok.text)
        .presentationDetents([.medium, .large])
    }

    private func infoRow(_ label: String, _ value: String) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(label).labelType(10).foregroundStyle(Tok.muted)
            Spacer()
            Text(value).font(.mono(11)).multilineTextAlignment(.trailing)
        }
    }
}

#if os(iOS)
private struct ActivityView: UIViewControllerRepresentable {
    let items: [Any]

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }

    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {}
}
#endif

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
