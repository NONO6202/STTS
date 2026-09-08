import Foundation
import CoreAudio
import AVFoundation
import Darwin

/// A public CoreAudio input with a tap restricted to this process's playback.
/// The silent device persists on quit so a client need not fall back to a physical mic.
@MainActor final class VirtualMicrophone {
    static let name = "STTS Microphone"
    private static var savedTapUUID: UUID {
        if let value = UserDefaults.standard.string(forKey: "microphoneTapUUID"), let uuid = UUID(uuidString: value) { return uuid }
        let uuid = UUID(); UserDefaults.standard.set(uuid.uuidString, forKey: "microphoneTapUUID"); return uuid
    }
    let identifier: String
    let tapUUID: UUID
    private(set) var device: AudioObjectID = 0
    private var tap: AudioObjectID = 0
    private var source: AudioObjectID = 0

    init(identifier: String? = nil, tapUUID: UUID? = nil) {
        self.identifier = identifier ?? "local.stts.microphone.\(getuid())"
        self.tapUUID = tapUUID ?? Self.savedTapUUID
    }
    func prepare() throws {
        device = AudioHardware.ids(AudioObjectID(kAudioObjectSystemObject), selector: kAudioHardwarePropertyDevices).first {
            AudioHardware.string($0, selector: kAudioDevicePropertyDeviceUID) == identifier
        } ?? 0
        let defaults: DefaultAudioDevices? = device == 0 ? try DefaultAudioDevices(createdUID: identifier) : nil
        defer { defaults?.finish() }
        var pid = getpid(), size = UInt32(MemoryLayout<AudioObjectID>.size)
        var address = AudioHardware.address(kAudioHardwarePropertyTranslatePIDToProcessObject)
        try check(AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &address, UInt32(MemoryLayout<pid_t>.size), &pid, &size, &source))
        guard source != 0 else { throw AppFailure("음성 출력 준비 후 가상 마이크를 다시 연결해 주세요.") }
        tap = AudioHardware.ids(AudioObjectID(kAudioObjectSystemObject), selector: kAudioHardwarePropertyTapList).first {
            AudioHardware.string($0, selector: kAudioTapPropertyUID) == tapUUID.uuidString
        } ?? 0
        if tap == 0 {
            let description = description(sending: false)
            try check(AudioHardwareCreateProcessTap(description, &tap))
        } else { try setSending(false, requireDevice: false) }
        if device == 0 {
            let composition: [String: Any] = [
                kAudioAggregateDeviceNameKey: Self.name, kAudioAggregateDeviceUIDKey: identifier,
                kAudioAggregateDeviceIsPrivateKey: false,
                kAudioAggregateDeviceTapListKey: [[kAudioSubTapUIDKey: tapUUID.uuidString, kAudioSubTapDriftCompensationKey: true]]
            ]
            try check(AudioHardwareCreateAggregateDevice(composition as CFDictionary, &device))
        } else {
            var list: CFArray = [tapUUID.uuidString] as CFArray
            var property = AudioHardware.address(kAudioAggregateDevicePropertyTapList)
            try check(AudioObjectSetPropertyData(device, &property, 0, nil, UInt32(MemoryLayout<CFArray>.size), &list))
        }
    }
    private func description(sending: Bool, monitoring: Bool = false) -> CATapDescription {
        let value = CATapDescription(monoMixdownOfProcesses: sending ? [source] : [])
        value.uuid = tapUUID; value.name = Self.name; value.isPrivate = false
        value.isExclusive = false; value.isProcessRestoreEnabled = false
        value.muteBehavior = sending && monitoring ? .unmuted : .muted
        return value
    }
    func setSending(_ sending: Bool, monitoring: Bool = false, requireDevice: Bool = true) throws {
        guard tap != 0, AudioHardware.string(tap, selector: kAudioTapPropertyUID) == tapUUID.uuidString,
              !requireDevice || (device != 0 && AudioHardware.string(device, selector: kAudioDevicePropertyDeviceUID) == identifier) else {
            throw AppFailure("가상 마이크가 없습니다. TTS 사용을 껐다 켜 주세요.")
        }
        var value = description(sending: sending, monitoring: monitoring)
        var property = AudioHardware.address(kAudioTapPropertyDescription)
        try check(AudioObjectSetPropertyData(tap, &property, 0, nil, UInt32(MemoryLayout<CATapDescription>.size), &value))
        // Monitoring changes hardware audibility, never the single captured TTS stream.
        var readback: Unmanaged<CFTypeRef>?, size = UInt32(MemoryLayout<Unmanaged<CFTypeRef>?>.size)
        try check(AudioObjectGetPropertyData(tap, &property, 0, nil, &size, &readback))
        guard let actual = readback?.takeRetainedValue() as? CATapDescription,
              actual.muteBehavior == value.muteBehavior, !actual.isExclusive,
              actual.processes == (sending ? [source] : []) else { throw AppFailure("가상 마이크의 송신 경로를 확인하지 못했습니다.") }
    }
    func disconnect() { if tap != 0 { try? setSending(false, requireDevice: false) } }
    func remove() throws {
        device = AudioHardware.ids(AudioObjectID(kAudioObjectSystemObject), selector: kAudioHardwarePropertyDevices).first {
            AudioHardware.string($0, selector: kAudioDevicePropertyDeviceUID) == identifier
        } ?? 0
        tap = AudioHardware.ids(AudioObjectID(kAudioObjectSystemObject), selector: kAudioHardwarePropertyTapList).first {
            AudioHardware.string($0, selector: kAudioTapPropertyUID) == tapUUID.uuidString
        } ?? 0
        disconnect()
        if device != 0, AudioHardware.string(device, selector: kAudioDevicePropertyDeviceUID) == identifier {
            try check(AudioHardwareDestroyAggregateDevice(device)); device = 0
        }
        if tap != 0, AudioHardware.string(tap, selector: kAudioTapPropertyUID) == tapUUID.uuidString {
            try check(AudioHardwareDestroyProcessTap(tap)); tap = 0
        }
    }
    private func check(_ status: OSStatus) throws {
        guard status == noErr else { throw AppFailure("가상 마이크를 준비하지 못했습니다 (\(status)). TTS 사용을 껐다 켜서 다시 시도해 주세요.") }
    }
}
