import Foundation
import FluidAudio

enum SpeakerModels {
    static let folder = "ls_eend_dih3_500ms.mlmodelc"
    static let revision = "28ce1b1f8ef186729df63b3886fbaae7bc10c4a1"
    static let files: [(String, Int64, String)] = [
        ("analytics/coremldata.bin", 243, "0d0577390ca35f2d7e42a1e75c3d4275127b262c37750a48fec0ac1d711ab2ff"),
        ("coremldata.bin", 1413, "3cc2c2502a1cfbc4ccf456695ae9130fb7f0dbfb992c52a2ebd8f20654744133"),
        ("metadata.json", 7024, "6abe993aced34e0a6a370008d202082b5d7887c889bda422ef68df4576daaa46"),
        ("model.mil", 240061, "ecb88f7ee68ea88760270ba35c630dcade651d3622e2b34a9e44b1d8af880c18"),
        ("weights/weight.bin", 44457216, "76ce7934e2cd91a0effb70dfa90fb24edb66bc9a764b290ee2065b896721b3cb")
    ]
    static func load() async throws -> LSEENDModel {
        for (file, bytes, hash) in files {
            let asset = ModelAsset(name: "화자 구분", file: "Speakers/\(folder)/\(file)", repo: "FluidInference/ls-eend-coreml", revision: revision, bytes: bytes, sha256: hash, sourceFile: "optimized/dih3/500ms/\(folder)/\(file)")
            try await AssetDownloader.prepare(asset) { _ in }
        }
        try Task.checkCancellation()
        return try LSEENDModel(modelURL: AppPaths.models.appendingPathComponent("Speakers/\(folder)"), computeUnits: .cpuOnly)
    }
}
