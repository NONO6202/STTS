import Foundation
import AVFoundation
import Testing
@testable import STTS

@Suite(.serialized) struct MicrophonePassthroughTests {
    @MainActor private final class Route: MicrophoneRouting {
        var preparations = 0, preparationFailures = 0, sendingFailures = 0
        var removalAllowed = false
        var sending = false, monitoring = false
        func prepare() throws {
            preparations += 1
            if preparationFailures > 0 { preparationFailures -= 1; throw AppFailure("route unavailable") }
        }
        func setSending(_ sending: Bool, monitoring: Bool, requireDevice: Bool) throws {
            if sending && sendingFailures > 0 { sendingFailures -= 1; throw AppFailure("stale route") }
            self.sending = sending; self.monitoring = monitoring
        }
        func remove() { #expect(removalAllowed, "Recovery must not remove the virtual microphone") }
    }
    private final class Capture: LiveMicrophoneCapture {
        var healthy = false, starts = 0, failures = 0
        var beforeStart: () -> Void = {}
        func start(deviceUID: String, volume: Double) throws {
            beforeStart(); starts += 1
            #expect(deviceUID == "selected-input")
            #expect(volume == 0.37)
            if failures > 0 { failures -= 1; throw AppFailure("capture unavailable") }
            healthy = true
        }
        func stop() { healthy = false }
        func setVolume(_ value: Double) {}
        func setEffects(pitch: Double, filter: String, strength: Double) {}
    }
    @MainActor private func retryPreferences() -> () -> Void {
        let keys = ["ttsEnabled", "liveMicrophoneEnabled", "liveMicrophoneUID", "liveMicrophoneVolume"]
        let defaults = UserDefaults.standard
        let saved = keys.map { ($0, defaults.object(forKey: $0)) }
        Preferences.save(true, key: "ttsEnabled")
        Preferences.save(false, key: "liveMicrophoneEnabled")
        Preferences.save("selected-input", key: "liveMicrophoneUID")
        Preferences.save(0.37, key: "liveMicrophoneVolume")
        return { for (key, value) in saved { if let value { defaults.set(value, forKey: key) } else { defaults.removeObject(forKey: key) } } }
    }
    @MainActor private func settle(_ state: AppState) async {
        for _ in 0..<100 {
            if state.liveMicrophoneStatus != "마이크 연결 중…" { return }
            await Task.yield()
        }
        Issue.record("Microphone startup did not finish")
    }
    @MainActor private func reconnect(_ state: AppState) async throws {
        for _ in 0..<120 {
            if state.liveMicrophoneActive { return }
            try await Task.sleep(for: .milliseconds(25))
        }
        Issue.record("Microphone did not reconnect automatically")
    }
    @Test @MainActor func failedPreparationCanRetryWithoutCyclingTTS() async throws {
        let restore = retryPreferences(); defer { restore() }
        let route = Route(), capture = Capture()
        route.preparationFailures = 1
        capture.beforeStart = { #expect(route.sending && !route.monitoring) }
        let state = AppState(microphone: route, liveMicrophone: capture, requestMicrophoneAccess: { true })
        defer { state.shutdown() }
        state.liveMicrophoneEnabled = true
        await settle(state)
        #expect(state.liveMicrophoneEnabled && !state.liveMicrophoneActive && !state.microphoneReady && state.ttsEnabled)
        #expect(capture.starts == 0 && state.error != nil)
        #expect(Preferences.read("liveMicrophoneEnabled", fallback: false))
        try await reconnect(state)
        #expect(state.liveMicrophoneEnabled && state.microphoneReady && state.ttsEnabled)
        #expect(capture.healthy && route.preparations == 2 && state.error == nil)
    }
    @Test @MainActor func permissionCanBeGrantedAfterDeniedAttempt() async throws {
        let restore = retryPreferences(); defer { restore() }
        let route = Route(), capture = Capture()
        var allowed = false
        let state = AppState(microphone: route, liveMicrophone: capture, requestMicrophoneAccess: { allowed })
        defer { state.shutdown() }
        state.liveMicrophoneEnabled = true
        await settle(state)
        #expect(state.liveMicrophoneEnabled && !state.liveMicrophoneActive && state.ttsEnabled)
        #expect(route.preparations == 0 && capture.starts == 0)
        allowed = true
        try await reconnect(state)
        #expect(state.liveMicrophoneEnabled && capture.healthy && state.error == nil)
    }
    @Test @MainActor func captureFailureRefreshesRouteOnNextAttempt() async throws {
        let restore = retryPreferences(); defer { restore() }
        let route = Route(), capture = Capture()
        capture.failures = 1
        capture.beforeStart = { #expect(route.sending && !route.monitoring) }
        let state = AppState(microphone: route, liveMicrophone: capture, requestMicrophoneAccess: { true })
        defer { state.shutdown() }
        state.connectMicrophone()
        state.liveMicrophoneEnabled = true
        await settle(state)
        #expect(state.liveMicrophoneEnabled && !state.liveMicrophoneActive && !route.sending && state.ttsEnabled)
        try await reconnect(state)
        #expect(capture.starts == 2 && capture.healthy && state.liveMicrophoneEnabled)
        #expect(route.preparations == 2 && state.error == nil)
    }
    @Test @MainActor func staleRouteIsRepairedBeforeCapture() async {
        let restore = retryPreferences(); defer { restore() }
        let route = Route(), capture = Capture()
        let state = AppState(microphone: route, liveMicrophone: capture, requestMicrophoneAccess: { true })
        defer { state.shutdown() }
        state.connectMicrophone()
        route.sendingFailures = 1
        capture.beforeStart = { #expect(route.sending && !route.monitoring && route.preparations == 2) }
        state.liveMicrophoneEnabled = true
        await settle(state)
        #expect(state.liveMicrophoneEnabled && capture.healthy && state.ttsEnabled && state.error == nil)
    }
    @Test @MainActor func ttsMonitoringNeverUnmutesTheLiveMicrophoneRoute() async {
        let restore = retryPreferences(); defer { restore() }
        let defaults = UserDefaults.standard, saved = defaults.object(forKey: "voiceMonitoring")
        defer { if let saved { defaults.set(saved, forKey: "voiceMonitoring") } else { defaults.removeObject(forKey: "voiceMonitoring") } }
        Preferences.save(true, key: "voiceMonitoring")
        let route = Route(), capture = Capture()
        let state = AppState(microphone: route, liveMicrophone: capture, requestMicrophoneAccess: { true })
        defer { state.shutdown() }
        state.liveMicrophoneEnabled = true
        await settle(state)
        #expect(state.voiceMonitoring && state.liveMicrophoneEnabled && route.sending)
        #expect(!route.monitoring)
        state.liveMicrophoneEnabled = false
        #expect(state.voiceMonitoring && !route.sending && !route.monitoring)
    }
    @Test @MainActor func unverifiedRouteNeverStartsCaptureAndRemainsRetryable() async throws {
        let restore = retryPreferences(); defer { restore() }
        let route = Route(), capture = Capture()
        let state = AppState(microphone: route, liveMicrophone: capture, requestMicrophoneAccess: { true })
        defer { state.shutdown() }
        state.connectMicrophone()
        route.sendingFailures = 2
        state.liveMicrophoneEnabled = true
        await settle(state)
        #expect(capture.starts == 0 && !state.microphoneReady && state.liveMicrophoneEnabled && !state.liveMicrophoneActive)
        try await reconnect(state)
        #expect(capture.healthy && state.liveMicrophoneEnabled && state.ttsEnabled && state.error == nil)
    }
    @Test @MainActor func disconnectedCaptureCanRestartWithTTSStillEnabled() async throws {
        let restore = retryPreferences(); defer { restore() }
        let route = Route(), capture = Capture()
        let state = AppState(microphone: route, liveMicrophone: capture, requestMicrophoneAccess: { true })
        defer { state.shutdown() }
        state.liveMicrophoneEnabled = true
        await settle(state)
        capture.healthy = false
        for _ in 0..<30 {
            if !state.liveMicrophoneActive { break }
            try await Task.sleep(for: .milliseconds(50))
        }
        #expect(state.liveMicrophoneEnabled && !state.liveMicrophoneActive && !route.sending && state.ttsEnabled)
        #expect(Preferences.read("liveMicrophoneEnabled", fallback: false))
        try await reconnect(state)
        #expect(capture.healthy && capture.starts == 2 && route.preparations == 2)
        #expect(state.liveMicrophoneEnabled && state.error == nil)
    }
    @Test @MainActor func disablingOrShuttingDownCancelsPendingRecovery() async throws {
        let restore = retryPreferences(); defer { restore() }
        for action in ["microphone", "tts", "shutdown"] {
            let route = Route(), capture = Capture()
            route.preparationFailures = 1
            let state = AppState(microphone: route, liveMicrophone: capture, requestMicrophoneAccess: { true })
            state.liveMicrophoneEnabled = true
            await settle(state)
            if action == "microphone" { state.liveMicrophoneEnabled = false }
            else if action == "tts" { route.removalAllowed = true; state.ttsEnabled = false }
            else { state.shutdown() }
            try await Task.sleep(for: .milliseconds(2200))
            #expect(capture.starts == 0 && route.preparations == 1 && !state.liveMicrophoneActive)
            state.shutdown()
            Preferences.save(true, key: "ttsEnabled"); Preferences.save(false, key: "liveMicrophoneEnabled")
        }
    }
    @Test func formatChangesConvertInsteadOfDisconnecting() throws {
        let mic = MicrophonePassthrough()
        for (rate, channels, type) in [(44100.0, AVAudioChannelCount(2), AVAudioCommonFormat.pcmFormatFloat32),
                                       (16000.0, AVAudioChannelCount(1), AVAudioCommonFormat.pcmFormatInt16)] {
            let format = try #require(AVAudioFormat(commonFormat: type, sampleRate: rate, channels: channels, interleaved: false))
            let input = try #require(AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(rate / 10)))
            input.frameLength = input.frameCapacity
            for channel in 0..<Int(channels) {
                if let samples = input.floatChannelData?[channel] { samples.update(repeating: 0.25, count: Int(input.frameLength)) }
                if let samples = input.int16ChannelData?[channel] { samples.update(repeating: 8192, count: Int(input.frameLength)) }
            }
            let output = try mic.convert(input)
            #expect(output.format.sampleRate == 48000 && output.format.channelCount == 1)
            #expect(output.frameLength > 0)
            let samples = try #require(output.floatChannelData?[0])
            #expect(UnsafeBufferPointer(start: samples, count: Int(output.frameLength)).allSatisfy { $0.isFinite })
            #expect((0..<Int(output.frameLength)).contains { abs(samples[$0]) > 0.1 })
        }
    }
    @Test @MainActor func freshPreferenceIsOffAndTTSDisabledPreventsCapture() {
        let defaults = UserDefaults.standard, saved = defaults.object(forKey: "ttsEnabled")
        let savedMic = defaults.object(forKey: "liveMicrophoneEnabled")
        defer {
            if let saved { defaults.set(saved, forKey: "ttsEnabled") } else { defaults.removeObject(forKey: "ttsEnabled") }
            if let savedMic { defaults.set(savedMic, forKey: "liveMicrophoneEnabled") } else { defaults.removeObject(forKey: "liveMicrophoneEnabled") }
        }
        defaults.removeObject(forKey: "liveMicrophoneEnabled")
        Preferences.save(false, key: "ttsEnabled")
        let state = AppState()
        #expect(!state.liveMicrophoneEnabled)
        state.liveMicrophoneEnabled = true
        #expect(!state.liveMicrophoneEnabled)
        #expect(state.error != nil)
        state.cancelSpeech()
        #expect(AppState().liveMicrophoneEnabled)
        state.shutdown()
    }
    @Test @MainActor func shutdownPreservesSavedMicrophonePreference() {
        let defaults = UserDefaults.standard, key = "liveMicrophoneEnabled", saved = defaults.object(forKey: "liveMicrophoneEnabled")
        defer { if let saved { defaults.set(saved, forKey: key) } else { defaults.removeObject(forKey: key) } }
        Preferences.save(true, key: key)
        let state = AppState()
        #expect(state.liveMicrophoneEnabled)
        state.shutdown()
        #expect(AppState().liveMicrophoneEnabled)
    }
    @Test func missingMicrophoneNeverFallsBackAndStopIsIdempotent() {
        let mic = MicrophonePassthrough()
        #expect(throws: (any Error).self) { try mic.start(deviceUID: "missing-stts-test-device", volume: 1) }
        #expect(!mic.healthy)
        mic.setVolume(.nan)
        mic.stop(); mic.stop()
        #expect(!mic.healthy)
    }
    @Test func inputListExcludesVirtualAndAggregateDevices() {
        #expect(AudioHardware.physicalInputs().allSatisfy { !$0.isVirtual })
    }
}
