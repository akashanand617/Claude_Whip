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
        case .exactA1: return !sequencedMotion && (leaseSeconds == 0 || leaseSeconds == 10)
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

/// UnifiedWire is the retained offline codec for the abandoned separate-service
/// design. The production RT12COL path uses the exact A1 adapter below and never
/// sends an unknown capability query to stock firmware.
@MainActor
protocol UnifiedModeTransport {
    func capabilities() async throws -> FirmwareCapabilities
    func status(requestID: UInt32) async throws -> ModeReply
    func setGesture(_ enabled: Bool, requestID: UInt32) async throws -> ModeReply
    func renew(session: UInt32, processedSequence: UInt32, requestID: UInt32) async throws -> ModeReply
}

enum UnifiedModeError: LocalizedError {
    case unavailable, uncorrelated, staleStream, renewalBoundary, exhausted
    var errorDescription: String? {
        switch self {
        case .unavailable: return "This installed firmware does not support the reviewed runtime mode switch."
        case .uncorrelated: return "The mode response did not match this request. Reconnect before continuing."
        case .staleStream: return "Gesture processing is not fresh. The Health-return lease will not be renewed."
        case .renewalBoundary:
            return "Motion timing or freshness changed across the Gesture lease renewal; the lease was not confirmed."
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

    /// Evidence from one lease renewal. The gate decides only on the judged
    /// window's mean spacing and duplicates, and on the largest post-write
    /// spacing (`failedRenewalChecks`); medians and the boundary spacing are
    /// journaled, not enforced. On a ~30 ms connection-event grid those two
    /// moved across their old limits (1.5x median, 120 ms) with ordinary missed
    /// events, and with several notifications per connection event a near-zero
    /// boundary spacing cannot show that a packet was caused by the write.
    ///
    /// The judged window is ten spacings from `judgedStart`: from the last
    /// baseline sample when delivery ran without a stall, otherwise from after
    /// the backlog that followed the last stall. Notifications held behind a
    /// stall across the write arrive bunched and may all predate the write,
    /// so they never decide the gate.
    struct RenewalBoundaryMetrics: Equatable {
        let baselineMedianSpacing: TimeInterval
        let renewalMedianSpacing: TimeInterval
        /// Last baseline sample to the first post-write sample.
        let boundarySpacing: TimeInterval
        /// Largest spacing from the last baseline sample through every
        /// post-write sample received, stalls included.
        let renewalMaximumSpacing: TimeInterval
        let baselineDuplicateFraction: Double
        let renewalDuplicateFraction: Double
        /// (last baseline - first baseline) / 9.
        let baselineMeanSpacing: TimeInterval
        /// (last judged sample - judged start) / 10.
        let renewalMeanSpacing: TimeInterval
        let baselineDuplicates: Int
        let renewalDuplicates: Int
    }

    /// One renewal attempt, passed or failed, for the lifecycle journal.
    struct RenewalReport: Equatable {
        enum Cause: Equatable {
            case criteria
            case timeout(samplesAfterWrite: Int)
            /// A non-positive or non-finite spacing: no metrics.
            case nonmonotonic
            case writeError
            case disconnected

            var journalName: String {
                switch self {
                case .criteria: return "criteria"
                case .timeout: return "timeout"
                case .nonmonotonic: return "nonmonotonic"
                case .writeError: return "write_error"
                case .disconnected: return "disconnected"
                }
            }
        }

        let passed: Bool
        /// Nil when passed.
        let cause: Cause?
        /// Any of rate_low, rate_high, max_gap, duplicates.
        let failedChecks: [String]
        let metrics: RenewalBoundaryMetrics?
        /// Nine baseline spacings, then the spacings from the last baseline
        /// sample through every post-write sample received, in ms.
        let baselineSpacingsMS: [Double]
        let renewalSpacingsMS: [Double]
        let writeUptime: TimeInterval
        let writeAfterBaselineMS: Double
        /// Post-write evidence stamped before the write (its delegate callback
        /// ran before the write, its main-actor hop after).
        let postBeforeWrite: Int
        /// Where the judged window starts in [last baseline] + post-write
        /// samples, i.e. how many post-write samples it skipped as backlog;
        /// nil when that point never arrived.
        var judgedFrom: Int? = nil
        /// Post-write spacings over `renewalStallSpacing`.
        var stalls = 0
        /// Samples stamped after the write that arrived under
        /// `GestureFreshness.quarantineMinSpacing` after the previous one.
        var backToBackAfterWrite = 0

        var fields: [String: Any] {
            var fields: [String: Any] = [
                "outcome": passed ? "passed" : "failed",
                "write_uptime": Self.rounded(writeUptime, scale: 1_000),
                "write_after_baseline_ms": Self.rounded(writeAfterBaselineMS, scale: 10),
                "post_before_write": postBeforeWrite,
                "post_samples": renewalSpacingsMS.count,
                "judged_from": judgedFrom.map { $0 as Any } ?? NSNull(),
                "stalls": stalls,
                "back_to_back_after_write": backToBackAfterWrite,
            ]
            if let cause {
                fields["cause"] = cause.journalName
                if case .timeout(let count) = cause { fields["samples_after_write"] = count }
            }
            if !failedChecks.isEmpty { fields["failed_checks"] = failedChecks }
            if let metrics {
                fields["mean_ms"] = Self.rounded(metrics.renewalMeanSpacing * 1_000, scale: 10)
                fields["max_ms"] = Self.rounded(metrics.renewalMaximumSpacing * 1_000, scale: 10)
                fields["boundary_ms"] = Self.rounded(metrics.boundarySpacing * 1_000, scale: 10)
                fields["median_ms"] = Self.rounded(metrics.renewalMedianSpacing * 1_000, scale: 10)
                fields["baseline_mean_ms"] = Self.rounded(metrics.baselineMeanSpacing * 1_000, scale: 10)
                fields["baseline_median_ms"] = Self.rounded(metrics.baselineMedianSpacing * 1_000, scale: 10)
                fields["dup_baseline"] = metrics.baselineDuplicates
                fields["dup_renewal"] = metrics.renewalDuplicates
            }
            if !passed {
                fields["baseline_spacings_ms"] = baselineSpacingsMS.map { Self.rounded($0, scale: 10) }
                fields["renewal_spacings_ms"] = renewalSpacingsMS.map { Self.rounded($0, scale: 10) }
            }
            return fields
        }

        private static func rounded(_ value: Double, scale: Double) -> Any {
            value.isFinite ? (value * scale).rounded() / scale : NSNull()
        }
    }

    private struct MotionObservation {
        let payload: Data
        let time: TimeInterval
    }

    private struct PendingStart {
        let id: UUID
        /// Entry evidence counts only once A1 04 has been written: packets
        /// still in flight from a stream a heal just stopped never confirm it.
        var armed = false
        var packets = 0
        var payloads = Set<Data>()
        let requestID: UInt32
        let continuation: CheckedContinuation<ModeReply, Error>
        let timeout: Task<Void, Never>
    }

    private struct PendingRenewal {
        let id: UUID
        let baseline: [MotionObservation]
        var after: [MotionObservation] = []
        let requestID: UInt32
        let writeUptime: TimeInterval
        let continuation: CheckedContinuation<ModeReply, Error>
        let timeout: Task<Void, Never>
    }

    var onMotion: MotionHandler?
    /// Every renewal attempt's report, published before its caller resumes.
    var onRenewalReport: ((RenewalReport) -> Void)?
    private let link: any A1ModeLink
    private let charging: () -> Bool
    private let clock: () -> TimeInterval
    private let requiresMotionHold: Bool
    private let firmwareLeaseSeconds: Int
    private var current: ModeStatus
    private var sequence: UInt32 = 0
    private var pending: PendingStart?
    private var pendingRenewal: PendingRenewal?
    private var renewalWriteInProgress = false
    private var hidWriteInProgress = false
    /// False before fresh Gesture entry, as soon as a stop begins, and after
    /// disconnect. A queued HID action re-checks this after its spacing wait.
    private var hidCommandsAllowed = false
    private var motionHistory: [MotionObservation] = []
    private var lastMotionAt: TimeInterval = -.infinity
    private var lastWriteAt: TimeInterval = -.infinity
    /// The last A1 04 that started or renewed the firmware lease.
    private var lastLeaseWriteAt: TimeInterval = -.infinity
    /// Set when a renewal starts, and again once its metrics exist; never
    /// carries a previous renewal's values.
    private(set) var lastRenewalMetrics: RenewalBoundaryMetrics?
    private(set) var lastRenewalReport: RenewalReport?
    /// Which guard refused the last `renew` with `staleStream` (journal only).
    private(set) var lastRejection: String?

    private static let renewalSampleCount = 10
    /// A stall just under the ceiling (0.5 s), its backlog and a quarantine
    /// that ends on the time fallback (0.5 s), then ten judged spacings at
    /// the slowest passing mean (0.64 s). The mode gate is then held for at
    /// most ~1.9 s with the write-slot wait, inside the sequencer's 2.5 s
    /// stop retry window and far inside the 10 s firmware lease.
    static let renewalTimeout = Duration.milliseconds(1_750)
    /// A post-write spacing over this is a delivery stall: the notifications
    /// held behind it arrive bunched and may all predate the write, so the
    /// judged window restarts after them. Above the ~30 ms connection-event
    /// lattice's ordinary four-event gap (120 ms); a shorter stall holds back
    /// at most three 40 ms samples, which the mean does not separate from
    /// fresh evidence.
    static let renewalStallSpacing: TimeInterval = 0.15
    /// 0.6-1.6x the 40 ms period that `FirmwareCapabilities.supported` pins
    /// (sampleRate == 25). Derive it from the capabilities if that ever changes.
    static let renewalMeanSpacing: ClosedRange<TimeInterval> = 0.024...0.064
    /// The same stall a running `GestureSession` survives once. The lease-only
    /// V6/V7 renewal changes only the lease byte, so a longer post-write gap is
    /// link or main-queue delivery, which the session owns.
    static var renewalMaximumSpacing: TimeInterval { GestureFreshness.stallCeiling }

    init(link: any A1ModeLink, charging: @escaping () -> Bool,
         requiresMotionHold: Bool = false,
         firmwareLeaseSeconds: Int = 0,
         connectionID: UInt64 = UInt64.random(in: 1...UInt64.max),
         clock: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }) {
        precondition(firmwareLeaseSeconds == 0 || firmwareLeaseSeconds == 10)
        self.link = link
        self.charging = charging
        self.clock = clock
        self.requiresMotionHold = requiresMotionHold
        self.firmwareLeaseSeconds = firmwareLeaseSeconds
        current = ModeStatus(bootID: connectionID, session: 0, mode: .health, charging: charging())
    }

    /// A renewal is refused once the last lease write is this old: the
    /// firmware lease may have lapsed, and an A1 04 would then re-enter
    /// (restart the producer) instead of renewing. Normal cadence is ~5.5 s.
    var leaseRenewalDeadline: TimeInterval { Double(firmwareLeaseSeconds) - 1 }
    /// The firmware's Health-return lease; 0 when the image has none.
    var leaseSeconds: Int { firmwareLeaseSeconds }
    /// Seconds since the last A1 04 that started or renewed the lease; nil before one.
    var leaseAge: TimeInterval? {
        let age = clock() - lastLeaseWriteAt
        return age.isFinite ? age : nil
    }
    /// The transport's own view of the ring (tests and journal).
    var currentStatus: ModeStatus { current }

    func capabilities() async throws -> FirmwareCapabilities {
        .init(protocolVersion: 1, healthDefault: true, darkGesture: true,
              sequencedMotion: false, leaseSeconds: firmwareLeaseSeconds,
              sampleRate: 25, profile: .exactA1)
    }

    /// V8+ caller contract. AppModel owns the exact-image capability gate;
    /// this transport owns runtime freshness and serialization with lease/mode
    /// writes. No HID report is emitted during entry, healing, or return.
    func sendHIDCommand(_ command: RingHIDCommand) async throws {
        try await reserveHIDWriteLane()
        defer { hidWriteInProgress = false }
        try await waitForWriteSlot()
        guard link.isReady, current.mode == .gesture, hidCommandsAllowed,
              pending == nil, pendingRenewal == nil, !renewalWriteInProgress else {
            throw RingProtocolError.busy
        }
        try writePrepared(ColmiR02Protocol.hidActionPacket(command))
    }

    /// Renewals can hold the mode lane for the post-write evidence window.
    /// A recognized gesture during that window is still current, so wait for
    /// the renewal instead of losing the action as `busy`. Every suspension
    /// rechecks session ownership. A stop flips `hidCommandsAllowed` before it
    /// retries the renewal-held mode gate, which withdraws queued actions.
    private func reserveHIDWriteLane() async throws {
        while true {
            guard link.isReady, current.mode == .gesture, hidCommandsAllowed,
                  pending == nil else { throw RingProtocolError.busy }
            if pendingRenewal == nil, !renewalWriteInProgress, !hidWriteInProgress {
                hidWriteInProgress = true
                return
            }
            try await Task.sleep(for: .milliseconds(10))
            try Task.checkCancellation()
        }
    }

    func status(requestID: UInt32) async throws -> ModeReply {
        // An attach (including a mode recovery re-attaching this transport)
        // starts clean: no guard of an earlier session may name a later end.
        lastRejection = nil
        hidCommandsAllowed = false
        try await stopRaw()
        current = .init(bootID: current.bootID, session: 0, mode: .health, charging: charging())
        return .init(requestID: requestID, status: current)
    }

    func setGesture(_ enabled: Bool, requestID: UInt32) async throws -> ModeReply {
        guard link.isReady else { throw RingProtocolError.notReady }
        if !enabled {
            // Stop owns priority over an HID command queued behind renewal.
            // The sequencer may have to retry the mode gate, but no queued A2
            // is allowed to escape during that wait.
            hidCommandsAllowed = false
            guard pending == nil, pendingRenewal == nil,
                  !renewalWriteInProgress else { throw RingProtocolError.busy }
            try await stopRaw()
            current = .init(bootID: current.bootID, session: 0, mode: .health, charging: charging())
            return .init(requestID: requestID, status: current)
        }
        guard pending == nil, pendingRenewal == nil,
              !renewalWriteInProgress else { throw RingProtocolError.busy }
        guard !hidWriteInProgress else { throw RingProtocolError.busy }
        guard !charging() else { throw FirmwareSwitchError.charging }
        hidCommandsAllowed = false
        var next = current.session &+ 1
        if next == 0 { next = 1 }
        sequence = 0
        motionHistory.removeAll(keepingCapacity: true)
        lastRenewalMetrics = nil
        lastRenewalReport = nil
        lastRejection = nil
        lastLeaseWriteAt = -.infinity
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
                do {
                    try await self?.writeSpaced(ColmiR02Protocol.startRawMotionPacket)
                    self?.leaseWritten()
                    self?.armStart(id: id)
                    if self?.requiresMotionHold == true {
                        try await self?.writeSpaced(ColmiR02Protocol.gestureMotionHoldPacket(enabled: true))
                    }
                }
                catch { self?.entryWriteFailed(id: id, session: next, error: error) }
            }
        }
    }

    func renew(session: UInt32, processedSequence: UInt32, requestID: UInt32) async throws -> ModeReply {
        lastRejection = nil
        lastRenewalMetrics = nil
        lastRenewalReport = nil
        if let reason = staleRenewalReason(session: session, processedSequence: processedSequence) {
            throw reject(reason)
        }
        guard pending == nil, pendingRenewal == nil, !renewalWriteInProgress,
              !hidWriteInProgress else {
            throw RingProtocolError.busy
        }
        guard firmwareLeaseSeconds > 0 else {
            return .init(requestID: requestID, status: current)
        }
        guard motionHistory.count >= Self.renewalSampleCount else {
            throw reject("history=\(motionHistory.count)")
        }

        // The corrected firmware interprets A1 04 as a lease-only operation
        // when Gesture is active. Do not accept the write itself as proof. Wait
        // out the UART throttle first, snapshot the ten packets immediately
        // before the exact write, then arm the post-boundary collector before
        // writeUART can synchronously hand anything back to us.
        renewalWriteInProgress = true
        do {
            try await waitForWriteSlot()
        } catch {
            renewalWriteInProgress = false
            throw error
        }
        let leaseAge = clock() - lastLeaseWriteAt
        let reason = staleRenewalReason(session: session, processedSequence: nil)
            ?? (motionHistory.count >= Self.renewalSampleCount ? nil : "history=\(motionHistory.count)")
            ?? (leaseAge <= leaseRenewalDeadline ? nil : String(format: "lease_age=%.3f", leaseAge))
        if let reason {
            renewalWriteInProgress = false
            throw reject(reason)
        }
        let baseline = Array(motionHistory.suffix(Self.renewalSampleCount))
        let id = UUID()
        return try await withCheckedThrowingContinuation { continuation in
            let timeout = Task { [weak self] in
                try? await Task.sleep(for: Self.renewalTimeout)
                guard !Task.isCancelled else { return }
                self?.timeOutRenewal(id: id)
            }
            pendingRenewal = PendingRenewal(
                id: id, baseline: baseline, requestID: requestID, writeUptime: clock(),
                continuation: continuation, timeout: timeout
            )
            do {
                try writePrepared(ColmiR02Protocol.startRawMotionPacket)
                leaseWritten()
                renewalWriteInProgress = false
            } catch {
                renewalWriteInProgress = false
                failRenewal(id: id, error: error, cause: .writeError)
            }
        }
    }

    /// Nil when Gesture is active for `session` and motion arrived within
    /// 0.5 s; `processedSequence` is checked only when given.
    private func staleRenewalReason(session: UInt32, processedSequence: UInt32?) -> String? {
        guard current.mode == .gesture else { return "not_gesture" }
        guard current.session == session else { return "session_mismatch" }
        if let processedSequence, processedSequence == 0 || processedSequence > sequence {
            return "processed_seq"
        }
        let motionAge = clock() - lastMotionAt
        guard motionAge <= 0.5 else { return String(format: "motion_age=%.3f", motionAge) }
        return nil
    }

    private func reject(_ reason: String) -> UnifiedModeError {
        lastRejection = reason
        return .staleStream
    }

    private func leaseWritten() { lastLeaseWriteAt = lastWriteAt }

    func receiveMotion(_ packet: Data, at time: TimeInterval) {
        if packet.count == 16, packet[0] == 0xa1, packet[1] == 0xff, ColmiR02Protocol.isValidPacket(packet) {
            receiveRefusal()
            return
        }
        guard packet.count == 16, packet[0] == 0xa1, packet[1] == 0x03,
              ColmiR02Protocol.isValidPacket(packet), time.isFinite else { return }
        sequence &+= 1
        if sequence == 0 { sequence = 1 }
        lastMotionAt = time
        let observation = MotionObservation(payload: Data(packet[2..<8]), time: time)
        motionHistory.append(observation)
        if motionHistory.count > Self.renewalSampleCount {
            motionHistory.removeFirst(motionHistory.count - Self.renewalSampleCount)
        }
        if var waiting = pending {
            // Before A1 04 is written nothing counts toward the entry.
            guard waiting.armed else { return }
            waiting.packets += 1
            waiting.payloads.insert(Data(packet[2..<8]))
            pending = waiting
            guard waiting.packets >= 3, waiting.payloads.count >= 2 else { return }
            waiting.timeout.cancel()
            pending = nil
            current = .init(bootID: current.bootID, session: current.session, mode: .gesture, charging: false)
            hidCommandsAllowed = true
            waiting.continuation.resume(returning: .init(requestID: waiting.requestID, status: current))
            return
        }
        guard current.mode == .gesture else { return }
        if var renewing = pendingRenewal {
            renewing.after.append(observation)
            pendingRenewal = renewing
            evaluateRenewal(renewing)
        }
        onMotion?(packet, current.session, sequence, time)
    }

    func disconnected() {
        if let waiting = pending {
            waiting.timeout.cancel()
            pending = nil
            waiting.continuation.resume(throwing: RingProtocolError.notReady)
        }
        if let waiting = pendingRenewal {
            waiting.timeout.cancel()
            pendingRenewal = nil
            publish(report(waiting, cause: .disconnected, failedChecks: [], metrics: nil))
            waiting.continuation.resume(throwing: RingProtocolError.notReady)
        }
        renewalWriteInProgress = false
        hidWriteInProgress = false
        hidCommandsAllowed = false
        motionHistory.removeAll(keepingCapacity: true)
        lastLeaseWriteAt = -.infinity
        lastRejection = nil
        current = .init(bootID: current.bootID, session: 0, mode: .health, charging: charging())
    }

    /// A1 FF: the firmware refused an A1 command. RT02 stock sends it for every
    /// A1 command while charging (`sub_02d4e`); RT12 V6/V7 behaviour is
    /// unverified. Receive-only: it fails a pending entry as charging (the
    /// keeper needs two consecutive refusals before it ends a session) and is
    /// otherwise ignored.
    private func receiveRefusal() {
        guard let waiting = pending else { return }
        failStart(id: waiting.id, error: FirmwareSwitchError.charging)
    }

    private func armStart(id: UUID) {
        guard var waiting = pending, waiting.id == id else { return }
        waiting.armed = true
        pending = waiting
    }

    /// An entry write failed. Before the entry resolved, it fails the entry;
    /// after it (the RT12 hold write, once fresh motion already confirmed
    /// Gesture), the transport stops reporting a Gesture it did not finish
    /// entering: it returns to Health with the audited stops, and the
    /// coordinator's next heartbeat sees `not_gesture`.
    private func entryWriteFailed(id: UUID, session: UInt32, error: Error) {
        if let waiting = pending, waiting.id == id {
            failStart(id: id, error: error)
            return
        }
        guard pending == nil, current.session == session, current.mode == .gesture else { return }
        hidCommandsAllowed = false
        current = .init(bootID: current.bootID, session: 0, mode: .health, charging: charging())
        Task { try? await stopRaw() }
    }

    private func failStart(id: UUID, error: Error) {
        guard let waiting = pending, waiting.id == id else { return }
        waiting.timeout.cancel()
        pending = nil
        hidCommandsAllowed = false
        current = .init(bootID: current.bootID, session: 0, mode: .health, charging: charging())
        waiting.continuation.resume(throwing: error)
        Task { try? await stopRaw() }
    }

    /// Pure gate over one renewal's metrics; empty means it passes. Rejects a
    /// stopped, half-rate or bursting producer (judged-window mean), a stall
    /// the session would not survive (max; `evaluateRenewal` also fails it as
    /// soon as it arrives) and paired or frozen payloads (judged-window
    /// duplicates against the pre-write baseline). Because the judged window
    /// follows the backlog of any stall over `renewalStallSpacing`, a stall
    /// across the write cannot pass a stopped, half-rate or frozen producer on
    /// evidence that predates the write; bunching under that spacing (at most
    /// three samples) is not separated and can still bias the mean low.
    static func failedRenewalChecks(_ metrics: RenewalBoundaryMetrics) -> [String] {
        var failed: [String] = []
        if metrics.renewalMeanSpacing < renewalMeanSpacing.lowerBound { failed.append("rate_high") }
        if metrics.renewalMeanSpacing > renewalMeanSpacing.upperBound { failed.append("rate_low") }
        if metrics.renewalMaximumSpacing > renewalMaximumSpacing { failed.append("max_gap") }
        let allowedDuplicateFraction = min(
            1, metrics.baselineDuplicateFraction + 1 / Double(renewalSampleCount)
        )
        if metrics.renewalDuplicateFraction > allowedDuplicateFraction + 1e-12 { failed.append("duplicates") }
        return failed
    }

    /// Where the judged window starts in `times`, the receipt times of the
    /// last baseline sample and every post-write sample. 0 when no spacing is
    /// over `renewalStallSpacing`. Otherwise, after the last such stall, the
    /// first sample that begins `GestureFreshness.quarantineSpacings`
    /// consecutive spacings of at least `quarantineMinSpacing` (the
    /// time-compressed backlog has passed), or that arrives
    /// `GestureFreshness.quarantine` after the stall, as `GestureSession`
    /// quarantines. Nil while that sample cannot be known yet; once known it
    /// changes only if a later stall arrives.
    static func judgedStart(_ times: [TimeInterval]) -> Int? {
        let spacings = zip(times, times.dropFirst()).map { $1 - $0 }
        guard let stall = spacings.lastIndex(where: { $0 > renewalStallSpacing }) else { return 0 }
        let resumed = stall + 1
        let run = GestureFreshness.quarantineSpacings
        for start in resumed..<times.count {
            if times[start] - times[resumed] >= GestureFreshness.quarantine { return start }
            guard start + run <= spacings.count else { return nil }
            if spacings[start..<(start + run)].allSatisfy({ $0 >= GestureFreshness.quarantineMinSpacing }) {
                return start
            }
        }
        return nil
    }

    /// Runs as each post-write sample arrives. A non-positive spacing or one
    /// over the ceiling fails at once; otherwise the renewal is judged once
    /// ten spacings follow `judgedStart`.
    private func evaluateRenewal(_ waiting: PendingRenewal) {
        guard pendingRenewal?.id == waiting.id, let lastBaseline = waiting.baseline.last,
              let newest = waiting.after.last else { return }
        let previous = waiting.after.count > 1 ? waiting.after[waiting.after.count - 2] : lastBaseline
        let spacing = newest.time - previous.time
        guard spacing.isFinite, spacing > 0 else {
            failRenewal(id: waiting.id, error: UnifiedModeError.renewalBoundary, cause: .nonmonotonic)
            return
        }
        guard spacing <= Self.renewalMaximumSpacing else {
            failRenewal(id: waiting.id, error: UnifiedModeError.renewalBoundary,
                        cause: .criteria, failedChecks: ["max_gap"])
            return
        }
        let series = [lastBaseline] + waiting.after
        guard let start = Self.judgedStart(series.map(\.time)),
              series.count > start + Self.renewalSampleCount else { return }
        guard let metrics = Self.renewalMetrics(baseline: waiting.baseline, series: series, judgedStart: start) else {
            failRenewal(id: waiting.id, error: UnifiedModeError.renewalBoundary, cause: .nonmonotonic)
            return
        }
        lastRenewalMetrics = metrics
        let failed = Self.failedRenewalChecks(metrics)
        guard failed.isEmpty else {
            failRenewal(id: waiting.id, error: UnifiedModeError.renewalBoundary,
                        cause: .criteria, failedChecks: failed, metrics: metrics)
            return
        }
        waiting.timeout.cancel()
        pendingRenewal = nil
        publish(report(waiting, cause: nil, failedChecks: [], metrics: metrics))
        waiting.continuation.resume(returning: .init(requestID: waiting.requestID, status: current))
    }

    private func timeOutRenewal(id: UUID) {
        guard let waiting = pendingRenewal, waiting.id == id else { return }
        failRenewal(id: id, error: UnifiedModeError.renewalBoundary,
                    cause: .timeout(samplesAfterWrite: waiting.after.count))
    }

    private func failRenewal(id: UUID, error: Error, cause: RenewalReport.Cause,
                             failedChecks: [String] = [], metrics: RenewalBoundaryMetrics? = nil) {
        guard let waiting = pendingRenewal, waiting.id == id else { return }
        waiting.timeout.cancel()
        pendingRenewal = nil
        publish(report(waiting, cause: cause, failedChecks: failedChecks, metrics: metrics))
        // A failed gate is a missed renewal, never a stop: Gesture stays
        // current and the caller decides (retry at the next heartbeat while the
        // lease is valid, or heal on a bad source). The firmware lease remains
        // the hardware backstop if nothing renews it.
        waiting.continuation.resume(throwing: error)
    }

    private func report(_ waiting: PendingRenewal, cause: RenewalReport.Cause?,
                        failedChecks: [String], metrics: RenewalBoundaryMetrics?) -> RenewalReport {
        let series = Array(waiting.baseline.suffix(1)) + waiting.after
        let spacings = zip(series, series.dropFirst()).map { $1.time - $0.time }
        let lastBaseline = waiting.baseline.last?.time ?? waiting.writeUptime
        return RenewalReport(
            passed: cause == nil, cause: cause, failedChecks: failedChecks, metrics: metrics,
            baselineSpacingsMS: zip(waiting.baseline, waiting.baseline.dropFirst()).map { ($1.time - $0.time) * 1_000 },
            renewalSpacingsMS: spacings.map { $0 * 1_000 },
            writeUptime: waiting.writeUptime,
            writeAfterBaselineMS: (waiting.writeUptime - lastBaseline) * 1_000,
            postBeforeWrite: waiting.after.filter { $0.time < waiting.writeUptime }.count,
            judgedFrom: Self.judgedStart(series.map(\.time)),
            stalls: spacings.filter { $0 > Self.renewalStallSpacing }.count,
            backToBackAfterWrite: zip(series, series.dropFirst()).filter { pair in
                pair.1.time >= waiting.writeUptime
                    && pair.1.time - pair.0.time < GestureFreshness.quarantineMinSpacing
            }.count
        )
    }

    private func publish(_ report: RenewalReport) {
        lastRenewalReport = report
        onRenewalReport?(report)
    }

    /// `series` is [last baseline] + post-write samples; the judged window is
    /// its eleven samples from `start`.
    private static func renewalMetrics(
        baseline: [MotionObservation], series: [MotionObservation], judgedStart start: Int
    ) -> RenewalBoundaryMetrics? {
        guard baseline.count == renewalSampleCount, start >= 0, series.count > start + renewalSampleCount,
              let firstBefore = baseline.first, let lastBefore = baseline.last else { return nil }
        let window = Array(series[start...(start + renewalSampleCount)])
        func spacings(_ samples: [MotionObservation]) -> [TimeInterval] {
            zip(samples, samples.dropFirst()).map { $1.time - $0.time }
        }
        func duplicates(_ samples: [MotionObservation]) -> Int {
            zip(samples, samples.dropFirst()).filter { $0.payload == $1.payload }.count
        }
        let baselineSpacings = spacings(baseline)
        let seriesSpacings = spacings(series)
        let windowSpacings = spacings(window)
        guard baselineSpacings.allSatisfy({ $0.isFinite && $0 > 0 }),
              seriesSpacings.allSatisfy({ $0.isFinite && $0 > 0 }) else { return nil }
        let baselineDuplicates = duplicates(baseline)
        let renewalDuplicates = duplicates(window)
        return RenewalBoundaryMetrics(
            baselineMedianSpacing: median(baselineSpacings),
            renewalMedianSpacing: median(windowSpacings),
            boundarySpacing: seriesSpacings[0],
            renewalMaximumSpacing: seriesSpacings.max()!,
            baselineDuplicateFraction: Double(baselineDuplicates) / Double(baselineSpacings.count),
            renewalDuplicateFraction: Double(renewalDuplicates) / Double(windowSpacings.count),
            baselineMeanSpacing: (lastBefore.time - firstBefore.time) / Double(baselineSpacings.count),
            renewalMeanSpacing: (window[window.count - 1].time - window[0].time) / Double(windowSpacings.count),
            baselineDuplicates: baselineDuplicates,
            renewalDuplicates: renewalDuplicates
        )
    }

    private static func median(_ values: [TimeInterval]) -> TimeInterval {
        let values = values.sorted()
        let middle = values.count / 2
        return values.count.isMultiple(of: 2)
            ? (values[middle - 1] + values[middle]) / 2
            : values[middle]
    }

    private func stopRaw() async throws {
        var firstError: Error?
        var packets = ColmiR02Protocol.stopRawMotionPackets
        if requiresMotionHold {
            // Preserve the previously measured host lifecycle: stop raw first,
            // then release the volatile STK hold so stock Health owns the sensor.
            // The RT12 candidate still requires its own physical validation.
            packets.append(ColmiR02Protocol.gestureMotionHoldPacket(enabled: false))
        }
        for packet in packets {
            do { try await writeSpaced(packet) }
            catch { if firstError == nil { firstError = error } }
        }
        motionHistory.removeAll(keepingCapacity: true)
        if let firstError { throw firstError }
    }

    private func waitForWriteSlot() async throws {
        while true {
            guard link.isReady else { throw RingProtocolError.notReady }
            let observedWrite = lastWriteAt
            let wait = 0.15 - (clock() - observedWrite)
            if wait > 0 { try await Task.sleep(for: .seconds(wait)) }
            try Task.checkCancellation()
            guard link.isReady else { throw RingProtocolError.notReady }
            // Another main-actor task may have written while this one slept.
            // Recompute its full spacing instead of emitting a back-to-back
            // action at the stale deadline.
            if lastWriteAt == observedWrite, clock() - lastWriteAt >= 0.15 { return }
        }
    }

    private func writePrepared(_ packet: Data) throws {
        guard link.isReady else { throw RingProtocolError.notReady }
        try link.writeUART(packet)
        lastWriteAt = clock()
    }

    private func writeSpaced(_ packet: Data) async throws {
        try await waitForWriteSlot()
        try writePrepared(packet)
    }
}

@MainActor
final class UnifiedModeCoordinator: ObservableObject {
    @Published private(set) var status: ModeStatus?
    @Published private(set) var available = false
    @Published private(set) var message = "Unified runtime control is unavailable. Health remains the default."
    var onModeChange: ((ModeStatus?, ModeStatus?) -> Void)?
    private var transport: (any UnifiedModeTransport)?
    private var connection = UUID()
    private var requestID: UInt32 = 0
    private let gate: RingOperationGate
    private var processed: (session: UInt32, sequence: UInt32, time: TimeInterval)?
    private var lastRenewedSequence: UInt32?
    private var lastRenewal: TimeInterval = -.infinity
    /// Which heartbeat guard threw `staleStream` last (journal only).
    private(set) var lastHeartbeatRejection: String?
    /// The last heartbeat called `transport.renew`, so the transport's
    /// renewal report and rejection belong to it (reset on each heartbeat).
    private(set) var lastHeartbeatReachedRenew = false
    /// The error `transport.renew` or the reply check threw in the last
    /// heartbeat, before control was dropped (journal only).
    private(set) var lastHeartbeatError: String?
    /// Retries of the last `heartbeat(now:)` while processing paused.
    private(set) var lastHeartbeatRetries = 0
    /// What the last heartbeat that returned normally did. `.notDue` renewed
    /// nothing and checked nothing: it is never a passed renewal.
    private(set) var lastHeartbeatOutcome: HeartbeatOutcome = .notDue(remaining: 0)
    /// Poll interval while a heartbeat waits out a processing pause.
    nonisolated static let heartbeatRetryPoll = Duration.milliseconds(100)

    init(gate: RingOperationGate) { self.gate = gate }

    // The coordinator accepts either the retired offline wire fixture or the
    // exact fingerprint-gated A1 transport attached by AppModel.
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

    @discardableResult
    func heartbeat(at now: TimeInterval) async throws -> HeartbeatOutcome {
        guard now.isFinite, now - lastRenewal >= 5 else {
            let outcome = HeartbeatOutcome.notDue(remaining: now.isFinite ? max(0, 5 - (now - lastRenewal)) : 5)
            lastHeartbeatOutcome = outcome
            return outcome
        }
        lastHeartbeatRejection = nil
        lastHeartbeatReachedRenew = false
        lastHeartbeatError = nil
        guard available, let transport, let status, status.mode == .gesture, !status.charging else {
            throw rejectHeartbeat("not_gesture")
        }
        guard let processed, processed.session == status.session else { throw rejectHeartbeat("not_processed") }
        guard now >= processed.time, now - processed.time <= 0.5 else {
            throw rejectHeartbeat(String(format: "processed_age=%.3f", now - processed.time))
        }
        guard lastRenewedSequence != processed.sequence else { throw rejectHeartbeat("same_sequence") }
        guard let op = gate.begin(.mode) else { throw RingProtocolError.busy }
        defer { gate.end(op) }
        let id = try nextID(), generation = connection
        do {
            lastHeartbeatReachedRenew = true
            let reply = try await transport.renew(session: status.session, processedSequence: processed.sequence, requestID: id)
            // Validate the renewal before accept publishes to Combine or coverage
            // observers. A later rejection cannot undo a persisted Health interval.
            guard reply.status.bootID == status.bootID, reply.status.session == status.session,
                  reply.status.mode == .gesture, !reply.status.charging else { throw rejectHeartbeat("reply_mismatch") }
            try accept(reply, id: id, connection: generation)
            lastRenewal = now
            lastRenewedSequence = processed.sequence
            lastHeartbeatOutcome = .renewed
            return .renewed
        } catch {
            lastHeartbeatError = String(describing: error)
            if generation == connection, !Self.keepsControl(after: error, heartbeatRejection: lastHeartbeatRejection) {
                disconnected()
            }
            throw error
        }
    }

    /// Whether a renewal failure leaves this coordinator in control of the
    /// Gesture session. Kept: a failed renewal gate (the lease-only A1 04 was
    /// written, its evidence was not good enough), a transport guard that
    /// wrote nothing, a busy write slot and a cancelled wait; the session's
    /// owner decides between a retry and a heal. Dropped: a reply that does not
    /// match (`reply_mismatch`, uncorrelated), exhausted request IDs, a lost
    /// link and anything unknown; mode recovery re-attaches with the audited stops.
    nonisolated static func keepsControl(after error: Error, heartbeatRejection: String?) -> Bool {
        if error is CancellationError { return true }
        if let error = error as? RingProtocolError, case .busy = error { return true }
        guard let error = error as? UnifiedModeError else { return false }
        switch error {
        case .renewalBoundary: return true
        case .staleStream: return heartbeatRejection == nil
        case .unavailable, .uncorrelated, .exhausted: return false
        }
    }

    /// `heartbeat(at:)`, retried every `poll` while it is refused only because
    /// processing paused (`processed_age`) for no longer than a stall that
    /// `GestureSession` tolerates can pause it (`waitsOnProcessingPause`).
    /// During a tolerated episode and its quarantine no output reaches
    /// `didProcess`, so a single 0.5 s check would end the session over the
    /// stall the session survived. Nothing is renewed without fresh
    /// processing meanwhile; the stall's own limits (ceiling, repeat, episode
    /// length) and a `GestureSession` fault end the session on their path and
    /// cancel the caller; the transport's 9 s lease-age guard still applies.
    /// `inFlight` brackets each attempt, not the waits between them. Returns
    /// the number of retries.
    @discardableResult
    func heartbeat(now: () -> TimeInterval, poll: Duration = heartbeatRetryPoll,
                   sleep: (Duration) async throws -> Void = { try await Task.sleep(for: $0) },
                   inFlight: (Bool) -> Void = { _ in }) async throws -> Int {
        lastHeartbeatRetries = 0
        while true {
            let at = now()
            inFlight(true)
            do {
                // `lastHeartbeatOutcome` says whether this renewed anything.
                try await heartbeat(at: at)
                inFlight(false)
                return lastHeartbeatRetries
            } catch {
                inFlight(false)
                guard waitsOnProcessingPause(error, at: at) else { throw error }
            }
            lastHeartbeatRetries += 1
            try await sleep(poll)
            try Task.checkCancellation()
        }
    }

    /// A heartbeat refused only on processed age, while the newest processed
    /// sample is no older than `GestureFreshness.processingPauseLimit`.
    func waitsOnProcessingPause(_ error: Error, at now: TimeInterval) -> Bool {
        guard (error as? UnifiedModeError) == .staleStream,
              lastHeartbeatRejection?.hasPrefix("processed_age=") == true,
              let processed, now >= processed.time else { return false }
        return now - processed.time <= GestureFreshness.processingPauseLimit
    }

    private func rejectHeartbeat(_ reason: String) -> UnifiedModeError {
        lastHeartbeatRejection = reason
        return .staleStream
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

/// A heartbeat that returned normally: it renewed the lease, or it was not
/// yet due (5 s since the last renewal on the uptime clock) and did nothing.
enum HeartbeatOutcome: Equatable {
    case renewed
    case notDue(remaining: TimeInterval)
}

/// Why one heartbeat failed, for `renewal_failed` and `session_end.detail`.
/// The transport's renewal report and rejection belong to this heartbeat
/// only when it reached `renew`, which clears both on entry; a heartbeat
/// refused before then must never carry the previous renewal's values.
struct HeartbeatFailure {
    var reachedRenew: Bool
    var heartbeatRejection: String?
    var transportRejection: String?
    var report: A1UnifiedModeTransport.RenewalReport?
    /// `String(describing:)` of the error, when known.
    var error: String?
    var retries = 0

    /// e.g. `renewal:criteria:max_gap`, `heartbeat:processed_age=2.300`,
    /// `heartbeat_error:busy`; nil only when nothing at all is known.
    var detail: String? {
        if reachedRenew {
            if let report, !report.passed {
                let checks = report.failedChecks.joined(separator: ",")
                return "renewal:" + (report.cause?.journalName ?? "failed") + (checks.isEmpty ? "" : ":" + checks)
            }
            if let transportRejection { return "renewal:" + transportRejection }
        }
        if let heartbeatRejection { return "heartbeat:" + heartbeatRejection }
        return error.map { "heartbeat_error:" + $0 }
    }

    /// Journal fields; `rejection` and `report` only when they are this heartbeat's.
    var fields: [String: Any] {
        var fields: [String: Any] = ["reached_renew": reachedRenew]
        if let heartbeatRejection { fields["heartbeat_rejection"] = heartbeatRejection }
        if reachedRenew {
            if let transportRejection { fields["rejection"] = transportRejection }
            if let report { fields["report"] = report.fields }
        }
        if retries > 0 { fields["retries"] = retries }
        return fields
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
