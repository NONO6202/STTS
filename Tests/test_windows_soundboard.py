import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).parents[1] / 'Windows'))
from soundboard import SoundboardLibrary


class SoundboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.library = SoundboardLibrary(self.root / 'Soundboard')

    def test_inputs_resolve_whole_names_and_reject_ambiguous_names(self):
        import unicodedata
        named = {'id': 'named', 'name': '박수 소리'}
        self.library.clips = [named, {'id': 'one', 'name': '중복'}, {'id': 'two', 'name': '중복'}]
        self.assertIs(self.library.clip_for_input(' \n박수 소리 '), named)
        self.assertIs(self.library.clip_for_input(unicodedata.normalize('NFD', '박수 소리')), named)
        self.assertIsNone(self.library.clip_for_input('@박수 소리'))
        self.assertIsNone(self.library.clip_for_input('이메일 user@example.com'))
        for text in ['', '없는이름', '박수', '박수 소리 들어봐']:
            self.assertIsNone(self.library.clip_for_input(text))
        with self.assertRaises(ValueError): self.library.clip_for_input('중복')

    def test_name_submission_plays_the_file_and_preserves_input_on_failure(self):
        spec = importlib.util.spec_from_file_location('soundboard_command_app', Path(__file__).parents[1] / 'Windows/app.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        app = module.App.__new__(module.App)
        app.tts_enabled = Mock(isChecked=lambda: True)
        app.tts_busy = app.voice_busy = False
        app.status = Mock(); app.status.text.return_value = 'playback error'
        app.hide_composer = Mock(); app.update_busy = Mock(); app.post = Mock(); app.tts_worker = Mock()
        app.config = {'volume': .3, 'voice_monitoring': True}
        app.soundboard = self.library
        clip = self.library.import_samples('박수 소리', np.full(2400, .1), 24000)
        audio = types.SimpleNamespace(cable_output=Mock(), play_cable=Mock(return_value=None))
        field = Mock(preedit=False); field.text.return_value = ' 박수 소리 '; field.height.return_value = 24
        field.mapToGlobal.return_value = module.QPoint(10, 40)
        def immediate_thread(*, target, **kwargs): return types.SimpleNamespace(start=target)
        with patch.dict(sys.modules, {'audio': audio}), patch.object(module.threading, 'Thread', side_effect=immediate_thread), patch.object(module.QToolTip, 'showText'):
            app.submit(field)
            self.assertEqual(app.playing_sound, clip['id'])
            audio.play_cable.assert_called_once()
            app.tts_worker.request.assert_not_called()
            field.clear.assert_called_once(); app.hide_composer.assert_called_once()
            for duplicate in (False, True):
                if duplicate: self.library.clips.append(dict(clip, id='duplicate'))
                app.tts_busy = False; field.reset_mock(); app.hide_composer.reset_mock(); audio.play_cable.reset_mock()
                field.text.return_value = '박수 소리'; field.height.return_value = 24
                audio.cable_output.side_effect = RuntimeError('no virtual microphone') if not duplicate else None
                app.submit(field)
                field.clear.assert_not_called(); app.hide_composer.assert_not_called(); audio.play_cable.assert_not_called()
                app.tts_worker.request.assert_not_called()

    def test_import_reload_and_delete_preserve_other_files(self):
        original = self.root / 'source.wav'
        samples = np.full(2400, .1, dtype='float32')
        sf.write(original, samples, 24000)
        saved = original.read_bytes()
        with self.assertRaises(ValueError): self.library.import_samples('effect', samples, 24000, [' effect '])
        self.assertFalse(self.library.folder.exists())
        clip = self.library.import_samples('effect', samples, 24000)
        with self.assertRaises(ValueError): self.library.import_samples(' effect ', samples, 24000)
        self.assertEqual(len(list(self.library.folder.glob('*.wav'))), 1)
        self.assertEqual(clip['duration'], .1)
        self.assertEqual(SoundboardLibrary(self.library.folder).clips, [clip])
        restored, rate = sf.read(self.library.audio_path(clip))
        self.assertEqual(rate, 24000)
        np.testing.assert_allclose(restored, samples, atol=1 / 32768)
        with self.assertRaises(ValueError):
            self.library.import_samples('bad', np.array([float('nan')]), 24000)
        self.assertEqual(self.library.clips, [clip])
        self.library.remove(clip)
        self.assertEqual(SoundboardLibrary(self.library.folder).clips, [])
        self.assertFalse(self.library.audio_path(clip).exists())
        self.assertEqual(original.read_bytes(), saved)

    def test_invalid_manifest_cannot_overwrite_the_saved_library(self):
        self.library.folder.mkdir()
        data = json.dumps([{'id': 'a' * 32, 'file': '../source.wav'}])
        self.library.manifest.write_text(data)
        library = SoundboardLibrary(self.library.folder)
        self.assertIsNotNone(library.load_error)
        with self.assertRaises(ValueError):
            library.import_samples('effect', np.ones(2400), 24000)
        self.assertEqual(library.manifest.read_text(), data)

    def test_malformed_metadata_is_rejected_without_overwriting_manifest(self):
        self.library.folder.mkdir()
        valid = {'id': 'a' * 32, 'file': 'a' * 32 + '.wav', 'name': '효과음', 'duration': 1}
        for bad in ({}, [dict(valid, name=123)], [dict(valid, duration=-1)], [dict(valid, duration=float('inf'))], [dict(valid, duration='1')], [dict(valid, duration=2 ** 2000)], [dict(valid, id=123)], [valid, valid], [valid, dict(valid, id=valid['id'].upper())]):
            with self.subTest(value=bad):
                data = json.dumps(bad); self.library.manifest.write_text(data)
                library = SoundboardLibrary(self.library.folder)
                self.assertIsNotNone(library.load_error)
                self.assertEqual(library.clips, [])
                self.assertEqual(self.library.manifest.read_text(), data)

    def test_sound_decode_accepts_short_effects_without_relaxing_voice_clone_limits(self):
        import base64
        spec = importlib.util.spec_from_file_location('soundboard_worker', Path(__file__).parents[1] / 'Windows/worker.py')
        worker = importlib.util.module_from_spec(spec); spec.loader.exec_module(worker)
        samples = np.full(12000, .1, dtype='float32')
        with patch.object(worker, 'decode_file', return_value=samples):
            result = worker.handle_request({'action': 'decode_sound', 'path': 'effect.wav'})
            self.assertEqual(len(base64.b64decode(result['audio'])), samples.nbytes)
            with self.assertRaises(ValueError):
                worker.handle_request({'action': 'decode', 'path': 'voice.wav'})

    def test_playback_uses_the_virtual_microphone_and_never_falls_back(self):
        spec = importlib.util.spec_from_file_location('soundboard_app', Path(__file__).parents[1] / 'Windows/app.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        app = module.App.__new__(module.App)
        app.tts_enabled = Mock(isChecked=lambda: True)
        app.tts_busy = app.voice_busy = False
        app.status = Mock(); app.update_busy = Mock(); app.post = Mock()
        app.config = {'volume': .3, 'voice_monitoring': True}
        app.soundboard = self.library
        clip = self.library.import_samples('effect', np.full(2400, .1), 24000)
        audio = types.SimpleNamespace(cable_output=Mock(), play_cable=Mock(return_value=None))
        def immediate_thread(*, target, **kwargs): return types.SimpleNamespace(start=target)
        with patch.dict(sys.modules, {'audio': audio}), patch.object(module.threading, 'Thread', side_effect=immediate_thread):
            app.play_sound(clip)
            audio.cable_output.assert_called_once_with(refresh=True)
            args = audio.play_cable.call_args
            self.assertEqual(args.args[1], 24000)
            self.assertEqual(args.args[2](), .3)
            self.assertIs(args.args[3], app.audio_stop)
            self.assertTrue(args.kwargs['monitor'])
            app.tts_busy = False; audio.play_cable.reset_mock()
            audio.cable_output.side_effect = RuntimeError('no virtual microphone')
            app.play_sound(clip)
            audio.play_cable.assert_not_called()
            app.status.setText.assert_called_with('no virtual microphone')
