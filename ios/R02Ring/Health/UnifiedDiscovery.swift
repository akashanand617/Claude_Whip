import Foundation

/// Unattached, read-only identity format for the separate unified service.
/// This parser performs no Bluetooth/UART access and does not authorize a build,
/// advertise capabilities, or attach UnifiedModeTransport. The reported IDs are
/// not cryptographic attestation. Production admission remains unavailable.
enum UnifiedDiscovery {
    enum Failure: Error { case invalid }
    struct Identification: Equatable {
        let bootID: UInt64
        let buildTag: UInt64
    }

    static func decode(_ bytes: [UInt8]) throws -> Identification {
        guard bytes.count == 20, bytes[0] == 0x57, bytes[1] == 0x49,
              bytes[2] == 1, bytes[3] == 0 else { throw Failure.invalid }
        func word(_ offset: Int) -> UInt64 {
            (0..<8).reduce(0) { $0 | (UInt64(bytes[offset + $1]) << (8 * $1)) }
        }
        let boot = word(4), build = word(12)
        guard boot != 0, build != 0 else { throw Failure.invalid }
        return .init(bootID: boot, buildTag: build)
    }
}
