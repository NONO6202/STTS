import SwiftUI
import AppKit
import Carbon

struct MainView: View {
    @ObservedObject var state: AppState
    @State private var tab = "TTS"
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                Picker("화면", selection: $tab) {
                    ForEach(["TTS", "STT", "설정"], id: \.self) { Text($0).tag($0) }
                }.labelsHidden().pickerStyle(.segmented).frame(width: 180)
                UpdateBadge(updates: state.updates, busy: state.modelWorkIsBusy)
            }.frame(maxWidth: .infinity).padding(.top, 10)
            Divider()
            Group {
                if tab == "TTS" {
                ScrollView {
                    VStack(alignment: .leading, spacing: 14) {
                        HStack {
                            Text("입력 단축키")
                            Spacer()
                            ShortcutRecorder(shortcut: state.shortcut, changed: state.setShortcut).frame(width: 190, height: 26)
                        }.padding(.bottom, 12)
                        HStack {
                            Picker("사양", selection: $state.ttsChoice) { ForEach(ResourceLevel.ttsSpecifications) { Text($0.ttsLabel).tag($0) } }
                                .disabled(!state.ttsEnabled || state.speaking)
                            Toggle("TTS 사용", isOn: $state.ttsEnabled).toggleStyle(.checkbox)
                        }
                        if !state.presetVoices.isEmpty {
                            Picker("목소리", selection: $state.selectedVoice) {
                                ForEach(state.presetVoices, id: \.self) { Text($0).tag($0) }
                                if state.supportsVoiceClone {
                                    ForEach(state.clonedVoices) { voice in
                                        Text(voice.name).tag(voice.selection).disabled(!voice.ready)
                                    }
                                }
                            }.disabled(!state.ttsEnabled || state.speaking)
                        }
                        Picker("언어", selection: $state.ttsLanguage) {
                            ForEach(state.ttsLanguages, id: \.self) { Text(SpeechLanguages.label($0)).tag($0) }
                        }.disabled(!state.ttsEnabled || state.speaking)
                        HStack {
                            Text("음량"); Slider(value: $state.volume, in: 0...1)
                            Text("\(Int(state.volume * 100))% ").monospacedDigit().frame(width: 46)
                        }
                        Toggle("목소리 모니터링", isOn: $state.voiceMonitoring)
                            .toggleStyle(.checkbox).disabled(!state.ttsEnabled || state.speaking)
                            .help("전송하는 TTS 목소리를 기본 스피커·헤드폰에서도 함께 듣습니다.")
                        VStack(alignment: .leading, spacing: 10) {
                            Text("입력창 모양").font(.headline).padding(.top, 10)
                            SurfaceControls(style: $state.windowStyle).padding(.top, 8)
                            Text("음성 입력창 미리보기").padding(12).frame(maxWidth: .infinity)
                                .foregroundStyle(state.windowStyle.foreground.color)
                                .background(state.windowStyle.background.color.opacity(state.windowStyle.opacity))
                                .clipShape(RoundedRectangle(cornerRadius: 8))
                        }
                        if !state.ttsEnabled || !state.microphoneReady || state.speaking || state.ttsStatus != "대기" {
                            HStack {
                                Text(!state.ttsEnabled ? "사용 안 함" : (!state.microphoneReady && !state.speaking ? "가상 마이크 연결 필요" : state.ttsStatus)).font(.caption)
                                Spacer()
                                if state.speaking { Button("취소") { state.cancelSpeech() } }
                            }
                        }
                    }.padding(18)
                }
                } else if tab == "STT" {
                ScrollView {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack {
                            Text("자막 단축키")
                            Spacer()
                            ShortcutRecorder(shortcut: state.captionShortcut, changed: state.setCaptionShortcut).frame(width: 190, height: 26)
                        }.padding(.bottom, 12)
                        HStack {
                            Picker("사양", selection: $state.sttChoice) { ForEach(ResourceLevel.sttSpecifications) { Text($0.sttLabel).tag($0) } }
                                .disabled(state.listening || state.preparing || state.managingModels)
                            Toggle("STT 사용", isOn: $state.sttEnabled).toggleStyle(.checkbox).disabled(state.managingModels)
                        }
                        if !state.captions.isEmpty {
                            LazyVStack(alignment: .leading, spacing: 10) {
                                ForEach(state.captions) { caption in
                                    VStack(alignment: .leading, spacing: 3) {
                                        Text(caption.text).textSelection(.enabled)
                                    }.frame(maxWidth: .infinity, alignment: .leading)
                                }
                            }.padding(12).background(state.captionStyle.background.color.opacity(state.captionStyle.opacity))
                                .foregroundStyle(state.captionStyle.foreground.color).clipShape(RoundedRectangle(cornerRadius: 8))
                        }
                        VStack(alignment: .leading, spacing: 10) {
                            Text("자막 모양").font(.headline).padding(.top, 10)
                            SurfaceControls(style: $state.captionStyle).padding(.top, 8)
                            Text("자막 미리보기").font(.system(size: 21)).padding(12).frame(maxWidth: .infinity)
                                .foregroundStyle(state.captionStyle.foreground.color)
                                .background(state.captionStyle.background.color.opacity(state.captionStyle.opacity))
                                .clipShape(RoundedRectangle(cornerRadius: 8))
                        }
                        if state.preparing || state.listening {
                            HStack {
                                if state.preparing { ProgressView().controlSize(.small) }
                                Text(state.status).font(.caption)
                                Spacer()
                            }
                        }
                    }.padding(18)
                }
                } else { SettingsView(state: state) }
            }
            if let error = state.error {
                HStack(alignment: .top) { Text(error); Spacer(); Button("닫기") { state.error = nil } }
                    .font(.callout).padding(.horizontal, 18).padding(.bottom, 10)
            }
        }.foregroundStyle(.primary)
            .frame(width: 600, height: 560)
            .background(Color(nsColor: .windowBackgroundColor))
    }
}

private enum SettingsPage: String, CaseIterable, Identifiable {
    case runtime = "실행", input = "입력창 동작", phrases = "TTS 단축어", voice = "보이스 클론", models = "모델 관리"
    var id: String { rawValue }
    var symbol: String {
        switch self { case .runtime: return "power"; case .input: return "keyboard"; case .phrases: return "text.bubble"; case .voice: return "waveform"; case .models: return "internaldrive" }
    }
}

private struct SettingsView: View {
    @ObservedObject var state: AppState
    @State private var page: SettingsPage?
    @State private var modelToDelete: DownloadedModel?
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            if let page {
                HStack(spacing: 12) {
                    Button { self.page = nil } label: { Label("설정", systemImage: "chevron.left") }
                    Text(page.rawValue).font(.headline)
                }
                Divider()
                ScrollView {
                    content(for: page).frame(maxWidth: .infinity, alignment: .leading)
                }.id(page)
            } else {
                Text("설정").font(.title2.bold())
                ForEach(SettingsPage.allCases) { destination in
                    Button {
                        page = destination
                        if destination == .models { state.refreshModels() }
                    } label: {
                        HStack(spacing: 14) {
                            Image(systemName: destination.symbol).font(.title3).frame(width: 26).foregroundStyle(.tint)
                            Text(destination.rawValue).font(.headline)
                            Spacer()
                            Image(systemName: "chevron.right").foregroundStyle(.secondary)
                        }.padding(14).contentShape(Rectangle())
                            .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 10))
                    }.buttonStyle(.plain)
                }
                Spacer(minLength: 0)
            }
        }.padding(18).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .alert("모델을 삭제할까요?", isPresented: Binding(get: { modelToDelete != nil }, set: { if !$0 { modelToDelete = nil } }), presenting: modelToDelete) { model in
                Button("삭제", role: .destructive) { state.deleteModel(model); modelToDelete = nil }
                Button("취소", role: .cancel) { modelToDelete = nil }
            } message: { model in
                Text("\(model.name) · \(model.sizeLabel)\n다음 사용 시 다시 다운로드합니다.")
            }
    }

    @ViewBuilder private func content(for page: SettingsPage) -> some View {
        switch page {
        case .runtime:
            RuntimeSettingsView(settings: state.runtime)
        case .input:
            VStack(alignment: .leading, spacing: 16) {
                Text("입력창 닫기").font(.headline)
                Toggle("입력창 밖을 클릭하면 닫기", isOn: $state.closeOnOutsideClick).toggleStyle(.checkbox)
                Toggle("마우스를 흔들면 닫기", isOn: $state.closeOnMouseShake).toggleStyle(.checkbox)
                Picker("흔들기 민감도", selection: $state.mouseShakeSensitivity) {
                    ForEach(MouseShakeSensitivity.allCases) { Text($0.rawValue).tag($0) }
                }.disabled(!state.closeOnMouseShake)
            }
        case .phrases:
            TTSShortcutsView(phrases: $state.ttsPhrases)
        case .voice:
            VoiceLibraryView(state: state)
        case .models:
            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    Text("다운로드한 모델").font(.headline)
                    Spacer()
                    Button("폴더 열기") { state.showModelFolder() }
                    Button("새로고침") { state.refreshModels() }.disabled(state.managingModels)
                }
                Button { state.showModelFolder() } label: {
                    Text(AppPaths.models.path).font(.caption).multilineTextAlignment(.leading)
                }.buttonStyle(.link)
                if state.managingModels { ProgressView().controlSize(.small) }
                if state.downloadedModels.isEmpty && !state.managingModels { Text("다운로드한 모델이 없습니다.").foregroundStyle(.secondary) }
                ForEach(state.downloadedModels) { model in
                    HStack {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(model.name).font(.callout)
                            Text(model.sizeLabel).font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button("삭제", role: .destructive) { modelToDelete = model }.disabled(state.modelWorkIsBusy)
                    }
                }
            }
        }
    }
}

struct TTSShortcutsView: View {
    @Binding var phrases: TTSPhrases
    @State private var editing: String?
    @State private var shortcut = ""
    @State private var phrase = ""
    @State private var error: String?

    private func clearEditor() { editing = nil; shortcut = ""; phrase = ""; error = nil }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("단축어").font(.headline)
            TextField("", text: $shortcut).textFieldStyle(.roundedBorder).accessibilityLabel("단축어")
            Text("읽을 문장").font(.headline)
            TextField("", text: $phrase, axis: .vertical)
                .lineLimit(3...5).textFieldStyle(.roundedBorder).accessibilityLabel("읽을 문장")
            HStack {
                Button(editing == nil ? "추가" : "저장") {
                    do {
                        try phrases.save(shortcut: shortcut, phrase: phrase, replacing: editing)
                        clearEditor()
                    } catch { self.error = error.localizedDescription }
                }
                if editing != nil { Button("취소", action: clearEditor) }
                Spacer()
            }
            if let error { Text(error).font(.caption).foregroundStyle(.red) }
            Divider().padding(.vertical, 4)
            if phrases.entries.isEmpty { Text("저장된 단축어 없음").foregroundStyle(.secondary) }
            ForEach(phrases.entries.keys.sorted(), id: \.self) { key in
                HStack(alignment: .top, spacing: 12) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(key).font(.headline).lineLimit(2)
                        Text(phrases.entries[key] ?? "").foregroundStyle(.secondary).lineLimit(3)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                    Button("수정") { editing = key; shortcut = key; phrase = phrases.entries[key] ?? ""; error = nil }
                    Button("삭제", role: .destructive) {
                        phrases.remove(key)
                        if editing == key { clearEditor() }
                    }
                }.padding(.vertical, 6)
            }
        }
    }
}

private struct VoiceLibraryView: View {
    @ObservedObject var state: AppState
    @State private var editingID: UUID?
    @State private var recordingPage = false
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            if recordingPage {
                Button { editingID = state.cancelVoiceRecording(); recordingPage = false } label: { Label("목록", systemImage: "chevron.left") }
                TextField("대본 (선택)", text: $state.voiceRecordingTranscript, axis: .vertical)
                    .lineLimit(4...7).textFieldStyle(.roundedBorder).disabled(state.voiceTranscribing)
                HStack {
                    if state.voiceRecordingActive {
                        Circle().fill(.red).frame(width: 8, height: 8)
                        Text("녹음 중 · \(state.voiceRecordingSeconds, specifier: "%.1f") / 30초").monospacedDigit()
                    } else if state.voiceTranscribing { ProgressView().controlSize(.small); Text("받아쓰는 중…") }
                    else if state.voiceRecordingPending { Text("마이크 준비 중…") }
                    Spacer()
                    if state.voiceRecordingBusy {
                        if !state.voiceTranscribing { Button("완료") { state.finishVoiceRecording() }.disabled(!state.voiceRecordingActive || state.voiceRecordingSeconds < 3) }
                        Button("취소") { editingID = state.cancelVoiceRecording(); recordingPage = false }
                    } else {
                        Button("녹음 시작") { state.startVoiceRecording { editingID = $0; recordingPage = false } }
                    }
                }
            } else if let id = editingID, let index = state.clonedVoices.firstIndex(where: { $0.id == id }) {
                Button { editingID = nil } label: { Label("목록", systemImage: "chevron.left") }
                Text("목소리명").font(.headline)
                TextField("목소리명", text: $state.clonedVoices[index].name).textFieldStyle(.roundedBorder)
                Text("대본").font(.headline)
                TextField("음성의 대본", text: $state.clonedVoices[index].transcript, axis: .vertical)
                    .lineLimit(4...7).textFieldStyle(.roundedBorder)
                HStack {
                    Text(state.clonedVoices[index].ready ? "등록 완료" : "이름·대본 필요").font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Button("삭제", role: .destructive) { state.deleteClonedVoice(id); editingID = nil }
                }
            } else {
                HStack {
                    Button("파일 추가") { editingID = state.addClonedVoices() }
                    Button("마이크 녹음") { state.voiceRecordingTranscript = ""; recordingPage = true }
                }
                if state.clonedVoices.isEmpty { Text("저장된 목소리 없음").foregroundStyle(.secondary) }
                ForEach(state.clonedVoices) { voice in
                    Button { editingID = voice.id } label: {
                        HStack {
                            Text(voice.name.isEmpty ? voice.sourceName : voice.name)
                            Spacer()
                            if !voice.ready { Text("대본 필요").font(.caption).foregroundStyle(.secondary) }
                            Image(systemName: "chevron.right").foregroundStyle(.secondary)
                        }.padding(.vertical, 10).contentShape(Rectangle())
                    }.buttonStyle(.plain)
                }
            }
        }.disabled(state.speaking)
            .onDisappear { state.cancelVoiceRecording() }
            .onReceive(NotificationCenter.default.publisher(for: NSWindow.willCloseNotification)) { notification in
                if (notification.object as? NSWindow)?.title == "STTS" { state.cancelVoiceRecording() }
            }
    }
}

struct UpdateBadge: View {
    @ObservedObject var updates: AppUpdater
    let busy: Bool
    var body: some View {
        if let version = updates.availableVersion {
            Button { updates.checkForUpdates() } label: {
                Image(systemName: "arrow.down").font(.system(size: 13, weight: .bold))
                    .foregroundStyle(.white).frame(width: 26, height: 26)
                    .background(.blue, in: Circle())
            }
            .buttonStyle(.plain).disabled(!updates.canCheck || busy)
            .accessibilityLabel("새 버전 다운로드")
            .help(busy ? "음성 작업이 끝나면 업데이트할 수 있습니다." : "버전 \(version) 다운로드")
        }
    }
}

private struct RuntimeSettingsView: View {
    @ObservedObject var settings: RuntimeSettings
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Toggle("로그인 시 자동 실행", isOn: Binding(get: { settings.launchAtLogin }, set: settings.setLaunchAtLogin))
                .toggleStyle(.checkbox)
            if settings.loginStatus == .requiresApproval {
                HStack { Text("승인 필요").font(.caption); Button("로그인 항목 설정") { settings.openLoginSettings() } }
            }
            Toggle("시작 시 백그라운드 실행", isOn: $settings.startInBackground).toggleStyle(.checkbox)
            Picker("창 닫을 때", selection: $settings.closeAction) {
                ForEach(WindowCloseAction.allCases) { Text($0.rawValue).tag($0) }
            }
            if let error = settings.error { Text(error).font(.caption).foregroundStyle(.red) }
        }.onAppear { settings.refresh() }
            .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in settings.refresh() }
    }
}

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

struct ComposerView: View {
    @ObservedObject var state: AppState
    @State private var text = ""
    let close: () -> Void
    private func submit() {
        guard !state.speaking, !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, text.count <= 500 else { return }
        state.speak(text)
        if state.speaking { close() } else { NSSound.beep() }
    }
    var body: some View {
        ComposingTextField(text: $text, foreground: state.windowStyle.foreground, submit: submit, cancel: close)
            .frame(maxWidth: .infinity).frame(height: 24).padding(.horizontal, 12).padding(.vertical, 10)
            .background(state.windowStyle.background.color.opacity(state.windowStyle.opacity))
            .clipShape(RoundedRectangle(cornerRadius: 9))
            .overlay(RoundedRectangle(cornerRadius: 9).stroke(state.error == nil ? Color.clear : Color.red, lineWidth: 1))
            .help(state.error ?? ("Enter 전송 · Esc 닫기"
                + (state.closeOnMouseShake ? " · 흔들어서 닫기" : "")
                + (state.closeOnOutsideClick ? " · 바깥 클릭으로 닫기" : "")))
    }
}

struct ComposingTextField: NSViewRepresentable {
    @Binding var text: String
    let foreground: Tint
    let submit: () -> Void
    let cancel: () -> Void
    func makeCoordinator() -> Coordinator { Coordinator(self) }
    func makeNSView(context: Context) -> NSTextField {
        let field = FocusedTextField(string: text)
        field.placeholderString = "입력 후 Enter"
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
        if field.currentEditor() == nil, field.stringValue != text { field.stringValue = text }
    }
    final class Coordinator: NSObject, NSTextFieldDelegate {
        var parent: ComposingTextField
        init(_ parent: ComposingTextField) { self.parent = parent }
        func controlTextDidChange(_ notification: Notification) {
            if let field = notification.object as? NSTextField { parent.text = field.stringValue }
        }
        func control(_ control: NSControl, textView: NSTextView, doCommandBy selector: Selector) -> Bool {
            if selector == #selector(NSResponder.insertNewline(_:)) {
                if textView.hasMarkedText() || (textView as? CompositionEditor)?.keyBeganWithMarkedText == true { return false }
                parent.text = control.stringValue; parent.submit(); return true
            }
            if selector == #selector(NSResponder.cancelOperation(_:)) {
                if textView.hasMarkedText() { return false }
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
            window.makeFirstResponder(self)
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
    func windowWillReturnFieldEditor(_ sender: NSWindow, to client: Any?) -> Any? {
        client is NSTextField ? editor : nil
    }
}

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

@MainActor final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    let state = AppState()
    private var main: NSWindow?
    private var composer: InputPanel?
    private var overlay: NSPanel?
    private var menuItem: NSStatusItem?
    private var hotkey: GlobalHotKey?
    private var captionHotkey: GlobalHotKey?
    private var previousApp: NSRunningApplication?
    private var shakeTimer: Timer?
    private var shakeLocalMonitor: Any?
    private var shakeGlobalMonitor: Any?
    private var shakePosition = CGPoint.zero
    private var shakeDetector = MouseShakeDetector()
    func applicationDidFinishLaunching(_ notification: Notification) {
        if state.ttsEnabled { state.connectMicrophone() } else { state.removeMicrophone() }
        state.closeComposer = { [weak self] in self?.closeComposer() }
        state.overlayChanged = { [weak self] in self?.updateOverlay() }
        state.appearanceChanged = { [weak self] in self?.composer?.invalidateShadow() }
        state.shortcutChanged = { [weak self] shortcut in
            guard let self else { return }
            if let hotkey = self.hotkey { try hotkey.update(shortcut) }
            else { self.hotkey = try GlobalHotKey(shortcut: shortcut) { [weak self] in self?.showComposer() } }
        }
        do { hotkey = try GlobalHotKey(shortcut: state.shortcut) { [weak self] in self?.showComposer() } }
        catch { state.error = error.localizedDescription }
        state.captionShortcutChanged = { [weak self] shortcut in
            guard let self else { return }
            if let hotkey = self.captionHotkey { try hotkey.update(shortcut) }
            else { self.captionHotkey = try GlobalHotKey(shortcut: shortcut, identifier: 2) { [weak self] in self?.state.toggleCaptions() } }
        }
        do { captionHotkey = try GlobalHotKey(shortcut: state.captionShortcut, identifier: 2) { [weak self] in self?.state.toggleCaptions() } }
        catch { state.error = error.localizedDescription }
        let menu = NSMenu()
        for (title, action) in [("STTS 열기", #selector(showMain)), ("자막 중지", #selector(stopCaptions)), ("종료", #selector(quit))] {
            let item = NSMenuItem(title: title, action: action, keyEquivalent: ""); item.target = self; menu.addItem(item)
        }
        menuItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        menuItem?.button?.title = "STTS"; menuItem?.menu = menu
        let mainMenu = NSMenu()
        let appMenu = NSMenu(title: "STTS")
        let quitItem = NSMenuItem(title: "STTS 종료", action: #selector(quit), keyEquivalent: "q")
        quitItem.target = self; appMenu.addItem(quitItem)
        let appRoot = NSMenuItem(); appRoot.submenu = appMenu; mainMenu.addItem(appRoot)
        let editMenu = NSMenu(title: "편집")
        for (title, action, key) in [("실행 취소", Selector(("undo:")), "z"), ("잘라내기", #selector(NSText.cut(_:)), "x"), ("복사", #selector(NSText.copy(_:)), "c"), ("붙여넣기", #selector(NSText.paste(_:)), "v"), ("모두 선택", #selector(NSText.selectAll(_:)), "a")] {
            editMenu.addItem(NSMenuItem(title: title, action: action, keyEquivalent: key))
        }
        let editRoot = NSMenuItem(); editRoot.submenu = editMenu; mainMenu.addItem(editRoot)
        NSApp.mainMenu = mainMenu
        if !state.runtime.startInBackground { showMain() }
        state.updates.isBusy = { [weak self] in
            guard let self else { return false }
            return self.state.modelWorkIsBusy || self.composer?.isVisible == true
        }
        state.updates.start()
    }
    @objc func showMain() {
        if main == nil {
            let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 680, height: 605), styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
            window.title = "STTS"; window.isReleasedWhenClosed = false
            window.delegate = self
            window.acceptsMouseMovedEvents = true
            window.isOpaque = true; window.backgroundColor = .windowBackgroundColor
            window.contentView = NSHostingView(rootView: MainView(state: state)); window.center(); main = window
        }
        if main?.isMiniaturized == true { main?.deminiaturize(nil) }
        NSApp.activate(ignoringOtherApps: true); main?.makeKeyAndOrderFront(nil)
    }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showMain(); return false
    }
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        guard sender === main else { return true }
        state.cancelVoiceRecording()
        switch state.runtime.closeAction {
        case .background: sender.orderOut(nil)
        case .minimize: sender.miniaturize(nil)
        case .quit: NSApp.terminate(nil)
        }
        return false
    }
    func windowDidMiniaturize(_ notification: Notification) {
        if notification.object as? NSWindow === main { state.cancelVoiceRecording() }
    }
    @objc func showComposer() {
        if composer?.isVisible == true { closeComposer(); return }
        guard state.ttsEnabled, !state.speaking else { return }
        previousApp = NSWorkspace.shared.frontmostApplication
        state.error = nil
        let mouse = NSEvent.mouseLocation
        let screen = NSScreen.screens.first(where: { $0.frame.contains(mouse) }) ?? NSScreen.main ?? NSScreen.screens[0]
        let frame = ComposerPlacement.frame(near: mouse, in: screen.visibleFrame)
        let panel = InputPanel(contentRect: frame, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        panel.delegate = panel
        panel.title = "STTS 입력"; panel.level = .floating
        panel.isOpaque = false; panel.backgroundColor = .clear; panel.hasShadow = true
        panel.isReleasedWhenClosed = false; panel.hidesOnDeactivate = false
        panel.acceptsMouseMovedEvents = true
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        let hosting = NSHostingView(rootView: ComposerView(state: state) { [weak self] in self?.closeComposer() })
        hosting.sizingOptions = []
        hosting.frame = NSRect(origin: .zero, size: frame.size)
        panel.contentView = hosting
        panel.setFrame(frame, display: false); composer = panel
        panel.makeKeyAndOrderFront(nil)
        shakeDetector = MouseShakeDetector()
        shakePosition = .zero
        _ = shakeDetector.sample(shakePosition, at: ProcessInfo.processInfo.systemUptime)
        let inputEvent: (NSEvent) -> Void = { [weak self] event in
            guard let self, let panel = self.composer, panel.isVisible else { return }
            switch event.type {
            case .leftMouseDown, .rightMouseDown, .otherMouseDown:
                if self.state.closeOnOutsideClick, event.window !== panel { self.closeComposer(restoreFocus: false) }
            default:
                // Games can lock or recenter the cursor while mouse deltas keep arriving.
                guard self.state.closeOnMouseShake else { return }
                self.shakePosition.x += event.deltaX
                self.shakePosition.y += event.deltaY
            }
        }
        let mask: NSEvent.EventTypeMask = [.mouseMoved, .leftMouseDragged, .rightMouseDragged, .otherMouseDragged,
                                         .leftMouseDown, .rightMouseDown, .otherMouseDown]
        shakeGlobalMonitor = NSEvent.addGlobalMonitorForEvents(matching: mask, handler: inputEvent)
        shakeLocalMonitor = NSEvent.addLocalMonitorForEvents(matching: mask) { event in
            inputEvent(event); return event
        }
        let timer = Timer(timeInterval: 1.0 / 60, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated {
                guard let self, self.composer?.isVisible == true else { return }
                guard self.state.closeOnMouseShake else { self.shakeDetector = MouseShakeDetector(); return }
                if self.shakeDetector.sample(self.shakePosition, at: ProcessInfo.processInfo.systemUptime,
                                             sensitivity: self.state.mouseShakeSensitivity) { self.closeComposer() }
            }
        }
        shakeTimer = timer; RunLoop.main.add(timer, forMode: .common)
    }
    private func closeComposer(restoreFocus: Bool = true) {
        stopShakeDetection()
        composer?.orderOut(nil); composer = nil
        if restoreFocus, previousApp?.processIdentifier != ProcessInfo.processInfo.processIdentifier { previousApp?.activate(options: []) }
        previousApp = nil
    }
    private func stopShakeDetection() {
        shakeTimer?.invalidate(); shakeTimer = nil
        if let shakeLocalMonitor { NSEvent.removeMonitor(shakeLocalMonitor) }; shakeLocalMonitor = nil
        if let shakeGlobalMonitor { NSEvent.removeMonitor(shakeGlobalMonitor) }; shakeGlobalMonitor = nil
    }
    func updateOverlay() {
        guard state.overlayVisible, state.sttEnabled else { overlay?.orderOut(nil); return }
        if overlay == nil {
            let panel = NSPanel(contentRect: .zero, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
            panel.title = "STTS 자막"
            panel.level = .floating; panel.isOpaque = false; panel.backgroundColor = .clear
            panel.ignoresMouseEvents = true; panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
            overlay = panel
        }
        let view = VStack(alignment: .leading, spacing: 6) {
            ForEach(state.visibleCaptions) { caption in
                Text(caption.text).font(.system(size: 21, weight: .medium)).foregroundStyle(self.state.captionStyle.foreground.color).lineLimit(3)
            }
        }.frame(minHeight: 28, alignment: .leading).padding(14).frame(width: 750, alignment: .leading).background(state.captionStyle.background.color.opacity(state.captionStyle.opacity)).clipShape(RoundedRectangle(cornerRadius: 10))
        let hosting = NSHostingView(rootView: view)
        overlay?.contentView = hosting
        let size = hosting.fittingSize, frame = (NSScreen.main ?? NSScreen.screens[0]).visibleFrame
        overlay?.setFrame(NSRect(x: frame.midX - size.width / 2, y: frame.minY + 90, width: size.width, height: size.height), display: true)
        overlay?.orderFrontRegardless()
    }
    @objc private func stopCaptions() { state.stop() }
    @objc private func quit() { NSApp.terminate(nil) }
    func applicationWillTerminate(_ notification: Notification) { stopShakeDetection(); state.shutdown() }
}
