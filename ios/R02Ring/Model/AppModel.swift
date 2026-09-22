import SwiftUI
import SwiftData

// MARK: - Navigation

enum Tab: String, CaseIterable, Identifiable {
    case today, gestures, settings
    var id: String { rawValue }
    static let healthTabs: [Tab] = [.today, .settings]
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

    /// Health details open on a day-by-day week. Longer ranges remain available
    /// from the range picker and intentionally aggregate to keep their charts legible.
    var defaultRange: MetricRange {
        switch self {
        case .sleep:     return .week
        case .heartRate: return .week
        case .steps:     return .week
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
    case snap
    case double_clap
    case wave

    var id: String { rawValue }
}

/// The phone-side action a gesture is mapped to.
struct GestureAction: Hashable {
    var name: String
}

// MARK: - Device & user

struct RingDevice {
    var id = "No ring"
    var firmware = "—"
    var hardware = "—"
    var batteryPercent: Int?
    var charging = false
    var linked = false
    var lastSync: Date?
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
    @Published var heartRateLogging = true
    @Published var units: Units = .metric

    @Published var ring = RingDevice()
    @Published var user = User()
    @Published var today = HealthData.emptyToday()
    @Published var isSyncing = false
    @Published var isMeasuringHeartRate = false
    @Published var liveHeartRate: Int?
    @Published var syncMessage = "Not synced"
    @Published private(set) var dataRevision = 0

    let ringManager = RingManager()
    private var healthStore: HealthStore?
    private var ringClient: ColmiR02Client?
    private var syncService: HealthSyncService?
    private var measurementTask: Task<Void, Never>?
    private var started = false
    private let lastSyncKeyPrefix = "lastHealthSync."

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
        .double_clap:         .init(name: "Toggle lights"),
        .wave:                .init(name: "Dismiss alert"),
    ]

    var mappedCount: Int { gestureMappings.count }

    let appVersion = "R02 · 2.8.0 (1149)"

    func start(modelContext: ModelContext) {
        guard !started else { return }
        started = true
        let store = HealthStore(context: modelContext)
        let client = ColmiR02Client(manager: ringManager)
        healthStore = store
        ringClient = client
        syncService = HealthSyncService(client: client, store: store)
        ringManager.onReady = { [weak self] in
            guard let self, let deviceID = self.ringManager.connectedIdentifier else { return }
            self.ring.lastSync = UserDefaults.standard.object(
                forKey: self.lastSyncKeyPrefix + deviceID
            ) as? Date
            Task { @MainActor in await self.sync(full: self.ring.lastSync == nil) }
        }
        ringManager.onDisconnect = { [weak self] in
            self?.ring.linked = false
            self?.syncMessage = "Waiting for ring"
        }
        refreshFromStore()
        ringManager.begin()
    }

    func connectCandidate() {
        ringManager.connectCandidate()
    }

    func beginPairing() {
        ringManager.scan()
    }

    func sync(full: Bool = false) async {
        guard !isSyncing, let syncService, let deviceID = ringManager.connectedIdentifier else {
            if !ringManager.isReady { ringManager.scan() }
            return
        }
        isSyncing = true
        syncMessage = "Syncing…"
        ring.linked = true
        ring.id = ringManager.connectedName ?? ringManager.candidate?.name ?? "Colmi R02"
        ring.firmware = ringManager.firmware ?? ring.firmware
        ring.hardware = ringManager.hardware ?? ring.hardware
        let result = await syncService.sync(deviceID: deviceID, full: full) { [weak self] message, battery in
            guard let self else { return }
            self.syncMessage = message
            if let battery {
                self.ring.batteryPercent = battery.percent
                self.ring.charging = battery.charging
            }
            self.refreshFromStore()
        }
        if let battery = result.battery {
            ring.batteryPercent = battery.percent
            ring.charging = battery.charging
        }
        ring.firmware = ringManager.firmware ?? ring.firmware
        ring.hardware = ringManager.hardware ?? ring.hardware
        ring.lastSync = .now
        UserDefaults.standard.set(ring.lastSync, forKey: lastSyncKeyPrefix + deviceID)
        isSyncing = false
        syncMessage = result.errorSummary ?? "Synced just now"
        ringManager.showsOnboarding = false
        refreshFromStore()
    }

    func series(for metric: Metric, range: MetricRange) -> MetricSeries {
        _ = dataRevision
        return healthStore?.series(deviceID: activeDeviceID, metric: metric, range: range)
            ?? .empty(for: metric)
    }

    func setHeartRateLogging(_ enabled: Bool) async {
        guard let ringClient, ringManager.isReady else {
            syncMessage = "Connect the ring first"
            return
        }
        do {
            try await ringClient.setHeartRateLogging(enabled: enabled, intervalMinutes: 5)
            heartRateLogging = enabled
        } catch {
            syncMessage = error.localizedDescription
        }
    }

    func measureHeartRate() {
        guard !isMeasuringHeartRate, let ringClient, let store = healthStore,
              let deviceID = activeDeviceID else { return }
        measurementTask?.cancel()
        isMeasuringHeartRate = true
        liveHeartRate = nil
        syncMessage = "Measuring live heart rate…"
        measurementTask = Task { [weak self] in
            do {
                let bpm = try await ringClient.measureHeartRate { reading in
                    self?.liveHeartRate = reading
                }
                try store.saveLiveHeartRate(deviceID: deviceID, timestamp: .now, bpm: bpm)
                self?.liveHeartRate = bpm
                self?.syncMessage = "Heart rate saved"
                self?.refreshFromStore()
            } catch is CancellationError {
                // Leaving the screen intentionally stops the optical sensor.
            } catch RingProtocolError.timeout {
                self?.syncMessage = "No heart-rate reading · adjust the ring and try again"
            } catch {
                self?.syncMessage = error.localizedDescription
            }
            self?.isMeasuringHeartRate = false
            self?.measurementTask = nil
        }
    }

    func stopHeartRateMeasurement() {
        ringClient?.cancelHeartRateMeasurement()
        measurementTask?.cancel()
        measurementTask = nil
        isMeasuringHeartRate = false
    }

    func forgetRing() {
        stopHeartRateMeasurement()
        ringManager.forget()
        ring = RingDevice()
        syncMessage = "Ring forgotten; local history was kept"
        refreshFromStore()
    }

    func exportFiles() throws -> [URL] {
        try healthStore?.exportFiles(deviceID: activeDeviceID) ?? []
    }

    var activeDeviceID: String? {
        ringManager.connectedIdentifier ?? ringManager.pairedIdentifier?.uuidString
    }

    var connectionLabel: String {
        isSyncing ? "Syncing" : ringManager.state.label
    }

    private func refreshFromStore() {
        today = healthStore?.today(deviceID: activeDeviceID) ?? HealthData.emptyToday()
        dataRevision &+= 1
    }
}
