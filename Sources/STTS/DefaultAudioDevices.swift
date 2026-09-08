import CoreAudio
import Foundation

/// Keeps each role independent and stops owning it after a repair or a user
/// choice. Device UIDs are used because CoreAudio object IDs can be reused.
struct DefaultAudioDeviceRole {
    let original: String
    private(set) var finished = false

    mutating func shouldRestore(current: String, created: String, originalAvailable: Bool) -> Bool {
        guard !finished else { return false }
        guard !original.isEmpty, originalAvailable else { finished = true; return false }
        if current == original || current.isEmpty { return false }
        guard current == created else { finished = true; return false }
        return true
    }

    mutating func restored() { finished = true }
}

/// A short-lived guard around creation of a public virtual device. It never
/// runs for an existing device or while the user normally uses STTS.
@MainActor final class DefaultAudioDevices {
    static let selectors: [AudioObjectPropertySelector] = [
        kAudioHardwarePropertyDefaultInputDevice,
        kAudioHardwarePropertyDefaultOutputDevice,
        kAudioHardwarePropertyDefaultSystemOutputDevice
    ]
    private let createdUID: String
    private var roles: [AudioObjectPropertySelector: DefaultAudioDeviceRole] = [:]
    private var listeners: [(AudioObjectPropertyAddress, AudioObjectPropertyListenerBlock)] = []
    private var stopped = false

    init(createdUID: String) throws {
        self.createdUID = createdUID
        for selector in Self.selectors {
            let device = try Self.defaultDevice(selector)
            let uid = device == 0 ? "" : AudioHardware.string(device, selector: kAudioDevicePropertyDeviceUID)
            guard device == 0 || !uid.isEmpty else { throw AppFailure("기존 기본 오디오 장치를 확인하지 못했습니다.") }
            roles[selector] = DefaultAudioDeviceRole(original: uid)
        }
        for selector in Self.selectors {
            var address = AudioHardware.address(selector)
            let listener: AudioObjectPropertyListenerBlock = { [weak self] _, _ in
                Task { @MainActor [weak self] in self?.restore() }
            }
            let status = AudioObjectAddPropertyListenerBlock(AudioObjectID(kAudioObjectSystemObject), &address, .main, listener)
            guard status == noErr else {
                stop()
                throw AppFailure("기본 오디오 장치 보존을 준비하지 못했습니다 (\(status)).")
            }
            listeners.append((address, listener))
        }
    }

    static func defaultDevice(_ selector: AudioObjectPropertySelector) throws -> AudioObjectID {
        var property = AudioHardware.address(selector), result: AudioObjectID = 0
        var bytes = UInt32(MemoryLayout<AudioObjectID>.size)
        let status = AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &property, 0, nil, &bytes, &result)
        guard status == noErr else { throw AppFailure("기본 오디오 장치를 읽지 못했습니다 (\(status)).") }
        return result
    }

    private func restore() {
        guard !stopped else { return }
        let devices = AudioHardware.ids(AudioObjectID(kAudioObjectSystemObject), selector: kAudioHardwarePropertyDevices)
        for selector in Self.selectors {
            guard var role = roles[selector], !role.finished,
                  let currentID = try? Self.defaultDevice(selector) else { continue }
            let current = currentID == 0 ? "" : AudioHardware.string(currentID, selector: kAudioDevicePropertyDeviceUID)
            let original = devices.first { AudioHardware.string($0, selector: kAudioDevicePropertyDeviceUID) == role.original }
            if role.shouldRestore(current: current, created: createdUID, originalAvailable: original != nil), var target = original {
                var address = AudioHardware.address(selector)
                let status = AudioObjectSetPropertyData(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil,
                    UInt32(MemoryLayout<AudioObjectID>.size), &target)
                if status == noErr, (try? Self.defaultDevice(selector)) == target { role.restored() }
                else { NSLog("STTS: could not restore default audio role %u (%d)", selector, status) }
            }
            roles[selector] = role
        }
    }

    /// Restore synchronously first, then cover delayed CoreAudio notifications.
    /// This task owns the guard until its fixed deadline and removes listeners.
    func finish() {
        restore()
        Task { @MainActor in
            for _ in 0..<10 {
                try? await Task.sleep(for: .milliseconds(200))
                restore()
            }
            stop()
        }
    }

    private func stop() {
        stopped = true
        for (var address, listener) in listeners {
            AudioObjectRemovePropertyListenerBlock(AudioObjectID(kAudioObjectSystemObject), &address, .main, listener)
        }
        listeners.removeAll()
    }
}
