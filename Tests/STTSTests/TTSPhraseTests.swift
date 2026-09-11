import AppKit
import SwiftUI
import Testing
@testable import STTS

@Suite struct TTSPhraseTests {
    @Test func expandsOnlyTheWholeInputOnce() throws {
        var phrases = TTSPhrases()
        try phrases.save(shortcut: " 안녕 ", phrase: " 안녕하세요 ")
        try phrases.save(shortcut: "안녕하세요", phrase: "반갑습니다")
        #expect(phrases.expand("\n안녕 ") == "안녕하세요")
        #expect(phrases.expand("안녕 친구야") == "안녕 친구야")
        #expect(phrases.expand("안녕!") == "안녕!")
        #expect(phrases.expand("평범한 문장") == "평범한 문장")
    }

    @Test func editingAndDeletingPersistWithoutOverwritingDuplicateEntries() throws {
        let key = "test.ttsPhrases." + UUID().uuidString
        defer { UserDefaults.standard.removeObject(forKey: key) }
        var phrases = TTSPhrases()
        try phrases.save(shortcut: "안녕", phrase: "안녕하세요")
        try phrases.save(shortcut: "감사", phrase: "감사합니다")
        #expect(throws: AppFailure.self) { try phrases.save(shortcut: " 안녕 ", phrase: "덮어쓰기") }
        #expect(throws: AppFailure.self) { try phrases.save(shortcut: "감사", phrase: "덮어쓰기", replacing: "안녕") }
        #expect(phrases.expand("안녕") == "안녕하세요")
        try phrases.save(shortcut: " 인사 ", phrase: " 만나서 반갑습니다 ", replacing: "안녕")
        Preferences.save(phrases, key: key)
        var restored = Preferences.read(key, fallback: TTSPhrases())
        #expect(restored == phrases)
        #expect(restored.expand("인사") == "만나서 반갑습니다")
        #expect(restored.expand("안녕") == "안녕")
        restored.remove("인사")
        Preferences.save(restored, key: key)
        #expect(Preferences.read(key, fallback: TTSPhrases()).entries == ["감사": "감사합니다"])
    }

    @Test func rejectsSoundNameCollisionsWithoutChangingExistingPhrases() throws {
        var phrases = TTSPhrases()
        try phrases.save(shortcut: "인사", phrase: "안녕하세요")
        let saved = phrases
        for original in [nil, "인사"] as [String?] {
            #expect(throws: AppFailure.self) { try phrases.save(shortcut: " 박수 ".decomposedStringWithCanonicalMapping, phrase: "변경", replacing: original, soundNames: ["박수"]) }
            #expect(phrases == saved)
        }
    }

    @Test func rejectsEmptyAndOversizedValuesWithoutChangingSavedPhrases() throws {
        var phrases = TTSPhrases()
        let maximum = String(repeating: "가", count: 500)
        try phrases.save(shortcut: "긴문장", phrase: maximum)
        let saved = phrases
        for (shortcut, phrase) in [(" ", "내용"), ("입력", "\n"), (maximum + "가", "내용"), ("입력", maximum + "가")] {
            #expect(throws: AppFailure.self) { try phrases.save(shortcut: shortcut, phrase: phrase, replacing: "긴문장") }
            #expect(phrases == saved)
        }
        #expect(phrases.expand("긴문장").count == 500)
    }

    @Test @MainActor func rendersTheShortcutSettings() throws {
        var phrases = TTSPhrases()
        try phrases.save(shortcut: "안녕", phrase: "안녕하세요")
        try phrases.save(shortcut: "감사", phrase: "감사합니다. 잠시 후 다시 말씀드리겠습니다.")
        let view = NSHostingView(rootView: TTSShortcutsView(phrases: .constant(phrases)).padding(18)
            .background(Color(nsColor: .windowBackgroundColor)))
        view.frame = NSRect(x: 0, y: 0, width: 564, height: 450)
        view.layoutSubtreeIfNeeded()
        let bitmap = try #require(view.bitmapImageRepForCachingDisplay(in: view.bounds))
        view.cacheDisplay(in: view.bounds, to: bitmap)
        let output = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent(".validation/tts-phrases/settings.png")
        try FileManager.default.createDirectory(at: output.deletingLastPathComponent(), withIntermediateDirectories: true)
        try #require(bitmap.representation(using: .png, properties: [:])).write(to: output)
        let state = AppState(); state.speaking = true; state.ttsStatus = "음성 생성 중…"
        let main = NSHostingView(rootView: MainView(state: state))
        main.frame = NSRect(x: 0, y: 0, width: AppContract.shared.window.width, height: AppContract.shared.window.height)
        main.layoutSubtreeIfNeeded()
        let statusBitmap = try #require(main.bitmapImageRepForCachingDisplay(in: main.bounds))
        main.cacheDisplay(in: main.bounds, to: statusBitmap)
        try #require(statusBitmap.representation(using: .png, properties: [:])).write(to: output.deletingLastPathComponent().appendingPathComponent("status-pill.png"))
    }
}
