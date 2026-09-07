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

BASE = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent

def command(kind):
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
                process = subprocess.Popen(command('worker'), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
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
        'CABLE Output은 Discord에서 선택하는 녹음 장치입니다.')

def play_cable(samples, rate, volume, stop):
    from scipy.signal import resample_poly
    from math import gcd
    index = cable_output()  # Never fall back to a physical speaker or another device.
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
            if stop.is_set():
                stream.abort()
                return
            gain = volume() if callable(volume) else volume
            chunk = np.repeat(np.clip(samples[offset:offset + 2048, None] * gain, -1, 1), channels, axis=1)
            stream.write(chunk)

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
