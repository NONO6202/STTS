import Foundation
import AVFoundation
import Testing
@testable import STTS

struct MicrophoneBufferTests {
    private func append(_ values: [Float], to buffer: MicrophoneBuffer) -> Bool {
        values.withUnsafeBufferPointer { buffer.append($0.baseAddress!, count: $0.count) }
    }
    private func render(_ count: Int, from buffer: MicrophoneBuffer) -> [Float] {
        var output = [Float](repeating: .nan, count: count)
        output.withUnsafeMutableBufferPointer { buffer.render($0.baseAddress!, count: count) }
        return output
    }
    @Test func startupGraceExpiresWhenProcessingNeverStarts() {
        let buffer = MicrophoneBuffer(now: 10)
        #expect(buffer.processingHealthy(at: 12.99))
        #expect(!buffer.processingHealthy(at: 13))
    }
    @Test func silentFramesKeepBothDirectionsHealthy() {
        let buffer = MicrophoneBuffer(now: 10)
        for tick in 1...20 {
            #expect(append([Float](repeating: 0, count: 480), to: buffer))
            #expect(render(480, from: buffer).allSatisfy { $0 == 0 })
            #expect(buffer.processingHealthy(at: 10 + Double(tick) / 2))
        }
    }
    @Test(arguments: [true, false]) func stalledDirectionExpiresWhileOtherDirectionKeepsProcessing(captureStalls: Bool) {
        let buffer = MicrophoneBuffer(now: 10)
        for tick in 1...8 {
            if captureStalls { _ = render(480, from: buffer) }
            else { #expect(append([Float](repeating: 0, count: 480), to: buffer)) }
            let elapsed = Double(tick) / 2
            #expect(buffer.processingHealthy(at: 10 + elapsed) == (elapsed < 3))
        }
        #expect(MicrophoneBuffer(now: 14).processingHealthy(at: 14))
    }
    @Test func primesBeforePlaybackAndSanitizesInput() {
        let buffer = MicrophoneBuffer()
        #expect(append([Float](repeating: 0.4, count: 480), to: buffer))
        #expect(render(480, from: buffer).allSatisfy { $0 == 0 })
        #expect(append([Float](repeating: 0.4, count: MicrophoneBuffer.target), to: buffer))
        let output = render(480, from: buffer)
        #expect(output.allSatisfy { $0.isFinite })
        #expect(abs(output.last! - 0.4) < 0.00001)
        #expect(zip(output, output.dropFirst()).allSatisfy { abs($0 - $1) < 0.004 })
        #expect(append([.nan, .infinity, -.infinity], to: buffer))
        #expect(render(5000, from: buffer).allSatisfy { $0.isFinite })
    }
    @Test func starvationFadesAndRebuffersInsteadOfClicking() {
        let buffer = MicrophoneBuffer()
        #expect(append([Float](repeating: 1, count: MicrophoneBuffer.target), to: buffer))
        let output = render(6000, from: buffer)
        #expect(buffer.underruns == 1)
        #expect(output.last == 0)
        #expect(zip(output, output.dropFirst()).allSatisfy { abs($0 - $1) <= 0.021 })
        #expect(append([Float](repeating: -1, count: 480), to: buffer))
        #expect(render(480, from: buffer).allSatisfy { $0 == 0 })
        #expect(append([Float](repeating: -1, count: MicrophoneBuffer.target), to: buffer))
        let recovered = render(480, from: buffer)
        #expect(abs(recovered.last! + 1) < 0.00001)
        #expect(zip(recovered, recovered.dropFirst()).allSatisfy { abs($0 - $1) < 0.009 })
    }
    @Test func stalledOutputRecoversWithoutAnUnboundedBacklog() {
        let buffer = MicrophoneBuffer()
        #expect(append([Float](repeating: 0.5, count: MicrophoneBuffer.capacity), to: buffer))
        #expect(!append([1], to: buffer))
        #expect(render(480, from: buffer).allSatisfy { $0 == 0 })
        #expect(buffer.queuedFrames == 0 && buffer.overflows == 1)
        #expect(append([Float](repeating: -0.5, count: MicrophoneBuffer.target), to: buffer))
        #expect(abs(render(480, from: buffer).last! + 0.5) < 0.00001)
    }
    @Test func sourceNodeConverts48kInputTo44100Output() throws {
        let buffer = MicrophoneBuffer(), engine = AVAudioEngine()
        let sourceFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 48000, channels: 1, interleaved: false)!
        let outputFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 44100, channels: 1, interleaved: false)!
        let source = MicrophonePassthrough.sourceNode(buffer: buffer, format: sourceFormat)
        engine.attach(source); engine.connect(source, to: engine.mainMixerNode, format: sourceFormat)
        try engine.enableManualRenderingMode(.offline, format: outputFormat, maximumFrameCount: 441)
        let output = AVAudioPCMBuffer(pcmFormat: engine.manualRenderingFormat, frameCapacity: 441)!
        #expect(append([Float](repeating: 0.25, count: MicrophoneBuffer.target), to: buffer))
        try engine.start(); defer { engine.stop() }
        for block in 0..<1000 {
            #expect(append([Float](repeating: 0.25, count: 480), to: buffer))
            #expect(try engine.renderOffline(441, to: output) == .success)
            if block > 10 {
                let samples = UnsafeBufferPointer(start: output.floatChannelData![0], count: Int(output.frameLength))
                #expect(samples.allSatisfy { $0.isFinite && $0 > 0.1 && $0 < 0.3 })
            }
        }
        #expect(buffer.underruns == 0 && buffer.overflows == 0)
    }
    @Test(arguments: [-0.001, 0.001]) func independentClocksAndJitterRemainContinuous(drift: Double) {
        let buffer = MicrophoneBuffer()
        var input = [Float](repeating: 0, count: 480), output = input
        var nextCapture = 0.0, captureBlock = 0, sample = 0
        var previous: Float = 0, largestJump: Float = 0
        var maximumQueue = 0, rejected = 0
        // Ten simulated minutes; +/-1000 ppm is deliberately larger than
        // ordinary device clock drift. Delivery alternates between 2 and 18 ms.
        for block in 0..<60000 {
            while nextCapture <= Double(block) * 0.01 {
                for i in input.indices { input[i] = Float(0.25 * sin(2 * .pi * 440 * Double(sample + i) / 48000)) }
                sample += input.count
                if !append(input, to: buffer) { rejected += 1 }
                nextCapture += (0.01 + (captureBlock.isMultiple(of: 2) ? 0.008 : -0.008)) / (1 + drift)
                captureBlock += 1
            }
            maximumQueue = max(maximumQueue, buffer.queuedFrames)
            output.withUnsafeMutableBufferPointer { buffer.render($0.baseAddress!, count: $0.count) }
            for value in output { largestJump = max(largestJump, abs(value - previous)); previous = value }
        }
        #expect(rejected == 0 && buffer.underruns == 0 && buffer.overflows == 0)
        #expect(maximumQueue < MicrophoneBuffer.target + 1920)
        #expect(buffer.queuedFrames > 480)
        #expect(largestJump < 0.025)
    }
}
