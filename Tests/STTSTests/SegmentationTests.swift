import Testing
import Foundation
import AppKit
@testable import STTS

@Suite struct SegmentationTests {
    @Test func mouseShakeRequiresFastReversals() {
        var fast = MouseShakeDetector()
        #expect(fast.sample(CGPoint(x: 0, y: 0), at: 1) == false)
        #expect(fast.sample(CGPoint(x: 35, y: 0), at: 1.05) == false)
        #expect(fast.sample(CGPoint(x: 0, y: 0), at: 1.10) == false)
        #expect(fast.sample(CGPoint(x: 35, y: 0), at: 1.15) == true)
        var straight = MouseShakeDetector(), slow = MouseShakeDetector()
        for i in 0..<20 {
            #expect(straight.sample(CGPoint(x: i * 100, y: 0), at: Double(i) * 0.04) == false)
            #expect(slow.sample(CGPoint(x: i % 2 * 20, y: 0), at: Double(i) * 0.1) == false)
        }
        var paused = MouseShakeDetector()
        _ = paused.sample(.zero, at: 0)
        _ = paused.sample(CGPoint(x: 100, y: 0), at: 0.04)
        _ = paused.sample(.zero, at: 0.08)
        #expect(paused.sample(CGPoint(x: 100, y: 0), at: 1) == false)
    }
    @Test func mouseShakeSensitivityControlsShortGesture() {
        for sensitivity in MouseShakeSensitivity.allCases {
            var detector = MouseShakeDetector()
            _ = detector.sample(.zero, at: 0, sensitivity: sensitivity)
            _ = detector.sample(CGPoint(x: 20, y: 0), at: 0.04, sensitivity: sensitivity)
            _ = detector.sample(.zero, at: 0.08, sensitivity: sensitivity)
            #expect(detector.sample(CGPoint(x: 20, y: 0), at: 0.12, sensitivity: sensitivity) == (sensitivity == .high))
        }
    }
    @Test @MainActor func composerClosesForRelativeMotionAndOutsideClicks() throws {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        let enabled = delegate.state.ttsEnabled
        let dismissal = (delegate.state.closeOnOutsideClick, delegate.state.closeOnMouseShake, delegate.state.mouseShakeSensitivity)
        delegate.state.ttsEnabled = true
        delegate.state.closeOnOutsideClick = true
        delegate.state.closeOnMouseShake = true
        delegate.state.mouseShakeSensitivity = .normal
        delegate.showComposer()
        let panel = try #require(app.windows.first { $0.title == "STTS 입력" && $0.isVisible })
        defer {
            if panel.isVisible { delegate.showComposer() }
            delegate.state.ttsEnabled = enabled
            delegate.state.closeOnOutsideClick = dismissal.0
            delegate.state.closeOnMouseShake = dismissal.1
            delegate.state.mouseShakeSensitivity = dismissal.2
        }
        func move(_ delta: Int64) throws {
            // FPS-style events: an unchanged cursor location, with relative movement.
            let cgEvent = try #require(CGEvent(mouseEventSource: nil, mouseType: .mouseMoved,
                mouseCursorPosition: CGPoint(x: 320, y: 240), mouseButton: .left))
            cgEvent.setIntegerValueField(.mouseEventDeltaX, value: delta)
            let event = try #require(NSEvent(cgEvent: cgEvent))
            #expect(event.deltaX == CGFloat(delta))
            app.postEvent(event, atStart: false)
            let deadline = Date().addingTimeInterval(0.04)
            while let next = app.nextEvent(matching: .any, until: deadline, inMode: .default, dequeue: true) {
                app.sendEvent(next)
                if Date() >= deadline { break }
            }
        }
        delegate.state.closeOnMouseShake = false
        for delta in [120, -120, 120] as [Int64] { try move(delta) }
        #expect(panel.isVisible)
        delegate.state.closeOnMouseShake = true
        try move(120)
        #expect(panel.isVisible) // An ordinary turn must not dismiss the input.
        for delta in [-120, 120, -120, 120, -120] as [Int64] {
            if !panel.isVisible { break }
            try move(delta)
        }
        #expect(!panel.isVisible)
        delegate.showComposer()
        let reopened = try #require(app.windows.first { $0.title == "STTS 입력" && $0.isVisible })
        defer { if reopened.isVisible { delegate.showComposer() } }
        func click(_ window: NSWindow) throws {
            for type in [NSEvent.EventType.leftMouseDown, .leftMouseUp] {
                let event = try #require(NSEvent.mouseEvent(with: type, location: CGPoint(x: 35, y: 22),
                    modifierFlags: [], timestamp: ProcessInfo.processInfo.systemUptime,
                    windowNumber: window.windowNumber, context: nil, eventNumber: 0, clickCount: 1, pressure: 0))
                app.postEvent(event, atStart: false)
            }
            let deadline = Date().addingTimeInterval(0.04)
            while let next = app.nextEvent(matching: .any, until: deadline, inMode: .default, dequeue: true) {
                app.sendEvent(next)
                if Date() >= deadline { break }
            }
        }
        try click(reopened)
        #expect(reopened.isVisible)
        final class ClickTarget: NSView {
            var clicks = 0
            override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
            override func mouseDown(with event: NSEvent) { clicks += 1 }
        }
        let outside = NSWindow(contentRect: CGRect(x: 30, y: 30, width: 200, height: 100),
                               styleMask: [.titled], backing: .buffered, defer: false)
        outside.isReleasedWhenClosed = false
        defer { outside.close() }
        let target = ClickTarget(frame: CGRect(x: 0, y: 0, width: 200, height: 100))
        outside.contentView = target
        outside.orderBack(nil)
        delegate.state.closeOnOutsideClick = false
        try click(outside)
        #expect(reopened.isVisible)
        #expect(target.clicks == 1)
        delegate.state.closeOnOutsideClick = true
        try click(outside)
        #expect(!reopened.isVisible)
        #expect(target.clicks == 2)
    }
    @Test func composerStaysOnScreenNearPointer() {
        let screen = CGRect(x: -1920, y: -200, width: 1920, height: 1080)
        for point in [CGPoint(x: -1919, y: -199), CGPoint(x: -1, y: 879), CGPoint(x: -800, y: 400)] {
            let frame = ComposerPlacement.frame(near: point, in: screen)
            #expect(screen.contains(frame))
            #expect(frame.height == 44)
        }
        #expect(ResourceLevel.specifications.map(\.rawValue) == ["최저", "하", "중", "상", "최상"])
    }
    @Test func shortcutRejectsGameplayKeysWithoutModifiers() {
        #expect(!Shortcut(keyCode: 0, modifiers: 0, key: "a").valid)
        #expect(Shortcut(keyCode: 97, modifiers: 0, key: "F6").valid)
        #expect(Shortcut.initial.valid)
        #expect(Shortcut.initial.label == "⌃⌥Space")
    }
    @Test func independentAppearanceValuesSurvivePersistence() throws {
        let window = SurfaceStyle(background: Tint(0.1, 0.3, 0.8), foreground: Tint(1, 1, 1), opacity: 0.35)
        let caption = SurfaceStyle.captions
        let encoded = try JSONEncoder().encode([window, caption])
        let decoded = try JSONDecoder().decode([SurfaceStyle].self, from: encoded)
        #expect(decoded == [window, caption])
        #expect(decoded[0].opacity != decoded[1].opacity)
    }
    @Test func localAutoDoesNotReplaceDefaultGTTS() {
        for level in ResourceLevel.allCases { #expect(TTSModel.gtts.resolved(level) == .gtts) }
        #expect(TTSModel.localAuto.resolved(.minimum) == .gtts)
        #expect(TTSModel.localAuto.resolved(.low) == .supertonic3)
        #expect(TTSModel.localAuto.resolved(.medium) == .qwen06)
        #expect(TTSModel.localAuto.resolved(.high) == .qwen17)
        #expect(TTSModel.localAuto.resolved(.maximum) == .qwen17)
        #expect(STTModel.automatic.resolved(.medium) == .turbo)
        #expect(STTModel.automatic.resolved(.low) == .small)
    }
    @Test @MainActor func virtualMicrophoneChecksMuteAndOwnProcessBeforePlayback() throws {
        let playback = AudioPlayback(); playback.prepareOutput()
        let microphone = VirtualMicrophone(identifier: "local.stts.test.\(UUID().uuidString)", tapUUID: UUID())
        defer { try? microphone.remove() }
        try microphone.prepare()
        #expect(microphone.device != 0)
        try microphone.setSending(true)
        try microphone.setSending(false)
        try microphone.prepare() // Reuse the same device and tap, including after reconnect.
        try microphone.remove()
        #expect(microphone.device == 0)
    }
    @Test func languageCatalogMatchesModelCapabilities() {
        #expect(SpeechLanguages.tts(.gtts).count == 69)
        #expect(SpeechLanguages.tts(.qwen06).count == 10)
        #expect(SpeechLanguages.tts(.chatterV3).count == 23)
        #expect(SpeechLanguages.tts(.vox).count == 30)
        #expect(SpeechLanguages.stt(.turbo).count == 101)
        #expect(SpeechLanguages.stt(.asr06).count == 31)
        #expect(SpeechLanguages.stt(.nemotron).count == 33)
        #expect(SpeechLanguages.matching("ko", in: SpeechLanguages.stt(.nemotron), fallback: "auto") == "ko-KR")
        #expect(SpeechLanguages.matching("ko-KR", in: SpeechLanguages.stt(.turbo), fallback: "auto") == "ko")
        #expect(!SpeechLanguages.stt(.base).contains("yue"))
        #expect(SpeechLanguages.stt(.turbo).contains("yue"))
        #expect(SpeechLanguages.tts(.gtts).contains("fr-CA"))
    }
    @Test func cancelledMLXWorkerCannotStartAProcess() {
        let worker = MLXWorker(); worker.stop()
        do { _ = try worker.call(["command": "prepare", "model": "turbo"]); Issue.record("Started cancelled MLX worker") }
        catch { #expect(error is CancellationError) }
    }
    @Test func residentWorkerRespondsWithoutClosingPipe() throws {
        let worker = MLXWorker()
        defer { worker.stop(force: true) }
        #expect(try worker.call(["command": "ping"], timeout: 5)["ok"] as? Bool == true)
        #expect(try worker.call(["command": "ping"], timeout: 5)["ok"] as? Bool == true)
    }
    @Test func silenceDoesNotEnqueueWhisperWork() {
        var segmenter = SpeechSegmenter(maximumSeconds: 3)
        for _ in 0..<2000 { #expect(segmenter.feed([Float](repeating: 0, count: 512), probability: 0) == nil) }
        #expect(segmenter.flush() == nil)
    }
    @Test func speechKeepsPreRollAndOriginalClock() throws {
        var segmenter = SpeechSegmenter(maximumSeconds: 3)
        for _ in 0..<100 { _ = segmenter.feed([Float](repeating: 0, count: 512), probability: 0) }
        for _ in 0..<10 { #expect(segmenter.feed([Float](repeating: 0.2, count: 512), probability: 0.9) == nil) }
        var result: SpeechChunk?
        for _ in 0..<13 { result = segmenter.feed([Float](repeating: 0, count: 512), probability: 0) ?? result }
        let chunk = try #require(result)
        #expect(abs(chunk.start - 3) < 0.0001)
        #expect(chunk.samples.prefix(3200).allSatisfy { $0 == 0 })
        #expect(abs(chunk.end - 3.936) < 0.0001)
        #expect(segmenter.flush() == nil)
    }
    @Test func continuousSpeechSplitsWithoutRepeatingAudio() {
        var segmenter = SpeechSegmenter(maximumSeconds: 2)
        var chunks: [SpeechChunk] = []
        for _ in 0..<200 {
            if let chunk = segmenter.feed([Float](repeating: 0.2, count: 512), probability: 0.8) { chunks.append(chunk) }
        }
        if let final = segmenter.flush() { chunks.append(final) }
        #expect(chunks.reduce(0) { $0 + $1.samples.count } == 102400)
        for pair in zip(chunks, chunks.dropFirst()) { #expect(abs(pair.0.end - pair.1.start) < 0.0001) }
        #expect(chunks.allSatisfy { $0.samples.count <= 32512 })
    }
    @Test func singleNoiseSpikeIsNotSpeech() {
        var segmenter = SpeechSegmenter(maximumSeconds: 3)
        _ = segmenter.feed([Float](repeating: 0.1, count: 512), probability: 0.95)
        for _ in 0..<20 { #expect(segmenter.feed([Float](repeating: 0, count: 512), probability: 0) == nil) }
        #expect(segmenter.flush() == nil)
    }
    @Test func ttsRejectsBlankTextBeforeNetwork() async {
        do { _ = try await SpeechRequest().synthesize(text: "  ", language: "ko"); Issue.record("Accepted empty text") }
        catch { #expect(error.localizedDescription.contains("500")) }
    }
    @Test func cancelledRequestCannotStartChild() async {
        let request = SpeechRequest(); request.cancel()
        do { _ = try await request.synthesize(text: "테스트", language: "ko"); Issue.record("Started a cancelled request") }
        catch { #expect(error is CancellationError) }
    }
}
