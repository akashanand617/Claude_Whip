import SwiftUI

/// Today (5a): the sleep hero, then full-width Heart rate and Steps bands that split
/// whatever height is left. Each of the three opens its detail screen.
struct TodayScreen: View {
    @EnvironmentObject private var model: AppModel
    @Binding var tab: Tab
    var open: (Metric) -> Void

    private var data: HealthData.TodaySummary { model.today }

    var body: some View {
        Screen(tab: $tab) {
            VStack(spacing: 0) {
                ScreenHeader(title: data.date) {
                    BatteryPill(percent: model.ring.batteryPercent)
                }

                HStack(spacing: 7) {
                    Circle()
                        .fill(model.ringManager.isReady ? Tok.accent : Tok.dim)
                        .frame(width: 6, height: 6)
                    Text(model.ringManager.isReady ? model.syncMessage : model.connectionLabel)
                        .font(.mono(10))
                        .foregroundStyle(Tok.muted)
                        .lineLimit(1)
                    Spacer()
                    if model.isSyncing { ProgressView().controlSize(.small).tint(Tok.accent) }
                }
                .padding(.horizontal, Tok.side)
                .padding(.top, 8)

                sleepHero

                VStack(spacing: 0) {
                    Hairline()
                    heartRateBand
                    Hairline()
                    stepsBand
                    Hairline()
                }
                .padding(.top, 10)
            }
        }
    }

    // MARK: Sleep hero

    private var sleepHero: some View {
        Button { open(.sleep) } label: {
            VStack(alignment: .leading, spacing: 0) {
                HStack {
                    Text("Sleep").labelType(10).foregroundStyle(Tok.muted)
                    Spacer()
                    Text("›").font(.mono(10)).foregroundStyle(Tok.accent)
                }

                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(data.sleepHours.map(String.init) ?? "0")
                        .font(.mono(72, .medium)).tracking(-4)
                    Text("h").font(.mono(18)).foregroundStyle(Tok.muted)
                    Text(data.sleepMinutes.map(String.init) ?? "0")
                        .font(.mono(72, .medium)).tracking(-4)
                        .padding(.leading, 8)
                    Text("m").font(.mono(18)).foregroundStyle(Tok.muted)
                }
                .padding(.top, 4)

                if data.hypnogram.isEmpty {
                    Text("No sleep session recorded yet")
                        .font(.mono(11)).foregroundStyle(Tok.dim)
                        .frame(maxWidth: .infinity, minHeight: 64, alignment: .leading)
                        .padding(.top, 12)
                } else {
                    hypnogram.padding(.top, 16)
                    sleepTimeline.padding(.top, 4)
                    sleepLegend.padding(.top, 6)
                }
            }
            .padding(.horizontal, Tok.side)
            .padding(.top, 18)
            .contentShape(Rectangle())
        }
        .buttonStyle(RowPressStyle())
        .accessibilityLabel(data.sleepHours.map { "Sleep, \($0) hours \(data.sleepMinutes ?? 0) minutes" }
                            ?? "No sleep data")
    }

    /// Stage runs sized in proportion to their duration, 1pt apart.
    private var hypnogram: some View {
        let total = data.hypnogram.reduce(0) { $0 + $1.weight }
        let gaps = CGFloat(data.hypnogram.count - 1)
        return GeometryReader { geo in
            let usable = max(0, geo.size.width - gaps)
            HStack(spacing: 1) {
                ForEach(Array(data.hypnogram.enumerated()), id: \.offset) { _, run in
                    Rectangle()
                        .fill(color(for: run.stage))
                        .frame(width: usable * run.weight / total)
                }
            }
        }
        .frame(height: 30)
    }

    /// The night's clock: end ticks plus three interior marks, with the times beneath.
    private var sleepTimeline: some View {
        VStack(spacing: 0) {
            Hairline()
            GeometryReader { geo in
                ZStack(alignment: .topLeading) {
                    ForEach(Array([0.0, 0.18, 0.46, 0.74, 1.0].enumerated()), id: \.offset) { i, f in
                        let isEnd = (i == 0 || i == 4)
                        Rectangle()
                            .fill(isEnd ? Tok.muted : Tok.hairline)
                            .frame(width: 1, height: isEnd ? 6 : 4)
                            .offset(x: min(geo.size.width - 1, geo.size.width * f))
                    }
                    Text(data.asleepAt).font(.mono(9)).foregroundStyle(Tok.muted)
                        .offset(y: 6)
                    Text(data.wokeAt).font(.mono(9)).foregroundStyle(Tok.muted)
                        .frame(width: geo.size.width, alignment: .trailing)
                        .offset(y: 6)
                }
            }
            .frame(height: 14)
        }
    }

    private var sleepLegend: some View {
        HStack(alignment: .top, spacing: 0) {
            ForEach(Array(data.stageTotals.enumerated()), id: \.offset) { _, entry in
                VStack(alignment: .leading, spacing: 0) {
                    HStack(spacing: 5) {
                        // Awake reads as an empty swatch with a dim outline.
                        Rectangle()
                            .fill(color(for: entry.0))
                            .frame(width: 8, height: 8)
                            .overlay {
                                if entry.0 == .awake {
                                    Rectangle().strokeBorder(Tok.dim, lineWidth: Tok.hairlineWidth)
                                }
                            }
                        Text(label(for: entry.0)).font(.mono(10)).foregroundStyle(Tok.muted)
                    }
                    Text(entry.1).font(.mono(13))
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    private func color(for stage: SleepStage) -> Color {
        switch stage {
        case .deep:  return Tok.sleepDeep
        case .light: return Tok.sleepLight
        case .rem:   return Tok.sleepREM
        case .awake: return Tok.sleepAwake
        }
    }

    private func label(for stage: SleepStage) -> String {
        switch stage {
        case .deep:  return "Deep"
        case .light: return "Light"
        case .rem:   return "REM"
        case .awake: return "Awake"
        }
    }

    // MARK: Heart rate

    private var heartRateBand: some View {
        Button { open(.heartRate) } label: {
            VStack(alignment: .leading, spacing: 0) {
                HStack {
                    Text("Heart rate").labelType(10).foregroundStyle(Tok.muted)
                    Spacer()
                    Text(model.isMeasuringHeartRate ? "● measuring" : data.heartRateFreshness)
                        .font(.mono(10))
                        .foregroundStyle(model.isMeasuringHeartRate ? Tok.accent : Tok.muted)
                }
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text((model.liveHeartRate ?? data.heartRate).map(String.init) ?? "—")
                        .font(.mono(40, .medium)).tracking(-2)
                    Text("bpm").font(.mono(13)).foregroundStyle(Tok.muted)
                }
                .padding(.top, 4)

                VStack(spacing: 0) {
                    Hairline()
                    PulseScope(bpm: model.liveHeartRate ?? data.heartRate).frame(maxHeight: .infinity)
                    Hairline()
                }
                .frame(minHeight: 36)
                .padding(.top, 10)

                HStack {
                    Text("ring heart rate").font(.mono(10)).foregroundStyle(Tok.muted)
                    Spacer()
                    Text("history & measure ›").font(.mono(10)).foregroundStyle(Tok.accent)
                }
                .padding(.top, 6)
            }
            .padding(.horizontal, Tok.side)
            .padding(.vertical, 14)
            .frame(maxHeight: .infinity)
            .contentShape(Rectangle())
        }
        .buttonStyle(RowPressStyle())
        .accessibilityLabel(data.heartRate.map { "Heart rate, \($0) beats per minute" }
                            ?? "No heart-rate data")
    }

    // MARK: Steps

    private var stepsBand: some View {
        Button { open(.steps) } label: {
            VStack(alignment: .leading, spacing: 0) {
                HStack {
                    Text("Steps").labelType(10).foregroundStyle(Tok.muted)
                    Spacer()
                    Text("›").font(.mono(10)).foregroundStyle(Tok.accent)
                }
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(verbatim: (data.steps ?? 0).formatted()).font(.mono(40, .medium)).tracking(-2)
                    Text("/ 10 000").font(.mono(13)).foregroundStyle(Tok.muted)
                }
                .padding(.top, 4)

                if data.steps == nil {
                    Text("No steps recorded today")
                        .font(.mono(10))
                        .foregroundStyle(Tok.dim)
                        .padding(.top, 3)
                }

                VStack(spacing: 0) {
                    GeometryReader { geo in
                        HStack(alignment: .bottom, spacing: 2) {
                            ForEach(Array(data.stepsByHour.enumerated()), id: \.offset) { i, h in
                                Rectangle()
                                    .fill(i >= data.stepsAccentFromHour
                                          ? Tok.accent : Tok.sleepREM)
                                    .frame(maxWidth: .infinity)
                                    .frame(height: geo.size.height * h)
                            }
                        }
                        .frame(width: geo.size.width, height: geo.size.height, alignment: .bottom)
                    }
                    Hairline()
                }
                .frame(minHeight: 32)
                .padding(.top, 10)

                HStack {
                    ForEach(Array(["12 AM", "6 AM", "12 PM", "6 PM", "12 AM"].enumerated()),
                            id: \.offset) { i, label in
                        if i > 0 { Spacer(minLength: 0) }
                        Text(label)
                    }
                }
                .font(.mono(10))
                .foregroundStyle(Tok.dim)
                .padding(.top, 6)
            }
            .padding(.horizontal, Tok.side)
            .padding(.vertical, 14)
            .frame(maxHeight: .infinity)
            .contentShape(Rectangle())
        }
        .buttonStyle(RowPressStyle())
        .accessibilityLabel(data.steps.map { "Steps, \($0) of \(data.stepGoal)" } ?? "No step data")
    }
}
