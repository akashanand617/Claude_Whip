import SwiftUI

/// How to toggle gestures with Back Tap from any app. The action name must
/// match `ToggleGestureSessionIntent.title` under the app's bundle name.
struct BackTapGuideSheet: View {
    static let appName = "R02Ring"
    static let actionTitle = "Toggle Gesture Session"
    static let shortcutName = "R02 Gestures"

    var scrolls = true
    @Environment(\.openURL) private var openURL

    var body: some View {
        SheetScaffold(title: "Back Tap", subtitle: "Toggle gestures from any app", scrolls: scrolls) {
            label("In Shortcuts")
            step(1, Text("Open Shortcuts and tap ") + name("+") + Text(" to create a shortcut."))
            step(2, Text("Tap Add Action, search for ") + name(Self.appName) + Text(" and add ")
                 + name("\(Self.appName) › \(Self.actionTitle)") + Text("."))
            step(3, Text("Name the shortcut ") + name(Self.shortcutName) + Text(" and tap Done."))
            Hairline()

            label("In Settings").padding(.top, 22)
            step(4, Text("Open ") + name("Settings › Accessibility › Touch › Back Tap") + Text("."))
            step(5, Text("Choose Double Tap or Triple Tap, then pick ") + name(Self.shortcutName)
                 + Text(" under Shortcuts."))
            Hairline()

            label("Good to know").padding(.top, 22)
            note("After a session starts, hold your fingers pointing down and still for 3 seconds to calibrate. Gestures act only after that.")
            note("Snap pauses gestures by default: the ring returns to Health. Back Tap again to resume.")
            note("The Action Button can run the same shortcut: Settings › Action Button › Shortcut.")
            note("If the ring isn't ready, Shortcuts asks to continue in R02, which then tries for up to 30 seconds to start the session. If the ring still isn't connected, tap Start once it is.")
            note("Start Gesture Session and Pause Gestures (Return to Health) are also available as separate actions.")

            OutlineButton(title: "Open Shortcuts") {
                if let url = URL(string: "shortcuts://") { openURL(url) }
            }
            .accessibilityHint("Opens the Shortcuts app")
            .padding(.top, 26)
        }
    }

    private func label(_ title: String) -> some View {
        Text(title)
            .labelType(10)
            .foregroundStyle(Tok.muted)
            .padding(.bottom, 6)
            .accessibilityAddTraits(.isHeader)
    }

    private func name(_ text: String) -> Text {
        Text(text).foregroundStyle(Tok.accent)
    }

    private func step(_ number: Int, _ text: Text) -> some View {
        VStack(spacing: 0) {
            Hairline()
            HStack(alignment: .firstTextBaseline, spacing: 14) {
                Text(String(format: "%02d", number))
                    .font(.mono(11))
                    .foregroundStyle(Tok.dim)
                    .accessibilityHidden(true)
                text
                    .font(.mono(12))
                    .foregroundStyle(Tok.text)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(.vertical, 12)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(Text("Step \(number). ") + text)
    }

    private func note(_ text: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Rectangle().fill(Tok.accentDeep).frame(width: 4, height: 4)
                .padding(.bottom, 1)
                .accessibilityHidden(true)
            Text(text)
                .font(.mono(11))
                .foregroundStyle(Tok.muted)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.vertical, 5)
    }
}

/// V8 swipes are relative mouse drags. V10 keeps V9's wheel/keyboard wire
/// reports while making Keyboard the primary HID application for iOS. F5/F6
/// can also be captured as external Switch Control inputs for real touch swipes.
struct RingControlsGuideSheet: View {
    var scrolls = true
    @State private var wheelSettings = RingHIDWheelSettingsStore().load()

    var body: some View {
        SheetScaffold(title: "Ring controls", subtitle: "Keyboard and mouse from the ring", scrolls: scrolls) {
            label("In R02")
            step(1, Text("Install exact verified V10 Keyboard-primary HID firmware from Settings › Firmware maintenance."))
            step(2, Text("After the ring reboots, forget the ring in iPhone Bluetooth settings, then reconnect it so iOS replaces the cached V9 report map."))
            step(3, Text("Start and calibrate a Gesture session, then map gestures to keyboard, wheel, media or navigation controls."))
            Hairline()

            label("Instagram without AssistiveTouch").padding(.top, 22)
            step(4, Text("In R02, map two gestures to ") + name("Switch swipe up (F5)")
                 + Text(" and ") + name("Switch swipe down (F6)") + Text("."))
            step(5, Text("Open ") + name("Settings › Accessibility › Switch Control › Switches")
                 + Text(", add two External switches, and perform the matching ring gesture when iPhone asks for each input."))
            step(6, Text("Open ") + name("Switch Control › Recipes")
                 + Text(", create an Instagram recipe, and assign the F5 switch a custom upward swipe and F6 a custom downward swipe."))
            step(7, Text("Launch that recipe and turn on Switch Control. Add Switch Control to Accessibility Shortcut so a triple-click of the side button turns it off again."))
            note("This performs a real system touch gesture, so Instagram does not need to support Arrow or Page keys.")
            note("Switch Control has no floating AssistiveTouch button, but it can show a scanning highlight and changes normal touch behavior while enabled.")
            note("The ring's F5/F6 external-switch capture is ready in the app but still needs one physical setup test on this iPhone.")
            Hairline()

            label("Other no-button controls").padding(.top, 22)
            note("Arrow, Page Up/Down, Space, Return and other keyboard actions do not use AssistiveTouch.")
            note("Media, volume, camera shutter and navigation controls also do not use AssistiveTouch.")
            note("Arrow and Page keys work only when the app on screen implements them. Instagram's iPhone feed does not expose them as Reel swipes.")
            note("Mouse drags and wheel reports remain available for apps where iPhone pointer support delivers them.")
            Hairline()

            label("V10 mouse-wheel amount").padding(.top, 22)
            Stepper(value: $wheelSettings.amount, in: RingHIDWheelSettings.range) {
                Text("Amount · \(wheelSettings.amount) of 5")
                    .font(.mono(12))
                    .foregroundStyle(Tok.text)
            }
            .tint(Tok.accent)
            .onChange(of: wheelSettings) { _, value in RingHIDWheelSettingsStore().save(value) }
            note("1 sends the smallest wheel step; 5 sends the largest. This setting applies to V9/V10 mouse-wheel actions.")
            Hairline()

            label("Good to know").padding(.top, 22)
            note("Swipes are short mouse drags. Some apps may ignore them or treat an edge drag as navigation.")
            note("Keyboard and Consumer controls work only in apps that handle the selected standard key.")
            note("V10 is physically recognized as a hardware keyboard on this iPhone. The new Switch Control recipe route still needs validation.")
        }
    }

    private func label(_ title: String) -> some View {
        Text(title)
            .labelType(10)
            .foregroundStyle(Tok.muted)
            .padding(.bottom, 6)
            .accessibilityAddTraits(.isHeader)
    }

    private func name(_ text: String) -> Text {
        Text(text).foregroundStyle(Tok.accent)
    }

    private func step(_ number: Int, _ text: Text) -> some View {
        VStack(spacing: 0) {
            Hairline()
            HStack(alignment: .firstTextBaseline, spacing: 14) {
                Text(String(format: "%02d", number))
                    .font(.mono(11))
                    .foregroundStyle(Tok.dim)
                    .accessibilityHidden(true)
                text
                    .font(.mono(12))
                    .foregroundStyle(Tok.text)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(.vertical, 12)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(Text("Step \(number). ") + text)
    }

    private func note(_ text: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Rectangle().fill(Tok.accentDeep).frame(width: 4, height: 4)
                .padding(.bottom, 1)
                .accessibilityHidden(true)
            Text(text)
                .font(.mono(11))
                .foregroundStyle(Tok.muted)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.vertical, 5)
    }
}

/// The cross-ring waveform capture, moved off the Gestures screen. Recording
/// needs a calibrated Gesture session; the prompts are timed, so the sheet
/// stays up until the capture ends or is cancelled.
struct GestureDiagnosticsSheet: View {
    var ready: Bool
    var recording: Bool
    var prompt: String
    var progress: String
    var captureName: String?
    var scrolls = true
    var start: () -> Void
    var cancel: () -> Void

    var body: some View {
        SheetScaffold(title: "Waveform capture", subtitle: "Cross-ring diagnostic set",
                      showsDone: !recording, scrolls: scrolls) {
            Text("After a 2-second quiet pre-roll, R02 prompts each gesture three times, then records a 30-second tail of natural movement. The session returns to Health when it finishes. Gesture actions are skipped while it records.")
                .font(.mono(11))
                .foregroundStyle(Tok.muted)
                .fixedSize(horizontal: false, vertical: true)

            VStack(alignment: .leading, spacing: 8) {
                if recording {
                    Text(prompt.isEmpty ? "Get ready" : prompt)
                        .font(.mono(28, .medium))
                        .foregroundStyle(Tok.accent)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityAddTraits(.updatesFrequently)
                }
                if !progress.isEmpty {
                    Text(progress).font(.mono(11)).foregroundStyle(recording ? Tok.text : Tok.muted)
                }
                if !recording, !ready {
                    Text("Start a Gesture session and finish the fingers-down calibration first.")
                        .font(.mono(11)).foregroundStyle(Tok.muted)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .frame(maxWidth: .infinity, minHeight: 96, alignment: .topLeading)
            .padding(.vertical, 18)

            if recording {
                OutlineButton(title: "Cancel capture", action: cancel)
                    .accessibilityHint("Stops recording and keeps a partial capture")
            } else {
                OutlineButton(title: "Record waveform set", action: start)
                    .disabled(!ready)
                    .accessibilityHint(ready ? "Starts the prompted recording"
                                             : "Needs a calibrated Gesture session")
            }

            if let captureName {
                Text(verbatim: "Last capture \(captureName) · saved in Documents/GestureDiagnostics")
                    .font(.mono(10))
                    .foregroundStyle(Tok.dim)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, 14)
            }
        }
        .interactiveDismissDisabled(recording)
    }
}
