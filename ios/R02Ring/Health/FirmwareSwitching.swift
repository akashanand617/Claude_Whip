import CryptoKit
import Foundation

enum RingFirmwareMode: String, CaseIterable, Identifiable {
    case unknown
    case health
    case gesture
    case unified

    var id: String { rawValue }

    var title: String {
        switch self {
        case .unknown: return "Unknown"
        case .health: return "Health"
        case .gesture: return "Gesture"
        case .unified: return "Unified"
        }
    }
}

enum FirmwareSwitchError: LocalizedError {
    case missingImage(String)
    case invalidImage(String)
    case incompatibleHardware(expected: String, actual: String)
    case batteryTooLow(Int)
    case charging
    case healthSyncFailed(String)
    case unrecognizedFirmware
    case rejected(String)

    var errorDescription: String? {
        switch self {
        case let .missingImage(name): return "The bundled firmware image \(name) is missing."
        case let .invalidImage(reason): return "Firmware validation failed: \(reason)"
        case let .incompatibleHardware(expected, actual):
            return "This image is for \(expected), but the ring reports \(actual)."
        case let .batteryTooLow(percent): return "Charge the ring above 40% before flashing (currently \(percent)%)."
        case .charging: return "Take the ring off its charger before flashing."
        case let .healthSyncFailed(message):
            return "Health history was not fully saved, so the firmware was not changed: \(message)"
        case .unrecognizedFirmware: return "The installed firmware could not be safely identified."
        case let .rejected(message): return "The ring rejected the firmware transfer: \(message)"
        }
    }
}

struct BundledFirmware {
    let mode: RingFirmwareMode
    let resource: String
    let sha256: String
    let initType: UInt8

    // Revoked after the first physical trial accepted DFU CHECK but did not
    // return a usable application BLE/DFU service after reboot.
    static let unifiedInstallEnabled = false

    static let gesture = BundledFirmware(
        mode: .gesture,
        resource: "rt02cr-25hz-optical-off-v2-experimental",
        sha256: "0d18a0fa860d58ab8f984b5f542f45dac105241f47bf1c2af41321eb0431e14c",
        initType: 4
    )

    static let unified = BundledFirmware(
        mode: .unified,
        resource: "rt02cr-25hz-health-default-gesture-v1-experimental",
        sha256: "b1070bed755ce14936501431e379c6c47570ce747265fe0b6af0e87553eb2dc4",
        initType: 4
    )

    static let health = BundledFirmware(
        mode: .health,
        resource: "rt02cr-stock-3.12.02",
        sha256: "b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0",
        initType: 1
    )

    static func image(for mode: RingFirmwareMode) -> BundledFirmware? {
        switch mode {
        case .health: return .health
        case .gesture: return .gesture
        case .unified: return .unified
        case .unknown: return nil
        }
    }

    func load(bundle: Bundle = .main) throws -> Data {
        guard let url = bundle.url(forResource: resource, withExtension: "bin", subdirectory: "Firmware")
                ?? bundle.url(forResource: resource, withExtension: "bin") else {
            throw FirmwareSwitchError.missingImage(resource + ".bin")
        }
        let data = try Data(contentsOf: url, options: .mappedIfSafe)
        let digest = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        guard digest == sha256 else {
            throw FirmwareSwitchError.invalidImage("SHA-256 mismatch")
        }
        guard data.count > 0x50, String(data: data[0x30..<min(data.count, 0x50)], encoding: .utf8) != nil else {
            throw FirmwareSwitchError.invalidImage("missing RT02CR hardware header")
        }
        return data
    }

    func declaredHardware(in data: Data) throws -> String {
        guard data.count >= 0x50 else { throw FirmwareSwitchError.invalidImage("truncated container") }
        let field = data[0x30..<0x50]
        let bytes = field.prefix { $0 != 0 }
        guard let value = String(bytes: bytes, encoding: .utf8), !value.isEmpty else {
            throw FirmwareSwitchError.invalidImage("unreadable hardware header")
        }
        return value
    }
}

enum R02DFU {
    static let magic: UInt8 = 0xbc
    static let chunkSize = 1024

    static func crc16(_ data: Data) -> UInt16 {
        var crc: UInt16 = 0xffff
        for byte in data {
            crc ^= UInt16(byte)
            for _ in 0..<8 {
                crc = crc & 1 == 1 ? (crc >> 1) ^ 0xa001 : crc >> 1
            }
        }
        return crc
    }

    static func checksum16(_ data: Data) -> UInt16 {
        data.reduce(UInt16(0)) { $0 &+ UInt16($1) }
    }

    static func frame(command: UInt8, payload: Data = Data()) -> Data {
        let crc = crc16(payload)
        let length = UInt16(payload.count)
        return Data([magic, command, UInt8(length & 0xff), UInt8(length >> 8),
                     UInt8(crc & 0xff), UInt8(crc >> 8)]) + payload
    }

    static func initFrame(firmware: Data, type: UInt8) throws -> Data {
        guard type == 1 || type == 4 else { throw FirmwareSwitchError.invalidImage("invalid init type") }
        let size = UInt32(firmware.count)
        let crc = crc16(firmware)
        let sum = checksum16(firmware)
        return frame(command: 2, payload: Data([
            type,
            UInt8(size & 0xff), UInt8((size >> 8) & 0xff),
            UInt8((size >> 16) & 0xff), UInt8((size >> 24) & 0xff),
            UInt8(crc & 0xff), UInt8(crc >> 8),
            UInt8(sum & 0xff), UInt8(sum >> 8),
        ]))
    }

    static func dataFrame(firmware: Data, index: Int) throws -> Data {
        let start = index * chunkSize
        guard start < firmware.count else { throw FirmwareSwitchError.invalidImage("chunk past end") }
        let end = min(start + chunkSize, firmware.count)
        let number = UInt16(index + 1)
        var payload = Data([UInt8(number & 0xff), UInt8(number >> 8)])
        payload.append(firmware[start..<end])
        return frame(command: 3, payload: payload)
    }

    static func validateResponse(_ data: Data, command: UInt8) throws {
        guard data.count >= 7, data[0] == magic, data[1] == command else {
            throw FirmwareSwitchError.rejected("malformed response")
        }
        let length = Int(data[2]) | (Int(data[3]) << 8)
        guard data.count == length + 6 else { throw FirmwareSwitchError.rejected("invalid response length") }
        let payload = data.dropFirst(6)
        let storedCRC = UInt16(data[4]) | (UInt16(data[5]) << 8)
        guard crc16(Data(payload)) == storedCRC else { throw FirmwareSwitchError.rejected("response CRC mismatch") }
        guard payload.first == 0 else {
            let names = [1: "data size", 2: "data content", 3: "command state", 4: "command format",
                         5: "internal error", 6: "low battery"]
            throw FirmwareSwitchError.rejected(names[Int(payload.first ?? 255)] ?? "status \(payload.first ?? 255)")
        }
    }
}

enum FirmwareIdentity {
    static let stockVersion = "RT02CR_3.12.02_260824"
    static let gestureVersion = "RT02CR_3.12.07_260514"
    private static let fileToAddress = 0x825fb0
    private static let ranges: [(Int, Int)] = [
        (0x21d6, 20), (0x2244, 16), (0x6918, 24), (0x7ed0, 20),
        (0xbf04, 16), (0xcad0, 20), (0xf68a, 80), (0x122fe, 48),
    ]

    struct Site {
        let offset: Int
        let length: Int
        var address: UInt32 { UInt32(offset + fileToAddress) }
    }

    static var sites: [Site] {
        ranges.flatMap { offset, length in
            stride(from: 0, to: length, by: 14).map {
                Site(offset: offset + $0, length: min(14, length - $0))
            }
        }
    }

    static let unifiedSites: [Site] = [
        .init(offset: 0x749a, length: 4),
        .init(offset: 0x1f128, length: 14),
        .init(offset: 0x1f170, length: 14),
        .init(offset: 0x1f1b8, length: 14),
        .init(offset: 0xf68c, length: 6),
        .init(offset: 0xcad2, length: 4),
        .init(offset: 0x122fe, length: 6),
        .init(offset: 0x21dc, length: 6),
        .init(offset: 0x691e, length: 4),
    ]

    static func readPacket(_ site: Site) -> Data {
        ColmiR02Protocol.packet(command: 0xcd, payload: [
            1, UInt8(site.length), UInt8((site.address >> 24) & 0xff),
            UInt8((site.address >> 16) & 0xff), UInt8((site.address >> 8) & 0xff),
            UInt8(site.address & 0xff),
        ])
    }
}
