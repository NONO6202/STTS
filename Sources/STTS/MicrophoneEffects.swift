import Foundation

/// Streaming, bounded delay lines; owned exclusively by the capture queue.
final class MicrophoneEffects {
    static let filters = ["기본", "로봇", "전화", "에코", "확성기", "디스토션", "8비트", "트레몰로"]
    var pitch = 0.0
    var filter = "기본"
    var strength = 0.65
    private let rate = 48000.0, window = 2400.0
    private var ring = [Double](repeating: 0, count: 2912)
    private var echo = [Double](repeating: 0, count: 10560)
    private var position = 0, echoPosition = 0, robotPosition = 0
    private var phase = 0.25, ratio = 1.0, pitchMix = 0.0
    private var weights = [Double](repeating: 0, count: MicrophoneEffects.filters.count - 1)
    private var previousFilter = "기본"
    private var echoGate = 0.0
    private let decay = exp(-1.0 / (48000 * 0.015))
    private var phoneEQ = [Biquad(frequency: 550, highPass: true, q: 0.541196100146197),
                           Biquad(frequency: 550, highPass: true, q: 1.306562964876377),
                           Biquad(frequency: 2300, highPass: false, q: 0.541196100146197),
                           Biquad(frequency: 2300, highPass: false, q: 1.306562964876377)]
    private var megaphoneEQ = [Biquad(frequency: 400, highPass: true), Biquad(frequency: 4000, highPass: false)]
    private var crushHold = 0.0

    func reset() {
        ring = [Double](repeating: 0, count: ring.count)
        echo = [Double](repeating: 0, count: echo.count)
        position = 0; echoPosition = 0; robotPosition = 0
        phase = 0.25; ratio = 1; pitchMix = 0; weights = [Double](repeating: 0, count: weights.count)
        echoGate = 0
        for i in phoneEQ.indices { phoneEQ[i].reset() }
        for i in megaphoneEQ.indices { megaphoneEQ[i].reset() }
        crushHold = 0; previousFilter = "기본"
    }

    func process(_ samples: UnsafeMutablePointer<Float>, count: Int) {
        let semitones = pitch.isFinite ? min(12, max(-12, pitch)) : 0
        let amount = strength.isFinite ? min(1, max(0, strength)) : 0
        if filter != previousFilter {
            if filter == "에코" { for i in echo.indices { echo[i] = 0 }; echoGate = 0 }
            if filter == "전화" { for i in phoneEQ.indices { phoneEQ[i].reset() } }
            if filter == "확성기" { for i in megaphoneEQ.indices { megaphoneEQ[i].reset() } }
            previousFilter = filter
        }
        // Keep the delay history ready for live pitch/filter changes, but avoid
        // interpolation and trigonometry while the microphone is unprocessed.
        if semitones == 0, ratio == 1, pitchMix == 0, filter == "기본", echoGate == 0,
           weights.allSatisfy({ $0 == 0 }) {
            for i in 0..<count {
                let x = samples[i].isFinite ? Double(samples[i]) : 0
                ring[position] = x; echo[echoPosition] = 0
                samples[i] = Float(min(1, max(-1, x)))
                position = (position + 1) % ring.count; echoPosition = (echoPosition + 1) % echo.count
                robotPosition = (robotPosition + 1) % Int(rate)
            }
            return
        }
        let targetRatio = pow(2, semitones / 12), targetMix = abs(semitones) > 0.001 ? 1.0 : 0.0
        let targets = Self.filters.dropFirst().map { $0 == filter ? amount : 0 }
        for i in 0..<count {
            var x = samples[i].isFinite ? Double(samples[i]) : 0
            ring[position] = x
            ratio = targetRatio + (ratio - targetRatio) * decay
            phase += (1 - ratio) / window; phase -= floor(phase)
            let blend = pow(sin(.pi * phase), 2)
            let shifted = read(phase) * blend + read((phase + 0.5).truncatingRemainder(dividingBy: 1)) * (1 - blend)
            pitchMix = targetMix + (pitchMix - targetMix) * decay
            x += (shifted - x) * pitchMix
            for j in weights.indices { weights[j] = targets[j] + (weights[j] - targets[j]) * decay }
            var y = x
            let clock = Double(robotPosition) / rate
            if weights[0] > 1e-6 {
                let robot = 0.65 * tanh(6 * x) * cos(2 * .pi * 80 * clock)
                y += weights[0] * (robot - x)
            }
            if weights[1] > 1e-6 {
                var telephone = x
                for j in phoneEQ.indices { telephone = phoneEQ[j].process(telephone) }
                y += weights[1] * (0.7 * tanh(4 * telephone) - x)
            }
            if weights[3] > 1e-6 {
                var megaphone = x
                for j in megaphoneEQ.indices { megaphone = megaphoneEQ[j].process(megaphone) }
                y += weights[3] * (0.65 * tanh(16 * megaphone) - x)
            }
            if weights[4] > 1e-6 { y += weights[4] * (0.7 * tanh(18 * x) - x) }
            if weights[5] > 1e-6 {
                if robotPosition % 12 == 0 { crushHold = (0.7 * tanh(4 * x) * 127).rounded(.toNearestOrEven) / 127 }
                y += weights[5] * (crushHold - x)
            }
            if weights[6] > 1e-6 {
                let tremolo = x * pow(0.5 + 0.5 * cos(2 * .pi * 8 * clock), 3)
                y += weights[6] * (tremolo - x)
            }
            let delayed = echo[echoPosition]
            let gateTarget = filter == "에코" ? 1.0 : 0.0
            echoGate = gateTarget + (echoGate - gateTarget) * decay
            echo[echoPosition] = filter == "에코" || weights[2] > 1e-6 ? x * echoGate + 0.55 * delayed : 0
            // At full strength the first repeat is as loud as the original.
            y += weights[2] * delayed
            samples[i] = Float(min(1, max(-1, y)))
            position = (position + 1) % ring.count; echoPosition = (echoPosition + 1) % echo.count
            robotPosition = (robotPosition + 1) % Int(rate)
        }
    }

    private func read(_ phase: Double) -> Double {
        let location = Double(position + ring.count) - 129 - phase * window
        let base = Int(floor(location)), fraction = location - floor(location)
        return ring[base % ring.count] * (1 - fraction) + ring[(base + 1) % ring.count] * fraction
    }

    private struct Biquad {
        let b0: Double, b1: Double, b2: Double, a1: Double, a2: Double
        var z1 = 0.0, z2 = 0.0
        init(frequency: Double, highPass: Bool, q: Double = sqrt(0.5)) {
            let omega = 2 * Double.pi * frequency / 48000, c = cos(omega), alpha = sin(omega) / (2 * q)
            let a0 = 1 + alpha, b = highPass ? (1 + c) / 2 : (1 - c) / 2
            b0 = b / a0; b1 = (highPass ? -2 : 2) * b / a0; b2 = b / a0
            a1 = -2 * c / a0; a2 = (1 - alpha) / a0
        }
        mutating func process(_ x: Double) -> Double {
            let y = b0 * x + z1
            z1 = b1 * x - a1 * y + z2; z2 = b2 * x - a2 * y
            return y
        }
        mutating func reset() { z1 = 0; z2 = 0 }
    }
}
