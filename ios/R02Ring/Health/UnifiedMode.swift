import Foundation
import Combine

/// Runtime mode is independent of the installed legacy image (`RingFirmwareMode`).
enum RingRuntimeMode: String, Codable { case unknown, health, enteringGesture, gesture, returningHealth, fault }

struct FirmwareCapabilities: Equatable {
    enum Profile: Equatable { case leasedService, exactA1 }

    let protocolVersion: Int
    let healthDefault: Bool
    let darkGesture: Bool
    let sequencedMotion: Bool
    let leaseSeconds: Int
    let sampleRate: Int
    let profile: Profile

    init(protocolVersion: Int, healthDefault: Bool, darkGesture: Bool,
         sequencedMotion: Bool, leaseSeconds: Int, sampleRate: Int,
         profile: Profile = .leasedService) {
        self.protocolVersion = protocolVersion
        self.healthDefault = healthDefault
        self.darkGesture = darkGesture
        self.sequencedMotion = sequencedMotion
        self.leaseSeconds = leaseSeconds
        self.sampleRate = sampleRate
        self.profile = profile
    }

    var supported: Bool {
        guard protocolVersion == 1, healthDefault, darkGesture, sampleRate == 25 else { return false }
        switch profile {
        case .leasedService: return sequencedMotion && leaseSeconds == 30
        case .exactA1: return !sequencedMotion && leaseSeconds == 0
        }
    }
}

struct ModeStatus: Equatable {
    let bootID: UInt64
    let session: UInt32
    let mode: RingRuntimeMode
    let charging: Bool
}

struct ModeReply {
    let requestID: UInt32
    let status: ModeStatus
}

/// Production transport remains unattached. UnifiedWire is an offline candidate
/// codec for a separate reviewed GATT service, never an unknown A1 query to stock.
@MainActor
protocol UnifiedModeTransport {
    func capabilities() async throws -> FirmwareCapabilities
    func status(requestID: UInt32) async throws -> ModeReply
    func setGesture(_ enabled: Bool, requestID: UInt32) async throws -> ModeReply
    func renew(session: UInt32, processedSequence: UInt32, requestID: UInt32) async throws -> ModeReply
}

enum UnifiedModeError: LocalizedError {
    case unavailable, uncorrelated, staleStream, exhausted
    var errorDescription: String? {
        switch self {
        case .unavailable: return "This installed firmware does not support the reviewed runtime mode switch."
        case .uncorrelated: return "The mode response did not match this request. Reconnect before continuing."
        case .staleStream: return "Gesture processing is not fresh. The Health-return lease will not be renewed."
        case .exhausted: return "Reconnect before sending further mode requests."
        }
    }
}

@MainActor
protocol A1ModeLink: AnyObject {
    var isReady: Bool { get }
    func writeUART(_ data: Data) throws
}

extension RingManager: A1ModeLink {}

/// Adapter for the exact, fingerprinted Health-default candidate. A1 04 enters
/// temporary Gesture mode; A1 05 followed by A1 02 restores Health. The first
/// mode transition is accepted only after fresh accelerometer notifications.
@MainActor
final class A1UnifiedModeTransport: UnifiedModeTransport {
    typealias MotionHandler = (Data, UInt32, UInt32, TimeInterval) -> Void

    private struct PendingStart {
        let id: UUID
        var packets = 0
        var payloads = Set<Data>()
        let requestID: UInt32
        let continuation: CheckedContinuation<ModeReply, Error>
        let timeout: Task<Void, Never>
    }

    var onMotion: MotionHandler?
    private let link: any A1ModeLink
    private let charging: () -> Bool
    private var current: ModeStatus
    private var sequence: UInt32 = 0
    private var pending: PendingStart?
    private var lastMotionAt: TimeInterval = -.infinity
    private var lastWriteAt: TimeInterval = -.infinity

    init(link: any A1ModeLink, charging: @escaping () -> Bool,
         connectionID: UInt64 = UInt64.random(in: 1...UInt64.max)) {
        self.link = link
        self.charging = charging
        current = ModeStatus(bootID: connectionID, session: 0, mode: .health, charging: charging())
    }

    func capabilities() async throws -> FirmwareCapabilities {
        .init(protocolVersion: 1, healthDefault: true, darkGesture: true,
              sequencedMotion: false, leaseSeconds: 0, sampleRate: 25, profile: .exactA1)
    }

    func status(requestID: UInt32) async throws -> ModeReply {
        try await stopRaw()
        current = .init(bootID: current.bootID, session: 0, mode: .health, charging: charging())
        return .init(requestID: requestID, status: current)
    }

    func setGesture(_ enabled: Bool, requestID: UInt32) async throws -> ModeReply {
        guard link.isReady, pending == nil else { throw RingProtocolError.busy }
        if !enabled {
            try await stopRaw()
            current = .init(bootID: current.bootID, session: 0, mode: .health, charging: charging())
            return .init(requestID: requestID, status: current)
        }
        guard !charging() else { throw FirmwareSwitchError.charging }
        var next = current.session &+ 1
        if next == 0 { next = 1 }
        sequence = 0
        current = .init(bootID: current.bootID, session: next, mode: .enteringGesture, charging: false)
        let id = UUID()
        return try await withCheckedThrowingContinuation { continuation in
            let timeout = Task { [weak self] in
                try? await Task.sleep(for: .seconds(3))
                guard !Task.isCancelled else { return }
                self?.failStart(id: id, error: UnifiedModeError.staleStream)
            }
            pending = PendingStart(id: id, requestID: requestID, continuation: continuation, timeout: timeout)
            Task { @MainActor [weak self] in
                do { try await self?.writeSpaced(ColmiR02Protocol.startRawMotionPacket) }
                catch { self?.failStart(id: id, error: error) }
            }
        }
    }

    func renew(session: UInt32, processedSequence: UInt32, requestID: UInt32) async throws -> ModeReply {
        guard current.mode == .gesture, current.session == session,
              processedSequence != 0, processedSequence <= sequence,
              ProcessInfo.processInfo.systemUptime - lastMotionAt <= 0.5 else {
            throw UnifiedModeError.staleStream
        }
        return .init(requestID: requestID, status: current)
    }

    func receiveMotion(_ packet: Data, at time: TimeInterval) {
        guard packet.count == 16, packet[0] == 0xa1, packet[1] == 0x03,
              ColmiR02Protocol.isValidPacket(packet), time.isFinite else { return }
        sequence &+= 1
        if sequence == 0 { sequence = 1 }
        lastMotionAt = time
        if var waiting = pending {
            waiting.packets += 1
            waiting.payloads.insert(Data(packet[2..<8]))
            pending = waiting
            guard waiting.packets >= 3, waiting.payloads.count >= 2 else { return }
            waiting.timeout.cancel()
            pending = nil
            current = .init(bootID: current.bootID, session: current.session, mode: .gesture, charging: false)
            waiting.continuation.resume(returning: .init(requestID: waiting.requestID, status: current))
            return
        }
        guard current.mode == .gesture else { return }
        onMotion?(packet, current.session, sequence, time)
    }

    func disconnected() {
        if let waiting = pending {
            waiting.timeout.cancel()
            pending = nil
            waiting.continuation.resume(throwing: RingProtocolError.notReady)
        }
        current = .init(bootID: current.bootID, session: 0, mode: .health, charging: charging())
    }

    private func failStart(id: UUID, error: Error) {
        guard let waiting = pending, waiting.id == id else { return }
        waiting.timeout.cancel()
        pending = nil
        current = .init(bootID: current.bootID, session: 0, mode: .health, charging: charging())
        waiting.continuation.resume(throwing: error)
        Task { try? await stopRaw() }
    }

    private func stopRaw() async throws {
        var firstError: Error?
        for packet in ColmiR02Protocol.stopRawMotionPackets {
            do { try await writeSpaced(packet) }
            catch { if firstError == nil { firstError = error } }
        }
        if let firstError { throw firstError }
    }

    private func writeSpaced(_ packet: Data) async throws {
        guard link.isReady else { throw RingProtocolError.notReady }
        let now = ProcessInfo.processInfo.systemUptime
        let wait = 0.15 - (now - lastWriteAt)
        if wait > 0 { try await Task.sleep(for: .seconds(wait)) }
        try Task.checkCancellation()
        guard link.isReady else { throw RingProtocolError.notReady }
        try link.writeUART(packet)
        lastWriteAt = ProcessInfo.processInfo.systemUptime
    }
}

@MainActor
final class UnifiedModeCoordinator: ObservableObject {
    @Published private(set) var status: ModeStatus?
    @Published private(set) var available = false
    @Published private(set) var message = "Unified firmware is not yet approved. Health is the intended default."
    var onModeChange: ((ModeStatus?, ModeStatus?) -> Void)?
    private var transport: (any UnifiedModeTransport)?
    private var connection = UUID()
    private var requestID: UInt32 = 0
    private let gate: RingOperationGate
    private var processed: (session: UInt32, sequence: UInt32, time: TimeInterval)?
    private var lastRenewedSequence: UInt32?
    private var lastRenewal: TimeInterval = -.infinity

    init(gate: RingOperationGate) { self.gate = gate }

    // Internal semantic attachment is for offline fixtures until a reviewed
    // production adapter exists. The shipped app never calls this with BLE.
    func attach(_ transport: any UnifiedModeTransport) async throws {
        disconnected()
        let generation = connection
        guard let op = gate.begin(.mode) else { throw RingProtocolError.busy }
        defer { gate.end(op) }
        let capabilities = try await transport.capabilities()
        guard generation == connection, capabilities.supported else { throw UnifiedModeError.unavailable }
        self.transport = transport
        do {
            var id = try nextID()
            var reply = try await transport.status(requestID: id)
            guard generation == connection, reply.requestID == id else { throw UnifiedModeError.uncorrelated }
            // A new app connection never silently adopts an old Gesture session.
            if reply.status.mode == .gesture || reply.status.mode == .enteringGesture {
                id = try nextID()
                reply = try await transport.setGesture(false, requestID: id)
            }
            try accept(reply, id: id, connection: generation)
            available = true
        } catch {
            if generation == connection { disconnected() }
            throw error
        }
    }

    func disconnected() {
        let previous = status
        connection = UUID()
        transport = nil
        available = false
        status = nil // Firmware should return Health; the disconnected app cannot attest it.
        processed = nil
        lastRenewedSequence = nil
        lastRenewal = -.infinity
        onModeChange?(previous, nil)
    }

    func setGesture(_ enabled: Bool) async throws {
        guard available, let transport else { throw UnifiedModeError.unavailable }
        if enabled, status?.charging != false { throw FirmwareSwitchError.charging }
        guard let op = gate.begin(.mode) else { throw RingProtocolError.busy }
        defer { gate.end(op) }
        let id = try nextID(), generation = connection
        do {
            let reply = try await transport.setGesture(enabled, requestID: id)
            try accept(reply, id: id, connection: generation)
        } catch {
            if generation == connection { disconnected() }
            throw error
        }
    }

    /// Called only after successful inference processing, not merely receipt.
    func didProcess(session: UInt32, sequence: UInt32, at monotonicTime: TimeInterval) {
        guard monotonicTime.isFinite, status?.mode == .gesture, status?.session == session else { return }
        if let previous = processed {
            let delta = sequence &- previous.sequence
            guard monotonicTime > previous.time, delta > 0, delta < 0x80000000 else { return }
        }
        processed = (session, sequence, monotonicTime)
    }

    func heartbeat(at now: TimeInterval) async throws {
        guard now.isFinite, now - lastRenewal >= 5 else { return }
        guard available, let transport, let status, status.mode == .gesture, !status.charging,
              let processed, processed.session == status.session,
              now >= processed.time, now - processed.time <= 0.5,
              lastRenewedSequence != processed.sequence else { throw UnifiedModeError.staleStream }
        guard let op = gate.begin(.mode) else { throw RingProtocolError.busy }
        defer { gate.end(op) }
        let id = try nextID(), generation = connection
        do {
            let reply = try await transport.renew(session: status.session, processedSequence: processed.sequence, requestID: id)
            // Validate the renewal before accept publishes to Combine or coverage
            // observers. A later rejection cannot undo a persisted Health interval.
            guard reply.status.bootID == status.bootID, reply.status.session == status.session,
                  reply.status.mode == .gesture, !reply.status.charging else { throw UnifiedModeError.staleStream }
            try accept(reply, id: id, connection: generation)
            lastRenewal = now
            lastRenewedSequence = processed.sequence
        } catch {
            if generation == connection { disconnected() }
            throw error
        }
    }

    private func nextID() throws -> UInt32 {
        guard requestID < UInt32.max else { throw UnifiedModeError.exhausted }
        requestID += 1
        return requestID
    }

    private func accept(_ reply: ModeReply, id: UInt32, connection generation: UUID) throws {
        guard generation == connection, reply.requestID == id else { throw UnifiedModeError.uncorrelated }
        let previous = status
        status = reply.status
        if previous != status {
            processed = nil
            lastRenewedSequence = nil
            lastRenewal = -.infinity
            onModeChange?(previous, status)
        }
        message = "Ring reports \(reply.status.mode.rawValue)"
    }
}

struct HealthCoverage: Codable, Equatable {
    enum Reason: String, Codable { case gestureSession, disconnected, unverifiedFirmware }
    let started: Date
    var ended: Date?
    let reason: Reason
    // Steps/sleep during raw sessions are unverified, not invented zeros.
    let opticalMeasurementsAvailable: Bool
    let stepsAndSleepVerified: Bool
}

extension UnifiedWire {
    /// Only a COMPLETE Receiver result may enter this conversion. Revalidate
    /// before any coordinator/coverage publication; negative replies never become
    /// ModeReply. This does not attest physical postconditions or authorize BLE.
    static func modeReply(_ body: [UInt8], requestID: UInt32,
                          operation: Operation, bootID: UInt64) throws -> ModeReply {
        guard requestID != 0, validBody(body, kind: .reply, bootID: bootID),
              body[0] == operation.rawValue else { throw Failure.invalid }
        guard body[1] == 0 else { throw Failure.rejected }
        let modes: [RingRuntimeMode] = [.health, .enteringGesture, .gesture, .returningHealth, .fault]
        return .init(requestID: requestID,
                     status: .init(bootID: bootID, session: word(body, 12),
                                   mode: modes[Int(body[2])], charging: body[3] == 1))
    }
}
