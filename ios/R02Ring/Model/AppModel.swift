import SwiftUI
import SwiftData

// MARK: - Navigation

enum Tab: String, CaseIterable, Identifiable {
    case today, gestures, settings
    var id: String { rawValue }
    static let healthTabs: [Tab] = [.today, .gestures, .settings]
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

/// User-facing session policy. The firmware's short lease remains an invisible
/// crash backstop; while the app is active it renews Gesture continuously until
/// this policy, the explicit button, or a future gesture mapping asks for Health.
enum GestureAutoReturn: Int, CaseIterable, Identifiable {
    case off = 0
    case oneMinute = 60
    case fiveMinutes = 300
    case fifteenMinutes = 900
    case thirtyMinutes = 1_800

    var id: Int { rawValue }
    var seconds: TimeInterval? { self == .off ? nil : TimeInterval(rawValue) }
    var title: String {
        switch self {
        case .off: return "Off"
        case .oneMinute: return "1 minute"
        case .fiveMinutes: return "5 minutes"
        case .fifteenMinutes: return "15 minutes"
        case .thirtyMinutes: return "30 minutes"
        }
    }
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
    @Published var heartRateLogging = false
    @Published private(set) var heartRateSettingsKnown = false
    @Published private(set) var heartRateIntervalMinutes = 5
    @Published var units: Units = .metric
    @Published var gestureAutoReturn: GestureAutoReturn {
        didSet {
            UserDefaults.standard.set(gestureAutoReturn.rawValue, forKey: Self.gestureAutoReturnKey)
            scheduleGestureAutoReturn()
        }
    }

    @Published var ring = RingDevice()
    @Published var user = User()
    @Published var today = HealthData.emptyToday()
    @Published var isSyncing = false
    @Published var isMeasuringHeartRate = false
    @Published var liveHeartRate: Int?
    @Published var syncMessage = "Not synced"
    @Published private(set) var firmwareMode: RingFirmwareMode = .unknown
    @Published private(set) var firmwareFamily: RingHardwareFamily?
    @Published private(set) var unifiedFirmwareInstalled = false
    @Published private(set) var isFirmwareSwitching = false
    @Published private(set) var firmwareProgress = 0.0
    @Published private(set) var lastFirmwareSwitchDuration: TimeInterval?
    @Published private(set) var lastFirmwareTransferDuration: TimeInterval?
    @Published private(set) var dataRevision = 0
    @Published private(set) var gestureStatus = "Health is the default. Start a Gesture session when needed."
    @Published private(set) var recentGestures: [RingGestureEvent] = []
    @Published private(set) var diagnosticPrompt = ""
    @Published private(set) var diagnosticProgress = ""
    @Published private(set) var diagnosticCaptureName: String?
    @Published private(set) var diagnosticRecording = false
    @Published private(set) var healthCoverageMessage: String?
    let modes: UnifiedModeCoordinator

    let ringManager = RingManager()
    private var healthStore: HealthStore?
    private var coverageStore: HealthCoverageStore?
    private var ringClient: ColmiR02Client?
    private var syncService: HealthSyncService?
    private var measurementTask: Task<Void, Never>?
    private var lastSyncSucceeded = false
    private let operations: RingOperationGate
    private var firmwareOperation: UUID?
    private var gestureDriver: GestureSession?
    private var gestureGeneration: UUID?
    private var diagnosticRecorder: GestureDiagnosticRecorder?
    private var diagnosticTask: Task<Void, Never>?
    private var gestureSensorCalibration: GestureSensorCalibration = .identity
    private var heartbeatTask: Task<Void, Never>?
    private var gestureAutoReturnTask: Task<Void, Never>?
    private var started = false
    private var pendingFirmwareTarget: RingFirmwareMode?
    private var firmwareSwitchStartedAt: Date?
    private var a1ModeTransport: A1UnifiedModeTransport?
    private let lastSyncKeyPrefix = "lastHealthSync."
    private static let gestureAutoReturnKey = "gestureAutoReturnSeconds"

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

    var firmwareOptions: [BundledFirmware] {
        BundledFirmware.routedCatalog(
            hardware: ringManager.hardware ?? ring.hardware,
            firmware: ringManager.firmware ?? ring.firmware
        ).filter { $0.mode != firmwareMode }
    }

    var firmwareRoutingMessage: String {
        let hardware = ringManager.hardware ?? ring.hardware
        let firmware = ringManager.firmware ?? ring.firmware
        guard let family = RingHardwareFamily.route(hardware: hardware, firmware: firmware) else {
            return "Connect a ring with a consistent hardware and firmware identity. Unknown or conflicting identities cannot be flashed."
        }
        return "Only images for the detected \(family.title) family are shown."
    }

    let appVersion = "R02 · 2.8.1 (1150)"

    init() {
        gestureAutoReturn = GestureAutoReturn(
            rawValue: UserDefaults.standard.integer(forKey: Self.gestureAutoReturnKey)
        ) ?? .off
        let gate = RingOperationGate()
        operations = gate
        modes = UnifiedModeCoordinator(gate: gate)
        modes.onModeChange = { [weak self] previous, current in
            self?.runtimeModeChanged(previous: previous, current: current)
        }
    }

    func setGestureSession(_ enabled: Bool) async {
        do { try await modes.setGesture(enabled) }
        catch { gestureStatus = error.localizedDescription }
    }

    /// The exact-image A1 adapter assigns a connection-bound monotonic sequence
    /// to each checksum-valid accelerometer notification at BLE receipt.
    func acceptMotionSample(_ packet: Data, session: UInt32, sequence: UInt32, receivedAt: Double) {
        guard modes.available, modes.status?.mode == .gesture, modes.status?.session == session else { return }
        diagnosticRecorder?.append(packet: packet, receivedAt: receivedAt)
        gestureDriver?.ingest(packet, session: session, sequence: sequence, receivedAt: receivedAt)
    }

    func startGestureDiagnosticWorkflow(repetitions: Int = 3) {
        guard !diagnosticRecording, modes.status?.mode == .gesture, gestureStatus == "Ready" else {
            diagnosticProgress = "Start Gesture mode and complete the fingers-down calibration first."
            return
        }
        do {
            let recorder = try GestureDiagnosticRecorder(
                name: ring.id,
                hardware: ringManager.hardware ?? ring.hardware,
                firmware: ringManager.firmware ?? ring.firmware,
                deviceID: activeDeviceID,
                signalCalibration: gestureSensorCalibration
            )
            diagnosticRecorder = recorder
            diagnosticRecording = true
            diagnosticCaptureName = nil
            let prompts = GestureDiagnosticPlan.prompts(repetitions: repetitions)
            diagnosticTask = Task { [weak self] in
                guard let self else { return }
                do {
                    self.diagnosticPrompt = "Get ready"
                    self.diagnosticProgress = "Recording a quiet pre-roll"
                    try await Task.sleep(for: .seconds(2))
                    for (index, prompt) in prompts.enumerated() {
                        for count in stride(from: 3, through: 1, by: -1) {
                            try Task.checkCancellation()
                            self.diagnosticPrompt = "Next: \(prompt.spoken) · \(count)"
                            self.diagnosticProgress = "\(index + 1) of \(prompts.count)"
                            try await Task.sleep(for: .seconds(1))
                        }
                        try Task.checkCancellation()
                        self.diagnosticRecorder?.mark(prompt, at: ProcessInfo.processInfo.systemUptime)
                        self.diagnosticPrompt = "NOW: \(prompt.spoken)"
                        try await Task.sleep(for: .seconds(3))
                    }
                    self.diagnosticPrompt = "Natural movement"
                    self.diagnosticProgress = "30-second ambient tail"
                    try await Task.sleep(for: .seconds(30))
                    self.finishGestureDiagnostic(cancelled: false)
                    await self.setGestureSession(false)
                } catch is CancellationError {
                    self.finishGestureDiagnostic(cancelled: true)
                } catch {
                    self.diagnosticProgress = error.localizedDescription
                    self.finishGestureDiagnostic(cancelled: true)
                }
            }
        } catch {
            diagnosticProgress = "Could not start capture: \(error.localizedDescription)"
        }
    }

    func cancelGestureDiagnosticWorkflow() {
        diagnosticTask?.cancel()
        diagnosticTask = nil
        finishGestureDiagnostic(cancelled: true)
    }

    private func finishGestureDiagnostic(cancelled: Bool) {
        let recorder = diagnosticRecorder
        diagnosticRecorder = nil
        diagnosticRecording = false
        diagnosticTask = nil
        diagnosticPrompt = ""
        guard let recorder else { return }
        do {
            diagnosticCaptureName = try recorder.finish(cancelled: cancelled)
            diagnosticProgress = cancelled ? "Saved partial capture \(recorder.sessionID)" : "Saved \(recorder.sessionID)"
        } catch {
            diagnosticProgress = "Capture close failed: \(error.localizedDescription)"
        }
    }

    private func runtimeModeChanged(previous: ModeStatus?, current: ModeStatus?) {
        gestureDriver?.stop(); gestureGeneration = nil
        heartbeatTask?.cancel(); heartbeatTask = nil
        gestureAutoReturnTask?.cancel(); gestureAutoReturnTask = nil
        if let current, let deviceID = activeDeviceID {
            do { try coverageStore?.observe(deviceID: deviceID, mode: current.mode, firmware: ring.firmware, at: .now) }
            catch { syncMessage = "Could not record health coverage: \(error.localizedDescription)" }
        }
        guard let current, current.mode == .gesture, !current.charging else {
            if diagnosticRecording { cancelGestureDiagnosticWorkflow() }
            gestureStatus = current?.mode == .health ? "Health mode · gesture recognition off" : "Gesture recognition paused"
            return
        }
        do {
            let classifier = try PinnedGestureClassifier()
            let calibration = GestureSensorCalibration.stored(for: activeDeviceID)
            gestureSensorCalibration = calibration
            let signalAdapter: GestureSignalAdapter = firmwareFamily == .rt12col
                ? .rt12col(calibration: calibration) : .rt02cr(calibration: calibration)
            let driver = GestureSession(signalAdapter: signalAdapter, output: { [weak self] output in
                Task { @MainActor in
                    guard let self, self.gestureGeneration == output.generation else { return }
                    self.gestureStatus = output.pose.reason
                    self.diagnosticRecorder?.setFrame(output.pose.frame)
                    self.modes.didProcess(session: output.session, sequence: output.sequence, at: output.receivedAt)
                    self.recentGestures.append(contentsOf: output.events)
                    if self.recentGestures.count > 20 { self.recentGestures.removeFirst(self.recentGestures.count - 20) }
                }
            }, invalid: { [weak self] generation, reason in
                Task { @MainActor in
                    guard let self, self.gestureGeneration == generation else { return }
                    self.gestureGeneration = nil
                    self.heartbeatTask?.cancel()
                    self.gestureStatus = reason
                    await self.setGestureSession(false)
                }
            })
            gestureDriver = driver
            gestureGeneration = driver.start(session: current.session, classifier: classifier)
            scheduleGestureAutoReturn()
            heartbeatTask = Task { [weak self] in
                while !Task.isCancelled {
                    do {
                        try await Task.sleep(for: .seconds(5))
                        guard !Task.isCancelled, let self else { return }
                        try await self.modes.heartbeat(at: ProcessInfo.processInfo.systemUptime)
                    } catch is CancellationError { return }
                    catch {
                        guard let self else { return }
                        self.gestureStatus = error.localizedDescription
                        await self.setGestureSession(false)
                        return
                    }
                }
            }
        } catch {
            gestureStatus = "Gesture model unavailable: \(error.localizedDescription)"
            Task { await setGestureSession(false) }
        }
    }

    private func scheduleGestureAutoReturn() {
        gestureAutoReturnTask?.cancel()
        gestureAutoReturnTask = nil
        guard let seconds = gestureAutoReturn.seconds,
              let active = modes.status, active.mode == .gesture else { return }
        let session = active.session
        gestureAutoReturnTask = Task { [weak self] in
            do { try await Task.sleep(for: .seconds(seconds)) }
            catch { return }
            guard !Task.isCancelled, let self,
                  self.modes.status?.mode == .gesture,
                  self.modes.status?.session == session else { return }
            self.gestureAutoReturnTask = nil
            self.gestureStatus = "Session timer ended · returning to Health"
            await self.setGestureSession(false)
        }
    }

    func start(modelContext: ModelContext) {
        guard !started else { return }
        started = true
        let store = HealthStore(context: modelContext)
        let client = ColmiR02Client(manager: ringManager)
        healthStore = store
        coverageStore = HealthCoverageStore(context: modelContext)
        ringClient = client
        syncService = HealthSyncService(client: client, store: store)
        ringManager.onReady = { [weak self] in
            Task { @MainActor [weak self] in
                guard let self, let deviceID = self.ringManager.connectedIdentifier else { return }
                self.ring.lastSync = UserDefaults.standard.object(
                    forKey: self.lastSyncKeyPrefix + deviceID
                ) as? Date
                await self.identifyFirmwareMode()
                let returningFromFirmwareSwitch = self.pendingFirmwareTarget == self.firmwareMode
                if returningFromFirmwareSwitch {
                    // Release the firmware owner before the unified transport
                    // acquires the mode owner on this post-DFU connection.
                    self.finishFirmwareSwitch()
                } else if self.pendingFirmwareTarget != nil {
                    if let operation = self.firmwareOperation { self.operations.end(operation) }
                    self.firmwareOperation = nil
                    self.isFirmwareSwitching = false
                    self.pendingFirmwareTarget = nil
                    self.firmwareSwitchStartedAt = nil
                    self.syncMessage = "Firmware return did not match the requested image"
                }
                if self.unifiedFirmwareInstalled { await self.attachUnifiedMode() }
                do {
                    try self.coverageStore?.observe(deviceID: deviceID,
                        mode: self.unifiedFirmwareInstalled
                            ? (self.modes.status?.mode ?? .unknown)
                            : (self.firmwareMode == .health ? .health : .unknown),
                        firmware: self.ring.firmware, at: .now)
                } catch { self.syncMessage = "Could not record health coverage: \(error.localizedDescription)" }
                if self.firmwareMode == .health || self.firmwareMode == .unified {
                    await self.refreshHealthSettings()
                    // A firmware return is not a newly provisioned ring. In particular,
                    // never send the full-sync clock command merely because this is a
                    // fresh app install: that command clears activity held by the ring.
                    await self.sync(full: returningFromFirmwareSwitch ? false : self.ring.lastSync == nil)
                } else if self.firmwareMode == .gesture {
                    self.ring.linked = true
                    self.syncMessage = "Gesture mode · health sync paused"
                    self.ringManager.showsOnboarding = false
                }
            }
        }
        ringManager.onDisconnect = { [weak self] in
            self?.a1ModeTransport?.disconnected()
            self?.a1ModeTransport = nil
            self?.ringManager.onRawMotion = nil
            self?.modes.disconnected()
            self?.heartRateSettingsKnown = false
            self?.ring.linked = false
            self?.syncMessage = self?.isFirmwareSwitching == true
                ? "Firmware installed · waiting for ring to restart"
                : "Waiting for ring"
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
        guard healthSyncEnabled,
              !isSyncing, let syncService, let deviceID = ringManager.connectedIdentifier else {
            if !ringManager.isReady { ringManager.scan() }
            return
        }
        guard let operation = operations.begin(.sync) else { return }
        defer { operations.end(operation) }
        await importHistory(syncService: syncService, deviceID: deviceID, full: full)
    }

    private func importHistory(syncService: HealthSyncService, deviceID: String, full: Bool) async {
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
        if !result.hasAnyError {
            ring.lastSync = .now
            UserDefaults.standard.set(ring.lastSync, forKey: lastSyncKeyPrefix + deviceID)
        }
        isSyncing = false
        syncMessage = result.errorSummary ?? "Synced just now"
        lastSyncSucceeded = !result.hasAnyError
        ringManager.showsOnboarding = false
        refreshFromStore()
    }

    func series(for metric: Metric, range: MetricRange) -> MetricSeries {
        _ = dataRevision
        return healthStore?.series(deviceID: activeDeviceID, metric: metric, range: range)
            ?? .empty(for: metric)
    }

    func setHeartRateLogging(_ enabled: Bool) async {
        guard healthSyncEnabled, let ringClient, ringManager.isReady else {
            syncMessage = "Switch to Health mode and connect the ring first"
            return
        }
        guard let operation = operations.begin(.settings) else { syncMessage = "Ring is busy"; return }
        defer { operations.end(operation) }
        do {
            try await ringClient.setHeartRateLogging(enabled: enabled,
                                                     intervalMinutes: UInt8(clamping: heartRateIntervalMinutes))
            heartRateLogging = enabled
            heartRateSettingsKnown = true
        } catch {
            syncMessage = error.localizedDescription
        }
    }

    private func refreshHealthSettings() async {
        heartRateSettingsKnown = false
        guard healthSyncEnabled, let ringClient, let operation = operations.begin(.settings) else { return }
        defer { operations.end(operation) }
        do {
            let settings = try await ringClient.heartRateLoggingSettings()
            heartRateLogging = settings.enabled
            heartRateIntervalMinutes = settings.interval > 0 ? settings.interval : 5
            heartRateSettingsKnown = true
        } catch { syncMessage = "Heart-rate settings unavailable: \(error.localizedDescription)" }
    }

    func measureHeartRate() {
        guard healthSyncEnabled, !isMeasuringHeartRate, let ringClient, let store = healthStore,
              let deviceID = activeDeviceID else { return }
        guard let operation = operations.begin(.liveHeartRate) else { return }
        measurementTask?.cancel()
        isMeasuringHeartRate = true
        liveHeartRate = nil
        syncMessage = "Measuring live heart rate…"
        measurementTask = Task { [weak self] in
            defer { self?.operations.end(operation) }
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
        guard isMeasuringHeartRate else { return }
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

    var healthSyncEnabled: Bool {
        !isFirmwareSwitching && (unifiedFirmwareInstalled
            ? modes.available && modes.status?.mode == .health
            : (modes.available ? modes.status?.mode == .health : firmwareMode == .health))
    }

    func switchFirmware(to target: RingFirmwareMode) async {
        guard firmwareMode != .unknown, target != .unknown, target != firmwareMode,
              !isFirmwareSwitching, !isSyncing,
              (!modes.available || modes.status?.mode == .health),
              let ringClient, ringManager.isReady else {
            if !ringManager.isReady { syncMessage = "Connect the ring before switching modes" }
            return
        }

        let actualHardware = ringManager.hardware ?? ring.hardware
        let actualFirmware = ringManager.firmware ?? ring.firmware
        guard let family = RingHardwareFamily.route(
            hardware: actualHardware, firmware: actualFirmware
        ) else {
            syncMessage = FirmwareSwitchError.unroutableIdentity(
                hardware: actualHardware, firmware: actualFirmware
            ).localizedDescription
            return
        }
        guard let descriptor = BundledFirmware.routedImage(
            for: target, hardware: actualHardware, firmware: actualFirmware
        ) else {
            syncMessage = FirmwareSwitchError.noCompatibleImage(
                mode: target, family: family
            ).localizedDescription
            return
        }
        guard descriptor.installEnabled else {
            syncMessage = descriptor.disabledReason ?? "This firmware image is disabled"
            return
        }

        guard let operation = operations.begin(.firmware) else { syncMessage = "Ring is busy"; return }
        firmwareOperation = operation

        pendingFirmwareTarget = target
        firmwareSwitchStartedAt = .now
        do {
            stopHeartRateMeasurement()
            // Stock holds the only copy of unsynced history. Import it before the
            // image is replaced; routine sync never sends the destructive clock command.
            if firmwareMode == .health || firmwareMode == .unified {
                syncMessage = "Saving health history before switching…"
                guard let syncService, let deviceID = activeDeviceID else { throw RingProtocolError.notReady }
                await importHistory(syncService: syncService, deviceID: deviceID, full: false)
                guard lastSyncSucceeded else {
                    throw FirmwareSwitchError.healthSyncFailed(syncMessage)
                }
            }

            isFirmwareSwitching = true
            firmwareProgress = 0
            let battery = try await ringClient.battery()
            ring.batteryPercent = battery.percent
            ring.charging = battery.charging
            guard !battery.charging else { throw FirmwareSwitchError.charging }
            guard battery.percent >= 40 else { throw FirmwareSwitchError.batteryTooLow(battery.percent) }

            let firmware = try descriptor.load()
            let expectedHardware = try descriptor.declaredHardware(in: firmware)
            let actualHardware = ringManager.hardware ?? ring.hardware
            guard expectedHardware == actualHardware else {
                throw FirmwareSwitchError.incompatibleHardware(expected: expectedHardware, actual: actualHardware)
            }

            syncMessage = "Preparing \(target.title) firmware…"
            let transferStartedAt = Date()
            try await ringManager.flashFirmware(firmware, initType: descriptor.initType) { [weak self] progress, message in
                self?.firmwareProgress = progress
                self?.syncMessage = message
            }
            lastFirmwareTransferDuration = Date().timeIntervalSince(transferStartedAt)
            print(String(format: "R02 DFU TRANSFER %.2f s target=%@", lastFirmwareTransferDuration ?? 0, target.rawValue))
            syncMessage = "\(target.title) firmware installed · reconnecting"
        } catch {
            operations.end(operation)
            firmwareOperation = nil
            syncMessage = error.localizedDescription
            isFirmwareSwitching = false
            pendingFirmwareTarget = nil
            firmwareSwitchStartedAt = nil
        }
    }

    var activeDeviceID: String? {
        ringManager.connectedIdentifier ?? ringManager.pairedIdentifier?.uuidString
    }

    var connectionLabel: String {
        isFirmwareSwitching ? "Updating firmware" : (isSyncing ? "Syncing" : ringManager.state.label)
    }

    private var firmwareModeKey: String {
        "ringFirmwareMode." + (activeDeviceID ?? "unpaired")
    }

    private func identifyFirmwareMode() async {
        unifiedFirmwareInstalled = false
        firmwareFamily = nil
        ring.linked = true
        ring.id = ringManager.connectedName ?? ringManager.candidate?.name ?? "Colmi R02"

        // DIS reads can finish just after UART discovery. The two 25 Hz images
        // deliberately report the same version and are fingerprinted below.
        for _ in 0..<10 where ringManager.firmware == nil || ringManager.hardware == nil {
            try? await Task.sleep(for: .milliseconds(100))
        }
        ring.firmware = ringManager.firmware ?? ring.firmware
        ring.hardware = ringManager.hardware ?? ring.hardware
        guard let family = RingHardwareFamily.route(
            hardware: ringManager.hardware, firmware: ringManager.firmware
        ) else {
            firmwareMode = .unknown
            syncMessage = "Unknown or conflicting ring identity · firmware actions and automatic health sync paused"
            return
        }
        firmwareFamily = family

        if family == .rt12col {
            guard let version = ringManager.firmware else {
                firmwareMode = .unknown
                syncMessage = "Unknown RT12COL firmware · firmware actions and automatic health sync paused"
                return
            }
            if version == FirmwareIdentity.rt12colStockVersion {
                firmwareMode = .health
                UserDefaults.standard.set(firmwareMode.rawValue, forKey: firmwareModeKey)
                return
            }
            if version == FirmwareIdentity.rt12colUnifiedVersion {
                do {
                    let candidate = try BundledFirmware.rt12colUnified.load()
                    guard try await imageMatches(
                        candidate, sites: FirmwareIdentity.rt12colUnifiedSites
                    ) else { throw FirmwareSwitchError.unrecognizedFirmware }
                    firmwareMode = .unified
                    unifiedFirmwareInstalled = true
                    UserDefaults.standard.set(firmwareMode.rawValue, forKey: firmwareModeKey)
                    return
                } catch {
                    firmwareMode = .unknown
                    syncMessage = "RT12COL firmware fingerprint uncertain · health sync paused"
                    return
                }
            }
            if version == FirmwareIdentity.rt12colUnifiedV6Version {
                do {
                    let candidate = try BundledFirmware.rt12colUnifiedLegacyV6.load()
                    guard try await imageMatches(
                        candidate, sites: FirmwareIdentity.rt12colUnifiedV6Sites
                    ) else { throw FirmwareSwitchError.unrecognizedFirmware }
                    firmwareMode = .unified
                    unifiedFirmwareInstalled = true
                    syncMessage = "RT12COL V6 verified · unified Health/Gesture ready"
                    UserDefaults.standard.set(firmwareMode.rawValue, forKey: firmwareModeKey)
                    return
                } catch {
                    firmwareMode = .unknown
                    syncMessage = "RT12COL firmware fingerprint uncertain · health sync paused"
                    return
                }
            }
            if version == FirmwareIdentity.rt12colUnifiedV3Version {
                do {
                    let candidate = try BundledFirmware.rt12colUnifiedLegacyV3.load()
                    guard try await imageMatches(
                        candidate, sites: FirmwareIdentity.rt12colUnifiedV3Sites
                    ) else { throw FirmwareSwitchError.unrecognizedFirmware }
                    firmwareMode = .unified
                    // Legacy images may be recovered or replaced, not entered.
                    unifiedFirmwareInstalled = false
                    syncMessage = "RT12COL V3 revoked · use stock recovery before a reviewed update"
                    UserDefaults.standard.set(firmwareMode.rawValue, forKey: firmwareModeKey)
                    return
                } catch {
                    firmwareMode = .unknown
                    syncMessage = "RT12COL firmware fingerprint uncertain · health sync paused"
                    return
                }
            }
            if version == FirmwareIdentity.rt12colUnifiedV2Version {
                do {
                    let candidate = try BundledFirmware.rt12colUnifiedLegacyV2.load()
                    guard try await imageMatches(
                        candidate, sites: FirmwareIdentity.rt12colUnifiedV2Sites
                    ) else { throw FirmwareSwitchError.unrecognizedFirmware }
                    firmwareMode = .unified
                    // Legacy images may be recovered or replaced, not entered.
                    unifiedFirmwareInstalled = false
                    syncMessage = "RT12COL V2 draft detected · wide-band leased update available"
                    UserDefaults.standard.set(firmwareMode.rawValue, forKey: firmwareModeKey)
                    return
                } catch {
                    firmwareMode = .unknown
                    syncMessage = "RT12COL firmware fingerprint uncertain · health sync paused"
                    return
                }
            }
            if version == FirmwareIdentity.rt12colUnifiedV1Version {
                do {
                    let candidate = try BundledFirmware.rt12colUnifiedLegacyV1.load()
                    guard try await imageMatches(
                        candidate, sites: FirmwareIdentity.rt12colUnifiedV1Sites
                    ) else { throw FirmwareSwitchError.unrecognizedFirmware }
                    firmwareMode = .unified
                    // Legacy images may be recovered or replaced, not entered.
                    unifiedFirmwareInstalled = false
                    syncMessage = "RT12COL V1 detected · wide-band leased V3 update available"
                    UserDefaults.standard.set(firmwareMode.rawValue, forKey: firmwareModeKey)
                    return
                } catch {
                    firmwareMode = .unknown
                    syncMessage = "RT12COL firmware fingerprint uncertain · health sync paused"
                    return
                }
            }
            firmwareMode = .unknown
            syncMessage = "Unknown RT12COL firmware · firmware actions and automatic health sync paused"
            return
        }

        if ringManager.firmware == FirmwareIdentity.stockVersion {
            firmwareMode = .health
            UserDefaults.standard.set(firmwareMode.rawValue, forKey: firmwareModeKey)
            return
        }
        guard ringManager.firmware == FirmwareIdentity.gestureVersion else {
            firmwareMode = .unknown
            syncMessage = "Unknown firmware · automatic health sync paused"
            return
        }

        do {
            let unified = try BundledFirmware.unified.load()
            if try await imageMatches(unified, sites: FirmwareIdentity.unifiedSites) {
                firmwareMode = .unified
                unifiedFirmwareInstalled = true
                UserDefaults.standard.set(firmwareMode.rawValue, forKey: firmwareModeKey)
                return
            }
            let candidate = try BundledFirmware.gesture.load()
            guard try await imageMatches(candidate, sites: FirmwareIdentity.sites) else {
                throw FirmwareSwitchError.unrecognizedFirmware
            }
            firmwareMode = .gesture
            UserDefaults.standard.set(firmwareMode.rawValue, forKey: firmwareModeKey)
        } catch {
            firmwareMode = .unknown
            syncMessage = "Firmware identity uncertain · health sync paused"
        }
    }

    private func imageMatches(_ image: Data, sites: [FirmwareIdentity.Site]) async throws -> Bool {
        for site in sites {
            let replies = try await ringManager.requestUART(
                FirmwareIdentity.readPacket(site), command: 0xcd, timeout: 3
            ) { _, _ in true }
            guard let reply = replies.last, reply.count == 16,
                  reply[1..<(1 + site.length)].elementsEqual(
                    image[site.offset..<(site.offset + site.length)]
                  ) else { return false }
        }
        return true
    }

    private func attachUnifiedMode() async {
        let leaseSafeRT12 = ringManager.firmware == FirmwareIdentity.rt12colUnifiedVersion
            || ringManager.firmware == FirmwareIdentity.rt12colUnifiedV6Version
        let transport = A1UnifiedModeTransport(link: ringManager, charging: { [weak self] in
            self?.ring.charging ?? false
        }, requiresMotionHold: firmwareFamily == .rt12col,
           firmwareLeaseSeconds: leaseSafeRT12 ? 10 : 0)
        transport.onMotion = { [weak self] packet, session, sequence, time in
            self?.acceptMotionSample(packet, session: session, sequence: sequence, receivedAt: time)
        }
        ringManager.onRawMotion = { [weak transport] packet, time in
            transport?.receiveMotion(packet, at: time)
        }
        a1ModeTransport = transport
        do { try await modes.attach(transport) }
        catch {
            a1ModeTransport = nil
            ringManager.onRawMotion = nil
            syncMessage = "Unified mode control unavailable: \(error.localizedDescription)"
        }
    }

    private func finishFirmwareSwitch() {
        if let operation = firmwareOperation { operations.end(operation) }
        firmwareOperation = nil
        if let startedAt = firmwareSwitchStartedAt {
            let duration = Date().timeIntervalSince(startedAt)
            lastFirmwareSwitchDuration = duration
            print(String(format: "R02 SWITCH VERIFIED %.2f s target=%@ transfer=%.2f s",
                         duration, firmwareMode.rawValue, lastFirmwareTransferDuration ?? 0))
            syncMessage = String(format: "%@ mode verified in %.1f s", firmwareMode.title, duration)
        }
        isFirmwareSwitching = false
        firmwareProgress = 1
        pendingFirmwareTarget = nil
        firmwareSwitchStartedAt = nil
    }

    private func refreshFromStore() {
        today = healthStore?.today(deviceID: activeDeviceID) ?? HealthData.emptyToday()
        if let deviceID = activeDeviceID {
            do {
                let startOfToday = Calendar.autoupdatingCurrent.startOfDay(for: .now)
                let uncertain = try coverageStore?.uncertainIntervals(deviceID: deviceID)
                    .contains { $0.ended == nil || $0.ended! >= startOfToday } ?? false
                healthCoverageMessage = uncertain
                    ? "Some health coverage is unverified. Gesture sessions may leave gaps in heart rate, steps and sleep."
                    : nil
            } catch { healthCoverageMessage = "Health coverage could not be checked." }
        } else { healthCoverageMessage = nil }
        dataRevision &+= 1
    }
}
