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
        if let error = settings.error { Text(L10n.message(error)).font(.caption).foregroundStyle(.red).padding(.vertical, 8) }
    }
}
