import AppKit
import Sparkle
import SwiftUI
import Testing
@testable import STTS

@Suite(.serialized) struct AppBehaviorTests {
    @Test @MainActor func updateReminderTracksAvailableVersionsWithoutInterruptingBackgroundWork() throws {
        let updates = AppUpdater()
        let controller = SPUStandardUpdaterController(startingUpdater: false, updaterDelegate: updates, userDriverDelegate: updates)
        let item = try #require(SUAppcastItem(dictionary: [
            "title": "STTS 0.7.0", "enclosure": ["url": "https://example.invalid/STTS.zip", "sparkle:version": "7", "sparkle:shortVersionString": "0.7.0", "length": "100", "type": "application/octet-stream"]
        ]))
        #expect(updates.availableVersion == nil)
        updates.updater(controller.updater, didFindValidUpdate: item)
        #expect(updates.availableVersion == "0.7.0")
        #expect(updates.supportsGentleScheduledUpdateReminders)
        #expect(!updates.standardUserDriverShouldHandleShowingScheduledUpdate(item, andInImmediateFocus: true))
        updates.isBusy = { true }
        try updates.updater(controller.updater, mayPerform: .updatesInBackground)
        #expect(throws: AppFailure.self) { try updates.updater(controller.updater, mayPerform: .updates) }
        let view = NSHostingView(rootView: UpdateBadge(updates: updates, busy: false).padding(8))
        view.frame = NSRect(x: 0, y: 0, width: 42, height: 42)
        view.layoutSubtreeIfNeeded()
        let bitmap = try #require(view.bitmapImageRepForCachingDisplay(in: view.bounds))
        view.cacheDisplay(in: view.bounds, to: bitmap)
        let output = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent(".validation/runtime-settings/update-badge.png")
        try FileManager.default.createDirectory(at: output.deletingLastPathComponent(), withIntermediateDirectories: true)
        try #require(bitmap.representation(using: .png, properties: [:])).write(to: output)
        updates.updaterDidNotFindUpdate(controller.updater)
        #expect(updates.availableVersion == nil)
        updates.updater(controller.updater, didFindValidUpdate: item)
        updates.standardUserDriverWillFinishUpdateSession()
        #expect(updates.availableVersion == nil)
    }

    @Test @MainActor func closingCanHideOrMinimizeAndReopeningRestoresTheWindow() throws {
        let defaults = UserDefaults.standard
        let keys = ["startInBackground", "windowCloseAction"]
        let saved = keys.map { defaults.object(forKey: $0) }
        defer {
            for (key, value) in zip(keys, saved) {
                if let value { defaults.set(value, forKey: key) } else { defaults.removeObject(forKey: key) }
            }
        }
        let app = NSApplication.shared, delegate = AppDelegate()
        delegate.state.runtime.startInBackground = true
        #expect(RuntimeSettings().startInBackground)
        delegate.showMain()
        let window = try #require(app.windows.first { $0.title == "STTS" })
        window.animationBehavior = .none
        defer { window.delegate = nil; window.close(); delegate.state.shutdown() }
        delegate.state.runtime.closeAction = .background
        window.performClose(nil)
        #expect(!window.isVisible)
        _ = delegate.applicationShouldHandleReopen(app, hasVisibleWindows: false)
        #expect(window.isVisible)
        delegate.state.runtime.closeAction = .minimize
        window.performClose(nil)
        RunLoop.current.run(until: Date().addingTimeInterval(0.5))
        #expect(window.isMiniaturized)
        _ = delegate.applicationShouldHandleReopen(app, hasVisibleWindows: false)
        RunLoop.current.run(until: Date().addingTimeInterval(0.5))
        #expect(!window.isMiniaturized && window.isVisible)
    }
}
