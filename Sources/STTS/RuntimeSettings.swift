import AppKit
import Combine

enum WindowCloseAction: String, CaseIterable, Identifiable, Codable {
    case background = "백그라운드 실행", minimize = "최소화"
    var id: String { rawValue }
}

@MainActor final class RuntimeSettings: ObservableObject {
    @Published var startInBackground = Preferences.read("startInBackground", fallback: AppContract.shared.defaults.background) {
        didSet { Preferences.save(startInBackground, key: "startInBackground") }
    }
    @Published var closeAction = Preferences.read("windowCloseAction", fallback: WindowCloseAction.background) {
        didSet { Preferences.save(closeAction, key: "windowCloseAction") }
    }
    @Published private(set) var launchAtLogin = BackgroundRuntime.loginEnabled
    @Published private(set) var error: String?
    func refresh() { launchAtLogin = BackgroundRuntime.loginEnabled }
    func setLaunchAtLogin(_ enabled: Bool) {
        do {
            guard let executable = Bundle.main.executableURL else { throw AppFailure("STTS를 시작하지 못했습니다. 다시 실행해 주세요.") }
            try BackgroundRuntime.configure(executable: executable, login: enabled)
            error = nil
        } catch { self.error = error.localizedDescription }
        refresh()
    }
}
