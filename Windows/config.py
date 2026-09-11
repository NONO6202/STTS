"""Shared product choices and Windows-specific preference storage."""
import copy
import json
import os
from pathlib import Path
import sys

RESOURCE_ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
CONTRACT = json.loads((RESOURCE_ROOT / 'Shared/app.json').read_text(encoding='utf-8'))
VERSION = CONTRACT['version']
DEFAULTS = copy.deepcopy(CONTRACT['defaults'])
DEFAULTS.update(composer_key={'keycode': 32, 'modifiers': 3, 'key': 'Space'}, stt_key='S')
TTS_MODELS = {tier['title']: tier['model'] for tier in CONTRACT['tts_tiers']}
STT_MODELS = {tier['title']: tier['model'] for tier in CONTRACT['stt_tiers']}
SPEECH_LANGUAGES = json.loads((RESOURCE_ROOT / ('speech_languages.json' if hasattr(sys, '_MEIPASS') else 'Support/speech_languages.json')).read_text(encoding='utf-8'))


def data_directory():
    return Path(os.environ.get('STTS_DATA_DIR', str(Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'STTS')))


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def voice_ready(profile, folder):
    return bool(profile['name'].strip() and 1 <= len(profile['transcript'].strip()) <= CONTRACT['limits']['transcript']
                and (folder / (profile['id'] + '.wav')).is_file())
