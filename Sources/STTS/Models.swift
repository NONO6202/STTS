import Foundation
import CryptoKit

struct AppFailure: LocalizedError {
    let message: String
    init(_ message: String) { self.message = message }
    var errorDescription: String? { message }
}

enum ResourceLevel: String, CaseIterable, Identifiable, Codable {
    case automatic = "자동", minimum = "최저", low = "하", medium = "중", high = "상", maximum = "최상"
    var id: String { rawValue }
    static let specifications: [ResourceLevel] = [.minimum, .low, .medium, .high, .maximum]
    static let ttsSpecifications: [ResourceLevel] = [.minimum, .low, .medium, .high]
    var ttsLabel: String { switch self { case .minimum: return "기본"; case .low: return "낮음"; case .medium: return "중간"; default: return "높음" } }
    static let sttSpecifications: [ResourceLevel] = [.medium, .low, .high]
    var sttLabel: String { switch self { case .low: return "낮음"; case .high: return "높음"; default: return "기본" } }
    var resolved: ResourceLevel {
        guard self == .automatic else { return self }
        let ram = ProcessInfo.processInfo.physicalMemory / 1_073_741_824
        return ram < 12 ? .minimum : (ram < 24 ? .low : .medium)
    }
    var threads: Int { switch resolved { case .minimum, .low: return 1; case .maximum: return 3; default: return 2 } }
    var chunkSeconds: Double { switch resolved { case .minimum: return 5; case .low: return 4; case .medium: return 3; case .high: return 2.5; default: return 2 } }
    var ttsMemoryMB: Int { switch resolved { case .minimum: return 3072; case .low: return 4096; case .medium: return 4608; case .high: return 6144; default: return 7168 } }
}

struct ModelAsset: Sendable {
    let name: String
    let file: String
    let repo: String
    let revision: String
    let bytes: Int64
    let sha256: String
    var sourceFile: String? = nil
    static let vad = ModelAsset(name: "Silero 음성 감지", file: "ggml-silero-v6.2.0.bin", repo: "ggml-org/whisper-vad", revision: "9ffd54a1e1ee413ddf265af9913beaf518d1639b", bytes: 885098, sha256: "2aa269b785eeb53a82983a20501ddf7c1d9c48e33ab63a41391ac6c9f7fb6987")
    var remote: URL { URL(string: "https://huggingface.co/\(repo)/resolve/\(revision)/\(sourceFile ?? file)")! }
    var local: URL { AppPaths.models.appendingPathComponent(file) }
    var available: Bool {
        (try? local.resourceValues(forKeys: [.fileSizeKey]).fileSize) == Int(bytes)
    }
}

enum AppPaths {
    static var support: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("STTS", isDirectory: true)
    }
    static var models: URL { support.appendingPathComponent("Models", isDirectory: true) }
    static var temporary: URL { FileManager.default.temporaryDirectory.appendingPathComponent("STTS-\(ProcessInfo.processInfo.processIdentifier)", isDirectory: true) }
    static func prepare() throws {
        for url in [support, models, temporary] { try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700]) }
    }
}

enum AssetDownloader {
    static func prepare(_ asset: ModelAsset, progress: @escaping @Sendable (String) -> Void) async throws {
        try AppPaths.prepare()
        let access = try ModelStorageAccess(root: AppPaths.models)
        defer { withExtendedLifetime(access) {} }
        try FileManager.default.createDirectory(at: asset.local.deletingLastPathComponent(), withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        if asset.available { progress("\(asset.name) 확인 중…") }
        else {
            progress("\(asset.name) 다운로드 중 · \(asset.bytes / 1_000_000) MB")
            let configuration = URLSessionConfiguration.ephemeral
            configuration.timeoutIntervalForResource = 900
            let session = URLSession(configuration: configuration)
            defer { session.invalidateAndCancel() }
            let (temporary, response) = try await session.download(from: asset.remote)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200 else { throw AppFailure("모델 다운로드에 실패했습니다.") }
            defer { try? FileManager.default.removeItem(at: temporary) }
            guard try valid(temporary, asset: asset) else { throw AppFailure("다운로드한 모델의 무결성이 맞지 않습니다. 다시 준비해 주세요.") }
            try Task.checkCancellation()
            if FileManager.default.fileExists(atPath: asset.local.path) { try FileManager.default.removeItem(at: asset.local) }
            try FileManager.default.moveItem(at: temporary, to: asset.local)
        }
        guard try valid(asset.local, asset: asset) else { throw AppFailure("모델 파일이 손상되었습니다. 모델 폴더에서 해당 파일을 지우고 다시 준비해 주세요.") }
    }
    static func valid(_ url: URL, asset: ModelAsset) throws -> Bool {
        guard try url.resourceValues(forKeys: [.fileSizeKey]).fileSize == Int(asset.bytes) else { return false }
        let input = try FileHandle(forReadingFrom: url)
        defer { try? input.close() }
        var hash = SHA256()
        while try autoreleasepool(invoking: { () throws -> Bool in
            guard let chunk = try input.read(upToCount: 1_048_576), !chunk.isEmpty else { return false }
            hash.update(data: chunk); return true
        }) {}
        return hash.finalize().map { String(format: "%02x", $0) }.joined() == asset.sha256
    }
}

struct Caption: Identifiable, Sendable {
    let id: UUID
    let text: String
    let start: Double
    let end: Double
    var speaker: String
    let duration: Double
    init(text: String, start: Double, end: Double, speaker: String = "수신 음성", duration: Double = 0) {
        self.id = UUID(); self.text = text; self.start = start; self.end = end; self.speaker = speaker; self.duration = duration
    }
}

struct SpeechChunk: Sendable { let samples: [Float]; let start: Double; let end: Double }

/// Timing stays in the original capture clock, including silence. No overlapping ASR windows.
struct SpeechSegmenter {
    let maximumSeconds: Double
    init(maximumSeconds: Double) { self.maximumSeconds = maximumSeconds }
    private(set) var clock: Int = 0
    private var prefix: [Float] = []
    private var speech: [Float] = []
    private var start = 0
    private var silence = 0
    private var voiced = 0
    mutating func feed(_ samples: [Float], probability: Float) -> SpeechChunk? {
        defer { clock += samples.count }
        if speech.isEmpty {
            guard probability >= 0.5 else {
                prefix.append(contentsOf: samples)
                if prefix.count > 3200 { prefix.removeFirst(prefix.count - 3200) }
                return nil
            }
            start = clock - prefix.count
            speech = prefix
            prefix.removeAll(keepingCapacity: true)
        }
        speech.append(contentsOf: samples)
        if probability >= 0.35 { voiced += samples.count; silence = 0 } else { silence += samples.count }
        if silence >= 6400 || speech.count >= Int(maximumSeconds * 16000) { return flush() }
        return nil
    }
    mutating func flush() -> SpeechChunk? {
        defer { speech.removeAll(keepingCapacity: true); silence = 0; voiced = 0 }
        guard voiced >= 1600 else { return nil }
        return SpeechChunk(samples: speech, start: Double(start) / 16000, end: Double(start + speech.count) / 16000)
    }
}
