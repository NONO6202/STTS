import Foundation
import AVFoundation
import Testing
@testable import STTS

@Suite struct VoiceProfileTests {
    @Test func importsMultipleClipsWithoutOverwritingTheSourceOrEachOther() throws {
        let temporary = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: temporary, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: temporary) }
        let source = temporary.appendingPathComponent("voice.wav")
        let format = AVAudioFormat(standardFormatWithSampleRate: 48000, channels: 1)!
        let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 48000 * 4)!
        buffer.frameLength = buffer.frameCapacity
        for frame in 0..<Int(buffer.frameLength) {
            buffer.floatChannelData![0][frame] = Float(sin(2 * Double.pi * 440 * Double(frame) / 48000) * 0.1)
        }
        do {
            let file = try AVAudioFile(forWriting: source, settings: format.settings)
            try file.write(from: buffer)
        }
        let original = try Data(contentsOf: source)
        let folder = temporary.appendingPathComponent("imports")
        let first = try VoiceProfile.importAudio(source, into: folder)
        let second = try VoiceProfile.importAudio(source, into: folder)
        #expect(first.id != second.id && first.audioURL(in: folder) != second.audioURL(in: folder))
        #expect(first.sourceName == "voice.wav" && first.name == "voice")
        for voice in [first, second] {
            let audio = try AVAudioFile(forReading: voice.audioURL(in: folder))
            #expect(audio.processingFormat.sampleRate == 16000 && audio.processingFormat.channelCount == 1)
            #expect(audio.length >= 16000 * 3 && audio.length <= 16000 * 5)
            #expect(try AudioFiles.samples(voice.audioURL(in: folder)).contains { abs($0) > 0.001 })
        }
        #expect(try Data(contentsOf: source) == original)
        let saved = try JSONEncoder().encode([first, second])
        #expect(try JSONDecoder().decode([VoiceProfile].self, from: saved) == [first, second])
    }
}
