import AppKit
import Carbon

@MainActor final class GlobalHotKey {
    private var reference: EventHotKeyRef?
    private var handler: EventHandlerRef?
    let action: () -> Void
    private var binding: Shortcut?
    private var localMonitor: Any?
    private let identifier: UInt32
    init(shortcut: Shortcut, identifier: UInt32 = 1, action: @escaping () -> Void) throws {
        self.action = action
        self.identifier = identifier
        var type = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        let status = InstallEventHandler(GetApplicationEventTarget(), { _, event, context in
            guard let event, let context else { return OSStatus(eventNotHandledErr) }
            let key = Unmanaged<GlobalHotKey>.fromOpaque(context).takeUnretainedValue()
            var pressed = EventHotKeyID()
            guard GetEventParameter(event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID), nil,
                                    MemoryLayout<EventHotKeyID>.size, nil, &pressed) == noErr,
                  pressed.signature == 0x53545453, pressed.id == key.identifier else { return OSStatus(eventNotHandledErr) }
            MainActor.assumeIsolated { key.action() }; return noErr
        }, 1, &type, Unmanaged.passUnretained(self).toOpaque(), &handler)
        guard status == noErr else { throw AppFailure("전역 단축키를 준비하지 못했습니다.") }
        try update(shortcut)
        localMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard let self, let binding = self.binding,
                  UInt32(event.keyCode) == binding.keyCode,
                  event.modifierFlags.intersection([.command, .control, .option, .shift]) == binding.flags else { return event }
            if !event.isARepeat { self.action() }
            return nil
        }
    }
    func update(_ shortcut: Shortcut) throws {
        guard binding != shortcut else { return }
        var candidate: EventHotKeyRef?
        let id = EventHotKeyID(signature: 0x53545453, id: identifier)
        guard RegisterEventHotKey(shortcut.keyCode, shortcut.carbonModifiers, id, GetApplicationEventTarget(), 0, &candidate) == noErr else { throw AppFailure("\(shortcut.label) 키를 등록할 수 없습니다. 다른 단축키를 선택해 주세요.") }
        if let reference { UnregisterEventHotKey(reference) }
        reference = candidate; binding = shortcut
    }
    deinit {
        if let localMonitor { NSEvent.removeMonitor(localMonitor) }
        if let reference { UnregisterEventHotKey(reference) }; if let handler { RemoveEventHandler(handler) }
    }
}
