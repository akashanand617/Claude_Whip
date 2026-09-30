import XCTest
@testable import R02Ring

@MainActor
final class GestureMappingTests: XCTestCase {
    private var suiteName = ""
    private var defaults: UserDefaults!

    override func setUp() {
        super.setUp()
        suiteName = UUID().uuidString
        defaults = UserDefaults(suiteName: suiteName)
    }

    override func tearDown() {
        defaults.removePersistentDomain(forName: suiteName)
        defaults = nil
        super.tearDown()
    }

    private func event(_ name: String, _ direction: String = "none") -> RingGestureEvent {
        RingGestureEvent(name: name, direction: direction, time: 1, confidence: 0.9, votes: 3, latency: 1, end: 1.2)
    }

    func testEveryEngineEventMapsToItsGesture() {
        let cases: [(String, String, GestureID)] = [
            ("flick", "up", .flick_up), ("flick", "down", .flick_down),
            ("flick", "left", .flick_left), ("flick", "right", .flick_right),
            ("double_flick", "up", .double_flick_up), ("double_flick", "down", .double_flick_down),
            ("double_flick", "left", .double_flick_left), ("double_flick", "right", .double_flick_right),
            ("snap", "none", .snap), ("double_clap", "none", .double_clap), ("wave", "none", .wave),
        ]
        XCTAssertEqual(Set(cases.map { $0.2 }), Set(GestureID.allCases))
        for (name, direction, expected) in cases {
            XCTAssertEqual(GestureID(event: event(name, direction)), expected, "\(name) \(direction)")
        }
        // Undirected gestures map by name even if the engine reports a direction.
        XCTAssertEqual(GestureID(event: event("wave", "left")), .wave)
        XCTAssertEqual(GestureID(event: event("snap", "up")), .snap)
    }

    func testNoneAndUnknownNamesAreUnrecognized() {
        for (name, direction) in [("none", "none"), ("none", "up"), ("clap", "none"), ("double_snap", "none"),
                                  ("flick", "none"), ("double_flick", "sideways"), ("flick_up", "none"),
                                  ("", "none"), ("Flick", "up")] {
            XCTAssertNil(GestureID(event: event(name, direction)), "\(name) \(direction)")
        }
    }

    func testGestureIDsAreTheModelLabelsWithoutNone() {
        XCTAssertEqual(GestureID.allCases.map(\.rawValue), Array(GestureContract.labels.dropFirst()))
        XCTAssertEqual(GestureID.flick_up.title, "Flick up")
        XCTAssertEqual(GestureID.double_flick_right.title, "Double flick right")
        XCTAssertEqual(GestureID.double_clap.title, "Double clap")
        XCTAssertEqual(GestureID.wave.title, "Wave")
    }

    func testExactDefaults() {
        XCTAssertEqual(GestureMappings.defaults, [
            .flick_up: .swipe_up, .flick_down: .swipe_down,
            .flick_right: .music_next, .flick_left: .music_previous,
            .snap: .pause_gestures,
            .double_flick_up: GestureActionID.none, .double_flick_down: GestureActionID.none,
            .double_flick_left: GestureActionID.none, .double_flick_right: GestureActionID.none,
            .double_clap: GestureActionID.none, .wave: GestureActionID.none,
        ])
        let mappings = GestureMappings()
        for gesture in GestureID.allCases {
            XCTAssertEqual(mappings[gesture], GestureMappings.defaults[gesture])
            XCTAssertTrue(mappings.isDefault(gesture))
        }
        XCTAssertTrue(mappings.overrides.isEmpty)
    }

    func testActionRawValuesArePinned() {
        XCTAssertEqual(GestureActionID.allCases.map(\.rawValue), [
            "none", "pause_gestures",
            "music_next", "music_previous", "music_play_pause", "music_restart",
            "music_toggle_shuffle", "music_cycle_repeat",
            "flag", "approve", "mark", "ping_phone",
            "swipe_up", "swipe_down", "swipe_left", "swipe_right",
            "hid_media_next", "hid_media_previous", "hid_media_play_pause", "hid_media_stop",
            "hid_volume_up", "hid_volume_down", "hid_mute", "hid_camera_shutter",
            "hid_search", "hid_home", "hid_back", "hid_forward",
            "hid_wheel_up", "hid_wheel_down",
            "hid_key_up", "hid_key_down", "hid_key_left", "hid_key_right",
            "hid_key_page_up", "hid_key_page_down", "hid_key_home", "hid_key_end",
            "hid_key_space", "hid_key_enter", "hid_key_escape", "hid_key_tab",
            "hid_key_backspace", "hid_key_delete", "hid_key_refresh",
            "hid_switch_swipe_up", "hid_switch_swipe_down",
        ])
    }

    func testCatalogExposesOnlyReviewedBackgroundActions() {
        XCTAssertTrue(GestureActionID.allCases.filter(\.isLocked).isEmpty)
        for action in GestureActionID.allCases {
            XCTAssertTrue(action.info.worksInBackground, action.rawValue)
        }
        let hid = GestureActionID.allCases.filter { $0.info.category == .needsRingHID }
        XCTAssertEqual(hid, [
            .swipe_up, .swipe_down, .swipe_left, .swipe_right,
            .hid_media_next, .hid_media_previous, .hid_media_play_pause, .hid_media_stop,
            .hid_volume_up, .hid_volume_down, .hid_mute, .hid_camera_shutter,
            .hid_search, .hid_home, .hid_back, .hid_forward,
            .hid_wheel_up, .hid_wheel_down,
            .hid_key_up, .hid_key_down, .hid_key_left, .hid_key_right,
            .hid_key_page_up, .hid_key_page_down, .hid_key_home, .hid_key_end,
            .hid_key_space, .hid_key_enter, .hid_key_escape, .hid_key_tab,
            .hid_key_backspace, .hid_key_delete, .hid_key_refresh,
            .hid_switch_swipe_up, .hid_switch_swipe_down,
        ])
        XCTAssertTrue(hid.allSatisfy { $0.ringHIDAction != nil })
        XCTAssertEqual(hid.filter { $0.minimumHIDVersion == 8 }.count, 16)
        XCTAssertEqual(hid.filter { $0.minimumHIDVersion == 9 }.count, 19)
        XCTAssertEqual(GestureActionID.hid_switch_swipe_up.ringHIDAction?.command(hidVersion: 10)?.code, 0xbe)
        XCTAssertEqual(GestureActionID.hid_switch_swipe_down.ringHIDAction?.command(hidVersion: 10)?.code, 0xbf)
        XCTAssertTrue(GestureActionCategory.needsRingHID.footnote?.contains("V9") == true)
        let forbidden = ["torch", "flashlight", "homekit", "light", "scene", "shortcut", "speak"]
        for action in GestureActionID.allCases {
            let text = "\(action.rawValue) \(action.info.title)".lowercased()
            XCTAssertFalse(forbidden.contains { text.contains($0) }, text)
            XCTAssertFalse(action.info.title.isEmpty)
            XCTAssertFalse(action.info.detail.isEmpty)
        }
        let music = GestureActionID.allCases.filter { $0.rawValue.hasPrefix("music_") }
        XCTAssertEqual(music.count, 6)
        XCTAssertTrue(music.allSatisfy { $0.info.permission == .appleMusic && $0.info.category == .appleMusic })
        XCTAssertEqual(GestureActionID.ping_phone.info.permission, .notifications)
        XCTAssertEqual(GestureActionID.allCases.filter { $0.info.permission != nil }.count, 7)
        XCTAssertEqual([GestureActionID.flag, .approve, .mark].map(\.info.category), [.research, .research, .research])
    }

    func testOverridesOnlyAndPermissions() {
        var mappings = GestureMappings()
        XCTAssertEqual(mappings.requiredPermissions, [.appleMusic])

        mappings[.wave] = .ping_phone
        mappings[.double_flick_up] = .flag
        XCTAssertEqual(mappings.overrides, [.wave: .ping_phone, .double_flick_up: .flag])
        XCTAssertEqual(mappings.requiredPermissions, [.appleMusic, .notifications])

        mappings[.wave] = GestureActionID.none // back to its default
        XCTAssertEqual(mappings.overrides, [.double_flick_up: .flag])
        mappings.reset(.double_flick_up)
        XCTAssertTrue(mappings.overrides.isEmpty)

        mappings[.flick_right] = .flag
        mappings[.flick_left] = .approve
        XCTAssertEqual(mappings.requiredPermissions, [])
        XCTAssertFalse(mappings.isDefault(.flick_right))
        mappings.resetAll()
        XCTAssertEqual(mappings, GestureMappings())

        XCTAssertEqual(GestureMappings(overrides: [.snap: .pause_gestures, .wave: .mark]).overrides, [.wave: .mark])
    }

    func testStoreRoundTripsOverridesOnly() throws {
        let store = GestureMappingStore(defaults: defaults)
        XCTAssertEqual(store.load(), GestureMappings())

        var mappings = GestureMappings()
        mappings[.snap] = .music_play_pause
        mappings[.double_clap] = .ping_phone
        store.save(mappings)
        XCTAssertEqual(GestureMappingStore(defaults: defaults).load(), mappings)

        let data = try XCTUnwrap(defaults.data(forKey: GestureMappingStore.key))
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(json["version"] as? Int, 1)
        XCTAssertEqual(json["overrides"] as? [String: String],
                       ["snap": "music_play_pause", "double_clap": "ping_phone"])
        XCTAssertEqual(GestureMappingStore.key, "gestureMappings.v1")

        mappings.resetAll()
        store.save(mappings)
        XCTAssertNil(defaults.object(forKey: GestureMappingStore.key))
        XCTAssertEqual(store.load(), GestureMappings())
    }

    func testBadStoredDataFallsBackToDefaults() {
        let store = GestureMappingStore(defaults: defaults)
        defaults.set(Data("not json".utf8), forKey: GestureMappingStore.key)
        XCTAssertEqual(store.load(), GestureMappings())

        defaults.set("a string", forKey: GestureMappingStore.key)
        XCTAssertEqual(store.load(), GestureMappings())

        defaults.set(Data(#"{"version":2,"overrides":{"snap":"flag"}}"#.utf8), forKey: GestureMappingStore.key)
        XCTAssertEqual(store.load(), GestureMappings())

        defaults.set(Data(#"{"overrides":{"snap":"flag"}}"#.utf8), forKey: GestureMappingStore.key)
        XCTAssertEqual(store.load(), GestureMappings())

        // Unknown ids fall back per gesture; valid overrides survive.
        defaults.set(Data(#"{"version":1,"overrides":{"flick_up":"volume_up","clap":"flag","snap":"ping_phone"}}"#.utf8),
                     forKey: GestureMappingStore.key)
        let loaded = store.load()
        XCTAssertEqual(loaded.overrides, [.snap: .ping_phone])
        XCTAssertEqual(loaded[.flick_up], .swipe_up)
    }

    func testV9WheelAmountDefaultsAndBounds() {
        let store = RingHIDWheelSettingsStore(defaults: defaults)
        XCTAssertEqual(store.load(), .standard)
        XCTAssertEqual(RingHIDWheelSettings(amount: -10), .init(amount: 1))
        store.save(.init(amount: 4))
        XCTAssertEqual(store.load(), .init(amount: 4))
        defaults.set(0, forKey: RingHIDWheelSettingsStore.key)
        XCTAssertEqual(store.load(), .init(amount: 1))
        defaults.set(99, forKey: RingHIDWheelSettingsStore.key)
        XCTAssertEqual(store.load(), .init(amount: 5))
        defaults.set("invalid", forKey: RingHIDWheelSettingsStore.key)
        XCTAssertEqual(store.load(), .standard)
    }

    func testV9MappingPersistsWithoutChangingV8Defaults() {
        var mappings = GestureMappings()
        mappings[.wave] = .hid_key_space
        mappings[.double_flick_up] = .hid_wheel_up
        mappings[.double_flick_down] = .hid_switch_swipe_down
        let store = GestureMappingStore(defaults: defaults)
        store.save(mappings)
        XCTAssertEqual(store.load(), mappings)
        XCTAssertEqual(store.load()[.flick_up], .swipe_up)
        XCTAssertEqual(store.load()[.double_flick_down], .hid_switch_swipe_down)
    }
}
