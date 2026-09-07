import Foundation
import AVFoundation

struct VoiceProfile: Codable, Identifiable, Equatable {
    let id: UUID
    var name: String
    let sourceName: String
    var transcript: String
    static var folder: URL { AppPaths.support.appendingPathComponent("Voice", isDirectory: true) }
    var selection: String { "clone:" + id.uuidString }
    func audioURL(in folder: URL = Self.folder) -> URL { folder.appendingPathComponent(id.uuidString + ".wav") }
    var ready: Bool {
        let text = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        return !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !text.isEmpty && text.count <= 1000
            && FileManager.default.fileExists(atPath: audioURL().path)
    }

    static func importAudio(_ source: URL, into folder: URL = Self.folder) throws -> VoiceProfile {
        let file = try AVAudioFile(forReading: source)
        let duration = Double(file.length) / file.processingFormat.sampleRate
        guard duration.isFinite, (3...30).contains(duration) else { throw AppFailure("음성은 3~30초로 선택해 주세요.") }
        let samples = try AudioFiles.samples(source)
        guard samples.allSatisfy(\.isFinite), samples.contains(where: { abs($0) > 0.001 }) else { throw AppFailure("음성에 들리는 목소리가 없습니다.") }
        let voice = VoiceProfile(id: UUID(), name: source.deletingPathExtension().lastPathComponent, sourceName: source.lastPathComponent, transcript: "")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let temporary = folder.appendingPathComponent(".import-" + voice.id.uuidString + ".wav")
        let destination = voice.audioURL(in: folder)
        var succeeded = false
        defer {
            try? FileManager.default.removeItem(at: temporary)
            if !succeeded { try? FileManager.default.removeItem(at: destination) }
        }
        let format = AVAudioFormat(standardFormatWithSampleRate: 16000, channels: 1)!
        let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(samples.count))!
        buffer.frameLength = buffer.frameCapacity
        samples.withUnsafeBufferPointer { buffer.floatChannelData![0].update(from: $0.baseAddress!, count: samples.count) }
        do { let output = try AVAudioFile(forWriting: temporary, settings: format.settings); try output.write(from: buffer) }
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: temporary.path)
        try FileManager.default.moveItem(at: temporary, to: destination)
        succeeded = true
        return voice
    }
}
