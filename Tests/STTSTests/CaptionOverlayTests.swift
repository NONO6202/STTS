import AppKit
import Testing
@testable import STTS

@Suite struct CaptionOverlayTests {
    @Test @MainActor func backgroundStaysVisibleWithoutTextUntilStopped() throws {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        delegate.state.overlayChanged = { [weak delegate] in delegate?.updateOverlay() }
        defer { delegate.state.stop() }
        #expect(delegate.state.language == "auto")

        // Exercise the native panel synchronously, then cancel before audio/model setup can run.
        delegate.state.sttEnabled = true
        let panel = try #require(app.windows.first { $0.title == "STTS 자막" })
        defer { panel.close() }
        #expect(panel.isVisible)
        #expect(panel.frame.width == 750 && panel.frame.height >= 56)
        #expect(panel.ignoresMouseEvents && panel.level == .floating)

        delegate.state.visibleCaptions = [Caption(text: "테스트 자막", start: 0, end: 1, duration: 1)]
        delegate.updateOverlay()
        #expect(panel.isVisible)
        delegate.state.visibleCaptions = []
        delegate.updateOverlay()
        #expect(panel.isVisible)
        #expect(panel.frame.height >= 56)

        delegate.state.sttEnabled = false
        #expect(!panel.isVisible)
        #expect(!delegate.state.preparing && !delegate.state.listening)
    }
}
