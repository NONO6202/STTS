import SwiftUI
import AppKit

struct ComposerSuggestion: Equatable, Identifiable {
    let name, kind: String
    var id: String { name }
    static func matches(_ input: String, phrases: [String], sounds: [String]) -> [Self] {
        let query = input.trimmingCharacters(in: .whitespacesAndNewlines).precomposedStringWithCanonicalMapping.lowercased()
        guard !query.isEmpty else { return [] }
        let sounds = sounds.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
        let counts = Dictionary(grouping: sounds, by: { $0 }).mapValues(\.count)
        let names = Set(phrases)
        let items = phrases.map { Self(name: $0, kind: "단축어") }
            + sounds.filter { counts[$0] == 1 && !names.contains($0) }.map { Self(name: $0, kind: "사운드") }
        if items.contains(where: { $0.name == input.trimmingCharacters(in: .whitespacesAndNewlines) }) { return [] }
        return Array(items.filter { $0.name.precomposedStringWithCanonicalMapping.lowercased().hasPrefix(query) }
            .sorted { $0.name < $1.name }.prefix(5))
    }
}

struct ComposerView: View {
    @ObservedObject var state: AppState
    @ObservedObject var library: SoundboardLibrary
    private var text: String {
        get { state.composerDraft }
        nonmutating set { state.composerDraft = newValue }
    }
    @State private var composing = false
    @State private var selected = 0
    @State private var recallIndex: Int?
    @State private var recallDraft = ""
    @State private var recalledText: String?
    let resize: (Int) -> Void
    let close: () -> Void
    private var suggestions: [ComposerSuggestion] {
        composing || recallIndex != nil || Edition.isDemo ? [] : ComposerSuggestion.matches(text, phrases: Array(state.ttsPhrases.entries.keys), sounds: library.clips.map(\.name))
    }
    private func accept(_ name: String) { text = name; selected = 0 }
    private func submit() {
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, text.count <= AppContract.shared.limits.text else { return }
        if state.speak(text) { state.remember(text); text = ""; recallIndex = nil; close() } else { NSSound.beep() }
    }
    /// ↑/↓ walk through recently sent inputs, then back to the unsent draft.
    private func recall(_ direction: Int) -> Bool {
        let history = state.sentHistory
        guard !history.isEmpty else { return false }
        let current = recallIndex ?? history.count
        if recallIndex == nil { recallDraft = text }
        let next = max(0, min(history.count, current + direction))
        recallIndex = next == history.count ? nil : next
        text = next == history.count ? recallDraft : history[next]; recalledText = text
        return true
    }
    var body: some View {
        VStack(spacing: 0) {
            ComposingTextField(text: $state.composerDraft, composing: $composing, foreground: state.windowStyle.foreground, navigate: { direction in
                guard recallIndex != nil || suggestions.isEmpty else {
                    selected = (selected + direction + suggestions.count) % suggestions.count; return true
                }
                return recall(direction)
            }, complete: {
                guard !suggestions.isEmpty else { return nil }
                let name = suggestions[min(selected, suggestions.count - 1)].name; accept(name); return name
            }, submit: submit, cancel: close)
                .frame(maxWidth: .infinity).frame(height: 24).padding(.horizontal, 12).padding(.vertical, 10)
            if !suggestions.isEmpty {
                VStack(spacing: 0) {
                    ForEach(Array(suggestions.enumerated()), id: \.element.id) { index, item in
                        Button { accept(item.name) } label: {
                            HStack { Text(item.name).lineLimit(1); Spacer(); Text(L10n.text(item.kind)).font(.caption).opacity(0.65) }
                                .font(.system(size: 13)).padding(.horizontal, 12).frame(height: 32).contentShape(Rectangle())
                                .background(index == selected ? Theme.accent.opacity(0.18) : .clear, in: RoundedRectangle(cornerRadius: 8))
                        }.buttonStyle(.plain).accessibilityAddTraits(index == selected ? .isSelected : [])
                    }
                }.padding(.horizontal, 4).padding(.bottom, 8)
            }
        }.foregroundStyle(state.windowStyle.foreground.color)
            .background(state.windowStyle.background.color.opacity(state.windowStyle.opacity))
            .clipShape(RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(state.error == nil ? Color.primary.opacity(0.08) : Color.red, lineWidth: state.error == nil ? 0.5 : 1))
            .onChange(of: text) { _, value in
                selected = 0
                // Typing ends history browsing so suggestions return.
                if value != recalledText { recallIndex = nil; recalledText = nil }
            }
            .onChange(of: suggestions.count) { _, count in resize(count) }
            .help(L10n.message(state.error ?? "Tab 완성 · Enter 전송 · Esc 닫기"))
    }
}

struct ComposingTextField: NSViewRepresentable {
    @Binding var text: String
    @Binding var composing: Bool
    let foreground: Tint
    let navigate: (Int) -> Bool
    let complete: () -> String?
    let submit: () -> Void
    let cancel: () -> Void
    func makeCoordinator() -> Coordinator { Coordinator(self) }
    func makeNSView(context: Context) -> NSTextField {
        let field = FocusedTextField(string: text)
        field.placeholderString = L10n.text("입력 후 Enter")
        field.isBezeled = false; field.isBordered = false; field.drawsBackground = false
        field.focusRingType = .none
        field.cell?.usesSingleLineMode = true; field.cell?.isScrollable = true
        field.textColor = NSColor(foreground.color)
        field.font = .systemFont(ofSize: 16); field.delegate = context.coordinator
        return field
    }
    func updateNSView(_ field: NSTextField, context: Context) {
        context.coordinator.parent = self
        field.textColor = NSColor(foreground.color)
        // Never replace the field editor while an IME is composing.
        if (field.currentEditor() as? NSTextView)?.hasMarkedText() != true, field.stringValue != text {
            field.stringValue = text
            if let editor = field.currentEditor() as? NSTextView { editor.string = text; editor.setSelectedRange(NSRange(location: (text as NSString).length, length: 0)) }
            field.window?.makeFirstResponder(field)
        }
    }
    final class Coordinator: NSObject, NSTextFieldDelegate {
        var parent: ComposingTextField
        init(_ parent: ComposingTextField) { self.parent = parent }
        func controlTextDidChange(_ notification: Notification) {
            if let field = notification.object as? NSTextField { parent.composing = (field.currentEditor() as? NSTextView)?.hasMarkedText() == true; parent.text = field.stringValue }
        }
        func control(_ control: NSControl, textView: NSTextView, doCommandBy selector: Selector) -> Bool {
            if textView.hasMarkedText() || (textView as? CompositionEditor)?.keyBeganWithMarkedText == true { return false }
            if selector == #selector(NSResponder.moveDown(_:)), parent.navigate(1) { return true }
            if selector == #selector(NSResponder.moveUp(_:)), parent.navigate(-1) { return true }
            if selector == #selector(NSResponder.insertTab(_:)), let name = parent.complete() {
                control.stringValue = name; textView.string = name
                textView.setSelectedRange(NSRange(location: (name as NSString).length, length: 0)); return true
            }
            if selector == #selector(NSResponder.insertNewline(_:)) {
                parent.text = control.stringValue; parent.submit(); return true
            }
            if selector == #selector(NSResponder.cancelOperation(_:)) {
                parent.cancel(); return true
            }
            return false
        }
    }
}

final class FocusedTextField: NSTextField {
    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        guard let window else { return }
        window.initialFirstResponder = self
        DispatchQueue.main.async { [weak self, weak window] in
            guard let self, let window, window.isVisible else { return }
            if let panel = window as? InputPanel { panel.focusInput() }
            else { window.makeFirstResponder(self) }
        }
    }
}

final class CompositionEditor: NSTextView {
    private(set) var keyBeganWithMarkedText = false
    override func keyDown(with event: NSEvent) {
        keyBeganWithMarkedText = hasMarkedText()
        defer { keyBeganWithMarkedText = false }
        super.keyDown(with: event)
    }
}

final class InputPanel: NSPanel, NSWindowDelegate {
    private lazy var editor: CompositionEditor = {
        let editor = CompositionEditor(); editor.isFieldEditor = true; return editor
    }()
    override var canBecomeKey: Bool { true }
    func showForTyping() {
        NSApp.activate(ignoringOtherApps: true)
        makeKeyAndOrderFront(nil)
        focusInput()
        DispatchQueue.main.async { [weak self] in
            guard let self, self.isVisible else { return }
            self.makeKey(); self.focusInput()
        }
    }
    func focusInput() {
        guard let field = initialFirstResponder as? NSTextField else { return }
        makeFirstResponder(field)
        if let editor = field.currentEditor() as? NSTextView {
            editor.setSelectedRange(NSRange(location: (field.stringValue as NSString).length, length: 0))
        }
    }
    func windowDidBecomeKey(_ notification: Notification) { focusInput() }
    func windowWillReturnFieldEditor(_ sender: NSWindow, to client: Any?) -> Any? {
        client is NSTextField ? editor : nil
    }
}
