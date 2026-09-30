import SwiftUI
#if os(iOS)
import UIKit
#endif

/// Gestures (8a): the session panel, then a 2-up grid of 104pt cells on hairline
/// gridlines, each previewing its gesture as a live 3D hand beside its action.
struct GesturesScreen: View {
    @EnvironmentObject private var model: AppModel
    @Binding var tab: Tab
    @State private var sheet: GestureSheet?
    @State private var logs = GestureLogCount()
    @State private var confirmsLogDelete = false
    @State private var confirmsReset = false

    var body: some View {
        Screen(tab: $tab) {
            VStack(spacing: 0) {
                ScreenHeader(title: "Gestures") {
                    BatteryPill(percent: model.ring.batteryPercent)
                }

                ScrollView {
                    VStack(alignment: .leading, spacing: 0) {
                        GestureSessionPanel(coordinator: model.modes, ringManager: model.ringManager)
                            .padding(.horizontal, Tok.side)
                            .padding(.top, 14)

                        permissionRows
                            .padding(.horizontal, Tok.side)

                        sectionLabel("Mappings", detail: "Tap a gesture to change its action")
                            .padding(.top, 26)
                        GestureMappingGrid(mappings: model.gestureMappings) { sheet = .picker($0) }

                        toolRows
                            .padding(.horizontal, Tok.side)
                            .padding(.top, 26)

                        footnotes
                            .padding(.horizontal, Tok.side)
                            .padding(.top, 14)
                            .padding(.bottom, 20)
                    }
                }
                .scrollIndicators(.hidden)

                OutlineButton(title: "Health dashboard") { tab = .today }
                    .padding(.vertical, 8)
            }
        }
        .sheet(item: $sheet) { sheet in
            sheetContent(sheet)
                .environmentObject(model)
        }
        .onAppear { logs.refresh() }
        .onChange(of: model.lastDispatch?.id) { _, _ in logs.refresh() }
        .onChange(of: model.lastSessionSummary) { _, _ in logs.refresh() }
    }

    // MARK: Sheets

    @ViewBuilder
    private func sheetContent(_ sheet: GestureSheet) -> some View {
        switch sheet {
        case .picker(let gesture):
            GesturePickerHost(gesture: gesture)
        case .backTap:
            BackTapGuideSheet()
        case .ringControls:
            RingControlsGuideSheet()
        case .diagnostics:
            GestureDiagnosticsHost()
        case .share(let urls):
            #if os(iOS)
            ActivityView(items: urls)
            #else
            EmptyView()
            #endif
        }
    }

    // MARK: Permissions

    /// Only permissions a current mapping needs and that aren't granted yet.
    private var neededPermissions: [GesturePermission] {
        let required = model.gestureMappings.requiredPermissions
        return GesturePermission.allCases.filter { required.contains($0) && !state(of: $0).isAuthorized }
    }

    private func state(of permission: GesturePermission) -> PermissionState {
        switch permission {
        case .appleMusic: return model.musicAuthorization
        case .notifications: return model.notificationAuthorization
        }
    }

    @ViewBuilder
    private var permissionRows: some View {
        let needed = neededPermissions
        if !needed.isEmpty {
            VStack(spacing: 0) {
                Hairline()
                ForEach(needed) { permission in
                    permissionRow(permission)
                }
            }
            .padding(.top, 18)
        }
    }

    private func permissionRow(_ permission: GesturePermission) -> some View {
        let current = state(of: permission)
        var names: [String] = []
        for gesture in GestureID.allCases {
            let action = model.gestureMappings[gesture]
            if action.info.permission == permission, !names.contains(action.title) { names.append(action.title) }
        }
        let subtitle: String
        let trailing: String?
        switch current {
        case .notDetermined:
            subtitle = "Needed for \(names.joined(separator: ", "))"
            trailing = "Allow ›"
        case .denied:
            subtitle = "Turned off for R02 · \(names.joined(separator: ", ")) won't work"
            trailing = "Settings ›"
        case .restricted:
            subtitle = "Restricted on this iPhone"
            trailing = nil
        case .authorized:
            subtitle = ""
            trailing = nil
        }
        return SettingsRow(title: "\(permission.title) access", subtitle: subtitle, isButton: trailing != nil) {
            if let trailing {
                Text(trailing).font(.mono(11)).foregroundStyle(Tok.accent)
            }
        } action: {
            switch current {
            case .notDetermined: Task { await model.requestPermission(permission) }
            case .denied: openAppSettings()
            case .restricted, .authorized: break
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityHint(current == .denied ? "Opens R02 in the Settings app"
                           : current == .notDetermined ? "Asks for \(permission.title) access" : "")
    }

    private func openAppSettings() {
        #if os(iOS)
        if let url = URL(string: UIApplication.openSettingsURLString) {
            UIApplication.shared.open(url)
        }
        #endif
    }

    // MARK: Rows

    private var changedMappings: Int { model.gestureMappings.overrides.count }

    private var toolRows: some View {
        VStack(spacing: 0) {
            Hairline()

            SettingsRow(title: "Back Tap setup", subtitle: "Toggle gestures from any app") {
                chevron
            } action: { sheet = .backTap }
            .accessibilityHint("Shows how to set up Back Tap")

            SettingsRow(title: "Ring controls setup", subtitle: "Instagram Switch swipes, keyboard and wheel") {
                chevron
            } action: { sheet = .ringControls }
            .accessibilityHint("Shows setup for ring controls and the V10 wheel amount")

            SettingsRow(title: "Research event log", subtitle: logs.subtitle) {
                Text(logs.total > 0 ? "Share ›" : "Empty")
                    .font(.mono(11)).foregroundStyle(logs.total > 0 ? Tok.accent : Tok.dim)
            } action: {
                let urls = model.gestureEventLogFiles()
                logs.refresh()
                if !urls.isEmpty { sheet = .share(urls) }
            }
            .disabled(logs.total == 0)
            .accessibilityHint(logs.total > 0 ? "Shares the event and lifecycle logs" : "No logs yet")

            SettingsRow(title: "Delete event logs",
                        subtitle: logs.total > 0 ? "Removes them from this iPhone" : "Nothing to delete") {
                Text("Delete").font(.mono(11))
                    .foregroundStyle(logs.total > 0 ? Color.red.opacity(0.8) : Tok.dim)
            } action: { confirmsLogDelete = true }
            .disabled(logs.total == 0)
            .confirmationDialog("Delete gesture logs?", isPresented: $confirmsLogDelete, titleVisibility: .visible) {
                Button("Delete \(logs.total == 1 ? "1 file" : "\(logs.total) files")", role: .destructive) {
                    model.deleteGestureEventLogs()
                    logs.refresh()
                }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("Event and lifecycle logs are removed. A running session keeps its open log. Share them first if you need them for labeling.")
            }

            SettingsRow(title: "Reset all mappings",
                        subtitle: changedMappings == 0 ? "Every gesture uses its default"
                        : "\(changedMappings) changed from the defaults") {
                chevron
            } action: { confirmsReset = true }
            .disabled(changedMappings == 0)
            .opacity(changedMappings == 0 ? 0.45 : 1)
            .confirmationDialog("Reset all mappings?", isPresented: $confirmsReset, titleVisibility: .visible) {
                Button("Reset to defaults", role: .destructive) { model.resetAllMappings() }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("Every gesture goes back to its default action.")
            }

            SettingsRow(title: "Waveform diagnostics", subtitle: diagnosticsSubtitle) {
                chevron
            } action: { sheet = .diagnostics }
            .accessibilityHint("Opens the cross-ring waveform capture")
        }
    }

    private var diagnosticsSubtitle: String {
        if model.diagnosticRecording {
            return model.diagnosticProgress.isEmpty ? "Recording" : "Recording · \(model.diagnosticProgress)"
        }
        return model.gestureReady ? "Ready to record a waveform set" : "Needs a calibrated Gesture session"
    }

    private var chevron: some View {
        Text("›").font(.mono(11)).foregroundStyle(Tok.muted).accessibilityHidden(true)
    }

    private func sectionLabel(_ title: String, detail: String) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(title).labelType(10).foregroundStyle(Tok.muted)
                .accessibilityAddTraits(.isHeader)
            Spacer(minLength: 8)
            Text(detail).font(.mono(10)).foregroundStyle(Tok.dim)
        }
        .padding(.horizontal, Tok.side)
        .padding(.bottom, 8)
    }

    private var footnotes: some View {
        VStack(alignment: .leading, spacing: 8) {
            // Verbatim: a literal is Markdown, and the two `*` would italicize the text between them.
            Text(verbatim: "Every judged gesture is logged to Documents/GestureEvents/events_*.jsonl with the live engine's keys. Join labels with python -m probe.label join --labels … --events events_*.jsonl.")
            Text("Mouse swipes/wheel may need AssistiveTouch. V10 F5/F6 can drive an iOS Switch Control recipe for real Instagram swipes without the floating button; one-time setup is required.")
            Text("Charging is checked when a session starts or reconnects.")
        }
        .font(.mono(10))
        .foregroundStyle(Tok.dim)
        .fixedSize(horizontal: false, vertical: true)
    }
}

private enum GestureSheet: Identifiable {
    case picker(GestureID), backTap, ringControls, diagnostics, share([URL])

    var id: String {
        switch self {
        case .picker(let gesture): return "picker.\(gesture.rawValue)"
        case .backTap: return "backTap"
        case .ringControls: return "ringControls"
        case .diagnostics: return "diagnostics"
        case .share: return "share"
        }
    }
}

/// File counts for the log rows, read without flushing the open journal.
private struct GestureLogCount {
    var events = 0
    var journals = 0
    var total: Int { events + journals }

    mutating func refresh() {
        events = GestureEventLog.files().count
        journals = GestureSessionJournal.files().count
    }

    var subtitle: String {
        guard total > 0 else { return "No logs yet · a session starts one" }
        let e = events == 1 ? "1 event file" : "\(events) event files"
        let j = journals == 1 ? "1 lifecycle file" : "\(journals) lifecycle files"
        return "\(e) · \(j)"
    }
}

// MARK: - Sheet hosts

/// Observes the model so the picker reflects permission changes while open.
private struct GesturePickerHost: View {
    @EnvironmentObject private var model: AppModel
    var gesture: GestureID

    var body: some View {
        GestureActionPickerSheet(
            gesture: gesture,
            current: model.gestureMappings[gesture],
            permissions: [.appleMusic: model.musicAuthorization,
                          .notifications: model.notificationAuthorization],
            availableHIDVersion: model.ringHIDVersion,
            choose: { action in
                model.setMapping(action, for: gesture)
                guard let permission = action.info.permission else { return }
                let state = permission == .appleMusic ? model.musicAuthorization : model.notificationAuthorization
                if state == .notDetermined { Task { await model.requestPermission(permission) } }
            },
            restoreDefault: { model.resetMapping(gesture) }
        )
    }
}

private struct GestureDiagnosticsHost: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        GestureDiagnosticsSheet(
            ready: model.gestureReady,
            recording: model.diagnosticRecording,
            prompt: model.diagnosticPrompt,
            progress: model.diagnosticProgress,
            captureName: model.diagnosticCaptureName,
            start: { model.startGestureDiagnosticWorkflow() },
            cancel: { model.cancelGestureDiagnosticWorkflow() }
        )
    }
}

// MARK: - Session panel

/// What the Start/Return button offers. Pure, so it is unit-tested.
enum GestureSessionButton: Equatable {
    /// Health, mode control available.
    case start
    /// A start (from R02 or a Shortcut) is waiting for the ring; tapping
    /// withdraws it, since a stop request cancels waiting starts.
    case waiting
    /// Entering Gesture; tapping cancels, since a stop during entry is honored.
    case starting
    case stop
    case stopping
    /// Mode control is being attached or recovered, or the ring is being identified.
    case preparing
    case unavailable
    /// The session is still on and re-entering Gesture (a heal); tapping
    /// turns gestures off.
    case reconnecting

    /// `requesting`: any start is pending (the model's or this panel's own).
    /// `attachInFlight`: mode control is being attached, recovered or identified.
    /// `healing`: a desired session is reconnecting; it wins over the heal's
    /// own stop and entry transitions.
    init(mode: RingRuntimeMode?, available: Bool, transition: GestureTransition?,
         requesting: Bool, attachInFlight: Bool, healing: Bool = false) {
        if healing { self = .reconnecting }
        else if transition == .leaving || mode == .returningHealth { self = .stopping }
        else if transition == .entering || mode == .enteringGesture { self = .starting }
        else if mode == .gesture { self = .stop }
        else if requesting { self = .waiting }
        else if !available { self = attachInFlight ? .preparing : .unavailable }
        else { self = mode == .health ? .start : .unavailable }
    }

    var title: String {
        switch self {
        case .start, .unavailable: return "Start Gesture session"
        case .waiting, .starting: return "Cancel start"
        case .stop, .reconnecting: return "Return to Health"
        case .stopping: return "Returning to Health…"
        case .preparing: return "Preparing gesture control…"
        }
    }

    var isEnabled: Bool { [.start, .waiting, .starting, .stop, .reconnecting].contains(self) }
    var showsProgress: Bool { [.waiting, .starting, .stopping, .preparing, .reconnecting].contains(self) }
    /// A tap asks for Gesture; otherwise it asks for Health.
    var requestsGesture: Bool { self == .start }

    var hint: String {
        switch self {
        case .start: return "Streams motion from the ring and turns on gesture actions"
        case .waiting, .starting: return "Cancels the start and keeps the ring in Health"
        case .stop: return "Ends the session and returns the ring to Health"
        case .reconnecting: return "Gestures are reconnecting; tap to return to Health"
        case .stopping, .preparing: return "Please wait"
        case .unavailable: return "Needs the unified firmware and a connected ring"
        }
    }
}

/// Reads the model, coordinator and link, and owns the panel's own request.
private struct GestureSessionPanel: View {
    @EnvironmentObject private var model: AppModel
    @ObservedObject var coordinator: UnifiedModeCoordinator
    /// Observed so link changes (connecting, ready) refresh the status line.
    @ObservedObject var ringManager: RingManager
    @State private var requesting = false

    var body: some View {
        let mode = coordinator.status?.mode
        let snapshot = model.gestureModeSnapshot
        let button = GestureSessionButton(
            mode: mode, available: coordinator.available, transition: model.gestureTransition,
            requesting: requesting || model.gestureStartPending,
            attachInFlight: model.modeAttachInFlight || (snapshot.link == .ready && !snapshot.connectionSetupComplete),
            healing: model.gestureHealing != nil
        )
        GestureSessionPanelView(
            button: button,
            mode: mode,
            linked: model.ring.linked,
            status: GestureSessionPanelView.statusLine(button: button, snapshot: snapshot,
                                                       gestureStatus: model.gestureStatus),
            requestMessage: model.panelRequestMessage ?? model.intentStartMessage,
            lastDispatch: model.lastDispatch?.summary,
            lastSession: model.lastSessionSummary,
            charging: coordinator.status?.charging ?? model.ring.charging,
            autoReturn: $model.gestureAutoReturn,
            idlePause: $model.gestureIdlePause,
            keepInBackground: $model.keepGesturesInBackground,
            tap: request,
            healing: model.gestureHealing != nil
        )
        .onChange(of: mode) { _, next in
            // The model already clears both messages whenever the ring reaches
            // Gesture, including while this panel was off screen or in the
            // background. A failed entry passes through the entering mode and
            // returns to Health, so only `.gesture` makes a failure moot.
            guard next == .gesture else { return }
            model.clearPanelRequestMessage()
            model.clearIntentStartMessage()
        }
        // The tap's own message lasts for this visit; a continuation failure
        // stays until it is seen, a new tap, or a session.
        .onDisappear { model.clearPanelRequestMessage() }
    }

    private func request(_ state: GestureSessionButton) {
        let enable = state.requestsGesture
        model.panelRequestBegan()
        if enable { requesting = true }
        Task {
            let outcome = await model.requestGestureSession(enable, source: .app)
            if enable { requesting = false }
            model.panelRequestFinished(outcome)
        }
    }
}

/// The session panel from plain values and bindings: mode, the Start/Return
/// button, status lines, the two timers and the background setting.
struct GestureSessionPanelView: View {
    var button: GestureSessionButton
    var mode: RingRuntimeMode?
    var linked: Bool
    var status: String
    var requestMessage: String?
    var lastDispatch: String?
    var lastSession: String?
    var charging: Bool
    @Binding var autoReturn: GestureAutoReturn
    @Binding var idlePause: GestureIdlePause
    @Binding var keepInBackground: Bool
    var tap: (GestureSessionButton) -> Void
    /// A desired session is reconnecting (heal).
    var healing = false

    /// The line under the button: the actual reason Start is unavailable, what
    /// a waiting start waits for, or the session status.
    static func statusLine(button: GestureSessionButton, snapshot: GestureModeSnapshot,
                           gestureStatus: String) -> String {
        switch button {
        case .unavailable: return snapshot.unavailableReason
        case .waiting: return GestureStartReadiness.evaluate(snapshot).waitingNote
        default: return gestureStatus
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 7) {
                Text("Session").labelType(10).foregroundStyle(Tok.muted)
                Spacer(minLength: 8)
                Circle()
                    .fill(modeIsGesture ? Tok.accent : Tok.dim)
                    .frame(width: 6, height: 6)
                Text(modeLabel).labelType(10).foregroundStyle(modeIsGesture ? Tok.accent : Tok.muted)
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("Session, ring mode \(modeLabel)")
            .accessibilityAddTraits(.isHeader)

            sessionButton.padding(.top, 12)

            VStack(alignment: .leading, spacing: 6) {
                if let requestMessage {
                    Text(requestMessage).font(.mono(11)).foregroundStyle(Tok.text)
                }
                Text(status)
                    .font(.mono(10)).foregroundStyle(Tok.muted)
                if let lastDispatch {
                    Text(lastDispatch)
                        .font(.mono(11)).foregroundStyle(Tok.accent)
                        .accessibilityLabel("Last gesture: \(lastDispatch)")
                }
                if let lastSession {
                    Text(lastSession).font(.mono(10)).foregroundStyle(Tok.dim)
                }
                if charging {
                    Text("On the charger · take the ring off its charger before starting. Charging is checked when a session starts or reconnects.")
                        .font(.mono(10)).foregroundStyle(Tok.muted)
                }
            }
            .fixedSize(horizontal: false, vertical: true)
            .padding(.top, 10)

            VStack(spacing: 0) {
                Hairline()
                SettingsRow(title: "Session timer", subtitle: autoReturn == .off
                            ? "No fixed limit" : "Returns to Health after this long", isButton: false) {
                    OptionMenu(label: "Session timer", selection: $autoReturn,
                               options: GestureAutoReturn.allCases, title: \.title)
                }
                SettingsRow(title: "Pause when idle", subtitle: idlePause == .off
                            ? "Never pauses for inactivity" : "After this long without a gesture", isButton: false) {
                    OptionMenu(label: "Pause when idle", selection: $idlePause,
                               options: GestureIdlePause.allCases, title: \.title)
                }
                SettingsRow(title: "Keep gestures active in background", subtitle: "Gestures work in other apps",
                            isButton: false) {
                    RingToggle(isOn: $keepInBackground)
                        .accessibilityLabel("Keep gestures active in background")
                }
            }
            .padding(.top, 16)

            Text(keepInBackground
                 ? "On: gestures stay on in other apps and on the lock screen until you stop them (Return, Back Tap, Pause Gestures or a pause gesture), a timer, the charger, or the ring stays out of range for a minute. Brief dropouts reconnect by themselves. Meanwhile the ring streams at 25 Hz and can't deep-sleep."
                 : "Off: leaving R02 returns the ring to Health.")
                .font(.mono(10)).foregroundStyle(Tok.muted)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, 10)
        }
    }

    private var modeIsGesture: Bool { healing || mode == .gesture || mode == .enteringGesture }

    private var modeLabel: String {
        if healing { return "Reconnecting" }
        switch mode {
        case .gesture: return "Gesture"
        case .enteringGesture: return "Entering gesture"
        case .returningHealth: return "Returning"
        case .health: return "Health"
        case .fault: return "Fault"
        case .unknown, nil: return linked ? "No mode control" : "Not connected"
        }
    }

    private var sessionButton: some View {
        let state = button
        let filled = state == .start
        return Button { tap(state) } label: {
            HStack(spacing: 10) {
                if state.showsProgress {
                    ProgressView().controlSize(.small).tint(Tok.accent)
                }
                Text(state.title).font(.mono(13, .medium))
            }
            .foregroundStyle(filled ? Tok.ink : state.isEnabled ? Tok.accent : Tok.dim)
            .frame(maxWidth: .infinity, minHeight: 50)
            .background(filled ? Tok.accent : Color.clear)
            .overlay { Rectangle().strokeBorder(state.isEnabled ? Tok.accent : Tok.hairline,
                                                lineWidth: Tok.hairlineWidth) }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(!state.isEnabled)
        .accessibilityLabel(state.title)
        .accessibilityHint(state.hint)
    }
}

/// A trailing `15 minutes ›` that opens a menu of options.
private struct OptionMenu<Option: Hashable & Identifiable>: View {
    var label: String
    @Binding var selection: Option
    var options: [Option]
    var title: KeyPath<Option, String>

    var body: some View {
        Menu {
            Picker(label, selection: $selection) {
                ForEach(options) { option in
                    Text(option[keyPath: title]).tag(option)
                }
            }
        } label: {
            Text("\(selection[keyPath: title]) ›")
                .font(.mono(11))
                .foregroundStyle(Tok.accent)
                .frame(minWidth: Tok.tapTarget, minHeight: Tok.tapTarget, alignment: .trailing)
                .contentShape(Rectangle())
        }
        .accessibilityLabel(label)
        .accessibilityValue(selection[keyPath: title])
    }
}

// MARK: - Grid

/// The eleven gesture cells, 2-up. Plain values in, so tests render it without a model.
struct GestureMappingGrid: View {
    var mappings: GestureMappings
    var select: (GestureID) -> Void

    private let columns = [GridItem(.flexible(), spacing: 0),
                           GridItem(.flexible(), spacing: 0)]

    var body: some View {
        VStack(spacing: 0) {
            Hairline()
            LazyVGrid(columns: columns, spacing: 0) {
                ForEach(Array(GestureID.allCases.enumerated()), id: \.element.id) { i, id in
                    GestureCell(id: id, action: mappings[id], showsRightRule: i.isMultiple(of: 2)) {
                        select(id)
                    }
                }
            }
        }
    }
}

/// One 104pt cell: the animation, a disclosure chevron, the gesture id, its action and badge.
struct GestureCell: View {
    var id: GestureID
    var action: GestureActionID
    /// Only the left column draws the vertical rule, so no stray line lands on the screen edge.
    var showsRightRule: Bool
    var select: () -> Void = {}

    var body: some View {
        Button(action: select) {
            VStack(alignment: .leading, spacing: 0) {
                HStack(alignment: .top) {
                    GestureTile(gesture: id)
                    Spacer(minLength: 0)
                    Text("›").font(.mono(11)).foregroundStyle(Tok.dim)
                }
                Spacer(minLength: 0)
                Text(id.rawValue).font(.mono(11))
                HStack(alignment: .center, spacing: 6) {
                    Text(action.title)
                        .font(.mono(10))
                        .foregroundStyle(action == .none ? Tok.dim : Tok.muted)
                        .lineLimit(1)
                        .minimumScaleFactor(0.8)
                    Spacer(minLength: 0)
                    if let kind = ActionBadge.Kind(action: action) {
                        ActionBadge(kind: kind)
                    }
                }
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
        .accessibilityLabel("\(id.title), \(action.spokenSummary)")
        .accessibilityHint("Choose the action for this gesture")
        .accessibilityAddTraits(.isButton)
    }
}
