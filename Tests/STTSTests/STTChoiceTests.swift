import Foundation
import Testing
@testable import STTS

@Suite(.serialized) struct STTChoiceTests {
    @Test @MainActor func choicesSelectTheRequestedModels() {
        let defaults = UserDefaults.standard
        let keys = ["level", "sttModel", "sttLanguage"]
        let saved = keys.map { defaults.object(forKey: $0) }
        defer {
            for (key, value) in zip(keys, saved) {
                if let value { defaults.set(value, forKey: key) } else { defaults.removeObject(forKey: key) }
            }
        }
        let state = AppState()
        #expect(ResourceLevel.sttSpecifications.map(\.sttLabel) == ["기본", "낮음", "높음"])
        for (choice, model) in [(ResourceLevel.medium, STTModel.turbo), (.low, .small), (.high, .large)] {
            state.sttChoice = choice
            #expect(state.sttChoice == choice)
            #expect(state.selectedSTTModel == model)
            #expect(state.sttLanguages.contains("auto") && state.sttLanguages.contains("ko"))
        }
        for model in STTModel.allCases {
            state.sttModel = model
            for level in ResourceLevel.allCases {
                state.level = level
                #expect(ResourceLevel.sttSpecifications.contains(state.sttChoice))
                #expect([STTModel.small, .turbo, .large].contains(state.selectedSTTModel))
            }
        }
    }

    @Test @MainActor func ttsChoicesAndLegacySettingsResolveToFourTiers() {
        let keys = ["ttsModel", "ttsLevel", "ttsLanguage", "ttsVoice", "clonedVoices", "selectedCloneID"]
        let defaults = UserDefaults.standard, saved = keys.map { UserDefaults.standard.object(forKey: $0) }
        defer {
            for (key, value) in zip(keys, saved) {
                if let value { defaults.set(value, forKey: key) } else { defaults.removeObject(forKey: key) }
            }
        }
        let state = AppState()
        let voices = [VoiceProfile(id: UUID(), name: "목소리 A", sourceName: "a.mp3", transcript: "첫 번째 대본"),
                      VoiceProfile(id: UUID(), name: "목소리 B", sourceName: "b.mp3", transcript: "두 번째 대본")]
        state.clonedVoices = voices
        #expect(ResourceLevel.ttsSpecifications.map(\.ttsLabel) == ["기본", "낮음", "중간", "높음"])
        for (choice, model) in [(ResourceLevel.minimum, TTSModel.gtts), (.low, .supertonic3), (.medium, .qwen06), (.high, .qwen17)] {
            state.ttsChoice = choice
            #expect(state.selectedTTSModel == model)
            #expect(state.supportsVoiceClone == [.medium, .high].contains(choice))
            #expect(state.ttsLanguages.contains("ko"))
            state.selectedCloneID = nil
            #expect(state.ttsWorkerModel == model.rawValue + (state.supportsVoiceClone ? "Custom" : ""))
            let voice = state.ttsVoice
            if state.supportsVoiceClone { #expect(state.presetVoices.contains("Sohee") && state.presetVoices.count == 9) }
            if state.supportsVoiceClone {
                state.selectedVoice = "Ryan"
                #expect(state.selectedVoice == "Ryan" && state.ttsWorkerModel == model.rawValue + "Custom")
                for profile in voices {
                    state.selectedVoice = profile.selection
                    #expect(state.selectedVoice == profile.selection && state.ttsWorkerModel == model.rawValue)
                    #expect(state.activeClonedVoice?.transcript == profile.transcript)
                    #expect(state.activeClonedVoice?.audioURL() == profile.audioURL())
                }
                state.selectedVoice = "Sohee"
                #expect(state.selectedCloneID == nil && state.ttsWorkerModel == model.rawValue + "Custom")
            } else {
                state.selectedCloneID = voices[0].id
                #expect(state.activeClonedVoice == nil && state.ttsWorkerModel == model.rawValue)
                #expect(state.ttsVoice == voice)
            }
        }
        state.ttsVoice = "Sohee"
        state.ttsModel = .chatterV3
        #expect(state.selectedTTSModel == .supertonic3 && state.ttsVoice == "F1")
        state.ttsChoice = .medium
        #expect(state.ttsVoice == "Sohee")
        for model in TTSModel.allCases {
            state.ttsModel = model
            for level in ResourceLevel.allCases {
                state.ttsLevel = level
                #expect(ResourceLevel.ttsSpecifications.contains(state.ttsChoice))
                #expect([TTSModel.gtts, .supertonic3, .qwen06, .qwen17].contains(state.selectedTTSModel))
            }
        }
        state.ttsChoice = .high
        state.selectedVoice = voices[1].selection
        let reopened = AppState()
        #expect(reopened.clonedVoices == voices)
        #expect(reopened.activeClonedVoice == voices[1])
    }
}
