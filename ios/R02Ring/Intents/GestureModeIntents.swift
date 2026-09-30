import AppIntents

// Titles are what the Shortcuts library lists under "R02Ring"; the Back Tap
// guide names "Toggle Gesture Session", so keep that title in step with it.
// ForegroundContinuableIntent is deprecated from iOS 26 in favour of
// `supportedModes`, which does not exist on the iOS 17 deployment target.

struct ToggleGestureSessionIntent: AppIntent, ForegroundContinuableIntent {
    static let title: LocalizedStringResource = "Toggle Gesture Session"
    static let description: IntentDescription? = IntentDescription(
        "Starts a Gesture session on the ring, or returns it to Health if one is running. Assign it to Back Tap to switch from any app."
    )

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        let reply = await GestureIntentLogic.toggle(AppRuntime.shared.model)
        let text = try dialog(for: reply)
        return .result(dialog: text)
    }
}

struct StartGestureSessionIntent: AppIntent, ForegroundContinuableIntent {
    static let title: LocalizedStringResource = "Start Gesture Session"
    static let description: IntentDescription? = IntentDescription(
        "Switches the ring from Health to a Gesture session so ring gestures run their mapped actions."
    )

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        let reply = await GestureIntentLogic.start(AppRuntime.shared.model)
        let text = try dialog(for: reply)
        return .result(dialog: text)
    }
}

/// Background only: returning to Health never needs R02 in front.
struct StopGestureSessionIntent: AppIntent {
    static let title: LocalizedStringResource = "Pause Gestures (Return to Health)"
    static let description: IntentDescription? = IntentDescription(
        "Ends the Gesture session and returns the ring to Health tracking."
    )

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        let reply = await GestureIntentLogic.stop(AppRuntime.shared.model)
        return .result(dialog: IntentDialog("\(reply.message)"))
    }
}

extension ForegroundContinuableIntent {
    /// Throws the continue-in-R02 request when the reply asks for it; R02 then
    /// opens on Gestures and tries for up to 30 seconds to start.
    @MainActor
    fileprivate func dialog(for reply: GestureIntentReply) throws -> IntentDialog {
        guard reply.needsForeground else { return IntentDialog("\(reply.message)") }
        // Still in the background: keep automatic syncs off the ring until the
        // continuation runs, since scene activation may come first.
        AppRuntime.shared.model.expectForegroundStart()
        throw needsToContinueInForegroundError(IntentDialog("\(reply.message)"), continuation: {
            AppRuntime.shared.model.openGesturesAfterIntent(startWhenReady: true)
        })
    }
}

struct R02Shortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: ToggleGestureSessionIntent(),
            phrases: ["Toggle gestures in \(.applicationName)", "Toggle \(.applicationName) gestures"],
            shortTitle: "Toggle Gestures",
            systemImageName: "hand.wave"
        )
        AppShortcut(
            intent: StartGestureSessionIntent(),
            phrases: ["Start gestures in \(.applicationName)", "Start \(.applicationName) gestures"],
            shortTitle: "Start Gestures",
            systemImageName: "hand.raised"
        )
        AppShortcut(
            intent: StopGestureSessionIntent(),
            phrases: ["Pause gestures in \(.applicationName)", "Pause \(.applicationName) gestures",
                      "Return \(.applicationName) to Health"],
            shortTitle: "Pause Gestures",
            systemImageName: "heart"
        )
    }
}
