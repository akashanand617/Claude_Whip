import Foundation
import MediaPlayer
import UserNotifications
#if canImport(UIKit)
import UIKit
#endif

enum PermissionState: String, Equatable {
    case notDetermined, denied, restricted, authorized

    var isAuthorized: Bool { self == .authorized }
}

extension PermissionState {
    init(_ status: MPMediaLibraryAuthorizationStatus) {
        switch status {
        case .authorized: self = .authorized
        case .notDetermined: self = .notDetermined
        case .restricted: self = .restricted
        case .denied: self = .denied
        @unknown default: self = .denied
        }
    }

    /// Provisional delivery is still a granted permission; R02 never asks for it.
    init(_ status: UNAuthorizationStatus) {
        switch status {
        case .authorized, .provisional, .ephemeral: self = .authorized
        case .notDetermined: self = .notDetermined
        case .denied: self = .denied
        @unknown default: self = .denied
        }
    }
}

enum MusicCommand: String, CaseIterable {
    case next, previous
    case playPause = "play_pause", restart
    case toggleShuffle = "toggle_shuffle", cycleRepeat = "cycle_repeat"
}

@MainActor
protocol MusicControlling: AnyObject {
    var authorization: PermissionState { get }
    func perform(_ command: MusicCommand) -> GestureActionOutcome
    /// Opens the player connection while no Gesture stream runs; never prompts.
    func prepare()
    /// UI only: may show the system prompt, so never call it from a gesture.
    func requestAuthorization() async -> PermissionState
}

/// The members of `MPMusicPlayerController` R02 uses, so tests can check the
/// commands against a fake player.
@MainActor
protocol MusicPlayerControlling: AnyObject {
    var playbackState: MPMusicPlaybackState { get }
    var indexOfNowPlayingItem: Int { get }
    var shuffleMode: MPMusicShuffleMode { get set }
    var repeatMode: MPMusicRepeatMode { get set }
    func play()
    func pause()
    func skipToNextItem()
    func skipToPreviousItem()
    func skipToBeginning()
}

extension MPMusicPlayerController: MusicPlayerControlling {}

/// Apple's Music app via `systemMusicPlayer`. The player is created on the
/// first authorized command or `prepare()`, never before, and neither prompts:
/// gestures can arrive while R02 is in the background.
///
/// Every call into the system player is synchronous IPC on the main queue,
/// where CoreBluetooth also stamps receipt times. A cold connection (Music not
/// running) can block for a long time, so R02 opens it with `prepare()` before
/// a stream starts, and reports any command slower than `slowCallThreshold`.
@MainActor
final class SystemMusicController: MusicControlling {
    static let slowCallThreshold: TimeInterval = 0.1

    private let status: () -> MPMediaLibraryAuthorizationStatus
    private let makePlayer: () -> MusicPlayerControlling
    private let now: () -> Double
    private var player: MusicPlayerControlling?
    /// (command, seconds) for a call slower than `slowCallThreshold`.
    var onSlowCall: ((String, Double) -> Void)?

    init(status: @escaping () -> MPMediaLibraryAuthorizationStatus = { MPMediaLibrary.authorizationStatus() },
         makePlayer: @escaping () -> MusicPlayerControlling = { MPMusicPlayerController.systemMusicPlayer },
         now: @escaping () -> Double = { ProcessInfo.processInfo.systemUptime }) {
        self.status = status
        self.makePlayer = makePlayer
        self.now = now
    }

    var authorization: PermissionState { PermissionState(status()) }
    var hasPlayer: Bool { player != nil }

    func requestAuthorization() async -> PermissionState {
        let status = await withCheckedContinuation { (continuation: CheckedContinuation<MPMediaLibraryAuthorizationStatus, Never>) in
            MPMediaLibrary.requestAuthorization { continuation.resume(returning: $0) }
        }
        return PermissionState(status)
    }

    func prepare() {
        guard authorization == .authorized else { return }
        timed("prepare") {
            // A server round trip, and the same query `previous` makes.
            _ = resolvedPlayer().indexOfNowPlayingItem
        }
    }

    func perform(_ command: MusicCommand) -> GestureActionOutcome {
        switch authorization {
        case .authorized: break
        case .notDetermined: return .failed("allow Apple Music in R02 first")
        case .denied, .restricted: return .failed("Apple Music access is off")
        }
        let player = resolvedPlayer()
        timed(command.rawValue) {
            switch command {
            case .next: player.skipToNextItem()
            case .previous: Self.previous(on: player)
            case .playPause: player.playbackState == .playing ? player.pause() : player.play()
            case .restart: player.skipToBeginning()
            case .toggleShuffle: player.shuffleMode = Self.toggled(player.shuffleMode)
            case .cycleRepeat: player.repeatMode = Self.cycled(player.repeatMode)
            }
        }
        return .performed
    }

    /// `skipToPreviousItem` at the first queue item ends playback; restart the
    /// song instead, and also when the queue has no usable index (an empty or
    /// infinite queue), so a flick never stops the music.
    static func previous(on player: MusicPlayerControlling) {
        let index = player.indexOfNowPlayingItem
        if index == 0 || index == NSNotFound { player.skipToBeginning() } else { player.skipToPreviousItem() }
    }

    /// Off (or the user's unknown default) turns song shuffle on; any shuffle turns it off.
    nonisolated static func toggled(_ mode: MPMusicShuffleMode) -> MPMusicShuffleMode {
        mode == .off || mode == .default ? .songs : .off
    }

    /// none → all → one → none; the user's unknown default counts as none.
    nonisolated static func cycled(_ mode: MPMusicRepeatMode) -> MPMusicRepeatMode {
        if mode == .all { return .one }
        if mode == .one { return .none }
        return .all
    }

    private func resolvedPlayer() -> MusicPlayerControlling {
        if let player { return player }
        let created = makePlayer()
        player = created
        return created
    }

    private func timed(_ name: String, _ body: () -> Void) {
        let began = now()
        body()
        let elapsed = now() - began
        if elapsed > Self.slowCallThreshold { onSlowCall?(name, elapsed) }
    }
}

@MainActor
protocol NotificationPosting: AnyObject {
    var authorization: PermissionState { get }
    @discardableResult func refreshAuthorization() async -> PermissionState
    /// UI only: may show the system prompt, so never call it from a gesture.
    func requestAuthorization() async -> PermissionState
    func post(title: String, body: String) -> GestureActionOutcome
    /// Posts now under `identifier`, replacing a pending or delivered one.
    func post(title: String, body: String, identifier: String) -> GestureActionOutcome
    /// Delivers after `seconds` unless cancelled or replaced; false when not authorized.
    @discardableResult
    func schedule(title: String, body: String, identifier: String, after seconds: Double) -> Bool
    func cancel(identifier: String)
}

extension NotificationPosting {
    func post(title: String, body: String, identifier: String) -> GestureActionOutcome {
        post(title: title, body: body)
    }

    @discardableResult
    func schedule(title: String, body: String, identifier: String, after seconds: Double) -> Bool { false }

    func cancel(identifier: String) {}
}

/// Immediate local notifications with the default sound, also shown while R02
/// is in front. `authorization` is a cache: refresh it at launch and whenever
/// the app becomes active, because posting must not wait on the system.
@MainActor
final class LocalNotificationPoster: NSObject, NotificationPosting, UNUserNotificationCenterDelegate {
    private let center: UNUserNotificationCenter
    private(set) var authorization: PermissionState = .notDetermined

    init(center: UNUserNotificationCenter = .current()) {
        self.center = center
        super.init()
    }

    /// The center holds its delegate weakly; the caller must retain `self`.
    func installAsDelegate() { center.delegate = self }

    @discardableResult
    func refreshAuthorization() async -> PermissionState {
        let status = await center.notificationSettings().authorizationStatus
        authorization = PermissionState(status)
        return authorization
    }

    func requestAuthorization() async -> PermissionState {
        _ = try? await center.requestAuthorization(options: [.alert, .sound])
        return await refreshAuthorization()
    }

    func post(title: String, body: String) -> GestureActionOutcome {
        post(title: title, body: body, identifier: UUID().uuidString)
    }

    func post(title: String, body: String, identifier: String) -> GestureActionOutcome {
        switch authorization {
        case .authorized: break
        case .notDetermined: return .failed("allow notifications in R02 first")
        case .denied, .restricted: return .failed("notifications are off for R02")
        }
        center.removePendingNotificationRequests(withIdentifiers: [identifier])
        center.add(UNNotificationRequest(identifier: identifier, content: content(title, body), trigger: nil))
        return .performed
    }

    /// Never prompts: an unauthorized schedule does nothing.
    @discardableResult
    func schedule(title: String, body: String, identifier: String, after seconds: Double) -> Bool {
        guard authorization == .authorized, seconds.isFinite else { return false }
        let trigger = UNTimeIntervalNotificationTrigger(timeInterval: max(1, seconds), repeats: false)
        center.add(UNNotificationRequest(identifier: identifier, content: content(title, body), trigger: trigger))
        return true
    }

    func cancel(identifier: String) {
        center.removePendingNotificationRequests(withIdentifiers: [identifier])
    }

    private func content(_ title: String, _ body: String) -> UNMutableNotificationContent {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        return content
    }

    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter, willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        completionHandler([.banner, .sound, .list])
    }
}

#if canImport(UIKit)
@MainActor
final class UIKitHaptics: HapticsPlaying {
    private let notification = UINotificationFeedbackGenerator()
    private let impact = UIImpactFeedbackGenerator(style: .medium)

    func play(_ cue: HapticCue) {
        switch cue {
        case .performed: notification.notificationOccurred(.success)
        case .paused: impact.impactOccurred()
        case .refused: notification.notificationOccurred(.error)
        }
    }
}
#endif

@MainActor
protocol RingHIDControlling: AnyObject {
    /// Synchronously accepts or refuses the action. An accepted write is sent
    /// asynchronously on the mode transport's serialized UART lane.
    func perform(_ action: RingHIDAction) -> GestureActionOutcome
}

@MainActor
final class GestureActionPerformer: GestureActionPerforming {
    static let pingTitle = "R02"
    static let pingBody = "Ping from your ring"

    private let music: MusicControlling
    private let notifications: NotificationPosting
    private let ringHID: RingHIDControlling?
    private let pause: () -> Void

    /// `pause` must only request the return to Health (it may start a Task);
    /// the router has already marked the session ending.
    init(music: MusicControlling, notifications: NotificationPosting,
         ringHID: RingHIDControlling? = nil, pause: @escaping () -> Void) {
        self.music = music; self.notifications = notifications
        self.ringHID = ringHID; self.pause = pause
    }

    func perform(_ action: GestureActionID) -> GestureActionOutcome {
        switch action {
        case .none: return .unassigned
        case .pause_gestures:
            pause()
            return .performed
        case .music_next: return music.perform(.next)
        case .music_previous: return music.perform(.previous)
        case .music_play_pause: return music.perform(.playPause)
        case .music_restart: return music.perform(.restart)
        case .music_toggle_shuffle: return music.perform(.toggleShuffle)
        case .music_cycle_repeat: return music.perform(.cycleRepeat)
        case .flag, .approve, .mark:
            // The event-log line written by the router is the label.
            return .performed
        case .ping_phone: return notifications.post(title: Self.pingTitle, body: Self.pingBody)
        case .swipe_up, .swipe_down, .swipe_left, .swipe_right,
             .hid_media_next, .hid_media_previous, .hid_media_play_pause, .hid_media_stop,
             .hid_volume_up, .hid_volume_down, .hid_mute, .hid_camera_shutter,
             .hid_search, .hid_home, .hid_back, .hid_forward,
             .hid_wheel_up, .hid_wheel_down,
             .hid_key_up, .hid_key_down, .hid_key_left, .hid_key_right,
             .hid_key_page_up, .hid_key_page_down, .hid_key_home, .hid_key_end,
             .hid_key_space, .hid_key_enter, .hid_key_escape, .hid_key_tab,
             .hid_key_backspace, .hid_key_delete, .hid_key_refresh,
             .hid_switch_swipe_up, .hid_switch_swipe_down:
            guard let hidAction = action.ringHIDAction else {
                return .failed("unsupported ring control")
            }
            return ringHID?.perform(hidAction)
                ?? .failed("install and verify the V\(action.minimumHIDVersion ?? 8) HID firmware first")
        }
    }
}
