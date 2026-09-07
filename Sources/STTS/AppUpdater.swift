import AppKit
import Combine
import Sparkle

@MainActor final class AppUpdater: NSObject, ObservableObject, SPUUpdaterDelegate, SPUStandardUserDriverDelegate {
    @Published private(set) var canCheck = false
    @Published private(set) var message = ""
    @Published private(set) var availableVersion: String?
    var isBusy: () -> Bool = { false }
    private var controller: SPUStandardUpdaterController?
    private var pendingInstall: (() -> Void)?
    private var installTimer: Timer?

    func start() {
        guard controller == nil else { return }
        let controller = SPUStandardUpdaterController(startingUpdater: false, updaterDelegate: self, userDriverDelegate: self)
        self.controller = controller
        controller.updater.publisher(for: \.canCheckForUpdates).assign(to: &$canCheck)
        controller.updater.automaticallyChecksForUpdates = true
        controller.updater.automaticallyDownloadsUpdates = false
        controller.startUpdater()
        controller.updater.checkForUpdatesInBackground()
    }
    @objc func checkForUpdates() {
        guard canCheck else { return }
        message = "업데이트 확인 중…"
        controller?.checkForUpdates(nil)
    }
    func updater(_ updater: SPUUpdater, mayPerform updateCheck: SPUUpdateCheck) throws {
        if updateCheck == .updates && isBusy() { throw AppFailure("음성·자막 작업과 입력창을 닫은 뒤 업데이트해 주세요.") }
    }
    func updater(_ updater: SPUUpdater, didFindValidUpdate item: SUAppcastItem) {
        message = "새 버전 \(item.displayVersionString) 사용 가능"
        availableVersion = item.displayVersionString
    }
    func updaterDidNotFindUpdate(_ updater: SPUUpdater) { message = "최신 버전입니다."; availableVersion = nil }
    var supportsGentleScheduledUpdateReminders: Bool { true }
    func standardUserDriverShouldHandleShowingScheduledUpdate(_ update: SUAppcastItem, andInImmediateFocus immediateFocus: Bool) -> Bool { false }
    func standardUserDriverWillHandleShowingUpdate(_ handleShowingUpdate: Bool, forUpdate update: SUAppcastItem, state: SPUUserUpdateState) {
        availableVersion = update.displayVersionString
    }
    func standardUserDriverWillFinishUpdateSession() { availableVersion = nil }
    func updater(_ updater: SPUUpdater, didAbortWithError error: Error) {
        message = "업데이트 정보를 가져오지 못했습니다. 잠시 후 다시 확인해 주세요."
    }
    func updater(_ updater: SPUUpdater, shouldPostponeRelaunchForUpdate item: SUAppcastItem,
                 untilInvokingBlock installHandler: @escaping () -> Void) -> Bool {
        guard isBusy() else { return false }
        pendingInstall = installHandler
        message = "작업이 끝나면 업데이트를 설치합니다."
        installTimer?.invalidate()
        let timer = Timer(timeInterval: 1, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated {
                guard let self, !self.isBusy() else { return }
                self.installTimer?.invalidate(); self.installTimer = nil
                let install = self.pendingInstall; self.pendingInstall = nil
                install?()
            }
        }
        installTimer = timer; RunLoop.main.add(timer, forMode: .common)
        return true
    }
}
