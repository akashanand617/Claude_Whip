import XCTest
@testable import R02Ring

/// The sticky-session contract, pure: which events may end a user's Gesture
/// session (an exhaustive table), the desired state's transitions, what a
/// failed renewal means, and the heal's timing rules.
@MainActor
final class GestureStickySessionPolicyTests: XCTestCase {
    // MARK: Which reasons may end a session

    /// The spec's allowed list, plus the two explicit user actions kept from
    /// before (Keep-in-background Off and Forget ring).
    private let endingTriggers: [GestureSessionTrigger: GestureEndReason] = [
        .appReturn: .user, .intentStop: .intent, .pauseGesture: .gestureAction,
        .sessionTimer: .autoReturn, .idleTimer: .idle,
        .backgroundedWithSettingOff: .backgrounded, .ringForgotten: .ringForgotten,
        .chargingRefusal: .charging, .ringGoneTimeout: .ringGone, .healExhausted: .healGaveUp,
    ]

    func testOnlyTheAllowedTriggersEndASession() {
        var ends: [GestureSessionTrigger: GestureEndReason] = [:]
        for trigger in GestureSessionTrigger.allCases {
            if case .end(let reason) = GestureSessionPolicy.disposition(trigger) { ends[trigger] = reason }
        }
        XCTAssertEqual(ends, endingTriggers)
        XCTAssertEqual(Set(ends.values), Set(GestureEndReason.allCases), "every end reason is reachable, nothing else")
    }

    func testStaleDataRenewalsLeaseReconnectsAndLostControlNeverEndASession() {
        let heals: [GestureSessionTrigger: GestureHealCause] = [
            .streamFault: .staleStream, .sourceStopped: .sourceStopped, .renewalBadSource: .badSource,
            .leaseLapsed: .leaseLapsed, .replyMismatch: .controlLost,
            .controlLost: .controlLost, .linkLost: .disconnected, .unexpectedHealth: .unexpectedHealth,
            .modelUnavailable: .modelUnavailable,
        ]
        for (trigger, cause) in heals {
            XCTAssertEqual(GestureSessionPolicy.disposition(trigger), .heal(cause), trigger.rawValue)
        }
        for trigger in [GestureSessionTrigger.renewalTiming, .renewalWriteFailed, .renewalPreWriteRefusal] {
            XCTAssertEqual(GestureSessionPolicy.disposition(trigger), .missedRenewal, trigger.rawValue)
        }
        for trigger in [GestureSessionTrigger.diagnosticsFinished, .reconnectAttach] {
            XCTAssertEqual(GestureSessionPolicy.disposition(trigger), GestureSessionDisposition.none, trigger.rawValue)
        }
        // The table is exhaustive: every trigger is one of the four.
        XCTAssertEqual(endingTriggers.count + heals.count + 3 + 2, GestureSessionTrigger.allCases.count)
    }

    func testEndReasonsMapToJournalReasonsAndOnlyGiveUpsAlwaysNotify() {
        XCTAssertEqual(Set(GestureEndReason.allCases.map(\.sessionReason.rawValue)).count, GestureEndReason.allCases.count)
        XCTAssertEqual(Set(GestureEndReason.allCases.filter(\.isAutomatic)),
                       [.autoReturn, .idle, .charging, .ringGone, .healGaveUp])
        XCTAssertEqual(Set(GestureEndReason.allCases.filter(\.alwaysNotifies)), [.charging, .ringGone, .healGaveUp])
        XCTAssertEqual(GestureEndReason.ringGone.sessionReason.endTitle, "ring out of range")
        XCTAssertEqual(GestureEndReason.healGaveUp.sessionReason.endTitle, "couldn't reconnect")
        XCTAssertEqual(GestureEndReason.charging.sessionReason.endTitle, "ring on charger")
        XCTAssertEqual(GestureRequestSource.app.endReason, .user)
        XCTAssertEqual(GestureRequestSource.intent.endReason, .intent)
    }

    // MARK: The desired state

    func testArmReachEnd() {
        var desire = GestureDesire()
        XCTAssertTrue(desire.isOff)
        let epoch = desire.arm()
        XCTAssertEqual(desire.state, .arming(epoch: epoch))
        XCTAssertFalse(desire.isOn, "a start that has not reached Gesture is not a session")
        XCTAssertTrue(desire.reached(epoch: epoch, at: 100))
        XCTAssertEqual(desire.state, .on(epoch: epoch))
        XCTAssertEqual(desire.onSince, 100)
        XCTAssertFalse(desire.reached(epoch: epoch, at: 101), "reached once")
        desire.startFinished(epoch: epoch) // the start's own return: ignored while on
        XCTAssertTrue(desire.isOn)
        XCTAssertTrue(desire.end(.intent))
        XCTAssertTrue(desire.isOff)
        XCTAssertNil(desire.onSince)
        XCTAssertEqual(desire.lastEnd, .intent)
        XCTAssertFalse(desire.end(.user), "ending twice notifies once")
        XCTAssertEqual(desire.lastEnd, .intent)
    }

    func testAFailedStartReturnsToOffWithoutEndingASession() {
        var desire = GestureDesire()
        let epoch = desire.arm()
        desire.startFinished(epoch: epoch)
        XCTAssertTrue(desire.isOff)
        XCTAssertNil(desire.lastEnd, "nothing started, so nothing ended")
    }

    func testAStopDuringEntryWinsOverTheEntry() {
        var desire = GestureDesire()
        let epoch = desire.arm()
        XCTAssertFalse(desire.end(.user), "withdrawing an arming start is not a session end")
        XCTAssertFalse(desire.reached(epoch: epoch, at: 5), "the entry that settles later cannot turn it on")
        XCTAssertTrue(desire.isOff)
    }

    func testTwoStartsShareAnEpochAndOnlyTheLastFailureDisarms() {
        var desire = GestureDesire()
        let first = desire.arm()
        let second = desire.arm()
        XCTAssertEqual(first, second)
        XCTAssertEqual(desire.pendingStarts, 2)
        desire.startFinished(epoch: first) // e.g. timed out
        XCTAssertTrue(desire.isArming, "the other start is still entering")
        XCTAssertTrue(desire.reached(epoch: second, at: 1))
        desire.startFinished(epoch: second)
        XCTAssertTrue(desire.isOn)
    }

    func testANewArmAdvancesTheEpochAndAStartWhileOnJoinsIt() {
        var desire = GestureDesire()
        let first = desire.arm()
        desire.reached(epoch: first, at: 0)
        XCTAssertEqual(desire.arm(), first, "a start while on answers for the running session")
        XCTAssertEqual(desire.pendingStarts, 0)
        desire.end(.idle)
        let second = desire.arm()
        XCTAssertNotEqual(first, second)
        desire.startFinished(epoch: first) // a stale start: ignored
        XCTAssertTrue(desire.isArming)
    }

    func testEveryEndReasonClearsTheDesiredState() {
        for reason in GestureEndReason.allCases {
            var desire = GestureDesire()
            desire.reached(epoch: desire.arm(), at: 0)
            XCTAssertTrue(desire.end(reason), reason.rawValue)
            XCTAssertTrue(desire.isOff, reason.rawValue)
        }
    }

    // MARK: Readiness and the snapshot

    private let health = GestureModeSnapshot(
        link: .ready, connectionSetupComplete: true, unifiedFirmwareInstalled: true,
        modeAttachInFlight: false, modeControlAvailable: true, mode: .health, charging: false,
        transition: nil, ringBusy: false, firmwareSwitching: false, appActive: false,
        keepGesturesInBackground: true
    )

    func testADesiredSessionIsActiveWhileItHealsAndAStartJoinsIt() {
        var healing = health
        healing.gestureDesired = true
        healing.healing = true
        healing.mode = nil
        healing.modeControlAvailable = false
        XCTAssertTrue(healing.gestureActive)
        XCTAssertEqual(GestureStartReadiness.evaluate(healing), .alreadyActive, "no second entry")
        XCTAssertEqual(GestureStartReadiness.evaluate(healing, ignoringDesire: true), .unavailable,
                       "the keeper judges the ring itself")
        healing.mode = .gesture
        healing.modeControlAvailable = true
        XCTAssertEqual(GestureStartReadiness.evaluate(healing, ignoringDesire: true), .alreadyActive,
                       "still in Gesture: the heal restarts it")
    }

    // MARK: Orphan Gesture and the start's own arming

    func testAStartsOwnArmingNeverHidesAnOrphan() {
        // A pause's stop failed; the ring still streams; a Toggle start arms.
        XCTAssertTrue(GestureOwnership.orphan(desireOn: false, desireArming: true, ringInGesture: true,
                                              transition: nil, enteringReason: nil))
        // Its readiness therefore waits for the return instead of answering alreadyActive.
        var snapshot = health
        snapshot.mode = .gesture
        snapshot.orphanGesture = GestureOwnership.orphan(desireOn: false, desireArming: true, ringInGesture: true,
                                                         transition: nil, enteringReason: nil)
        XCTAssertEqual(GestureStartReadiness.evaluate(snapshot), .returning)
        // A stop held for a heal's entry: still an orphan while the start arms.
        XCTAssertTrue(GestureOwnership.orphan(desireOn: false, desireArming: true, ringInGesture: false,
                                              transition: .entering, enteringReason: .heal))
        // The arming start's own entry from Health is not an orphan: a second start joins it.
        for reason in [GestureSessionReason.user, .intent] {
            XCTAssertFalse(GestureOwnership.orphan(desireOn: false, desireArming: true, ringInGesture: false,
                                                   transition: .entering, enteringReason: reason))
        }
        // With the desire off, even a user entry is an orphan (a stop won it).
        XCTAssertTrue(GestureOwnership.orphan(desireOn: false, desireArming: false, ringInGesture: false,
                                              transition: .entering, enteringReason: .user))
        XCTAssertFalse(GestureOwnership.orphan(desireOn: true, desireArming: false, ringInGesture: true,
                                               transition: nil, enteringReason: nil))
        XCTAssertFalse(GestureOwnership.orphan(desireOn: false, desireArming: false, ringInGesture: false,
                                               transition: nil, enteringReason: nil))
    }

    func testADeferredReturnToHealthNeverStopsANewerStartsEntry() {
        XCTAssertTrue(GestureOwnership.returnToHealthApplies(desireOn: false, desireArming: false,
                                                             transition: nil, enteringReason: nil))
        XCTAssertTrue(GestureOwnership.returnToHealthApplies(desireOn: false, desireArming: true,
                                                             transition: nil, enteringReason: nil),
                      "a start waiting .returning needs this stop")
        XCTAssertFalse(GestureOwnership.returnToHealthApplies(desireOn: false, desireArming: true,
                                                              transition: .entering, enteringReason: .intent),
                       "the ring was in Health for that entry: a stop now would follow its A1 04")
        XCTAssertFalse(GestureOwnership.returnToHealthApplies(desireOn: true, desireArming: false,
                                                              transition: nil, enteringReason: nil))
    }

    func testANoLeaseGiveUpSaysSoAndNeverClaimsAMinuteOfRetries() {
        let noLease = GestureGiveUpNotice.body(.healGaveUp, cause: .staleStream, detail: "stale_stream:no_lease",
                                               time: "9:41")
        XCTAssertFalse(noLease.contains("for a minute"))
        XCTAssertTrue(noLease.contains("can't reconnect gestures automatically"))
        XCTAssertEqual(GestureGiveUpNotice.body(.healGaveUp, cause: nil, detail: "no_lease", time: "9:41"),
                       "At 9:41 gestures stopped: this ring's firmware can't reconnect gestures automatically. The ring is back in Health.")
        XCTAssertTrue(GestureGiveUpNotice.body(.healGaveUp, cause: .sourceStopped, detail: "stale_stream",
                                               time: "9:41").contains("couldn't reconnect for a minute"))
        XCTAssertTrue(GestureGiveUpNotice.body(.ringGone, cause: .disconnected, time: "9:41").contains("out of range"))
    }

    func testTheTerminationMarkerIsReportedExactlyOnce() throws {
        let defaults = try XCTUnwrap(UserDefaults(suiteName: "GestureSessionMarkerTests"))
        defaults.removePersistentDomain(forName: "GestureSessionMarkerTests")
        XCTAssertNil(GestureSessionMarker.take(from: defaults), "no session was on")
        let began = Date(timeIntervalSince1970: 1_000)
        var marker = GestureSessionMarker(epoch: 4, startedAt: began, lastAliveAt: began)
        marker.save(to: defaults)
        marker.lastAliveAt = began.addingTimeInterval(300)
        marker.save(to: defaults)
        XCTAssertEqual(GestureSessionMarker.load(from: defaults)?.lastAliveAt, began.addingTimeInterval(300))
        // Every end clears it.
        GestureSessionMarker.clear(in: defaults)
        XCTAssertNil(GestureSessionMarker.take(from: defaults))
        // A process that died with it set: the next launch takes it once.
        marker.save(to: defaults)
        XCTAssertEqual(GestureSessionMarker.take(from: defaults), marker)
        XCTAssertNil(GestureSessionMarker.take(from: defaults), "reported once")
        XCTAssertEqual(marker.noticeBody(lastAlive: "9:41"),
                       "iOS closed R02 while gestures were on (last active at 9:41). The ring returns to Health.")
        defaults.removePersistentDomain(forName: "GestureSessionMarkerTests")
    }

    func testGestureNoSessionWantsIsNotActiveAndAStartWaitsForItsReturn() {
        var orphan = health
        orphan.mode = .gesture
        orphan.orphanGesture = true
        XCTAssertFalse(orphan.gestureActive, "a Toggle starts rather than stopping an orphan")
        XCTAssertEqual(GestureStartReadiness.evaluate(orphan), .returning)
        XCTAssertTrue(GestureStartReadiness.evaluate(orphan).isWaiting)
    }

    func testSummaryCountsReconnects() {
        XCTAssertEqual(GestureSessionSummary.text(duration: 125, recognized: 3, performed: 2, reason: .ringGone,
                                                  reconnects: 2),
                       "Last session 2 min 5 s · 3 gestures, 2 actions · 2 reconnects · ring out of range")
        XCTAssertEqual(GestureSessionSummary.text(duration: 5, recognized: 0, performed: 0, reason: .intent,
                                                  reconnects: 1),
                       "Last session 5 s · 0 gestures, 0 actions · 1 reconnect · stopped by Shortcut")
    }

    // MARK: A failed renewal

    private func report(_ cause: A1UnifiedModeTransport.RenewalReport.Cause, checks: [String] = [])
        -> A1UnifiedModeTransport.RenewalReport {
        .init(passed: false, cause: cause, failedChecks: checks, metrics: nil, baselineSpacingsMS: [],
              renewalSpacingsMS: [], writeUptime: 0, writeAfterBaselineMS: 0, postBeforeWrite: 0)
    }

    private func verdict(_ error: Error, reached: Bool = false, heartbeat: String? = nil, transport: String? = nil,
                         report: A1UnifiedModeTransport.RenewalReport? = nil,
                         leaseAge: Double? = 2, linkReady: Bool = true) -> RenewalVerdict {
        RenewalVerdict.classify(error, failure: HeartbeatFailure(reachedRenew: reached, heartbeatRejection: heartbeat,
                                                                  transportRejection: transport, report: report,
                                                                  error: nil),
                                linkReady: linkReady, leaseAge: leaseAge, leaseDeadline: 9)
    }

    /// Post-write timing misses (the A1 04 was written, so the lease was
    /// restarted) never heal however often they repeat; only the lease's age
    /// can turn one into a heal.
    private let timingMisses: [A1UnifiedModeTransport.RenewalReport] = [
        .init(passed: false, cause: .nonmonotonic, failedChecks: [], metrics: nil, baselineSpacingsMS: [],
              renewalSpacingsMS: [], writeUptime: 0, writeAfterBaselineMS: 0, postBeforeWrite: 0),
        .init(passed: false, cause: .timeout(samplesAfterWrite: 12), failedChecks: [], metrics: nil,
              baselineSpacingsMS: [], renewalSpacingsMS: [], writeUptime: 0, writeAfterBaselineMS: 0,
              postBeforeWrite: 0),
        .init(passed: false, cause: .criteria, failedChecks: ["max_gap"], metrics: nil, baselineSpacingsMS: [],
              renewalSpacingsMS: [], writeUptime: 0, writeAfterBaselineMS: 0, postBeforeWrite: 0),
        .init(passed: false, cause: .criteria, failedChecks: ["rate_high"], metrics: nil, baselineSpacingsMS: [],
              renewalSpacingsMS: [], writeUptime: 0, writeAfterBaselineMS: 0, postBeforeWrite: 0),
        .init(passed: false, cause: .criteria, failedChecks: ["rate_high", "max_gap"], metrics: nil,
              baselineSpacingsMS: [], renewalSpacingsMS: [], writeUptime: 0, writeAfterBaselineMS: 0,
              postBeforeWrite: 0),
    ]

    func testATimingGateFailureIsAlwaysAMissedRenewalWhileTheLeaseHolds() {
        let boundary = UnifiedModeError.renewalBoundary
        for miss in timingMisses {
            XCTAssertEqual(verdict(boundary, reached: true, report: miss), .missed(.renewalTiming, retryIn: 5),
                           "\(miss.cause.map { "\($0)" } ?? "nil") \(miss.failedChecks)")
            XCTAssertEqual(verdict(boundary, reached: true, report: miss, leaseAge: 4.2), .act(.leaseLapsed),
                           "the next heartbeat would come after the lease's renewal deadline")
        }
    }

    /// The spec: a renewal that fails the timing gate never calls the stop
    /// path. Twenty consecutive misses, each routed as the heartbeat loop
    /// routes its verdict, never reach the keeper, a restart or a give-up.
    func testRepeatedTimingMissesNeverRestartOrEndTheSession() async {
        var restarts = 0, giveUps = 0
        let keeper = GestureSessionKeeper(.init(
            now: { 0 }, sleep: { _ in await Task.yield() }, isDesired: { true }, linkReady: { true },
            readiness: { .alreadyActive }, leaseBackstop: { true },
            restart: { restarts += 1; return .started }
        ))
        keeper.onGiveUp = { _, _, _ in giveUps += 1 }
        var missed = 0
        for index in 0..<20 {
            let miss = timingMisses[index % timingMisses.count]
            switch verdict(UnifiedModeError.renewalBoundary, reached: true, report: miss) {
            case .missed(let trigger, _):
                XCTAssertEqual(GestureSessionPolicy.disposition(trigger), .missedRenewal)
                missed += 1
            case .act(let trigger):
                if case .heal(let cause) = GestureSessionPolicy.disposition(trigger) {
                    keeper.fault(cause, detail: nil)
                }
            }
        }
        for _ in 0..<50 { await Task.yield() }
        XCTAssertEqual(missed, 20)
        XCTAssertFalse(keeper.hasEpisode, "no heal_started")
        XCTAssertEqual(restarts, 0, "no stop, no re-entry")
        XCTAssertEqual(giveUps, 0)
    }

    func testABadOrStoppedSourceHealsWithAFreshStart() {
        let boundary = UnifiedModeError.renewalBoundary
        XCTAssertEqual(verdict(boundary, reached: true, report: report(.criteria, checks: ["duplicates"])),
                       .act(.renewalBadSource))
        XCTAssertEqual(verdict(boundary, reached: true, report: report(.criteria, checks: ["rate_low", "max_gap"])),
                       .act(.renewalBadSource))
        XCTAssertEqual(verdict(boundary, reached: true, report: report(.timeout(samplesAfterWrite: 0))),
                       .act(.sourceStopped))
        XCTAssertEqual(verdict(boundary, reached: true, report: report(.timeout(samplesAfterWrite: 9))),
                       .act(.renewalBadSource), "fewer than ten samples in 1.75 s is a half-rate source")
        let stale = UnifiedModeError.staleStream
        XCTAssertEqual(verdict(stale, heartbeat: "not_processed"), .act(.sourceStopped))
        XCTAssertEqual(verdict(stale, heartbeat: "processed_age=2.400"), .act(.sourceStopped))
    }

    func testARefusalThatWroteNothingRetriesWhileTheLeaseHolds() {
        let stale = UnifiedModeError.staleStream
        for rejection in ["history=4", "processed_seq", "motion_age=0.612"] {
            XCTAssertEqual(verdict(stale, reached: true, transport: rejection),
                           .missed(.renewalPreWriteRefusal, retryIn: 1), rejection)
            XCTAssertEqual(verdict(stale, reached: true, transport: rejection, leaseAge: 8.2),
                           .act(.leaseLapsed), "a retry would come too late for the lease")
        }
        XCTAssertEqual(verdict(stale, heartbeat: "same_sequence"), .missed(.renewalPreWriteRefusal, retryIn: 1))
        XCTAssertEqual(verdict(stale, reached: true, transport: "lease_age=9.100"), .act(.leaseLapsed))
        XCTAssertEqual(verdict(stale, reached: true, transport: "history=4", leaseAge: 7.9),
                       .missed(.renewalPreWriteRefusal, retryIn: 1))
        XCTAssertEqual(verdict(RingProtocolError.busy), .missed(.renewalPreWriteRefusal, retryIn: 1))
        XCTAssertEqual(verdict(CancellationError()), .missed(.renewalPreWriteRefusal, retryIn: 1))
        XCTAssertEqual(verdict(UnifiedModeError.renewalBoundary, reached: true, report: report(.writeError)),
                       .missed(.renewalWriteFailed, retryIn: 1))
    }

    func testIntegrityFailuresAndLinkLossHealThroughControlOrTheLink() {
        XCTAssertEqual(verdict(UnifiedModeError.staleStream, reached: true, heartbeat: "reply_mismatch"),
                       .act(.replyMismatch))
        XCTAssertEqual(verdict(UnifiedModeError.uncorrelated, reached: true), .act(.replyMismatch))
        XCTAssertEqual(verdict(UnifiedModeError.exhausted), .act(.replyMismatch))
        XCTAssertEqual(verdict(UnifiedModeError.staleStream, heartbeat: "not_gesture"), .act(.controlLost))
        XCTAssertEqual(verdict(RingProtocolError.notReady), .act(.linkLost))
        XCTAssertEqual(verdict(UnifiedModeError.renewalBoundary, reached: true, report: report(.disconnected)),
                       .act(.linkLost))
        XCTAssertEqual(verdict(UnifiedModeError.renewalBoundary, reached: true,
                               report: report(.criteria, checks: ["max_gap"]), linkReady: false), .act(.linkLost))
    }

    func testNoRenewalVerdictEverEndsASession() {
        let errors: [Error] = [UnifiedModeError.renewalBoundary, UnifiedModeError.staleStream,
                               UnifiedModeError.uncorrelated, UnifiedModeError.exhausted, RingProtocolError.busy,
                               RingProtocolError.notReady, RingProtocolError.timeout, CancellationError()]
        let causes: [A1UnifiedModeTransport.RenewalReport.Cause?] = [
            nil, .criteria, .timeout(samplesAfterWrite: 0), .timeout(samplesAfterWrite: 5),
            .timeout(samplesAfterWrite: 10), .nonmonotonic, .writeError, .disconnected,
        ]
        let checks = [[], ["duplicates"], ["rate_low"], ["rate_high"], ["max_gap"]]
        let rejections: [String?] = [nil, "not_gesture", "not_processed", "processed_age=3.000", "same_sequence",
                                     "reply_mismatch", "lease_age=9.500", "history=3", "motion_age=0.700"]
        var seen = 0
        for error in errors {
            for cause in causes {
                for check in checks {
                    for rejection in rejections {
                        for leaseAge in [nil, 2.0, 5.0, 8.5] as [Double?] {
                            for link in [true, false] {
                                let result = verdict(error, reached: cause != nil || rejection != nil,
                                                     heartbeat: rejection, transport: rejection,
                                                     report: cause.map { report($0, checks: check) },
                                                     leaseAge: leaseAge, linkReady: link)
                                let trigger: GestureSessionTrigger
                                switch result {
                                case .missed(let missed, _): trigger = missed
                                case .act(let acted): trigger = acted
                                }
                                if case .end = GestureSessionPolicy.disposition(trigger) {
                                    XCTFail("\(error) \(String(describing: cause)) \(check) \(String(describing: rejection)) ended")
                                }
                                seen += 1
                            }
                        }
                    }
                }
            }
        }
        XCTAssertGreaterThan(seen, 10_000)
    }

    // MARK: Heal timing

    func testBackoffDoublesToItsCap() {
        XCTAssertEqual((1...7).map { GestureHealPolicy.backoff(attempt: $0, background: false) }, [0.5, 1, 2, 4, 8, 8, 8])
        XCTAssertEqual((1...6).map { GestureHealPolicy.backoff(attempt: $0, background: true) }, [0.5, 1, 2, 4, 4, 4])
    }

    func testGiveUpWindows() {
        func giveUp(_ started: Double, _ down: Double?, _ usable: Double?, _ now: Double,
                    awaitingFailure: Bool = false) -> GestureEndReason? {
            GestureHealPolicy.giveUp(startedAt: started, linkDownSince: down, linkUsableSince: usable, now: now,
                                     awaitingFailure: awaitingFailure)
        }
        // A reopened episode none of whose own attempts has failed: only the
        // link being gone or the cap ends it.
        XCTAssertNil(giveUp(0, nil, nil, 179.9, awaitingFailure: true))
        XCTAssertEqual(giveUp(0, nil, nil, 180, awaitingFailure: true), .healGaveUp)
        XCTAssertEqual(giveUp(0, 0, nil, 60, awaitingFailure: true), .ringGone)
        XCTAssertEqual(GestureHealPolicy.giveUpDeadline(startedAt: 0, linkDownSince: nil, linkUsableSince: nil,
                                                        awaitingFailure: true), 180)
        // Link up, failing.
        XCTAssertNil(giveUp(0, nil, nil, 59.9))
        XCTAssertEqual(giveUp(0, nil, nil, 60), .healGaveUp)
        // Link down.
        XCTAssertNil(giveUp(0, 0, nil, 59))
        XCTAssertEqual(giveUp(0, 0, nil, 60), .ringGone)
        XCTAssertEqual(giveUp(0, 30, nil, 90), .ringGone)
        XCTAssertNil(giveUp(0, 30, nil, 89))
        // Back after 50 s down: 20 s to identify, attach and re-enter.
        XCTAssertNil(giveUp(0, nil, 50, 69.9))
        XCTAssertEqual(giveUp(0, nil, 50, 70), .healGaveUp)
        // The cap, however the link flapped.
        XCTAssertEqual(giveUp(0, nil, 170, 180), .healGaveUp)
        XCTAssertEqual(giveUp(0, 150, nil, 180), .ringGone)
        XCTAssertNil(giveUp(0, 150, nil, 179.9))
        // Anchored at the last good processing: a wake long after gives up at once.
        XCTAssertEqual(giveUp(-7_200, nil, nil, 0), .healGaveUp)
        XCTAssertEqual(giveUp(-7_200, 0, nil, 0), .ringGone)
        XCTAssertEqual(GestureHealPolicy.giveUpDeadline(startedAt: 0, linkDownSince: 10, linkUsableSince: nil), 70)
        XCTAssertEqual(GestureHealPolicy.giveUpDeadline(startedAt: 0, linkDownSince: nil, linkUsableSince: 50), 70)
        XCTAssertEqual(GestureHealPolicy.giveUpDeadline(startedAt: 0, linkDownSince: nil, linkUsableSince: nil), 60)
        XCTAssertEqual(GestureHealPolicy.giveUpDeadline(startedAt: 0, linkDownSince: 150, linkUsableSince: nil), 180)
    }

    func testTheCalibrationFrameIsKeptOnlyForAQuickHealOnAnUnbrokenLink() {
        for hadFrame in [false, true] {
            for linkDropped in [false, true] {
                for duration in [0.0, 59.9, 60, 60.1] {
                    let expected = hadFrame && !linkDropped && duration <= 60
                    XCTAssertEqual(GestureHealPolicy.keepsFrame(hadFrame: hadFrame, linkDropped: linkDropped,
                                                                faultAt: 100, resumedAt: 100 + duration),
                                   expected, "frame \(hadFrame) dropped \(linkDropped) \(duration)")
                }
            }
        }
    }
}
