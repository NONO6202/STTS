import Foundation
import CoreAudio
import AVFoundation
import Darwin

/// The existing one-shot smoke command can check the virtual input using a second process.
/// It publishes a unique test device; it never reads a physical microphone or Discord audio.
enum MicrophoneCheck {
    private static func emit(_ object: [String: Any]) throws {
        var data = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]); data.append(10)
        try FileHandle.standardOutput.write(contentsOf: data)
    }
    private static func line(_ fd: Int32) throws -> [String: Any] {
        var result = Data()
        while result.count < 4096 {
            var pollDescriptor = pollfd(fd: fd, events: Int16(POLLIN), revents: 0)
            guard poll(&pollDescriptor, 1, 30_000) > 0 else { throw AppFailure("가상 입력 검사 응답 시간 초과") }
            var byte: UInt8 = 0
            guard Darwin.read(fd, &byte, 1) == 1 else { throw AppFailure("가상 입력 검사 프로세스 종료") }
            if byte == 10 { return try JSONSerialization.jsonObject(with: result) as? [String: Any] ?? [:] }
            result.append(byte)
        }
        throw AppFailure("가상 입력 검사 응답 오류")
    }
    private static func defaultDevice(_ selector: AudioObjectPropertySelector) -> AudioObjectID {
        var address = AudioHardware.address(selector), result: AudioObjectID = 0, size: UInt32 = 4
        AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size, &result)
        return result
    }
    @MainActor static func run() async throws {
        let inputBefore = defaultDevice(kAudioHardwarePropertyDefaultInputDevice)
        let outputBefore = defaultDevice(kAudioHardwarePropertyDefaultOutputDevice)
        let systemOutputBefore = defaultDevice(kAudioHardwarePropertyDefaultSystemOutputDevice)
        let player = AudioPlayback(); player.prepareOutput(); player.setVolume(0.5)
        let mic = VirtualMicrophone(identifier: "local.stts.check.\(UUID().uuidString)", tapUUID: UUID())
        defer { player.stop(); try? mic.remove() }
        try mic.prepare()
        guard defaultDevice(kAudioHardwarePropertyDefaultInputDevice) == inputBefore,
              defaultDevice(kAudioHardwarePropertyDefaultOutputDevice) == outputBefore,
              defaultDevice(kAudioHardwarePropertyDefaultSystemOutputDevice) == systemOutputBefore else { throw AppFailure("가상 입력 생성 후 기본 장치가 달라졌습니다.") }
        try await Task.sleep(for: .milliseconds(2300))
        guard defaultDevice(kAudioHardwarePropertyDefaultInputDevice) == inputBefore,
              defaultDevice(kAudioHardwarePropertyDefaultOutputDevice) == outputBefore,
              defaultDevice(kAudioHardwarePropertyDefaultSystemOutputDevice) == systemOutputBefore else { throw AppFailure("가상 입력 생성 후 기본 장치가 지연 변경되었습니다.") }
        try AppPaths.prepare()
        let audio = AppPaths.temporary.appendingPathComponent(UUID().uuidString + ".wav")
        defer { try? FileManager.default.removeItem(at: audio) }
        let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 48000, channels: 1, interleaved: false)!
        let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 48000)!
        buffer.frameLength = 48000
        for i in 0..<48000 { buffer.floatChannelData![0][i] = 0.1 * sin(2 * .pi * 997 * Float(i) / 48000) }
        do { let file = try AVAudioFile(forWriting: audio, settings: format.settings); try file.write(from: buffer) }
        func capturePlayback(monitoring: Bool = false) async throws -> [String: Any] {
            if monitoring { try mic.setSending(true, monitoring: true) }
            let child = Process(), stdout = Pipe()
            child.executableURL = Bundle.main.executableURL
            child.arguments = ["--microphone-receiver", mic.identifier]
            child.standardOutput = stdout; child.standardError = FileHandle.standardError
            try child.run()
            defer { if child.isRunning { child.terminate() } }
            let fd = stdout.fileHandleForReading.fileDescriptor
            let ready = try await Task.detached { try line(fd) }.value
            guard ready["ready"] as? Bool == true else { throw AppFailure("가상 입력 수신 준비 실패") }
            try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
                do { try player.play(audio, deviceUID: "") { continuation.resume() } }
                catch { continuation.resume(throwing: error) }
            }
            return try await Task.detached { try line(fd) }.value
        }
        try mic.setSending(true)
        let result = try await capturePlayback()
        guard let peak = result["peak"] as? Double, peak > 0.005, peak < 0.08,
              let frames = result["samples"] as? Int, frames > 1000 else {
            throw AppFailure("가상 입력의 오디오 신호를 확인하지 못했습니다. STTS의 시스템 오디오 녹음 권한을 확인해 주세요.")
        }
        let repeated = try await capturePlayback()
        let monitored = try await capturePlayback(monitoring: true)
        guard let monitoredPeak = monitored["peak"] as? Double,
              let repeatedPeak = repeated["peak"] as? Double,
              monitoredPeak > 0.005, abs(monitoredPeak - repeatedPeak) < 0.001 else {
            throw AppFailure("모니터링 가상 입력 검사 실패: 최초=\(peak), 반복=\(repeated), 모니터링=\(monitored)")
        }
        // Keep the verification tone inaudible while testing the preview exclusion separately.
        var pid = getpid(), source: AudioObjectID = 0, sourceSize: UInt32 = 4
        var sourceAddress = AudioHardware.address(kAudioHardwarePropertyTranslatePIDToProcessObject)
        guard AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &sourceAddress, 4, &pid, &sourceSize, &source) == noErr, source != 0 else { throw AppFailure("검사 출력 프로세스 없음") }
        let guardDescription = CATapDescription(monoMixdownOfProcesses: [source])
        guardDescription.isPrivate = true; guardDescription.muteBehavior = .muted
        var guardTap: AudioObjectID = 0
        guard AudioHardwareCreateProcessTap(guardDescription, &guardTap) == noErr else { throw AppFailure("검사 무음 보호 준비 실패") }
        defer { AudioHardwareDestroyProcessTap(guardTap) }
        try mic.setSending(false)
        let preview = try await capturePlayback()
        guard let previewPeak = preview["peak"] as? Double, previewPeak < 0.00001 else { throw AppFailure("미리 듣기 음성이 가상 입력으로 전달되었습니다.") }
        let reopened = VirtualMicrophone(identifier: mic.identifier, tapUUID: mic.tapUUID)
        try reopened.remove()
        guard !AudioHardware.ids(AudioObjectID(kAudioObjectSystemObject), selector: kAudioHardwarePropertyDevices).contains(where: {
            AudioHardware.string($0, selector: kAudioDevicePropertyDeviceUID) == mic.identifier
        }), !AudioHardware.ids(AudioObjectID(kAudioObjectSystemObject), selector: kAudioHardwarePropertyTapList).contains(where: {
            AudioHardware.string($0, selector: kAudioTapPropertyUID) == mic.tapUUID.uuidString
        }) else { throw AppFailure("이전 가상 입력 장치를 제거하지 못했습니다.") }
        try emit(["microphone": "CoreAudio public tap", "separateProcessInput": true,
                  "muteConfigurationVerified": true, "monitoringConfigurationVerified": true,
                  "repeatedPeak": repeatedPeak, "monitoringPeak": monitoredPeak, "previewExcluded": true, "previewPeak": previewPeak, "defaultDevicesUnchanged": true, "removedByNewInstance": true, "peak": peak, "samples": frames])
    }
    static func receive(identifier: String) throws {
        guard identifier.hasPrefix("local.stts.check."),
              let device = AudioHardware.ids(AudioObjectID(kAudioObjectSystemObject), selector: kAudioHardwarePropertyDevices).first(where: {
                  AudioHardware.string($0, selector: kAudioDevicePropertyDeviceUID) == identifier
              }) else { throw AppFailure("검사용 가상 입력 장치 없음") }
        var format = AudioStreamBasicDescription(), size = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
        var address = AudioHardware.address(kAudioDevicePropertyStreamFormat, scope: kAudioDevicePropertyScopeInput)
        guard AudioObjectGetPropertyData(device, &address, 0, nil, &size, &format) == noErr,
              format.mFormatID == kAudioFormatLinearPCM, format.mFormatFlags & kAudioFormatFlagIsFloat != 0,
              format.mBitsPerChannel == 32 else { throw AppFailure("검사용 입력 형식 오류") }
        final class Meter: @unchecked Sendable { var peak: Float = 0; var samples = 0 }
        let meter = Meter(), queue = DispatchQueue(label: "local.stts.check.meter")
        var proc: AudioDeviceIOProcID?
        guard AudioDeviceCreateIOProcIDWithBlock(&proc, device, queue, { _, input, _, _, _ in
            for buffer in UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: input)) {
                guard let data = buffer.mData else { continue }
                let samples = UnsafeBufferPointer(start: data.assumingMemoryBound(to: Float.self), count: Int(buffer.mDataByteSize) / 4)
                for value in samples { meter.peak = max(meter.peak, abs(value)) }
                meter.samples += samples.count
            }
        }) == noErr, let proc else { throw AppFailure("검사용 입력 생성 오류") }
        defer { AudioDeviceStop(device, proc); AudioDeviceDestroyIOProcID(device, proc) }
        guard AudioDeviceStart(device, proc) == noErr else { throw AppFailure("검사용 입력 시작 오류") }
        try emit(["ready": true])
        Thread.sleep(forTimeInterval: 3)
        let result = queue.sync { ["peak": Double(meter.peak), "samples": meter.samples] as [String: Any] }
        try emit(result)
    }
}
