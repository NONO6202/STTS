import AVFoundation
import Foundation
import Testing
@testable import STTS

@Suite struct SoundboardTests {
    @Test @MainActor func inputsResolveWholeNamesAndRejectAmbiguousNames() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let named = SoundboardClip(id: UUID(), name: "박수 소리", file: "", duration: 1)
        let clips = [named, SoundboardClip(id: UUID(), name: "중복", file: "", duration: 1), SoundboardClip(id: UUID(), name: "중복", file: "", duration: 1)]
            .map { SoundboardClip(id: $0.id, name: $0.name, file: $0.id.uuidString + ".wav", duration: $0.duration) }
        try JSONEncoder().encode(clips).write(to: root.appendingPathComponent("clips.json"))
        let library = SoundboardLibrary(folder: root)
        #expect(try library.clip(forInput: " \n박수 소리 ")?.id == named.id)
        #expect(try library.clip(forInput: "박수 소리".decomposedStringWithCanonicalMapping)?.id == named.id)
        for input in ["", "없는이름", "박수", "박수 소리 들어봐", "@박수 소리", "이메일 user@example.com"] {
            #expect(try library.clip(forInput: input) == nil)
        }
        #expect(throws: AppFailure.self) { try library.clip(forInput: "중복") }
    }

    @Test @MainActor func importingPersistsAnOwnedCopyAndDeletingPreservesTheOriginal() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let source = root.appendingPathComponent("effect.wav")
        let format = try #require(AVAudioFormat(standardFormatWithSampleRate: 24000, channels: 1))
        let buffer = try #require(AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 2400))
        buffer.frameLength = 2400
        for i in 0..<2400 { buffer.floatChannelData![0][i] = Float(sin(Double(i) * 0.1)) * 0.1 }
        do { let file = try AVAudioFile(forWriting: source, settings: format.settings); try file.write(from: buffer) }
        let original = try Data(contentsOf: source)
        let library = SoundboardLibrary(folder: root.appendingPathComponent("library"))
        #expect(throws: AppFailure.self) { try library.importAudio(source, phraseNames: ["effect"]) }
        #expect(library.clips.isEmpty)
        #expect(!FileManager.default.fileExists(atPath: library.folder.path))
        let clip = try library.importAudio(source)
        #expect(throws: AppFailure.self) { try library.importAudio(source) }
        #expect(library.clips == [clip])
        #expect(clip.duration == 0.1)
        #expect(try Data(contentsOf: library.audioURL(clip)) == original)
        #expect(SoundboardLibrary(folder: library.folder).clips == [clip])
        let invalid = root.appendingPathComponent("invalid.wav")
        try Data("invalid".utf8).write(to: invalid)
        #expect(throws: (any Error).self) { try library.importAudio(invalid) }
        #expect(library.clips == [clip])
        try library.remove(clip)
        #expect(SoundboardLibrary(folder: library.folder).clips.isEmpty)
        #expect(!FileManager.default.fileExists(atPath: library.audioURL(clip).path))
        #expect(try Data(contentsOf: source) == original)
    }

    @Test @MainActor func malformedManifestCannotRedirectDeletionOutsideTheLibrary() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let clip = SoundboardClip(id: UUID(), name: "outside", file: "../outside.wav", duration: 1)
        let data = try JSONEncoder().encode([clip])
        let manifest = root.appendingPathComponent("clips.json")
        try data.write(to: manifest)
        let library = SoundboardLibrary(folder: root)
        #expect(library.loadError != nil)
        #expect(library.clips.isEmpty)
        #expect(try Data(contentsOf: manifest) == data)
    }
}
