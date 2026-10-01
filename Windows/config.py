"""Shared product choices and Windows-specific preference storage."""
import copy
import json
import os
from pathlib import Path
import sys

RESOURCE_ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
CONTRACT = json.loads((RESOURCE_ROOT / 'Shared/app.json').read_text(encoding='utf-8'))
VERSION = CONTRACT['version']
# Steam demo builds bundle Shared/edition.json; STTS_DEMO=1 previews the demo from source.
# The one-file launcher finds the marker in the runtime's _internal folder beside it.
_EDITIONS = [RESOURCE_ROOT / 'Shared/edition.json', Path(sys.executable).parent / '_internal/Shared/edition.json']
DEMO = os.environ.get('STTS_DEMO') == '1' or any(path.is_file() and json.loads(path.read_text(encoding='utf-8')).get('demo') is True for path in _EDITIONS)
# The demo speaks with the basic and low voices only.
STORE_URL = 'https://store.steampowered.com/app/5360340/'
DEFAULTS = copy.deepcopy(CONTRACT['defaults'])
DEFAULTS.update(composer_key={'keycode': 192, 'modifiers': 0, 'key': '`'}, stt_key='S')
TTS_MODELS = {tier['title']: tier['model'] for tier in CONTRACT['tts_tiers'] if not DEMO or tier['model'] in ('gtts', 'supertonic3')}
STT_MODELS = {tier['title']: tier['model'] for tier in CONTRACT['stt_tiers']}
SPEECH_LANGUAGES = json.loads((RESOURCE_ROOT / ('speech_languages.json' if hasattr(sys, '_MEIPASS') else 'Support/speech_languages.json')).read_text(encoding='utf-8'))


def data_directory():
    # The demo keeps its own settings so it never changes the full version's.
    return Path(os.environ.get('STTS_DATA_DIR', str(Path(os.environ.get('LOCALAPPDATA', Path.home())) / ('STTS Demo' if DEMO else 'STTS'))))


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def voice_ready(profile, folder):
    return bool(profile['name'].strip() and 1 <= len(profile['transcript'].strip()) <= CONTRACT['limits']['transcript']
                and (folder / (profile['id'] + '.wav')).is_file())
