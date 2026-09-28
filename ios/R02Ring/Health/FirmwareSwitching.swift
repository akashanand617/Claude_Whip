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

enum RingHardwareFamily: String, CaseIterable, Identifiable {
    case rt02cr
    case rt12col

    var id: String { rawValue }

    var title: String {
        switch self {
        case .rt02cr: return "RT02CR"
        case .rt12col: return "RT12COL"
        }
    }

    private static func hardwareFamily(_ value: String?) -> RingHardwareFamily? {
        guard let value else { return nil }
        if value == "RT02CR_V3.1" { return .rt02cr }
        if value == "RT12COL_V1.0" { return .rt12col }
        return nil
    }

    private static func firmwareFamily(_ value: String?) -> RingHardwareFamily? {
        guard let value else { return nil }
        if value.hasPrefix("RT02CR_") { return .rt02cr }
        if value.hasPrefix("RT12COL_") { return .rt12col }
        return nil
    }

    /// Routes only when both Device Information fields independently identify
    /// the same family. A missing, novel, or contradictory identity must not
    /// expose a firmware image.
    static func route(hardware: String?, firmware: String?) -> RingHardwareFamily? {
        guard let hardware = hardwareFamily(hardware),
              let firmware = firmwareFamily(firmware),
              hardware == firmware else { return nil }
        return hardware
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
    case unroutableIdentity(hardware: String, firmware: String)
    case noCompatibleImage(mode: RingFirmwareMode, family: RingHardwareFamily)
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
        case let .unroutableIdentity(hardware, firmware):
            return "No firmware route matches hardware \(hardware) with firmware \(firmware)."
        case let .noCompatibleImage(mode, family):
            return "No approved \(mode.title) image is bundled for \(family.title)."
        case let .rejected(message): return "The ring rejected the firmware transfer: \(message)"
        }
    }
}

struct BundledFirmware: Identifiable {
    let family: RingHardwareFamily
    let mode: RingFirmwareMode
    let resource: String
    let sha256: String
    let initType: UInt8
    let targetHardware: String
    let installEnabled: Bool
    let disabledReason: String?

    var id: String { "\(family.rawValue).\(mode.rawValue)" }

    var label: String {
        switch mode {
        case .health: return "Stock Health firmware"
        case .gesture: return "Experimental Gesture-only V2 firmware"
        case .unified: return "Experimental unified firmware"
        case .unknown: return "Unknown firmware"
        }
    }

    // Revoked after the first physical trial accepted DFU CHECK but did not
    // return a usable application BLE/DFU service after reboot.
    static var unifiedInstallEnabled: Bool { unified.installEnabled }

    static let gesture = BundledFirmware(
        family: .rt02cr,
        mode: .gesture,
        resource: "rt02cr-25hz-optical-off-v2-experimental",
        sha256: "0d18a0fa860d58ab8f984b5f542f45dac105241f47bf1c2af41321eb0431e14c",
        initType: 4,
        targetHardware: "RT02CR_V3.1",
        installEnabled: true,
        disabledReason: nil
    )

    static let unified = BundledFirmware(
        family: .rt02cr,
        mode: .unified,
        resource: "rt02cr-25hz-health-default-gesture-v1-experimental",
        sha256: "b1070bed755ce14936501431e379c6c47570ce747265fe0b6af0e87553eb2dc4",
        initType: 4,
        targetHardware: "RT02CR_V3.1",
        installEnabled: false,
        disabledReason: "disabled after failed boot validation"
    )

    static let health = BundledFirmware(
        family: .rt02cr,
        mode: .health,
        resource: "rt02cr-stock-3.12.02",
        sha256: "b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0",
        initType: 1,
        targetHardware: "RT02CR_V3.1",
        installEnabled: true,
        disabledReason: nil
    )

    static let rt12colUnified = BundledFirmware(
        family: .rt12col,
        mode: .unified,
        resource: "rt12col-25hz-health-default-gesture-v7-100hz-comparison-experimental",
        sha256: "cb815abea8d0ed0b4734b83790a45f632113e0bed4184de606b897727d4e9bd5",
        initType: 4,
        targetHardware: "RT12COL_V1.0",
        installEnabled: false,
        disabledReason: "V7 is recognized for bounded testing, but app installation remains locked pending physical gates"
    )

    // Physically fresh, lease-safe V6 remains an authenticated rollback and
    // comparison identity. It is not re-exposed as an app install target.
    static let rt12colUnifiedLegacyV6 = BundledFirmware(
        family: .rt12col,
        mode: .unified,
        resource: "rt12col-25hz-health-default-gesture-v6-sleep-fix-experimental",
        sha256: "e92c5bc0d2751c3348aeea56ece4e5b5693baf1f6ba45c2a869c2d79729e134d",
        initType: 4,
        targetHardware: "RT12COL_V1.0",
        installEnabled: false,
        disabledReason: "retained as the verified 200 Hz rollback/comparison image"
    )

    // Retained for exact authentication of the revoked V3 image. V3 used LP3
    // despite its old LP2 label and renewal re-entered the producer path.
    static let rt12colUnifiedLegacyV3 = BundledFirmware(
        family: .rt12col,
        mode: .unified,
        resource: "rt12col-25hz-health-default-gesture-v3-experimental",
        sha256: "ea5b7a61041d7c64213307018a29f7dc6d803a135afd94d1f1a25178c0ab5026",
        initType: 4,
        targetHardware: "RT12COL_V1.0",
        installEnabled: false,
        disabledReason: "revoked: CTRL1 0x62 is LP mode 3; renewal also re-enters the producer path"
    )

    // Retained for exact authentication and rollback visibility only. V2 was
    // an off-ring 200 Hz / ODR/4 draft without the complete stock-restore lease.
    static let rt12colUnifiedLegacyV2 = BundledFirmware(
        family: .rt12col,
        mode: .unified,
        resource: "rt12col-25hz-health-default-gesture-v2-experimental",
        sha256: "cca729f1b36543bea9d1076c8cf7a39542db608df40e24b9ce2920753e2efab4",
        initType: 4,
        targetHardware: "RT12COL_V1.0",
        installEnabled: false,
        disabledReason: "superseded before device deployment by the wide-band leased build"
    )

    // Retained only so an app update can authenticate an already-installed V1
    // and offer V2 or stock. It is not exposed as an install target.
    static let rt12colUnifiedLegacyV1 = BundledFirmware(
        family: .rt12col,
        mode: .unified,
        resource: "rt12col-25hz-health-default-gesture-v1-experimental",
        sha256: "52736f328dd2ea60e284a25438284447b54837e93a0dbcc2da88737968b4483b",
        initType: 4,
        targetHardware: "RT12COL_V1.0",
        installEnabled: false,
        disabledReason: "superseded after measured duplicate samples"
    )

    static let rt12colHealth = BundledFirmware(
        family: .rt12col,
        mode: .health,
        resource: "rt12col-stock-1.00.00",
        sha256: "b180b27a3fddd24db8a49de7c6b0041b94621062187300ceeb79af3d7908c639",
        initType: 4,
        targetHardware: "RT12COL_V1.0",
        installEnabled: true,
        disabledReason: nil
    )

    static let rt02crCatalog: [BundledFirmware] = [.health, .unified, .gesture]
    static let rt12colCatalog: [BundledFirmware] = [.rt12colHealth, .rt12colUnified]

    static func catalog(for family: RingHardwareFamily) -> [BundledFirmware] {
        switch family {
        case .rt02cr: return rt02crCatalog
        case .rt12col: return rt12colCatalog
        }
    }

    static func routedCatalog(hardware: String?, firmware: String?) -> [BundledFirmware] {
        guard let family = RingHardwareFamily.route(hardware: hardware, firmware: firmware),
              FirmwareIdentity.isKnownInstalledVersion(firmware, family: family) else {
            return []
        }
        return catalog(for: family)
    }

    static func routedImage(for mode: RingFirmwareMode,
                            hardware: String?, firmware: String?) -> BundledFirmware? {
        routedCatalog(hardware: hardware, firmware: firmware).first { $0.mode == mode }
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
            throw FirmwareSwitchError.invalidImage("missing hardware header")
        }
        let declared = try declaredHardware(in: data)
        guard declared == targetHardware else {
            throw FirmwareSwitchError.invalidImage(
                "catalog target \(targetHardware) does not match image header \(declared)"
            )
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
    static let rt12colStockVersion = "RT12COL_1.00.00_260520"
    static let rt12colUnifiedV1Version = "RT12COL_1.00.01_260927"
    static let rt12colUnifiedV2Version = "RT12COL_1.00.02_260927"
    static let rt12colUnifiedV3Version = "RT12COL_1.00.03_260927"
    static let rt12colUnifiedV6Version = "RT12COL_1.00.06_260927"
    static let rt12colUnifiedVersion = "RT12COL_1.00.07_260927"

    static func isKnownInstalledVersion(_ version: String?, family: RingHardwareFamily) -> Bool {
        guard let version else { return false }
        switch family {
        case .rt02cr: return version == stockVersion || version == gestureVersion
        case .rt12col:
            return version == rt12colStockVersion || version == rt12colUnifiedV1Version
                || version == rt12colUnifiedV2Version || version == rt12colUnifiedV3Version
                || version == rt12colUnifiedV6Version || version == rt12colUnifiedVersion
        }
    }
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

    static let rt12colUnifiedV1Sites: [Site] = [
        .init(offset: 0x1e48, length: 4),
        .init(offset: 0x1ea2, length: 4),
        .init(offset: 0x1f22, length: 4),
        .init(offset: 0x1f64, length: 4),
        .init(offset: 0x21ce, length: 8),
        .init(offset: 0x2240, length: 14),
        .init(offset: 0x7c7e, length: 14),
        .init(offset: 0x7cd4, length: 10),
        .init(offset: 0x94a0, length: 12),
        .init(offset: 0xf662, length: 14),
        .init(offset: 0xf670, length: 4),
    ]

    static let rt12colUnifiedV2Sites: [Site] = rt12colUnifiedV1Sites + [
        // V2-only source lifecycle. These cover every new hook plus every byte
        // of the bounded helper region; version text alone is never trusted.
        .init(offset: 0x21ec, length: 14),
        .init(offset: 0x22e2, length: 14),
        .init(offset: 0x6926, length: 14),
        .init(offset: 0xbfd8, length: 14),
        .init(offset: 0xc042, length: 14),
        .init(offset: 0xc064, length: 14),
        .init(offset: 0xc072, length: 14),
        .init(offset: 0xc080, length: 14),
        .init(offset: 0xc08e, length: 14),
        .init(offset: 0xc09c, length: 14),
        .init(offset: 0xc0aa, length: 14),
        .init(offset: 0xc0b8, length: 14),
        .init(offset: 0xc0c6, length: 6),
    ]

    static let rt12colUnifiedV3Sites: [Site] = rt12colUnifiedV1Sites + [
        .init(offset: 0x1fc8, length: 10),
        .init(offset: 0x21ec, length: 14),
        .init(offset: 0x22e2, length: 14),
        .init(offset: 0x6926, length: 14),
        .init(offset: 0xbfd8, length: 14),
        .init(offset: 0xc042, length: 14),
    ] + stride(from: 0, to: 0xc0, by: 14).map {
        Site(offset: 0xc064 + $0, length: min(14, 0xc0 - $0))
    }

    // V6 authentication covers every byte changed from the stock application,
    // including all three runtime version strings and the complete 212-byte
    // helper region. Sites are split only to the audited 14-byte CD01 limit.
    private static let rt12colUnifiedV6Ranges: [(Int, Int)] = [
        (0x1e48, 4), (0x1ea2, 4), (0x1ef4, 8), (0x1f00, 6),
        (0x1f64, 4), (0x1fc8, 10), (0x21c8, 22), (0x21f0, 4),
        (0x2242, 1), (0x22ea, 4), (0x692e, 4), (0x7764, 8),
        (0x7770, 6), (0x7c80, 1), (0x7c88, 1), (0x7cd6, 1),
        (0x7cda, 1), (0x9164, 8), (0x9170, 6), (0x94a4, 4),
        (0xbfe2, 2), (0xc04a, 8), (0xc064, 212), (0xf670, 2),
        (0x1257c, 4),
    ]
    static let rt12colUnifiedSites: [Site] = rt12colUnifiedV6Ranges.flatMap { offset, length in
        stride(from: 0, to: length, by: 14).map {
            Site(offset: offset + $0, length: min(14, length - $0))
        }
    }
    // V7 changes one byte inside the same helper interval, so the exact same
    // complete changed-byte site set authenticates V6 against its own bundle.
    static let rt12colUnifiedV6Sites = rt12colUnifiedSites

    static func readPacket(_ site: Site) -> Data {
        ColmiR02Protocol.packet(command: 0xcd, payload: [
            1, UInt8(site.length), UInt8((site.address >> 24) & 0xff),
            UInt8((site.address >> 16) & 0xff), UInt8((site.address >> 8) & 0xff),
            UInt8(site.address & 0xff),
        ])
    }
}
