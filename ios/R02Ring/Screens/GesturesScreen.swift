import SwiftUI

/// Gestures (8a): a 2-up grid of 104pt cells on hairline gridlines, each previewing its
/// gesture as a live 3D hand.
struct GesturesScreen: View {
    @EnvironmentObject private var model: AppModel
    @Binding var tab: Tab

    private let columns = [GridItem(.flexible(), spacing: 0),
                           GridItem(.flexible(), spacing: 0)]

    var body: some View {
        Screen(tab: $tab) {
            VStack(spacing: 0) {
                ScreenHeader(title: "Gestures") {
                    BatteryPill(percent: model.ring.batteryPercent)
                }

                GestureSessionControl(coordinator: model.modes) { enabled in
                    await model.setGestureSession(enabled)
                }
                .padding(.horizontal, Tok.side)
                Text(model.gestureStatus).font(.mono(10)).foregroundStyle(Tok.muted)
                    .padding(.horizontal, Tok.side).padding(.vertical, 8)
                if let event = model.recentGestures.last {
                    Text("Detected: \(event.name) \(event.direction == "none" ? "" : event.direction)")
                        .font(.mono(11)).foregroundStyle(Tok.accent)
                }

                VStack(spacing: 0) {
                    Hairline()
                    ScrollView {
                        LazyVGrid(columns: columns, spacing: 0) {
                            ForEach(Array(GestureID.allCases.enumerated()), id: \.element.id) { i, id in
                                GestureCell(id: id,
                                            action: "Preview · actions disabled",
                                            showsRightRule: i.isMultiple(of: 2))
                            }
                        }
                    }
                }
                .padding(.top, 10)
                .frame(maxHeight: .infinity)

                HStack {
                    Spacer()
                    Text("Mappings are previews; no system actions run.")
                            .font(.mono(10))
                            .foregroundStyle(Tok.muted)
                }
                .padding(.horizontal, Tok.side)
                .padding(.top, 8)

                OutlineButton(title: "Health dashboard") { tab = .today }
                    .padding(.top, 8)
            }
        }
    }
}

private struct GestureSessionControl: View {
    @ObservedObject var coordinator: UnifiedModeCoordinator
    let change: (Bool) async -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            let gesture = coordinator.status?.mode == .gesture || coordinator.status?.mode == .enteringGesture
            Button(gesture ? "Return to Health" : "Start Gesture session") {
                Task { await change(!gesture) }
            }
            .font(.mono(13))
            .foregroundStyle(coordinator.available ? Tok.accent : Tok.muted)
            .frame(maxWidth: .infinity, minHeight: Tok.tapTarget, alignment: .leading)
            .buttonStyle(.plain)
            .disabled(!coordinator.available || coordinator.status?.mode == .returningHealth)
            Text(coordinator.available ? "Health returns when the session ends, data becomes stale, the app backgrounds, or the ring disconnects."
                 : "Runtime toggle is available only on the verified unified image. Firmware maintenance remains under Settings.")
                .font(.mono(10)).foregroundStyle(Tok.muted)
        }
    }
}

/// One 104pt cell: the animation, a disclosure chevron, the gesture id and its action.
private struct GestureCell: View {
    var id: GestureID
    var action: String
    /// Only the left column draws the vertical rule, so no stray line lands on the screen edge.
    var showsRightRule: Bool

    var body: some View {
        Button {} label: {
            VStack(alignment: .leading, spacing: 0) {
                HStack(alignment: .top) {
                    GestureTile(gesture: id)
                    Spacer(minLength: 0)
                    Text("›").font(.mono(11)).foregroundStyle(Tok.dim)
                }
                Spacer(minLength: 0)
                Text(id.rawValue).font(.mono(11))
                Text(action).font(.mono(10)).foregroundStyle(Tok.muted)
                    .padding(.top, 3)
            }
            .padding(.horizontal, 12)
            .padding(.top, 6)
            .padding(.bottom, 10)
            .frame(height: 104, alignment: .topLeading)
            .contentShape(Rectangle())
        }
        .buttonStyle(RowPressStyle())
        .overlay(alignment: .bottom) { Hairline() }
        .overlay(alignment: .trailing) {
            if showsRightRule {
                Rectangle().fill(Tok.hairline).frame(width: Tok.hairlineWidth)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(id.rawValue.replacingOccurrences(of: "_", with: " ")), \(action)")
        .accessibilityAddTraits(.isButton)
    }
}
