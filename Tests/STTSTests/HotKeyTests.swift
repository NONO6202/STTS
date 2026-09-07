import AppKit
import Carbon
import Testing
@testable import STTS

@Suite struct HotKeyTests {
    @Test @MainActor func hotKeysDispatchOnlyTheirOwnEvent() throws {
        _ = NSApplication.shared
        let modifiers = NSEvent.ModifierFlags([.command, .control, .option, .shift]).rawValue
        var firstCount = 0, secondCount = 0
        let first = try GlobalHotKey(shortcut: Shortcut(keyCode: UInt32(kVK_F17), modifiers: modifiers, key: ""), identifier: 101) { firstCount += 1 }
        let second = try GlobalHotKey(shortcut: Shortcut(keyCode: UInt32(kVK_F18), modifiers: modifiers, key: ""), identifier: 102) { secondCount += 1 }
        try withExtendedLifetime((first, second)) {
            func send(_ identifier: UInt32) throws {
                var createdEvent: EventRef?
                #expect(CreateEvent(nil, OSType(kEventClassKeyboard), UInt32(kEventHotKeyPressed), 0, 0, &createdEvent) == noErr)
                let event = try #require(createdEvent)
                defer { ReleaseEvent(event) }
                var id = EventHotKeyID(signature: 0x53545453, id: identifier)
                #expect(SetEventParameter(event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID), MemoryLayout<EventHotKeyID>.size, &id) == noErr)
                #expect(SendEventToEventTarget(event, GetApplicationEventTarget()) == noErr)
            }
            try send(101)
            #expect(firstCount == 1 && secondCount == 0)
            try send(102)
            #expect(firstCount == 1 && secondCount == 1)
        }
    }

    @Test @MainActor func shortcutConflictsIgnoreDisplayText() {
        let state = AppState()
        let input = state.shortcut, captions = state.captionShortcut
        state.setShortcut(Shortcut(keyCode: captions.keyCode, modifiers: captions.modifiers, key: "different display text"))
        #expect(state.shortcut == input)
        #expect(state.error != nil)
        state.error = nil
        state.setCaptionShortcut(Shortcut(keyCode: input.keyCode, modifiers: input.modifiers, key: "different display text"))
        #expect(state.captionShortcut == captions)
        #expect(state.error != nil)
    }

    @Test @MainActor func captionsCheckboxAndShortcutShareStartAndStop() {
        let state = AppState()
        #expect(!state.sttEnabled && !state.preparing && !state.listening)
        // Cancel synchronously before the preparation task runs: no models or audio are accessed.
        state.toggleCaptions()
        #expect(state.sttEnabled && state.preparing)
        state.toggleCaptions()
        #expect(!state.sttEnabled && !state.preparing && !state.listening)
        state.sttEnabled = true
        #expect(state.preparing)
        state.stop()
        #expect(!state.sttEnabled && !state.preparing && !state.listening)
        state.sttEnabled = true
        state.sttEnabled = false
        #expect(!state.preparing && !state.listening)
    }
}
