import SwiftUI
import AppKit

struct MainView: View {
    @ObservedObject var state: AppState
    @State private var tab = "TTS"
    @State private var tool: String?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(spacing: 0) {
            ZStack(alignment: .bottom) {
                Group {
                    if tab == "TTS" { ttsPage }
                    else if tab == "마이크" { microphonePage }
                    else if tab == "STT" { sttPage }
                    else { SettingsView(state: state, bottomInset: bottomInset) }
                }.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                    .allowsHitTesting(tool == nil).accessibilityHidden(tool != nil)
                if let tool {
                    Color.black.opacity(0.18).onTapGesture { setTool(nil) }.transition(.opacity)
                    ToolDrawer(state: state, tool: tool) { setTool(nil) }
                        .padding(.horizontal, 12).padding(.top, 80).padding(.bottom, bottomInset)
                        .transition(reduceMotion ? .opacity : .move(edge: .bottom).combined(with: .opacity)).zIndex(1)
                }
            }.clipped()
            if let error = state.error {
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange)
                    Text(L10n.message(error)).lineLimit(3).help(L10n.message(error)).frame(maxWidth: .infinity, alignment: .leading)
                    Button { state.error = nil } label: { Image(systemName: "xmark").font(.system(size: 10, weight: .bold)) }
                        .buttonStyle(.borderless).foregroundStyle(.secondary).accessibilityLabel(L10n.text("닫기"))
                }.font(.callout).padding(.horizontal, 14).padding(.vertical, 12)
                    .background(Color.orange.opacity(0.1), in: RoundedRectangle(cornerRadius: 12))
                    .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(Color.orange.opacity(0.25), lineWidth: 0.5))
                    .padding(.horizontal, 24).padding(.bottom, 8 + bottomInset)
            }
        }.font(.system(size: 13)).tint(Theme.accent)
            .frame(width: AppContract.shared.window.width, height: AppContract.shared.window.height)
            .overlay(alignment: .top) { navigation }
            .overlay(alignment: .bottom) { bottomControls }
            .background(Color.primary.opacity(0.03)).background(Color(nsColor: .windowBackgroundColor))
            .onChange(of: tab) { _, _ in setTool(nil) }
            .sheet(isPresented: $state.showingSetup) {
                SetupView {
                    if !Preferences.read("setupCompleted", fallback: false) {
                        state.runtime.setLaunchAtLogin(Preferences.read("launchAtLogin", fallback: AppContract.shared.defaults.login))
                        if let error = state.runtime.error { state.error = error }
                    }
                    Preferences.save(true, key: "setupCompleted"); state.showingSetup = false
                }
            }
    }

    private var statusVisible: Bool { state.speaking || state.preparing || state.listening || state.ttsStatus != "대기" }
    private var bottomInset: CGFloat { (tab == "TTS" ? 60 : 0) + (statusVisible ? 44 : 0) }
    private var ttsLocked: Bool { !state.ttsEnabled || state.speaking || state.voiceRecordingBusy }

    private var bottomControls: some View {
        VStack(spacing: 0) {
            if statusVisible {
                let message = state.speaking || state.ttsStatus != "대기" ? state.ttsStatus : state.status
                HStack(spacing: 8) {
                    if state.speaking || state.preparing { ProgressView().controlSize(.mini) }
                    else { Circle().fill(state.listening ? Color.green : Theme.accent).frame(width: 7, height: 7) }
                    Text(L10n.message(message)).font(.caption).foregroundStyle(.secondary).lineLimit(1).help(message)
                    if !state.speechQueue.isEmpty {
                        Text(L10n.text("대기 {0}개", String(state.speechQueue.count))).font(.caption2.weight(.semibold))
                            .padding(.horizontal, 6).padding(.vertical, 2).background(.quaternary, in: Capsule())
                    }
                    if state.speaking { Button(L10n.text("취소")) { state.cancelSpeech() }.controlSize(.small).buttonStyle(.borderless) }
                }.padding(.horizontal, 14).frame(height: 34)
                    .glassEffect(.regular, in: Capsule())
                    .padding(.horizontal, 24).padding(.bottom, 8)
            }
            if tab == "TTS" {
                segments(AppContract.shared.tools.map { ($0.id, $0.title, $0.symbol) }, selected: tool) { id in setTool(tool == id ? nil : id) }
                    .padding(.horizontal, 24).padding(.top, 8).padding(.bottom, 12)
            }
        }
    }

    private var navigation: some View {
        segments(AppContract.shared.tabs.map { ($0, $0, Self.symbol(for: $0)) }, selected: tab) { tab = $0 }
            .padding(.horizontal, 24).padding(.top, 12).padding(.bottom, 8)
    }

    private static func symbol(for tab: String) -> String {
        switch tab {
        case "TTS": "waveform"
        case "마이크": "mic"
        case "STT": "captions.bubble"
        default: "gearshape"
        }
    }

    private func segments(_ items: [(id: String, title: String, symbol: String)], selected: String?, select: @escaping (String) -> Void) -> some View {
        HStack(spacing: 2) {
            ForEach(items, id: \.id) { item in
                let active = selected == item.id
                Button { select(item.id) } label: {
                    Label(L10n.text(item.title), systemImage: item.symbol)
                        .font(.system(size: 12.5, weight: .semibold))
                        .frame(maxWidth: .infinity).frame(height: 30)
                        .contentShape(Capsule())
                        .background(active ? Color.primary.opacity(0.08) : .clear, in: Capsule())
                }.buttonStyle(.plain).foregroundStyle(active ? .primary : .secondary)
                    .accessibilityAddTraits(active ? .isSelected : [])
            }
        }.frame(width: barWidth(items.map(\.title)) - 8).padding(4).glassEffect(.regular, in: Capsule())
    }

    private func barWidth(_ titles: [String]) -> CGFloat {
        let font = NSFont.systemFont(ofSize: 12.5, weight: .semibold)
        let widest = titles.map { (L10n.text($0) as NSString).size(withAttributes: [.font: font]).width }.max() ?? 0
        return min(AppContract.shared.window.width - 48, max(AppContract.shared.window.tabsWidth, (widest + 32) * Double(titles.count) + 20))
    }

    private var ttsPage: some View {
        Page(bottomInset: bottomInset) {
            FormSection {
                FeatureHeader(symbol: "waveform", title: L10n.text("TTS 사용"),
                              detail: L10n.text(state.microphoneReady ? "STTS 연결됨" : "TTS를 켜면 가상 마이크를 연결합니다."),
                              isOn: $state.ttsEnabled, active: state.ttsEnabled && state.microphoneReady)
                FormRow(L10n.text("입력 단축키")) { ShortcutRecorder(shortcut: state.shortcut, changed: state.setShortcut).frame(width: 180, height: 26) }
                MenuRow(L10n.text("사양"), selection: $state.ttsChoice) {
                    ForEach(ResourceLevel.ttsSpecifications) { Text(L10n.text($0.ttsLabel)).tag($0) }
                }.disabled(ttsLocked)
                if !state.presetVoices.isEmpty {
                    MenuRow(L10n.text("목소리"), selection: $state.selectedVoice) {
                        ForEach(state.presetVoices, id: \.self) { Text($0).tag($0) }
                        if state.supportsVoiceClone { ForEach(state.clonedVoices) { Text($0.name).tag($0.selection).disabled(!$0.ready) } }
                    }.disabled(ttsLocked)
                }
                MenuRow(L10n.text("언어"), selection: Binding(get: { state.ttsFollowsSystem ? "system" : state.ttsLanguage }, set: state.selectTTSLanguage)) {
                    Text(L10n.text("시스템 언어 · {0}", L10n.languageName(state.ttsLanguage))).tag("system")
                    ForEach(state.ttsLanguages, id: \.self) { Text(SpeechLanguages.label($0)).tag($0) }
                }.disabled(ttsLocked)
                ToggleRow(L10n.text("모니터링"), detail: L10n.text("전송하는 TTS 목소리를 기본 스피커·헤드폰에서도 함께 듣습니다."), isOn: $state.voiceMonitoring)
                    .disabled(ttsLocked)
            }

            FormSection(L10n.text("음성 조절")) {
                SliderRow(L10n.text("음량"), value: $state.volume, in: 0...1, format: .percent)
                SliderRow(L10n.text("피치"), value: $state.pitch, in: -12...12, step: 1, format: .signed).disabled(state.speaking)
                SliderRow(L10n.text("속도"), value: $state.speed, in: 0.5...2, step: 0.05, format: .speed).disabled(state.speaking)
            } accessory: {
                SectionAction(title: L10n.text("기본값 복원")) { state.volume = AppContract.shared.defaults.volume; state.pitch = 0; state.speed = 1 }
                    .disabled(state.speaking)
            }

            FormSection(L10n.text("입력창 모양")) {
                SurfacePreview(text: L10n.text("음성 입력창 미리보기"), style: state.windowStyle)
                SurfaceControls(style: $state.windowStyle)
            }
        }
    }

    private var microphonePage: some View {
        Page(bottomInset: bottomInset) {
            FormSection {
                FeatureHeader(symbol: "mic.fill", title: L10n.text("마이크 함께 보내기"), detail: L10n.message(state.liveMicrophoneStatus),
                              isOn: $state.liveMicrophoneEnabled, active: state.liveMicrophoneActive)
                    .disabled(!state.ttsEnabled)
                FormRow(L10n.text("마이크")) {
                    HStack(spacing: 6) {
                        Picker(L10n.text("마이크"), selection: $state.liveMicrophoneUID) {
                            Text(L10n.text("마이크 선택")).tag("")
                            if !state.liveMicrophoneUID.isEmpty && !state.liveMicrophoneDevices.contains(where: { $0.uid == state.liveMicrophoneUID }) {
                                Text(L10n.text("연결되지 않은 마이크")).tag(state.liveMicrophoneUID)
                            }
                            ForEach(state.liveMicrophoneDevices) { Text($0.name).tag($0.uid) }
                        }.labelsHidden().pickerStyle(.menu).frame(maxWidth: 240)
                        Button(action: state.refreshLiveMicrophones) { Image(systemName: "arrow.clockwise") }
                            .buttonStyle(.borderless).help(L10n.text("새로고침")).accessibilityLabel(L10n.text("새로고침"))
                    }
                }.disabled(state.liveMicrophoneActive)
                SliderRow(L10n.text("마이크 음량"), value: $state.liveMicrophoneVolume, in: 0...1, format: .percent)
            }.onAppear(perform: state.refreshLiveMicrophones)

            FormSection(L10n.text("마이크 효과")) {
                SliderRow(L10n.text("피치"), value: $state.liveMicrophonePitch, in: -12...12, step: 1, format: .signed)
                MenuRow(L10n.text("필터"), selection: $state.liveMicrophoneFilter) {
                    ForEach(MicrophoneEffects.filters, id: \.self) { Text(L10n.text($0)).tag($0) }
                }
                SliderRow(L10n.text("강도"), value: $state.liveMicrophoneStrength, in: 0...1, format: .percent)
                    .disabled(state.liveMicrophoneFilter == "기본")
            } accessory: {
                SectionAction(title: L10n.text("기본값 복원")) { state.liveMicrophonePitch = 0; state.liveMicrophoneFilter = "기본"; state.liveMicrophoneStrength = 0.65 }
            }
        }
    }

    private var sttPage: some View {
        Page(bottomInset: bottomInset) {
            FormSection {
                FeatureHeader(symbol: "captions.bubble.fill", title: L10n.text("STT 사용"), detail: L10n.message(state.status),
                              isOn: $state.sttEnabled, active: state.sttEnabled)
                    .disabled(state.managingModels || state.voiceRecordingBusy)
                FormRow(L10n.text("자막 단축키")) { ShortcutRecorder(shortcut: state.captionShortcut, changed: state.setCaptionShortcut).frame(width: 180, height: 26) }
                MenuRow(L10n.text("사양"), selection: $state.sttChoice) {
                    ForEach(ResourceLevel.sttSpecifications) { Text(L10n.text($0.sttLabel)).tag($0) }
                }.disabled(state.listening || state.preparing || state.managingModels || state.voiceRecordingBusy)
            }
            if !state.captions.isEmpty {
                LazyVStack(alignment: .leading, spacing: 10) {
                    ForEach(state.captions) { Text($0.text).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }
                }.padding(16).background(state.captionStyle.background.color.opacity(state.captionStyle.opacity), in: RoundedRectangle(cornerRadius: Theme.cardRadius))
                    .foregroundStyle(state.captionStyle.foreground.color)
            }
            FormSection(L10n.text("자막 모양")) {
                SurfacePreview(text: L10n.text("자막 미리보기"), style: state.captionStyle, fontSize: state.captionFontSize)
                SurfaceControls(style: $state.captionStyle)
                SliderRow(L10n.text("글자 크기"), value: $state.captionFontSize, in: 14...40, step: 1, format: .plain)
            }
        }
    }

    private func setTool(_ selection: String?) {
        if tool == "voice" { state.cancelVoiceRecording() }
        withAnimation(reduceMotion ? .easeOut(duration: 0.15) : .spring(response: 0.38, dampingFraction: 0.9)) { tool = selection }
    }
}

struct SetupView: View {
    let complete: () -> Void
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack(spacing: 12) {
                Image(systemName: "waveform").font(.system(size: 18, weight: .semibold)).foregroundStyle(.white)
                    .frame(width: 40, height: 40).background(Theme.accent, in: RoundedRectangle(cornerRadius: 10))
                Text(L10n.text(AppContract.shared.onboarding.title)).font(.title2.bold())
            }
            VStack(alignment: .leading, spacing: 12) {
                ForEach(AppContract.shared.onboarding.sections, id: \.title) { section in
                    VStack(alignment: .leading, spacing: 6) {
                        Text(L10n.text(section.title)).font(.headline)
                        Text(L10n.text(section.text)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                    }.padding(16).frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color.primary.opacity(0.04), in: RoundedRectangle(cornerRadius: 12))
                }
            }
            HStack {
                Spacer()
                Button(L10n.text(AppContract.shared.onboarding.button), action: complete)
                    .keyboardShortcut(.defaultAction).buttonStyle(.borderedProminent).controlSize(.large)
            }
        }.padding(28).frame(width: 480).fixedSize(horizontal: false, vertical: true)
            .tint(Theme.accent).interactiveDismissDisabled()
    }
}
