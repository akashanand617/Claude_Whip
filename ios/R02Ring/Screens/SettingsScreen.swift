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
    @State private var showsModePicker = false
    @State private var pendingFirmware: BundledFirmware?

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
        .confirmationDialog("Firmware maintenance", isPresented: $showsModePicker, titleVisibility: .visible) {
            ForEach(model.firmwareOptions) { image in
                Button(optionLabel(image)) { pendingFirmware = image }
                    .disabled(!image.installEnabled)
            }
            if model.firmwareOptions.isEmpty {
                Button("No compatible firmware available") {}
                    .disabled(true)
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text(model.firmwareRoutingMessage)
        }
        .alert(item: $pendingFirmware) { image in
            Alert(
                title: Text("Install \(image.label)?"),
                message: Text(firmwareWarning(image)),
                primaryButton: .destructive(Text("Flash firmware")) {
                    Task { await model.switchFirmware(to: image) }
                },
                secondaryButton: .cancel()
            )
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

            SettingsRow(title: "Ring", subtitle: ringSubtitle) {
                Text(model.connectionLabel)
                    .labelType(10)
                    .foregroundStyle(model.ring.linked ? Tok.accent : Tok.muted)
            } action: { showsRing = true }

            SettingsRow(title: "Firmware maintenance", subtitle: modeSubtitle) {
                if model.isFirmwareSwitching {
                    ProgressView(value: model.firmwareProgress)
                        .tint(Tok.accent)
                        .frame(width: 72)
                } else {
                    Text("\(model.firmwareMode.title) ›")
                        .font(.mono(11)).foregroundStyle(Tok.muted)
                }
            } action: {
                guard !model.isFirmwareSwitching else { return }
                showsModePicker = true
            }

            SettingsRow(title: "Haptics", subtitle: "Confirms gesture actions while R02 is open",
                        isButton: false) {
                RingToggle(isOn: $model.haptics)
                    .accessibilityLabel("Haptics")
            }

            SettingsRow(title: "Heart-rate logging", subtitle: model.heartRateSettingsKnown
                        ? "Every \(model.heartRateIntervalMinutes) minutes" : "Settings not read", isButton: false) {
                RingToggle(isOn: Binding(
                    get: { model.heartRateLogging },
                    set: { enabled in Task { await model.setHeartRateLogging(enabled) } }
                ))
                .disabled(!model.healthSyncEnabled || !model.heartRateSettingsKnown)
                .opacity(model.healthSyncEnabled ? 1 : 0.45)
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

    private var modeSubtitle: String {
        if model.isFirmwareSwitching { return model.syncMessage }
        switch model.firmwareMode {
        case .health: return "Stock health tracking · gestures unavailable"
        case .unified: return "Health default · instant temporary Gesture sessions"
        case .gesture: return "25 Hz gestures · optical health paused"
        case .unknown: return "Connect to identify installed firmware"
        }
    }

    private func optionLabel(_ image: BundledFirmware) -> String {
        guard let reason = image.disabledReason else { return image.label }
        return "\(image.label) (\(reason))"
    }

    private func firmwareWarning(_ image: BundledFirmware) -> String {
        if image.targetVersion == FirmwareIdentity.rt12colUnifiedHIDV10Version {
            return "This installs experimental RT12COL V10 with Keyboard as the primary Bluetooth HID application, plus mouse wheel, swipes, media, volume and navigation. The app saves pending health history first. After reboot, forget the ring in iPhone Bluetooth settings and reconnect it so iOS replaces the cached V9 report map. Keyboard and Consumer controls do not need AssistiveTouch; mouse input may. V10 HID behavior and Health return are not yet physically validated."
        }
        if image.targetVersion == FirmwareIdentity.rt12colUnifiedHIDV9Version {
            return "V9 remains recognized when already installed, but is superseded as an install target because iOS classified its Keyboard usage as secondary. Upgrade to V10 or use the exact V8 rollback."
        }
        if image.targetVersion == FirmwareIdentity.rt12colUnifiedHIDVersion {
            return "This installs experimental RT12COL V8 with ring-sent Bluetooth HID swipes and controls. Swipes require AssistiveTouch. The app will save pending health history first. Keep the app open and the ring nearby; physical HID behavior and Health return are not yet validated."
        }
        switch image.mode {
        case .gesture:
            return "The app will sync pending health history first. Heart-rate and blood-oxygen tracking will stop while Gesture mode is active. Keep the app open and the ring nearby."
        case .health:
            return "This restores stock health tracking. Gesture recognition will be unavailable until you switch back. Keep the app open and the ring nearby."
        case .unified:
            return "This installs the experimental size-neutral Health-default image. Offline safety checks pass, but its RT12COL behavior is not yet validated on-ring. The app will save pending health history first; Gesture sessions then switch without another firmware transfer."
        case .unknown:
            return ""
        }
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
                if let duration = model.lastFirmwareSwitchDuration {
                    infoRow("Last mode switch", String(format: "%.1f s", duration))
                }
                if let duration = model.lastFirmwareTransferDuration {
                    infoRow("DFU transfer", String(format: "%.1f s", duration))
                }
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
