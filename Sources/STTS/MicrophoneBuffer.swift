import Foundation
import Synchronization

/// One capture producer and one audio-render consumer. The render callback
/// neither waits for the capture queue nor allocates/schedules audio buffers.
final class MicrophoneBuffer: @unchecked Sendable {
    static let capacity = 16384
    static let target = 2880 // 60 ms at 48 kHz, including capture callback jitter.
    private let samples = UnsafeMutablePointer<Float>.allocate(capacity: capacity)
    private let written = Atomic<Int>(0)
    private let consumed = Atomic<Int>(0)
    private let resync = Atomic<Bool>(false)
    private let underrunCount = Atomic<Int>(0)
    private let overflowCount = Atomic<Int>(0)
    private let captureFrames = Atomic<Int>(0)
    private let renderFrames = Atomic<Int>(0)
    // Watchdog-owned state; audio callbacks only increment atomic counters.
    private var observedCapture = 0, observedRender = 0
    private var captureProgressAt: TimeInterval, renderProgressAt: TimeInterval
    // Consumer-owned state.
    private var position = 0, fraction = 0.0
    private var primed = false, gain: Float = 0, last: Float = 0
    private var filteredDepth = Double(target)

    init(now: TimeInterval = ProcessInfo.processInfo.systemUptime) {
        captureProgressAt = now; renderProgressAt = now
        samples.initialize(repeating: 0, count: Self.capacity)
    }
    deinit { samples.deallocate() }
    var underruns: Int { underrunCount.load(ordering: .relaxed) }
    var overflows: Int { overflowCount.load(ordering: .relaxed) }
    var queuedFrames: Int { max(0, written.load(ordering: .acquiring) - consumed.load(ordering: .acquiring)) }

    func processingHealthy(at now: TimeInterval = ProcessInfo.processInfo.systemUptime) -> Bool {
        let capture = captureFrames.load(ordering: .relaxed), render = renderFrames.load(ordering: .relaxed)
        if capture != observedCapture { observedCapture = capture; captureProgressAt = now }
        if render != observedRender { observedRender = render; renderProgressAt = now }
        // Silence still produces frames. Missing processing, not sample amplitude,
        // triggers recovery after the same three-second grace on both platforms.
        return now - captureProgressAt < 3 && now - renderProgressAt < 3
    }

    @discardableResult func append(_ input: UnsafePointer<Float>, count: Int) -> Bool {
        guard count > 0 else { return true }
        _ = captureFrames.wrappingAdd(count, ordering: .relaxed)
        let head = written.load(ordering: .relaxed)
        guard count <= Self.capacity - (head - consumed.load(ordering: .acquiring)) else {
            _ = overflowCount.wrappingAdd(1, ordering: .relaxed)
            resync.store(true, ordering: .releasing)
            return false
        }
        for i in 0..<count { samples[(head + i) & (Self.capacity - 1)] = input[i].isFinite ? input[i] : 0 }
        written.store(head + count, ordering: .releasing)
        return true
    }

    func render(_ output: UnsafeMutablePointer<Float>, count: Int) {
        let head = written.load(ordering: .acquiring)
        if resync.exchange(false, ordering: .acquiringAndReleasing) {
            position = head; fraction = 0; primed = false; gain = 0
        }
        if !primed && head - position >= Self.target {
            primed = true; filteredDepth = Double(Self.target)
        }
        // USB input and output devices have independent clocks. A small,
        // smoothed rate correction keeps latency stable without dropping blocks.
        filteredDepth += (Double(head - position) - filteredDepth) * min(1, Double(count) / 48000)
        let step = 1 + min(0.003, max(-0.003, (filteredDepth - Double(Self.target)) / 96000))
        for i in 0..<count {
            if primed && position + 1 < head {
                let a = samples[position & (Self.capacity - 1)]
                let b = samples[(position + 1) & (Self.capacity - 1)]
                gain = min(1, gain + 1 / 128)
                last = (a + (b - a) * Float(fraction)) * gain
                fraction += step
                let advance = Int(fraction); position += advance; fraction -= Double(advance)
            } else {
                if primed {
                    _ = underrunCount.wrappingAdd(1, ordering: .relaxed)
                    position = head // Do not join a stale last sample to a new segment.
                }
                primed = false; gain = 0; fraction = 0
                last *= 0.98
                if abs(last) < 0.000001 { last = 0 }
            }
            output[i] = last
        }
        consumed.store(position, ordering: .releasing)
        if count > 0 { _ = renderFrames.wrappingAdd(count, ordering: .relaxed) }
    }
}
