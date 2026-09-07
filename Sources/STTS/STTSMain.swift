import AppKit
import Foundation
import WhisperBridge
import FluidAudio

@main struct STTSMain {
    @MainActor static func main() {
        if CommandLine.arguments.count == 3, CommandLine.arguments[1] == "--microphone-receiver" {
            do { try MicrophoneCheck.receive(identifier: CommandLine.arguments[2]); exit(0) }
            catch { FileHandle.standardError.write(Data((error.localizedDescription + "\n").utf8)); exit(1) }
        }
        if CommandLine.arguments.contains("--smoke-test") || CommandLine.arguments.contains("--prepare-models") {
            Task {
                do { try await runCommand(); exit(0) }
                catch { FileHandle.standardError.write(Data((error.localizedDescription + "\n").utf8)); exit(1) }
            }
            RunLoop.main.run()
            return
        }
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        let delegate = AppDelegate(); app.delegate = delegate
        withExtendedLifetime(delegate) { app.run() }
    }
    static func runCommand() async throws {
        if CommandLine.arguments.contains("--microphone") { try await MicrophoneCheck.run(); return }
        let worker = MLXWorker(threads: 2)
        defer { worker.stop(force: true) }
        _ = try await Task.detached(priority: .utility) {
            try worker.call(["command": "prepare", "model": "turbo", "root": AppPaths.models.path], timeout: 900)
        }.value
        try await AssetDownloader.prepare(.vad) { FileHandle.standardError.write(Data(($0 + "\n").utf8)) }
        guard CommandLine.arguments.contains("--smoke-test") else { print("모델 준비 완료"); return }
        let beforeTTS = Date()
        let audio: URL
        if CommandLine.arguments.contains("--local-tts") {
            let tts = MLXWorker(threads: 2)
            defer { tts.stop(force: true) }
            try AppPaths.prepare()
            audio = AppPaths.temporary.appendingPathComponent(UUID().uuidString + ".wav")
            try await Task.detached(priority: .utility) {
                _ = try tts.call(["command": "load", "model": "qwen06Custom", "root": AppPaths.models.path, "memoryMB": 4608], timeout: 900)
                _ = try tts.call(["command": "tts", "text": "안녕하세요. 음성 자막 테스트입니다. 지금 왼쪽으로 이동합니다.", "language": "ko", "voice": "Sohee", "output": audio.path], timeout: 180)
            }.value
        } else {
            audio = try await SpeechRequest().synthesize(text: "안녕하세요. 음성 자막 테스트입니다. 지금 왼쪽으로 이동합니다.", language: "ko")
        }
        defer { try? FileManager.default.removeItem(at: audio) }
        let ttsSeconds = Date().timeIntervalSince(beforeTTS)
        let samples = try AudioFiles.samples(audio)
        let result = try await Task.detached(priority: .utility) { () throws -> [String: Any] in
            let beforeLoad = Date()
            let engine = try MLXRecognizer(model: .turbo, level: .medium, worker: worker)
            defer { engine.close() }
            let loadSeconds = Date().timeIntervalSince(beforeLoad)
            _ = ComputeBackend.ready
            guard let vad = stts_vad_load(ModelAsset.vad.local.path) else { throw AppFailure("VAD 로드 실패") }
            defer { stts_vad_free(vad) }
            var splitter = SpeechSegmenter(maximumSeconds: 3), chunks: [SpeechChunk] = []
            let padded = samples + [Float](repeating: 0, count: 16000)
            for index in stride(from: 0, through: padded.count - 512, by: 512) {
                let frame = Array(padded[index..<index + 512])
                let probability = frame.withUnsafeBufferPointer { stts_vad_probability(vad, $0.baseAddress, 512) }
                guard probability >= 0 else { throw AppFailure("VAD 추론 실패") }
                if let chunk = splitter.feed(frame, probability: probability) { chunks.append(chunk) }
            }
            if let last = splitter.flush() { chunks.append(last) }
            let captions = try chunks.flatMap { try engine.transcribe($0, language: "ko") }
            let text = captions.map(\.text).joined(separator: " ")
            guard text.contains("테스트"), text.contains("이동") else { throw AppFailure("실제 음성 전사 검증 실패: " + text) }
            return ["model": "MLX Whisper large-v3-turbo 8bit", "tts": CommandLine.arguments.contains("--local-tts") ? "Qwen3-TTS 0.6B CustomVoice" : "gTTS",
                    "ttsSecondsIncludingLoad": ttsSeconds, "audioSeconds": Double(samples.count) / 16000,
                    "loadSeconds": loadSeconds, "inferenceSeconds": captions.map(\.duration),
                    "chunks": chunks.count, "transcript": text, "mlxActiveMemoryMB": engine.activeMemoryMB]
        }.value
        var report = result
        if CommandLine.arguments.contains("--speakers") {
            let diarizer = try LSEENDDiarizer(model: await SpeakerModels.load(), timelineConfig: DiarizerTimelineConfig(maxStoredFrames: 600))
            let before = Date()
            let timeline = try diarizer.processComplete(samples, sourceSampleRate: 16000)
            report["speakerProcessingSeconds"] = Date().timeIntervalSince(before)
            report["speakerTracksDetected"] = timeline.speakers.count
            report["speakerNote"] = "한 합성 음성의 실행 검증이며 다화자·한국어 정확도 검증이 아님"
            diarizer.cleanup()
        }
        let data = try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
        print(String(decoding: data, as: UTF8.self))
    }
}
