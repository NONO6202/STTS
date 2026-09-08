import AppKit
import SwiftUI
import UniformTypeIdentifiers
import AVFoundation

@MainActor final class AppState: ObservableObject {
    let updates = AppUpdater()
    let runtime = RuntimeSettings()
    @Published private(set) var downloadedModels: [DownloadedModel] = []
    @Published private(set) var managingModels = false
    var modelWorkIsBusy: Bool { speaking || listening || preparing || managingModels || voiceRecordingBusy }
    @Published private(set) var voiceRecordingActive = false
    @Published private(set) var voiceRecordingPending = false
    @Published private(set) var voiceRecordingSeconds: Double = 0
    @Published var voiceRecordingTranscript = ""
    @Published private(set) var voiceTranscribing = false
    var voiceRecordingBusy: Bool { voiceRecordingActive || voiceRecordingPending || voiceTranscribing }
    @Published var ttsEnabled = Preferences.read("ttsEnabled", fallback: true) {
        didSet {
            Preferences.save(ttsEnabled, key: "ttsEnabled")
            if ttsEnabled != oldValue {
                if ttsEnabled { connectMicrophone() }
                else { cancelSpeech(); closeComposer?(); removeMicrophone() }
            }
        }
    }
    @Published var sttEnabled = false {
        didSet {
            guard sttEnabled != oldValue else { return }
            if sttEnabled {
                guard !managingModels else { sttEnabled = false; return }
                prepareModels(startAfter: true)
                overlayChanged?()
            } else { stop() }
        }
    }
    @Published var level = ResourceLevel(rawValue: UserDefaults.standard.string(forKey: "level") ?? "") ?? .medium {
        didSet { UserDefaults.standard.set(level.rawValue, forKey: "level"); normalizeLanguages() }
    }
    @Published var sttModel = Preferences.read("sttModel", fallback: STTModel.automatic) {
        didSet { Preferences.save(sttModel, key: "sttModel"); normalizeLanguages() }
    }
    @Published var ttsLevel = Preferences.read("ttsLevel", fallback: ResourceLevel.minimum) {
        didSet { Preferences.save(ttsLevel, key: "ttsLevel"); cancelSpeech(); normalizeLanguages() }
    }
    @Published var ttsModel = Preferences.read("ttsModel", fallback: TTSModel.gtts) {
        didSet { Preferences.save(ttsModel, key: "ttsModel"); cancelSpeech(); normalizeLanguages() }
    }
    @Published var ttsVoice = Preferences.read("ttsVoice", fallback: "Sohee") {
        didSet { Preferences.save(ttsVoice, key: "ttsVoice") }
    }
    @Published var ttsPhrases = Preferences.read("ttsPhrases", fallback: TTSPhrases()) {
        didSet { Preferences.save(ttsPhrases, key: "ttsPhrases") }
    }
    @Published var clonedVoices = Preferences.read("clonedVoices", fallback: [VoiceProfile]()) {
        didSet { Preferences.save(clonedVoices, key: "clonedVoices") }
    }
    @Published var selectedCloneID = Preferences.read("selectedCloneID", fallback: Optional<UUID>.none) {
        didSet { Preferences.save(selectedCloneID, key: "selectedCloneID") }
    }
    @Published var volume = Preferences.read("volume", fallback: 1.0) {
        didSet { Preferences.save(volume, key: "volume"); playback.setVolume(volume) }
    }
    @Published var voiceMonitoring = Preferences.read("voiceMonitoring", fallback: false) {
        didSet { Preferences.save(voiceMonitoring, key: "voiceMonitoring") }
    }
    @Published var windowStyle = Preferences.read("windowStyle", fallback: SurfaceStyle.window) {
        didSet { Preferences.save(windowStyle, key: "windowStyle"); appearanceChanged?() }
    }
    @Published var captionStyle = Preferences.read("captionStyle", fallback: SurfaceStyle.captions) {
        didSet { Preferences.save(captionStyle, key: "captionStyle"); overlayChanged?() }
    }
    @Published var closeOnOutsideClick = Preferences.read("closeOnOutsideClick", fallback: true) {
        didSet { Preferences.save(closeOnOutsideClick, key: "closeOnOutsideClick") }
    }
    @Published var closeOnMouseShake = Preferences.read("closeOnMouseShake", fallback: true) {
        didSet { Preferences.save(closeOnMouseShake, key: "closeOnMouseShake") }
    }
    @Published var mouseShakeSensitivity = Preferences.read("mouseShakeSensitivity", fallback: MouseShakeSensitivity.normal) {
        didSet { Preferences.save(mouseShakeSensitivity, key: "mouseShakeSensitivity") }
    }
    @Published private(set) var shortcut = Preferences.read("shortcut", fallback: Shortcut.initial)
    @Published private(set) var captionShortcut = Preferences.read("captionShortcut", fallback: Shortcut.captionInitial)
    let language = "auto"
    @Published var ttsLanguage = Preferences.read("ttsLanguage", fallback: "ko") { didSet { Preferences.save(ttsLanguage, key: "ttsLanguage") } }
    @Published var microphoneReady = false
    @Published var listening = false
    @Published var preparing = false
    @Published var speaking = false
    @Published var status = "자막 꺼짐"
    @Published var ttsStatus = "대기"
    @Published var error: String?
    @Published var captions: [Caption] = []
    @Published var overlayVisible = true
    var closeComposer: (() -> Void)?
    var overlayChanged: (() -> Void)?
    var appearanceChanged: (() -> Void)?
    var shortcutChanged: ((Shortcut) throws -> Void)?
    var captionShortcutChanged: ((Shortcut) throws -> Void)?
    private var capture: DiscordCapture?
    private var pipeline: RecognitionPipeline?
    private var sttWorker: MLXWorker?
    private var ttsWorker: MLXWorker?
    private var setupTask: Task<Void, Never>?
    private var ttsTask: Task<Void, Never>?
    private var ttsExpiry: Task<Void, Never>?
    private var speechRequest: SpeechRequest?
    private let playback = AudioPlayback()
    private let microphone = VirtualMicrophone()
    private var session = UUID()
    private var speechID = UUID()
    private var overlayExpiry: Task<Void, Never>?
    private var voiceRecorder: AVAudioRecorder?
    private var voiceRecordingTimer: Timer?
    private var voiceRecordingTask: Task<Void, Never>?
    private var voiceRecordingID = UUID()
    private var voiceRecordingURL: URL?
    private var voiceRecordingCompleted: ((UUID) -> Void)?
    private var voiceTranscriptWorker: MLXWorker?
    private var recordedVoiceID: UUID?
    var visibleCaptions: [Caption] = []
    init() { normalizeLanguages() }

    var ttsChoice: ResourceLevel {
        get {
            switch ttsModel {
            case .gtts: return .minimum
            case .qwen06: return .medium
            case .qwen17: return .high
            case .supertonic3, .chatterV3: return .low
            case .vox: return .high
            default: return ttsLevel.resolved == .maximum ? .high : ttsLevel.resolved
            }
        }
        set { ttsLevel = newValue; ttsModel = .localAuto }
    }
    var sttChoice: ResourceLevel {
        get {
            switch sttModel {
            case .base, .small, .nemotron: return .low
            case .turbo: return .medium
            case .large, .asr06, .asr17: return .high
            default:
                switch level.resolved {
                case .minimum, .low: return .low
                case .high, .maximum: return .high
                default: return .medium
                }
            }
        }
        set { level = newValue; sttModel = .automatic }
    }
    var selectedTTSModel: TTSModel { TTSModel.localAuto.resolved(ttsChoice) }
    var selectedSTTModel: STTModel { STTModel.automatic.resolved(sttChoice) }
    var ttsLanguages: [String] { SpeechLanguages.sorted(SpeechLanguages.tts(selectedTTSModel)) }
    var sttLanguages: [String] { SpeechLanguages.sorted(SpeechLanguages.stt(selectedSTTModel)) }
    var supportsVoiceClone: Bool { [.qwen06, .qwen17].contains(selectedTTSModel) }
    var presetVoices: [String] {
        if selectedTTSModel == .supertonic3 { return ["F1", "F2", "F3", "F4", "F5", "M1", "M2", "M3", "M4", "M5"] }
        return supportsVoiceClone ? ["Sohee", "Vivian", "Serena", "Uncle_Fu", "Dylan", "Eric", "Ryan", "Aiden", "Ono_Anna"] : []
    }
    var activeClonedVoice: VoiceProfile? { supportsVoiceClone ? clonedVoices.first { $0.id == selectedCloneID } : nil }
    var ttsWorkerModel: String { selectedTTSModel.rawValue + (supportsVoiceClone && activeClonedVoice == nil ? "Custom" : "") }
    var selectedVoice: String {
        get { activeClonedVoice?.selection ?? ttsVoice }
        set {
            if supportsVoiceClone, let voice = clonedVoices.first(where: { $0.selection == newValue }) { selectedCloneID = voice.id }
            else if presetVoices.contains(newValue) { ttsVoice = newValue; selectedCloneID = nil }
        }
    }
    func addClonedVoices() -> UUID? {
        guard !speaking, !voiceRecordingBusy else { return nil }
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.wav, .aiff, .mp3, .mpeg4Audio]
        panel.allowsMultipleSelection = true
        panel.message = "음성 추가 · MP3, WAV, M4A, AIFF · 3~30초"
        guard panel.runModal() == .OK else { return nil }
        var first: UUID?, failures: [String] = []
        for source in panel.urls {
            do {
                let voice = try VoiceProfile.importAudio(source)
                clonedVoices.append(voice)
                if first == nil { first = voice.id }
            } catch { failures.append(source.lastPathComponent + ": " + error.localizedDescription) }
        }
        error = failures.isEmpty ? nil : failures.joined(separator: "\n")
        return first
    }
    func deleteClonedVoice(_ id: UUID) {
        guard !speaking, !voiceRecordingBusy, let voice = clonedVoices.first(where: { $0.id == id }) else { return }
        do {
            if FileManager.default.fileExists(atPath: voice.audioURL().path) {
                try FileManager.default.trashItem(at: voice.audioURL(), resultingItemURL: nil)
            }
            clonedVoices.removeAll { $0.id == id }
            if selectedCloneID == id { selectedCloneID = nil }
            error = nil
        } catch { self.error = error.localizedDescription }
    }
    func startVoiceRecording(completed: @escaping (UUID) -> Void) {
        guard !speaking, !voiceRecordingBusy else { return }
        error = nil; voiceRecordingPending = true; voiceRecordingSeconds = 0
        recordedVoiceID = nil
        let token = UUID(); voiceRecordingID = token
        voiceRecordingCompleted = completed
        voiceRecordingTask = Task {
            let allowed = await AVCaptureDevice.requestAccess(for: .audio)
            guard !Task.isCancelled, voiceRecordingID == token else { return }
            do {
                guard allowed else { throw AppFailure("시스템 설정에서 STTS의 마이크 접근을 허용해 주세요.") }
                try AppPaths.prepare()
                let url = AppPaths.temporary.appendingPathComponent("recording-" + token.uuidString + ".wav")
                voiceRecordingURL = url
                let recorder = try AVAudioRecorder(url: url, settings: [
                    AVFormatIDKey: kAudioFormatLinearPCM, AVSampleRateKey: 16000,
                    AVNumberOfChannelsKey: 1, AVLinearPCMBitDepthKey: 16,
                    AVLinearPCMIsFloatKey: false, AVLinearPCMIsBigEndianKey: false
                ])
                voiceRecorder = recorder
                guard recorder.record(forDuration: 30) else { throw AppFailure("마이크 녹음을 시작하지 못했습니다.") }
                voiceRecordingPending = false; voiceRecordingActive = true
                let timer = Timer(timeInterval: 0.1, repeats: true) { [weak self] _ in
                    Task { @MainActor in
                        guard let self, let recorder = self.voiceRecorder else { return }
                        if recorder.isRecording { self.voiceRecordingSeconds = recorder.currentTime }
                        else { self.finishVoiceRecording() }
                    }
                }
                voiceRecordingTimer = timer; RunLoop.main.add(timer, forMode: .common)
                voiceRecordingTask = nil
            } catch {
                cancelVoiceRecording(); self.error = error.localizedDescription
            }
        }
    }
    func finishVoiceRecording() {
        guard let recorder = voiceRecorder, let url = voiceRecordingURL else { return }
        voiceRecordingTimer?.invalidate(); voiceRecordingTimer = nil
        recorder.stop(); voiceRecorder = nil; voiceRecordingURL = nil
        voiceRecordingActive = false; voiceRecordingSeconds = 0
        let completed = voiceRecordingCompleted
        defer { try? FileManager.default.removeItem(at: url) }
        do {
            let voice = try VoiceProfile.importAudio(url)
            let name = "녹음 " + DateFormatter.localizedString(from: Date(), dateStyle: .short, timeStyle: .short)
            let transcript = voiceRecordingTranscript.trimmingCharacters(in: .whitespacesAndNewlines)
            clonedVoices.append(VoiceProfile(id: voice.id, name: name, sourceName: "마이크 녹음.wav", transcript: transcript))
            recordedVoiceID = voice.id
            if transcript.isEmpty { transcribeRecordedVoice(voice, completed: completed) }
            else { voiceRecordingCompleted = nil; completed?(voice.id) }
        } catch { voiceRecordingCompleted = nil; self.error = error.localizedDescription }
    }
    private func transcribeRecordedVoice(_ voice: VoiceProfile, completed: ((UUID) -> Void)?) {
        voiceTranscribing = true
        let worker = MLXWorker(threads: 2), token = voiceRecordingID
        voiceTranscriptWorker = worker
        voiceRecordingTask = Task {
            do {
                let text = try await Task.detached(priority: .utility) {
                    _ = try worker.call(["command": "load", "model": "turbo", "root": AppPaths.models.path, "memoryMB": 3072], timeout: 900)
                    let response = try worker.call(["command": "transcribe_voice", "audioFile": voice.audioURL().path, "language": "auto"], timeout: 180)
                    return (response["segments"] as? [[String: Any]] ?? []).compactMap { $0["text"] as? String }.joined(separator: " ").trimmingCharacters(in: .whitespacesAndNewlines)
                }.value
                guard !Task.isCancelled, voiceRecordingID == token else { return }
                guard !text.isEmpty else { throw AppFailure("대본을 인식하지 못했습니다. 직접 입력해 주세요.") }
                if let index = clonedVoices.firstIndex(where: { $0.id == voice.id }), clonedVoices[index].transcript.isEmpty { clonedVoices[index].transcript = text }
            } catch {
                guard !Task.isCancelled, voiceRecordingID == token else { return }
                self.error = error.localizedDescription
            }
            worker.stop(); voiceTranscriptWorker = nil; voiceRecordingTask = nil
            voiceTranscribing = false; voiceRecordingCompleted = nil
            completed?(voice.id)
        }
    }
    @discardableResult func cancelVoiceRecording() -> UUID? {
        let saved = recordedVoiceID; recordedVoiceID = nil
        voiceRecordingID = UUID(); voiceRecordingTask?.cancel(); voiceRecordingTask = nil
        voiceTranscriptWorker?.stop(); voiceTranscriptWorker = nil; voiceTranscribing = false
        voiceRecordingTimer?.invalidate(); voiceRecordingTimer = nil
        voiceRecorder?.stop(); voiceRecorder = nil
        if let url = voiceRecordingURL { try? FileManager.default.removeItem(at: url) }
        voiceRecordingURL = nil; voiceRecordingCompleted = nil
        voiceRecordingActive = false; voiceRecordingPending = false; voiceRecordingSeconds = 0
        return saved
    }
    func refreshModels() {
        guard !managingModels else { return }
        managingModels = true
        Task {
            defer { managingModels = false }
            do { downloadedModels = try await Task.detached(priority: .utility) { try ModelStorage.installed() }.value }
            catch { self.error = error.localizedDescription }
        }
    }
    func deleteModel(_ model: DownloadedModel) {
        guard !modelWorkIsBusy else { error = "음성·자막 작업이 끝난 뒤 모델을 삭제해 주세요."; return }
        managingModels = true
        cancelSpeech() // Release the idle TTS model kept warm in the worker.
        Task {
            defer { managingModels = false }
            do {
                downloadedModels = try await Task.detached(priority: .utility) {
                    try ModelStorage.delete(model)
                    return try ModelStorage.installed()
                }.value
            } catch { self.error = error.localizedDescription }
        }
    }
    func showModelFolder(_ model: DownloadedModel? = nil) {
        do {
            if let model { NSWorkspace.shared.activateFileViewerSelecting([try ModelStorage.location(of: model)]) }
            else { try AppPaths.prepare(); NSWorkspace.shared.open(AppPaths.models) }
        } catch { self.error = error.localizedDescription }
    }
    func connectMicrophone() {
        guard ttsEnabled, !speaking else { return }
        do {
            playback.prepareOutput(); try microphone.prepare()
            microphoneReady = true; error = nil
        } catch { microphoneReady = false; self.error = error.localizedDescription }
    }
    func removeMicrophone() {
        guard !speaking else { return }
        do { try microphone.remove(); microphoneReady = false }
        catch { self.error = error.localizedDescription }
    }
    private func normalizeLanguages() {
        let tts = SpeechLanguages.matching(ttsLanguage, in: ttsLanguages, fallback: "ko")
        if tts != ttsLanguage { ttsLanguage = tts }
        if let first = presetVoices.first, !presetVoices.contains(ttsVoice) { ttsVoice = first }
    }

    func setShortcut(_ candidate: Shortcut) {
        guard candidate.valid else { error = "⌘·⌃·⌥ 조합 또는 F1~F20 키를 선택해 주세요."; return }
        guard candidate.keyCode != captionShortcut.keyCode || candidate.modifiers != captionShortcut.modifiers else { error = "자막 단축키와 다른 키를 선택해 주세요."; return }
        do {
            try shortcutChanged?(candidate)
            shortcut = candidate; Preferences.save(candidate, key: "shortcut")
        } catch { self.error = error.localizedDescription }
    }
    func setCaptionShortcut(_ candidate: Shortcut) {
        guard candidate.valid else { error = "⌘·⌃·⌥ 조합 또는 F1~F20 키를 선택해 주세요."; return }
        guard candidate.keyCode != shortcut.keyCode || candidate.modifiers != shortcut.modifiers else { error = "TTS 입력 단축키와 다른 키를 선택해 주세요."; return }
        do {
            try captionShortcutChanged?(candidate)
            captionShortcut = candidate; Preferences.save(candidate, key: "captionShortcut")
        } catch { self.error = error.localizedDescription }
    }
    func toggleCaptions() {
        sttEnabled.toggle()
    }
    func prepareModels(startAfter: Bool = false) {
        guard sttEnabled, !preparing, !listening, !managingModels else { return }
        preparing = true; error = nil
        let token = UUID(); session = token
        let selectedLevel = sttChoice, selectedModel = selectedSTTModel, selectedLanguage = language
        let worker = MLXWorker(threads: selectedLevel.threads); sttWorker = worker
        setupTask = Task {
            guard !Task.isCancelled, session == token else { return }
            do {
                status = "모델 확인 중…"
                _ = try await Task.detached(priority: .utility) {
                    try worker.call(["command": "prepare", "model": selectedModel.rawValue, "root": AppPaths.models.path], timeout: 900) { [weak self] message in
                        Task { @MainActor in if self?.session == token { self?.status = message } }
                    }
                }.value
                try await AssetDownloader.prepare(.vad) { _ in }
                guard !Task.isCancelled, session == token else { worker.stop(); return }
                if startAfter {
                    status = "음성 인식 준비 중…"
                    let newPipeline = try await RecognitionPipeline.create(level: selectedLevel, model: selectedModel, worker: worker, language: selectedLanguage, speakers: false,
                        captions: { [weak self] result in Task { @MainActor in self?.receive(result, token: token) } },
                        failure: { [weak self] message in Task { @MainActor in
                            guard let self, self.session == token else { return }
                            self.stop(); self.error = message
                        } })
                    guard !Task.isCancelled, session == token else { newPipeline.stop(); return }
                    pipeline = newPipeline
                    let source = DiscordCapture()
                    try source.start { [weak newPipeline] samples in newPipeline?.receive(samples) }
                    capture = source; listening = true; status = "Discord 수신 중"
                } else { worker.stop(); sttWorker = nil; status = "준비 완료" }
                preparing = false
            } catch {
                guard session == token else { return }
                stop(); self.error = error.localizedDescription
            }
        }
    }
    func stop() {
        if sttEnabled { sttEnabled = false; return }
        session = UUID(); setupTask?.cancel(); setupTask = nil
        capture?.stop(); capture = nil
        pipeline?.stop(); pipeline = nil; sttWorker?.stop(); sttWorker = nil
        listening = false; preparing = false; status = "자막 꺼짐"
        overlayExpiry?.cancel(); visibleCaptions = []; overlayChanged?()
    }
    private func receive(_ result: [Caption], token: UUID) {
        guard session == token, listening, !result.isEmpty else { return }
        captions.append(contentsOf: result)
        if captions.count > 100 { captions.removeFirst(captions.count - 100) }
        visibleCaptions = Array(captions.suffix(2)); status = "Discord 수신 중"
        overlayChanged?(); overlayExpiry?.cancel()
        overlayExpiry = Task {
            try? await Task.sleep(for: .seconds(10))
            guard !Task.isCancelled else { return }
            visibleCaptions = []; overlayChanged?()
        }
    }
    func prepareTTS() {
        guard ttsEnabled, !speaking, !voiceRecordingBusy, !managingModels, selectedTTSModel != .gtts else { return }
        cancelSpeech(); speaking = true; error = nil; ttsStatus = "모델 확인 중…"
        let worker = MLXWorker(threads: ttsChoice.threads), token = speechID, model = ttsWorkerModel
        ttsWorker = worker
        ttsTask = Task {
            do {
                _ = try await Task.detached(priority: .utility) {
                    try worker.call(["command": "prepare", "model": model, "root": AppPaths.models.path], timeout: 900) { [weak self] message in
                        Task { @MainActor in if self?.speechID == token { self?.ttsStatus = message } }
                    }
                }.value
                guard speechID == token else { return }
                worker.stop(); ttsWorker = nil; speaking = false; ttsStatus = "준비 완료"
            } catch { if speechID == token { cancelSpeech(); self.error = error.localizedDescription } }
        }
    }
    func speak(_ text: String, preview: Bool = false) {
        guard ttsEnabled else { return }
        guard !voiceRecordingBusy else { error = "녹음을 먼저 마쳐 주세요."; return }
        guard !managingModels else { error = "모델 관리가 끝난 뒤 전송해 주세요."; return }
        guard !speaking else { error = "현재 음성 재생이 끝난 뒤 전송해 주세요."; return }
        let text = ttsPhrases.expand(text)
        guard !text.isEmpty, text.count <= 500 else { error = "1~500자 이내로 입력해 주세요."; return }
        let clone = activeClonedVoice
        guard clone == nil || clone?.ready == true else {
            error = "설정 > 보이스 클론에서 선택한 목소리의 이름과 대본을 확인해 주세요."; return
        }
        if !preview && !microphoneReady { connectMicrophone() }
        guard preview || microphoneReady else {
            ttsStatus = "가상 마이크 연결 필요"; return
        }
        error = nil; speaking = true; ttsStatus = "음성 생성 중…"; ttsExpiry?.cancel()
        let token = UUID(), language = ttsLanguage, model = selectedTTSModel, workerModel = ttsWorkerModel, voice = ttsVoice, memory = ttsChoice.ttsMemoryMB
        speechID = token
        let request = SpeechRequest(); speechRequest = model == .gtts ? request : nil
        let worker: MLXWorker?
        if model == .gtts { worker = nil } else { worker = ttsWorker ?? MLXWorker(threads: ttsChoice.threads); ttsWorker = worker }
        ttsTask = Task {
            var generated: URL?
            do {
                let url: URL
                if let worker {
                    try AppPaths.prepare()
                    url = AppPaths.temporary.appendingPathComponent(UUID().uuidString + ".wav"); generated = url
                    try await Task.detached(priority: .utility) {
                        _ = try worker.call(["command": "load", "model": workerModel, "root": AppPaths.models.path, "memoryMB": memory], timeout: 900) { [weak self] message in
                            Task { @MainActor in if self?.speechID == token { self?.ttsStatus = message } }
                        }
                        var payload: [String: Any] = ["command": "tts", "text": text, "language": language, "voice": voice, "output": url.path]
                        if let clone { payload["referenceAudio"] = clone.audioURL().path; payload["referenceText"] = clone.transcript.trimmingCharacters(in: .whitespacesAndNewlines) }
                        _ = try worker.call(payload, timeout: 180)
                    }.value
                } else { url = try await request.synthesize(text: text, language: language); generated = url }
                guard speechID == token, !Task.isCancelled else { try? FileManager.default.removeItem(at: url); return }
                if microphoneReady { try microphone.setSending(!preview, monitoring: voiceMonitoring) }
                else if !preview { throw AppFailure("가상 마이크를 다시 연결해 주세요.") }
                ttsStatus = preview ? "미리 듣는 중…" : "가상 마이크로 보내는 중…"; playback.setVolume(volume)
                try playback.play(url, deviceUID: "") { [weak self] in
                    try? FileManager.default.removeItem(at: url)
                    guard let self, self.speechID == token else { return }
                    self.microphone.disconnect()
                    self.speaking = false; self.speechRequest = nil; self.ttsStatus = "대기"
                    self.ttsExpiry = Task {
                        try? await Task.sleep(for: .seconds(30))
                        guard !Task.isCancelled, self.speechID == token else { return }
                        self.ttsWorker?.stop(); self.ttsWorker = nil
                    }
                }
            } catch {
                if let generated { try? FileManager.default.removeItem(at: generated) }
                guard speechID == token else { return }
                cancelSpeech(); self.error = error.localizedDescription
            }
        }
    }
    func cancelSpeech() {
        speechID = UUID(); speechRequest?.cancel(); speechRequest = nil
        ttsTask?.cancel(); ttsTask = nil; ttsExpiry?.cancel(); ttsExpiry = nil
        ttsWorker?.stop(); ttsWorker = nil; playback.stop(); speaking = false; ttsStatus = "대기"
        microphone.disconnect()
    }
    func shutdown() {
        cancelVoiceRecording()
        sttWorker?.stop(force: true); ttsWorker?.stop(force: true)
        stop(); cancelSpeech(); try? FileManager.default.removeItem(at: AppPaths.temporary)
    }
}
