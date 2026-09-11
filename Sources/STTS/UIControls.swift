import SwiftUI
import AppKit

struct SurfaceControls: View {
    @Binding var style: SurfaceStyle
    var body: some View {
        VStack(spacing: 10) {
            HStack {
                ColorPicker("배경", selection: Binding(get: { style.background.color }, set: { style.background = Tint($0) }), supportsOpacity: false)
                ColorPicker("글자", selection: Binding(get: { style.foreground.color }, set: { style.foreground = Tint($0) }), supportsOpacity: false)
            }
            HStack {
                Text("불투명도"); Slider(value: $style.opacity, in: 0...1)
                Text("\(Int(style.opacity * 100))%").monospacedDigit().frame(width: 42)
            }
        }
    }
}

struct ShortcutRecorder: NSViewRepresentable {
    let shortcut: Shortcut
    let changed: (Shortcut) -> Void
    func makeCoordinator() -> Coordinator { Coordinator(self) }
    func makeNSView(context: Context) -> NSButton {
        let button = NSButton(title: shortcut.label, target: context.coordinator, action: #selector(Coordinator.record))
        button.bezelStyle = .rounded; button.toolTip = "단축키 변경"
        context.coordinator.button = button
        return button
    }
    func updateNSView(_ button: NSButton, context: Context) {
        context.coordinator.parent = self
        if context.coordinator.monitor == nil { button.title = shortcut.label }
    }
    static func dismantleNSView(_ button: NSButton, coordinator: Coordinator) { coordinator.stop() }
    @MainActor final class Coordinator: NSObject {
        var parent: ShortcutRecorder
        weak var button: NSButton?
        var monitor: Any?
        init(_ parent: ShortcutRecorder) { self.parent = parent }
        @objc func record() {
            if monitor != nil { stop(); return }
            button?.title = "키를 누르세요 · Esc 취소"
            monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
                guard let self else { return event }
                let flags = event.modifierFlags.intersection([.command, .control, .option, .shift])
                self.stop()
                if event.keyCode != 53 || !flags.isEmpty {
                    self.parent.changed(Shortcut(keyCode: UInt32(event.keyCode), modifiers: flags.rawValue, key: event.charactersIgnoringModifiers ?? ""))
                }
                return nil
            }
        }
        func stop() {
            if let monitor { NSEvent.removeMonitor(monitor) }; monitor = nil; button?.title = parent.shortcut.label
        }
    }
}


extension View {
    func settingsCard() -> some View {
        self.padding(20).frame(maxWidth: .infinity, alignment: .leading)
            .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 18))
    }
}
