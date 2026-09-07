import AppKit
import AVFoundation
import CoreAudio

struct OutputDevice: Identifiable, Equatable {
    let id: AudioDeviceID
    let uid: String
    let name: String
    let isVirtual: Bool
}

enum AudioHardware {
    static func address(_ selector: AudioObjectPropertySelector, scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal) -> AudioObjectPropertyAddress {
        AudioObjectPropertyAddress(mSelector: selector, mScope: scope, mElement: kAudioObjectPropertyElementMain)
    }
    static func ids(_ object: AudioObjectID, selector: AudioObjectPropertySelector) -> [AudioObjectID] {
        var property = address(selector), size: UInt32 = 0
        guard AudioObjectGetPropertyDataSize(object, &property, 0, nil, &size) == noErr else { return [] }
        var result = [AudioObjectID](repeating: 0, count: Int(size) / MemoryLayout<AudioObjectID>.size)
        guard AudioObjectGetPropertyData(object, &property, 0, nil, &size, &result) == noErr else { return [] }
        return result
    }
    static func string(_ object: AudioObjectID, selector: AudioObjectPropertySelector) -> String {
        var property = address(selector), size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
        var result: Unmanaged<CFString>?
        guard AudioObjectGetPropertyData(object, &property, 0, nil, &size, &result) == noErr else { return "" }
        return result?.takeRetainedValue() as String? ?? ""
    }
    static func outputs() -> [OutputDevice] {
        ids(AudioObjectID(kAudioObjectSystemObject), selector: kAudioHardwarePropertyDevices).compactMap { id in
            var prop = address(kAudioDevicePropertyStreamConfiguration, scope: kAudioDevicePropertyScopeOutput), bytes: UInt32 = 0
            guard AudioObjectGetPropertyDataSize(id, &prop, 0, nil, &bytes) == noErr, bytes > 0 else { return nil }
            let data = UnsafeMutableRawPointer.allocate(byteCount: Int(bytes), alignment: MemoryLayout<AudioBufferList>.alignment)
            defer { data.deallocate() }
            guard AudioObjectGetPropertyData(id, &prop, 0, nil, &bytes, data) == noErr else { return nil }
            let buffers = UnsafeMutableAudioBufferListPointer(data.assumingMemoryBound(to: AudioBufferList.self))
            guard buffers.contains(where: { $0.mNumberChannels > 0 }) else { return nil }
            var transport: UInt32 = 0, size = UInt32(MemoryLayout<UInt32>.size)
            var transportProperty = address(kAudioDevicePropertyTransportType)
            AudioObjectGetPropertyData(id, &transportProperty, 0, nil, &size, &transport)
            return OutputDevice(id: id, uid: string(id, selector: kAudioDevicePropertyDeviceUID), name: string(id, selector: kAudioObjectPropertyName), isVirtual: transport == kAudioDeviceTransportTypeVirtual)
        }
    }
    static func discordProcesses() -> [AudioObjectID] {
        ids(AudioObjectID(kAudioObjectSystemObject), selector: kAudioHardwarePropertyProcessObjectList).filter { id in
            let bundle = string(id, selector: kAudioProcessPropertyBundleID).lowercased()
            return bundle == "com.hnc.discord" || bundle.hasPrefix("com.hnc.discord.") || bundle == "com.hnc.discordcanary" || bundle.hasPrefix("com.hnc.discordcanary.") || bundle == "com.hnc.discordptb" || bundle.hasPrefix("com.hnc.discordptb.")
        }
    }
}

/// Private, unmuted process tap: never changes the system or Discord output device.
final class DiscordCapture {
    private var tap: AudioObjectID = 0
    private var aggregate: AudioObjectID = 0
    private var proc: AudioDeviceIOProcID?
    private let queue = DispatchQueue(label: "local.stts.capture", qos: .userInitiated)
    private var converter: AVAudioConverter?
    private var inputFormat: AVAudioFormat?
    private let target = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 16000, channels: 1, interleaved: false)!
    private var active = false

    func start(receive: @escaping @Sendable ([Float]) -> Void) throws {
        stop()
        let processes = AudioHardware.discordProcesses()
        guard !processes.isEmpty else { throw AppFailure("Discord를 실행하고 음성 통화에 들어간 뒤 자막을 시작해 주세요.") }
        let description = CATapDescription(monoMixdownOfProcesses: processes)
        description.name = "STTS Discord 수신"
        description.isPrivate = true
        description.muteBehavior = .unmuted
        if #available(macOS 26.0, *) { description.isProcessRestoreEnabled = true }
        do {
            try check(AudioHardwareCreateProcessTap(description, &tap), "Discord 소리 접근")
            var format = AudioStreamBasicDescription()
            var prop = AudioHardware.address(kAudioTapPropertyFormat), size = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
            try check(AudioObjectGetPropertyData(tap, &prop, 0, nil, &size, &format), "오디오 형식 확인")
            guard let input = AVAudioFormat(streamDescription: &format), let converter = AVAudioConverter(from: input, to: target) else { throw AppFailure("Discord의 오디오 형식을 변환할 수 없습니다.") }
            queue.sync { self.inputFormat = input; self.converter = converter; self.active = true }
            let specification: [String: Any] = [
                kAudioAggregateDeviceNameKey: "STTS Private Capture",
                kAudioAggregateDeviceUIDKey: "local.stts.capture.\(UUID().uuidString)",
                kAudioAggregateDeviceIsPrivateKey: true,
                kAudioAggregateDeviceTapAutoStartKey: true,
                kAudioAggregateDeviceTapListKey: [[kAudioSubTapUIDKey: description.uuid.uuidString, kAudioSubTapDriftCompensationKey: true]]
            ]
            try check(AudioHardwareCreateAggregateDevice(specification as CFDictionary, &aggregate), "수신 장치 준비")
            try check(AudioDeviceCreateIOProcIDWithBlock(&proc, aggregate, queue) { [weak self] _, input, _, _, _ in
                guard let self, self.active else { return }
                self.convert(input, receive: receive)
            }, "수신 처리 준비")
            try check(AudioDeviceStart(aggregate, proc), "소리 수신 시작")
        } catch { stop(); throw error }
    }
    func stop() {
        if aggregate != 0, let proc { AudioDeviceStop(aggregate, proc); AudioDeviceDestroyIOProcID(aggregate, proc) }
        queue.sync { active = false; converter = nil; inputFormat = nil }
        proc = nil
        if aggregate != 0 { AudioHardwareDestroyAggregateDevice(aggregate); aggregate = 0 }
        if tap != 0 { AudioHardwareDestroyProcessTap(tap); tap = 0 }
    }
    private func check(_ status: OSStatus, _ operation: String) throws {
        guard status == noErr else { throw AppFailure("\(operation)에 실패했습니다 (\(status)). 시스템 설정에서 STTS의 시스템 오디오 녹음 권한을 확인해 주세요.") }
    }
    private func convert(_ list: UnsafePointer<AudioBufferList>, receive: ([Float]) -> Void) {
        guard let inputFormat, let converter else { return }
        let buffers = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: list))
        guard let first = buffers.first, first.mDataByteSize > 0 else { return }
        let bytesPerFrame = inputFormat.streamDescription.pointee.mBytesPerFrame
        guard bytesPerFrame > 0 else { return }
        let frames = AVAudioFrameCount(first.mDataByteSize) / bytesPerFrame
        guard frames > 0, let input = AVAudioPCMBuffer(pcmFormat: inputFormat, frameCapacity: frames) else { return }
        input.frameLength = frames
        let destinations = UnsafeMutableAudioBufferListPointer(input.mutableAudioBufferList)
        for i in 0..<min(buffers.count, destinations.count) {
            if let source = buffers[i].mData, let destination = destinations[i].mData { memcpy(destination, source, min(Int(buffers[i].mDataByteSize), Int(destinations[i].mDataByteSize))) }
        }
        let capacity = AVAudioFrameCount(ceil(Double(frames) * 16000 / inputFormat.sampleRate)) + 32
        guard let output = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: capacity) else { return }
        var supplied = false, error: NSError?
        converter.convert(to: output, error: &error) { _, status in
            if supplied { status.pointee = .noDataNow; return nil }
            supplied = true; status.pointee = .haveData; return input
        }
        if error == nil, output.frameLength > 0, let data = output.floatChannelData?[0] { receive(Array(UnsafeBufferPointer(start: data, count: Int(output.frameLength)))) }
    }
    deinit { stop() }
}

enum AudioFiles {
    static func samples(_ url: URL) throws -> [Float] {
        let file = try AVAudioFile(forReading: url)
        guard file.length <= Int64(file.processingFormat.sampleRate * 60), file.length > 0 else { throw AppFailure("검증 음성은 1분 이하의 파일을 사용해 주세요.") }
        guard let input = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: AVAudioFrameCount(file.length)) else { throw AppFailure("음성 파일 메모리 준비 실패") }
        try file.read(into: input)
        let target = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 16000, channels: 1, interleaved: false)!
        guard let converter = AVAudioConverter(from: input.format, to: target), let output = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: AVAudioFrameCount(ceil(Double(input.frameLength) * 16000 / input.format.sampleRate)) + 512) else { throw AppFailure("음성 파일 변환 실패") }
        var supplied = false, error: NSError?
        converter.convert(to: output, error: &error) { _, status in
            if supplied { status.pointee = .endOfStream; return nil }
            supplied = true; status.pointee = .haveData; return input
        }
        if let error { throw error }
        return Array(UnsafeBufferPointer(start: output.floatChannelData![0], count: Int(output.frameLength)))
    }
}

@MainActor final class AudioPlayback {
    private let engine = AVAudioEngine()
    func prepareOutput() { _ = engine.outputNode }
    private let player = AVAudioPlayerNode()
    private var completion: (() -> Void)?
    private var generation = UUID()
    private var volume: Float = 1
    init() { engine.attach(player) }
    func setVolume(_ value: Double) { volume = Float(min(1, max(0, value))); player.volume = volume }
    func play(_ url: URL, deviceUID: String, finished: @escaping () -> Void) throws {
        stop()
        do {
            guard let unit = engine.outputNode.audioUnit else { throw AppFailure("오디오 출력을 준비할 수 없습니다.") }
            var id: AudioDeviceID = 0
            if deviceUID.isEmpty {
                var property = AudioHardware.address(kAudioHardwarePropertyDefaultOutputDevice), size = UInt32(MemoryLayout<AudioDeviceID>.size)
                guard AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &property, 0, nil, &size, &id) == noErr else { throw AppFailure("기본 출력 장치를 찾을 수 없습니다.") }
            } else {
                guard let device = AudioHardware.outputs().first(where: { $0.uid == deviceUID }) else { throw AppFailure("선택한 출력 장치를 찾을 수 없습니다. 장치를 다시 선택해 주세요.") }
                id = device.id
            }
            guard AudioUnitSetProperty(unit, kAudioOutputUnitProperty_CurrentDevice, kAudioUnitScope_Global, 0, &id, UInt32(MemoryLayout<AudioDeviceID>.size)) == noErr else { throw AppFailure("선택한 장치로 음성을 보낼 수 없습니다.") }
        }
        let file = try AVAudioFile(forReading: url)
        engine.connect(player, to: engine.mainMixerNode, format: file.processingFormat)
        player.volume = volume
        completion = finished
        let token = generation
        player.scheduleFile(file, at: nil, completionCallbackType: .dataPlayedBack) { [weak self] _ in
            Task { @MainActor in if self?.generation == token { self?.stop() } }
        }
        try engine.start(); player.play()
    }
    func stop() {
        generation = UUID()
        let finished = completion; completion = nil
        player.stop(); engine.stop(); engine.reset()
        finished?()
    }
}
