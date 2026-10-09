import Foundation
import Darwin
import ServiceManagement

/// The launcher talks to a per-user runtime owned by launchd, never a Steam child.
enum BackgroundRuntime {
    static let label = "local.stts.runtime"
    static let domain = "gui/\(getuid())"
    static var preferences: UserDefaults {
        // The demo keeps its own settings so it never changes the full version's.
        if (Bundle.main.object(forInfoDictionaryKey: "STTSDemo") as? Bool) == true || ProcessInfo.processInfo.environment["STTS_DEMO"] == "1" {
            return UserDefaults(suiteName: "local.stts.demo")!
        }
        return Bundle.main.bundleIdentifier == "local.stts.mac" ? .standard : UserDefaults(suiteName: "local.stts.mac")!
    }
    static let directory = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/STTS/Runtime")
    static let agent = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/LaunchAgents/\(label).plist")
    static var loginEnabled: Bool {
        if let data = preferences.data(forKey: "launchAtLogin"), let value = try? JSONDecoder().decode(Bool.self, from: data) { return value }
        return Bundle.main.bundleIdentifier == "local.stts.mac" && SMAppService.mainApp.status == .enabled
    }
    static func configure(executable: URL, login: Bool) throws {
        let value: [String: Any] = ["Label": label,
                                  "ProgramArguments": [executable.path, "--background-runtime"],
                                  "RunAtLoad": login, "KeepAlive": false,
                                  "ProcessType": "Interactive"]
        let data = try PropertyListSerialization.data(fromPropertyList: value, format: .xml, options: 0)
        try FileManager.default.createDirectory(at: agent.deletingLastPathComponent(), withIntermediateDirectories: true)
        if (try? Data(contentsOf: agent)) != data { try data.write(to: agent, options: .atomic) }
        // Replace the previous main-app login item with this launchd runtime.
        if Bundle.main.bundleIdentifier == "local.stts.mac",
           [.enabled, .requiresApproval].contains(SMAppService.mainApp.status) {
            try SMAppService.mainApp.unregister()
        }
        preferences.set(try JSONEncoder().encode(login), forKey: "launchAtLogin")
    }
    @discardableResult static func launchctl(_ arguments: [String], required: Bool = true) throws -> (success: Bool, output: String) {
        let process = Process(), output = Pipe()
        process.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        process.arguments = arguments
        process.standardOutput = output; process.standardError = output
        try process.run()
        let detail = String(decoding: output.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
        process.waitUntilExit()
        if required && process.terminationStatus != 0 {
            throw NSError(domain: "STTS", code: Int(process.terminationStatus), userInfo: [NSLocalizedDescriptionKey: detail])
        }
        return (process.terminationStatus == 0, detail)
    }
    /// Steam replaces files under a runtime that keeps running, so a reply from another build is stale.
    static func outdated(_ response: [String: Any], build: Int?) -> Bool {
        guard let build, let running = response["build"] as? Int else { return false }
        return running != build
    }
    static func installedBuild(_ executable: URL) -> Int? {
        let bundle = executable.deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        return (Bundle(url: bundle)?.object(forInfoDictionaryKey: "CFBundleVersion") as? String).flatMap(Int.init)
    }
    /// Quits the old runtime and waits for its process, which still holds the lock, to exit.
    static func replace(_ response: [String: Any], directory: URL = directory, timeout: TimeInterval = 10) throws -> Bool {
        guard let pid = (response["pid"] as? NSNumber)?.int32Value, pid > 0 else { return false }
        _ = try request("quit", directory: directory)
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if kill(pid, 0) != 0 && errno == ESRCH { return true }
            Thread.sleep(forTimeInterval: 0.1)
        }
        return false
    }
    static func launch(executable: URL, show: Bool) throws {
        let login = loginEnabled
        try configure(executable: executable, login: login)
        if let running = try request("status") {
            // If the old build will not exit, keep using it rather than failing to open.
            if try !outdated(running, build: installedBuild(executable)) || !replace(running) {
                if try !show || request("show") != nil { return }
            }
        }
        let job = try launchctl(["print", domain + "/" + label], required: false)
        let running = job.output.components(separatedBy: .newlines).contains { line in
            let value = line.trimmingCharacters(in: .whitespaces)
            return value.hasPrefix("pid = ") && (Int(value.dropFirst(6)) ?? 0) > 0
        }
        // A busy or starting runtime must never be killed because its reply is late.
        if !running {
            if job.success { try launchctl(["bootout", domain + "/" + label]) }
            try launchctl(["bootstrap", domain, agent.path])
            if !login { try launchctl(["kickstart", domain + "/" + label]) }
        }
        let deadline = Date().addingTimeInterval(15)
        repeat {
            if try request(show ? "show" : "status") != nil { return }
            Thread.sleep(forTimeInterval: 0.1)
        } while Date() < deadline
        throw NSError(domain: "STTS", code: 1, userInfo: [NSLocalizedDescriptionKey: "STTS를 시작하지 못했습니다. 다시 실행해 주세요."])
    }
    static func address(_ path: String) throws -> sockaddr_un {
        let bytes = path.utf8CString
        var value = sockaddr_un()
        guard bytes.count <= MemoryLayout.size(ofValue: value.sun_path) else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(ENAMETOOLONG))
        }
        value.sun_len = UInt8(MemoryLayout<sockaddr_un>.size); value.sun_family = sa_family_t(AF_UNIX)
        bytes.withUnsafeBufferPointer { bytes in
            withUnsafeMutablePointer(to: &value.sun_path) { pointer in
                pointer.withMemoryRebound(to: CChar.self, capacity: bytes.count) { $0.update(from: bytes.baseAddress!, count: bytes.count) }
            }
        }
        return value
    }
    static func socket() throws -> Int32 {
        let fd = Darwin.socket(AF_UNIX, SOCK_STREAM, 0)
        guard fd >= 0 else { throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno)) }
        _ = fcntl(fd, F_SETFD, FD_CLOEXEC)
        var enabled: Int32 = 1
        setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &enabled, socklen_t(MemoryLayout<Int32>.size))
        var timeout = timeval(tv_sec: 2, tv_usec: 0)
        setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size))
        setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size))
        return fd
    }
    static func request(_ command: String, directory: URL = directory) throws -> [String: Any]? {
        let fd = try socket(); defer { Darwin.close(fd) }
        var address = try address(directory.appendingPathComponent("control.sock").path)
        let connected = withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { connect(fd, $0, socklen_t(MemoryLayout<sockaddr_un>.size)) }
        }
        guard connected == 0 else {
            if [ENOENT, ECONNREFUSED].contains(errno) { return nil }
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
        }
        let data = try JSONSerialization.data(withJSONObject: ["command": command]) + Data([10])
        guard data.withUnsafeBytes({ send(fd, $0.baseAddress, $0.count, 0) }) == data.count else { return nil }
        var response = Data(), bytes = [UInt8](repeating: 0, count: 2048)
        while response.count < 4096 {
            let count = recv(fd, &bytes, bytes.count, 0)
            guard count > 0 else { return nil }
            response.append(contentsOf: bytes.prefix(count))
            if response.contains(10) { return try JSONSerialization.jsonObject(with: response) as? [String: Any] }
        }
        return nil
    }
}

final class BackgroundControlServer {
    private var listener: Int32 = -1, lock: Int32 = -1
    private var source: DispatchSourceRead?
    private let queue = DispatchQueue(label: "local.stts.runtime.control")
    private let directory: URL
    init(directory: URL = BackgroundRuntime.directory, receive: @escaping @MainActor (String) -> [String: Any]) throws {
        self.directory = directory
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            lock = open(directory.appendingPathComponent("runtime.lock").path, O_CREAT | O_RDWR | O_CLOEXEC, 0o600)
            guard lock >= 0, flock(lock, LOCK_EX | LOCK_NB) == 0 else { throw NSError(domain: NSPOSIXErrorDomain, code: Int(EADDRINUSE)) }
            let path = directory.appendingPathComponent("control.sock").path
            unlink(path)
            listener = try BackgroundRuntime.socket()
            var address = try BackgroundRuntime.address(path)
            let result = withUnsafePointer(to: &address) { pointer in
                pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { bind(listener, $0, socklen_t(MemoryLayout<sockaddr_un>.size)) }
            }
            guard result == 0, chmod(path, 0o600) == 0, listen(listener, 8) == 0 else { throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno)) }
            _ = fcntl(listener, F_SETFL, O_NONBLOCK)
            let source = DispatchSource.makeReadSource(fileDescriptor: listener, queue: queue)
            source.setEventHandler { [weak self] in
                guard let self else { return }
                let client = accept(self.listener, nil, nil)
                guard client >= 0 else { return }
                _ = fcntl(client, F_SETFD, FD_CLOEXEC)
                // Darwin's accepted sockets inherit the listener's nonblocking flag.
                // Wait for the complete request instead of treating a send race as EOF.
                _ = fcntl(client, F_SETFL, fcntl(client, F_GETFL) & ~O_NONBLOCK)
                var uid: uid_t = 0, gid: gid_t = 0
                guard getpeereid(client, &uid, &gid) == 0, uid == getuid() else { Darwin.close(client); return }
                var noSignal: Int32 = 1, timeout = timeval(tv_sec: 2, tv_usec: 0)
                setsockopt(client, SOL_SOCKET, SO_NOSIGPIPE, &noSignal, socklen_t(MemoryLayout<Int32>.size))
                setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size))
                setsockopt(client, SOL_SOCKET, SO_SNDTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size))
                var data = Data(), bytes = [UInt8](repeating: 0, count: 2048)
                while data.count < 4096 && !data.contains(10) {
                    let count = recv(client, &bytes, bytes.count, 0)
                    guard count > 0 else { Darwin.close(client); return }
                    data.append(contentsOf: bytes.prefix(count))
                }
                guard let packet = try? JSONSerialization.jsonObject(with: data) as? [String: String],
                      let command = packet["command"], ["status", "show", "hide", "quit"].contains(command) else { Darwin.close(client); return }
                DispatchQueue.main.async {
                    defer { Darwin.close(client) }
                    guard self.listener >= 0, let response = try? JSONSerialization.data(withJSONObject: receive(command)) else { return }
                    let message = response + Data([10])
                    _ = message.withUnsafeBytes { send(client, $0.baseAddress, $0.count, 0) }
                }
            }
            self.source = source; source.resume()
        } catch { stop(); throw error }
    }
    func stop() {
        queue.sync {
            source?.cancel(); source = nil
            if listener >= 0 { Darwin.close(listener); listener = -1; unlink(directory.appendingPathComponent("control.sock").path) }
            if lock >= 0 { flock(lock, LOCK_UN); Darwin.close(lock); lock = -1 }
        }
    }
    deinit { stop() }
}
