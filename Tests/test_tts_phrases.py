import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

# These logic checks do not need a Windows desktop.
sys.path.insert(0, str(Path(__file__).parents[1] / 'Windows'))
spec = importlib.util.spec_from_file_location('stts_windows', Path(__file__).parents[1] / 'Windows/app.py')
app_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app_module)


class TTSPhraseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        data = patch.object(app_module, 'DATA', self.root)
        data.start(); self.addCleanup(data.stop)
        self.app = app_module.App.__new__(app_module.App)
        self.app.config = dict(app_module.DEFAULTS)

    def test_save_rename_delete_and_reload_preserve_unrelated_settings(self):
        app = self.app
        app.save_tts_phrase(' 안녕 ', ' 안녕하세요 ')
        app.save_tts_phrase('감사', '감사합니다')
        with self.assertRaises(ValueError): app.save_tts_phrase('안녕', '덮어쓰기')
        with self.assertRaises(ValueError): app.save_tts_phrase('감사', '덮어쓰기', original='안녕')
        for shortcut, phrase in [(' ', '내용'), ('입력', '\n'), ('가' * 501, '내용'), ('입력', '가' * 501)]:
            with self.assertRaises(ValueError): app.save_tts_phrase(shortcut, phrase, original='안녕')
        self.assertEqual(app.config['tts_phrases']['안녕'], '안녕하세요')
        app.save_tts_phrase(' 인사 ', ' 만나서 반갑습니다 ', original='안녕')
        app.config = json.loads((self.root / 'settings.json').read_text(encoding='utf-8'))
        self.assertEqual(app.config['tts_phrases'], {'인사': '만나서 반갑습니다', '감사': '감사합니다'})
        self.assertEqual(app.config['volume'], app_module.DEFAULTS['volume'])
        app.delete_tts_phrase('인사')
        self.assertEqual(json.loads((self.root / 'settings.json').read_text(encoding='utf-8'))['tts_phrases'], {'감사': '감사합니다'})

    def test_submission_sends_one_expansion_to_every_tts_backend(self):
        app = self.app
        app.save_tts_phrase('안녕', '안녕하세요')
        app.save_tts_phrase('안녕하세요', '반갑습니다')
        app.tts_enabled = Mock(isChecked=lambda: True)
        app.voice_busy = False
        app.status = Mock()
        app.profiles = []
        app.model_root, app.voice_root = self.root / 'Models', self.root / 'Voice'
        app.hide_composer = Mock(); app.update_busy = Mock(); app.report = Mock(); app.post = Mock()
        app.tts_worker = Mock()
        app.tts_worker.request.return_value = {'audio': '', 'rate': 24000}
        audio = types.SimpleNamespace(cable_output=Mock(), play_cable=Mock())
        def immediate_thread(*, target, **kwargs):
            return types.SimpleNamespace(start=target)
        with patch.dict(sys.modules, {'audio': audio}), patch.object(app_module.threading, 'Thread', side_effect=immediate_thread):
            for tier in app_module.TTS_MODELS:
                app.config['tts'] = tier
                for text, expected in [(' 안녕\n', '안녕하세요'), ('안녕 친구야', '안녕 친구야'), ('안녕!', '안녕!')]:
                    app.tts_busy = False
                    widget = Mock(); widget.preedit = False; widget.text.return_value = text
                    app.submit(widget)
                    audio.cable_output.assert_called_with(refresh=True)
                    self.assertEqual(app.tts_worker.request.call_args.args[0]['text'], expected)
                    widget.clear.assert_called_once_with()

    def test_failed_hotkey_registration_preserves_the_previous_saved_setting(self):
        app = self.app
        previous = app.config['composer_key']
        app.hotkeys = Mock(); app.status = Mock(); app.recording_key = None
        app.shortcut_buttons = {'composer_key': Mock()}
        app.register_hotkeys = Mock(side_effect=[RuntimeError('already registered'), None])
        app.save = Mock()
        candidate = {'keycode': 89, 'modifiers': 3, 'key': 'Y'}
        winutil = types.SimpleNamespace(shortcut_label=lambda value: str(value),
            shortcut_data=lambda value: {'keycode': ord(value), 'modifiers': 3, 'key': value} if isinstance(value, str) else value)
        with patch.dict(sys.modules, {'winutil': winutil}):
            app.record_shortcut('composer_key')
            app.finish_shortcut(candidate)
        self.assertEqual(app.config['composer_key'], previous)
        app.save.assert_not_called()
        self.assertIsNone(app.recording_key)
        self.assertEqual(app.register_hotkeys.call_count, 2)

    def test_missing_playback_endpoint_keeps_text_and_explains_failure_at_the_input(self):
        app = self.app
        app.tts_enabled = Mock(isChecked=lambda: True); app.tts_busy = app.voice_busy = False
        app.status = Mock(); app.hide_composer = Mock(); app.tts_worker = Mock()
        field = Mock(preedit=False); field.text.return_value = '안녕하세요'; field.height.return_value = 24
        field.mapToGlobal.return_value = app_module.QPoint(10, 40)
        error = RuntimeError('CABLE Input을 찾지 못했습니다.')
        with patch.dict(sys.modules, {'audio': types.SimpleNamespace(cable_output=Mock(side_effect=error))}), patch.object(app_module.QToolTip, 'showText') as tooltip:
            app.submit(field)
            self.assertEqual(tooltip.call_args.args[1], str(error))
            self.assertIs(tooltip.call_args.args[2], field)
        field.clear.assert_not_called(); app.hide_composer.assert_not_called()
        app.tts_worker.request.assert_not_called()

    def test_idle_release_does_not_stop_a_new_request_or_replacement_worker(self):
        app = self.app
        app.status = Mock(); app.update_busy = Mock(); app.report = Mock()
        app.backends = {}; app.closing = False; app.job = object()
        token = app.audio_stop = object()
        previous = app.tts_worker = Mock()
        with patch.object(app_module.QTimer, 'singleShot') as schedule:
            app.finish_tts(token, '')
        self.assertEqual(schedule.call_args.args[0], 30000)
        release = schedule.call_args.args[1]
        app.tts_busy = True
        release(); previous.stop.assert_not_called()
        app.tts_busy = False
        replacement = Mock()
        with patch.dict(sys.modules, {'audio': types.SimpleNamespace(Worker=Mock(return_value=replacement))}):
            release(); release()
        previous.stop.assert_called_once()
        self.assertIs(app.tts_worker, replacement)
        replacement.stop.assert_not_called()


class ComposerRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = app_module.QApplication.instance() or app_module.QApplication([])

    def test_background_color_and_opacity_render_without_fading_text(self):
        app = app_module.App.__new__(app_module.App)
        app.config = dict(app_module.DEFAULTS); app.caption = None
        window = app.composer = app_module.ComposerWindow(); window.resize(480, 44)
        self.addCleanup(window.close)
        layout = app_module.QHBoxLayout(window); layout.setContentsMargins(12, 10, 12, 10)
        field = app_module.ComposerEdit(); field.setText('HHHH'); layout.addWidget(field)
        for background, alpha in [('#1464c8', .6), ('#cc4422', .3)]:
            app.config.update(window_bg=background, window_alpha=alpha, window_color='#ffffff')
            app.refresh_surfaces(); window.show(); self.qt.processEvents()
            pixels = window.grab().toImage(); ratio = pixels.devicePixelRatio()
            actual = pixels.pixelColor(round(240 * ratio), round(5 * ratio))
            expected = app_module.QColor(background); expected.setAlphaF(alpha)
            for channel, wanted in zip(actual.getRgb(), expected.getRgb()):
                self.assertLessEqual(abs(channel - wanted), 2)
            self.assertEqual(pixels.pixelColor(0, 0).alpha(), 0)
            self.assertGreaterEqual(max(pixels.pixelColor(x, y).alpha()
                for x in range(round(12 * ratio), round(70 * ratio))
                for y in range(round(10 * ratio), round(34 * ratio))), 250)
            self.assertEqual(field.text(), 'HHHH')


if __name__ == '__main__':
    unittest.main()
