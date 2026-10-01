"""Owned soundboard recordings; importing and deleting never modify source files."""
import json
from pathlib import Path
import uuid
import unicodedata
from config import write_json


class SoundboardLibrary:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.manifest = self.folder / 'clips.json'
        self.clips = []
        self.load_error = None
        if self.manifest.exists():
            try:
                clips = json.loads(self.manifest.read_text(encoding='utf-8'))
                if not isinstance(clips, list): raise ValueError('사운드보드 파일 목록이 올바르지 않습니다.')
                identifiers = set()
                for clip in clips:
                    if (not isinstance(clip, dict) or not isinstance(clip.get('id'), str)
                            or not isinstance(clip.get('name'), str) or not clip['name'].strip()
                            or type(clip.get('duration')) not in (int, float)
                            or not 0 < clip['duration'] < 2 ** 63
                            or uuid.UUID(clip['id']).hex in identifiers or clip.get('file') != uuid.UUID(clip['id']).hex + '.wav'):
                        raise ValueError('사운드보드 파일 목록이 올바르지 않습니다.')
                    identifiers.add(uuid.UUID(clip['id']).hex)
                self.clips = clips
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.load_error = str(error)

    def audio_path(self, clip):
        return self.folder / clip['file']

    def clip_for_input(self, text):
        name = unicodedata.normalize('NFC', text.strip())
        matches = [clip for clip in self.clips if unicodedata.normalize('NFC', clip['name'].strip()) == name]
        if not matches:
            return None
        if len(matches) != 1:
            raise ValueError('같은 이름의 사운드가 여러 개 있습니다. 사운드보드에서 선택해 주세요.')
        return matches[0]

    def save(self, clips):
        if self.load_error:
            raise ValueError(self.load_error)
        self.folder.mkdir(parents=True, exist_ok=True)
        write_json(self.manifest, clips)

    def import_samples(self, name, samples, rate, phrase_names=()):
        import numpy as np
        import soundfile as sf
        if self.load_error:
            raise ValueError(self.load_error)
        if not len(samples) or rate <= 0 or not np.isfinite(samples).all():
            raise ValueError('재생할 수 있는 음성 파일을 선택해 주세요.')
        name = unicodedata.normalize('NFC', name.strip())
        if not name:
            raise ValueError('사운드 이름이 비어 있습니다.')
        if any(unicodedata.normalize('NFC', value.strip()) == name for value in [*(clip['name'] for clip in self.clips), *phrase_names]):
            raise ValueError('이미 사용 중인 이름입니다. 파일 이름을 바꾼 뒤 추가해 주세요.')
        ident = uuid.uuid4().hex
        clip = {'id': ident, 'name': name, 'file': ident + '.wav', 'duration': len(samples) / rate}
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.audio_path(clip)
        temporary = path.with_suffix('.tmp')
        try:
            sf.write(temporary, samples, rate, subtype='PCM_16', format='WAV')
            temporary.replace(path)
            self.save(self.clips + [clip])
        except Exception:
            path.unlink(missing_ok=True)
            raise
        finally:
            temporary.unlink(missing_ok=True)
        self.clips = self.clips + [clip]
        return clip

    def remove(self, clip):
        if clip not in self.clips:
            return
        remaining = [item for item in self.clips if item['id'] != clip['id']]
        self.save(remaining)
        try:
            self.audio_path(clip).unlink(missing_ok=True)
        except OSError:
            self.save(self.clips)
            raise
        self.clips = remaining
