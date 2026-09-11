import AppKit
import Combine
import ServiceManagement

enum WindowCloseAction: String, CaseIterable, Identifiable, Codable {
    case background = "백그라운드 실행", minimize = "최소화", quit = "앱 종료"
    var id: String { rawValue }
}

@MainActor final class RuntimeSettings: ObservableObject {
    @Published var startInBackground = Preferences.read("startInBackground", fallback: AppContract.shared.defaults.background) {
        didSet { Preferences.save(startInBackground, key: "startInBackground") }
    }
    @Published var closeAction = Preferences.read("windowCloseAction", fallback: WindowCloseAction.background) {
        didSet { Preferences.save(closeAction, key: "windowCloseAction") }
    }
    @Published private(set) var loginStatus = SMAppService.mainApp.status
    @Published private(set) var error: String?
    var launchAtLogin: Bool { loginStatus == .enabled || loginStatus == .requiresApproval }
    func refresh() { loginStatus = SMAppService.mainApp.status }
    func setLaunchAtLogin(_ enabled: Bool) {
        do {
            let service = SMAppService.mainApp
            if enabled && service.status != .enabled && service.status != .requiresApproval { try service.register() }
            else if !enabled && (service.status == .enabled || service.status == .requiresApproval) { try service.unregister() }
            error = nil
        } catch { self.error = error.localizedDescription }
        refresh()
    }
    func openLoginSettings() { SMAppService.openSystemSettingsLoginItems() }
}
