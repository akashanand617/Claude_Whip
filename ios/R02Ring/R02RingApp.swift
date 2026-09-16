import SwiftUI

@main
struct R02RingApp: App {
    var body: some Scene {
        WindowGroup {
            RootView()
                .preferredColorScheme(.dark)   // the design is authored dark-first
        }
    }
}

/// Three tabs; Today additionally pushes the metric detail screens.
struct RootView: View {
    @StateObject private var model = AppModel()
    @State private var path: [Metric] = []

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
        // Switching tabs from inside a pushed detail screen should not leave that
        // screen sitting on Today's stack when you come back.
        .onChange(of: model.selectedTab) { _, _ in
            if model.selectedTab != .today { path.removeAll() }
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
