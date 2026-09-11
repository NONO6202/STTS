import AppKit
import SwiftUI
import Testing
@testable import STTS

@Suite(.serialized) struct AppBehaviorTests {
    @Test @MainActor func voiceMonitoringDefaultsOffAndPersists() throws {
        let defaults = UserDefaults.standard, key = "voiceMonitoring"
        let saved = defaults.object(forKey: key)
        defer {
            if let saved { defaults.set(saved, forKey: key) } else { defaults.removeObject(forKey: key) }
        }
        defaults.removeObject(forKey: key)
        let state = AppState()
        #expect(!state.voiceMonitoring)
        state.voiceMonitoring = true
        #expect(AppState().voiceMonitoring)
        let view = NSHostingView(rootView: MainView(state: state))
        view.frame = NSRect(x: 0, y: 0, width: 680, height: 605)
        view.layoutSubtreeIfNeeded()
        let bitmap = try #require(view.bitmapImageRepForCachingDisplay(in: view.bounds))
        view.cacheDisplay(in: view.bounds, to: bitmap)
        let output = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent(".validation/voice-monitor/tts-mac.png")
        try FileManager.default.createDirectory(at: output.deletingLastPathComponent(), withIntermediateDirectories: true)
        try #require(bitmap.representation(using: .png, properties: [:])).write(to: output)
        state.voiceMonitoring = false
        #expect(!AppState().voiceMonitoring)
    }

    @Test @MainActor func closingCanHideOrMinimizeAndReopeningRestoresTheWindow() throws {
        let defaults = UserDefaults.standard
        let keys = ["startInBackground", "windowCloseAction", "setupCompleted"]
        let saved = keys.map { defaults.object(forKey: $0) }
        defer {
            for (key, value) in zip(keys, saved) {
                if let value { defaults.set(value, forKey: key) } else { defaults.removeObject(forKey: key) }
            }
        }
        Preferences.save(true, key: "setupCompleted")
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
