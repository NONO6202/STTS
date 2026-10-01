import Foundation
import Darwin

/// Local achievement progress. A short-lived helper process tells Steam about new unlocks,
/// so the always-on runtime never shows up as a running game in Steam.
@MainActor final class AchievementTracker {
    private struct Progress: Codable {
        var counts: [String: Int] = [:]
        var sets: [String: [String]] = [:]
        var unlocked: [String] = []
        var reported: [String] = []
    }
    private let url: URL
    private let enabled: Bool
    private var progress: Progress
    private var reporting = false
    /// Only packaged full builds carry the Steam library; source runs and tests never contact Steam.
    nonisolated static var available: Bool {
        !Edition.isDemo && FileManager.default.fileExists(atPath: Bundle.main.bundleURL.appendingPathComponent("Contents/Frameworks/libsteam_api.dylib").path)
    }
    init(folder: URL = AppPaths.support, enabled: Bool = AchievementTracker.available) {
        url = folder.appendingPathComponent("achievements.json"); self.enabled = enabled
        progress = (try? JSONDecoder().decode(Progress.self, from: Data(contentsOf: url))) ?? Progress()
    }
    private func value(_ stat: String) -> Int { max(progress.counts[stat] ?? 0, progress.sets[stat]?.count ?? 0) }
    func count(_ stat: String, by amount: Int = 1) { progress.counts[stat, default: 0] += amount; check() }
    /// Distinct values, such as the microphone filters or languages used.
    func include(_ stat: String, _ item: String) {
        guard !(progress.sets[stat] ?? []).contains(item) else { return }
        progress.sets[stat, default: []].append(item); check()
    }
    /// Current totals, such as saved phrases; the best total is kept.
    func level(_ stat: String, _ total: Int) {
        guard total > (progress.counts[stat] ?? 0) else { return }
        progress.counts[stat] = total; check()
    }
    func check() {
        guard enabled else { return }
        for goal in AppContract.shared.achievements where !progress.unlocked.contains(goal.id) && value(goal.stat) >= goal.goal {
            progress.unlocked.append(goal.id)
        }
        try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? JSONEncoder().encode(progress).write(to: url, options: .atomic)
        let pending = progress.unlocked.filter { !progress.reported.contains($0) }
        guard !pending.isEmpty, !reporting, let executable = Bundle.main.executableURL else { return }
        reporting = true
        Task.detached(priority: .utility) {
            // Steam may be closed; unreported unlocks are retried at the next check.
            let process = Process(); process.executableURL = executable
            process.arguments = ["--steam-achievements"] + pending
            let stored = (try? process.run()) != nil && { process.waitUntilExit(); return process.terminationStatus == 0 }()
            await MainActor.run {
                self.reporting = false
                if stored { self.progress.reported = Array(Set(self.progress.reported + pending)).sorted(); try? JSONEncoder().encode(self.progress).write(to: self.url, options: .atomic) }
            }
        }
    }
}

/// Unlocks Steam achievements through the Steamworks flat API, then exits.
enum SteamAchievements {
    static func unlock(_ ids: [String]) -> Int32 {
        // The runtime is started by launchd, not Steam, so the helper names its app itself.
        let app = String(AppContract.shared.steamAppId)
        setenv("SteamAppId", app, 0); setenv("SteamGameId", app, 0)
        let frameworks = Bundle.main.bundleURL.appendingPathComponent("Contents/Frameworks/libsteam_api.dylib")
        guard let steam = dlopen(frameworks.path, RTLD_NOW) else { return 2 }
        func symbol<T>(_ name: String, as type: T.Type) -> T? { dlsym(steam, name).map { unsafeBitCast($0, to: type) } }
        typealias Init = @convention(c) (UnsafeMutablePointer<CChar>?) -> Int32
        typealias Plain = @convention(c) () -> Void
        typealias Stats = @convention(c) () -> OpaquePointer?
        typealias Set = @convention(c) (OpaquePointer?, UnsafePointer<CChar>) -> Bool
        typealias Store = @convention(c) (OpaquePointer?) -> Bool
        guard let initialize = symbol("SteamAPI_InitFlat", as: Init.self), let run = symbol("SteamAPI_RunCallbacks", as: Plain.self),
              let shutdown = symbol("SteamAPI_Shutdown", as: Plain.self), let userStats = symbol("SteamAPI_SteamUserStats_v013", as: Stats.self),
              let set = symbol("SteamAPI_ISteamUserStats_SetAchievement", as: Set.self),
              let store = symbol("SteamAPI_ISteamUserStats_StoreStats", as: Store.self) else { return 2 }
        var message = [CChar](repeating: 0, count: 1024)
        guard initialize(&message) == 0 else { return 1 }
        defer { shutdown() }
        let stats = userStats()
        var pending = Swift.Set(ids)
        let deadline = Date().addingTimeInterval(10)
        // Setting fails until Steam has sent this user's current stats.
        while !pending.isEmpty && Date() < deadline {
            run()
            pending = pending.filter { !set(stats, $0) }
            if !pending.isEmpty { usleep(100_000) }
        }
        guard pending.isEmpty, store(stats) else { return 1 }
        for _ in 0..<20 { run(); usleep(100_000) }
        return 0
    }
}
