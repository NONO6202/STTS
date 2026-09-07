import Foundation
import Testing
@testable import STTS

@Suite struct ModelStorageTests {
    @Test func auxiliaryVADIsHiddenAndQwenVariantsAreNamedExactly() throws {
        let fm = FileManager.default
        let root = fm.temporaryDirectory.appendingPathComponent(UUID().uuidString).resolvingSymlinksInPath()
        defer { try? fm.removeItem(at: root) }
        for key in ["qwen06", "qwen17", "qwen06Custom", "qwen17Custom"] {
            try fm.createDirectory(at: root.appendingPathComponent("MLX/\(key)-123456abcdef"), withIntermediateDirectories: true)
        }
        let vad = root.appendingPathComponent(ModelAsset.vad.file)
        try Data([1]).write(to: vad)
        let models = try ModelStorage.installed(root: root)
        #expect(Set(models.map(\.name)) == Set(["TTS · Qwen3-TTS 0.6B Base", "TTS · Qwen3-TTS 1.7B Base", "TTS · Qwen3-TTS 0.6B CustomVoice", "TTS · Qwen3-TTS 1.7B CustomVoice"]))
        #expect(fm.fileExists(atPath: vad.path))
    }
    @Test func deletionIsScopedAndBlockedWhileModelsAreInUse() throws {
        let fm = FileManager.default
        let root = fm.temporaryDirectory.appendingPathComponent(UUID().uuidString).resolvingSymlinksInPath()
        defer { try? fm.removeItem(at: root) }
        let modelURL = root.appendingPathComponent("MLX/base-123456abcdef")
        try fm.createDirectory(at: modelURL, withIntermediateDirectories: true)
        try Data(repeating: 1, count: 128).write(to: modelURL.appendingPathComponent("model.safetensors"))
        let sibling = root.appendingPathComponent("keep.txt")
        try Data("preserve".utf8).write(to: sibling)
        let model = try #require(ModelStorage.installed(root: root).first)
        #expect(model.bytes == 128)
        do {
            let access = try ModelStorageAccess(root: root)
            withExtendedLifetime(access) {
                #expect(throws: AppFailure.self) { try ModelStorage.delete(model, root: root) }
                #expect(fm.fileExists(atPath: modelURL.path))
            }
        }
        try ModelStorage.delete(model, root: root)
        #expect(!fm.fileExists(atPath: modelURL.path))
        #expect(try String(contentsOf: sibling, encoding: .utf8) == "preserve")
    }
    @Test func deletionRejectsTraversalAndExternalSymlinks() throws {
        let fm = FileManager.default
        let base = fm.temporaryDirectory.appendingPathComponent(UUID().uuidString).resolvingSymlinksInPath()
        defer { try? fm.removeItem(at: base) }
        let root = base.appendingPathComponent("Models"), outside = base.appendingPathComponent("Outside")
        try fm.createDirectory(at: root.appendingPathComponent("MLX"), withIntermediateDirectories: true)
        try fm.createDirectory(at: outside, withIntermediateDirectories: true)
        try Data("preserve".utf8).write(to: outside.appendingPathComponent("keep.txt"))
        let link = root.appendingPathComponent("MLX/base-123456abcdef")
        try fm.createSymbolicLink(at: link, withDestinationURL: outside)
        #expect(throws: AppFailure.self) {
            try ModelStorage.delete(DownloadedModel(id: "MLX/base-123456abcdef", name: "link", bytes: 0), root: root)
        }
        #expect(throws: AppFailure.self) {
            try ModelStorage.delete(DownloadedModel(id: "../Outside", name: "escape", bytes: 0), root: root)
        }
        #expect(try ModelStorage.installed(root: root).isEmpty)
        #expect(fm.fileExists(atPath: outside.appendingPathComponent("keep.txt").path))
    }
}
