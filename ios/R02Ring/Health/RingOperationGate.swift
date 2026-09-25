import Foundation

/// One logical owner across awaits, not just one packet at a time. Fail busy
/// rather than queue user intentions that may be unsafe after a mode change.
@MainActor
final class RingOperationGate {
    enum Operation { case sync, settings, liveHeartRate, mode, firmware }
    private(set) var owner: Operation?
    private var token: UUID?

    func begin(_ operation: Operation) -> UUID? {
        guard owner == nil else { return nil }
        let id = UUID()
        owner = operation
        token = id
        return id
    }

    func end(_ id: UUID) {
        guard token == id else { return }
        owner = nil
        token = nil
    }
}
