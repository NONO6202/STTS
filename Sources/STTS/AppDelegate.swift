import SwiftUI
import AppKit

@MainActor final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    let state = AppState()
    private var main: NSWindow?
    private var composer: InputPanel?
    private var overlay: NSPanel?
    private var menuItem: NSStatusItem?
    private var hotkey: GlobalHotKey?
    private var captionHotkey: GlobalHotKey?
    private var previousApp: NSRunningApplication?
    private var shakeTimer: Timer?
    private var shakeLocalMonitor: Any?
    private var shakeGlobalMonitor: Any?
    private var shakePosition = CGPoint.zero
    private var shakeDetector = MouseShakeDetector()
    func applicationDidFinishLaunching(_ notification: Notification) {
        if state.ttsEnabled { state.connectMicrophone() } else { state.removeMicrophone() }
        state.closeComposer = { [weak self] in self?.closeComposer() }
        state.overlayChanged = { [weak self] in self?.updateOverlay() }
        state.appearanceChanged = { [weak self] in self?.composer?.invalidateShadow() }
        state.shortcutChanged = { [weak self] shortcut in
            guard let self else { return }
            if let hotkey = self.hotkey { try hotkey.update(shortcut) }
            else { self.hotkey = try GlobalHotKey(shortcut: shortcut) { [weak self] in self?.showComposer() } }
        }
        do { hotkey = try GlobalHotKey(shortcut: state.shortcut) { [weak self] in self?.showComposer() } }
        catch { state.error = error.localizedDescription }
        state.captionShortcutChanged = { [weak self] shortcut in
            guard let self else { return }
            if let hotkey = self.captionHotkey { try hotkey.update(shortcut) }
            else { self.captionHotkey = try GlobalHotKey(shortcut: shortcut, identifier: 2) { [weak self] in self?.state.toggleCaptions() } }
        }
        do { captionHotkey = try GlobalHotKey(shortcut: state.captionShortcut, identifier: 2) { [weak self] in self?.state.toggleCaptions() } }
        catch { state.error = error.localizedDescription }
        let menu = NSMenu()
        for (title, action) in [("STTS 열기", #selector(showMain)), ("입력창 열기", #selector(showComposer)), ("자막 중지", #selector(stopCaptions)), ("종료", #selector(quit))] {
            let item = NSMenuItem(title: title, action: action, keyEquivalent: ""); item.target = self; menu.addItem(item)
        }
        menuItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        menuItem?.button?.title = "STTS"; menuItem?.menu = menu
        let mainMenu = NSMenu()
        let appMenu = NSMenu(title: "STTS")
        let quitItem = NSMenuItem(title: "STTS 종료", action: #selector(quit), keyEquivalent: "q")
        quitItem.target = self; appMenu.addItem(quitItem)
        let appRoot = NSMenuItem(); appRoot.submenu = appMenu; mainMenu.addItem(appRoot)
        let editMenu = NSMenu(title: "편집")
        for (title, action, key) in [("실행 취소", Selector(("undo:")), "z"), ("잘라내기", #selector(NSText.cut(_:)), "x"), ("복사", #selector(NSText.copy(_:)), "c"), ("붙여넣기", #selector(NSText.paste(_:)), "v"), ("모두 선택", #selector(NSText.selectAll(_:)), "a")] {
            editMenu.addItem(NSMenuItem(title: title, action: action, keyEquivalent: key))
        }
        let editRoot = NSMenuItem(); editRoot.submenu = editMenu; mainMenu.addItem(editRoot)
        NSApp.mainMenu = mainMenu
        if CommandLine.arguments.contains("--show") || !state.runtime.startInBackground || !Preferences.read("setupCompleted", fallback: false) { showMain() }
    }
    @objc func showMain() {
        if main == nil {
            let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: AppContract.shared.window.width, height: AppContract.shared.window.height), styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
            window.title = "STTS"; window.isReleasedWhenClosed = false
            window.delegate = self
            window.acceptsMouseMovedEvents = true
            window.isOpaque = true; window.backgroundColor = .windowBackgroundColor
            window.contentView = NSHostingView(rootView: MainView(state: state)); window.center(); main = window
        }
        if main?.isMiniaturized == true { main?.deminiaturize(nil) }
        NSApp.activate(ignoringOtherApps: true); main?.makeKeyAndOrderFront(nil)
    }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showMain(); return false
    }
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        guard sender === main else { return true }
        state.cancelVoiceRecording()
        switch state.runtime.closeAction {
        case .background: sender.orderOut(nil)
        case .minimize: sender.miniaturize(nil)
        case .quit: NSApp.terminate(nil)
        }
        return false
    }
    func windowDidMiniaturize(_ notification: Notification) {
        if notification.object as? NSWindow === main { state.cancelVoiceRecording() }
    }
    @objc func showComposer() {
        if composer?.isVisible == true { closeComposer(); return }
        guard state.ttsEnabled, !state.speaking else { return }
        previousApp = NSWorkspace.shared.frontmostApplication
        state.error = nil
        let mouse = NSEvent.mouseLocation
        let screen = NSScreen.screens.first(where: { $0.frame.contains(mouse) }) ?? NSScreen.main ?? NSScreen.screens[0]
        let frame = ComposerPlacement.frame(near: mouse, in: screen.visibleFrame)
        let panel = InputPanel(contentRect: frame, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        panel.delegate = panel
        panel.title = "STTS 입력"; panel.level = .floating
        panel.isOpaque = false; panel.backgroundColor = .clear; panel.hasShadow = true
        panel.isReleasedWhenClosed = false; panel.hidesOnDeactivate = false
        panel.acceptsMouseMovedEvents = true
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        let hosting = NSHostingView(rootView: ComposerView(state: state, library: state.soundboard, resize: { [weak panel] count in
            guard let panel else { return }
            let height = CGFloat(44 + (count > 0 ? count * 32 + 8 : 0))
            let resized = NSRect(x: frame.minX, y: max(screen.visibleFrame.minY + 8, frame.maxY - height), width: frame.width, height: height)
            panel.setFrame(resized, display: true); panel.contentView?.frame = NSRect(origin: .zero, size: resized.size)
        }) { [weak self] in self?.closeComposer() })
        hosting.sizingOptions = []
        hosting.frame = NSRect(origin: .zero, size: frame.size)
        panel.contentView = hosting
        panel.setFrame(frame, display: false); composer = panel
        panel.makeKeyAndOrderFront(nil)
        shakeDetector = MouseShakeDetector()
        shakePosition = .zero
        _ = shakeDetector.sample(shakePosition, at: ProcessInfo.processInfo.systemUptime)
        let inputEvent: (NSEvent) -> Void = { [weak self] event in
            guard let self, let panel = self.composer, panel.isVisible else { return }
            switch event.type {
            case .leftMouseDown, .rightMouseDown, .otherMouseDown:
                if self.state.closeOnOutsideClick, event.window !== panel { self.closeComposer(restoreFocus: false) }
            default:
                // Games can lock or recenter the cursor while mouse deltas keep arriving.
                guard self.state.closeOnMouseShake else { return }
                self.shakePosition.x += event.deltaX
                self.shakePosition.y += event.deltaY
            }
        }
        let mask: NSEvent.EventTypeMask = [.mouseMoved, .leftMouseDragged, .rightMouseDragged, .otherMouseDragged,
                                         .leftMouseDown, .rightMouseDown, .otherMouseDown]
        shakeGlobalMonitor = NSEvent.addGlobalMonitorForEvents(matching: mask, handler: inputEvent)
        shakeLocalMonitor = NSEvent.addLocalMonitorForEvents(matching: mask) { event in
            inputEvent(event); return event
        }
        let timer = Timer(timeInterval: 1.0 / 60, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated {
                guard let self, self.composer?.isVisible == true else { return }
                guard self.state.closeOnMouseShake else { self.shakeDetector = MouseShakeDetector(); return }
                if self.shakeDetector.sample(self.shakePosition, at: ProcessInfo.processInfo.systemUptime,
                                             sensitivity: self.state.mouseShakeSensitivity) { self.closeComposer() }
            }
        }
        shakeTimer = timer; RunLoop.main.add(timer, forMode: .common)
    }
    private func closeComposer(restoreFocus: Bool = true) {
        stopShakeDetection()
        composer?.orderOut(nil); composer = nil
        if restoreFocus, previousApp?.processIdentifier != ProcessInfo.processInfo.processIdentifier { previousApp?.activate(options: []) }
        previousApp = nil
    }
    private func stopShakeDetection() {
        shakeTimer?.invalidate(); shakeTimer = nil
        if let shakeLocalMonitor { NSEvent.removeMonitor(shakeLocalMonitor) }; shakeLocalMonitor = nil
        if let shakeGlobalMonitor { NSEvent.removeMonitor(shakeGlobalMonitor) }; shakeGlobalMonitor = nil
    }
    func updateOverlay() {
        guard state.overlayVisible, state.sttEnabled else { overlay?.orderOut(nil); return }
        if overlay == nil {
            let panel = NSPanel(contentRect: .zero, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
            panel.title = "STTS 자막"
            panel.level = .floating; panel.isOpaque = false; panel.backgroundColor = .clear
            panel.ignoresMouseEvents = true; panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
            overlay = panel
        }
        let frame = (NSScreen.main ?? NSScreen.screens[0]).visibleFrame
        let width = min(AppContract.shared.caption.width, frame.width - 40)
        let view = VStack(alignment: .leading, spacing: 6) {
            ForEach(state.visibleCaptions) { caption in
                Text(caption.text).font(.system(size: self.state.captionFontSize, weight: .medium))
                    .foregroundStyle(self.state.captionStyle.foreground.color)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }.frame(minHeight: 28, alignment: .leading).padding(AppContract.shared.caption.padding)
            .frame(width: width, alignment: .leading)
            .background(state.captionStyle.background.color.opacity(state.captionStyle.opacity))
            .clipShape(RoundedRectangle(cornerRadius: AppContract.shared.caption.radius))
        let hosting = NSHostingView(rootView: view)
        overlay?.contentView = hosting
        let size = hosting.fittingSize
        overlay?.setFrame(NSRect(x: frame.midX - size.width / 2,
                                y: frame.minY + AppContract.shared.defaults.captionY,
                                width: size.width, height: min(size.height, frame.height - 40)), display: true)
        overlay?.orderFrontRegardless()
    }
    @objc private func stopCaptions() { state.stop() }
    @objc private func quit() { NSApp.terminate(nil) }
    func applicationWillTerminate(_ notification: Notification) { stopShakeDetection(); state.shutdown() }
}
