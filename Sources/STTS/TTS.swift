import Foundation
import Darwin

/// Owns exactly one child process. Cancellation cannot target another request.
final class SpeechRequest: @unchecked Sendable {
    private let lock = NSLock()
    private var process: Process?
    private var cancelled = false
    func cancel() {
        lock.lock(); defer { lock.unlock() }
        cancelled = true
        if let process, process.isRunning { kill(process.processIdentifier, SIGKILL) }
    }
    func synthesize(text: String, language: String) async throws -> URL {
        try await withTaskCancellationHandler {
            try await Task.detached(priority: .utility) { try self.run(text: text, language: language) }.value
        } onCancel: { self.cancel() }
    }
    private func run(text: String, language: String) throws -> URL {
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, text.count <= 500 else { throw AppFailure("1~500자 이내로 입력해 주세요.") }
        try AppPaths.prepare()
        let output = AppPaths.temporary.appendingPathComponent(UUID().uuidString + ".mp3")
        var succeeded = false
        defer { if !succeeded { try? FileManager.default.removeItem(at: output) } }
        let child = Process()
        let bundled = Bundle.main.resourceURL?.appendingPathComponent("gtts-worker/gtts-worker")
        if let bundled, FileManager.default.isExecutableFile(atPath: bundled.path) { child.executableURL = bundled }
        else {
            let root = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
            child.executableURL = root.appendingPathComponent(".venv/bin/python")
            child.arguments = [root.appendingPathComponent("Support/gtts_worker.py").path]
        }
        let input = Pipe()
        child.standardInput = input
        child.standardOutput = FileHandle.nullDevice
        child.standardError = FileHandle.nullDevice
        let request = try JSONSerialization.data(withJSONObject: ["text": text, "language": language, "output": output.path])
        lock.lock()
        if cancelled { lock.unlock(); throw CancellationError() }
        do { try child.run(); process = child; lock.unlock() }
        catch { lock.unlock(); throw AppFailure("gTTS 실행 파일이 없습니다. 앱을 다시 빌드해 주세요.") }
        let deadline = DispatchWorkItem { [weak self] in self?.cancel() }
        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + 30, execute: deadline)
        defer { deadline.cancel(); lock.lock(); process = nil; lock.unlock() }
        try input.fileHandleForWriting.write(contentsOf: request)
        try input.fileHandleForWriting.close()
        child.waitUntilExit()
        lock.lock(); let wasCancelled = cancelled; lock.unlock()
        guard !wasCancelled else { throw AppFailure("음성 생성을 취소했거나 응답 시간 30초를 초과했습니다.") }
        guard child.terminationStatus == 0, (try? output.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0 > 0 else { throw AppFailure("gTTS 음성 생성에 실패했습니다. 인터넷 연결을 확인해 주세요.") }
        succeeded = true
        return output
    }
}
