import Foundation
import Darwin
import Testing
@testable import STTS

@Suite(.serialized) struct BackgroundRuntimeTests {
    private func folder() -> URL { FileManager.default.temporaryDirectory.appendingPathComponent("stts-runtime-" + UUID().uuidString.prefix(8)) }
    @Test @MainActor func secondRuntimeCannotReplaceAnActiveControlSocket() async throws {
        let directory = folder(); defer { try? FileManager.default.removeItem(at: directory) }
        let server = try BackgroundControlServer(directory: directory) { _ in ["pid": getpid()] }
        defer { server.stop() }
        do {
            let duplicate = try BackgroundControlServer(directory: directory) { _ in [:] }
            duplicate.stop(); Issue.record("A second runtime acquired the active address")
        } catch { #expect((error as NSError).code == Int(EADDRINUSE)) }
        #expect(FileManager.default.fileExists(atPath: directory.appendingPathComponent("control.sock").path))
        let response = try await Task.detached { try BackgroundRuntime.request("status", directory: directory) }.value
        #expect(response != nil, "The original runtime must still answer after a duplicate is rejected")
        #expect(response?["pid"] as? Int32 == getpid())
        let attributes = try FileManager.default.attributesOfItem(atPath: directory.appendingPathComponent("control.sock").path)
        #expect(attributes[.posixPermissions] as? Int == 0o600)
    }
    @Test @MainActor func launcherDisconnectionDoesNotStopRuntimeAndRequestsReuseIt() async throws {
        let directory = folder(); defer { try? FileManager.default.removeItem(at: directory) }
        var commands: [String] = []
        let server = try BackgroundControlServer(directory: directory) { command in
            commands.append(command); return ["pid": getpid()]
        }
        defer { server.stop() }
        for command in ["show", "hide", "show", "status"] {
            let response = try await Task.detached { try BackgroundRuntime.request(command, directory: directory) }.value
            #expect(response?["pid"] as? Int32 == getpid())
        }
        #expect(commands == ["show", "hide", "show", "status"])
    }
    @Test @MainActor func fullStopDoesNotRestartButAnExplicitNewStartCanReuseTheAddress() async throws {
        let directory = folder(); defer { try? FileManager.default.removeItem(at: directory) }
        let server = try BackgroundControlServer(directory: directory) { _ in ["pid": getpid()] }
        server.stop()
        #expect(try BackgroundRuntime.request("status", directory: directory) == nil)
        let replacement = try BackgroundControlServer(directory: directory) { _ in ["pid": getpid()] }
        defer { replacement.stop() }
        let response = try await Task.detached { try BackgroundRuntime.request("show", directory: directory) }.value
        #expect(response?["pid"] as? Int32 == getpid())
    }
    @Test func onlyAReplyFromAnotherBuildIsOutdated() {
        #expect(BackgroundRuntime.outdated(["pid": 7, "build": 16], build: 17))
        #expect(!BackgroundRuntime.outdated(["pid": 7, "build": 17], build: 17))
        #expect(!BackgroundRuntime.outdated(["pid": 7], build: 17))
        #expect(!BackgroundRuntime.outdated(["pid": 7, "build": 16], build: nil))
    }
    @Test @MainActor func previousBuildIsQuitAndAwaitedBeforeReplacement() async throws {
        let directory = folder(); defer { try? FileManager.default.removeItem(at: directory) }
        let old = Process(); old.executableURL = URL(fileURLWithPath: "/bin/sleep"); old.arguments = ["30"]
        try old.run(); defer { if old.isRunning { old.terminate() } }
        var commands: [String] = []
        let server = try BackgroundControlServer(directory: directory) { command in
            commands.append(command)
            if command == "quit" { old.terminate() }
            return ["pid": old.processIdentifier, "build": 16]
        }
        defer { server.stop() }
        let response = try #require(try await Task.detached { try BackgroundRuntime.request("status", directory: directory) }.value)
        #expect(BackgroundRuntime.outdated(response, build: 17))
        let replaced = try await Task.detached { try BackgroundRuntime.replace(response, directory: directory, timeout: 5) }.value
        #expect(replaced)
        #expect(commands == ["status", "quit"])
    }
    @Test func legacyClosePreferenceCannotTurnWindowCloseIntoFullQuit() {
        let defaults = Preferences.defaults, key = "windowCloseAction", saved = defaults.object(forKey: "windowCloseAction")
        defer { if let saved { defaults.set(saved, forKey: key) } else { defaults.removeObject(forKey: key) } }
        defaults.set(try? JSONEncoder().encode("앱 종료"), forKey: key)
        #expect(Preferences.read(key, fallback: WindowCloseAction.background) == .background)
    }
}
