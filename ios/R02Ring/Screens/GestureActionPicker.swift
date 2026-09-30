import SwiftUI

extension ActionBadge.Kind {
    /// Nil for an action that runs only while R02 is in front; none ships today.
    init?(action: GestureActionID) {
        if action == .none { self = .unassigned }
        else if action.isLocked { self = .locked }
        else if action.info.worksInBackground { self = .background }
        else { return nil }
    }
}

extension GestureActionID {
    /// "Next track, works in background": the title plus what its badge says.
    var spokenSummary: String {
        guard let kind = ActionBadge.Kind(action: self), self != .none else { return title }
        return "\(title), \(kind.accessibilityText)"
    }
}

/// Chooses the action for one gesture: actions grouped by category, locked
/// ones dimmed with the reason. Plain values in and closures out, so it renders
/// without the model. The owner requests any permission the choice needs.
struct GestureActionPickerSheet: View {
    var gesture: GestureID
    var current: GestureActionID
    var permissions: [GesturePermission: PermissionState] = [:]
    /// Granted only after the complete installed-image fingerprint is checked.
    /// Keyboard actions stay visible but cannot be mapped below V9. V10 is
    /// the current guarded install target; an installed V9 remains recognized.
    var availableHIDVersion = 0
    var scrolls = true
    var choose: (GestureActionID) -> Void
    var restoreDefault: () -> Void
    @Environment(\.dismiss) private var dismiss

    private var defaultAction: GestureActionID { GestureMappings.defaultAction(for: gesture) }

    var body: some View {
        SheetScaffold(title: gesture.title, subtitle: "Now: \(current.title)", scrolls: scrolls) {
            ForEach(GestureActionCategory.allCases) { category in
                section(category)
            }
            restoreFooter
        }
    }

    private func section(_ category: GestureActionCategory) -> some View {
        let actions = GestureActionID.allCases.filter { $0.info.category == category }
        // Permissions follow the category: every Apple Music action needs Apple Music access.
        let note = permissionNote(actions.lazy.compactMap(\.info.permission).first)
        return VStack(alignment: .leading, spacing: 0) {
            Text(category.title)
                .labelType(10)
                .foregroundStyle(Tok.muted)
                .padding(.bottom, 6)
                .accessibilityAddTraits(.isHeader)
            if let note {
                Text(note)
                    .font(.mono(10))
                    .foregroundStyle(Tok.accent)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.bottom, 8)
            }
            Hairline()
            if category == .needsRingHID {
                Text("V8 controls")
                    .font(.mono(10)).foregroundStyle(Tok.dim)
                    .padding(.top, 10)
                ForEach(actions.filter { $0.minimumHIDVersion == 8 }) { action in
                    row(action, note: note)
                    Hairline()
                }
                Text("V10 keyboard, Switch Control and wheel")
                    .font(.mono(10)).foregroundStyle(Tok.dim)
                    .padding(.top, 14)
                ForEach(actions.filter { $0.minimumHIDVersion == 9 }) { action in
                    row(action, note: note)
                    Hairline()
                }
            } else {
                ForEach(actions) { action in
                    row(action, note: note)
                    Hairline()
                }
            }
            if let footnote = category.footnote {
                footnoteText(footnote)
                    .font(.mono(10))
                    .foregroundStyle(Tok.dim)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, 8)
            }
        }
        .padding(.bottom, 22)
    }

    /// Catalog footnotes carry Markdown code spans for command names.
    private func footnoteText(_ footnote: String) -> Text {
        guard let styled = try? AttributedString(markdown: footnote) else { return Text(footnote) }
        return Text(styled)
    }

    private func row(_ action: GestureActionID, note: String?) -> some View {
        let info = action.info
        let selected = action == current
        let versionReason = action.minimumHIDVersion.flatMap { $0 > availableHIDVersion
            ? ($0 == 9
                ? "Requires exact, verified V10 keyboard firmware (installed V9 is also recognized)."
                : "Requires exact, verified V\($0) Ring controls firmware.")
            : nil
        }
        let reason = info.lockedReason ?? versionReason
        let locked = reason != nil
        return Button {
            choose(action)
            dismiss()
        } label: {
            HStack(alignment: .top, spacing: 12) {
                Circle()
                    .fill(selected ? Tok.accent : Color.clear)
                    .overlay { Circle().strokeBorder(selected ? Tok.accent : Tok.dim, lineWidth: Tok.hairlineWidth) }
                    .frame(width: 7, height: 7)
                    .padding(.top, 4)
                VStack(alignment: .leading, spacing: 4) {
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text(info.title)
                            .font(.mono(12))
                            .foregroundStyle(selected ? Tok.accent : locked ? Tok.muted : Tok.text)
                        if action == defaultAction {
                            Text("default").font(.mono(9)).foregroundStyle(Tok.dim)
                        }
                        Spacer(minLength: 8)
                        if let kind = locked ? ActionBadge.Kind.locked : ActionBadge.Kind(action: action) {
                            ActionBadge(kind: kind)
                        }
                    }
                    Text(reason ?? info.detail)
                        .font(.mono(10))
                        .foregroundStyle(locked ? Tok.dim : Tok.muted)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(.vertical, 12)
            .frame(minHeight: Tok.tapTarget)
            .contentShape(Rectangle())
        }
        .buttonStyle(RowPressStyle())
        .disabled(locked)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(locked ? "\(action.title), locked" : action.spokenSummary)
        .accessibilityHint([reason ?? info.detail, info.permission == nil ? nil : note]
            .compactMap { $0 }.joined(separator: " "))
        .accessibilityAddTraits(selected ? [.isButton, .isSelected] : .isButton)
    }

    /// What choosing from a section means for its permission, while it isn't granted.
    private func permissionNote(_ permission: GesturePermission?) -> String? {
        guard let permission else { return nil }
        switch permissions[permission] ?? .notDetermined {
        case .authorized: return nil
        case .notDetermined: return "R02 asks for \(permission.title) access when you choose one of these."
        case .denied: return "\(permission.title) access is off. Allow it for R02 in Settings."
        case .restricted: return "\(permission.title) access is restricted on this iPhone."
        }
    }

    @ViewBuilder
    private var restoreFooter: some View {
        if current == defaultAction {
            Text("Using the default: \(defaultAction.title)")
                .font(.mono(10))
                .foregroundStyle(Tok.dim)
        } else {
            OutlineButton(title: "Restore default") {
                restoreDefault()
                dismiss()
            }
            .accessibilityHint("Sets \(gesture.title) back to \(defaultAction.title)")
            Text("Default: \(defaultAction.title)")
                .font(.mono(10))
                .foregroundStyle(Tok.dim)
                .frame(maxWidth: .infinity)
                .padding(.top, 8)
        }
    }
}
