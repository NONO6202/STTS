import Foundation
import Darwin

/// Shared by model readers/downloaders; deletion requires exclusive access.
final class ModelStorageAccess {
    private var descriptor: Int32
    init(root: URL, exclusive: Bool = false) throws {
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        descriptor = Darwin.open(root.appendingPathComponent(".model-access.lock").path, O_CREAT | O_RDWR | O_NOFOLLOW, 0o600)
        guard descriptor >= 0 else { throw AppFailure("모델 저장소를 열 수 없습니다.") }
        guard flock(descriptor, (exclusive ? LOCK_EX : LOCK_SH) | LOCK_NB) == 0 else {
            Darwin.close(descriptor)
            descriptor = -1
            throw AppFailure("모델 파일을 사용 중입니다. 다운로드나 삭제가 끝난 뒤 다시 시도해 주세요.")
        }
    }
    deinit { if descriptor >= 0 { flock(descriptor, LOCK_UN); Darwin.close(descriptor) } }
}

struct DownloadedModel: Identifiable, Sendable {
    let id: String
    let name: String
    let bytes: Int64
    var sizeLabel: String { ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file) }
}

enum ModelStorage {
    private static let names = [
        "base": "STT · Whisper Base", "small": "STT · Whisper Small",
        "turbo": "STT · Whisper Large-v3-Turbo", "large": "STT · Whisper Large-v3", "nemotron": "STT · Nemotron 3.5 ASR 0.6B",
        "asr06": "STT · Qwen3-ASR 0.6B", "asr17": "STT · Qwen3-ASR 1.7B",
        "qwen06": "TTS · Qwen3-TTS 0.6B Base", "qwen17": "TTS · Qwen3-TTS 1.7B Base",
        "supertonic3": "TTS · Supertonic 3",
        "qwen06Custom": "TTS · Qwen3-TTS 0.6B CustomVoice", "qwen17Custom": "TTS · Qwen3-TTS 1.7B CustomVoice",
        "chatter": "TTS · Chatterbox (이전 모델)", "chatterV3": "TTS · Chatterbox Multilingual V3", "vox": "TTS · VoxCPM2"
    ]
    private static func name(for id: String) -> String? {
        if id == "Speakers" { return "이전 화자 구분 모델" }
        if id == ModelAsset.vad.file { return "STT 공용 · Silero 음성 감지" }
        if id == "ggml-large-v3-turbo-q5_0.bin" { return "STT · Whisper Turbo (이전 모델)" }
        let parts = id.split(separator: "/", omittingEmptySubsequences: false)
        guard parts.count == 2, parts[0] == "MLX",
              let separator = parts[1].lastIndex(of: "-") else { return nil }
        let key = String(parts[1][..<separator]), revision = parts[1][parts[1].index(after: separator)...]
        guard revision.count == 12, revision.allSatisfy({ $0.isHexDigit }) else { return nil }
        return names[key]
    }
    static func location(of model: DownloadedModel, root: URL = AppPaths.models) throws -> URL {
        guard name(for: model.id) != nil else { throw AppFailure("삭제할 모델 경로가 올바르지 않습니다.") }
        let root = root.standardizedFileURL
        let url = root.appendingPathComponent(model.id).standardizedFileURL
        guard root.resolvingSymlinksInPath().path == root.path,
              url.resolvingSymlinksInPath().path == url.path,
              url.path.hasPrefix(root.path + "/") else { throw AppFailure("연결된 외부 폴더는 삭제하지 않습니다.") }
        return url
    }
    static func installed(root: URL = AppPaths.models) throws -> [DownloadedModel] {
        let fm = FileManager.default
        guard fm.fileExists(atPath: root.path) else { return [] }
        let children = try fm.contentsOfDirectory(at: root, includingPropertiesForKeys: nil, options: .skipsHiddenFiles)
        var ids = children.filter { $0.lastPathComponent != "MLX" }.map(\.lastPathComponent)
        let mlx = root.appendingPathComponent("MLX")
        if fm.fileExists(atPath: mlx.path), mlx.resolvingSymlinksInPath().path == mlx.standardizedFileURL.path {
            ids += try fm.contentsOfDirectory(at: mlx, includingPropertiesForKeys: nil, options: .skipsHiddenFiles).map { "MLX/" + $0.lastPathComponent }
        }
        return try ids.compactMap { id in
            guard id != ModelAsset.vad.file, let name = name(for: id) else { return nil }
            let model = DownloadedModel(id: id, name: name, bytes: 0)
            guard let url = try? location(of: model, root: root) else { return nil }
            let keys: Set<URLResourceKey> = [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey]
            var bytes: Int64 = 0
            let entries = [url] + ((fm.enumerator(at: url, includingPropertiesForKeys: Array(keys))?.allObjects as? [URL]) ?? [])
            for entry in entries {
                let values = try entry.resourceValues(forKeys: keys)
                if values.isRegularFile == true, values.isSymbolicLink != true { bytes += Int64(values.fileSize ?? 0) }
            }
            return DownloadedModel(id: id, name: name, bytes: bytes)
        }.sorted { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
    }
    static func delete(_ model: DownloadedModel, root: URL = AppPaths.models) throws {
        let url = try location(of: model, root: root)
        let access = try ModelStorageAccess(root: root, exclusive: true)
        try withExtendedLifetime(access) { try FileManager.default.removeItem(at: url) }
    }
}
