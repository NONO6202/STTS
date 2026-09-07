"""Checks only the shared VB-CABLE endpoints, never a physical microphone."""
import time
import threading


def cable_levels(repair=False):
    import comtypes
    from pycaw.pycaw import AudioUtilities
    comtypes.CoInitialize()
    try:
        found = {}
        for device in AudioUtilities.GetAllDevices(device_state=1):
            name = ''.join(device.FriendlyName.casefold().split())
            if not ('vb-audiovirtualcable' in name or name.startswith(('cableinput(', 'cableoutput('))):
                continue
            role = 'playback' if device.id.startswith('{0.0.0.') else 'capture' if device.id.startswith('{0.0.1.') else None
            if role is None: continue
            level = device.EndpointVolume
            if repair:
                level.SetMute(False, None)
                level.SetMasterVolumeLevelScalar(1., None)
                for channel in range(level.GetChannelCount()): level.SetChannelVolumeLevelScalar(channel, 1., None)
            found[role] = {'name': device.FriendlyName, 'mute': bool(level.GetMute()),
                           'volume': level.GetMasterVolumeLevelScalar(),
                           'channels': [level.GetChannelVolumeLevelScalar(i) for i in range(level.GetChannelCount())]}
        return found
    finally:
        comtypes.CoUninitialize()


def inspect(repair=False):
    levels = cable_levels(repair)
    problems = []
    for key, name in [('playback', 'CABLE Input'), ('capture', 'CABLE Output')]:
        value = levels.get(key)
        if value is None: problems.append(name + ' 장치가 없거나 사용 중지 상태입니다.')
        elif value['mute'] or value['volume'] <= .001 or max(value['channels'], default=0) <= .001:
            problems.append(name + '이 음소거 또는 0% 음량입니다. 케이블 음량 복구를 누르세요.')
    return {'ok': not problems, 'levels': levels, 'message': '\n'.join(problems) or '케이블 장치와 음량이 정상입니다. 신호 테스트로 수신까지 확인하세요.'}


def signal_test():
    import numpy as np
    from audio import cable_output, play_cable, sd
    result = inspect()
    if not result['ok']: return result
    cable_output(refresh=True)
    devices, apis = sd.query_devices(), sd.query_hostapis()
    candidates = [i for i, d in enumerate(devices) if d['max_input_channels'] > 0
                  and 'cableoutput' in ''.join(d['name'].casefold().split())
                  and apis[d['hostapi']]['name'] == 'Windows WASAPI']
    if not candidates: raise RuntimeError('CABLE Output 녹음 장치를 찾지 못했습니다. Windows 마이크 접근 권한도 확인하세요.')
    index = candidates[0]; rate = int(devices[index]['default_samplerate']); received = []
    def callback(data, frames, timing, status): received.append(data.copy())
    # A distinctive synthetic tone, sent only when the user requests this test.
    t = np.arange(24000, dtype=np.float32) / 24000
    tone = .06 * np.sin(2 * np.pi * 997 * t) * np.minimum(1, np.minimum(t, 1-t) * 40)
    with sd.InputStream(device=index, samplerate=rate, channels=1, dtype='float32', callback=callback,
                        extra_settings=sd.WasapiSettings(auto_convert=True)):
        time.sleep(.2); play_cable(tone, 24000, 1., threading.Event()); time.sleep(.3)
    samples = np.concatenate(received).reshape(-1) if received else np.zeros(1)
    spectrum = abs(np.fft.rfft(samples)); freq = np.fft.rfftfreq(len(samples), 1/rate)
    band = spectrum[abs(freq-997) < 4]
    amplitude = float(band.max(initial=0) * 2 / len(samples))
    result.update(ok=amplitude > .003, received_tone_amplitude=amplitude)
    result['message'] = ('테스트 신호가 CABLE Output까지 도착했습니다. Discord 입력도 CABLE Output으로 선택하세요.'
                         if result['ok'] else '출력은 열렸지만 테스트 신호가 수신되지 않았습니다. Windows 소리 설정을 확인하세요.')
    return result
