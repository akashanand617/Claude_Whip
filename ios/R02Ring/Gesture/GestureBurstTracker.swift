import Foundation

/// Port of whip.events.BurstTracker, pinned by full recorded-stream replay tests.
final class GestureBurstTracker {
    private struct Vote {
        let start: Double
        let label: String
        let confidence: Double
        let direction: String
    }
    private final class Burst {
        let on: Double
        var off: Double
        var peak = 0.0
        var above = 0
        var lull = (length: 0.0, lo: 0.0, hi: 0.0)
        init(_ on: Double, _ off: Double) { self.on = on; self.off = off }
    }
    private var bursts: [Burst] = []
    private var pending: [Burst] = []
    private var open: Burst?
    private var windows: [Vote] = []
    private var lastWindow = -Double.infinity
    private var lastTime = -Double.infinity
    private var waveStart: Double?
    private var waveLast = -Double.infinity
    private var waveCount = 0
    private var waveJudged = false
    private var waveSuppressedUntil = -Double.infinity
    private var waveConfidence = 0.0
    private var waveDirections: [String] = [] // at most min_run entries needed

    func sample(_ time: Double, magnitude: Double) -> [RingGestureEvent] {
        lastTime = time
        if magnitude >= 1 {
            if open == nil { open = Burst(time, time) }
            else if let b = open {
                let gap = time - b.off
                if gap > b.lull.length { b.lull = (gap, b.off, time) }
                b.off = time
            }
            open!.peak = max(open!.peak, magnitude)
            open!.above += 1
        } else if let b = open, time - b.off >= 0.6 {
            open = nil
            if !(b.above == 1 && b.peak < 1.5) {
                let parts = b.off - b.on > 2 && b.lull.length >= 0.35
                    ? [Burst(b.on, b.lull.lo), Burst(b.lull.hi, b.off)] : [b]
                bursts += parts; pending += parts
            }
        }
        return judgeReady(time)
    }

    func window(_ start: Double, label: String, confidence: Double, direction: String) -> [RingGestureEvent] {
        if label != "none" && label != "wave" {
            windows.append(Vote(start: start, label: label, confidence: confidence, direction: direction))
        }
        windows.removeAll { $0.start < start - 6 }
        var events: [RingGestureEvent] = []
        if waveStart != nil && start - waveLast > 0.48 { closeWave(at: waveLast + 0.24) }
        if label != "wave" { closeWave(at: start) }
        else {
            if waveStart == nil { waveStart = start }
            waveLast = start
            waveCount = min(4, waveCount + 1)
            if waveCount <= 3 {
                waveConfidence += confidence
                if direction != "none" { waveDirections.append(direction) }
            }
            if waveCount == 3 && !waveJudged {
                waveJudged = true
                if start >= waveSuppressedUntil {
                    events.append(RingGestureEvent(name: "wave", direction: dominant(waveDirections),
                                                   time: (waveStart! + start) / 2 + 1,
                                                   confidence: waveConfidence / 3, votes: 3, latency: nil, end: nil))
                }
            }
        }
        lastWindow = start
        events += judgeReady(max(lastTime, start + 2))
        return events
    }

    private func closeWave(at end: Double) {
        if waveStart != nil && waveJudged { waveSuppressedUntil = end + 2 }
        waveStart = nil; waveCount = 0; waveJudged = false; waveConfidence = 0
        waveDirections.removeAll(keepingCapacity: true)
    }

    private func dominant(_ values: [String]) -> String {
        // Match whip.events.dominant_direction: most votes, then earliest vote.
        // Callers exclude "none"; confidence does not break direction ties.
        var result = "none", best = 0
        for value in values {
            let count = values.filter { $0 == value }.count
            if count > best { result = value; best = count }
        }
        return result
    }

    private func votes(_ b: Burst) -> [Vote] {
        let lo = bursts.last { $0 !== b && $0.on < b.on }?.off ?? -.infinity
        let hi = (bursts.filter { $0 !== b && $0.on > b.on }.map(\.on)
                  + (open.map { [$0.on] } ?? [])).min() ?? .infinity
        let mine = windows.filter { lo <= $0.start && $0.start <= b.on - 0.08 && $0.start + 2 >= min(b.off, b.on + 1.3) + 0.08 }
        let clean = mine.filter { $0.start + 2 <= hi }
        return clean.count >= 2 ? clean : mine
    }

    private func early(_ b: Burst) -> Bool {
        if b.off - b.on > 2 { return true }
        guard lastWindow.isFinite else { return false }
        let remaining = Int(ceil(max(0, b.on - 0.08 - lastWindow) / 0.24))
        let v = votes(b)
        guard v.count >= 2 else { return false }
        let counts = Dictionary(grouping: v, by: \.label).values.map(\.count).sorted(by: >)
        let runner = counts.count > 1 ? counts[1] : 0
        return counts[0] > runner + remaining || (v.count >= 3 && counts.count == 1)
    }

    private func judgeReady(_ now: Double) -> [RingGestureEvent] {
        var events: [RingGestureEvent] = []
        for b in pending {
            guard lastWindow > b.on - 0.08 || now >= b.on - 0.08 + 2 + 2 * 0.24 || early(b) else { continue }
            if let event = judge(b, at: now) { events.append(event) }
            pending.removeAll { $0 === b }
        }
        // Keep the immediate predecessor of the earliest pending/open movement,
        // not the whole session (the Python UI retains all judged diagnostics).
        let earliest = pending.map(\.on).min() ?? open?.on ?? .infinity
        if let predecessor = bursts.lastIndex(where: { $0.on < earliest }), predecessor > 0 {
            bursts.removeFirst(predecessor)
        }
        return events
    }

    private func judge(_ b: Burst, at now: Double) -> RingGestureEvent? {
        guard b.off - b.on <= 2 else { return nil }
        let v = votes(b)
        var labels: [String] = []
        for vote in v where !labels.contains(vote.label) { labels.append(vote.label) }
        var best: [Vote] = []
        for label in labels {
            let group = v.filter { $0.label == label }
            if group.count > best.count || (group.count == best.count && group.reduce(0, { $0 + $1.confidence }) > best.reduce(0, { $0 + $1.confidence })) {
                best = group
            }
        }
        guard best.count >= 2 else { return nil }
        return RingGestureEvent(name: best[0].label, direction: dominant(best.map(\.direction).filter { $0 != "none" }),
                                time: b.on, confidence: best.reduce(0, { $0 + $1.confidence }) / Double(best.count),
                                votes: best.count, latency: now - b.on, end: b.off)
    }
}
