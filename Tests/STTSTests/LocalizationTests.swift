import Foundation
import AppKit
import SwiftUI
import Testing
@testable import STTS

@Suite(.serialized) struct LocalizationTests {
    @Test func languageMatching() {
        for (requested, expected) in [("ko-KR", "ko"), ("en-GB", "en"), ("ja-JP", "ja"), ("zh-TW", "zh-Hans"), ("es-MX", "es"), ("fr-CA", "fr"), ("de-DE", "de"), ("pt_BR", "pt"), ("ar-SA", "en")] {
            #expect(L10n.uiLanguage(for: [requested]) == expected)
        }
        #expect(L10n.speechLanguage(for: ["ja-JP"], supported: ["en", "ja"]) == "ja")
        #expect(L10n.speechLanguage(for: ["zh-TW"], supported: ["zh-CN", "zh-TW", "en"]) == "zh-TW")
        #expect(L10n.speechLanguage(for: ["ar-SA"], supported: ["ar", "en"]) == "ar")
        #expect(L10n.speechLanguage(for: ["de-DE"], supported: ["en", "ko"]) == "en")
        #expect(L10n.speechLanguage(for: ["de-DE"], supported: ["ko"]) == "ko")
        #expect(L10n.speechLanguage(for: ["zh-Hans"], supported: ["zh", "zh-CN", "en"]) == "zh-CN")
        #expect(L10n.speechLanguage(for: ["zh-Hant-HK"], supported: ["zh", "zh-CN", "zh-TW"]) == "zh-TW")
    }
    @Test func catalogAndMessages() {
        let keys = Set(L10n.catalog.strings["en"]!.keys)
        for language in L10n.supported where language != "ko" {
            #expect(Set(L10n.catalog.strings[language]!.keys) == keys)
            #expect(L10n.catalog.languageNames[language]?["ko"] != nil)
        }
        if L10n.language == "en" {
            #expect(L10n.message("내 파일 재생 중…") == "Playing 내 파일…")
            #expect(L10n.text("시스템 언어 · {0}", "日本語") == "System language · 日本語")
        }
        #expect(L10n.message("내 원문 그대로") == "내 원문 그대로")
    }
    @Test @MainActor func automaticAndManualLanguagePersistence() throws {
        let defaults = UserDefaults.standard
        let keys = ["ttsLanguage", "ttsFollowsSystem", "ttsModel", "ttsLevel", "ttsVoice", "setupCompleted"]
        let saved = keys.map { defaults.object(forKey: $0) }
        defer {
            for (key, value) in zip(keys, saved) {
                if let value { defaults.set(value, forKey: key) } else { defaults.removeObject(forKey: key) }
            }
        }
        for key in keys { defaults.removeObject(forKey: key) }
        Preferences.save(true, key: "setupCompleted")
        let fresh = AppState()
        #expect(fresh.ttsFollowsSystem)
        #expect(fresh.ttsLanguage == L10n.speechLanguage(for: L10n.preferredLanguages, supported: fresh.ttsLanguages))
        let view = NSHostingView(rootView: MainView(state: fresh))
        view.frame = NSRect(x: 0, y: 0, width: 600, height: 740)
        view.layoutSubtreeIfNeeded()
        let bitmap = try #require(view.bitmapImageRepForCachingDisplay(in: view.bounds))
        view.cacheDisplay(in: view.bounds, to: bitmap)
        let output = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent(".build/localization-mac-" + L10n.language + ".png")
        try #require(bitmap.representation(using: .png, properties: [:])).write(to: output)
        fresh.selectTTSLanguage("ja")
        let manual = AppState()
        #expect(!manual.ttsFollowsSystem && manual.ttsLanguage == "ja")
        manual.selectTTSLanguage("system")
        #expect(AppState().ttsFollowsSystem)
        defaults.removeObject(forKey: "ttsFollowsSystem")
        Preferences.save("fr", key: "ttsLanguage")
        let legacy = AppState()
        #expect(!legacy.ttsFollowsSystem && legacy.ttsLanguage == "fr")
    }
}
