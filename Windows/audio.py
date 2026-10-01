import base64
from collections import deque
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import numpy as np
import psutil
import sounddevice as sd
from microphone_effects import MicrophoneEffects
from microphone_buffer import MicrophoneBuffer

BASE = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
_playback_lock = threading.Lock()

def command():
    if getattr(sys, 'frozen', False):
        isolated = BASE / 'Engine' / 'STTSWorker.exe'
        return [str(isolated if isolated.is_file() else BASE / 'STTSWorker.exe')]
    return [sys.executable, '-u', str(BASE / 'worker.py')]

class Worker:
    def __init__(self, job, status):
        self.job, self.status = job, status
        self.process = None
        self.closed = threading.Event()
        self.lock = threading.Lock()
    def request(self, request):
        with self.lock:
            if self.closed.is_set():
                raise RuntimeError('음성 작업이 취소되었습니다.')
            if self.process is None or self.process.poll() is not None:
                process = subprocess.Popen(command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, text=True, encoding='utf-8', bufsize=1,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                self.job.assign(process)
                self.process = process
                if self.closed.is_set():
                    process.kill()
                    raise RuntimeError('음성 작업이 취소되었습니다.')
            process = self.process
            process.stdin.write(json.dumps(request, ensure_ascii=False) + '\n')
            process.stdin.flush()
            while line := process.stdout.readline():
                result = json.loads(line)
                if result.get('event') == 'progress':
                    self.status(result['message'])
                    continue
                if not result.get('ok'):
                    raise RuntimeError(result.get('error', '음성 작업 실패'))
                if result.get('backend'):
                    backend = result['backend']
                    channel = 'STT' if request.get('model') in ('small', 'turbo', 'large') else 'TTS'
                    self.status(channel + ' · ' + ('CPU' if backend['device'] == 'cpu' else 'GPU · ' + backend['name']) + ' · ' + backend.get('precision', ''))
                return result
            raise RuntimeError('음성 엔진이 종료되었습니다. 메모리 여유를 확인하고 다시 시도하세요.')
    def stop(self):
        self.closed.set()
        process, self.process = self.process, None
        if process and process.poll() is None:
            process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

def cable_output(*, refresh=False):
    # PortAudio caches the endpoint list at initialization. Only refresh while
    # idle: terminating it would close any active voice-recording/playback stream.
    if refresh:
        sd._terminate()
        sd._initialize()
    devices = sd.query_devices()
    apis = sd.query_hostapis()
    candidates = []
    priority = {'Windows WASAPI': 0, 'Windows DirectSound': 1, 'MME': 2}
    for index, device in enumerate(devices):
        name = ''.join(device['name'].casefold().split())
        if device['max_output_channels'] > 0 and (
                'vb-audiovirtualcable' in name or name.startswith(('cableinput', 'cablein16ch'))):
            candidates.append((priority.get(apis[device['hostapi']]['name'], 3), index))
    if candidates: return min(candidates)[1]
    raise RuntimeError('사용 가능한 재생 장치 CABLE Input을 찾지 못했습니다.\n'
        'Windows 소리 설정의 재생 장치에서 CABLE Input의 사용 상태를 확인하세요.\n'
        'STTS (VB-Audio Virtual Cable)는 Discord에서 선택하는 녹음 장치입니다.')


def cable_input():
    from setup_check import cable_levels
    endpoint = cable_levels().get('capture')
    if endpoint is None:
        raise RuntimeError('STTS 가상 마이크가 없거나 사용 중지 상태입니다.')
    name = ''.join(endpoint['name'].casefold().split())
    devices, apis = sd.query_devices(), sd.query_hostapis()
    matches = [i for i, d in enumerate(devices) if d['max_input_channels'] > 0
               and ''.join(d['name'].casefold().split()) == name
               and apis[d['hostapi']]['name'] == 'Windows WASAPI']
    if len(matches) != 1:
        raise RuntimeError('STTS 녹음 장치를 확인하지 못했습니다. Windows 마이크 접근 권한과 장치 상태를 확인하세요.')
    return matches[0]


def physical_microphones():
    """Use one shared-mode endpoint per device; never feed the cable into itself."""
    devices, apis = sd.query_devices(), sd.query_hostapis()
    result = []
    for index, device in enumerate(devices):
        name = device['name']
        if (device['max_input_channels'] <= 0 or apis[device['hostapi']]['name'] != 'Windows WASAPI'
                or any(word in name.casefold() for word in ('cable', 'stts', 'loopback', 'stereo mix', '스테레오 믹스', 'voicemeeter'))):
            continue
        result.append({'id': name, 'name': name, 'index': index})
    return result


class MicrophonePassthrough:
    """The Windows shared mixer combines this stream with TTS at CABLE Input."""
    def __init__(self):
        self.stream = None
        self._input_stream = None
        self._thread = None
        self._stopped = threading.Event()
        self._failed = False
        self.buffer = MicrophoneBuffer()
        self.volume = 1.0
        self.effects = None
        self.effect_settings = (0, '기본', 0.65)

    @property
    def active(self):
        return (self.stream is not None and self.stream.active
                and self._input_stream is not None and self._input_stream.active and not self._failed)

    def start(self, device_id, volume, *, refresh=False):
        self.stop()
        # Resolve BOTH endpoint indices after refreshing: PortAudio indices can
        # change when a USB device or the virtual cable is reconnected.
        if refresh and _playback_lock.acquire(blocking=False):
            try:
                sd._terminate()
                sd._initialize()
            finally:
                _playback_lock.release()
        matches = [d for d in physical_microphones() if d['id'] == device_id]
        if len(matches) != 1:
            raise RuntimeError('선택한 실제 마이크를 찾지 못했습니다. 장치 목록을 새로고침해 다시 선택하세요.')
        source = matches[0]['index']; target = cable_output()
        input_info, output_info = sd.query_devices(source), sd.query_devices(target)
        if sd.query_hostapis(output_info['hostapi'])['name'] != 'Windows WASAPI':
            raise RuntimeError('가상 마이크의 WASAPI 장치를 사용할 수 없습니다.')
        self.volume = volume
        rate = int(output_info['default_samplerate'])
        input_rate = int(input_info['default_samplerate'])
        self.effects = MicrophoneEffects(input_rate)
        self.buffer = buffer = MicrophoneBuffer(input_rate, output_rate=rate)
        self._stopped = stopped = threading.Event()
        self._failed = False
        try:
            settings = sd.WasapiSettings(auto_convert=True)
            self._input_stream = sd.InputStream(device=source, samplerate=input_rate,
                channels=min(2, input_info['max_input_channels']), dtype='float32',
                latency='low', extra_settings=settings)
            self.stream = sd.OutputStream(device=target, samplerate=rate,
                channels=min(2, output_info['max_output_channels']), dtype='float32',
                blocksize=max(1, round(rate * 0.01)), latency=0.06, extra_settings=settings,
                callback=lambda outdata, frames, timestamp, status:
                    self._render(buffer, outdata, discontinuity=bool(status.output_underflow)))
            self._input_stream.start()
            self.stream.start()
            self._thread = threading.Thread(target=self._capture,
                args=(self._input_stream, buffer, self.effects, stopped, max(1, round(input_rate * 0.01))), daemon=True)
            self._thread.start()
        except Exception:
            self.stop()
            raise

    def _capture(self, stream, buffer, effects, stopped, frames):
        try:
            while not stopped.is_set():
                data, overflowed = stream.read(frames)
                if stopped.is_set(): break
                mono = effects.process(np.mean(data, axis=1), *self.effect_settings)
                buffer.append(mono, discontinuity=overflowed)
        except Exception:
            if not stopped.is_set(): self._failed = True

    def _render(self, buffer, outdata, *, discontinuity=False):
        # Only cheap buffered playback runs on PortAudio's deadline. Effects
        # execute on the capture worker and never play through local speakers.
        buffer.render(outdata, discontinuity=discontinuity)
        gain = float(self.volume)
        gain = min(1.0, max(0.0, gain)) if np.isfinite(gain) else 0.0
        outdata *= gain
        np.clip(outdata, -1.0, 1.0, out=outdata)

    def stop(self):
        self._stopped.set()
        streams = (self.stream, self._input_stream)
        self.stream = self._input_stream = None
        for stream in streams:
            if stream is None: continue
            try: stream.abort()
            except sd.PortAudioError: pass  # A removed endpoint may already be stopped.
        if self._thread is not None:
            if self._thread.ident is not None: self._thread.join(timeout=2)
            self._thread = None
        for stream in streams:
            if stream is None: continue
            try: stream.close()
            except sd.PortAudioError: pass
        self._failed = False
        self.effects = None

def _play_output(samples, rate, index, volume, cancelled):
    from scipy.signal import resample_poly
    from math import gcd
    info = sd.query_devices(index)
    target = int(info['default_samplerate'])
    if target != rate:
        common = gcd(int(rate), target)
        samples = resample_poly(samples, target // common, int(rate) // common)
    samples = np.asarray(samples, dtype='float32')
    channels = min(2, info['max_output_channels'])
    settings = sd.WasapiSettings(auto_convert=True) if sd.query_hostapis(info['hostapi'])['name'] == 'Windows WASAPI' else None
    with sd.OutputStream(device=index, samplerate=target, channels=channels, dtype='float32', latency='high', extra_settings=settings) as stream:
        for offset in range(0, len(samples), 2048):
            if cancelled():
                stream.abort()
                return
            gain = volume() if callable(volume) else volume
            chunk = np.repeat(np.clip(samples[offset:offset + 2048, None] * gain, -1, 1), channels, axis=1)
            stream.write(chunk)

def play_cable(samples, rate, volume, stop, *, monitor=False):
    # Cancellation clears the UI busy flag before the playback thread closes
    # its streams. Keep microphone retries from resetting PortAudio in that gap.
    with _playback_lock:
        return _play_cable(samples, rate, volume, stop, monitor=monitor)

def _play_cable(samples, rate, volume, stop, *, monitor=False):
    index = cable_output()  # The transmitted stream never falls back to another device.
    monitor_stop = threading.Event()
    monitor_errors = []
    monitor_thread = None

    def play_monitor():
        try:
            info = sd.query_devices(kind='output')
            name = ''.join(info['name'].casefold().split())
            if (info['index'] == index or info['max_output_channels'] <= 0
                    or 'vb-audiovirtualcable' in name or name.startswith(('cableinput', 'cablein16ch'))):
                raise RuntimeError('Windows 기본 출력 장치를 스피커·헤드폰으로 선택하세요.')
            _play_output(samples, rate, info['index'], volume,
                         lambda: stop.is_set() or monitor_stop.is_set())
        except Exception as error:
            monitor_errors.append(str(error))

    if monitor and not stop.is_set():
        # Separate device clocks must not block each other's writes or slow TTS delivery.
        monitor_thread = threading.Thread(target=play_monitor, daemon=True)
        monitor_thread.start()
    try:
        _play_output(samples, rate, index, volume, stop.is_set)
    except BaseException:
        monitor_stop.set()
        raise
    finally:
        if monitor_thread is not None:
            monitor_thread.join()
    if monitor_errors and not stop.is_set():
        return 'TTS는 전송했지만 목소리 모니터링을 하지 못했습니다: ' + monitor_errors[0]
    return None

def discord_pid():
    candidates = {}
    for process in psutil.process_iter(['pid', 'ppid', 'name', 'create_time']):
        if (process.info['name'] or '').lower() in ('discord.exe', 'discordptb.exe', 'discordcanary.exe'):
            candidates[process.pid] = process.info
    roots = [p for p in candidates.values() if p['ppid'] not in candidates]
    if not roots:
        raise RuntimeError('Discord 데스크톱 앱을 먼저 실행하세요.')
    return min(roots, key=lambda p: p['create_time'])['pid']

class SpeechChunks:
    """Bounded in-memory segmentation; Whisper's Silero VAD confirms speech."""
    def __init__(self):
        self.pre = deque(maxlen=5)
        self.frames = []
        self.quiet = 0
    def feed(self, data):
        voiced = float(np.sqrt(np.mean(data * data))) >= 0.006
        if not self.frames:
            self.pre.append(data)
            if voiced:
                self.frames = list(self.pre)
                self.pre.clear()
            return None
        self.frames.append(data)
        self.quiet = 0 if voiced else self.quiet + 1
        if self.quiet >= 6 or len(self.frames) >= 50:
            value = np.concatenate(self.frames)
            self.frames, self.quiet = [], 0
            return value
        return None

class Capture:
    def __init__(self, job, worker, model, model_root, caption, status, ended):
        self.job, self.worker, self.model, self.model_root = job, worker, model, model_root
        self.caption, self.status, self.ended = caption, status, ended
        self.stop_event = threading.Event()
        self.frames = queue.Queue(maxsize=2)
        self.process = None
    def start(self):
        pid = discord_pid()
        self.process = subprocess.Popen([str(BASE / 'STTSCapture.exe'), str(pid)], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
        self.job.assign(self.process)
        threading.Thread(target=self.read, daemon=True).start()
        threading.Thread(target=self.transcribe, daemon=True).start()
    def read(self):
        segmenter = SpeechChunks()
        try:
            while not self.stop_event.is_set():
                raw = self.process.stdout.read(3200)
                if len(raw) < 3200:
                    if not self.stop_event.is_set():
                        detail = self.process.stderr.read(2048).decode(errors='replace').strip()
                        raise RuntimeError('Discord 오디오 캡처가 종료되었습니다. ' + detail)
                    break
                result = segmenter.feed(np.frombuffer(raw, dtype='<i2').astype('float32') / 32768)
                if result is not None:
                    try:
                        self.frames.put_nowait(result)
                    except queue.Full:
                        try:
                            self.frames.get_nowait()
                        except queue.Empty:
                            pass
                        self.frames.put_nowait(result)
                        self.status('인식이 밀려 오래된 음성 구간을 건너뜁니다. STT 낮음을 선택해 보세요.')
        except Exception as error:
            if not self.stop_event.is_set():
                self.status(str(error))
                self.ended()
    def transcribe(self):
        try:
            self.worker.request({'action': 'load', 'model': self.model, 'root': str(self.model_root)})
            if not self.stop_event.is_set():
                self.status('Discord 수신 대기')
            while not self.stop_event.is_set():
                try:
                    data = self.frames.get(timeout=0.2)
                except queue.Empty:
                    continue
                result = self.worker.request({'action': 'stt', 'model': self.model, 'root': str(self.model_root),
                    'audio': base64.b64encode(data.astype('<f4').tobytes()).decode()})
                if not self.stop_event.is_set() and result['text']:
                    self.caption(result['text'])
        except Exception as error:
            if not self.stop_event.is_set():
                self.status(str(error))
                self.ended()
    def stop(self):
        self.stop_event.set()
        if self.process and self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=5)
        self.worker.stop()
