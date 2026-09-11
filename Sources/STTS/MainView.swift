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
                    else if tab == "STT" { sttPage }
                    else { SettingsView(state: state).padding(.top, 60).padding(.bottom, bottomInset) }
                }.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                    .allowsHitTesting(tool == nil).accessibilityHidden(tool != nil)
                if let tool {
                    Color.black.opacity(0.16).onTapGesture { setTool(nil) }.transition(.opacity)
                    ToolDrawer(state: state, tool: tool) { setTool(nil) }
                        .padding(.horizontal, 12).padding(.top, 88).padding(.bottom, bottomInset)
                        .transition(reduceMotion ? .opacity : .move(edge: .bottom).combined(with: .opacity)).zIndex(1)
                }
            }.clipped()
            if let error = state.error {
                HStack(alignment: .top) {
                    Image(systemName: "exclamationmark.circle.fill").foregroundStyle(.orange)
                    Text(error).lineLimit(3).help(error)
                    Spacer()
                    Button("닫기") { state.error = nil }
                }.font(.callout).padding(12).background(.orange.opacity(0.08), in: RoundedRectangle(cornerRadius: 12))
                    .padding(.horizontal, 24).padding(.bottom, 8 + bottomInset)
            }
        }.font(.system(size: 13)).tint(Color(red: 0.19, green: 0.51, blue: 0.96))
            .frame(width: AppContract.shared.window.width, height: AppContract.shared.window.height)
            .overlay(alignment: .top) { navigation }
            .overlay(alignment: .bottom) { bottomControls }
            .background(Color.primary.opacity(0.035)).background(Color(nsColor: .windowBackgroundColor))
            .onChange(of: tab) { _, _ in setTool(nil) }
            .sheet(isPresented: $state.showingSetup) {
                SetupView { Preferences.save(true, key: "setupCompleted"); state.showingSetup = false }
            }
    }

    private var statusVisible: Bool { state.speaking || state.preparing || state.listening || state.ttsStatus != "대기" }
    private var bottomInset: CGFloat { (tab == "TTS" ? 60 : 0) + (statusVisible ? 44 : 0) }

    private var bottomControls: some View {
        VStack(spacing: 0) {
            if statusVisible {
                HStack(spacing: 8) {
                    if state.speaking || state.preparing { ProgressView().controlSize(.mini) }
                    Text(state.speaking || state.ttsStatus != "대기" ? state.ttsStatus : state.status)
                        .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                        .help(state.speaking || state.ttsStatus != "대기" ? state.ttsStatus : state.status)
                    if state.speaking { Button("취소") { state.cancelSpeech() }.controlSize(.small) }
                }.padding(.horizontal, 14).frame(height: 36)
                    .glassEffect(.regular, in: Capsule())
                    .padding(.horizontal, 24).padding(.bottom, 8)
            }
            if tab == "TTS" {
            HStack(spacing: 4) {
                ForEach(AppContract.shared.tools) { destination in
                    Button { setTool(tool == destination.id ? nil : destination.id) } label: {
                        Label(destination.title, systemImage: destination.symbol)
                            .font(.system(size: 13, weight: .semibold))
                            .frame(maxWidth: .infinity).frame(height: 32)
                            .contentShape(Rectangle())
                            .background(tool == destination.id ? Color.primary.opacity(0.075) : .clear, in: Capsule())
                    }.buttonStyle(.plain).foregroundStyle(tool == destination.id ? .primary : .secondary)
                        .accessibilityAddTraits(tool == destination.id ? .isSelected : [])
                }
            }.frame(width: AppContract.shared.window.tabsWidth - 8).padding(4).glassEffect(.regular, in: Capsule())
                .padding(.horizontal, 24).padding(.top, 8).padding(.bottom, 12)
            }
        }
    }

    private var navigation: some View {
            HStack(spacing: 4) {
                ForEach(AppContract.shared.tabs, id: \.self) { destination in
                    Button { tab = destination } label: {
                        Label(destination, systemImage: destination == "TTS" ? "waveform" : destination == "STT" ? "captions.bubble" : "gearshape")
                            .font(.system(size: 13, weight: .semibold))
                            .frame(maxWidth: .infinity).frame(height: 32)
                            .contentShape(Rectangle())
                            .background(tab == destination ? Color.primary.opacity(0.075) : .clear, in: Capsule())
                    }.buttonStyle(.plain).foregroundStyle(tab == destination ? .primary : .secondary)
                        .accessibilityAddTraits(tab == destination ? .isSelected : [])
                }
            }.frame(width: AppContract.shared.window.tabsWidth - 8).padding(4).glassEffect(.regular, in: Capsule())
                .padding(.horizontal, 24).padding(.top, 12).padding(.bottom, 8)
    }

    private var ttsPage: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 16) {
                    HStack { Text("TTS 사용").font(.system(size: 15, weight: .semibold)); Spacer(); Toggle("TTS 사용", isOn: $state.ttsEnabled).labelsHidden().toggleStyle(.switch) }
                    Divider()
                    HStack { Text("입력 단축키"); Spacer(); ShortcutRecorder(shortcut: state.shortcut, changed: state.setShortcut).frame(width: 190, height: 28) }
                    Picker("사양", selection: $state.ttsChoice) { ForEach(ResourceLevel.ttsSpecifications) { Text($0.ttsLabel).tag($0) } }
                        .disabled(!state.ttsEnabled || state.speaking || state.voiceRecordingBusy)
                    if !state.presetVoices.isEmpty {
                        Picker("목소리", selection: $state.selectedVoice) {
                            ForEach(state.presetVoices, id: \.self) { Text($0).tag($0) }
                            if state.supportsVoiceClone { ForEach(state.clonedVoices) { Text($0.name).tag($0.selection).disabled(!$0.ready) } }
                        }.disabled(!state.ttsEnabled || state.speaking || state.voiceRecordingBusy)
                    }
                    Picker("언어", selection: $state.ttsLanguage) {
                        ForEach(state.ttsLanguages, id: \.self) { Text(SpeechLanguages.label($0)).tag($0) }
                    }.disabled(!state.ttsEnabled || state.speaking || state.voiceRecordingBusy)
                    HStack { Text("음량"); Slider(value: $state.volume, in: 0...1); Text("\(Int(state.volume * 100))%").foregroundStyle(.secondary).monospacedDigit().frame(width: 42) }
                    HStack {
                        Text("피치"); Slider(value: $state.pitch, in: -12...12, step: 1)
                        Text(String(format: "%+.0f", state.pitch)).monospacedDigit().foregroundStyle(.secondary).frame(width: 42)
                    }.disabled(state.speaking)
                    HStack {
                        Text("속도"); Slider(value: $state.speed, in: 0.5...2, step: 0.05)
                        Text(String(format: "%.2f×", state.speed)).monospacedDigit().foregroundStyle(.secondary).frame(width: 42)
                    }.disabled(state.speaking)
                    HStack { Spacer(); Button("기본값 복원") { state.volume = AppContract.shared.defaults.volume; state.pitch = 0; state.speed = 1 }.disabled(state.speaking) }
                    HStack { Text("목소리 모니터링"); Spacer(); Toggle("목소리 모니터링", isOn: $state.voiceMonitoring).labelsHidden().toggleStyle(.switch) }
                        .disabled(!state.ttsEnabled || state.speaking || state.voiceRecordingBusy)
                        .help("전송하는 TTS 목소리를 기본 스피커·헤드폰에서도 함께 듣습니다.")
                }.settingsCard()
                VStack(alignment: .leading, spacing: 16) {
                    Text("입력창 모양").font(.system(size: 15, weight: .semibold))
                    SurfaceControls(style: $state.windowStyle)
                    Text("음성 입력창 미리보기").padding(18).frame(maxWidth: .infinity)
                        .foregroundStyle(state.windowStyle.foreground.color)
                        .background(state.windowStyle.background.color.opacity(state.windowStyle.opacity), in: RoundedRectangle(cornerRadius: 12))
                }.settingsCard()

            }.padding(24).padding(.top, 60).padding(.bottom, bottomInset)
        }
    }

    private var sttPage: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 16) {
                    HStack { Text("STT 사용").font(.system(size: 15, weight: .semibold)); Spacer(); Toggle("STT 사용", isOn: $state.sttEnabled).labelsHidden().toggleStyle(.switch) }
                        .disabled(state.managingModels || state.voiceRecordingBusy)
                    Divider()
                    HStack { Text("자막 단축키"); Spacer(); ShortcutRecorder(shortcut: state.captionShortcut, changed: state.setCaptionShortcut).frame(width: 190, height: 28) }
                    Picker("사양", selection: $state.sttChoice) { ForEach(ResourceLevel.sttSpecifications) { Text($0.sttLabel).tag($0) } }
                        .disabled(state.listening || state.preparing || state.managingModels || state.voiceRecordingBusy)
                }.settingsCard()
                if !state.captions.isEmpty {
                    LazyVStack(alignment: .leading, spacing: 10) {
                        ForEach(state.captions) { Text($0.text).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }
                    }.padding(16).background(state.captionStyle.background.color.opacity(state.captionStyle.opacity), in: RoundedRectangle(cornerRadius: 14))
                        .foregroundStyle(state.captionStyle.foreground.color)
                }
                VStack(alignment: .leading, spacing: 16) {
                    Text("자막 모양").font(.system(size: 15, weight: .semibold))
                    SurfaceControls(style: $state.captionStyle)
                    HStack {
                        Text("글자 크기"); Slider(value: $state.captionFontSize, in: 14...40, step: 1)
                        Text("\(Int(state.captionFontSize))").foregroundStyle(.secondary).monospacedDigit().frame(width: 42)
                    }
                    Text("자막 미리보기").font(.system(size: state.captionFontSize)).padding(18).frame(maxWidth: .infinity)
                        .foregroundStyle(state.captionStyle.foreground.color)
                        .background(state.captionStyle.background.color.opacity(state.captionStyle.opacity), in: RoundedRectangle(cornerRadius: 12))
                }.settingsCard()

            }.padding(24).padding(.top, 60).padding(.bottom, bottomInset)
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
        VStack(alignment: .leading, spacing: 16) {
            Text(AppContract.shared.onboarding.title).font(.title2.bold())
            ForEach(AppContract.shared.onboarding.sections, id: \.title) { section in
                VStack(alignment: .leading, spacing: 10) {
                    Text(section.title).font(.headline)
                    Text(section.text)
                }
            }
            HStack {
                Spacer()
                Button(AppContract.shared.onboarding.button, action: complete).keyboardShortcut(.defaultAction)
            }
        }.padding(24).frame(width: 460).fixedSize(horizontal: false, vertical: true)
            .interactiveDismissDisabled()
    }
}
