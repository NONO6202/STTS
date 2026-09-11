import AppKit
import SwiftUI
import Carbon

enum Preferences {
    static func read<T: Decodable>(_ key: String, fallback: T) -> T {
        guard let data = UserDefaults.standard.data(forKey: key), let value = try? JSONDecoder().decode(T.self, from: data) else { return fallback }
        return value
    }
    static func save<T: Encodable>(_ value: T, key: String) { UserDefaults.standard.set(try? JSONEncoder().encode(value), forKey: key) }
}

struct TTSPhrases: Codable, Equatable {
    private(set) var entries: [String: String] = [:]

    mutating func save(shortcut: String, phrase: String, replacing original: String? = nil, soundNames: [String] = []) throws {
        let shortcut = shortcut.trimmingCharacters(in: .whitespacesAndNewlines)
        let phrase = phrase.trimmingCharacters(in: .whitespacesAndNewlines)
        guard (1...AppContract.shared.limits.text).contains(shortcut.count), (1...AppContract.shared.limits.text).contains(phrase.count) else {
            throw AppFailure("단축어와 읽을 문장은 각각 1~500자로 입력해 주세요.")
        }
        guard shortcut == original || entries[shortcut] == nil else {
            throw AppFailure("이미 저장된 단축어입니다. 기존 항목을 수정해 주세요.")
        }
        guard !soundNames.contains(where: { $0.trimmingCharacters(in: .whitespacesAndNewlines) == shortcut }) else {
            throw AppFailure("같은 이름의 사운드가 있습니다. 다른 단축어를 입력해 주세요.")
        }
        if let original { entries.removeValue(forKey: original) }
        entries[shortcut] = phrase
    }

    mutating func remove(_ shortcut: String) { entries.removeValue(forKey: shortcut) }

    func expand(_ input: String) -> String {
        let input = input.trimmingCharacters(in: .whitespacesAndNewlines)
        return entries[input] ?? input
    }
}

struct Tint: Codable, Equatable {
    var red: Double; var green: Double; var blue: Double
    var color: Color { Color(red: red, green: green, blue: blue) }
    init(_ color: Color) {
        let rgb = NSColor(color).usingColorSpace(.sRGB) ?? .white
        red = rgb.redComponent; green = rgb.greenComponent; blue = rgb.blueComponent
    }
    init(hex: String) {
        let value = UInt32(hex.dropFirst(), radix: 16) ?? 0
        red = Double((value >> 16) & 255) / 255
        green = Double((value >> 8) & 255) / 255
        blue = Double(value & 255) / 255
    }
    init(_ red: Double, _ green: Double, _ blue: Double) { self.red = red; self.green = green; self.blue = blue }
}

struct SurfaceStyle: Codable, Equatable {
    var background: Tint
    var foreground: Tint
    var opacity: Double
    static let window = SurfaceStyle(background: Tint(hex: AppContract.shared.defaults.windowBg), foreground: Tint(hex: AppContract.shared.defaults.windowColor), opacity: AppContract.shared.defaults.windowAlpha)
    static let captions = SurfaceStyle(background: Tint(hex: AppContract.shared.defaults.captionBg), foreground: Tint(hex: AppContract.shared.defaults.captionColor), opacity: AppContract.shared.defaults.captionAlpha)
}

struct Shortcut: Codable, Equatable {
    let keyCode: UInt32
    let modifiers: UInt
    let key: String
    static let initial = Shortcut(keyCode: UInt32(kVK_Space), modifiers: NSEvent.ModifierFlags([.control, .option]).rawValue, key: " ")
    static let captionInitial = Shortcut(keyCode: UInt32(kVK_ANSI_S), modifiers: NSEvent.ModifierFlags([.control, .option]).rawValue, key: "s")
    var flags: NSEvent.ModifierFlags { NSEvent.ModifierFlags(rawValue: modifiers) }
    var valid: Bool {
        let functionKeys: Set<UInt32> = [122,120,99,118,96,97,98,100,101,109,103,111,105,107,113,106,64,79,80,90]
        return !flags.intersection([.command, .control, .option]).isEmpty || functionKeys.contains(keyCode)
    }
    var carbonModifiers: UInt32 {
        var value: UInt32 = 0
        if flags.contains(.control) { value |= UInt32(controlKey) }
        if flags.contains(.option) { value |= UInt32(optionKey) }
        if flags.contains(.shift) { value |= UInt32(shiftKey) }
        if flags.contains(.command) { value |= UInt32(cmdKey) }
        return value
    }
    var label: String {
        let names: [UInt32: String] = [49:"Space",36:"Enter",48:"Tab",53:"Esc",51:"Delete",123:"←",124:"→",125:"↓",126:"↑",122:"F1",120:"F2",99:"F3",118:"F4",96:"F5",97:"F6",98:"F7",100:"F8",101:"F9",109:"F10",103:"F11",111:"F12",105:"F13",107:"F14",113:"F15",106:"F16",64:"F17",79:"F18",80:"F19",90:"F20"]
        return (flags.contains(.control) ? "⌃" : "") + (flags.contains(.option) ? "⌥" : "") + (flags.contains(.shift) ? "⇧" : "") + (flags.contains(.command) ? "⌘" : "") + (names[keyCode] ?? key.uppercased())
    }
}

enum STTModel: String, CaseIterable, Identifiable, Codable {
    case automatic, base, small, turbo, large, asr06, asr17, nemotron
    var id: String { rawValue }
    func resolved(_ level: ResourceLevel) -> STTModel {
        guard self == .automatic else { return self }
        switch level.resolved {
        case .minimum, .low: return .small
        case .high, .maximum: return .large
        default: return .turbo
        }
    }
}

enum TTSModel: String, CaseIterable, Identifiable, Codable {
    case gtts, localAuto, supertonic3, qwen06, qwen17, chatterV3, vox
    var id: String { rawValue }
    func resolved(_ level: ResourceLevel) -> TTSModel {
        guard self == .localAuto else { return self }
        switch level.resolved {
        case .minimum: return .gtts
        case .low: return .supertonic3
        case .high, .maximum: return .qwen17
        default: return .qwen06
        }
    }
}

enum SpeechLanguages {
    static let catalog: [String: [String: String]] = {
        let url = Bundle.main.url(forResource: "speech_languages", withExtension: "json")
            ?? URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("Support/speech_languages.json")
        guard let data = try? Data(contentsOf: url), let value = try? JSONDecoder().decode([String: [String: String]].self, from: data) else { return [:] }
        return value
    }()
    static func tts(_ model: TTSModel) -> [String] {
        let key = model == .gtts ? "gtts" : (model == .supertonic3 ? "supertonic3" : (model == .chatterV3 ? "chatter" : (model == .vox ? "vox" : "qwenTTS")))
        return Array(catalog[key, default: [:]].keys)
    }
    static func stt(_ model: STTModel) -> [String] {
        let key = model == .nemotron ? "nemotron" : ([.asr06, .asr17].contains(model) ? "qwenASR" : "whisper")
        let codes = Array(catalog[key, default: [:]].keys)
        return ["auto"] + codes.filter { $0 != "yue" || ![.base, .small].contains(model) }
    }
    static func label(_ code: String) -> String {
        if code == "auto" { return "자동 감지" }
        return (AppContract.shared.languageLabels[code] ?? code) + " · " + code
    }
    static func sorted(_ codes: [String]) -> [String] {
        let known = AppContract.shared.languageOrder.filter { codes.contains($0) }
        return (codes.contains("auto") ? ["auto"] : []) + known
            + codes.filter { $0 != "auto" && !known.contains($0) }.sorted()
    }
    static func matching(_ code: String, in options: [String], fallback: String) -> String {
        if options.contains(code) { return code }
        let base = code.split(separator: "-")[0]
        return options.first { $0.split(separator: "-")[0] == base } ?? fallback
    }
}
