import SwiftUI

// MARK: - Shared chart chrome
//
// Every rule's percentage is a fraction of the *plot* height, not of the whole chart
// block: at the authored size that is what puts the steps average on the mean of the
// bars (40% from the top vs. a 59.8% mean bar height) and the heart-rate average on
// the mean of the resting dots. The design's CSS positions them against the outer box,
// which is a close-enough approximation at 393×852 only.

/// Plot + baseline + axis + legend, with the rules overlaid on the plot.
private struct ChartFrame<Plot: View, Axis: View>: View {
    var rules: [Rule]
    var legend: [LegendRow.Item]
    @ViewBuilder var plot: Plot
    @ViewBuilder var axis: Axis

    struct Rule {
        var fraction: Double
        var color: Color
        var opacity: Double = 1
        var dashed: Bool = true
        var label: String? = nil
    }

    var body: some View {
        VStack(spacing: 0) {
            plot
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .overlay {
                    GeometryReader { geo in
                        ForEach(Array(rules.enumerated()), id: \.offset) { _, rule in
                            let y = geo.size.height * rule.fraction
                            ZStack(alignment: .topLeading) {
                                if rule.dashed {
                                    DashedRule(color: rule.color, opacity: rule.opacity)
                                } else {
                                    Hairline(color: rule.color)
                                }
                                if let label = rule.label {
                                    Text(label)
                                        .font(.mono(9))
                                        .foregroundStyle(rule.color)
                                        .offset(y: -14)
                                }
                            }
                            .offset(y: y)
                        }
                    }
                }

            Hairline()
            axis.padding(.top, 8)

            LegendRow(items: legend).padding(.top, 12)
        }
    }
}

/// `flex:1` columns with a fixed gap — the layout every plot row uses.
private struct PlotRow<Content: View>: View {
    var spacing: CGFloat
    @ViewBuilder var content: Content

    var body: some View {
        HStack(alignment: .bottom, spacing: spacing) { content }
    }
}

/// Axis labels, one centred under each column.
private struct ColumnAxis: View {
    var labels: [String]
    var spacing: CGFloat

    var body: some View {
        HStack(spacing: spacing) {
            ForEach(Array(labels.enumerated()), id: \.offset) { _, label in
                Text(label)
                    .font(.mono(10))
                    .foregroundStyle(Tok.muted)
                    .frame(maxWidth: .infinity)
            }
        }
    }
}

// MARK: - Sleep (10a)

/// Seven nightly columns, each a bottom-aligned stack of light / REM / deep.
struct SleepChart: View {
    var nights: [SleepNight]
    var average: Double

    var body: some View {
        ChartFrame(
            rules: [.init(fraction: average, color: Tok.accent, opacity: 0.6)],
            legend: [
                .init(color: Tok.accent, label: "Deep"),
                .init(color: Tok.accentDeep, label: "REM"),
                .init(color: Tok.series3, label: "Light"),
            ]
        ) {
            GeometryReader { geo in
                PlotRow(spacing: 10) {
                    ForEach(nights) { night in
                        let h = geo.size.height * night.height
                        let total = night.light + night.rem + night.deep
                        VStack(spacing: 0) {
                            Rectangle().fill(Tok.series3)
                                .frame(height: h * night.light / total)
                            Rectangle().fill(Tok.accentDeep)
                                .frame(height: h * night.rem / total)
                            Rectangle().fill(Tok.accent)
                                .frame(height: h * night.deep / total)
                        }
                        .frame(maxWidth: .infinity)
                    }
                }
                .frame(width: geo.size.width, height: geo.size.height, alignment: .bottom)
            }
        } axis: {
            ColumnAxis(labels: nights.map(\.axis), spacing: 10)
        }
    }
}

// MARK: - Heart rate (10b)

/// One pill per day spanning min–max, with the resting dot on its lower end.
struct HeartRateChart: View {
    var days: [HeartRateDay]
    var gridlines: [Double]
    var average: Double
    var axis: [String]

    var body: some View {
        ChartFrame(
            rules: gridlines.map { .init(fraction: $0, color: Tok.hairline, dashed: false) }
                 + [.init(fraction: average, color: Tok.accent, opacity: 0.6)],
            legend: [
                .init(color: Tok.accentDeep, label: "Daily min–max"),
                .init(color: Tok.accent, label: "Resting"),
            ]
        ) {
            GeometryReader { geo in
                HStack(spacing: 8) {
                    ForEach(days) { day in
                        let h = geo.size.height
                        let bandTop = h * day.top
                        let bandHeight = max(0, h * (1 - day.top - day.bottom))
                        ZStack(alignment: .topLeading) {
                            GeometryReader { col in
                                // Inset 25% left and right of the column.
                                Capsule()
                                    .fill(Tok.accentDeep)
                                    .frame(width: col.size.width * 0.5, height: bandHeight)
                                    .offset(x: col.size.width * 0.25, y: bandTop)
                                // The day's resting HR, centred on the band's lower end.
                                Circle()
                                    .fill(Tok.accent)
                                    .frame(width: 6, height: 6)
                                    .offset(x: col.size.width / 2 - 3,
                                            y: h * (1 - day.bottom) - 3)
                            }
                        }
                        .frame(maxWidth: .infinity)
                    }
                }
            }
        } axis: {
            HStack {
                ForEach(Array(axis.enumerated()), id: \.offset) { i, label in
                    if i > 0 { Spacer(minLength: 0) }
                    Text(label).font(.mono(10)).foregroundStyle(Tok.muted)
                }
            }
        }
    }
}

// MARK: - Steps (10c)

/// Monthly bars against a goal line, the current month picked out in accent.
struct StepsChart: View {
    var bars: [StepBar]
    var goal: Double
    var goalLabel: String
    var average: Double
    var note: String

    var body: some View {
        ChartFrame(
            rules: [
                .init(fraction: goal, color: Tok.dim, label: goalLabel),
                .init(fraction: average, color: Tok.accent, opacity: 0.6),
            ],
            legend: [
                .init(color: Tok.accent, label: "This month"),
                .init(color: nil, label: note),
            ]
        ) {
            GeometryReader { geo in
                PlotRow(spacing: 14) {
                    ForEach(bars) { bar in
                        Rectangle()
                            .fill(bar.isCurrent ? Tok.accent : Tok.accentDeep)
                            .frame(maxWidth: .infinity)
                            .frame(height: geo.size.height * bar.height)
                    }
                }
                .frame(width: geo.size.width, height: geo.size.height, alignment: .bottom)
            }
        } axis: {
            ColumnAxis(labels: bars.map(\.axis), spacing: 14)
        }
    }
}
