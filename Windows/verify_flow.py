"""One packaged Windows flow, using generated test speech only."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import numpy as np
import sounddevice as sd


def audio_device(input=False):
    from audio import cable_input, cable_output
    return cable_input() if input else cable_output()


def play(path):
    import soundfile as sf
    from audio import play_cable
    data, rate = sf.read(path, dtype='float32')
    print('READY', flush=True)
    time.sleep(3)
    play_cable(data, rate, 1., threading.Event())
    time.sleep(2)


def main(install=None, validation=None):
    if len(sys.argv) > 1 and sys.argv[1] == '--play':
        play(sys.argv[2]); return
    import soundfile as sf
    from scipy.signal import resample_poly
    from audio import SpeechChunks
    if install is None: install, validation = map(Path, sys.argv[1:3])
    validation.mkdir(parents=True, exist_ok=True)
    model_root = validation / 'Models'
    log = (validation / 'worker-stderr.log').open('w', encoding='utf-8')
    engine = install / 'Engine' / 'STTSWorker.exe'
    worker = subprocess.Popen([str(engine if engine.is_file() else install / 'STTSWorker.exe')], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=log, text=True, encoding='utf-8', bufsize=1, creationflags=subprocess.CREATE_NO_WINDOW)
    def request(value):
        worker.stdin.write(json.dumps(value, ensure_ascii=False) + '\n'); worker.stdin.flush()
        for line in worker.stdout:
            item = json.loads(line)
            if item.get('event'):
                print(item.get('message'), flush=True); continue
            if not item.get('ok'): raise RuntimeError(item)
            return item
        raise RuntimeError('Worker exited')
    report = {}
    try:
        assert request({'action': 'ping'})['ok']
        # No speech chunks are produced for digital silence.
        chunks = SpeechChunks()
        assert all(chunks.feed(np.zeros(1600, dtype='float32')) is None for _ in range(100))
        start = time.monotonic()
        result = request({'action': 'tts', 'model': 'supertonic3', 'root': str(model_root),
            'voice': 'F1', 'language': 'ko', 'text': '안녕하세요. 음성 인식과 가상 마이크가 정상적으로 작동하는지 테스트하고 있습니다.'})
        data = np.frombuffer(base64.b64decode(result['audio']), dtype='<f4')
        assert data.size > result['rate'] and float(np.max(np.abs(data))) > 0.01
        report['supertonic_backend'] = result.get('backend')
        report['supertonic_seconds_including_download'] = time.monotonic() - start
        path = validation / 'generated-test.wav'; sf.write(path, data, result['rate'])
        # Route the packaged engine's actual audio through the installed virtual mic.
        input_device = audio_device(True)
        input_rate = int(sd.query_devices(input_device)['default_samplerate'])
        mic_chunks = []
        def record(indata, frames, timestamp, status): mic_chunks.append(indata[:, 0].copy())
        with sd.InputStream(device=input_device, channels=1, samplerate=input_rate, dtype='float32', callback=record, extra_settings=sd.WasapiSettings(auto_convert=True)):
            player = subprocess.Popen([str(engine), '--play-test', str(path)], stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW)
            assert player.stdout.readline().strip() == 'READY'
            capture = subprocess.Popen([str(install / 'STTSCapture.exe'), str(player.pid)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
            pipe = []
            reader = threading.Thread(target=lambda: pipe.append(capture.communicate(timeout=120)))
            reader.start()
            player.wait(timeout=120)
            assert player.returncode == 0, player.stderr.read()
            reader.join(timeout=125)
            if reader.is_alive(): capture.kill(); raise AssertionError('Capture did not stop when target exited')
        assert capture.returncode == 0, pipe[0][1].decode(errors='replace')
        captured = np.frombuffer(pipe[0][0], dtype='<i2').astype('float32') / 32768
        microphone = np.concatenate(mic_chunks)
        assert captured.size > 16000 and np.max(np.abs(captured)) > 0.005, 'Process loopback silent'
        assert microphone.size > input_rate and np.max(np.abs(microphone)) > 0.005, 'Virtual microphone silent'
        report['process_loopback_samples'] = int(captured.size)
        report['microphone_peak'] = float(np.max(np.abs(microphone)))
        # Recognize audio that actually arrived at the virtual microphone.
        from math import gcd
        common = gcd(input_rate, 16000)
        pcm = resample_poly(microphone, 16000 // common, input_rate // common).astype('<f4')
        result = request({'action': 'stt', 'model': 'small', 'root': str(model_root),
            'audio': base64.b64encode(pcm.tobytes()).decode()})
        report['whisper_backend'] = result.get('backend')
        report['virtual_microphone_transcript'] = result['text']
        assert sum(word in result['text'] for word in ('안녕', '마이크', '테스트')) >= 2, result
        # Exercise a downloaded INT8 Qwen checkpoint through the packaged loader.
        start = time.monotonic()
        result = request({'action': 'tts', 'model': 'qwen06Custom', 'root': str(model_root),
            'voice': 'Sohee', 'language': 'ko', 'text': '안녕하세요.'})
        qwen = np.frombuffer(base64.b64decode(result['audio']), dtype='<f4')
        assert qwen.size > result['rate'] // 4 and np.isfinite(qwen).all() and np.max(np.abs(qwen)) > 0.01
        report['qwen_backend'] = result.get('backend')
        report['qwen_seconds_including_download'] = time.monotonic() - start
        sf.write(validation / 'qwen-test.wav', qwen, result['rate'])
        report['ok'] = True
        (validation / 'flow.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False), flush=True)
    finally:
        worker.kill(); worker.wait(timeout=10); log.close()

if __name__ == '__main__': main()
