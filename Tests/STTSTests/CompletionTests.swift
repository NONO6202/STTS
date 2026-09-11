import AppKit
import SwiftUI
import Testing
@testable import STTS

@Suite struct CompletionTests {
    @Test func suggestionsUsePrefixesAndKeepExecutionNamesUnambiguous() {
        let phrases = ["인사", "인사말", "Hello"]
        let sounds = ["인사", "인사음", "중복", "중복 "]
        let matches = ComposerSuggestion.matches("인", phrases: phrases, sounds: sounds)
        #expect(matches.map(\.name) == ["인사", "인사말", "인사음"])
        #expect(matches.map(\.kind) == ["단축어", "단축어", "사운드"])
        #expect(ComposerSuggestion.matches("", phrases: phrases, sounds: sounds).isEmpty)
        #expect(ComposerSuggestion.matches("인사", phrases: phrases, sounds: sounds).isEmpty)
        #expect(ComposerSuggestion.matches("문장 인", phrases: phrases, sounds: sounds).isEmpty)
        #expect(ComposerSuggestion.matches("중", phrases: phrases, sounds: sounds).isEmpty)
        #expect(ComposerSuggestion.matches("he", phrases: phrases, sounds: sounds).first?.name == "Hello")
        #expect(ComposerSuggestion.matches("인".decomposedStringWithCanonicalMapping, phrases: phrases, sounds: sounds) == matches)
        #expect(ComposerSuggestion.matches("a", phrases: (0..<10).map { "a\($0)" }, sounds: []).count == 5)
    }

    @Test @MainActor func tabCompletesWithoutSubmittingAndLeavesIMEKeysAlone() {
        var text = "인", composing = false, sends = 0, moves = 0
        let view = ComposingTextField(text: Binding(get: { text }, set: { text = $0 }), composing: Binding(get: { composing }, set: { composing = $0 }), foreground: .init(.black), navigate: { moves += $0; return true }, complete: { text = "인사말"; return text }, submit: { sends += 1 }, cancel: {})
        let coordinator = view.makeCoordinator(), field = NSTextField(string: "인"), editor = NSTextView()
        #expect(coordinator.control(field, textView: editor, doCommandBy: #selector(NSResponder.insertTab(_:))))
        #expect(field.stringValue == "인사말" && editor.string == "인사말" && sends == 0)
        #expect(coordinator.control(field, textView: editor, doCommandBy: #selector(NSResponder.moveDown(_:))))
        #expect(moves == 1)
        final class MarkedEditor: NSTextView { override func hasMarkedText() -> Bool { true } }
        let marked = MarkedEditor()
        for command in [#selector(NSResponder.insertTab(_:)), #selector(NSResponder.moveDown(_:)), #selector(NSResponder.insertNewline(_:))] {
            #expect(!coordinator.control(field, textView: marked, doCommandBy: command))
        }
        #expect(moves == 1 && sends == 0)
    }
}
