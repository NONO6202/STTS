import Foundation

/// Product choices shared with Windows; OS-specific settings keep their existing storage keys.
enum AppContract {
    struct Window: Decodable { let width, height, padding, spacing, tabsWidth: Double }
    struct Setting: Decodable, Identifiable { let id, title, symbol: String }
    struct Section: Decodable { let title, text: String }
    struct Onboarding: Decodable { let title, button: String; let sections: [Section] }
    struct Tier: Decodable { let title, model: String }
    struct Defaults: Decodable {
        let voice, windowBg, windowColor, captionBg, captionColor: String
        let background, login, ttsEnabled, voiceMonitoring, outside, shake, keepDraft: Bool
        let volume, windowAlpha, captionAlpha, captionFont, captionY: Double
    }
    struct Limits: Decodable { let text, transcript: Int; let recordingMin, recordingMax, voicePeak: Double }
    /// Layout and colour tokens both platforms draw from, so the two apps stay identical.
    struct Theme: Decodable { let accent: String; let cardRadius, controlRadius, pagePadding, pageTop, rowHeight, rowInset, sectionGap: Double }
    struct Caption: Decodable { let width, expirySeconds, padding, radius: Double; let history, visible: Int }
    struct Manifest: Decodable {
        let version: String
        let build: Int
        let window: Window
        let tabs: [String]
        let settings, tools: [Setting]
        let onboarding: Onboarding
        let ttsTiers, sttTiers: [Tier]
        let voices: [String: [String]]
        let defaults: Defaults
        let limits: Limits
        let caption: Caption
        let theme: Theme
        let shakeSensitivities: [String: Double]
        let modelNames: [String: String]
        let languageOrder: [String]
    }
    static let shared: Manifest = {
        let source = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("Shared/app.json")
        let url = Bundle.main.url(forResource: "app", withExtension: "json") ?? source
        do {
            let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
            return try decoder.decode(Manifest.self, from: Data(contentsOf: url))
        } catch { preconditionFailure("Cannot load STTS product configuration: \(error)") }
    }()
}
