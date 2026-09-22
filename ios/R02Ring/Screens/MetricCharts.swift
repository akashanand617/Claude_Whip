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
                .background {
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

/// Compact in-plot callout for the selected day. It only exists after a tap or
/// drag, leaving the chart clean in its resting state.
private struct ChartTooltip: View {
    var label: String
    var value: String
    var detail: String

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(label).labelType(8).foregroundStyle(Tok.muted)
            Text(value).font(.mono(12, .medium)).foregroundStyle(Tok.text)
            Text(detail).font(.mono(9)).foregroundStyle(Tok.muted).lineLimit(1)
        }
        .padding(.horizontal, 9)
        .padding(.vertical, 7)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Tok.inkRaised.opacity(0.96))
        .overlay { Rectangle().strokeBorder(Tok.hairline, lineWidth: Tok.hairlineWidth) }
        .accessibilityElement(children: .combine)
    }
}

/// Keeps a tooltip close to its selected mark without allowing it to leave the plot.
private struct AnchoredChartTooltip: View {
    var plotSize: CGSize
    var columnIndex: Int
    var columnCount: Int
    var markTop: CGFloat
    var label: String
    var value: String
    var detail: String

    private let tooltipWidth: CGFloat = 190
    private let tooltipHeight: CGFloat = 58

    var body: some View {
        let columnWidth = plotSize.width / CGFloat(max(1, columnCount))
        let markX = (CGFloat(columnIndex) + 0.5) * columnWidth
        let x = min(plotSize.width - tooltipWidth / 2 - 8,
                    max(tooltipWidth / 2 + 8, markX))
        let preferredY = markTop - tooltipHeight / 2 - 10
        let y = min(plotSize.height - tooltipHeight / 2 - 8,
                    max(tooltipHeight / 2 + 8, preferredY))

        ChartTooltip(label: label, value: value, detail: detail)
            .frame(width: tooltipWidth, alignment: .leading)
            .position(x: x, y: y)
            .allowsHitTesting(false)
    }
}

private struct ChartScrubber: View {
    var count: Int
    @Binding var selection: Int?

    var body: some View {
        GeometryReader { geo in
            if count > 0 {
                let columnWidth = geo.size.width / CGFloat(count)
                ZStack(alignment: .leading) {
                    if let selection {
                        let selected = min(max(selection, 0), count - 1)
                        Rectangle()
                            .fill(Tok.text.opacity(0.36))
                            .frame(width: Tok.hairlineWidth)
                            .offset(x: (CGFloat(selected) + 0.5) * columnWidth)
                    }

                    Color.clear
                        .contentShape(Rectangle())
                        .gesture(
                            DragGesture(minimumDistance: 0, coordinateSpace: .local)
                                .onChanged { gesture in
                                    let fraction = min(0.999_999, max(0, gesture.location.x / max(1, geo.size.width)))
                                    selection = min(count - 1, max(0, Int(fraction * CGFloat(count))))
                                }
                        )
                }
            }
        }
    }
}

private func chartDuration(_ minutes: Int) -> String {
    "\(minutes / 60) h \(minutes % 60) min"
}

private struct SleepPlot: View {
    var nights: [SleepNight]
    var selectedIndex: Int?
    @Binding var selection: Int?

    var body: some View {
        GeometryReader { geo in
            PlotRow(spacing: 10) {
                ForEach(Array(nights.enumerated()), id: \.element.id) { index, night in
                    SleepColumn(night: night, plotHeight: geo.size.height,
                                selectionState: selectedIndex.map { index == $0 })
                }
            }
            .frame(width: geo.size.width, height: geo.size.height, alignment: .bottom)
            .overlay { ChartScrubber(count: nights.count, selection: $selection) }
            .overlay {
                if let selectedIndex, nights.indices.contains(selectedIndex) {
                    let night = nights[selectedIndex]
                    AnchoredChartTooltip(
                        plotSize: geo.size,
                        columnIndex: selectedIndex,
                        columnCount: nights.count,
                        markTop: geo.size.height * (1 - night.height),
                        label: night.label,
                        value: chartDuration(night.totalMinutes),
                        detail: "Deep \(chartDuration(Int(night.deep.rounded()))) · REM \(chartDuration(Int(night.rem.rounded()))) · Light \(chartDuration(Int(night.light.rounded())))"
                    )
                }
            }
        }
    }
}

private struct SleepColumn: View {
    var night: SleepNight
    var plotHeight: CGFloat
    var selectionState: Bool?

    var body: some View {
        let height = plotHeight * night.height
        let total = max(1, night.light + night.rem + night.deep)
        VStack(spacing: 0) {
            Rectangle().fill(Tok.series3).frame(height: height * night.light / total)
            Rectangle().fill(Tok.accentDeep).frame(height: height * night.rem / total)
            Rectangle().fill(Tok.accent).frame(height: height * night.deep / total)
        }
        .opacity(selectionState == false ? 0.42 : 1)
        .frame(maxWidth: .infinity)
    }
}

private struct HeartRatePlot: View {
    var days: [HeartRateDay]
    var selectedIndex: Int?
    @Binding var selection: Int?

    var body: some View {
        GeometryReader { geo in
            HStack(spacing: 8) {
                ForEach(Array(days.enumerated()), id: \.element.id) { index, day in
                    HeartRateColumn(day: day, plotHeight: geo.size.height,
                                    selectionState: selectedIndex.map { index == $0 })
                }
            }
            .overlay { ChartScrubber(count: days.count, selection: $selection) }
            .overlay {
                if let selectedIndex, days.indices.contains(selectedIndex) {
                    let day = days[selectedIndex]
                    AnchoredChartTooltip(plotSize: geo.size,
                                         columnIndex: selectedIndex,
                                         columnCount: days.count,
                                         markTop: geo.size.height * day.top,
                                         label: day.label,
                                         value: "\(day.averageBPM) bpm average",
                                         detail: "\(day.minimumBPM)–\(day.maximumBPM) bpm range")
                }
            }
        }
    }
}

private struct HeartRateColumn: View {
    var day: HeartRateDay
    var plotHeight: CGFloat
    var selectionState: Bool?

    var body: some View {
        let top = plotHeight * day.top
        let bandHeight = max(0, plotHeight * (1 - day.top - day.bottom))
        GeometryReader { col in
            Capsule()
                .fill(selectionState == true ? Tok.accent : Tok.accentDeep)
                .frame(width: col.size.width * 0.5, height: bandHeight)
                .offset(x: col.size.width * 0.25, y: top)
            Circle()
                .fill(Tok.text)
                .frame(width: selectionState == true ? 8 : 6, height: selectionState == true ? 8 : 6)
                .offset(x: col.size.width / 2 - (selectionState == true ? 4 : 3),
                        y: plotHeight * (1 - day.bottom) - (selectionState == true ? 4 : 3))
        }
        .opacity(selectionState == false ? 0.45 : 1)
        .frame(maxWidth: .infinity)
    }
}

private struct StepsPlot: View {
    var bars: [StepBar]
    var selectedIndex: Int?
    @Binding var selection: Int?

    var body: some View {
        GeometryReader { geo in
            PlotRow(spacing: 14) {
                ForEach(Array(bars.enumerated()), id: \.element.id) { index, bar in
                    Rectangle()
                        .fill(selectedIndex == index ? Tok.accent : Tok.accentDeep)
                        .opacity(selectedIndex == nil || selectedIndex == index ? 1 : 0.42)
                        .frame(maxWidth: .infinity)
                        .frame(height: bar.steps > 0 ? max(2, geo.size.height * bar.height) : 0)
                }
            }
            .frame(width: geo.size.width, height: geo.size.height, alignment: .bottom)
            .overlay { ChartScrubber(count: bars.count, selection: $selection) }
            .overlay {
                if let selectedIndex, bars.indices.contains(selectedIndex) {
                    let bar = bars[selectedIndex]
                    let percent = Int((Double(bar.steps) / 10_000 * 100).rounded())
                    AnchoredChartTooltip(plotSize: geo.size,
                                         columnIndex: selectedIndex,
                                         columnCount: bars.count,
                                         markTop: geo.size.height * (1 - bar.height),
                                         label: bar.label,
                                         value: "\(bar.steps.formatted()) steps",
                                         detail: "\(percent)% of 10,000 goal")
                }
            }
        }
    }
}

// MARK: - Sleep (10a)

/// Seven nightly columns, each a bottom-aligned stack of light / REM / deep.
struct SleepChart: View {
    var nights: [SleepNight]
    var average: Double
    @State private var selection: Int?

    private var selectedIndex: Int? {
        guard let selection, nights.indices.contains(selection) else { return nil }
        return selection
    }

    var body: some View {
        framedChart
        .onChange(of: nights.count) { _, count in
            normalizeSelection(for: count)
        }
    }

    private func normalizeSelection(for count: Int) {
        guard count > 0, let selection else {
            selection = nil
            return
        }
        self.selection = min(selection, count - 1)
    }

    private var framedChart: some View {
        ChartFrame(
            rules: [.init(fraction: average, color: Tok.accent, opacity: 0.6)],
            legend: [
                .init(color: Tok.accent, label: "Deep"),
                .init(color: Tok.accentDeep, label: "REM"),
                .init(color: Tok.series3, label: "Light"),
            ]
        ) {
            SleepPlot(nights: nights, selectedIndex: selectedIndex, selection: $selection)
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
    @State private var selection: Int?

    private var selectedIndex: Int? {
        guard let selection, days.indices.contains(selection) else { return nil }
        return selection
    }

    var body: some View {
        framedChart
        .onChange(of: days.count) { _, count in
            normalizeSelection(for: count)
        }
    }

    private func normalizeSelection(for count: Int) {
        guard count > 0, let selection else {
            selection = nil
            return
        }
        self.selection = min(selection, count - 1)
    }

    private var chartRules: [ChartFrame<HeartRatePlot, HeartRateAxis>.Rule] {
        gridlines.map { .init(fraction: $0, color: Tok.hairline, dashed: false) }
            + [.init(fraction: average, color: Tok.accent, opacity: 0.6)]
    }

    private var framedChart: some View {
        ChartFrame(
            rules: chartRules,
            legend: [
                .init(color: Tok.accentDeep, label: "Daily min–max"),
                .init(color: Tok.accent, label: "Average"),
            ]
        ) {
            HeartRatePlot(days: days, selectedIndex: selectedIndex, selection: $selection)
        } axis: {
            HeartRateAxis(labels: axis)
        }
    }
}

private struct HeartRateAxis: View {
    var labels: [String]
    var body: some View {
        HStack {
            ForEach(Array(labels.enumerated()), id: \.offset) { index, label in
                if index > 0 { Spacer(minLength: 0) }
                Text(label).font(.mono(10)).foregroundStyle(Tok.muted)
            }
        }
    }
}

// MARK: - Steps (10c)

/// Daily bars in Week view; longer ranges use readable aggregate buckets.
struct StepsChart: View {
    var bars: [StepBar]
    var goal: Double
    var goalLabel: String
    var average: Double
    var note: String
    @State private var selection: Int?

    private var selectedIndex: Int? {
        guard let selection, bars.indices.contains(selection) else { return nil }
        return selection
    }

    var body: some View {
        framedChart
        .onChange(of: bars.count) { _, count in
            normalizeSelection(for: count)
        }
    }

    private func normalizeSelection(for count: Int) {
        guard count > 0, let selection else {
            selection = nil
            return
        }
        self.selection = min(selection, count - 1)
    }

    private var framedChart: some View {
        ChartFrame(
            rules: [
                .init(fraction: goal, color: Tok.dim, label: goalLabel),
                .init(fraction: average, color: Tok.accent, opacity: 0.6),
            ],
            legend: [
                .init(color: Tok.accent, label: "Selected period"),
                .init(color: nil, label: note),
            ]
        ) {
            StepsPlot(bars: bars, selectedIndex: selectedIndex, selection: $selection)
        } axis: {
            ColumnAxis(labels: bars.map(\.axis), spacing: 14)
        }
    }
}
