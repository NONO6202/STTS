import Foundation
import WhisperBridge
import FluidAudio

enum ComputeBackend {
    // Swift initializes this once, on the first STT load. TTS-only sessions stay small.
    static let ready: Void = {
        let bundled = Bundle.main.privateFrameworksURL
        let backends = bundled != nil && FileManager.default.fileExists(atPath: bundled!.appendingPathComponent("libggml-metal.so").path)
            ? bundled!.path : "/opt/homebrew/opt/ggml/libexec"
        stts_load_backends(backends)
    }()
}

final class RecognitionPipeline: @unchecked Sendable {
    private let ingest = DispatchQueue(label: "local.stts.vad", qos: .utility)
    private let inference = DispatchQueue(label: "local.stts.whisper", qos: .utility)
    private let incomingSlots = DispatchSemaphore(value: 32)
    private let inferenceSlots = DispatchSemaphore(value: 3)
    private let lock = NSLock()
    private var running = true
    private let recognizer: MLXRecognizer
    private var vad: OpaquePointer?
    private var diarizer: LSEENDDiarizer?
    private var segmenter: SpeechSegmenter
    private var remainder: [Float] = []
    private var speakerEpoch: Double = 0
    private let language: String
    private let captions: @Sendable ([Caption]) -> Void
    private let failure: @Sendable (String) -> Void
    private var active: Bool { lock.lock(); defer { lock.unlock() }; return running }

    static func create(level: ResourceLevel, model: STTModel, worker: MLXWorker, language: String, speakers: Bool,
                       captions: @escaping @Sendable ([Caption]) -> Void,
                       failure: @escaping @Sendable (String) -> Void) async throws -> RecognitionPipeline {
        try await Task.detached(priority: .utility) {
            let recognizer = try MLXRecognizer(model: model, level: level, worker: worker)
            _ = ComputeBackend.ready
            guard let vad = stts_vad_load(ModelAsset.vad.local.path) else { throw AppFailure("음성 감지 모델을 불러오지 못했습니다.") }
            let pipeline = RecognitionPipeline(recognizer: recognizer, vad: vad, level: level, language: language, captions: captions, failure: failure)
            if speakers {
                let diarizer = try LSEENDDiarizer(model: await SpeakerModels.load(), timelineConfig: DiarizerTimelineConfig(maxStoredFrames: 600))
                pipeline.diarizer = diarizer
            }
            return pipeline
        }.value
    }
    private init(recognizer: MLXRecognizer, vad: OpaquePointer, level: ResourceLevel, language: String,
                 captions: @escaping @Sendable ([Caption]) -> Void, failure: @escaping @Sendable (String) -> Void) {
        self.recognizer = recognizer; self.vad = vad; self.language = language
        self.segmenter = SpeechSegmenter(maximumSeconds: level.chunkSeconds)
        self.captions = captions; self.failure = failure
    }
    func receive(_ samples: [Float]) {
        guard active else { return }
        guard incomingSlots.wait(timeout: .now()) == .success else { fail("수신 처리가 밀려 자막을 중지했습니다. 화자 구분을 끄거나 STT 사양을 낮춰 주세요."); return }
        ingest.async { [self] in
            defer { incomingSlots.signal() }
            guard active, let vad else { return }
            do {
                if let diarizer {
                    // Bound the model's session history; names restart in the next hour.
                    if Double(segmenter.clock) / 16000 - speakerEpoch > 3600 {
                        diarizer.reset(); speakerEpoch = Double(segmenter.clock) / 16000
                    }
                    _ = try diarizer.process(samples: samples, sourceSampleRate: 16000)
                }
                remainder.append(contentsOf: samples)
                var offset = 0
                while remainder.count - offset >= 512 {
                    let frame = Array(remainder[offset..<offset + 512]); offset += 512
                    let probability = frame.withUnsafeBufferPointer { stts_vad_probability(vad, $0.baseAddress, 512) }
                    guard probability >= 0 else { throw AppFailure("음성 감지 처리에 실패했습니다.") }
                    if let chunk = segmenter.feed(frame, probability: probability) { enqueue(chunk) }
                }
                if offset > 0 { remainder.removeFirst(offset) }
            } catch { fail(error.localizedDescription) }
        }
    }
    private func enqueue(_ chunk: SpeechChunk) {
        guard active else { return }
        guard inferenceSlots.wait(timeout: .now()) == .success else { fail("인식 대기가 한도를 초과했습니다. STT 사양을 낮추거나 화자 구분을 꺼 주세요."); return }
        inference.async { [self] in
            defer { inferenceSlots.signal() }
            guard active else { return }
            do {
                let result = try recognizer.transcribe(chunk, language: language)
                ingest.async { [self] in
                    guard active else { return }
                    captions(result.map { caption in
                        var caption = caption
                        if let diarizer {
                            let segments: [DiarizerSegment] = diarizer.timeline.speakers.values.flatMap { $0.finalizedSegments + $0.tentativeSegments }
                            let lower = caption.start - speakerEpoch, upper = caption.end - speakerEpoch
                            let matching = segments.filter { segment in
                                Double(segment.endTime) > lower && Double(segment.startTime) < upper
                            }
                            let ids = Set(matching.map { $0.speakerIndex }).sorted()
                            caption.speaker = ids.isEmpty ? "화자 확인 중" : ids.map { "화자 \($0 + 1)" }.joined(separator: " / ")
                        }
                        return caption
                    })
                }
            } catch { if active { fail(error.localizedDescription) } }
        }
    }
    private func fail(_ message: String) {
        lock.lock(); let first = running; running = false; lock.unlock()
        if first { recognizer.cancel(); failure(message) }
    }
    func stop() {
        lock.lock(); running = false; lock.unlock()
        recognizer.cancel()
        ingest.async { [self] in stts_vad_free(vad); vad = nil; diarizer?.cleanup(); diarizer = nil; remainder = [] }
        inference.async { [self] in recognizer.close() }
    }
    deinit { stts_vad_free(vad) }
}
