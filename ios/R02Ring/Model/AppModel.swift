import SwiftUI

// MARK: - Navigation

enum Tab: String, CaseIterable, Identifiable {
    case today, gestures, settings
    var id: String { rawValue }
    var title: String {
        switch self {
        case .today:    return "Today"
        case .gestures: return "Gestures"
        case .settings: return "Settings"
        }
    }
}

enum Metric: String, Hashable, Identifiable, CaseIterable {
    case sleep, heartRate, steps
    var id: String { rawValue }

    /// Uppercased by the label style; stored in sentence case so it reads in code.
    var title: String {
        switch self {
        case .sleep:     return "Sleep"
        case .heartRate: return "Heart rate"
        case .steps:     return "Steps"
        }
    }

    /// The range each detail screen opens on, per the design (10a W, 10b M, 10c 6M).
    var defaultRange: MetricRange {
        switch self {
        case .sleep:     return .week
        case .heartRate: return .month
        case .steps:     return .sixMonths
        }
    }
}

enum MetricRange: String, CaseIterable, Identifiable {
    case week, month, sixMonths, year
    var id: String { rawValue }
    var label: String {
        switch self {
        case .week:      return "W"
        case .month:     return "M"
        case .sixMonths: return "6M"
        case .year:      return "Y"
        }
    }
}

enum Units: String, CaseIterable {
    case metric = "Metric", imperial = "Imperial"
}

// MARK: - Gestures

enum GestureID: String, CaseIterable, Identifiable {
    case flick_up, flick_down, flick_left, flick_right
    case double_flick_up, double_flick_down, double_flick_left, double_flick_right
    case snap, double_snap
    case clap, double_clap
    case wave

    var id: String { rawValue }
}

/// The phone-side action a gesture is mapped to.
struct GestureAction: Hashable {
    var name: String
}

// MARK: - Device & user

struct RingDevice {
    var id = "R02_341C"
    var firmware = "4.2.1"
    var batteryPercent = 72
    var linked = true
}

struct User {
    var name = "Maya Kestrel"
    var email = "maya.kestrel@hey.com"
    var initials = "MK"
}

// MARK: - App state

@MainActor
final class AppModel: ObservableObject {
    @Published var selectedTab: Tab = .today
    @Published var selectedMetric: Metric?

    @Published var haptics = true
    @Published var continuousPPG = false
    @Published var units: Units = .metric

    @Published var ring = RingDevice()
    @Published var user = User()

    @Published var gestureMappings: [GestureID: GestureAction] = [
        .flick_up:            .init(name: "Volume up"),
        .flick_down:          .init(name: "Volume down"),
        .flick_left:          .init(name: "Previous track"),
        .flick_right:         .init(name: "Next track"),
        .double_flick_up:     .init(name: "Brightness up"),
        .double_flick_down:   .init(name: "Brightness down"),
        .double_flick_left:   .init(name: "Previous slide"),
        .double_flick_right:  .init(name: "Next slide"),
        .snap:                .init(name: "Play / pause"),
        .double_snap:         .init(name: "Run shortcut · Lights"),
        .clap:                .init(name: "Camera shutter"),
        .double_clap:         .init(name: "Toggle lights"),
        .wave:                .init(name: "Dismiss alert"),
    ]

    var mappedCount: Int { gestureMappings.count }

    let appVersion = "R02 · 2.8.0 (1149)"
}
