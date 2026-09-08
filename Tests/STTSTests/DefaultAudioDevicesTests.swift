import Testing
@testable import STTS

struct DefaultAudioDevicesTests {
    @Test func restoresOnlyTheCreatedDeviceAndOnlyOnce() {
        var role = DefaultAudioDeviceRole(original: "headset")
        #expect(role.shouldRestore(current: "headset", created: "STTS", originalAvailable: true) == false)
        #expect(role.shouldRestore(current: "STTS", created: "STTS", originalAvailable: true) == true)
        role.restored()
        #expect(role.shouldRestore(current: "STTS", created: "STTS", originalAvailable: true) == false)
    }

    @Test func respectsAnotherDeviceChoiceAndDisconnection() {
        var role = DefaultAudioDeviceRole(original: "headset")
        #expect(role.shouldRestore(current: "speakers", created: "STTS", originalAvailable: true) == false)
        #expect(role.shouldRestore(current: "STTS", created: "STTS", originalAvailable: true) == false)
        var disconnected = DefaultAudioDeviceRole(original: "headset")
        #expect(disconnected.shouldRestore(current: "STTS", created: "STTS", originalAvailable: false) == false)
        #expect(disconnected.shouldRestore(current: "STTS", created: "STTS", originalAvailable: true) == false)
    }

    @Test func preservesMissingAndAlreadySelectedDefaults() {
        var missing = DefaultAudioDeviceRole(original: "")
        #expect(missing.shouldRestore(current: "STTS", created: "STTS", originalAvailable: false) == false)
        var selected = DefaultAudioDeviceRole(original: "STTS")
        #expect(selected.shouldRestore(current: "STTS", created: "STTS", originalAvailable: true) == false)
    }

    @Test func inputOutputAndSystemOutputRemainIndependent() {
        var input = DefaultAudioDeviceRole(original: "microphone")
        var output = DefaultAudioDeviceRole(original: "headset")
        var alerts = DefaultAudioDeviceRole(original: "speakers")
        #expect(input.shouldRestore(current: "STTS", created: "STTS", originalAvailable: true) == true)
        #expect(output.shouldRestore(current: "headset", created: "STTS", originalAvailable: true) == false)
        #expect(alerts.shouldRestore(current: "STTS", created: "STTS", originalAvailable: true) == true)
        input.restored()
        #expect(alerts.shouldRestore(current: "STTS", created: "STTS", originalAvailable: true) == true)
    }
}
