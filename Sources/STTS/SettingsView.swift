import SwiftUI
import AppKit

private enum SettingsPage: String, Identifiable {
    case runtime, input, models
    var id: String { rawValue }
    static var pages: [Self] { AppContract.shared.settings.compactMap { Self(rawValue: $0.id) } }
    private var definition: AppContract.Setting { AppContract.shared.settings.first { $0.id == rawValue }! }
    var title: String { definition.title }
    var symbol: String { definition.symbol }
}

struct SettingsView: View {
    @ObservedObject var state: AppState
    @State private var page: SettingsPage?
    @State private var modelToDelete: DownloadedModel?
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            if let page {
                HStack(spacing: 12) {
                    Button { self.page = nil } label: { Label("설정", systemImage: "chevron.left") }
                    Text(page.title).font(.headline)
                }
                Divider()
                ScrollView {
                    content(for: page).settingsCard().frame(maxWidth: .infinity, alignment: .leading)
                }.id(page)
            } else {
                Text("설정").font(.system(size: 24, weight: .bold))
                ForEach(SettingsPage.pages) { destination in
                    Button {
                        page = destination
                        if destination == .models { state.refreshModels() }
                    } label: {
                        HStack(spacing: 14) {
                            Image(systemName: destination.symbol).font(.title3).frame(width: 26).foregroundStyle(.tint)
                            Text(destination.title).font(.headline)
                            Spacer()
                            Image(systemName: "chevron.right").foregroundStyle(.secondary)
                        }.padding(20).contentShape(Rectangle())
                            .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 18))
                    }.buttonStyle(.plain)
                }
                HStack {
                    Text("STTS " + AppContract.shared.version).font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Button("처음 설정") { state.showingSetup = true }
                }
                Spacer(minLength: 0)
            }
        }.padding(24).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
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
            VStack(alignment: .leading, spacing: 18) {
                RuntimeSettingsView(settings: state.runtime)
                Divider()
                Text("가상 마이크").font(.headline)
                Text(state.microphoneReady ? "STTS 연결됨" : "TTS를 켜면 가상 마이크를 연결합니다.").font(.caption).foregroundStyle(.secondary)
                HStack {
                    Button("연결 확인") { state.connectMicrophone() }.disabled(!state.ttsEnabled || state.modelWorkIsBusy)
                    Button("소리 설정") { NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.Sound-Settings.extension")!) }
                }
            }
        case .input:
            VStack(alignment: .leading, spacing: 16) {
                Text("입력창 닫기").font(.headline)
                Toggle("입력창 밖을 클릭하면 닫기", isOn: $state.closeOnOutsideClick).toggleStyle(.switch)
                Toggle("마우스를 흔들면 닫기", isOn: $state.closeOnMouseShake).toggleStyle(.switch)
                Picker("흔들기 민감도", selection: $state.mouseShakeSensitivity) {
                    ForEach(MouseShakeSensitivity.allCases) { Text($0.rawValue).tag($0) }
                }.disabled(!state.closeOnMouseShake)
            }
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

private struct RuntimeSettingsView: View {
    @ObservedObject var settings: RuntimeSettings
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Toggle("로그인 시 자동 실행", isOn: Binding(get: { settings.launchAtLogin }, set: settings.setLaunchAtLogin))
                .toggleStyle(.switch)
            if settings.loginStatus == .requiresApproval {
                HStack { Text("승인 필요").font(.caption); Button("로그인 항목 설정") { settings.openLoginSettings() } }
            }
            Toggle("시작 시 백그라운드 실행", isOn: $settings.startInBackground).toggleStyle(.switch)
            Picker("창 닫을 때", selection: $settings.closeAction) {
                ForEach(WindowCloseAction.allCases) { Text($0.rawValue).tag($0) }
            }
            if let error = settings.error { Text(error).font(.caption).foregroundStyle(.red) }
        }.onAppear { settings.refresh() }
            .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in settings.refresh() }
    }
}
