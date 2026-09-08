import Testing
@testable import STTS

struct DefaultAudioDevicesTests {
    @Test func restoresOnlyTheCreatedDeviceAndOnlyOnce() {
        var role = DefaultAudioDeviceRole(original: "headset")
        #expect(!role.shouldRestore(current: "headset", created: "STTS", originalAvailable: true))
        #expect(role.shouldRestore(current: "STTS", created: "STTS", originalAvailable: true))
        role.restored()
        #expect(!role.shouldRestore(current: "STTS", created: "STTS", originalAvailable: true))
    }

    @Test func respectsAnotherDeviceChoiceAndDisconnection() {
        var role = DefaultAudioDeviceRole(original: "headset")
        #expect(!role.shouldRestore(current: "speakers", created: "STTS", originalAvailable: true))
        #expect(!role.shouldRestore(current: "STTS", created: "STTS", originalAvailable: true))
        var disconnected = DefaultAudioDeviceRole(original: "headset")
        #expect(!disconnected.shouldRestore(current: "STTS", created: "STTS", originalAvailable: false))
        #expect(!disconnected.shouldRestore(current: "STTS", created: "STTS", originalAvailable: true))
    }

    @Test func preservesMissingAndAlreadySelectedDefaults() {
        var missing = DefaultAudioDeviceRole(original: "")
        #expect(!missing.shouldRestore(current: "STTS", created: "STTS", originalAvailable: false))
        var selected = DefaultAudioDeviceRole(original: "STTS")
        #expect(!selected.shouldRestore(current: "STTS", created: "STTS", originalAvailable: true))
    }

    @Test func inputOutputAndSystemOutputRemainIndependent() {
        var input = DefaultAudioDeviceRole(original: "microphone")
        var output = DefaultAudioDeviceRole(original: "headset")
        var alerts = DefaultAudioDeviceRole(original: "speakers")
        #expect(input.shouldRestore(current: "STTS", created: "STTS", originalAvailable: true))
        #expect(!output.shouldRestore(current: "headset", created: "STTS", originalAvailable: true))
        #expect(alerts.shouldRestore(current: "STTS", created: "STTS", originalAvailable: true))
        input.restored()
        #expect(alerts.shouldRestore(current: "STTS", created: "STTS", originalAvailable: true))
    }
}
