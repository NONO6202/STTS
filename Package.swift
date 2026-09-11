// swift-tools-version: 6.0
import PackageDescription
import Foundation

let brew = ProcessInfo.processInfo.environment["HOMEBREW_PREFIX"] ?? "/opt/homebrew"
let package = Package(
    name: "STTS",
    platforms: [.macOS("26.0")],
    products: [.executable(name: "STTS", targets: ["STTS"])],
    dependencies: [
        .package(url: "https://github.com/FluidInference/FluidAudio.git", exact: "0.15.6")
    ],
    targets: [
        .target(name: "WhisperBridge", publicHeadersPath: "include",
            cSettings: [.unsafeFlags(["-I\(brew)/opt/whisper-cpp/include", "-I\(brew)/opt/ggml/include"])],
            linkerSettings: [.unsafeFlags(["-L\(brew)/opt/whisper-cpp/lib", "-L\(brew)/opt/ggml/lib"]), .linkedLibrary("whisper"), .linkedLibrary("ggml"), .linkedLibrary("ggml-base")]),
        .executableTarget(name: "STTS", dependencies: ["WhisperBridge", .product(name: "FluidAudio", package: "FluidAudio")],
            linkerSettings: [.linkedFramework("Carbon"), .linkedFramework("CoreAudio"), .linkedFramework("AVFoundation")]),
        .testTarget(name: "STTSTests", dependencies: ["STTS"])
    ],
    swiftLanguageModes: [.v5]
)
