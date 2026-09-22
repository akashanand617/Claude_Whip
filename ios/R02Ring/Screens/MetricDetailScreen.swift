import SwiftUI

// MARK: - Range picker

/// `W · M · 6M · Y` — a single-select control in a hairline box, sized for thumb reach.
struct RangePicker: View {
    @Binding var selection: MetricRange

    var body: some View {
        HStack(spacing: 0) {
            ForEach(Array(MetricRange.allCases.enumerated()), id: \.element.id) { i, range in
                let active = range == selection
                Button {
                    selection = range
                } label: {
                    Text(range.label)
                        .font(.mono(11))
                        .foregroundStyle(active ? Tok.ink : Tok.muted)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 10)
                        .background(active ? Tok.accent : Color.clear)
                        .contentShape(Rectangle())
                        // Drawn as an overlay so the rule takes the segment's height
                        // rather than stretching the control to fill the screen.
                        .overlay(alignment: .leading) {
                            if i > 0 {
                                Rectangle().fill(Tok.hairline).frame(width: Tok.hairlineWidth)
                            }
                        }
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(active ? [.isButton, .isSelected] : .isButton)
            }
        }
        .fixedSize(horizontal: false, vertical: true)
        .overlay { Rectangle().strokeBorder(Tok.hairline, lineWidth: Tok.hairlineWidth) }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Range")
    }
}

// MARK: - Detail screen

/// One frame, three datasets: the period average with its delta, and a chart that
/// fills everything left over. Reached by tapping a stat on Today.
struct MetricDetailScreen: View {
    @EnvironmentObject private var model: AppModel
    let metric: Metric
    @Binding var tab: Tab
    var onBack: () -> Void

    @State private var range: MetricRange

    init(metric: Metric, tab: Binding<Tab>, onBack: @escaping () -> Void) {
        self.metric = metric
        self._tab = tab
        self.onBack = onBack
        self._range = State(initialValue: metric.defaultRange)
    }

    private var series: MetricSeries { model.series(for: metric, range: range) }

    var body: some View {
        Screen(tab: $tab) {
            VStack(alignment: .leading, spacing: 0) {

                // Header: just a back button. The metric's name lives in the headline.
                Button(action: onBack) {
                    Text("‹ Today")
                        .labelType()
                        .foregroundStyle(Tok.muted)
                        .frame(minHeight: Tok.tapTarget, alignment: .topLeading)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .padding(.horizontal, Tok.side)
                .padding(.top, Tok.headerTopPad)

                headline
                    .padding(.horizontal, Tok.side)
                    .padding(.top, 0)   // the back button's tap target already carries the gap

                if metric == .heartRate {
                    heartRateMeasurement
                        .padding(.horizontal, Tok.side)
                        .padding(.top, 16)
                }

                chart
                    // A new range starts with a clean chart. Its exact values appear
                    // only after the user taps or drags across a day/bucket.
                    .id(range)
                    .padding(.horizontal, Tok.side)
                    .padding(.top, 26)
                    .frame(maxHeight: .infinity)

                RangePicker(selection: $range)
                    .padding(.horizontal, Tok.side)
                    .padding(.top, 22)
                    .padding(.bottom, 16)
            }
            .animation(.easeOut(duration: 0.2), value: range)
        }
        .onDisappear {
            if metric == .heartRate { model.stopHeartRateMeasurement() }
        }
    }

    private var heartRateMeasurement: some View {
        Button {
            if model.isMeasuringHeartRate {
                model.stopHeartRateMeasurement()
            } else {
                model.measureHeartRate()
            }
        } label: {
            HStack {
                if model.isMeasuringHeartRate { ProgressView().tint(Tok.accent) }
                Text(model.isMeasuringHeartRate ? "Measuring…" : "Measure now")
                    .font(.mono(11, .medium))
                Spacer()
                if let bpm = model.liveHeartRate {
                    Text("\(bpm) bpm").font(.mono(12)).foregroundStyle(Tok.accent)
                }
            }
            .foregroundStyle(Tok.text)
            .frame(minHeight: 44)
            .padding(.horizontal, 12)
            .overlay { Rectangle().strokeBorder(Tok.hairline, lineWidth: Tok.hairlineWidth) }
        }
        .buttonStyle(.plain)
        .disabled(!model.ringManager.isReady)
    }

    private var headline: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(metric.title)
                .labelType(10)
                .foregroundStyle(Tok.muted)

            HStack(alignment: .firstTextBaseline, spacing: 10) {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(series.headline.value)
                        .font(.serif(44))
                    if let unit = series.headline.unit {
                        Text(unit)
                            .font(.serif(18))
                            .foregroundStyle(Tok.muted)
                    }
                }
                Text(series.headline.delta)
                    .font(.mono(11))
                    .foregroundStyle(Tok.accent)
            }

            Text(series.headline.caption)
                .labelType(10, tracking: 0.06)
                .foregroundStyle(Tok.dim)
        }
        .accessibilityElement(children: .combine)
    }

    @ViewBuilder
    private var chart: some View {
        switch series.chart {
        case let .sleep(nights, average):
            SleepChart(nights: nights, average: average)
        case let .heartRate(days, gridlines, average, axis):
            HeartRateChart(days: days, gridlines: gridlines, average: average, axis: axis)
        case let .steps(bars, goal, goalLabel, average, note):
            StepsChart(bars: bars, goal: goal, goalLabel: goalLabel, average: average, note: note)
        }
    }
}
