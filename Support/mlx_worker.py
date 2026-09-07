"""One resident local model per worker. PCM travels over a pipe, never over HTTP."""
import base64
import contextlib
import fcntl
import hashlib
import json
import math
import os
import signal
import select
from pathlib import Path
import ssl
import sys
import tempfile
import time
import urllib.request
import wave

os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
os.environ['TOKENIZERS_PARALLELISM'] = 'false'
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
CATALOG = json.loads((Path(__file__).parent / 'mlx_models.json').read_text())
LANGUAGES = json.loads((Path(__file__).parent / 'speech_languages.json').read_text())
LIMIT = 2_000_000
MODEL = None
MODEL_KEY = None


def caption_segments(segments, duration):
    result = []
    for segment in segments:
        text = segment['text'].strip()
        start, end = float(segment['start']), float(segment['end'])
        if not math.isfinite(start) or not math.isfinite(end) or start >= duration or end <= 0:
            continue
        start, end = max(0, start), min(duration, end)
        if end > start and any(char.isalnum() for char in text) and segment.get('no_speech_prob', 0) < 0.75:
            result.append({'text': text, 'start': start, 'end': end})
    return result


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def valid_file(path, entry):
    if not path.is_file() or path.stat().st_size != entry['size']:
        return False
    digest = hashlib.sha256() if entry.get('sha256') else hashlib.sha1()
    if not entry.get('sha256'):
        digest.update(f"blob {entry['size']}\0".encode())
    with path.open('rb') as handle:
        while chunk := handle.read(1_048_576):
            digest.update(chunk)
    return digest.hexdigest() == (entry.get('sha256') or entry['git_sha1'])


def prepare_model(key, root):
    import certifi
    asset = CATALOG[key]
    directory = Path(root) / 'MLX' / f"{key}-{asset['revision'][:12]}"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    context = ssl.create_default_context(cafile=certifi.where())
    for entry in asset['files']:
        dest = directory / entry['path']
        if valid_file(dest, entry):
            continue
        dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        url = f"https://huggingface.co/{entry.get('repo', asset['repo'])}/resolve/{entry.get('revision', asset['revision'])}/{entry['path']}"
        emit({'event': 'progress', 'message': '모델 다운로드 중…'})
        fd, temporary = tempfile.mkstemp(dir=dest.parent, prefix='.download-')
        try:
            with os.fdopen(fd, 'wb') as output, urllib.request.urlopen(url, context=context, timeout=60) as response:
                while chunk := response.read(1_048_576):
                    output.write(chunk)
            if not valid_file(Path(temporary), entry):
                raise ValueError('model integrity mismatch')
            os.replace(temporary, dest)
        finally:
            Path(temporary).unlink(missing_ok=True)
    if key != 'supertonic3':
        config = json.loads((directory / 'config.json').read_text())
        bits = config.get('quantization', config.get('quantization_config', {})).get('bits')
        if not asset.get('quantizeOnLoad') and bits != (8 if asset.get('bits', 8) == 8 else None):
            raise ValueError('unexpected model precision')
    return directory


def load_model(request):
    global MODEL, MODEL_KEY
    import gc
    import mlx.core as mx
    key = request['model']
    if MODEL_KEY == key:
        return {'ok': True, 'bits': CATALOG[key].get('bits', 8), 'model': key}
    directory = prepare_model(key, request['root'])
    if MODEL_KEY != key:
        MODEL = None
        gc.collect()
        mx.clear_cache()
        # Keep caches small; do not wire the machine's entire available memory.
        mx.set_cache_limit(128 * 1_048_576)
        mx.set_memory_limit(int(request.get('memoryMB', 4096)) * 1_048_576)
        mx.set_wired_limit(0)
        with contextlib.redirect_stdout(sys.stderr):
            if key == 'supertonic3':
                from supertonic import TTS
                MODEL = TTS(model='supertonic-3', model_dir=directory, auto_download=False,
                    intra_op_num_threads=int(os.environ.get('OMP_NUM_THREADS', '1')), inter_op_num_threads=1)
            elif key == 'chatterV3':
                from chatterbox_loader import load
            elif CATALOG[key]['kind'] == 'stt':
                from mlx_audio.stt.utils import load_model as load
            else:
                from mlx_audio.tts.utils import load_model as load
            if key != 'supertonic3':
                MODEL = load(directory if key == 'chatterV3' else str(directory))
        if key in ('qwen06', 'qwen17', 'qwen06Custom', 'qwen17Custom') and (MODEL.tokenizer is None or MODEL.speech_tokenizer is None):
            MODEL = None
            raise ValueError('missing local tokenizer')
        MODEL_KEY = key
    return {'ok': True, 'bits': CATALOG[key].get('bits', 8), 'model': key}


def reference_prompt(request):
    audio, text = request.get('referenceAudio'), request.get('referenceText')
    if audio is None and text is None:
        return {}
    if not isinstance(audio, str) or not Path(audio).is_absolute() or not Path(audio).is_file():
        raise ValueError('invalid reference audio')
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 1000:
        raise ValueError('invalid reference transcript')
    import soundfile as sf
    import numpy as np
    info = sf.info(audio)
    if not 3 <= info.duration <= 30 or not 1 <= info.channels <= 2 or not 8000 <= info.samplerate <= 192000:
        raise ValueError('reference must be 3 to 30 seconds')
    samples, _ = sf.read(audio, dtype='float32')
    if not np.isfinite(samples).all() or not np.any(np.abs(samples) > .001):
        raise ValueError('invalid reference samples')
    return {'ref_audio': audio, 'ref_text': text.strip()}


@contextlib.contextmanager
def model_access(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(root / '.model-access.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH)
        yield
    finally:
        os.close(fd)


def handle(request):
    if request.get('command') in ('prepare', 'load'):
        with model_access(request['root']):
            return handle_model_request(request)
    return handle_model_request(request)


def handle_model_request(request):
    command = request['command']
    if command == 'ping':
        return {'ok': True}
    if command == 'prepare':
        prepare_model(request['model'], request['root'])
        return {'ok': True, 'bits': CATALOG[request['model']].get('bits', 8)}
    if command == 'load':
        return load_model(request)
    if MODEL is None:
        raise ValueError('model not loaded')
    import mlx.core as mx
    import numpy as np
    started = time.monotonic()
    if command in ('stt', 'transcribe_voice') and CATALOG[MODEL_KEY]['kind'] == 'stt':
        if command == 'transcribe_voice':
            import soundfile as sf
            source = Path(request['audioFile'])
            if MODEL_KEY != 'turbo' or not source.is_absolute() or not source.is_file():
                raise ValueError('invalid voice recording')
            info = sf.info(source)
            if info.samplerate != 16000 or info.channels != 1 or not 3 <= info.duration <= 30:
                raise ValueError('invalid voice recording format')
            audio, _ = sf.read(source, dtype='float32')
        else:
            audio = np.frombuffer(base64.b64decode(request['samples'], validate=True), dtype='<f4').copy()
        if audio.size < 1 or audio.size > 16000 * (30 if command == 'transcribe_voice' else 6) or not np.isfinite(audio).all():
            raise ValueError('invalid PCM')
        language = request.get('language', 'ko')
        qwen = MODEL_KEY in ('asr06', 'asr17')
        nemotron = MODEL_KEY == 'nemotron'
        languages = LANGUAGES['nemotron' if nemotron else ('qwenASR' if qwen else 'whisper')]
        if language != 'auto' and (language not in languages or (language == 'yue' and MODEL_KEY in ('base', 'small'))):
            raise ValueError('invalid language')
        with contextlib.redirect_stdout(sys.stderr):
            if nemotron:
                result = MODEL.generate(mx.array(audio), language=language, chunk_duration=None,
                    att_context_size=[56, 3], verbose=False)
            elif qwen:
                result = MODEL.generate(audio, language=None if language == 'auto' else languages[language],
                    max_tokens=256, verbose=False, temperature=0.0)
            else:
                result = MODEL.generate(audio, language=None if language == 'auto' else language,
                    verbose=None, temperature=0.0, condition_on_previous_text=False, word_timestamps=False)
        if nemotron:
            segments = caption_segments([{'text': s.text, 'start': s.start, 'end': s.end} for s in result.sentences], audio.size / 16000)
        else:
            segments = caption_segments(result.segments, audio.size / 16000)
        return {'ok': True, 'segments': segments, 'seconds': time.monotonic() - started,
                'activeMemoryMB': mx.get_active_memory() / 1_048_576}
    if command == 'tts' and CATALOG[MODEL_KEY]['kind'] == 'tts':
        text = request['text'].strip()
        if not text or len(text) > 500:
            raise ValueError('invalid text')
        language_code = request.get('language', 'ko')
        language = LANGUAGES['supertonic3' if MODEL_KEY == 'supertonic3' else ('chatter' if MODEL_KEY == 'chatterV3' else ('vox' if MODEL_KEY == 'vox' else 'qwenTTS'))][language_code]
        prompt = reference_prompt(request) if MODEL_KEY in ('qwen06', 'qwen17') else {}
        if MODEL_KEY not in ('qwen06', 'qwen17') and ('referenceAudio' in request or 'referenceText' in request):
            raise ValueError('voice cloning is unavailable for this model')
        with contextlib.redirect_stdout(sys.stderr):
            if MODEL_KEY == 'supertonic3':
                from types import SimpleNamespace
                style = MODEL.get_voice_style(request.get('voice', 'F1'))
                wav, duration = MODEL.synthesize(text, voice_style=style, lang=language_code)
                wav = np.asarray(wav).reshape(-1)[:int(float(np.asarray(duration).reshape(-1)[0]) * MODEL.sample_rate)]
                results = [SimpleNamespace(audio=wav, sample_rate=MODEL.sample_rate, token_count=0)]
            elif MODEL_KEY == 'chatterV3':
                results = list(MODEL.generate(text=text, lang_code=language_code, max_tokens=1500, verbose=False))
            elif MODEL_KEY == 'vox':
                results = list(MODEL.generate(text=text, instruct=f'A clear native {language.title()} speaker.',
                    max_tokens=1500, inference_timesteps=7))
            elif MODEL_KEY in ('qwen06Custom', 'qwen17Custom'):
                voice = request.get('voice', 'Sohee')
                if voice.lower() not in [speaker.lower() for speaker in MODEL.get_supported_speakers()]:
                    raise ValueError('unsupported voice')
                results = list(MODEL.generate_custom_voice(text=text, speaker=voice, language=language,
                    max_tokens=1500, temperature=0.7, verbose=False))
            else:
                results = list(MODEL.generate(text=text, lang_code=language.lower(), voice=None,
                    max_tokens=1500, temperature=0.7, verbose=False, **prompt))
        if not results or any(r.token_count >= 1500 for r in results):
            raise ValueError('speech generation incomplete')
        audio = np.concatenate([np.asarray(r.audio, dtype=np.float32).reshape(-1) for r in results])
        if not audio.size or not np.isfinite(audio).all():
            raise ValueError('invalid generated audio')
        output = Path(request['output'])
        temporary_root = Path(tempfile.gettempdir()).resolve()
        if not output.resolve().is_relative_to(temporary_root) or not output.parent.name.startswith('STTS-'):
            raise ValueError('invalid output location')
        try:
            with output.open('xb') as handle, wave.open(handle, 'wb') as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(results[0].sample_rate)
                wav.writeframes((np.clip(audio, -1, 1) * 32767).astype('<i2').tobytes())
        except Exception:
            output.unlink(missing_ok=True)
            raise
        return {'ok': True, 'seconds': time.monotonic() - started, 'audioSeconds': audio.size / results[0].sample_rate,
                'activeMemoryMB': mx.get_active_memory() / 1_048_576}
    raise ValueError('invalid operation')


def read_requests(fd=0):
    pending = bytearray()
    while True:
        try:
            chunk = os.read(fd, 65536)
        except BlockingIOError:
            select.select([fd], [], [])
            continue
        if not chunk:
            if pending.strip():
                raise ValueError('incomplete request')
            return
        pending.extend(chunk)
        while b'\n' in pending:
            line, _, remaining = pending.partition(b'\n')
            pending = bytearray(remaining)
            if len(line) > LIMIT:
                raise ValueError('request too large')
            if line.strip():
                yield line
        if len(pending) > LIMIT:
            raise ValueError('request too large')


def main():
    if '--self-check' in sys.argv:
        import mlx.core as mx
        import mlx_audio
        emit({'ok': True, 'mlx': mx.__version__, 'audio': mlx_audio.__version__})
        return
    for raw in read_requests():
        try:
            emit(handle(json.loads(raw)))
        except Exception as error:
            if '--debug' in sys.argv:
                import traceback
                traceback.print_exc(file=sys.stderr)
            else:
                print(type(error).__name__, file=sys.stderr)
            emit({'ok': False, 'error': 'MLX 처리에 실패했습니다. 모델을 다시 준비하거나 사양을 확인해 주세요.'})


if __name__ == '__main__':
    # Frozen multiprocessing resource trackers must not enter our stdin server.
    import multiprocessing
    multiprocessing.freeze_support()
    main()
