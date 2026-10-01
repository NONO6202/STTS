"""Private JSON pipe worker. No listening ports and no persistent captured audio."""
import base64
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import subprocess

ROOT = Path(__file__).resolve().parent
CATALOG = json.loads((ROOT / 'models.json').read_text(encoding='utf-8'))
MODEL = None
MODEL_KEY = None
BACKEND = {'device': 'cpu', 'name': 'CPU'}
CPU_ONLY = set()
OUT = sys.stdout

def emit(value):
    OUT.write(json.dumps(value, ensure_ascii=False) + '\n')
    OUT.flush()

def valid_file(path, entry):
    if not path.is_file() or path.stat().st_size != entry['size']:
        return False
    digest = hashlib.sha256() if entry.get('sha256') else hashlib.sha1()
    if not entry.get('sha256'):
        digest.update(f"blob {entry['size']}\0".encode())
    with path.open('rb') as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest() == (entry.get('sha256') or entry['git_sha1'])

def prepare_model(key, root):
    from downloads import download, finish_parts
    asset = CATALOG[key]
    directory = Path(root) / f"{key}-{asset.get('variant', asset['revision'][:12])}"
    directory.mkdir(parents=True, exist_ok=True)
    total = sum(f['size'] for f in asset['files'])
    completed = 0
    for entry in asset['files']:
        dest = directory / entry['path']
        if not valid_file(dest, entry):
            dest.parent.mkdir(parents=True, exist_ok=True)
            url = f"https://huggingface.co/{entry.get('repo', asset['repo'])}/resolve/{entry.get('revision', asset['revision'])}/{entry.get('remote_path', entry['path'])}"
            temporary, parts, count = download(url, dest, entry['size'],
                lambda received: emit({'event': 'progress', 'message': f'{key} 다운로드 {(completed + received) * 100 // total}%'}))
            try:
                if not valid_file(Path(temporary), entry):
                    finish_parts(parts, count)
                    raise ValueError('모델 파일 검증 실패. 다시 시도하세요.')
                os.replace(temporary, dest)
                finish_parts(parts, count)
            finally:
                Path(temporary).unlink(missing_ok=True)
        completed += entry['size']
    return directory

def load_model(key, root):
    global MODEL, MODEL_KEY, BACKEND
    if MODEL_KEY == key:
        return MODEL
    from acceleration import cuda_device, directml_device, enable_directml, release_cuda, accelerator_error
    MODEL = None; MODEL_KEY = None
    release_cuda()
    directory = prepare_model(key, root)
    emit({'event': 'progress', 'message': f'{key} 불러오는 중…'})
    device = None
    if key not in CPU_ONLY:
        try: device = directml_device() if key == 'supertonic3' else cuda_device()
        except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired):
            emit({'event': 'progress', 'message': 'GPU를 확인하지 못해 CPU를 사용합니다.'})
    def create(accelerator):
        if key in ('small', 'turbo', 'large'):
            from faster_whisper import WhisperModel
            return WhisperModel(str(directory), device='cuda' if accelerator else 'cpu',
                                device_index=accelerator['index'] if accelerator else 0,
                                compute_type='int8_float16' if accelerator else 'int8', cpu_threads=min(8, os.cpu_count() or 2))
        if key == 'supertonic3':
            from supertonic import TTS
            engine = TTS(model='supertonic-3', model_dir=directory, auto_download=False,
                         intra_op_num_threads=min(4, os.cpu_count() or 2), inter_op_num_threads=1)
            if accelerator and not enable_directml(engine, directory, accelerator):
                raise RuntimeError('DirectML 실행 환경을 사용할 수 없습니다.')
            return engine
        import torch
        from qwen_int8 import load
        torch.set_num_threads(min(8, os.cpu_count() or 2))
        # The quantized checkpoints retain BF16 tensors. FP16 overflows on
        # these weights; use BF16 where supported, otherwise FP32 activations.
        dtype = torch.float32
        if accelerator:
            with torch.cuda.device(accelerator['index']):
                if torch.cuda.is_bf16_supported(): dtype = torch.bfloat16
        return load(directory, accelerator['device'] if accelerator else 'cpu', dtype)
    try:
        MODEL = create(device)
    except Exception as error:
        if not device or not accelerator_error(error): raise
        CPU_ONLY.add(key); device = None; release_cuda()
        emit({'event': 'progress', 'message': 'GPU 초기화 실패 또는 메모리 부족으로 CPU를 사용합니다.'})
        MODEL = create(None)
    MODEL_KEY = key
    BACKEND = {'device': ('directml' if key == 'supertonic3' else device['device']) if device else 'cpu',
               'name': device['name'] if device else 'CPU', 'precision': CATALOG[key]['precision']}
    emit({'event': 'progress', 'message': ('GPU · ' if device else 'CPU · ') + BACKEND['name']})
    return MODEL

def decode_file(path):
    from faster_whisper.audio import decode_audio
    return decode_audio(path, sampling_rate=24000)

def handle_request(req):
    import numpy as np
    if req['action'] == 'ping':
        return {'ok': True}
    if req['action'] in ('decode', 'decode_sound'):
        data = decode_file(req['path'])
        if req['action'] == 'decode' and not 3 <= len(data) / 24000 <= 30:
            raise ValueError('음성 샘플은 3~30초여야 합니다.')
        return audio_reply(data, 24000, pitch=req.get('pitch', 0) if req['action'] == 'decode_sound' else 0, speed=req.get('speed', 1) if req['action'] == 'decode_sound' else 1)
    if req['action'] == 'load':
        load_model(req['model'], req['root'])
        return {'ok': True}
    if req['action'] == 'stt':
        data = np.frombuffer(base64.b64decode(req['audio']), dtype='<f4')
        if data.size > 16000 * 30 or not np.isfinite(data).all():
            raise ValueError('잘못된 음성 입력')
        if data.size == 0 or np.max(np.abs(data)) < 0.001:
            return {'ok': True, 'text': ''}
        model = load_model(req['model'], req['root'])
        segments, _ = model.transcribe(data, language=None, beam_size=3, vad_filter=True,
            condition_on_previous_text=False, no_speech_threshold=0.6,
            vad_parameters={'min_silence_duration_ms': 350})
        text = ' '.join(s.text.strip() for s in segments if s.no_speech_prob < 0.6 and s.avg_logprob > -1)
        return {'ok': True, 'text': text.strip()}
    if req['action'] != 'tts':
        raise ValueError('알 수 없는 요청')
    text = req['text'].strip()
    if not text or len(text) > 500:
        raise ValueError('1~500자를 입력하세요.')
    key = req['model']
    if key == 'gtts':
        from gtts import gTTS
        from faster_whisper.audio import decode_audio
        data = io.BytesIO()
        gTTS(text, lang=req.get('language', 'ko'), timeout=(10, 30)).write_to_fp(data)
        data.seek(0)
        return audio_reply(decode_audio(data, sampling_rate=24000), 24000, pitch=req.get('pitch', 0), speed=req.get('speed', 1))
    model = load_model(key, req['root'])
    if key == 'supertonic3':
        style = model.get_voice_style(req.get('voice', 'F1'))
        data, duration = model.synthesize(text, voice_style=style, lang=req.get('language', 'ko'))
        sr = model.sample_rate
        data = np.asarray(data).reshape(-1)[:int(float(np.asarray(duration).reshape(-1)[0]) * sr)]
    else:
        languages = {'ko': 'Korean', 'en': 'English', 'ja': 'Japanese', 'zh': 'Chinese', 'de': 'German',
                     'fr': 'French', 'es': 'Spanish', 'it': 'Italian', 'pt': 'Portuguese', 'ru': 'Russian'}
        options = dict(text=text, language=languages[req.get('language', 'ko')], max_new_tokens=1500,
                       do_sample=True, temperature=0.7)
        if key.endswith('Custom'):
            waves, sr = model.generate_custom_voice(speaker=req.get('voice', 'Sohee'), **options)
        else:
            import soundfile as sf
            path = Path(req['reference']).resolve()
            voice_root = Path(req['voice_root']).resolve()
            if path.parent != voice_root or path.suffix != '.wav':
                raise ValueError('저장된 목소리만 사용할 수 있습니다.')
            ref, ref_sr = sf.read(path, dtype='float32')
            if not 3 <= len(ref) / ref_sr <= 30 or not req.get('transcript', '').strip():
                raise ValueError('클론 음성과 대본이 필요합니다.')
            waves, sr = model.generate_voice_clone(ref_audio=(ref, ref_sr), ref_text=req['transcript'], **options)
        data = waves[0]
    return audio_reply(data, sr, pitch=req.get('pitch', 0), speed=req.get('speed', 1))

def handle(req):
    global MODEL, MODEL_KEY
    from acceleration import accelerator_error, release_cuda
    try:
        result = handle_request(req)
    except Exception as error:
        key = req.get('model')
        if key not in CATALOG or MODEL_KEY != key or BACKEND['device'] == 'cpu' or not accelerator_error(error): raise
        CPU_ONLY.add(key); MODEL = None; MODEL_KEY = None; release_cuda()
        emit({'event': 'progress', 'message': 'GPU 실행 실패 또는 메모리 부족으로 CPU에서 다시 처리합니다.'})
        result = handle_request(req)
    if req.get('model') is not None and req.get('model') == MODEL_KEY: result['backend'] = dict(BACKEND)
    return result


def audio_reply(data, sr, *, pitch=0, speed=1):
    import numpy as np
    data = np.asarray(data, dtype='<f4').reshape(-1)
    if not data.size or not np.isfinite(data).all() or data.size > sr * 180:
        raise ValueError('음성 생성 결과가 유효하지 않습니다.')
    if not np.isfinite(pitch) or not -12 <= pitch <= 12 or not np.isfinite(speed) or not .5 <= speed <= 2:
        raise ValueError('피치 또는 속도 범위가 올바르지 않습니다.')
    if pitch or speed != 1:
        import librosa
        if pitch: data = librosa.effects.pitch_shift(data, sr=int(sr), n_steps=float(pitch))
        if speed != 1: data = librosa.effects.time_stretch(data, rate=float(speed))
        data = np.asarray(data, dtype='<f4')
        if not data.size or not np.isfinite(data).all(): raise ValueError('음성 조절 결과가 유효하지 않습니다.')
    return {'ok': True, 'audio': base64.b64encode(data.tobytes()).decode('ascii'), 'rate': int(sr)}

def main():
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    os.environ['DO_NOT_TRACK'] = '1'
    os.environ['TOKENIZERS_PARALLELISM'] = 'false'
    for line in sys.stdin:
        try:
            if len(line) > 8_000_000:
                raise ValueError('요청 크기 초과')
            with contextlib.redirect_stdout(sys.stderr):
                result = handle(json.loads(line))
            emit(result)
        except Exception as error:
            emit({'ok': False, 'error': f'{type(error).__name__}: {error}'})

if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--play-test':
        import soundfile as sf
        import threading, time
        from audio import play_cable
        data, rate = sf.read(sys.argv[2], dtype='float32')
        print('READY', flush=True)
        time.sleep(3)
        play_cable(data, rate, 1., threading.Event())
        time.sleep(2)
    else:
        main()
