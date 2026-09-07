import Foundation
import Darwin

/// Private, sequential pipe protocol. Killing this worker cancels only its model job.
final class MLXWorker: @unchecked Sendable {
    private let ioLock = NSLock()
    private let processLock = NSLock()
    private var process: Process?
    private var input: FileHandle?
    private var output: FileHandle?
    private var buffered = Data()
    private var stopped = false
    private let threads: Int
    init(threads: Int = 2) { self.threads = threads; signal(SIGPIPE, SIG_IGN) }

    private func start() throws {
        processLock.lock(); defer { processLock.unlock() }
        guard !stopped else { throw CancellationError() }
        if let process, process.isRunning { return }
        let child = Process(), stdin = Pipe(), stdout = Pipe()
        let bundled = Bundle.main.resourceURL?.appendingPathComponent("mlx-worker/mlx-worker")
        if let bundled, FileManager.default.isExecutableFile(atPath: bundled.path) { child.executableURL = bundled }
        else {
            let root = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
            child.executableURL = root.appendingPathComponent(".venv/bin/python")
            child.arguments = [root.appendingPathComponent("Support/mlx_worker.py").path]
        }
        var environment = ProcessInfo.processInfo.environment
        for key in ["OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"] { environment[key] = String(threads) }
        child.environment = environment
        child.standardInput = stdin; child.standardOutput = stdout; child.standardError = FileHandle.nullDevice
        if CommandLine.arguments.contains("--smoke-test") {
            child.arguments = (child.arguments ?? []) + ["--debug"]
            child.standardError = FileHandle.standardError
        }
        try child.run()
        process = child; input = stdin.fileHandleForWriting; output = stdout.fileHandleForReading
    }
    func call(_ request: [String: Any], timeout: Double = 60, progress: @escaping @Sendable (String) -> Void = { _ in }) throws -> [String: Any] {
        ioLock.lock(); defer { ioLock.unlock() }
        try start()
        let deadline = DispatchWorkItem { [weak self] in self?.stop() }
        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + timeout, execute: deadline)
        defer { deadline.cancel() }
        var payload = try JSONSerialization.data(withJSONObject: request)
        guard payload.count < 2_000_000 else { throw AppFailure("음성 요청이 너무 큽니다.") }
        payload.append(10)
        try input?.write(contentsOf: payload)
        while true {
            guard let line = try readLine(), let response = try JSONSerialization.jsonObject(with: line) as? [String: Any] else { throw AppFailure("MLX 작업이 중단되었습니다.") }
            if response["event"] as? String == "progress" { progress(response["message"] as? String ?? "모델 준비 중…"); continue }
            guard response["ok"] as? Bool == true else { throw AppFailure(response["error"] as? String ?? "MLX 처리 실패") }
            return response
        }
    }
    private func readLine() throws -> Data? {
        while true {
            if let index = buffered.firstIndex(of: 10) {
                let line = buffered.prefix(upTo: index); buffered.removeSubrange(...index); return Data(line)
            }
            guard let output else { return nil }
            var bytes = [UInt8](repeating: 0, count: 4096)
            let count = Darwin.read(output.fileDescriptor, &bytes, bytes.count)
            if count < 0, errno == EINTR { continue }
            guard count >= 0 else { throw AppFailure("MLX 응답을 읽을 수 없습니다.") }
            guard count > 0 else { return nil }
            buffered.append(contentsOf: bytes.prefix(count))
            guard buffered.count < 524_288 else { stop(); throw AppFailure("MLX 응답 한도를 초과했습니다.") }
        }
    }
    func stop(force: Bool = false) {
        processLock.lock(); defer { processLock.unlock() }
        stopped = true
        if let process, process.isRunning {
            kill(process.processIdentifier, force ? SIGKILL : SIGTERM)
            DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + 1) {
                if process.isRunning { kill(process.processIdentifier, SIGKILL) }
            }
        }
    }
    deinit { stop() }
}

final class MLXRecognizer {
    private let worker: MLXWorker
    private(set) var activeMemoryMB: Double = 0
    init(model: STTModel, level: ResourceLevel, worker: MLXWorker) throws {
        self.worker = worker
        let selected = model.resolved(level)
        _ = try worker.call(["command": "load", "model": selected.rawValue, "root": AppPaths.models.path, "memoryMB": selected == .large ? 6144 : (selected == .asr17 ? 4096 : 3072)], timeout: 180)
    }
    func cancel() { worker.stop() }
    func close() { worker.stop() }
    func transcribe(_ chunk: SpeechChunk, language: String) throws -> [Caption] {
        let pcm = chunk.samples.withUnsafeBytes { Data($0).base64EncodedString() }
        let result = try worker.call(["command": "stt", "samples": pcm, "language": language])
        activeMemoryMB = result["activeMemoryMB"] as? Double ?? 0
        let duration = result["seconds"] as? Double ?? 0
        return (result["segments"] as? [[String: Any]] ?? []).compactMap { segment in
            guard let text = segment["text"] as? String, !text.isEmpty else { return nil }
            let start = chunk.start + (segment["start"] as? Double ?? 0)
            let end = min(chunk.end, chunk.start + (segment["end"] as? Double ?? chunk.end - chunk.start))
            return Caption(text: text, start: start, end: max(start, end), duration: duration)
        }
    }
}
