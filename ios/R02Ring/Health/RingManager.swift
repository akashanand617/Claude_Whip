import CoreBluetooth
import Foundation

enum RingConnectionState: Equatable {
    case idle
    case bluetoothUnavailable(String)
    case scanning
    case discovered
    case connecting
    case discoveringServices
    case ready
    case disconnected(String)

    var label: String {
        switch self {
        case .idle: return "Idle"
        case let .bluetoothUnavailable(message): return message
        case .scanning: return "Looking for your R02…"
        case .discovered: return "R02 nearby"
        case .connecting: return "Connecting…"
        case .discoveringServices: return "Finishing setup…"
        case .ready: return "Connected"
        case let .disconnected(message): return message
        }
    }
}

struct DiscoveredRing: Identifiable, Equatable {
    let id: UUID
    let name: String
    let rssi: Int
}

@MainActor
final class RingManager: NSObject, ObservableObject {
    @Published private(set) var state: RingConnectionState = .idle
    @Published private(set) var candidate: DiscoveredRing?
    @Published private(set) var candidates: [DiscoveredRing] = []
    @Published var showsOnboarding = false
    @Published private(set) var firmware: String?
    @Published private(set) var hardware: String?

    var onReady: (() -> Void)?
    var onDisconnect: (() -> Void)?

    private var central: CBCentralManager!
    private var peripheral: CBPeripheral?
    private var uartWrite: CBCharacteristic?
    private var uartNotify: CBCharacteristic?
    private var bigWrite: CBCharacteristic?
    private var bigNotify: CBCharacteristic?
    private var firmwareCharacteristic: CBCharacteristic?
    private var hardwareCharacteristic: CBCharacteristic?
    private var reconnectTask: Task<Void, Never>?
    private var isPairing = false
    private var hasAnnouncedReady = false
    private var hasBegun = false
    private var pendingCharacteristicDiscoveries = 0
    private var lastUARTWriteAt = Date.distantPast
    private let minimumUARTCommandSpacing: TimeInterval = 0.35

    private let savedRingKey = "pairedColmiR02Identifier"
    private let restoreIDKey = "colmiCentralRestoreIdentifier"

    private struct PendingUART {
        let id: UUID
        let command: UInt8
        var packets: [Data]
        let isComplete: ([Data], Data) -> Bool
        let continuation: CheckedContinuation<[Data], Error>
        let timeout: Task<Void, Never>
    }
    private var pendingUART: PendingUART?

    private struct PendingRealtimeHeartRate {
        let id: UUID
        var readings: [Int]
        let onReading: (Int) -> Void
        let continuation: CheckedContinuation<Int, Error>
        let timeout: Task<Void, Never>
    }
    private var pendingRealtimeHeartRate: PendingRealtimeHeartRate?

    private struct PendingBigData {
        let id: UUID
        let dataID: UInt8
        let continuation: CheckedContinuation<Data, Error>
        let reassembler: BigDataReassembler
        let timeout: Task<Void, Never>
    }
    private var pendingBigData: PendingBigData?

    override init() {
        super.init()
        let defaults = UserDefaults.standard
        let restoreID: String
        if let saved = defaults.string(forKey: restoreIDKey) {
            restoreID = saved
        } else {
            restoreID = UUID().uuidString
            defaults.set(restoreID, forKey: restoreIDKey)
        }
        central = CBCentralManager(delegate: self, queue: .main, options: [
            CBCentralManagerOptionRestoreIdentifierKey: restoreID,
            CBCentralManagerOptionShowPowerAlertKey: true,
        ])
    }

    var pairedIdentifier: UUID? {
        UserDefaults.standard.string(forKey: savedRingKey).flatMap(UUID.init(uuidString:))
    }

    var connectedIdentifier: String? { peripheral?.identifier.uuidString }
    var connectedName: String? { peripheral?.name }
    var isReady: Bool { state == .ready && uartWrite != nil && uartNotify != nil }
    var canReadSleep: Bool { isReady && bigWrite != nil && bigNotify != nil }

    func begin() {
        hasBegun = true
        guard central.state == .poweredOn else { return }
        switch state {
        case .scanning, .discovered, .connecting, .discoveringServices, .ready:
            return
        default:
            break
        }
        restoreOrScan()
    }

    func scan() {
        guard central.state == .poweredOn else {
            state = .bluetoothUnavailable("Bluetooth is off")
            showsOnboarding = true
            return
        }
        reconnectTask?.cancel()
        candidate = nil
        candidates = []
        state = .scanning
        showsOnboarding = true
        central.scanForPeripherals(withServices: nil, options: [CBCentralManagerScanOptionAllowDuplicatesKey: false])
    }

    func connectCandidate() {
        guard let candidate,
              let target = central.retrievePeripherals(withIdentifiers: [candidate.id]).first else {
            scan()
            return
        }
        isPairing = true
        connect(target)
    }

    func selectCandidate(_ ring: DiscoveredRing) {
        guard candidates.contains(where: { $0.id == ring.id }) else { return }
        candidate = ring
    }

    func forget() {
        reconnectTask?.cancel()
        if let peripheral { central.cancelPeripheralConnection(peripheral) }
        UserDefaults.standard.removeObject(forKey: savedRingKey)
        self.peripheral = nil
        resetCharacteristics()
        candidate = nil
        candidates = []
        state = .idle
        showsOnboarding = true
        scan()
    }

    func dismissOnboarding() {
        if pairedIdentifier != nil { showsOnboarding = false }
    }

    func cancelPairing() {
        guard pairedIdentifier == nil else { return }
        central.stopScan()
        candidates = []
        candidate = nil
        if state == .scanning || state == .discovered { state = .idle }
    }

    func writeUART(_ data: Data) throws {
        guard let peripheral, let uartWrite, peripheral.state == .connected else { throw RingProtocolError.notReady }
#if DEBUG
        print("R02 UART TX", data.map { String(format: "%02X", $0) }.joined(separator: " "))
#endif
        peripheral.writeValue(data, for: uartWrite, type: .withoutResponse)
        lastUARTWriteAt = .now
    }

    func requestUART(_ data: Data, command: UInt8, timeout seconds: Double = 6,
                     isComplete: @escaping ([Data], Data) -> Bool) async throws -> [Data] {
        guard pendingUART == nil else { throw RingProtocolError.busy }
        guard isReady else { throw RingProtocolError.notReady }
        let remainingGap = minimumUARTCommandSpacing - Date.now.timeIntervalSince(lastUARTWriteAt)
        if remainingGap > 0 {
            try await Task.sleep(for: .seconds(remainingGap))
        }
        let id = UUID()
        return try await withCheckedThrowingContinuation { continuation in
            let timeout = Task { [weak self] in
                try? await Task.sleep(for: .seconds(seconds))
                guard !Task.isCancelled else { return }
                self?.failUART(id: id, error: RingProtocolError.timeout)
            }
            pendingUART = PendingUART(id: id, command: command, packets: [],
                                      isComplete: isComplete, continuation: continuation, timeout: timeout)
            do {
                try writeUART(data)
            } catch {
                failUART(id: id, error: error)
            }
        }
    }

    func requestBigData(_ data: Data, dataID: UInt8, timeout seconds: Double = 12) async throws -> Data {
        guard pendingBigData == nil else { throw RingProtocolError.busy }
        guard let peripheral, let bigWrite, let bigNotify, peripheral.state == .connected else {
            throw RingProtocolError.notReady
        }
        peripheral.setNotifyValue(true, for: bigNotify)
        let id = UUID()
        return try await withCheckedThrowingContinuation { continuation in
            let timeout = Task { [weak self] in
                try? await Task.sleep(for: .seconds(seconds))
                guard !Task.isCancelled else { return }
                self?.failBigData(id: id, error: RingProtocolError.timeout)
            }
            pendingBigData = PendingBigData(id: id, dataID: dataID, continuation: continuation,
                                            reassembler: BigDataReassembler(), timeout: timeout)
#if DEBUG
            print("R02 BIG TX", data.map { String(format: "%02X", $0) }.joined(separator: " "))
#endif
            peripheral.writeValue(data, for: bigWrite, type: .withoutResponse)
        }
    }

    /// Starts a real-time HR measurement and waits for asynchronous `0x69` readings.
    /// The ring first acknowledges with a zero value, then publishes the actual BPM in
    /// later notifications; treating the acknowledgement as a request response drops
    /// every useful reading.
    func collectRealtimeHeartRate(timeout seconds: Double = 45,
                                  onReading: @escaping (Int) -> Void) async throws -> Int {
        guard pendingRealtimeHeartRate == nil, pendingUART == nil else { throw RingProtocolError.busy }
        guard isReady else { throw RingProtocolError.notReady }
        let id = UUID()
        return try await withCheckedThrowingContinuation { continuation in
            let timeout = Task { [weak self] in
                try? await Task.sleep(for: .seconds(seconds))
                guard !Task.isCancelled else { return }
                self?.failRealtimeHeartRate(id: id, error: RingProtocolError.timeout)
            }
            pendingRealtimeHeartRate = PendingRealtimeHeartRate(
                id: id, readings: [], onReading: onReading,
                continuation: continuation, timeout: timeout
            )
            do {
                try writeUART(ColmiR02Protocol.startRealtimeHeartRatePacket)
            } catch {
                failRealtimeHeartRate(id: id, error: error)
            }
        }
    }

    func cancelRealtimeHeartRate() {
        guard let pending = pendingRealtimeHeartRate else { return }
        failRealtimeHeartRate(id: pending.id, error: CancellationError())
    }

    private func restoreOrScan() {
        if let identifier = pairedIdentifier,
           let saved = central.retrievePeripherals(withIdentifiers: [identifier]).first {
            connect(saved)
        } else {
            scan()
        }
    }

    private func connect(_ peripheral: CBPeripheral) {
        central.stopScan()
        self.peripheral = peripheral
        peripheral.delegate = self
        resetCharacteristics()
        state = .connecting
        var options: [String: Any] = [
            CBConnectPeripheralOptionNotifyOnConnectionKey: false,
            CBConnectPeripheralOptionNotifyOnDisconnectionKey: false,
        ]
        if #available(iOS 17.0, *) {
            options[CBConnectPeripheralOptionEnableAutoReconnect] = true
        }
        central.connect(peripheral, options: options)
    }

    private func resetCharacteristics() {
        uartWrite = nil
        uartNotify = nil
        bigWrite = nil
        bigNotify = nil
        firmwareCharacteristic = nil
        hardwareCharacteristic = nil
        hasAnnouncedReady = false
        pendingCharacteristicDiscoveries = 0
    }

    private func announceReadyIfPossible() {
        guard pendingCharacteristicDiscoveries == 0,
              uartWrite != nil, uartNotify != nil, !hasAnnouncedReady else { return }
        hasAnnouncedReady = true
        if let id = peripheral?.identifier, isPairing {
            UserDefaults.standard.set(id.uuidString, forKey: savedRingKey)
        }
        isPairing = false
        state = .ready
        onReady?()
    }

    private func receiveUART(_ data: Data) {
#if DEBUG
        print("R02 UART RX", data.map { String(format: "%02X", $0) }.joined(separator: " "))
#endif
        guard ColmiR02Protocol.isValidPacket(data) else {
            if let pending = pendingUART, data.first == pending.command {
                failUART(id: pending.id, error: RingProtocolError.invalidPacket)
            }
            return
        }
        if data.first == ColmiR02Protocol.startRealtimeCommand,
           data.count == 16, data[1] == 1, data[2] == 0,
           (30...240).contains(Int(data[3])),
           var realtime = pendingRealtimeHeartRate {
            let bpm = Int(data[3])
            realtime.readings.append(bpm)
            realtime.onReading(bpm)
            if realtime.readings.count >= 5 {
                realtime.timeout.cancel()
                pendingRealtimeHeartRate = nil
                let sorted = realtime.readings.sorted()
                realtime.continuation.resume(returning: sorted[sorted.count / 2])
            } else {
                pendingRealtimeHeartRate = realtime
            }
        }
        guard var pending = pendingUART, data.first == pending.command else { return }
        pending.packets.append(data)
        if pending.isComplete(pending.packets, data) {
            pending.timeout.cancel()
            pendingUART = nil
            pending.continuation.resume(returning: pending.packets)
        } else {
            pendingUART = pending
        }
    }

    private func receiveBigData(_ data: Data) {
#if DEBUG
        print("R02 BIG RX", data.map { String(format: "%02X", $0) }.joined(separator: " "))
#endif
        guard let pending = pendingBigData,
              let message = pending.reassembler.ingest(data), message.dataID == pending.dataID else { return }
        pending.timeout.cancel()
        pendingBigData = nil
        pending.continuation.resume(returning: message.payload)
    }

    private func failUART(id: UUID, error: Error) {
        guard let pending = pendingUART, pending.id == id else { return }
        pending.timeout.cancel()
        pendingUART = nil
        pending.continuation.resume(throwing: error)
    }

    private func failBigData(id: UUID, error: Error) {
        guard let pending = pendingBigData, pending.id == id else { return }
        pending.timeout.cancel()
        pendingBigData = nil
        pending.continuation.resume(throwing: error)
    }

    private func failRealtimeHeartRate(id: UUID, error: Error) {
        guard let pending = pendingRealtimeHeartRate, pending.id == id else { return }
        pending.timeout.cancel()
        pendingRealtimeHeartRate = nil
        pending.continuation.resume(throwing: error)
    }

    private func failPending(_ error: Error) {
        if let pending = pendingUART { failUART(id: pending.id, error: error) }
        if let pending = pendingBigData { failBigData(id: pending.id, error: error) }
        if let pending = pendingRealtimeHeartRate {
            failRealtimeHeartRate(id: pending.id, error: error)
        }
    }
}

extension RingManager: CBCentralManagerDelegate {
    nonisolated func centralManagerDidUpdateState(_ central: CBCentralManager) {
        Task { @MainActor in
            guard hasBegun else { return }
            switch central.state {
            case .poweredOn: restoreOrScan()
            case .poweredOff: state = .bluetoothUnavailable("Bluetooth is off")
            case .unauthorized: state = .bluetoothUnavailable("Bluetooth permission is denied")
            case .unsupported: state = .bluetoothUnavailable("Bluetooth LE is unavailable")
            default: state = .idle
            }
        }
    }

    nonisolated func centralManager(_ central: CBCentralManager, willRestoreState dict: [String: Any]) {
        let restored = (dict[CBCentralManagerRestoredStatePeripheralsKey] as? [CBPeripheral])?.first
        Task { @MainActor in
            guard let restored else { return }
            peripheral = restored
            restored.delegate = self
            guard hasBegun else { return }
            if restored.state == .connected {
                state = .discoveringServices
                restored.discoverServices(nil)
            } else {
                connect(restored)
            }
        }
    }

    nonisolated func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral,
                                    advertisementData: [String: Any], rssi RSSI: NSNumber) {
        Task { @MainActor in
            let advertisedName = advertisementData[CBAdvertisementDataLocalNameKey] as? String
            let name = advertisedName ?? peripheral.name ?? "Colmi R02"
            let services = (advertisementData[CBAdvertisementDataServiceUUIDsKey] as? [CBUUID]) ?? []
            let looksLikeR02 = name.uppercased().contains("R02")
                || services.contains(CBUUID(string: ColmiR02Protocol.uartService))
            guard looksLikeR02 else { return }
            let found = DiscoveredRing(id: peripheral.identifier, name: name, rssi: RSSI.intValue)
            // Some unbonded R02 firmware revisions rotate their BLE address. CoreBluetooth
            // can consequently surface the same physical ring with a fresh UUID. Prefer the
            // advertised Colmi name as its stable discovery identity so the chooser does not
            // fill with duplicate D507 (or CC07) rows.
            let normalizedName = name.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
            let existingIndex = candidates.firstIndex {
                $0.id == found.id
                    || $0.name.trimmingCharacters(in: .whitespacesAndNewlines).uppercased() == normalizedName
            }
            if let index = existingIndex {
                let replacedID = candidates[index].id
                candidates[index] = found
                if candidate?.id == replacedID { candidate = found }
            } else {
                candidates.append(found)
            }
            candidates.sort { $0.rssi > $1.rssi }
            if candidates.count > 8 { candidates.removeLast(candidates.count - 8) }
            if candidate == nil || candidate?.id == found.id {
                candidate = found
            }
            state = .discovered
            showsOnboarding = true
        }
    }

    nonisolated func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        Task { @MainActor in
            self.peripheral = peripheral
            peripheral.delegate = self
            state = .discoveringServices
            peripheral.discoverServices([
                CBUUID(string: ColmiR02Protocol.uartService),
                CBUUID(string: ColmiR02Protocol.bigDataService),
                CBUUID(string: ColmiR02Protocol.deviceInfoService),
            ])
        }
    }

    nonisolated func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral,
                                    error: Error?) {
        Task { @MainActor in
            state = .disconnected(error?.localizedDescription ?? "Could not connect")
            scheduleReconnect()
        }
    }

    nonisolated func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral,
                                    error: Error?) {
        Task { @MainActor in
            resetCharacteristics()
            failPending(error ?? RingProtocolError.peripheral("The ring disconnected."))
            state = .disconnected("Ring out of range")
            onDisconnect?()
            scheduleReconnect()
        }
    }

    @available(iOS 17.0, *)
    nonisolated func centralManager(_ central: CBCentralManager,
                                    didDisconnectPeripheral peripheral: CBPeripheral,
                                    timestamp: CFAbsoluteTime,
                                    isReconnecting: Bool,
                                    error: Error?) {
        Task { @MainActor in
            resetCharacteristics()
            failPending(error ?? RingProtocolError.peripheral("The ring disconnected."))
            onDisconnect?()
            if isReconnecting {
                state = .connecting
            } else {
                state = .disconnected("Ring out of range")
                scheduleReconnect()
            }
        }
    }

    private func scheduleReconnect() {
        guard pairedIdentifier != nil else { return }
        reconnectTask?.cancel()
        reconnectTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(3))
            guard !Task.isCancelled else { return }
            self?.restoreOrScan()
        }
    }
}

extension RingManager: CBPeripheralDelegate {
    nonisolated func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        Task { @MainActor in
            if let error {
                state = .disconnected(error.localizedDescription)
                return
            }
            let services = peripheral.services ?? []
            pendingCharacteristicDiscoveries = services.count
            guard !services.isEmpty else {
                state = .disconnected("The ring did not expose its health services")
                return
            }
            for service in services { peripheral.discoverCharacteristics(nil, for: service) }
        }
    }

    nonisolated func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService,
                                error: Error?) {
        Task { @MainActor in
            if error == nil {
                for characteristic in service.characteristics ?? [] {
                    switch characteristic.uuid.uuidString.uppercased() {
                    case ColmiR02Protocol.uartWrite: uartWrite = characteristic
                    case ColmiR02Protocol.uartNotify:
                        uartNotify = characteristic
                        peripheral.setNotifyValue(true, for: characteristic)
                    case ColmiR02Protocol.bigDataWrite: bigWrite = characteristic
                    case ColmiR02Protocol.bigDataNotify: bigNotify = characteristic
                    case ColmiR02Protocol.firmwareRevision:
                        firmwareCharacteristic = characteristic
                        peripheral.readValue(for: characteristic)
                    case ColmiR02Protocol.hardwareRevision:
                        hardwareCharacteristic = characteristic
                        peripheral.readValue(for: characteristic)
                    default: break
                    }
                }
            }
            pendingCharacteristicDiscoveries = max(0, pendingCharacteristicDiscoveries - 1)
            announceReadyIfPossible()
        }
    }

    nonisolated func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic,
                                error: Error?) {
        Task { @MainActor in
            guard error == nil, let data = characteristic.value else { return }
            switch characteristic.uuid.uuidString.uppercased() {
            case ColmiR02Protocol.uartNotify: receiveUART(data)
            case ColmiR02Protocol.bigDataNotify: receiveBigData(data)
            case ColmiR02Protocol.firmwareRevision:
                firmware = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .controlCharacters)
#if DEBUG
                print("R02 FIRMWARE", firmware ?? "<unreadable>")
#endif
            case ColmiR02Protocol.hardwareRevision:
                hardware = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .controlCharacters)
#if DEBUG
                print("R02 HARDWARE", hardware ?? "<unreadable>")
#endif
            default: break
            }
        }
    }
}
