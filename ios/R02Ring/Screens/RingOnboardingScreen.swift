import SwiftUI

struct RingOnboardingScreen: View {
    @ObservedObject var manager: RingManager
    var connect: () -> Void

    var body: some View {
        ZStack {
            Tok.ink.ignoresSafeArea()
            VStack(spacing: 22) {
                Spacer(minLength: 8)
                ringArtwork
                VStack(spacing: 8) {
                    Text(manager.candidate?.name ?? "Colmi R02")
                        .font(.serif(32))
                    Text(manager.state.label)
                        .font(.mono(11))
                        .foregroundStyle(Tok.muted)
                        .multilineTextAlignment(.center)
                }

                if manager.candidates.count > 1, manager.state == .discovered {
                    ringChoices
                        .padding(.horizontal, 28)
                }

                action
                    .padding(.horizontal, 28)
                Text(helpText)
                    .font(.mono(10))
                    .foregroundStyle(Tok.dim)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 30)
                Spacer(minLength: 8)
            }
            .padding(.vertical, 22)
        }
        .foregroundStyle(Tok.text)
    }

    private var ringChoices: some View {
        VStack(spacing: 0) {
            ForEach(manager.candidates) { ring in
                Button {
                    manager.selectCandidate(ring)
                } label: {
                    HStack(spacing: 12) {
                        Circle()
                            .fill(manager.candidate?.id == ring.id ? Tok.accent : Tok.dim)
                            .frame(width: 7, height: 7)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(ring.name).font(.mono(12))
                            Text(signalLabel(ring.rssi))
                                .font(.mono(9)).foregroundStyle(Tok.muted)
                        }
                        Spacer()
                        if manager.candidate?.id == ring.id {
                            Text("SELECTED").labelType(9).foregroundStyle(Tok.accent)
                        }
                    }
                    .frame(minHeight: 48)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                Hairline()
            }
        }
        .overlay { Rectangle().strokeBorder(Tok.hairline) }
    }

    private var ringArtwork: some View {
        ZStack {
            Circle()
                .fill(Tok.accent.opacity(0.08))
                .frame(width: 184, height: 184)
            Circle()
                .stroke(Tok.accentDeep, lineWidth: 22)
                .frame(width: 106, height: 106)
                .shadow(color: Tok.accent.opacity(0.28), radius: 24)
            Circle()
                .stroke(Tok.accent.opacity(0.7), lineWidth: 2)
                .frame(width: 87, height: 87)
        }
        .accessibilityHidden(true)
    }

    @ViewBuilder
    private var action: some View {
        switch manager.state {
        case .discovered:
            Button(action: connect) {
                Text("Connect \(selectedSuffix)")
                    .font(.mono(13, .medium))
                    .frame(maxWidth: .infinity, minHeight: 50)
                    .foregroundStyle(Tok.ink)
                    .background(Tok.accent)
            }
            .buttonStyle(.plain)
        case .scanning, .connecting, .discoveringServices:
            HStack(spacing: 12) {
                ProgressView().tint(Tok.accent)
                Text(manager.state.label).font(.mono(12))
            }
            .frame(maxWidth: .infinity, minHeight: 50)
            .overlay { Rectangle().strokeBorder(Tok.hairline) }
        case .ready, .recoveryReady:
            Button("Done") { manager.dismissOnboarding() }
                .font(.mono(13, .medium))
                .frame(maxWidth: .infinity, minHeight: 50)
                .foregroundStyle(Tok.ink)
                .background(Tok.accent)
        default:
            Button("Try again") { manager.scan() }
                .font(.mono(13))
                .frame(maxWidth: .infinity, minHeight: 50)
                .foregroundStyle(Tok.accent)
                .overlay { Rectangle().strokeBorder(Tok.accent) }
        }
    }

    private var selectedSuffix: String {
        guard let name = manager.candidate?.name else { return "R02" }
        return name.split(separator: "_").last.map(String.init) ?? name
    }

    private func signalLabel(_ rssi: Int) -> String {
        if rssi >= -60 { return "Very close" }
        if rssi >= -75 { return "Nearby" }
        return "Farther away"
    }

    private var helpText: String {
        switch manager.state {
        case .scanning: return "Keep the ring close. If it is asleep, place it on the charger for two seconds, then remove it."
        case .connecting, .discoveringServices: return "The R02 can take several seconds to expose all of its health services."
        case .bluetoothUnavailable: return "Enable Bluetooth and allow access for R02 Ring in Settings."
        case .recoveryReady: return "The ring is reachable through its recovery service, but its normal health connection is unavailable. No firmware is written automatically."
        case .disconnected: return "Make sure QRing is closed so it does not hold the ring's only connection."
        default: return manager.candidates.count > 1
            ? "Choose the suffix printed by your ring's Bluetooth name. This app remembers only that ring."
            : "One tap pairs this app with one stock-firmware R02. No account or cloud is required."
        }
    }
}

struct RingManagerSheetPresenter: ViewModifier {
    @ObservedObject var manager: RingManager
    var connect: () -> Void

    func body(content: Content) -> some View {
        content.sheet(isPresented: $manager.showsOnboarding, onDismiss: manager.cancelPairing) {
            RingOnboardingScreen(manager: manager, connect: connect)
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(manager.canDismissConnectionSheet ? .visible : .hidden)
                .interactiveDismissDisabled(!manager.canDismissConnectionSheet)
        }
    }
}

extension View {
    func ringOnboarding(manager: RingManager, connect: @escaping () -> Void) -> some View {
        modifier(RingManagerSheetPresenter(manager: manager, connect: connect))
    }
}
