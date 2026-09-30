import Foundation

// Actions deliberately NOT offered from the iOS app process, because they
// cannot be done reliably while another app is in front:
// - torch: AVCaptureDevice torch control from the background is unverified;
// - HomeKit scenes/lights: need the HomeKit entitlement and a home to control;
// - running a Shortcut: `shortcuts://` URLs only open while R02 is in front;
// - speaking text: needs the `audio` background mode, which R02 does not declare.
// Ring HID actions are different: exactly fingerprinted V8/V9/V10 firmware emits
// standard input reports, so they can target the foreground app or system.

/// Stable identifiers: raw values are persisted in mappings and `flag`/`approve`
/// are written verbatim to the research event log, where Python's
/// `whip.labeling.MAPPED_ACTIONS` joins on them. Never rename a raw value.
enum GestureActionID: String, CaseIterable, Identifiable, Codable {
    case none
    case pause_gestures
    case music_next, music_previous, music_play_pause, music_restart
    case music_toggle_shuffle, music_cycle_repeat
    case flag, approve, mark
    case ping_phone
    case swipe_up, swipe_down, swipe_left, swipe_right
    case hid_media_next, hid_media_previous, hid_media_play_pause, hid_media_stop
    case hid_volume_up, hid_volume_down, hid_mute
    case hid_camera_shutter, hid_search, hid_home, hid_back, hid_forward
    // V9+ reports. Keep their persisted names stable once a mapping is saved.
    case hid_wheel_up, hid_wheel_down
    case hid_key_up, hid_key_down, hid_key_left, hid_key_right
    case hid_key_page_up, hid_key_page_down, hid_key_home, hid_key_end
    case hid_key_space, hid_key_enter, hid_key_escape, hid_key_tab
    case hid_key_backspace, hid_key_delete, hid_key_refresh
    // Dedicated keys for iOS Switch Control recipes. Unlike mouse-wheel or
    // pointer reports, these remain on the keyboard HID path.
    case hid_switch_swipe_up, hid_switch_swipe_down

    var id: String { rawValue }
    var title: String { info.title }
    var isLocked: Bool { info.lockedReason != nil }

    /// The firmware image must be identified by its complete fingerprint;
    /// version text alone never grants this capability.
    var minimumHIDVersion: Int? {
        switch self {
        case .swipe_up, .swipe_down, .swipe_left, .swipe_right,
             .hid_media_next, .hid_media_previous, .hid_media_play_pause, .hid_media_stop,
             .hid_volume_up, .hid_volume_down, .hid_mute, .hid_camera_shutter,
             .hid_search, .hid_home, .hid_back, .hid_forward:
            return 8
        case .hid_wheel_up, .hid_wheel_down,
             .hid_key_up, .hid_key_down, .hid_key_left, .hid_key_right,
             .hid_key_page_up, .hid_key_page_down, .hid_key_home, .hid_key_end,
             .hid_key_space, .hid_key_enter, .hid_key_escape, .hid_key_tab,
             .hid_key_backspace, .hid_key_delete, .hid_key_refresh,
             .hid_switch_swipe_up, .hid_switch_swipe_down:
            return 9
        default:
            return nil
        }
    }

    var info: GestureActionInfo {
        switch self {
        case .none:
            return .init(title: "No action",
                         detail: "The gesture is recognized and logged, and nothing else happens.",
                         category: .session, worksInBackground: true)
        case .pause_gestures:
            return .init(title: "Pause gestures",
                         detail: "Ends the Gesture session and returns the ring to Health. Start again from R02 or Back Tap.",
                         category: .session, worksInBackground: true)
        case .music_next:
            return .init(title: "Next track",
                         detail: "Skips to the next song in the Music app. After the last song, Music goes back to the first and pauses.",
                         category: .appleMusic, worksInBackground: true, permission: .appleMusic)
        case .music_previous:
            return .init(title: "Previous track",
                         detail: "Goes back to the previous song in the Music app. On the first song it restarts that song.",
                         category: .appleMusic, worksInBackground: true, permission: .appleMusic)
        case .music_play_pause:
            return .init(title: "Play / pause", detail: "Pauses the Music app if it is playing, otherwise plays.",
                         category: .appleMusic, worksInBackground: true, permission: .appleMusic)
        case .music_restart:
            return .init(title: "Restart song", detail: "Jumps to the beginning of the current song.",
                         category: .appleMusic, worksInBackground: true, permission: .appleMusic)
        case .music_toggle_shuffle:
            return .init(title: "Shuffle on / off", detail: "Turns song shuffle in the Music app on or off.",
                         category: .appleMusic, worksInBackground: true, permission: .appleMusic)
        case .music_cycle_repeat:
            return .init(title: "Cycle repeat", detail: "Steps Music repeat through off, all and one.",
                         category: .appleMusic, worksInBackground: true, permission: .appleMusic)
        case .flag:
            return .init(title: "Flag",
                         detail: "Research label: writes “flag” to the gesture event log. Nothing else happens.",
                         category: .research, worksInBackground: true)
        case .approve:
            return .init(title: "Approve",
                         detail: "Research label: writes “approve” to the gesture event log. Nothing else happens.",
                         category: .research, worksInBackground: true)
        case .mark:
            return .init(title: "Mark",
                         detail: "Writes a timestamped “mark” to the gesture event log. Nothing else happens.",
                         category: .research, worksInBackground: true)
        case .ping_phone:
            return .init(title: "Ping phone",
                         detail: "Posts a notification with a sound on this iPhone. Silent mode and Focus can mute it.",
                         category: .alerts, worksInBackground: true, permission: .notifications)
        case .swipe_up:
            return .init(title: "Swipe up",
                         detail: "Uses an AssistiveTouch mouse drag in the app on screen, such as moving to the next Reel.",
                         category: .needsRingHID, worksInBackground: true)
        case .swipe_down:
            return .init(title: "Swipe down",
                         detail: "Uses an AssistiveTouch mouse drag downward in the app on screen.",
                         category: .needsRingHID, worksInBackground: true)
        case .swipe_left:
            return .init(title: "Swipe left", detail: "Uses an AssistiveTouch mouse drag left in the app on screen.",
                         category: .needsRingHID, worksInBackground: true)
        case .swipe_right:
            return .init(title: "Swipe right", detail: "Uses an AssistiveTouch mouse drag right in the app on screen.",
                         category: .needsRingHID, worksInBackground: true)
        case .hid_media_next:
            return .init(title: "Media next", detail: "Sends the standard next-track key to the active media app.",
                         category: .needsRingHID, worksInBackground: true)
        case .hid_media_previous:
            return .init(title: "Media previous", detail: "Sends the standard previous-track key to the active media app.",
                         category: .needsRingHID, worksInBackground: true)
        case .hid_media_play_pause:
            return .init(title: "Media play / pause", detail: "Sends the standard play/pause key to the active media app.",
                         category: .needsRingHID, worksInBackground: true)
        case .hid_media_stop:
            return .init(title: "Media stop", detail: "Sends the standard stop key to the active media app.",
                         category: .needsRingHID, worksInBackground: true)
        case .hid_volume_up:
            return .init(title: "Volume up", detail: "Sends the standard volume-up key from the ring.",
                         category: .needsRingHID, worksInBackground: true)
        case .hid_volume_down:
            return .init(title: "Volume down", detail: "Sends the standard volume-down key from the ring.",
                         category: .needsRingHID, worksInBackground: true)
        case .hid_mute:
            return .init(title: "Mute", detail: "Sends the standard mute key from the ring.",
                         category: .needsRingHID, worksInBackground: true)
        case .hid_camera_shutter:
            return .init(title: "Camera shutter", detail: "Sends Volume Up, which takes a photo while Camera is in front.",
                         category: .needsRingHID, worksInBackground: true)
        case .hid_search:
            return .init(title: "Search", detail: "Sends the standard Search control. App support varies.",
                         category: .needsRingHID, worksInBackground: true)
        case .hid_home:
            return .init(title: "Home", detail: "Sends the standard Home control. iPhone support is experimental.",
                         category: .needsRingHID, worksInBackground: true)
        case .hid_back:
            return .init(title: "Navigate back", detail: "Sends the standard browser/app Back key. App support varies.",
                         category: .needsRingHID, worksInBackground: true)
        case .hid_forward:
            return .init(title: "Navigate forward", detail: "Sends the standard browser/app Forward key. App support varies.",
                         category: .needsRingHID, worksInBackground: true)
        case .hid_wheel_up:
            return .init(title: "Mouse wheel up", detail: "Sends a mouse-wheel step upward. iPhone may require AssistiveTouch/pointer support.",
                         category: .needsRingHID, worksInBackground: true)
        case .hid_wheel_down:
            return .init(title: "Mouse wheel down", detail: "Sends a mouse-wheel step downward. iPhone may require AssistiveTouch/pointer support.",
                         category: .needsRingHID, worksInBackground: true)
        case .hid_key_up: return keyInfo("Arrow up", "Up-arrow key")
        case .hid_key_down: return keyInfo("Arrow down", "Down-arrow key")
        case .hid_key_left: return keyInfo("Arrow left", "Left-arrow key")
        case .hid_key_right: return keyInfo("Arrow right", "Right-arrow key")
        case .hid_key_page_up: return keyInfo("Page up", "Page Up key")
        case .hid_key_page_down: return keyInfo("Page down", "Page Down key")
        case .hid_key_home: return keyInfo("Home key", "Home key")
        case .hid_key_end: return keyInfo("End key", "End key")
        case .hid_key_space: return keyInfo("Space", "Space key")
        case .hid_key_enter: return keyInfo("Return", "Return key")
        case .hid_key_escape: return keyInfo("Escape", "Escape key")
        case .hid_key_tab: return keyInfo("Tab", "Tab key")
        case .hid_key_backspace: return keyInfo("Backspace", "Backspace key")
        case .hid_key_delete: return keyInfo("Forward delete", "Forward Delete key")
        case .hid_key_refresh: return keyInfo("Refresh (F5)", "F5 key")
        case .hid_switch_swipe_up:
            return .init(title: "Switch swipe up (F5)",
                         detail: "Sends F5 to an iOS Switch Control recipe that performs a real upward touch swipe. Requires one-time setup.",
                         category: .needsRingHID, worksInBackground: true)
        case .hid_switch_swipe_down:
            return .init(title: "Switch swipe down (F6)",
                         detail: "Sends F6 to an iOS Switch Control recipe that performs a real downward touch swipe. Requires one-time setup.",
                         category: .needsRingHID, worksInBackground: true)
        }
    }

    private func keyInfo(_ title: String, _ key: String) -> GestureActionInfo {
        .init(title: title, detail: "Sends the \(key) to the app on screen. App support varies.",
              category: .needsRingHID, worksInBackground: true)
    }

    var ringHIDAction: RingHIDAction? {
        switch self {
        case .swipe_up: return .swipeUp
        case .swipe_down: return .swipeDown
        case .swipe_left: return .swipeLeft
        case .swipe_right: return .swipeRight
        case .hid_media_next: return .nextTrack
        case .hid_media_previous: return .previousTrack
        case .hid_media_play_pause: return .playPause
        case .hid_media_stop: return .stopMedia
        case .hid_volume_up: return .volumeUp
        case .hid_volume_down: return .volumeDown
        case .hid_mute: return .mute
        case .hid_camera_shutter: return .volumeUp
        case .hid_search: return .search
        case .hid_home: return .home
        case .hid_back: return .back
        case .hid_forward: return .forward
        case .hid_wheel_up: return .wheelUp
        case .hid_wheel_down: return .wheelDown
        case .hid_key_up: return .keyUp
        case .hid_key_down: return .keyDown
        case .hid_key_left: return .keyLeft
        case .hid_key_right: return .keyRight
        case .hid_key_page_up: return .keyPageUp
        case .hid_key_page_down: return .keyPageDown
        case .hid_key_home: return .keyHome
        case .hid_key_end: return .keyEnd
        case .hid_key_space: return .keySpace
        case .hid_key_enter: return .keyEnter
        case .hid_key_escape: return .keyEscape
        case .hid_key_tab: return .keyTab
        case .hid_key_backspace: return .keyBackspace
        case .hid_key_delete: return .keyDelete
        case .hid_key_refresh: return .keyRefresh
        case .hid_switch_swipe_up: return .keyRefresh
        case .hid_switch_swipe_down: return .keyF6
        default: return nil
        }
    }
}

enum GestureActionCategory: String, CaseIterable, Identifiable {
    case session, appleMusic, research, alerts, needsRingHID

    var id: String { rawValue }
    var title: String {
        switch self {
        case .session: return "Session"
        case .appleMusic: return "Apple Music"
        case .research: return "Research labels"
        case .alerts: return "Alerts"
        case .needsRingHID: return "Ring controls"
        }
    }
    var footnote: String? {
        switch self {
        case .appleMusic:
            return "Controls Apple's Music app only. Other players, such as Spotify or YouTube, can't be controlled by another app."
        case .research:
            return "Labels go to the event log for `python -m probe.label join`."
        case .needsRingHID:
            return "Ring controls need exact verified HID firmware: V8 for swipes/media or V10 for keyboard controls. Mouse drags/wheel may require AssistiveTouch; Switch swipes use iOS Switch Control instead. Installed V9 remains recognized but is superseded."
        case .session, .alerts:
            return nil
        }
    }
}

enum GesturePermission: String, CaseIterable, Identifiable {
    case appleMusic, notifications

    var id: String { rawValue }
    var title: String {
        switch self {
        case .appleMusic: return "Apple Music"
        case .notifications: return "Notifications"
        }
    }
}

struct GestureActionInfo: Equatable {
    let title: String
    let detail: String
    let category: GestureActionCategory
    let worksInBackground: Bool
    /// Non-nil means the action is shown but can never be performed.
    let lockedReason: String?
    let permission: GesturePermission?

    init(title: String, detail: String, category: GestureActionCategory, worksInBackground: Bool,
         lockedReason: String? = nil, permission: GesturePermission? = nil) {
        self.title = title; self.detail = detail; self.category = category
        self.worksInBackground = worksInBackground
        self.lockedReason = lockedReason; self.permission = permission
    }
}

extension GestureID {
    /// Engine events carry the collapsed label plus a direction; only the
    /// flick families are direction-split. Anything outside the pinned
    /// vocabulary, including a flick without a direction, is unrecognized.
    init?(event: RingGestureEvent) {
        switch event.name {
        case "flick", "double_flick":
            guard ["up", "down", "left", "right"].contains(event.direction) else { return nil }
            self.init(rawValue: "\(event.name)_\(event.direction)")
        case "snap", "double_clap", "wave":
            self.init(rawValue: event.name)
        default:
            return nil
        }
    }

    var title: String {
        let words = rawValue.replacingOccurrences(of: "_", with: " ")
        return words.prefix(1).uppercased() + words.dropFirst()
    }
}

/// Stores only the user's overrides; everything else resolves to `defaults`.
struct GestureMappings: Equatable {
    static let defaults: [GestureID: GestureActionID] = Dictionary(
        uniqueKeysWithValues: GestureID.allCases.map { ($0, defaultAction(for: $0)) }
    )

    static func defaultAction(for gesture: GestureID) -> GestureActionID {
        switch gesture {
        case .flick_up: return .swipe_up
        case .flick_down: return .swipe_down
        case .flick_right: return .music_next
        case .flick_left: return .music_previous
        case .snap: return .pause_gestures
        case .double_flick_up, .double_flick_down, .double_flick_left, .double_flick_right,
             .double_clap, .wave:
            return .none
        }
    }

    private(set) var overrides: [GestureID: GestureActionID]

    init(overrides: [GestureID: GestureActionID] = [:]) {
        self.overrides = overrides.filter { $0.value != Self.defaultAction(for: $0.key) }
    }

    subscript(gesture: GestureID) -> GestureActionID {
        get { overrides[gesture] ?? Self.defaultAction(for: gesture) }
        set {
            overrides[gesture] = newValue == Self.defaultAction(for: gesture) ? nil : newValue
        }
    }

    func isDefault(_ gesture: GestureID) -> Bool { overrides[gesture] == nil }

    mutating func reset(_ gesture: GestureID) { overrides[gesture] = nil }

    mutating func resetAll() { overrides.removeAll() }

    var requiredPermissions: Set<GesturePermission> {
        Set(GestureID.allCases.compactMap { self[$0].info.permission })
    }
}

/// Versioned JSON of overrides only. Unreadable data or a different version
/// falls back to the defaults as a whole; an unknown gesture or action id falls
/// back to that gesture's default and leaves the other overrides intact.
struct GestureMappingStore {
    static let key = "gestureMappings.v1"
    static let version = 1

    private struct Stored: Codable {
        let version: Int
        let overrides: [String: String]
    }

    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    func load() -> GestureMappings {
        guard let data = defaults.data(forKey: Self.key),
              let stored = try? JSONDecoder().decode(Stored.self, from: data),
              stored.version == Self.version else { return GestureMappings() }
        var overrides: [GestureID: GestureActionID] = [:]
        for (gesture, action) in stored.overrides {
            guard let gesture = GestureID(rawValue: gesture),
                  let action = GestureActionID(rawValue: action) else { continue }
            overrides[gesture] = action
        }
        return GestureMappings(overrides: overrides)
    }

    func save(_ mappings: GestureMappings) {
        guard !mappings.overrides.isEmpty else {
            defaults.removeObject(forKey: Self.key)
            return
        }
        let stored = Stored(version: Self.version, overrides: Dictionary(
            uniqueKeysWithValues: mappings.overrides.map { ($0.key.rawValue, $0.value.rawValue) }
        ))
        guard let data = try? JSONEncoder().encode(stored) else { return }
        defaults.set(data, forKey: Self.key)
    }
}

/// Phone-side wheel amount for fingerprint-gated V9/V10 HID. V8 ignores it.
struct RingHIDWheelSettings: Equatable {
    static let range = 1...5
    static let standard = RingHIDWheelSettings(amount: 3)

    var amount: Int

    init(amount: Int) {
        self.amount = min(max(amount, Self.range.lowerBound), Self.range.upperBound)
    }
}

struct RingHIDWheelSettingsStore {
    static let key = "ringHID.wheelAmount.v1"

    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) { self.defaults = defaults }

    func load() -> RingHIDWheelSettings {
        RingHIDWheelSettings(amount: defaults.object(forKey: Self.key) as? Int
                             ?? RingHIDWheelSettings.standard.amount)
    }

    func save(_ settings: RingHIDWheelSettings) {
        defaults.set(RingHIDWheelSettings(amount: settings.amount).amount, forKey: Self.key)
    }
}

/// "Pause when idle": ends a Gesture session after this long without a
/// recognized gesture. Separate from the fixed session timer.
enum GestureIdlePause: Int, CaseIterable, Identifiable {
    case off = 0
    case fiveMinutes = 300
    case fifteenMinutes = 900
    case thirtyMinutes = 1_800

    static let `default`: Self = .fifteenMinutes
    static let storageKey = "gestureIdlePauseSeconds"

    var id: Int { rawValue }
    var seconds: TimeInterval? { self == .off ? nil : TimeInterval(rawValue) }
    var title: String {
        switch self {
        case .off: return "Off"
        case .fiveMinutes: return "5 minutes"
        case .fifteenMinutes: return "15 minutes"
        case .thirtyMinutes: return "30 minutes"
        }
    }

    /// A missing key is the default, not `off`: `UserDefaults.integer` reads 0.
    static func stored(in defaults: UserDefaults = .standard) -> Self {
        guard let value = defaults.object(forKey: storageKey) as? Int else { return .default }
        return Self(rawValue: value) ?? .default
    }

    func store(in defaults: UserDefaults = .standard) {
        defaults.set(rawValue, forKey: Self.storageKey)
    }
}

/// Pure idle deadline on the uptime clock. The owner starts it with the
/// session, reports each recognized gesture, and polls `isExpired(at:)`.
struct GestureIdleTracker: Equatable {
    var policy: GestureIdlePause
    private(set) var lastActivity: Double?

    init(policy: GestureIdlePause) {
        self.policy = policy
    }

    mutating func start(at time: Double) {
        lastActivity = time.isFinite ? time : nil
    }

    /// Activity never moves the deadline earlier; a stale or non-finite time is ignored.
    mutating func activity(at time: Double) {
        guard time.isFinite, let last = lastActivity else { return }
        lastActivity = max(last, time)
    }

    mutating func stop() { lastActivity = nil }

    var deadline: Double? {
        guard let seconds = policy.seconds, let lastActivity else { return nil }
        return lastActivity + seconds
    }

    func remaining(at time: Double) -> Double? {
        deadline.map { max(0, $0 - time) }
    }

    func isExpired(at time: Double) -> Bool {
        guard let deadline, time.isFinite else { return false }
        return time >= deadline
    }
}
