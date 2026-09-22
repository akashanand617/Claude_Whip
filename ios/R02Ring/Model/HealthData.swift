import Foundation

// MARK: - Chart primitives
//
// Geometry is expressed the way the design authored it: fractions of the plot height.
// `height` is the column's share of the plot; `topFraction` / `bottomFraction` measure
// from the top and bottom edges respectively, matching the CSS the design shipped.

struct SleepNight: Identifiable {
    let id = UUID()
    let axis: String
    /// Full period label shown while scrubbing (for example "Tue 22 Sep").
    let label: String
    /// Column height as a fraction of the plot (0…1).
    let height: Double
    /// Segment weights, top to bottom: light, REM, deep.
    let light: Double
    let rem: Double
    let deep: Double

    init(axis: String, label: String? = nil, height: Double,
         light: Double, rem: Double, deep: Double) {
        self.axis = axis
        self.label = label ?? axis
        self.height = height
        self.light = light
        self.rem = rem
        self.deep = deep
    }

    var totalMinutes: Int { Int((light + rem + deep).rounded()) }
}

struct HeartRateDay: Identifiable {
    let id = UUID()
    let label: String
    let minimumBPM: Int
    let maximumBPM: Int
    let averageBPM: Int
    /// Band top edge, measured down from the top of the plot (0…1) — the day's peak HR.
    let top: Double
    /// Band bottom edge, measured up from the bottom of the plot (0…1) — the day's resting HR,
    /// where the accent dot sits.
    let bottom: Double

    init(top: Double, bottom: Double, label: String = "Period",
         minimumBPM: Int? = nil, maximumBPM: Int? = nil, averageBPM: Int? = nil) {
        self.top = top
        self.bottom = bottom
        self.label = label
        let inferredHigh = Int((35 + (1 - top) * 170).rounded())
        let inferredAverage = Int((35 + bottom * 170).rounded())
        self.minimumBPM = minimumBPM ?? inferredAverage
        self.maximumBPM = maximumBPM ?? inferredHigh
        self.averageBPM = averageBPM ?? inferredAverage
    }
}

struct StepBar: Identifiable {
    let id = UUID()
    let axis: String
    let label: String
    let steps: Int
    let height: Double
    /// The current bucket draws in `accent`, earlier ones in `accentDeep`.
    let isCurrent: Bool

    init(axis: String, label: String? = nil, steps: Int? = nil,
         height: Double, isCurrent: Bool) {
        self.axis = axis
        self.label = label ?? axis
        self.steps = steps ?? Int((height * 10_000).rounded())
        self.height = height
        self.isCurrent = isCurrent
    }
}

enum ChartData {
    case sleep(nights: [SleepNight], average: Double)
    case heartRate(days: [HeartRateDay], gridlines: [Double], average: Double, axis: [String])
    case steps(bars: [StepBar], goal: Double, goalLabel: String, average: Double, note: String)
}

struct Headline {
    let value: String
    var unit: String? = nil
    let delta: String
    let caption: String
}

struct MetricSeries {
    let headline: Headline
    let chart: ChartData
}

extension MetricSeries {
    static func empty(for metric: Metric) -> MetricSeries {
        let headline = Headline(value: "—", delta: "", caption: "No synced data")
        switch metric {
        case .sleep:
            return .init(headline: headline, chart: .sleep(nights: [], average: 0.5))
        case .heartRate:
            return .init(headline: headline,
                         chart: .heartRate(days: [], gridlines: [0.2, 0.8], average: 0.5, axis: []))
        case .steps:
            return .init(headline: headline,
                         chart: .steps(bars: [], goal: 0.5, goalLabel: "goal 10k",
                                       average: 0.5, note: "No synced days"))
        }
    }
}

// MARK: - Fixtures
//
// The W/M/6M series for sleep/HR/steps are transcribed verbatim from the design canvas
// (10a, 10b, 10c) — those are the states the screens open in and the ones held to
// pixel fidelity. The remaining ranges are generated deterministically in the same
// shape so the range picker re-aggregates and re-animates for real.

enum HealthData {

    static func series(for metric: Metric, range: MetricRange) -> MetricSeries {
        switch metric {
        case .sleep:     return sleep(range)
        case .heartRate: return heartRate(range)
        case .steps:     return steps(range)
        }
    }

    // MARK: Sleep

    private static func sleep(_ range: MetricRange) -> MetricSeries {
        switch range {
        case .week:
            // 10a, verbatim.
            let nights = [
                SleepNight(axis: "T", height: 0.70, light: 32, rem: 24, deep: 24),
                SleepNight(axis: "W", height: 0.82, light: 38, rem: 22, deep: 32),
                SleepNight(axis: "T", height: 0.60, light: 28, rem: 20, deep: 16),
                SleepNight(axis: "F", height: 0.78, light: 34, rem: 24, deep: 28),
                SleepNight(axis: "S", height: 0.68, light: 30, rem: 24, deep: 20),
                SleepNight(axis: "S", height: 0.92, light: 38, rem: 24, deep: 36),
                SleepNight(axis: "M", height: 0.74, light: 32, rem: 24, deep: 26),
            ]
            return .init(
                headline: .init(value: "7 h 22", delta: "+18 min",
                                caption: "Nightly average · 9–15 Sep"),
                chart: .sleep(nights: nights, average: 0.34))

        case .month:
            let axis = ["W1", "W2", "W3", "W4"]
            var rng = LCG(seed: 21)
            let nights = axis.map { label in
                makeNight(label, &rng)
            }
            return .init(
                headline: .init(value: "7 h 09", delta: "+6 min",
                                caption: "Nightly average · Aug–Sep"),
                chart: .sleep(nights: nights, average: 0.38))

        case .sixMonths:
            let axis = ["Apr", "May", "Jun", "Jul", "Aug", "Sep"]
            var rng = LCG(seed: 44)
            return .init(
                headline: .init(value: "6 h 58", delta: "−4 min",
                                caption: "Nightly average · Apr–Sep"),
                chart: .sleep(nights: axis.map { makeNight($0, &rng) }, average: 0.41))

        case .year:
            let axis = ["O", "N", "D", "J", "F", "M", "A", "M", "J", "J", "A", "S"]
            var rng = LCG(seed: 77)
            return .init(
                headline: .init(value: "7 h 03", delta: "+11 min",
                                caption: "Nightly average · last 12 months"),
                chart: .sleep(nights: axis.map { makeNight($0, &rng) }, average: 0.37))
        }
    }

    private static func makeNight(_ axis: String, _ rng: inout LCG) -> SleepNight {
        SleepNight(axis: axis,
                   height: rng.next(in: 0.58...0.90),
                   light:  rng.next(in: 28...38),
                   rem:    rng.next(in: 20...24),
                   deep:   rng.next(in: 16...36))
    }

    // MARK: Heart rate

    private static func heartRate(_ range: MetricRange) -> MetricSeries {
        let gridlines = [0.20, 0.78]
        switch range {
        case .month:
            // 10b, verbatim.
            let pairs: [(Double, Double)] = [
                (0.22, 0.46), (0.14, 0.48), (0.28, 0.44), (0.12, 0.50),
                (0.24, 0.46), (0.16, 0.52), (0.30, 0.44), (0.13, 0.49),
                (0.20, 0.47), (0.18, 0.45), (0.12, 0.51), (0.21, 0.46),
            ]
            return .init(
                headline: .init(value: "54", unit: "bpm", delta: "−2 bpm",
                                caption: "Resting average · Aug–Sep"),
                chart: .heartRate(days: pairs.map { HeartRateDay(top: $0.0, bottom: $0.1) },
                                  gridlines: gridlines, average: 0.53,
                                  axis: ["18 Aug", "1 Sep", "now"]))

        case .week:
            var rng = LCG(seed: 9)
            let days = (0..<7).map { _ in makeHRDay(&rng) }
            return .init(
                headline: .init(value: "53", unit: "bpm", delta: "−1 bpm",
                                caption: "Resting average · 9–15 Sep"),
                chart: .heartRate(days: days, gridlines: gridlines,
                                  average: averageTopFraction(days),
                                  axis: ["9 Sep", "12 Sep", "now"]))

        case .sixMonths:
            var rng = LCG(seed: 31)
            let days = (0..<18).map { _ in makeHRDay(&rng) }
            return .init(
                headline: .init(value: "56", unit: "bpm", delta: "−3 bpm",
                                caption: "Resting average · Apr–Sep"),
                chart: .heartRate(days: days, gridlines: gridlines,
                                  average: averageTopFraction(days),
                                  axis: ["Apr", "Jul", "now"]))

        case .year:
            var rng = LCG(seed: 63)
            let days = (0..<24).map { _ in makeHRDay(&rng) }
            return .init(
                headline: .init(value: "57", unit: "bpm", delta: "−5 bpm",
                                caption: "Resting average · last 12 months"),
                chart: .heartRate(days: days, gridlines: gridlines,
                                  average: averageTopFraction(days),
                                  axis: ["Oct", "Apr", "now"]))
        }
    }

    private static func makeHRDay(_ rng: inout LCG) -> HeartRateDay {
        HeartRateDay(top: rng.next(in: 0.12...0.30), bottom: rng.next(in: 0.44...0.52))
    }

    /// The dashed average sits on the mean of the resting dots, converted to a from-the-top fraction.
    private static func averageTopFraction(_ days: [HeartRateDay]) -> Double {
        guard !days.isEmpty else { return 0.5 }
        let meanFromBottom = days.reduce(0) { $0 + $1.bottom } / Double(days.count)
        return 1 - meanFromBottom
    }

    // MARK: Steps

    private static func steps(_ range: MetricRange) -> MetricSeries {
        let note = "Goal hit 68% of days"
        switch range {
        case .sixMonths:
            // 10c, verbatim.
            let heights = [0.48, 0.57, 0.66, 0.53, 0.74, 0.61]
            let axis = ["Apr", "May", "Jun", "Jul", "Aug", "Sep"]
            let bars = zip(axis, heights).enumerated().map { i, pair in
                StepBar(axis: pair.0, height: pair.1, isCurrent: i == heights.count - 1)
            }
            return .init(
                headline: .init(value: "7,140", delta: "+640 / day",
                                caption: "Daily average · Apr–Sep"),
                chart: .steps(bars: bars, goal: 0.14, goalLabel: "goal 9k",
                              average: 0.40, note: note))

        case .week:
            var rng = LCG(seed: 5)
            let axis = ["T", "W", "T", "F", "S", "S", "M"]
            return .init(
                headline: .init(value: "7,684", delta: "+420 / day",
                                caption: "Daily average · 9–15 Sep"),
                chart: .steps(bars: makeBars(axis, &rng), goal: 0.12, goalLabel: "goal 9k",
                              average: 0.36, note: "Goal hit 4 of 7 days"))

        case .month:
            var rng = LCG(seed: 17)
            let axis = ["W1", "W2", "W3", "W4"]
            return .init(
                headline: .init(value: "7,402", delta: "+180 / day",
                                caption: "Daily average · Aug–Sep"),
                chart: .steps(bars: makeBars(axis, &rng), goal: 0.13, goalLabel: "goal 9k",
                              average: 0.38, note: "Goal hit 61% of days"))

        case .year:
            var rng = LCG(seed: 88)
            let axis = ["O", "N", "D", "J", "F", "M", "A", "M", "J", "J", "A", "S"]
            return .init(
                headline: .init(value: "6,905", delta: "+1,210 / day",
                                caption: "Daily average · last 12 months"),
                chart: .steps(bars: makeBars(axis, &rng), goal: 0.16, goalLabel: "goal 9k",
                              average: 0.44, note: "Goal hit 54% of days"))
        }
    }

    private static func makeBars(_ axis: [String], _ rng: inout LCG) -> [StepBar] {
        axis.enumerated().map { i, label in
            StepBar(axis: label, height: rng.next(in: 0.42...0.78), isCurrent: i == axis.count - 1)
        }
    }

    // MARK: Today (5a)

    struct TodaySummary {
        var date = "Today"
        var sleepHours: Int? = nil
        var sleepMinutes: Int? = nil
        /// Hypnogram run lengths, in the order they were slept.
        var hypnogram: [(stage: SleepStage, weight: Double)] = []
        var asleepAt = "—"
        var wokeAt = "—"
        var stageTotals: [(SleepStage, String)] = []
        var heartRate: Int? = nil
        var heartRateFreshness = "No reading"
        var steps: Int? = nil
        var stepGoal = 10_000
        /// Per-hour step bars across the 24h day; zero-height hours are still to come.
        var stepsByHour: [Double] = Array(repeating: 0, count: 24)
        /// Overnight hours draw dim; the waking day draws in accent.
        var stepsAccentFromHour = 0
    }

    static let today = TodaySummary(
        date: "Mon 15 Sep", sleepHours: 7, sleepMinutes: 12,
        hypnogram: [
            (.rem, 6), (.deep, 18), (.light, 9), (.deep, 12), (.awake, 3),
            (.light, 14), (.deep, 10), (.rem, 9), (.awake, 4), (.rem, 8),
        ],
        asleepAt: "11:42 PM", wokeAt: "6:54 AM",
        stageTotals: [(.deep, "2h 41"), (.light, "3h 32"), (.rem, "0h 46"), (.awake, "0h 13")],
        heartRate: 62, heartRateFreshness: "Just now", steps: 6842, stepGoal: 10_000,
        stepsByHour: [
            0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.12, 0.48, 0.90, 0.30, 0.18, 0.22,
            0.74, 0.40, 0.14, 0.26, 0, 0, 0, 0, 0, 0, 0, 0,
        ],
        stepsAccentFromHour: 7
    )

    static func emptyToday(at date: Date = .now) -> TodaySummary {
        let formatter = DateFormatter()
        formatter.dateFormat = "EEE d MMM"
        return TodaySummary(date: formatter.string(from: date))
    }
}

enum SleepStage: String, Codable, CaseIterable {
    case deep, light, rem, awake
}

// MARK: - Deterministic sample data

/// A tiny linear-congruential generator so the generated ranges are stable across
/// launches — a chart that reshuffles every time you tab away reads as a bug.
struct LCG {
    private var state: UInt64
    init(seed: UInt64) { state = seed &* 6364136223846793005 &+ 1442695040888963407 }

    private mutating func nextUnit() -> Double {
        state = state &* 6364136223846793005 &+ 1442695040888963407
        return Double((state >> 33) & 0xFFFFFF) / Double(0xFFFFFF)
    }

    mutating func next(in range: ClosedRange<Double>) -> Double {
        range.lowerBound + nextUnit() * (range.upperBound - range.lowerBound)
    }
}
