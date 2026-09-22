import Foundation
import SwiftData

@Model
final class HeartRateRecord {
    @Attribute(.unique) var key: String
    var deviceID: String
    var timestamp: Date
    var bpm: Int
    var source: String
    var timezoneID: String

    init(deviceID: String, timestamp: Date, bpm: Int, source: String,
         timezoneID: String = TimeZone.autoupdatingCurrent.identifier) {
        self.key = "\(deviceID)|\(Int(timestamp.timeIntervalSince1970))|\(source)"
        self.deviceID = deviceID
        self.timestamp = timestamp
        self.bpm = bpm
        self.source = source
        self.timezoneID = timezoneID
    }
}

@Model
final class StepRecord {
    @Attribute(.unique) var key: String
    var deviceID: String
    var timestamp: Date
    var steps: Int
    var calories: Int
    var distanceMeters: Int
    var timezoneID: String

    init(deviceID: String, timestamp: Date, steps: Int, calories: Int, distanceMeters: Int,
         timezoneID: String = TimeZone.autoupdatingCurrent.identifier) {
        self.key = "\(deviceID)|\(Int(timestamp.timeIntervalSince1970))"
        self.deviceID = deviceID
        self.timestamp = timestamp
        self.steps = steps
        self.calories = calories
        self.distanceMeters = distanceMeters
        self.timezoneID = timezoneID
    }
}

@Model
final class SleepSessionRecord {
    @Attribute(.unique) var key: String
    var deviceID: String
    var start: Date
    var end: Date
    var wakeDay: Date
    var timezoneID: String

    init(deviceID: String, start: Date, end: Date, wakeDay: Date,
         timezoneID: String = TimeZone.autoupdatingCurrent.identifier) {
        self.key = "\(deviceID)|\(Int(wakeDay.timeIntervalSince1970))"
        self.deviceID = deviceID
        self.start = start
        self.end = end
        self.wakeDay = wakeDay
        self.timezoneID = timezoneID
    }
}

@Model
final class SleepStageRecord {
    @Attribute(.unique) var key: String
    var sessionKey: String
    var start: Date
    var end: Date
    var stageRaw: String

    var stage: SleepStage { SleepStage(rawValue: stageRaw) ?? .light }

    init(sessionKey: String, start: Date, end: Date, stage: SleepStage, index: Int) {
        self.key = "\(sessionKey)|\(index)"
        self.sessionKey = sessionKey
        self.start = start
        self.end = end
        self.stageRaw = stage.rawValue
    }
}

@MainActor
final class HealthStore {
    private let context: ModelContext
    private var calendar: Calendar { .autoupdatingCurrent }
    private var ringCalendar: Calendar {
        var value = Calendar(identifier: .gregorian)
        value.timeZone = TimeZone(secondsFromGMT: 0)!
        return value
    }

    init(context: ModelContext) {
        self.context = context
    }

    func saveHeartRates(deviceID: String, day: Date, log: HeartRateLog) throws {
        for (index, bpm) in log.samples.enumerated() where (30...240).contains(bpm) {
            guard let timestamp = ringCalendar.date(
                byAdding: .minute, value: index * log.intervalMinutes,
                to: ringCalendar.startOfDay(for: day)
            ) else { continue }
            upsertHeartRate(deviceID: deviceID, timestamp: timestamp, bpm: bpm, source: "periodic")
        }
        try context.save()
    }

    func saveLiveHeartRate(deviceID: String, timestamp: Date, bpm: Int) throws {
        upsertHeartRate(deviceID: deviceID, timestamp: timestamp, bpm: bpm, source: "live")
        try context.save()
    }

    private func upsertHeartRate(deviceID: String, timestamp: Date, bpm: Int, source: String) {
        let key = "\(deviceID)|\(Int(timestamp.timeIntervalSince1970))|\(source)"
        let descriptor = FetchDescriptor<HeartRateRecord>(predicate: #Predicate { $0.key == key })
        if let existing = try? context.fetch(descriptor).first {
            existing.bpm = bpm
        } else {
            context.insert(HeartRateRecord(deviceID: deviceID, timestamp: timestamp, bpm: bpm, source: source))
        }
    }

    func saveSteps(deviceID: String, buckets: [StepBucket]) throws {
        for bucket in buckets {
            var components = DateComponents()
            // The ring clock and the date/time fields in 0x43 step packets are UTC.
            // Decode them in that same frame, then let dashboard queries/chart labels
            // convert the absolute Date into the user's current timezone.
            components.calendar = ringCalendar
            components.timeZone = ringCalendar.timeZone
            components.year = bucket.year
            components.month = bucket.month
            components.day = bucket.day
            components.hour = bucket.timeIndex / 4
            components.minute = (bucket.timeIndex % 4) * 15
            guard let timestamp = components.date else { continue }
            let key = "\(deviceID)|\(Int(timestamp.timeIntervalSince1970))"
            let descriptor = FetchDescriptor<StepRecord>(predicate: #Predicate { $0.key == key })
            if let existing = try? context.fetch(descriptor).first {
                existing.steps = bucket.steps
                existing.calories = bucket.calories
                existing.distanceMeters = bucket.distanceMeters
            } else {
                context.insert(StepRecord(deviceID: deviceID, timestamp: timestamp, steps: bucket.steps,
                                          calories: bucket.calories, distanceMeters: bucket.distanceMeters))
            }
        }
        try context.save()
    }

    func saveSleep(deviceID: String, nights: [RingSleepNight], now: Date = .now) throws {
        let today = ringCalendar.startOfDay(for: now)
        for night in nights {
            guard let wakeDay = ringCalendar.date(byAdding: .day, value: -night.daysAgo, to: today),
                  let start = ringCalendar.date(byAdding: .minute, value: night.startMinutes, to: wakeDay),
                  let end = ringCalendar.date(byAdding: .minute, value: night.endMinutes, to: wakeDay)
            else { continue }
            let sessionKey = "\(deviceID)|\(Int(wakeDay.timeIntervalSince1970))"
            let sessionDescriptor = FetchDescriptor<SleepSessionRecord>(predicate: #Predicate { $0.key == sessionKey })
            let session: SleepSessionRecord
            if let existing = try? context.fetch(sessionDescriptor).first {
                existing.start = start
                existing.end = end
                session = existing
            } else {
                session = SleepSessionRecord(deviceID: deviceID, start: start, end: end, wakeDay: wakeDay)
                context.insert(session)
            }

            let oldStages = try context.fetch(FetchDescriptor<SleepStageRecord>(
                predicate: #Predicate { $0.sessionKey == sessionKey }
            ))
            oldStages.forEach(context.delete)
            var stageStart = start
            for (index, item) in night.stages.enumerated() {
                guard let stageEnd = calendar.date(byAdding: .minute, value: item.durationMinutes, to: stageStart) else { continue }
                context.insert(SleepStageRecord(sessionKey: sessionKey, start: stageStart,
                                                end: stageEnd, stage: item.stage, index: index))
                stageStart = stageEnd
            }
        }
        try context.save()
    }

    func today(deviceID: String?, now: Date = .now) -> HealthData.TodaySummary {
        var result = HealthData.emptyToday(at: now)
        guard let deviceID else { return result }
        let start = calendar.startOfDay(for: now)
        let tomorrow = calendar.date(byAdding: .day, value: 1, to: start) ?? now

        let stepDescriptor = FetchDescriptor<StepRecord>(
            predicate: #Predicate { $0.deviceID == deviceID && $0.timestamp >= start && $0.timestamp < tomorrow },
            sortBy: [SortDescriptor(\.timestamp)]
        )
        let steps = (try? context.fetch(stepDescriptor)) ?? []
        if !steps.isEmpty {
            result.steps = steps.reduce(0) { $0 + $1.steps }
            var hourly = [Int](repeating: 0, count: 24)
            for record in steps {
                hourly[calendar.component(.hour, from: record.timestamp)] += record.steps
            }
            let maximum = max(1, hourly.max() ?? 1)
            result.stepsByHour = hourly.map { Double($0) / Double(maximum) }
            result.stepsAccentFromHour = min(23, calendar.component(.hour, from: now))
        }

        var heartDescriptor = FetchDescriptor<HeartRateRecord>(
            predicate: #Predicate { $0.deviceID == deviceID && $0.timestamp <= now },
            sortBy: [SortDescriptor(\.timestamp, order: .reverse)]
        )
        heartDescriptor.fetchLimit = 1
        if let latest = try? context.fetch(heartDescriptor).first {
            result.heartRate = latest.bpm
            result.heartRateFreshness = freshness(latest.timestamp, now: now)
        }

        var sleepDescriptor = FetchDescriptor<SleepSessionRecord>(
            predicate: #Predicate { $0.deviceID == deviceID && $0.end <= tomorrow },
            sortBy: [SortDescriptor(\.end, order: .reverse)]
        )
        sleepDescriptor.fetchLimit = 1
        if let sleep = try? context.fetch(sleepDescriptor).first {
            let sleepKey = sleep.key
            let stages = ((try? context.fetch(FetchDescriptor<SleepStageRecord>(
                predicate: #Predicate { $0.sessionKey == sleepKey },
                sortBy: [SortDescriptor(\.start)]
            ))) ?? [])
            let asleepMinutes = stages.filter { $0.stage != .awake }
                .reduce(0) { $0 + Int($1.end.timeIntervalSince($1.start) / 60) }
            result.sleepHours = asleepMinutes / 60
            result.sleepMinutes = asleepMinutes % 60
            result.hypnogram = stages.map { ($0.stage, max(1, $0.end.timeIntervalSince($0.start) / 60)) }
            let time = DateFormatter()
            time.timeStyle = .short
            result.asleepAt = time.string(from: sleep.start)
            result.wokeAt = time.string(from: sleep.end)
            var totals: [(SleepStage, String)] = []
            for stage in SleepStage.allCases {
                let matching = stages.filter { $0.stage == stage }
                let minutes = matching.reduce(0) { partial, record in
                    partial + Int(record.end.timeIntervalSince(record.start) / 60)
                }
                totals.append((stage, duration(minutes)))
            }
            result.stageTotals = totals
        }
        return result
    }

    func series(deviceID: String?, metric: Metric, range: MetricRange, now: Date = .now) -> MetricSeries {
        guard let deviceID else { return .empty(for: metric) }
        switch metric {
        case .sleep: return sleepSeries(deviceID: deviceID, range: range, now: now)
        case .heartRate: return heartSeries(deviceID: deviceID, range: range, now: now)
        case .steps: return stepSeries(deviceID: deviceID, range: range, now: now)
        }
    }

    func exportFiles(deviceID: String?) throws -> [URL] {
        guard let deviceID else { throw RingProtocolError.notReady }
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("R02 Health Export \(Int(Date().timeIntervalSince1970))", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let iso = ISO8601DateFormatter()

        let heart = try context.fetch(FetchDescriptor<HeartRateRecord>(
            predicate: #Predicate { $0.deviceID == deviceID }, sortBy: [SortDescriptor(\.timestamp)]))
        let heartCSV = "timestamp,bpm,source\n" + heart.map {
            "\(iso.string(from: $0.timestamp)),\($0.bpm),\($0.source)"
        }.joined(separator: "\n")

        let steps = try context.fetch(FetchDescriptor<StepRecord>(
            predicate: #Predicate { $0.deviceID == deviceID }, sortBy: [SortDescriptor(\.timestamp)]))
        let stepsCSV = "timestamp,steps,calories,distance_m\n" + steps.map {
            "\(iso.string(from: $0.timestamp)),\($0.steps),\($0.calories),\($0.distanceMeters)"
        }.joined(separator: "\n")

        let sessions = try context.fetch(FetchDescriptor<SleepSessionRecord>(
            predicate: #Predicate { $0.deviceID == deviceID }, sortBy: [SortDescriptor(\.start)]))
        let sessionCSV = "session_id,start,end,wake_day\n" + sessions.map {
            "\($0.key),\(iso.string(from: $0.start)),\(iso.string(from: $0.end)),\(iso.string(from: $0.wakeDay))"
        }.joined(separator: "\n")
        let keys = Set(sessions.map(\.key))
        let stages = try context.fetch(FetchDescriptor<SleepStageRecord>(sortBy: [SortDescriptor(\.start)]))
            .filter { keys.contains($0.sessionKey) }
        let stageCSV = "session_id,start,end,stage\n" + stages.map {
            "\($0.sessionKey),\(iso.string(from: $0.start)),\(iso.string(from: $0.end)),\($0.stageRaw)"
        }.joined(separator: "\n")

        let files = [
            ("heart_rate.csv", heartCSV), ("steps.csv", stepsCSV),
            ("sleep_sessions.csv", sessionCSV), ("sleep_stages.csv", stageCSV),
        ]
        return try files.compactMap { name, contents in
            let url = directory.appendingPathComponent(name)
            guard let data = contents.data(using: String.Encoding.utf8) else { return nil }
            try data.write(to: url, options: Data.WritingOptions.atomic)
            return url
        }
    }

    // MARK: - Aggregation

    private func rangeStart(_ range: MetricRange, now: Date) -> Date {
        let start = calendar.startOfDay(for: now)
        switch range {
        case .week: return calendar.date(byAdding: .day, value: -6, to: start)!
        case .month: return calendar.date(byAdding: .day, value: -29, to: start)!
        case .sixMonths: return calendar.date(byAdding: .month, value: -5, to: monthStart(start))!
        case .year: return calendar.date(byAdding: .month, value: -11, to: monthStart(start))!
        }
    }

    private func sleepSeries(deviceID: String, range: MetricRange, now: Date) -> MetricSeries {
        let start = rangeStart(range, now: now)
        let sessions = ((try? context.fetch(FetchDescriptor<SleepSessionRecord>(
            predicate: #Predicate { $0.deviceID == deviceID && $0.wakeDay >= start && $0.wakeDay <= now },
            sortBy: [SortDescriptor(\.wakeDay)]
        ))) ?? [])
        guard !sessions.isEmpty else { return .empty(for: .sleep) }
        var values: [(Date, Int, Int, Int)] = []
        for session in sessions {
            let sessionKey = session.key
            let stages = ((try? context.fetch(FetchDescriptor<SleepStageRecord>(
                predicate: #Predicate { $0.sessionKey == sessionKey }
            ))) ?? [])
            func minutes(_ stage: SleepStage) -> Int {
                stages.filter { $0.stage == stage }.reduce(0) { $0 + Int($1.end.timeIntervalSince($1.start) / 60) }
            }
            values.append((session.wakeDay, minutes(.light), minutes(.rem), minutes(.deep)))
        }
        let grouped = groupSleep(values, range: range)
        let total = grouped.map { $0.1 + $0.2 + $0.3 }
        let average = total.reduce(0, +) / max(1, total.count)
        let nights = grouped.map { value in
            SleepNight(axis: axisLabel(value.0, range: range),
                       label: selectionLabel(value.0, range: range),
                       height: min(1, Double(value.1 + value.2 + value.3) / 600),
                       light: Double(value.1), rem: Double(value.2), deep: Double(value.3))
        }
        return .init(headline: .init(value: duration(average), delta: "", caption: "Sleep average · synced from ring"),
                     chart: .sleep(nights: nights, average: max(0, 1 - Double(average) / 600)))
    }

    private func heartSeries(deviceID: String, range: MetricRange, now: Date) -> MetricSeries {
        let start = rangeStart(range, now: now)
        let records = ((try? context.fetch(FetchDescriptor<HeartRateRecord>(
            predicate: #Predicate { $0.deviceID == deviceID && $0.timestamp >= start && $0.timestamp <= now },
            sortBy: [SortDescriptor(\.timestamp)]
        ))) ?? [])
        guard !records.isEmpty else { return .empty(for: .heartRate) }
        let groups = Dictionary(grouping: records) { bucketStart($0.timestamp, range: range) }
        let ordered = groups.keys.sorted()
        let summaries = ordered.compactMap { date -> (Date, Int, Int, Int)? in
            guard let group = groups[date], !group.isEmpty else { return nil }
            let bpms = group.map(\.bpm)
            return (date, bpms.min()!, bpms.max()!, bpms.reduce(0, +) / bpms.count)
        }
        let days = summaries.map { item in
            HeartRateDay(top: clamp(1 - Double(item.2 - 35) / 170),
                         bottom: clamp(Double(item.3 - 35) / 170),
                         label: selectionLabel(item.0, range: range),
                         minimumBPM: item.1, maximumBPM: item.2, averageBPM: item.3)
        }
        let average = records.map(\.bpm).reduce(0, +) / records.count
        let axis = summaries.isEmpty ? [] : [axisLabel(summaries.first!.0, range: range),
                                             axisLabel(summaries.last!.0, range: range)]
        return .init(headline: .init(value: "\(average)", unit: "bpm", delta: "",
                                     caption: "Daily average · synced from ring"),
                     chart: .heartRate(days: days, gridlines: [0.2, 0.8],
                                       average: clamp(1 - Double(average - 35) / 170), axis: axis))
    }

    private func stepSeries(deviceID: String, range: MetricRange, now: Date) -> MetricSeries {
        let start = rangeStart(range, now: now)
        let records = ((try? context.fetch(FetchDescriptor<StepRecord>(
            predicate: #Predicate { $0.deviceID == deviceID && $0.timestamp >= start && $0.timestamp <= now },
            sortBy: [SortDescriptor(\.timestamp)]
        ))) ?? [])
        guard !records.isEmpty else { return .empty(for: .steps) }
        let daily = Dictionary(grouping: records) { calendar.startOfDay(for: $0.timestamp) }
            .mapValues { $0.reduce(0) { $0 + $1.steps } }
        let groups = Dictionary(grouping: daily.keys) { bucketStart($0, range: range) }
        let ordered = groups.keys.sorted()
        let values = ordered.map { key -> (Date, Int) in
            let days = groups[key] ?? []
            return (key, days.reduce(0) { $0 + (daily[$1] ?? 0) } / max(1, days.count))
        }
        let scale = max(10_000, values.map { $0.1 }.max() ?? 10_000)
        let bars = values.enumerated().map { index, value in
            StepBar(axis: axisLabel(value.0, range: range),
                    label: selectionLabel(value.0, range: range), steps: value.1,
                    height: Double(value.1) / Double(scale),
                    isCurrent: index == values.count - 1)
        }
        let average = daily.values.reduce(0, +) / max(1, daily.count)
        let hit = daily.values.filter { $0 >= 10_000 }.count
        return .init(headline: .init(value: average.formatted(), delta: "",
                                     caption: "Daily average · synced from ring"),
                     chart: .steps(bars: bars, goal: 1 - Double(10_000) / Double(scale), goalLabel: "goal 10k",
                                   average: 1 - Double(average) / Double(scale),
                                   note: "Goal hit \(hit) of \(daily.count) days"))
    }

    private func groupSleep(_ values: [(Date, Int, Int, Int)], range: MetricRange) -> [(Date, Int, Int, Int)] {
        let groups = Dictionary(grouping: values) { bucketStart($0.0, range: range) }
        return groups.keys.sorted().map { key in
            let rows = groups[key]!
            return (key,
                    rows.reduce(0) { $0 + $1.1 } / rows.count,
                    rows.reduce(0) { $0 + $1.2 } / rows.count,
                    rows.reduce(0) { $0 + $1.3 } / rows.count)
        }
    }

    private func bucketStart(_ date: Date, range: MetricRange) -> Date {
        switch range {
        case .week: return calendar.startOfDay(for: date)
        case .month:
            return calendar.dateInterval(of: .weekOfYear, for: date)?.start ?? calendar.startOfDay(for: date)
        case .sixMonths, .year: return monthStart(date)
        }
    }

    private func monthStart(_ date: Date) -> Date {
        calendar.date(from: calendar.dateComponents([.year, .month], from: date)) ?? date
    }

    private func axisLabel(_ date: Date, range: MetricRange) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = range == .week ? "EEEEE" : (range == .month ? "d MMM" : "MMM")
        return formatter.string(from: date)
    }

    private func selectionLabel(_ date: Date, range: MetricRange) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = range == .week ? "EEE d MMM" : (range == .month ? "'Week of' d MMM" : "MMMM yyyy")
        return formatter.string(from: date)
    }

    private func freshness(_ date: Date, now: Date) -> String {
        let minutes = max(0, Int(now.timeIntervalSince(date) / 60))
        if minutes < 1 { return "Just now" }
        if minutes < 60 { return "\(minutes) min ago" }
        if minutes < 1_440 { return "\(minutes / 60) h ago" }
        return "\(minutes / 1_440) d ago"
    }

    private func duration(_ minutes: Int) -> String { "\(minutes / 60) h \(minutes % 60)" }
    private func clamp(_ value: Double) -> Double { min(0.96, max(0.04, value)) }
}
