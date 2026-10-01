import AppKit
import Foundation

@main struct STTSLauncher {
    static func main() {
        let runtime = Bundle.main.bundleURL.appendingPathComponent("Contents/Helpers/STTSRuntime.app/Contents/MacOS/STTS")
        let arguments = Array(CommandLine.arguments.dropFirst())
        do {
            if arguments.contains("--smoke-test") || arguments.contains("--prepare-models") {
                let process = Process(); process.executableURL = runtime; process.arguments = arguments
                try process.run(); process.waitUntilExit(); exit(process.terminationStatus)
            }
            if let command = ["status", "hide", "quit"].first(where: { arguments.contains("--" + $0) }) {
                guard let response = try BackgroundRuntime.request(command) else { exit(1) }
                FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: response) + Data([10]))
                return
            }
            try BackgroundRuntime.launch(executable: runtime, show: !arguments.contains("--background"))
        } catch {
            FileHandle.standardError.write(Data((error.localizedDescription + "\n").utf8))
            let alert = NSAlert()
            alert.messageText = "STTS"
            alert.informativeText = NSLocalizedString("STTS를 시작하지 못했습니다. 다시 실행해 주세요.", comment: "")
            alert.runModal(); exit(1)
        }
    }
}
