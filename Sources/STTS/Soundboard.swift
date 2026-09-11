import Foundation
import AVFoundation
import Combine

struct SoundboardClip: Codable, Identifiable, Equatable {
    let id: UUID
    let name, file: String
    let duration: Double
}

@MainActor final class SoundboardLibrary: ObservableObject {
    @Published private(set) var clips: [SoundboardClip] = []
    private(set) var loadError: String?
    let folder: URL
    private var manifest: URL { folder.appendingPathComponent("clips.json") }

    init(folder: URL = AppPaths.support.appendingPathComponent("Soundboard", isDirectory: true)) {
        self.folder = folder
        guard FileManager.default.fileExists(atPath: manifest.path) else { return }
        do {
            let loaded = try JSONDecoder().decode([SoundboardClip].self, from: Data(contentsOf: manifest))
            guard loaded.allSatisfy({ $0.file == URL(fileURLWithPath: $0.file).lastPathComponent && $0.file.hasPrefix($0.id.uuidString + ".") }) else {
                throw AppFailure("사운드보드 파일 목록이 올바르지 않습니다.")
            }
            clips = loaded
        } catch { loadError = error.localizedDescription }
    }

    func audioURL(_ clip: SoundboardClip) -> URL { folder.appendingPathComponent(clip.file) }

    func clip(forInput input: String) throws -> SoundboardClip? {
        let name = input.trimmingCharacters(in: .whitespacesAndNewlines)
        let matches = clips.filter { $0.name.trimmingCharacters(in: .whitespacesAndNewlines) == name }
        guard let clip = matches.first else { return nil }
        guard matches.count == 1 else { throw AppFailure("같은 이름의 사운드가 여러 개 있습니다. 사운드보드에서 선택해 주세요.") }
        return clip
    }

    private func save(_ items: [SoundboardClip]) throws {
        if let loadError { throw AppFailure(loadError) }
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        try JSONEncoder().encode(items).write(to: manifest, options: .atomic)
    }

    @discardableResult func importAudio(_ source: URL, phraseNames: [String] = []) throws -> SoundboardClip {
        if let loadError { throw AppFailure(loadError) }
        let name = source.deletingPathExtension().lastPathComponent.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { throw AppFailure("사운드 이름이 비어 있습니다.") }
        guard !clips.contains(where: { $0.name.trimmingCharacters(in: .whitespacesAndNewlines) == name }),
              !phraseNames.contains(where: { $0.trimmingCharacters(in: .whitespacesAndNewlines) == name }) else {
            throw AppFailure("이미 사용 중인 이름입니다. 파일 이름을 바꾼 뒤 추가해 주세요.")
        }
        let audio = try AVAudioFile(forReading: source)
        let duration = Double(audio.length) / audio.processingFormat.sampleRate
        guard duration.isFinite, duration > 0 else { throw AppFailure("재생할 수 있는 음성 파일을 선택해 주세요.") }
        let id = UUID()
        let clip = SoundboardClip(id: id, name: name,
                                  file: id.uuidString + "." + (source.pathExtension.isEmpty ? "caf" : source.pathExtension.lowercased()), duration: duration)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let destination = audioURL(clip)
        try FileManager.default.copyItem(at: source, to: destination)
        do { try save(clips + [clip]) }
        catch { try? FileManager.default.removeItem(at: destination); throw error }
        clips.append(clip)
        return clip
    }

    func remove(_ clip: SoundboardClip) throws {
        guard clips.contains(where: { $0.id == clip.id }) else { return }
        let remaining = clips.filter { $0.id != clip.id }
        try save(remaining)
        do {
            let url = audioURL(clip)
            if FileManager.default.fileExists(atPath: url.path) { try FileManager.default.removeItem(at: url) }
        } catch { try? save(clips); throw error }
        clips = remaining
    }
}
