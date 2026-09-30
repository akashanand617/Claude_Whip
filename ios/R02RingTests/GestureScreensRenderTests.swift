import XCTest
import SwiftUI
@testable import R02Ring

/// Renders the Gestures sheets and grid offscreen at iPhone size, dark. With
/// `WHIP_RENDER_DIR` set (pass `TEST_RUNNER_WHIP_RENDER_DIR` to xcodebuild)
/// the PNGs are written there for review. Never constructs `AppModel`.
@MainActor
final class GestureScreensRenderTests: XCTestCase {
    private static let width: CGFloat = 393

    /// 393×852 points at 3x, an iPhone 16/17 Pro screen. Sheets render with
    /// `scrolls: false` because `ImageRenderer` draws nothing inside a ScrollView.
    @discardableResult
    private func render<V: View>(_ view: V, named name: String, height: CGFloat = 852,
                                 file: StaticString = #filePath, line: UInt = #line) throws -> UIImage {
        let content = view
            // Top-anchored and clipped like a scroll view's first screen.
            .frame(width: Self.width, height: height, alignment: .top)
            .clipped()
            .background(Tok.ink)
            .environment(\.colorScheme, .dark)
        let renderer = ImageRenderer(content: content)
        renderer.scale = 3
        renderer.proposedSize = ProposedViewSize(width: Self.width, height: height)
        let image = try XCTUnwrap(renderer.uiImage, "\(name) did not render")
        XCTAssertEqual(image.size, CGSize(width: Self.width, height: height))
        // A size check alone passes for a view that drew nothing (as any
        // ScrollView does under ImageRenderer); require visible content.
        XCTAssertGreaterThan(try Self.drawnFraction(image), 0.005, "\(name) rendered no visible content",
                             file: file, line: line)
        if let directory = ProcessInfo.processInfo.environment["WHIP_RENDER_DIR"], !directory.isEmpty {
            let root = URL(fileURLWithPath: directory, isDirectory: true)
            try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
            try XCTUnwrap(image.pngData()).write(to: root.appendingPathComponent("\(name).png"))
        }
        return image
    }

    /// Fraction of pixels (sampled at 1/4 scale) that differ from the empty
    /// `Tok.ink` background by more than a small tolerance in any channel.
    private static func drawnFraction(_ image: UIImage) throws -> Double {
        func pixels(_ cg: CGImage, width: Int, height: Int) throws -> [UInt8] {
            var buffer = [UInt8](repeating: 0, count: width * height * 4)
            let drew = buffer.withUnsafeMutableBytes { raw -> Bool in
                guard let context = CGContext(data: raw.baseAddress, width: width, height: height,
                                              bitsPerComponent: 8, bytesPerRow: width * 4,
                                              space: CGColorSpaceCreateDeviceRGB(),
                                              bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return false }
                context.interpolationQuality = .none
                context.draw(cg, in: CGRect(x: 0, y: 0, width: width, height: height))
                return true
            }
            guard drew else { throw CocoaError(.featureUnsupported) }
            return buffer
        }
        let cg = try XCTUnwrap(image.cgImage)
        let width = max(1, cg.width / 4), height = max(1, cg.height / 4)
        let blank = ImageRenderer(content: Color.clear.frame(width: 4, height: 4).background(Tok.ink)
            .environment(\.colorScheme, .dark))
        let background = try pixels(XCTUnwrap(blank.cgImage), width: 1, height: 1)
        let sampled = try pixels(cg, width: width, height: height)
        var drawn = 0
        for index in stride(from: 0, to: sampled.count, by: 4) {
            if (0..<3).contains(where: { abs(Int(sampled[index + $0]) - Int(background[$0])) > 12 }) { drawn += 1 }
        }
        return Double(drawn) / Double(width * height)
    }

    func testBlankRenderIsDetected() throws {
        // Proves the content check can fail: an empty view is all background.
        let renderer = ImageRenderer(content: Color.clear.frame(width: Self.width, height: 400).background(Tok.ink)
            .environment(\.colorScheme, .dark))
        renderer.scale = 3
        XCTAssertEqual(try Self.drawnFraction(XCTUnwrap(renderer.uiImage)), 0)
    }

    func testActionPickerSheetRenders() throws {
        let picker = GestureActionPickerSheet(
            gesture: .flick_right, current: .music_next,
            permissions: [.appleMusic: .notDetermined, .notifications: .denied],
            scrolls: false, choose: { _ in }, restoreDefault: {}
        )
        try render(picker, named: "gesture-action-picker")
        try render(picker, named: "gesture-action-picker-full", height: 2_000)
        let changed = GestureActionPickerSheet(
            gesture: .wave, current: .ping_phone, permissions: [.notifications: .authorized],
            scrolls: false, choose: { _ in }, restoreDefault: {}
        )
        try render(changed, named: "gesture-action-picker-changed", height: 2_000)
        let v9 = GestureActionPickerSheet(
            gesture: .double_flick_up, current: .hid_key_page_down,
            availableHIDVersion: 9, scrolls: false, choose: { _ in }, restoreDefault: {}
        )
        // Keep the 3x bitmap below Core Graphics' 8K texture limit.
        try render(v9, named: "gesture-action-picker-v9", height: 2_500)
    }

    func testBackTapGuideSheetRenders() throws {
        try render(BackTapGuideSheet(scrolls: false), named: "back-tap-guide")
    }

    func testRingControlsGuideSheetRenders() throws {
        try render(RingControlsGuideSheet(scrolls: false), named: "ring-controls-guide")
    }

    func testDiagnosticsSheetRenders() throws {
        try render(GestureDiagnosticsSheet(ready: false, recording: false, prompt: "", progress: "",
                                           captureName: nil, scrolls: false, start: {}, cancel: {}),
                   named: "gesture-diagnostics")
        try render(GestureDiagnosticsSheet(ready: true, recording: true, prompt: "NOW: double flick up",
                                           progress: "4 of 33", captureName: nil, scrolls: false,
                                           start: {}, cancel: {}),
                   named: "gesture-diagnostics-recording")
    }

    func testMappingGridRenders() throws {
        var mappings = GestureMappings()
        mappings[.wave] = .ping_phone
        mappings[.double_flick_up] = .music_toggle_shuffle
        mappings[.double_clap] = .flag
        try render(GestureMappingGrid(mappings: mappings) { _ in }, named: "gesture-grid")
    }

    func testSessionPanelRenders() throws {
        func panel(_ button: GestureSessionButton, mode: RingRuntimeMode?, keep: Bool = true,
                   charging: Bool = false, status: String? = nil, healing: Bool = false) -> some View {
            VStack(spacing: 0) {
                ScreenHeader(title: "Gestures") { BatteryPill(percent: 72) }
                GestureSessionPanelView(
                    button: button, mode: mode, linked: true,
                    status: status ?? (mode == .gesture ? "Ready" : "Health mode · gesture recognition off"),
                    requestMessage: nil,
                    lastDispatch: "Flick right → Next track · done",
                    lastSession: "Last session 4 min 12 s · 7 gestures, 5 actions · paused by gesture",
                    charging: charging,
                    autoReturn: .constant(.off), idlePause: .constant(.fifteenMinutes),
                    keepInBackground: .constant(keep), tap: { _ in }, healing: healing
                )
                .padding(.horizontal, Tok.side)
                .padding(.top, 14)
                GestureMappingGrid(mappings: GestureMappings()) { _ in }
                    .padding(.top, 26)
            }
        }
        // The first screen of the tab's ScrollView, without the tab bar. The two
        // timer menus are UIKit-backed and render as placeholders here.
        try render(panel(.start, mode: .health), named: "gesture-session-health")
        try render(panel(.stop, mode: .gesture, keep: false, charging: true), named: "gesture-session-active")
        var connecting = Self.snapshot
        connecting.link = .connecting
        try render(panel(.unavailable, mode: nil, status: connecting.unavailableReason),
                   named: "gesture-session-unavailable")
        try render(panel(.waiting, mode: .health,
                         status: GestureStartReadiness.connecting.waitingNote), named: "gesture-session-waiting")
        let reconnecting = GestureHealStatus(cause: .disconnected, attempt: 2, phase: .waitingForLink)
        try render(panel(.reconnecting, mode: nil, status: reconnecting.statusText, healing: true),
                   named: "gesture-session-reconnecting")
    }

    func testAReconnectingSessionOffersReturnToHealthWhateverTheHealIsDoing() {
        typealias B = GestureSessionButton
        for (mode, transition) in [(RingRuntimeMode?.none, GestureTransition?.none), (.health, nil),
                                   (.gesture, .leaving), (.health, .entering), (.returningHealth, nil)] {
            XCTAssertEqual(B(mode: mode, available: mode != nil, transition: transition, requesting: false,
                             attachInFlight: mode == nil, healing: true), .reconnecting,
                           "\(String(describing: mode)) \(String(describing: transition))")
        }
        XCTAssertEqual(B.reconnecting.title, "Return to Health")
        XCTAssertTrue(B.reconnecting.isEnabled)
        XCTAssertTrue(B.reconnecting.showsProgress)
        XCTAssertFalse(B.reconnecting.requestsGesture, "tapping ends the session (end reason: user)")
        XCTAssertEqual(B.reconnecting.hint, "Gestures are reconnecting; tap to return to Health")
        XCTAssertEqual(GestureSessionPanelView.statusLine(button: .reconnecting, snapshot: Self.snapshot,
                                                          gestureStatus: "Reconnecting gestures…"),
                       "Reconnecting gestures…")
        XCTAssertEqual(GestureHealStatus(cause: .staleStream, attempt: 1, phase: .backingOff).statusText,
                       "Reconnecting gestures…")
        XCTAssertEqual(GestureHealStatus(cause: .disconnected, attempt: 0, phase: .waitingForLink).statusText,
                       "Reconnecting gestures · waiting for the ring")
    }

    func testBadgeKinds() {
        XCTAssertEqual(ActionBadge.Kind(action: .none), .unassigned)
        for action in GestureActionID.allCases where action != .none {
            XCTAssertEqual(ActionBadge.Kind(action: action), .background, action.rawValue)
        }
        XCTAssertEqual(GestureActionID.music_next.spokenSummary, "Next track, works in background")
        XCTAssertEqual(GestureActionID.swipe_up.spokenSummary, "Swipe up, works in background")
        XCTAssertEqual(GestureActionID.none.spokenSummary, "No action")
    }

    func testBackTapGuideNamesTheToggleIntent() {
        XCTAssertEqual(BackTapGuideSheet.actionTitle, String(localized: ToggleGestureSessionIntent.title))
        XCTAssertEqual(BackTapGuideSheet.appName, Bundle(for: AppModel.self).object(forInfoDictionaryKey: "CFBundleName") as? String)
    }

    func testSessionButtonFollowsModeAndTransition() {
        typealias B = GestureSessionButton
        func state(_ mode: RingRuntimeMode?, available: Bool = true, transition: GestureTransition? = nil,
                   requesting: Bool = false, attaching: Bool = false) -> B {
            B(mode: mode, available: available, transition: transition,
              requesting: requesting, attachInFlight: attaching)
        }
        XCTAssertEqual(state(.health), .start)
        XCTAssertEqual(state(.health, requesting: true), .waiting)
        XCTAssertEqual(state(.health, transition: .entering, requesting: true), .starting)
        XCTAssertEqual(state(.enteringGesture), .starting)
        XCTAssertEqual(state(.gesture), .stop)
        XCTAssertEqual(state(.gesture, requesting: true), .stop)
        XCTAssertEqual(state(.gesture, transition: .leaving), .stopping)
        XCTAssertEqual(state(.returningHealth), .stopping)
        XCTAssertEqual(state(nil, available: false, attaching: true), .preparing)
        XCTAssertEqual(state(nil, available: false), .unavailable)
        XCTAssertEqual(state(.fault), .unavailable)
        XCTAssertEqual(state(.unknown), .unavailable)

        XCTAssertEqual([B.start, .waiting, .starting, .stop].filter(\.isEnabled).count, 4)
        for disabled in [B.stopping, .preparing, .unavailable] {
            XCTAssertFalse(disabled.isEnabled, "\(disabled)")
        }
        XCTAssertTrue(B.start.requestsGesture)
        XCTAssertFalse(B.starting.requestsGesture, "cancelling an entry asks for Health")
        XCTAssertFalse(B.waiting.requestsGesture, "cancelling a waiting start asks for Health")
        XCTAssertEqual(B.waiting.title, "Cancel start")
        XCTAssertTrue(B.waiting.showsProgress)
        XCTAssertFalse(B.stop.requestsGesture)
    }

    private static let snapshot = GestureModeSnapshot(
        link: .ready, connectionSetupComplete: true, unifiedFirmwareInstalled: true,
        modeAttachInFlight: false, modeControlAvailable: true, mode: .health, charging: false,
        transition: nil, ringBusy: false, firmwareSwitching: false, appActive: true,
        keepGesturesInBackground: true
    )

    func testStatusLineNamesTheCauseOrWhatAStartWaitsFor() {
        var disconnected = Self.snapshot
        disconnected.link = .connecting
        XCTAssertEqual(GestureSessionPanelView.statusLine(button: .unavailable, snapshot: disconnected,
                                                          gestureStatus: "Health mode · gesture recognition off"),
                       "Ring not connected · R02 reconnects when it's in range.")
        var stock = Self.snapshot
        stock.unifiedFirmwareInstalled = false
        XCTAssertEqual(GestureSessionPanelView.statusLine(button: .unavailable, snapshot: stock, gestureStatus: "x"),
                       "Gesture sessions need the verified unified image. Firmware maintenance is under Settings.")
        XCTAssertEqual(GestureSessionPanelView.statusLine(button: .waiting, snapshot: disconnected, gestureStatus: "x"),
                       "Starting · waiting for the ring to connect")
        for button in [GestureSessionButton.start, .starting, .stop, .stopping, .preparing] {
            XCTAssertEqual(GestureSessionPanelView.statusLine(button: button, snapshot: disconnected,
                                                              gestureStatus: "Ready"), "Ready", "\(button)")
        }
    }
}
