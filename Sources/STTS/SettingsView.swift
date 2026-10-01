import SwiftUI
import AppKit

private extension AppContract.Setting {
    static func title(_ id: String) -> String { L10n.text(AppContract.shared.settings.first { $0.id == id }?.title ?? id) }
}

struct SettingsView: View {
    @ObservedObject var state: AppState
    var bottomInset: CGFloat = 0
    @State private var modelToDelete: DownloadedModel?
    var body: some View {
        Page(bottomInset: bottomInset) {
            if Edition.isDemo {
                FormSection(L10n.text("데모 버전")) { DemoNotice(text: "보이스 클론, TTS 단축어, 사운드보드, 마이크 효과, 실시간 자막은 정식판에서 사용할 수 있습니다.") }
            }
            FormSection(AppContract.Setting.title("runtime")) { RuntimeSettingsView(settings: state.runtime) }

            FormSection(L10n.text("가상 마이크")) {
                FormRow(L10n.text(state.microphoneReady ? "STTS 연결됨" : "TTS를 켜면 가상 마이크를 연결합니다.")) {
                    HStack(spacing: 6) {
                        Button(L10n.text("연결 확인")) { state.connectMicrophone() }.disabled(!state.ttsEnabled || state.modelWorkIsBusy)
                        Button(L10n.text("소리 설정")) { NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.Sound-Settings.extension")!) }
                    }.controlSize(.small)
                }.foregroundStyle(state.microphoneReady ? .primary : .secondary)
            }

            FormSection(AppContract.Setting.title("input")) {
                ToggleRow(L10n.text("작성 중인 내용 유지"), isOn: $state.keepComposerDraft)
                ToggleRow(L10n.text("입력창 밖을 클릭하면 닫기"), isOn: $state.closeOnOutsideClick)
                ToggleRow(L10n.text("마우스를 흔들면 닫기"), isOn: $state.closeOnMouseShake)
                MenuRow(L10n.text("흔들기 민감도"), selection: $state.mouseShakeSensitivity) {
                    ForEach(MouseShakeSensitivity.allCases) { Text(L10n.text($0.rawValue)).tag($0) }
                }.disabled(!state.closeOnMouseShake)
            }

            FormSection(AppContract.Setting.title("models")) {
                if state.managingModels && state.downloadedModels.isEmpty { ProgressView().controlSize(.small) }
                if state.downloadedModels.isEmpty && !state.managingModels {
                    Text(L10n.text("다운로드한 모델이 없습니다.")).foregroundStyle(.secondary)
                }
                ForEach(state.downloadedModels) { model in
                    FormRow(L10n.message(model.name), detail: model.sizeLabel) {
                        Button(role: .destructive) { modelToDelete = model } label: { Image(systemName: "trash") }
                            .buttonStyle(.borderless).foregroundStyle(.red).help(L10n.text("삭제")).accessibilityLabel(L10n.text("삭제"))
                            .disabled(state.modelWorkIsBusy)
                    }
                }
                Button { state.showModelFolder() } label: {
                    Label(AppPaths.models.path, systemImage: "folder").font(.caption).lineLimit(1).truncationMode(.middle)
                }.buttonStyle(.link).help(L10n.text("폴더 열기")).padding(.vertical, 8)
            } accessory: {
                if state.managingModels { ProgressView().controlSize(.mini) }
                SectionAction(title: L10n.text("새로고침"), symbol: "arrow.clockwise") { state.refreshModels() }.disabled(state.managingModels)
            }.onAppear { state.refreshModels() }

            HStack {
                Text("STTS " + AppContract.shared.version).font(.caption).foregroundStyle(.tertiary)
                Spacer()
                Button(L10n.text("처음 설정")) { state.showingSetup = true }.buttonStyle(.link).font(.caption)
            }.padding(.horizontal, 6)
        }
        .alert(L10n.text("모델을 삭제할까요?"), isPresented: Binding(get: { modelToDelete != nil }, set: { if !$0 { modelToDelete = nil } }), presenting: modelToDelete) { model in
            Button(L10n.text("삭제"), role: .destructive) { state.deleteModel(model); modelToDelete = nil }
            Button(L10n.text("취소"), role: .cancel) { modelToDelete = nil }
        } message: { model in
            Text(L10n.text("{0} · {1}\n다음 사용 시 다시 다운로드합니다.", model.name, model.sizeLabel))
        }
    }
}

private struct RuntimeSettingsView: View {
    @ObservedObject var settings: RuntimeSettings
    var body: some View {
        ToggleRow(L10n.text("로그인 시 자동 실행"), isOn: Binding(get: { settings.launchAtLogin }, set: settings.setLaunchAtLogin))
            .onAppear { settings.refresh() }
            .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in settings.refresh() }
        ToggleRow(L10n.text("시작 시 백그라운드 실행"), isOn: $settings.startInBackground)
        MenuRow(L10n.text("창 닫을 때"), selection: $settings.closeAction) {
            ForEach(WindowCloseAction.allCases) { Text(L10n.text($0.rawValue)).tag($0) }
        }
        LanguageSettingView()
        if let error = settings.error { Text(L10n.message(error)).font(.caption).foregroundStyle(.red).padding(.vertical, 8) }
    }
}

private struct LanguageSettingView: View {
    @State private var choice = L10n.chosen ?? ""
    var body: some View {
        MenuRow(L10n.text("앱 언어"), selection: $choice) {
            Text(L10n.text("시스템 언어")).tag("")
            ForEach(L10n.supported, id: \.self) { Text(L10n.nativeNames[$0] ?? $0).tag($0) }
        }.onChange(of: choice) { _, value in L10n.chosen = value.isEmpty ? nil : value }
        // UI text is fixed at launch, so a different choice waits for a restart.
        if L10n.uiLanguage(for: choice.isEmpty ? Locale.preferredLanguages : [choice]) != L10n.language {
            FormRow(L10n.text("다시 시작하면 언어가 바뀝니다.")) {
                Button(L10n.text("다시 시작")) { relaunch() }.controlSize(.small)
            }.foregroundStyle(.secondary)
        }
    }
    private func relaunch() {
        // The runtime lives in Contents/Helpers of the STTS app; reopen the outer app after quitting.
        var app = Bundle.main.bundleURL
        if app.deletingLastPathComponent().lastPathComponent == "Helpers" {
            app = app.deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        }
        // A new session keeps launchd from ending the helper together with this runtime's process group.
        var attributes: posix_spawnattr_t?
        posix_spawnattr_init(&attributes); defer { posix_spawnattr_destroy(&attributes) }
        posix_spawnattr_setflags(&attributes, Int16(POSIX_SPAWN_SETSID))
        let arguments = ["/bin/sh", "-c", "sleep 1.5; /usr/bin/open \"$0\"", app.path]
        var argv = arguments.map { strdup($0) } + [nil]; defer { argv.forEach { free($0) } }
        var pid = pid_t()
        guard posix_spawn(&pid, "/bin/sh", nil, &attributes, &argv, environ) == 0 else { return }
        NSApp.terminate(nil)
    }
}
