import Foundation
import Testing
@testable import STTS

@Suite(.serialized) struct SpeechQueueTests {
    @Test @MainActor func pendingInputKeepsOrderAndCancellationClearsIt() {
        let state = AppState()
        state.speaking = true
        #expect(state.speak("첫 번째"))
        #expect(state.speak("두 번째"))
        #expect(!state.speak("   "))
        #expect(!state.speak(String(repeating: "가", count: 501)))
        #expect(!state.speak("preview", preview: true))
        #expect(state.speechQueue == ["첫 번째", "두 번째"])
        #expect(state.speaking)
        state.cancelSpeech()
        #expect(state.speechQueue.isEmpty && !state.speaking)
    }
    @Test @MainActor func composerDraftSurvivesClosingOnlyWhenEnabled() {
        let defaults = UserDefaults.standard, key = "keepComposerDraft", saved = defaults.object(forKey: "keepComposerDraft")
        defer { if let saved { defaults.set(saved, forKey: key) } else { defaults.removeObject(forKey: key) } }
        defaults.removeObject(forKey: key)
        let state = AppState()
        #expect(state.keepComposerDraft)
        state.composerDraft = "작성 중인 문장"
        state.composerClosed()
        #expect(state.composerDraft == "작성 중인 문장")
        state.keepComposerDraft = false
        #expect(!AppState().keepComposerDraft)
        state.composerClosed()
        #expect(state.composerDraft.isEmpty)
    }
}
