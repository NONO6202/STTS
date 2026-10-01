import Foundation
import Testing
@testable import STTS

struct MicrophoneEffectsTests {
    private func tone(_ frequency: Double) -> [Float] {
        (0..<48000).map { Float(0.2 * sin(2 * .pi * frequency * Double($0) / 48000)) }
    }
    private func render(_ input: [Float], pitch: Double = 0, filter: String = "기본", strength: Double = 1, block: Int = 256) -> [Float] {
        let dsp = MicrophoneEffects(); dsp.pitch = pitch; dsp.filter = filter; dsp.strength = strength
        var output = input
        output.withUnsafeMutableBufferPointer { buffer in
            for offset in stride(from: 0, to: input.count, by: block) {
                dsp.process(buffer.baseAddress! + offset, count: min(block, input.count - offset))
            }
        }
        return output
    }
    @Test func neutralAndPitch() {
        let x = tone(440)
        #expect(render(x) == x)
        for (pitch, expected) in [(-12.0, 220.0), (12.0, 880.0)] {
            let y = render(x, pitch: pitch)
            let crossings = (12001..<48000).filter { y[$0 - 1] < 0 && y[$0] >= 0 }.count
            #expect(abs(Double(crossings) / 0.75 - expected) < 3)
            #expect(y.count == x.count)
        }
    }
    @Test func filtersAndVariableBuffers() {
        let x = tone(440)
        for filter in MicrophoneEffects.filters.dropFirst() {
            #expect(render(x, pitch: 7, filter: filter, block: 97) == render(x, pitch: 7, filter: filter, block: 4096))
        }
        func rms(_ frequency: Double) -> Double {
            let y = render(tone(frequency), filter: "전화").dropFirst(12000)
            return sqrt(y.reduce(0) { $0 + Double($1 * $1) } / Double(y.count))
        }
        #expect(rms(60) < rms(1000) * 0.1)
        #expect(rms(10000) < rms(1000) * 0.1)
        #expect(rms(250) < rms(1000) * 0.1)
        #expect(rms(4000) < rms(1000) * 0.2)
        var impulse = [Float](repeating: 0, count: 48000); impulse[12000] = 0.5
        let echo = render(impulse, filter: "에코")
        #expect(abs(echo[22560] - 0.5) < 0.00001)
        #expect(abs(echo[33120] - 0.275) < 0.00001)
    }
    @Test func resetDropsTailsAndInvalidValuesStayFinite() {
        let dsp = MicrophoneEffects(); dsp.filter = "에코"; dsp.pitch = 12
        var samples = tone(440)
        samples.withUnsafeMutableBufferPointer { dsp.process($0.baseAddress!, count: $0.count) }
        dsp.reset(); samples = [Float](repeating: 0, count: 48000)
        samples.withUnsafeMutableBufferPointer { dsp.process($0.baseAddress!, count: $0.count) }
        #expect(samples.allSatisfy { $0 == 0 })
        dsp.pitch = .nan; dsp.strength = .infinity; samples = [.nan, .infinity, -.infinity]
        samples.withUnsafeMutableBufferPointer { dsp.process($0.baseAddress!, count: $0.count) }
        #expect(samples.allSatisfy { $0.isFinite })
    }
    @Test func liveChangesAreSmoothed() {
        let dsp = MicrophoneEffects(); dsp.strength = 1
        var samples = [Float](repeating: 0.1, count: 48000)
        samples.withUnsafeMutableBufferPointer { buffer in
            for offset in stride(from: 0, to: buffer.count, by: 256) {
                dsp.pitch = offset > 16000 ? 12 : -12
                dsp.filter = offset > 32000 ? "에코" : "로봇"
                dsp.process(buffer.baseAddress! + offset, count: min(256, buffer.count - offset))
            }
        }
        #expect(zip(samples.dropFirst(12000), samples.dropFirst(12001)).allSatisfy { abs($0 - $1) < 0.02 })
    }
    @Test func fullStrengthAndNewEffects() {
        let input = tone(440)
        for filter in MicrophoneEffects.filters.dropFirst() {
            #expect(render(input, filter: filter, strength: 0) == input)
            let full = render(input, filter: filter)
            let difference = zip(full.dropFirst(12000), input.dropFirst(12000)).reduce(0.0) { $0 + pow(Double($1.0 - $1.1), 2) }
            #expect(difference > 40)
            let loud = render(input.map { $0 * 8 }, filter: filter)
            #expect(loud.allSatisfy { $0.isFinite && abs($0) <= 1 })
        }
        let crushed = render(input, filter: "8비트")
        for i in stride(from: 24000, to: 48000, by: 12) {
            #expect((i..<(i + 12)).allSatisfy { abs(crushed[$0] - crushed[i]) < 0.000001 })
        }
        let tremolo = render(tone(1000), filter: "트레몰로")
        #expect(tremolo[14950..<15050].allSatisfy { abs($0) < 0.00001 })
    }
}
