import AVFoundation
import CoreMedia

protocol LiveMicrophoneCapture {
    var healthy: Bool { get }
    func start(deviceUID: String, volume: Double) throws
    func stop()
    func setVolume(_ value: Double)
    func setEffects(pitch: Double, filter: String, strength: Double)
}

/// Playback stays inside STTS's muted process tap. Nothing is recorded to disk.
final class MicrophonePassthrough: NSObject, LiveMicrophoneCapture, AVCaptureAudioDataOutputSampleBufferDelegate {
    private let queue = DispatchQueue(label: "local.stts.microphone", qos: .userInitiated)
    private let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 48000, channels: 1, interleaved: false)!
    private var session: AVCaptureSession?
    private var device: AVCaptureDevice?
    private var engine: AVAudioEngine?
    private var buffer: MicrophoneBuffer?
    private var converter: AVAudioConverter?
    private var failed = false
    private let effects = MicrophoneEffects()

    var healthy: Bool {
        queue.sync {
            session?.isRunning == true && device?.isConnected == true && engine?.isRunning == true
                && !failed && buffer?.processingHealthy() == true
        }
    }
    func setVolume(_ value: Double) {
        queue.sync { engine?.mainMixerNode.outputVolume = Float(value.isFinite ? min(1, max(0, value)) : 0) }
    }
    func setEffects(pitch: Double, filter: String, strength: Double) {
        queue.sync { effects.pitch = pitch; effects.filter = filter; effects.strength = strength }
    }
    static func sourceNode(buffer: MicrophoneBuffer, format: AVAudioFormat) -> AVAudioSourceNode {
        AVAudioSourceNode(format: format) { isSilence, _, frames, audio in
            let buffers = UnsafeMutableAudioBufferListPointer(audio)
            guard let first = buffers.first?.mData?.assumingMemoryBound(to: Float.self) else { return noErr }
            buffer.render(first, count: Int(frames))
            for other in buffers.dropFirst() {
                other.mData?.assumingMemoryBound(to: Float.self).update(from: first, count: Int(frames))
            }
            isSilence.pointee = false
            return noErr
        }
    }
    func start(deviceUID: String, volume: Double) throws {
        stop()
        guard AVCaptureDevice.authorizationStatus(for: .audio) == .authorized else {
            throw AppFailure("시스템 설정에서 STTS의 마이크 접근을 허용해 주세요.")
        }
        guard AudioHardware.physicalInputs().contains(where: { $0.uid == deviceUID }),
              let device = AVCaptureDevice(uniqueID: deviceUID), device.isConnected else {
            throw AppFailure("선택한 실제 마이크를 찾지 못했습니다. 장치를 확인하고 다시 선택해 주세요.")
        }
        do {
            try queue.sync {
                let session = AVCaptureSession(), input = try AVCaptureDeviceInput(device: device)
                let output = AVCaptureAudioDataOutput()
                output.audioSettings = format.settings
                output.setSampleBufferDelegate(self, queue: queue)
                guard session.canAddInput(input), session.canAddOutput(output) else { throw AppFailure("선택한 마이크를 사용할 수 없습니다.") }
                session.addInput(input); session.addOutput(output)
                let engine = AVAudioEngine(), buffer = MicrophoneBuffer()
                let source = Self.sourceNode(buffer: buffer, format: format)
                engine.attach(source); engine.connect(source, to: engine.mainMixerNode, format: format)
                self.session = session; self.device = device; self.engine = engine; self.buffer = buffer
                engine.mainMixerNode.outputVolume = Float(volume.isFinite ? min(1, max(0, volume)) : 0)
                try engine.start(); session.startRunning()
                guard session.isRunning else { throw AppFailure("마이크 입력을 시작하지 못했습니다.") }
            }
        } catch { stop(); throw error }
    }
    func stop() {
        queue.sync {
            session?.stopRunning(); session = nil; device = nil
            engine?.stop(); engine = nil; buffer = nil
            converter = nil
            failed = false
            effects.reset()
        }
    }
    func convert(_ input: AVAudioPCMBuffer) throws -> AVAudioPCMBuffer {
        if input.format == format { converter = nil; return input }
        if converter?.inputFormat != input.format { converter = AVAudioConverter(from: input.format, to: format) }
        let capacity = AVAudioFrameCount(ceil(Double(input.frameLength) * format.sampleRate / input.format.sampleRate)) + 32
        guard let converter, let output = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: capacity) else {
            throw AppFailure("선택한 마이크를 사용할 수 없습니다.")
        }
        var supplied = false, error: NSError?
        let result = converter.convert(to: output, error: &error) { _, status in
            if supplied { status.pointee = .noDataNow; return nil }
            supplied = true; status.pointee = .haveData; return input
        }
        if let error { throw error }
        guard result != .error else { throw AppFailure("선택한 마이크를 사용할 수 없습니다.") }
        return output
    }
    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
        guard let destination = buffer, !failed, let description = CMSampleBufferGetFormatDescription(sampleBuffer) else { return }
        let actual = AVAudioFormat(cmAudioFormatDescription: description)
        let frames = CMSampleBufferGetNumSamples(sampleBuffer)
        guard frames > 0 else { return }
        guard let buffer = AVAudioPCMBuffer(pcmFormat: actual, frameCapacity: AVAudioFrameCount(frames)) else { failed = true; return }
        buffer.frameLength = AVAudioFrameCount(frames)
        guard CMSampleBufferCopyPCMDataIntoAudioBufferList(sampleBuffer, at: 0, frameCount: Int32(frames), into: buffer.mutableAudioBufferList) == noErr else {
            failed = true; return
        }
        do {
            let converted = try convert(buffer)
            if let samples = converted.floatChannelData?[0] {
                let count = Int(converted.frameLength)
                effects.process(samples, count: count)
                destination.append(samples, count: count)
            }
        } catch { failed = true }
    }
}
