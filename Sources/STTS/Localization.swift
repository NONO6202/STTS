import Foundation

enum L10n {
    static let supported = ["ko", "en", "ja", "zh-Hans", "es", "fr", "de", "pt"]
    static let nativeNames = ["ko": "한국어", "en": "English", "ja": "日本語", "zh-Hans": "简体中文", "es": "Español", "fr": "Français", "de": "Deutsch", "pt": "Português"]
    /// The app language picked in settings, or nil to follow the system.
    static var chosen: String? {
        get { Preferences.defaults.string(forKey: "uiLanguage").flatMap { supported.contains($0) ? $0 : nil } }
        set { if let newValue { Preferences.defaults.set(newValue, forKey: "uiLanguage") } else { Preferences.defaults.removeObject(forKey: "uiLanguage") } }
    }
    struct Catalog: Decodable {
        let strings: [String: [String: String]]
        let languageNames: [String: [String: String]]
    }
    static let catalog: Catalog = {
        let source = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("Shared/localization.json")
        let url = Bundle.main.url(forResource: "localization", withExtension: "json") ?? source
        do { return try JSONDecoder().decode(Catalog.self, from: Data(contentsOf: url)) }
        catch { preconditionFailure("Cannot load translations: \(error)") }
    }()
    static func uiLanguage(for preferred: [String]) -> String {
        for code in preferred {
            let base = code.replacingOccurrences(of: "_", with: "-").lowercased().split(separator: "-").first.map(String.init) ?? ""
            if base == "zh" { return "zh-Hans" }
            if supported.contains(base) { return base }
        }
        return "en"
    }
    static var preferredLanguages: [String] {
        if let override = ProcessInfo.processInfo.environment["STTS_UI_LANGUAGE"], !override.isEmpty { return [override] }
        if let chosen { return [chosen] }
        return Locale.preferredLanguages
    }
    static let language = uiLanguage(for: preferredLanguages)
    static func text(_ key: String, _ arguments: String...) -> String {
        var result = language == "ko" ? key : catalog.strings[language]?[key] ?? catalog.strings["en"]?[key] ?? key
        for (index, value) in arguments.enumerated() { result = result.replacingOccurrences(of: "{\(index)}", with: value) }
        return result
    }
    static func languageName(_ code: String) -> String {
        catalog.languageNames[language]?[code] ?? catalog.languageNames["en"]?[code] ?? code
    }
    static func speechLanguage(for preferred: [String], supported options: [String]) -> String {
        for requested in preferred + ["en"] {
            let code = requested.replacingOccurrences(of: "_", with: "-").lowercased()
            if let exact = options.first(where: { $0.lowercased() == code }) { return exact }
            let parts = code.split(separator: "-"), base = parts.first.map(String.init) ?? ""
            if base == "zh" {
                let traditional = parts.contains("hant") || parts.contains("tw") || parts.contains("hk") || parts.contains("mo")
                let candidates = traditional ? ["zh-tw", "zh-hant", "zh-hk"] : ["zh-cn", "zh-hans"]
                for candidate in candidates { if let match = options.first(where: { $0.lowercased() == candidate }) { return match } }
            }
            if let generic = options.first(where: { $0.lowercased() == base }) { return generic }
            if let match = options.sorted().first(where: { $0.lowercased().split(separator: "-").first == parts.first }) { return match }
        }
        return options.first ?? "en"
    }
    // Progress and engine errors arrive as strings. Translate only their known
    // message templates; file names, transcripts and other arguments stay intact.
    static func message(_ source: String) -> String {
        if language == "ko" { return source }
        if catalog.strings["en"]?[source] != nil { return text(source) }
        for (key, regex) in messageTemplates {
            let range = NSRange(source.startIndex..., in: source)
            guard let match = regex.firstMatch(in: source, range: range) else { continue }
            var result = text(key)
            for index in 1..<match.numberOfRanges {
                if let range = Range(match.range(at: index), in: source) {
                    result = result.replacingOccurrences(of: "{\(index - 1)}", with: String(source[range]))
                }
            }
            return result
        }
        return source
    }
    private static let messageTemplates: [(String, NSRegularExpression)] = {
        (catalog.strings["en"] ?? [:]).keys.filter { $0.contains("{0}") }.sorted { $0.count > $1.count }.compactMap { key in
            var pattern = NSRegularExpression.escapedPattern(for: key)
            for index in 0..<10 { pattern = pattern.replacingOccurrences(of: NSRegularExpression.escapedPattern(for: "{\(index)}"), with: "(.*?)") }
            guard let regex = try? NSRegularExpression(pattern: "^" + pattern + "$", options: [.dotMatchesLineSeparators]) else { return nil }
            return (key, regex)
        }
    }()
}
