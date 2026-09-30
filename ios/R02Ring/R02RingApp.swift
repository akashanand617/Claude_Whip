import SwiftUI
import SwiftData
import Combine

@main
struct R02RingApp: App {
    private let runtime: AppRuntime

    init() {
        runtime = AppRuntime.shared
    }

    var body: some Scene {
        WindowGroup {
            RootView(model: runtime.model)
                .preferredColorScheme(.dark)   // the design is authored dark-first
                .modelContainer(runtime.container)
        }
    }
}

/// Three tabs; Today additionally pushes the metric detail screens.
struct RootView: View {
    @Environment(\.scenePhase) private var scenePhase
    @ObservedObject var model: AppModel
    @State private var path: [Metric] = []
    private let foregroundRefresh = Timer.publish(every: 300, on: .main, in: .common).autoconnect()

    var body: some View {
        Group {
            switch model.selectedTab {
            case .today:
                NavigationStack(path: $path) {
                    TodayScreen(tab: $model.selectedTab) { metric in
                        path.append(metric)
                    }
                    .navigationDestination(for: Metric.self) { metric in
                        MetricDetailScreen(metric: metric, tab: $model.selectedTab) {
                            path.removeLast()
                        }
                        .hideNavigationBar()
                    }
                }
                .hideNavigationBar()

            case .gestures:
                GesturesScreen(tab: $model.selectedTab)

            case .settings:
                SettingsScreen(tab: $model.selectedTab)
            }
        }
        .environmentObject(model)
        .background(Tok.ink)
        .ringOnboarding(manager: model.ringManager) {
            model.connectCandidate()
        }
        // Switching tabs from inside a pushed detail screen should not leave that
        // screen sitting on Today's stack when you come back.
        .onChange(of: model.selectedTab) { _, _ in
            if model.selectedTab != .today { path.removeAll() }
        }
        .onChange(of: scenePhase, initial: true) { _, phase in
            model.scenePhaseChanged(phase)
        }
        .onReceive(foregroundRefresh) { _ in
            guard scenePhase == .active else { return }
            model.automaticHealthSync()
        }
    }
}

extension View {
    /// The design has no system navigation bar anywhere — every header is drawn by hand.
    func hideNavigationBar() -> some View {
        #if os(iOS)
        return self.toolbar(.hidden, for: .navigationBar)
        #else
        return self
        #endif
    }
}
