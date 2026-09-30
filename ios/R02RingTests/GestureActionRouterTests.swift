import MediaPlayer
import XCTest
@testable import R02Ring

@MainActor
private final class FakePerformer: GestureActionPerforming {
    var performed: [GestureActionID] = []
    var outcome: GestureActionOutcome = .performed
    var onPerform: ((GestureActionID) -> Void)?

    func perform(_ action: GestureActionID) -> GestureActionOutcome {
        performed.append(action)
        onPerform?(action)
        return outcome
    }
}

@MainActor
private final class FakeHaptics: HapticsPlaying {
    var cues: [HapticCue] = []
    func play(_ cue: HapticCue) { cues.append(cue) }
}

@MainActor
private final class FakeLog: GestureEventLogging {
    var records: [(name: String, action: GestureActionID?, wall: Double)] = []
    var closed = false
    func record(_ event: RingGestureEvent, action: GestureActionID?, wall: Double) {
        records.append((event.name, action, wall))
    }
    func close() { closed = true }
}

@MainActor
final class GestureActionRouterTests: XCTestCase {
    private var performer: FakePerformer!
    private var haptics: FakeHaptics!
    private var log: FakeLog!
    private var router: GestureActionRouter!
    private var generation = UUID()
    private var clock = 1_790_000_000.0
    private let front = GestureActionRouter.Context(foreground: true, hapticsEnabled: true)

    override func setUp() {
        super.setUp()
        performer = FakePerformer()
        haptics = FakeHaptics()
        log = FakeLog()
        clock = 1_790_000_000
        router = GestureActionRouter(performer: performer, haptics: haptics, wall: { [unowned self] in
            clock += 1
            return clock
        })
        generation = UUID()
        router.begin(generation: generation, log: log)
        router.calibrated(at: 100)
    }

    private func event(_ name: String, _ direction: String = "none", at time: Double) -> RingGestureEvent {
        RingGestureEvent(name: name, direction: direction, time: time, confidence: 0.9, votes: 3,
                         latency: 1.2, end: time + 0.4)
    }

    @discardableResult
    private func route(_ events: [RingGestureEvent], context: GestureActionRouter.Context? = nil) -> [GestureDispatch] {
        router.route(events, generation: generation, context: context ?? front)
    }

    func testPerformedActionIsLoggedByNameWithDispatchWall() {
        let dispatches = route([event("flick", "right", at: 105)])
        XCTAssertEqual(dispatches.count, 1)
        let dispatch = dispatches[0]
        XCTAssertEqual(dispatch.gesture, .flick_right)
        XCTAssertEqual(dispatch.action, .music_next)
        XCTAssertEqual(dispatch.outcome, .performed)
        XCTAssertEqual(dispatch.generation, generation)
        XCTAssertEqual(dispatch.wall, 1_790_000_001)
        XCTAssertEqual(dispatch.summary, "Flick right → Next track · done")
        XCTAssertEqual(performer.performed, [.music_next])
        XCTAssertEqual(log.records.map { $0.action }, [.music_next])
        XCTAssertEqual(log.records.map { $0.wall }, [1_790_000_001])
        XCTAssertEqual(haptics.cues, [.performed])
        XCTAssertEqual(router.lastDispatch, dispatch)
        XCTAssertEqual(router.recentDispatches, [dispatch])
    }

    func testUnassignedAndUnrecognizedAreLoggedNull() {
        let dispatches = route([event("double_clap", at: 105), event("clap", at: 110), event("flick", "none", at: 115)])
        XCTAssertEqual(dispatches.map(\.outcome), [.unassigned, .unrecognized, .unrecognized])
        XCTAssertEqual(dispatches.map(\.gesture), [.double_clap, nil, nil])
        XCTAssertEqual(dispatches[0].action, GestureActionID.none)
        XCTAssertNil(dispatches[1].action)
        XCTAssertEqual(log.records.map { $0.name }, ["double_clap", "clap", "flick"])
        XCTAssertTrue(log.records.allSatisfy { $0.action == nil })
        XCTAssertTrue(performer.performed.isEmpty)
        XCTAssertTrue(haptics.cues.isEmpty)
        XCTAssertEqual(dispatches[0].summary, "Double clap · no action assigned")
        XCTAssertEqual(dispatches[1].summary, "clap · not recognized")
    }

    func testCooldownIsMeasuredOnStreamOnsetsOfActedEvents() {
        let dispatches = route([event("flick", "right", at: 105), event("flick", "left", at: 105.5),
                                event("flick", "left", at: 106.0)])
        XCTAssertEqual(dispatches.map(\.outcome), [.performed, .suppressed(.cooldown), .performed])
        XCTAssertEqual(performer.performed, [.music_next, .music_previous])
        XCTAssertEqual(log.records.map { $0.action }, [.music_next, nil, .music_previous])

        // The boundary is inclusive: exactly 0.75 s later is allowed, also across batches.
        XCTAssertEqual(route([event("flick", "right", at: 106.75)]).map(\.outcome), [.performed])
        // An out-of-order older onset inside the cooldown is suppressed too.
        XCTAssertEqual(route([event("flick", "right", at: 106.5)]).map(\.outcome), [.suppressed(.cooldown)])
        // Unassigned gestures start a cooldown as well: one movement, one outcome.
        XCTAssertEqual(route([event("wave", at: 110), event("flick", "right", at: 110.3)]).map(\.outcome),
                       [.unassigned, .suppressed(.cooldown)])
    }

    func testSettleWindowAfterCalibration() {
        XCTAssertEqual(route([event("flick", "right", at: 100.5)]).map(\.outcome), [.suppressed(.settling)])
        router.calibrated(at: 200) // first call per session wins
        XCTAssertEqual(route([event("flick", "right", at: 101.0)]).map(\.outcome), [.performed])
        XCTAssertEqual(log.records.map { $0.action }, [nil, .music_next])

        let uncalibrated = UUID()
        router.begin(generation: uncalibrated, log: log)
        XCTAssertEqual(router.route([event("flick", "right", at: 500)], generation: uncalibrated, context: front)
            .map(\.outcome), [.suppressed(.settling)])
    }

    func testASuspendedSessionDropsLateEventsUnloggedAndAResumedOneSettlesAgain() {
        XCTAssertEqual(route([event("flick", "right", at: 105)]).map(\.outcome), [.performed])
        router.suspend() // a heal: the old segment's late events
        XCTAssertEqual(route([event("flick", "right", at: 106)]), [])
        XCTAssertNil(router.generation)
        XCTAssertFalse(log.closed, "the user's session log stays open across a heal")
        let healed = UUID()
        router.resume(generation: healed)
        XCTAssertEqual(router.route([event("flick", "right", at: 107)], generation: generation, context: front), [],
                       "the old generation stays dropped")
        XCTAssertEqual(router.route([event("flick", "right", at: 110)], generation: healed, context: front)
            .map(\.outcome), [.suppressed(.settling)], "nothing dispatches before the healed segment calibrates")
        router.calibrated(at: 111)
        XCTAssertEqual(router.route([event("flick", "right", at: 111.5)], generation: healed, context: front)
            .map(\.outcome), [.suppressed(.settling)])
        XCTAssertEqual(router.route([event("flick", "right", at: 112.2)], generation: healed, context: front)
            .map(\.outcome), [.performed])
        XCTAssertEqual(log.records.count, 4, "one line per routed event; none for the dropped ones")
        router.end()
        XCTAssertTrue(log.closed)
    }

    func testStaleGenerationsAreDroppedUnlogged() {
        XCTAssertEqual(router.route([event("snap", at: 105)], generation: UUID(), context: front), [])
        router.end()
        XCTAssertTrue(log.closed)
        XCTAssertEqual(route([event("snap", at: 106)]), [])
        XCTAssertTrue(log.records.isEmpty)
        XCTAssertTrue(performer.performed.isEmpty)
        XCTAssertNil(router.lastDispatch)
        XCTAssertNil(router.generation)

        let fresh = GestureActionRouter(performer: performer, haptics: haptics)
        XCTAssertEqual(fresh.route([event("snap", at: 105)], generation: generation, context: front), [])
    }

    func testSuppressionOrderDiagnosticsThenEndingThenSettling() {
        var context = front
        context.diagnosticsRunning = true
        context.sessionEnding = true
        XCTAssertEqual(route([event("flick", "right", at: 100.2)], context: context).map(\.outcome),
                       [.suppressed(.diagnostics)])
        context.diagnosticsRunning = false
        XCTAssertEqual(route([event("flick", "right", at: 100.2)], context: context).map(\.outcome),
                       [.suppressed(.sessionEnding)])
        context.sessionEnding = false
        XCTAssertEqual(route([event("flick", "right", at: 100.2)], context: context).map(\.outcome),
                       [.suppressed(.settling)])
        XCTAssertTrue(performer.performed.isEmpty)
        XCTAssertEqual(log.records.map { $0.action }, [nil, nil, nil])
        // Suppressed gestures do not start a cooldown.
        XCTAssertEqual(route([event("flick", "right", at: 105)]).map(\.outcome), [.performed])
    }

    func testPauseFiresExactlyOnceAcrossBatches() {
        var endingWhenPerformed: [Bool] = []
        performer.onPerform = { [unowned self] _ in endingWhenPerformed.append(router.isEnding) }
        let first = route([event("snap", at: 105), event("snap", at: 107), event("flick", "right", at: 109)])
        XCTAssertEqual(first.map(\.outcome), [.performed, .suppressed(.sessionEnding), .suppressed(.sessionEnding)])
        XCTAssertEqual(route([event("snap", at: 111)]).map(\.outcome), [.suppressed(.sessionEnding)])
        XCTAssertEqual(performer.performed, [.pause_gestures])
        XCTAssertEqual(endingWhenPerformed, [true])
        XCTAssertEqual(haptics.cues, [.paused])
        XCTAssertEqual(log.records.map { $0.action }, [.pause_gestures, nil, nil, nil])

        let next = UUID()
        router.begin(generation: next, log: log)
        XCTAssertFalse(router.isEnding)
        router.calibrated(at: 0)
        XCTAssertEqual(router.route([event("snap", at: 5)], generation: next, context: front).map(\.outcome),
                       [.performed])
        XCTAssertEqual(performer.performed, [.pause_gestures, .pause_gestures])
    }

    func testFailedOrCancelledPauseResumesRouting() {
        performer.outcome = .failed("busy")
        XCTAssertEqual(route([event("snap", at: 105)]).map(\.outcome), [.failed("busy")])
        XCTAssertFalse(router.isEnding)
        XCTAssertEqual(haptics.cues, [.refused])

        performer.outcome = .performed
        XCTAssertEqual(route([event("snap", at: 107), event("flick", "right", at: 109)]).map(\.outcome),
                       [.performed, .suppressed(.sessionEnding)])
        XCTAssertTrue(router.isEnding)
        router.cancelEnding(generation: UUID()) // another session's cancel is ignored
        XCTAssertTrue(router.isEnding)
        router.cancelEnding(generation: generation)
        XCTAssertFalse(router.isEnding)
        XCTAssertEqual(route([event("flick", "right", at: 111)]).map(\.outcome), [.performed])
        XCTAssertEqual(performer.performed, [.pause_gestures, .pause_gestures, .music_next])
    }

    func testPerformerEndingTheSessionStopsTheBatch() {
        performer.onPerform = { [unowned self] _ in router.end() }
        let dispatches = route([event("snap", at: 105), event("flick", "right", at: 110)])
        XCTAssertEqual(dispatches.map(\.outcome), [.performed])
        XCTAssertEqual(router.lastDispatch?.gesture, .snap)
        XCTAssertEqual(log.records.count, 1)
    }

    func testHIDActionsReachTheCapabilityGatedPerformer() {
        let dispatches = route([event("flick", "up", at: 105), event("flick", "down", at: 110)])
        XCTAssertEqual(dispatches.map(\.action), [.swipe_up, .swipe_down])
        XCTAssertEqual(dispatches.map(\.outcome), [.performed, .performed])
        XCTAssertEqual(performer.performed, [.swipe_up, .swipe_down])
        XCTAssertEqual(log.records.map { $0.action }, [.swipe_up, .swipe_down])
        XCTAssertEqual(haptics.cues, [.performed, .performed])
        XCTAssertEqual(dispatches[0].summary, "Flick up → Swipe up · done")
    }

    func testHapticsOnlyInForegroundWithSettingOn() {
        route([event("flick", "right", at: 105)], context: .init(foreground: false, hapticsEnabled: true))
        route([event("flick", "right", at: 110)], context: .init(foreground: true, hapticsEnabled: false))
        route([event("flick", "up", at: 115)], context: .init(foreground: false, hapticsEnabled: true))
        XCTAssertEqual(performer.performed, [.music_next, .music_next, .swipe_up])
        XCTAssertTrue(haptics.cues.isEmpty)

        performer.outcome = .failed("Apple Music access is off")
        let failed = route([event("flick", "left", at: 120)])
        XCTAssertEqual(failed.map(\.outcome), [.failed("Apple Music access is off")])
        XCTAssertEqual(haptics.cues, [.refused])
        XCTAssertEqual(log.records.last?.action, .music_previous)
        XCTAssertEqual(failed[0].summary, "Flick left → Previous track · Apple Music access is off")
    }

    func testRecognizedGesturesSignalIdleActivity() {
        var context = front
        context.diagnosticsRunning = true
        let dispatches = route([event("flick", "right", at: 105)], context: context)
            + route([event("double_clap", at: 110), event("clap", at: 115), event("flick", "right", at: 115.2)])
        XCTAssertEqual(dispatches.map(\.outcome),
                       [.suppressed(.diagnostics), .unassigned, .unrecognized, .performed])
        XCTAssertEqual(dispatches.map(\.isActivity), [true, true, false, true])
    }

    func testMappingsAreReadAtRouteTime() {
        router.mappings[.wave] = .flag
        router.mappings[.double_flick_up] = .approve
        route([event("wave", "left", at: 105), event("double_flick", "up", at: 110)])
        XCTAssertEqual(performer.performed, [.flag, .approve])
        XCTAssertEqual(log.records.map { $0.action }, [.flag, .approve])
    }

    func testRecentDispatchesAreCappedAndEmptyBatchesPublishNothing() {
        XCTAssertEqual(route([]), [])
        XCTAssertNil(router.lastDispatch)
        let events = (0..<25).map { event("double_clap", at: 105 + Double($0)) }
        let dispatches = route(events)
        XCTAssertEqual(router.recentDispatches.count, GestureActionRouter.recentLimit)
        XCTAssertEqual(router.recentDispatches, Array(dispatches.suffix(20)))
        XCTAssertEqual(router.lastDispatch, dispatches.last)
        router.end()
        XCTAssertEqual(router.lastDispatch, dispatches.last) // kept for the UI after the session
    }

    func testBeginClosesThePreviousLog() {
        let next = FakeLog()
        router.begin(generation: UUID(), log: next)
        XCTAssertTrue(log.closed)
        XCTAssertFalse(next.closed)
        XCTAssertEqual(router.timing, .standard)
        XCTAssertEqual(router.timing.cooldown, 0.75)
        XCTAssertEqual(router.timing.settle, 1.0)
    }
}

@MainActor
private final class FakeMusic: MusicControlling {
    var authorization: PermissionState = .authorized
    var commands: [MusicCommand] = []
    var requests = 0
    var prepared = 0
    func perform(_ command: MusicCommand) -> GestureActionOutcome {
        commands.append(command)
        return authorization == .authorized ? .performed : .failed("off")
    }
    func prepare() { prepared += 1 }
    func requestAuthorization() async -> PermissionState { requests += 1; return authorization }
}

@MainActor
private final class FakeNotifications: NotificationPosting {
    var authorization: PermissionState = .authorized
    var posts: [(String, String)] = []
    var requests = 0
    func refreshAuthorization() async -> PermissionState { authorization }
    func requestAuthorization() async -> PermissionState { requests += 1; return authorization }
    func post(title: String, body: String) -> GestureActionOutcome {
        posts.append((title, body))
        return .performed
    }
}

@MainActor
private final class FakeRingHID: RingHIDControlling {
    var actions: [RingHIDAction] = []
    var outcome: GestureActionOutcome = .performed
    func perform(_ action: RingHIDAction) -> GestureActionOutcome {
        actions.append(action)
        return outcome
    }
}

@MainActor
final class GestureActionPerformerTests: XCTestCase {
    func testEachActionReachesItsPerformerWithoutPrompting() {
        let music = FakeMusic(), notifications = FakeNotifications(), ringHID = FakeRingHID()
        var pauses = 0
        let performer = GestureActionPerformer(
            music: music, notifications: notifications, ringHID: ringHID,
            pause: { pauses += 1 }
        )
        let expected: [(GestureActionID, MusicCommand)] = [
            (.music_next, .next), (.music_previous, .previous), (.music_play_pause, .playPause),
            (.music_restart, .restart), (.music_toggle_shuffle, .toggleShuffle), (.music_cycle_repeat, .cycleRepeat),
        ]
        for (action, _) in expected { XCTAssertEqual(performer.perform(action), .performed) }
        XCTAssertEqual(music.commands, expected.map { $0.1 })

        for action in [GestureActionID.flag, .approve, .mark] { XCTAssertEqual(performer.perform(action), .performed) }
        XCTAssertEqual(performer.perform(.ping_phone), .performed)
        XCTAssertEqual(notifications.posts.count, 1)
        XCTAssertEqual(notifications.posts.first?.0, GestureActionPerformer.pingTitle)
        XCTAssertEqual(performer.perform(.pause_gestures), .performed)
        XCTAssertEqual(pauses, 1)
        XCTAssertEqual(performer.perform(GestureActionID.none), .unassigned)
        let hidActions = GestureActionID.allCases.filter { $0.ringHIDAction != nil }
        for action in hidActions { XCTAssertEqual(performer.perform(action), .performed) }
        XCTAssertEqual(ringHID.actions, hidActions.compactMap(\.ringHIDAction))
        XCTAssertEqual(music.commands.count, 6)
        XCTAssertEqual(music.requests + notifications.requests, 0)
    }

    func testHIDActionsFailClosedWithoutAnExactFirmwareController() {
        let performer = GestureActionPerformer(
            music: FakeMusic(), notifications: FakeNotifications(), pause: {}
        )
        for action in GestureActionID.allCases where action.ringHIDAction != nil {
            XCTAssertEqual(performer.perform(action),
                           .failed("install and verify the V\(action.minimumHIDVersion ?? 8) HID firmware first"))
        }
    }

    func testSystemMusicNeverCreatesThePlayerWithoutAuthorization() {
        for status in [MPMediaLibraryAuthorizationStatus.notDetermined, .denied, .restricted] {
            let controller = SystemMusicController(status: { status })
            for command in MusicCommand.allCases {
                guard case .failed = controller.perform(command) else { return XCTFail("\(status) \(command)") }
            }
            XCTAssertFalse(controller.hasPlayer)
            XCTAssertNotEqual(controller.authorization, .authorized)
        }
    }

    func testPreviousNeverEndsPlayback() {
        // skipToPreviousItem at the first queue item ends playback (SDK contract).
        let expected: [(Int, [String])] = [
            (0, ["skipToBeginning"]), (NSNotFound, ["skipToBeginning"]),
            (3, ["skipToPreviousItem"]), (1, ["skipToPreviousItem"]),
        ]
        for (index, calls) in expected {
            let player = FakePlayer()
            player.index = index
            let controller = SystemMusicController(status: { .authorized }, makePlayer: { player })
            XCTAssertEqual(controller.perform(.previous), .performed)
            XCTAssertEqual(player.calls, calls, "index \(index)")
        }
    }

    func testEachMusicCommandReachesThePlayer() {
        let player = FakePlayer()
        player.index = 2
        let controller = SystemMusicController(status: { .authorized }, makePlayer: { player })
        for command in MusicCommand.allCases { _ = controller.perform(command) }
        XCTAssertEqual(player.calls, ["skipToNextItem", "skipToPreviousItem", "play", "skipToBeginning"])
        XCTAssertEqual(player.shuffleMode, .songs)
        XCTAssertEqual(player.repeatMode, .all)
        player.playbackState = .playing
        _ = controller.perform(.playPause)
        XCTAssertEqual(player.calls.last, "pause")
    }

    func testPrepareOpensThePlayerOnlyWhenAuthorized() {
        var created = 0
        let player = FakePlayer()
        for status in [MPMediaLibraryAuthorizationStatus.notDetermined, .denied, .restricted] {
            let controller = SystemMusicController(status: { status }, makePlayer: { created += 1; return player })
            controller.prepare()
            XCTAssertFalse(controller.hasPlayer)
        }
        XCTAssertEqual(created, 0)
        let controller = SystemMusicController(status: { .authorized }, makePlayer: { created += 1; return player })
        controller.prepare()
        controller.prepare()
        _ = controller.perform(.next)
        XCTAssertTrue(controller.hasPlayer)
        XCTAssertEqual(created, 1, "one player for the controller's lifetime")
        XCTAssertEqual(player.indexReads, 2, "prepare makes a server round trip")
    }

    func testSlowMusicCallsAreReported() {
        var now = 0.0
        let player = FakePlayer()
        player.onCall = { now += $0 == "skipToNextItem" ? 0.4 : 0.01 }
        let controller = SystemMusicController(status: { .authorized }, makePlayer: { player }, now: { now })
        var slow: [(String, Double)] = []
        controller.onSlowCall = { slow.append(($0, $1)) }
        _ = controller.perform(.restart)
        _ = controller.perform(.next)
        XCTAssertEqual(slow.map(\.0), ["next"])
        XCTAssertEqual(slow.first?.1 ?? 0, 0.4, accuracy: 1e-9)
        XCTAssertEqual(SystemMusicController.slowCallThreshold, 0.1)
    }

    func testShuffleAndRepeatCycles() {
        XCTAssertEqual(SystemMusicController.toggled(.off), .songs)
        XCTAssertEqual(SystemMusicController.toggled(.default), .songs)
        XCTAssertEqual(SystemMusicController.toggled(.songs), .off)
        XCTAssertEqual(SystemMusicController.toggled(.albums), .off)
        XCTAssertEqual(SystemMusicController.cycled(.none), .all)
        XCTAssertEqual(SystemMusicController.cycled(.default), .all)
        XCTAssertEqual(SystemMusicController.cycled(.all), .one)
        XCTAssertEqual(SystemMusicController.cycled(.one), .none)
    }

    func testPermissionStateMapping() {
        XCTAssertEqual(PermissionState(MPMediaLibraryAuthorizationStatus.authorized), .authorized)
        XCTAssertEqual(PermissionState(MPMediaLibraryAuthorizationStatus.notDetermined), .notDetermined)
        XCTAssertEqual(PermissionState(MPMediaLibraryAuthorizationStatus.denied), .denied)
        XCTAssertEqual(PermissionState(MPMediaLibraryAuthorizationStatus.restricted), .restricted)
        XCTAssertEqual(PermissionState(UNAuthorizationStatus.authorized), .authorized)
        XCTAssertEqual(PermissionState(UNAuthorizationStatus.provisional), .authorized)
        XCTAssertEqual(PermissionState(UNAuthorizationStatus.denied), .denied)
        XCTAssertEqual(PermissionState(UNAuthorizationStatus.notDetermined), .notDetermined)
    }

    func testNotificationPosterRefusesUntilAuthorizationIsKnown() {
        let poster = LocalNotificationPoster()
        XCTAssertEqual(poster.authorization, .notDetermined)
        guard case .failed = poster.post(title: "R02", body: "test") else { return XCTFail() }
    }
}

@MainActor
private final class FakePlayer: MusicPlayerControlling {
    var playbackState: MPMusicPlaybackState = .paused
    var index = 0
    var indexReads = 0
    var indexOfNowPlayingItem: Int { indexReads += 1; return index }
    var shuffleMode: MPMusicShuffleMode = .off
    var repeatMode: MPMusicRepeatMode = .none
    var calls: [String] = []
    var onCall: ((String) -> Void)?

    private func record(_ name: String) { calls.append(name); onCall?(name) }
    func play() { record("play") }
    func pause() { record("pause") }
    func skipToNextItem() { record("skipToNextItem") }
    func skipToPreviousItem() { record("skipToPreviousItem") }
    func skipToBeginning() { record("skipToBeginning") }
}
