import Foundation
import SwiftData

@Model
final class HealthCoverageRecord {
    @Attribute(.unique) var id: UUID
    var deviceID: String
    var started: Date
    var ended: Date?
    var reason: String
    var firmwareIdentity: String
    var timezoneID: String
    var opticalMeasurementsAvailable: Bool
    var stepsAndSleepVerified: Bool

    init(deviceID: String, coverage: HealthCoverage, firmwareIdentity: String) {
        id = UUID(); self.deviceID = deviceID
        started = coverage.started; ended = coverage.ended; reason = coverage.reason.rawValue
        self.firmwareIdentity = firmwareIdentity
        timezoneID = TimeZone.autoupdatingCurrent.identifier
        opticalMeasurementsAvailable = coverage.opticalMeasurementsAvailable
        stepsAndSleepVerified = coverage.stepsAndSleepVerified
    }
}

/// Acquisition uncertainty, separate from the import cursor. An open interval
/// survives app termination and closes ONLY when Health is observed again.
@MainActor
final class HealthCoverageStore {
    private let context: ModelContext
    init(context: ModelContext) { self.context = context }

    func observe(deviceID: String, mode: RingRuntimeMode, firmware: String, at date: Date) throws {
        guard !context.hasChanges else { throw RingProtocolError.busy }
        let existing = try context.fetch(FetchDescriptor<HealthCoverageRecord>(predicate: #Predicate {
            $0.deviceID == deviceID && $0.ended == nil
        }))
        do {
            if mode == .health {
                for record in existing { record.ended = max(date, record.started) }
            } else if existing.isEmpty {
                let gesture = mode == .gesture || mode == .enteringGesture
                let coverage = HealthCoverage(started: date, ended: nil,
                                               reason: gesture ? .gestureSession : .unverifiedFirmware,
                                               opticalMeasurementsAvailable: false, stepsAndSleepVerified: false)
                context.insert(HealthCoverageRecord(deviceID: deviceID, coverage: coverage, firmwareIdentity: firmware))
            }
            try context.save()
        } catch { context.rollback(); throw error }
    }

    func uncertainIntervals(deviceID: String) throws -> [HealthCoverageRecord] {
        try context.fetch(FetchDescriptor<HealthCoverageRecord>(predicate: #Predicate { $0.deviceID == deviceID },
                                                               sortBy: [SortDescriptor(\.started)]))
    }
}
