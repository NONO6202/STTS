import SwiftUI
import AppKit

struct SurfaceControls: View {
    @Binding var style: SurfaceStyle
    var body: some View {
        FormRow(L10n.text("배경")) {
            ColorPicker(L10n.text("배경"), selection: Binding(get: { style.background.color }, set: { style.background = Tint($0) }), supportsOpacity: false).labelsHidden()
        }
        FormRow(L10n.text("글자")) {
            ColorPicker(L10n.text("글자"), selection: Binding(get: { style.foreground.color }, set: { style.foreground = Tint($0) }), supportsOpacity: false).labelsHidden()
        }
        SliderRow(L10n.text("불투명도"), value: $style.opacity, in: 0...1, format: .percent)
    }
}

/// Appearance controls are a full-version feature; the demo shows them locked.
struct SurfaceLock: ViewModifier {
    func body(content: Content) -> some View {
        if Edition.isDemo {
            content.disabled(true)
            DemoNotice(text: "모양 꾸미기는 정식판에서 사용할 수 있습니다.")
        } else { content }
    }
}

/// Shows a surface over a patterned backdrop so its opacity is visible.
struct SurfacePreview: View {
    let text: String
    let style: SurfaceStyle
    var fontSize: Double = 13
    var body: some View {
        Text(text).font(.system(size: fontSize, weight: .medium)).lineLimit(2).multilineTextAlignment(.center)
            .padding(.horizontal, 20).padding(.vertical, 14).frame(maxWidth: .infinity)
            .foregroundStyle(style.foreground.color)
            .background(style.background.color.opacity(style.opacity), in: RoundedRectangle(cornerRadius: 12))
            .padding(18).frame(maxWidth: .infinity)
            .background {
                LinearGradient(colors: [Color(red: 0.36, green: 0.55, blue: 0.98), Color(red: 0.62, green: 0.42, blue: 0.93), Color(red: 0.98, green: 0.58, blue: 0.47)], startPoint: .topLeading, endPoint: .bottomTrailing)
                    .opacity(0.55)
            }
            .clipShape(RoundedRectangle(cornerRadius: 12))
            .padding(.vertical, 6)
    }
}

struct ShortcutRecorder: NSViewRepresentable {
    let shortcut: Shortcut?
    let changed: (Shortcut) -> Void
    fileprivate var title: String { shortcut?.label ?? L10n.text("지정 안 함") }
    func makeCoordinator() -> Coordinator { Coordinator(self) }
    func makeNSView(context: Context) -> NSButton {
        let button = NSButton(title: title, target: context.coordinator, action: #selector(Coordinator.record))
        button.bezelStyle = .rounded; button.toolTip = L10n.text("단축키 변경")
        context.coordinator.button = button
        return button
    }
    func updateNSView(_ button: NSButton, context: Context) {
        context.coordinator.parent = self
        if context.coordinator.monitor == nil { button.title = title }
    }
    static func dismantleNSView(_ button: NSButton, coordinator: Coordinator) { coordinator.stop() }
    @MainActor final class Coordinator: NSObject {
        var parent: ShortcutRecorder
        weak var button: NSButton?
        var monitor: Any?
        init(_ parent: ShortcutRecorder) { self.parent = parent }
        @objc func record() {
            if monitor != nil { stop(); return }
            button?.title = L10n.text("키를 누르세요 · Esc 취소")
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
            if let monitor { NSEvent.removeMonitor(monitor) }; monitor = nil; button?.title = parent.title
        }
    }
}

/// A recorder for an optional global shortcut, with a button that clears it.
struct HotkeyField: View {
    let shortcut: Shortcut?
    var width: CGFloat = 180
    let changed: (Shortcut?) -> Void
    var body: some View {
        HStack(spacing: 4) {
            ShortcutRecorder(shortcut: shortcut) { changed($0) }.frame(width: width, height: 26)
            if shortcut != nil {
                Button { changed(nil) } label: { Image(systemName: "xmark").font(.system(size: 10, weight: .semibold)) }
                    .buttonStyle(.borderless).foregroundStyle(.secondary).help(L10n.text("단축키 지우기")).accessibilityLabel(L10n.text("단축키 지우기"))
            }
        }
    }
}

enum Theme {
    private static let tokens = AppContract.shared.theme
    static let accent: Color = {
        let value = Int(tokens.accent.dropFirst(), radix: 16) ?? 0
        return Color(red: Double(value >> 16 & 0xff) / 255, green: Double(value >> 8 & 0xff) / 255, blue: Double(value & 0xff) / 255)
    }()
    static let cardRadius = CGFloat(tokens.cardRadius)
    static let rowInset = CGFloat(tokens.rowInset)
    static let rowHeight = CGFloat(tokens.rowHeight)
    static let sectionGap = CGFloat(tokens.sectionGap)
    static let pagePadding = CGFloat(tokens.pagePadding)
    static let pageTop = CGFloat(tokens.pageTop)
    static var card: some ShapeStyle { Color(nsColor: .controlBackgroundColor) }
}

/// A titled, rounded group whose rows are separated by inset hairlines.
struct FormSection<Content: View, Accessory: View>: View {
    let title: String?
    let content: Content
    let accessory: Accessory
    init(_ title: String? = nil, @ViewBuilder content: () -> Content, @ViewBuilder accessory: () -> Accessory = { EmptyView() }) {
        self.title = title; self.content = content(); self.accessory = accessory()
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if title != nil || Accessory.self != EmptyView.self {
                HStack(alignment: .firstTextBaseline) {
                    if let title { Text(title).font(.system(size: 12, weight: .semibold)).foregroundStyle(.secondary) }
                    Spacer()
                    accessory.font(.system(size: 12)).controlSize(.small)
                }.padding(.horizontal, 6).frame(minHeight: 20)
            }
            VStack(spacing: 0) {
                Group(subviews: content) { rows in
                    ForEach(rows) { row in
                        if row.id != rows.first?.id { Divider().padding(.leading, Theme.rowInset) }
                        row.padding(.horizontal, Theme.rowInset).frame(maxWidth: .infinity, minHeight: Theme.rowHeight, alignment: .leading)
                    }
                }
            }.background(Theme.card, in: RoundedRectangle(cornerRadius: Theme.cardRadius))
                .overlay(RoundedRectangle(cornerRadius: Theme.cardRadius).strokeBorder(Color.primary.opacity(0.06), lineWidth: 0.5))
        }
    }
}

/// Label on the leading edge, control on the trailing edge.
struct FormRow<Control: View>: View {
    let title: String
    var detail: String?
    let control: Control
    init(_ title: String, detail: String? = nil, @ViewBuilder control: () -> Control) {
        self.title = title; self.detail = detail; self.control = control()
    }
    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                if let detail { Text(detail).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true) }
            }.frame(maxWidth: .infinity, alignment: .leading)
            control
        }.padding(.vertical, 8)
    }
}

struct ToggleRow: View {
    let title: String
    var detail: String?
    @Binding var isOn: Bool
    init(_ title: String, detail: String? = nil, isOn: Binding<Bool>) { self.title = title; self.detail = detail; _isOn = isOn }
    var body: some View {
        FormRow(title, detail: detail) { Toggle(title, isOn: $isOn).labelsHidden().toggleStyle(.switch).controlSize(.small) }
    }
}

/// A picker rendered as a trailing pop-up menu.
struct MenuRow<Selection: Hashable, Options: View>: View {
    let title: String
    @Binding var selection: Selection
    let options: Options
    init(_ title: String, selection: Binding<Selection>, @ViewBuilder options: () -> Options) {
        self.title = title; _selection = selection; self.options = options()
    }
    var body: some View {
        FormRow(title) {
            Picker(title, selection: $selection) { options }.labelsHidden().pickerStyle(.menu).fixedSize()
        }
    }
}

struct SliderRow: View {
    enum Format { case percent, signed, speed, plain }
    let title: String
    @Binding var value: Double
    let range: ClosedRange<Double>
    var step: Double?
    let format: Format
    init(_ title: String, value: Binding<Double>, in range: ClosedRange<Double>, step: Double? = nil, format: Format) {
        self.title = title; _value = value; self.range = range; self.step = step; self.format = format
    }
    private var label: String {
        switch format {
        case .percent: "\(Int((value * 100).rounded()))%"
        case .signed: String(format: "%+.0f", value)
        case .speed: String(format: "%.2f×", value)
        case .plain: "\(Int(value))"
        }
    }
    var body: some View {
        HStack(spacing: 12) {
            Text(title).frame(width: 84, alignment: .leading).lineLimit(1).minimumScaleFactor(0.8)
            // Snap manually so stepped sliders don't draw tick marks.
            Slider(value: Binding(get: { value }, set: { raw in value = step.map { (raw / $0).rounded() * $0 } ?? raw }), in: range)
                .controlSize(.small).accessibilityLabel(title)
            Text(label).monospacedDigit().foregroundStyle(.secondary).frame(width: 48, alignment: .trailing)
        }.padding(.vertical, 8)
    }
}

/// The on/off switch that leads a feature page.
struct FeatureHeader: View {
    let symbol: String
    let title: String
    let detail: String
    @Binding var isOn: Bool
    var active: Bool
    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: symbol).font(.system(size: 15, weight: .semibold)).foregroundStyle(.white)
                .frame(width: 32, height: 32)
                .background(active ? Theme.accent : Color.secondary.opacity(0.55), in: RoundedRectangle(cornerRadius: 8))
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.system(size: 14, weight: .semibold))
                Text(detail).font(.caption).foregroundStyle(active ? Theme.accent : .secondary).lineLimit(2)
            }.frame(maxWidth: .infinity, alignment: .leading)
            Toggle(title, isOn: $isOn).labelsHidden().toggleStyle(.switch)
        }.padding(.vertical, 12).animation(.easeOut(duration: 0.2), value: active)
    }
}

/// Small borderless action shown beside a section title.
struct SectionAction: View {
    let title: String
    var symbol = "arrow.counterclockwise"
    let action: () -> Void
    var body: some View {
        Button(action: action) { Label(title, systemImage: symbol).labelStyle(.titleAndIcon) }
            .buttonStyle(.borderless).foregroundStyle(.secondary)
    }
}

/// Scrollable page column shared by the main tabs.
struct Page<Content: View>: View {
    let bottomInset: CGFloat
    @ViewBuilder let content: Content
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.sectionGap) { content }
                .padding(.horizontal, Theme.pagePadding).padding(.top, Theme.pageTop).padding(.bottom, Theme.pagePadding + bottomInset)
        }.scrollIndicators(.never)
    }
}
