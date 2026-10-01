import json
from pathlib import Path
import re
import sys
import unittest
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'Windows'))
import localization as l10n


class LocalizationTests(unittest.TestCase):
    def test_ui_language_and_fallback(self):
        for requested, expected in [('ko-KR', 'ko'), ('en-GB', 'en'), ('ja-JP', 'ja'), ('zh-TW', 'zh-Hans'), ('es-MX', 'es'), ('fr-CA', 'fr'), ('de-DE', 'de'), ('pt_BR', 'pt'), ('ar-SA', 'en')]:
            self.assertEqual(l10n.ui_language([requested]), expected)
        self.assertEqual(l10n.ui_language(['ar-SA', 'fr-FR']), 'fr')

    def test_speech_uses_os_language_independently_of_ui_support(self):
        cases = [(['ja-JP'], ['en', 'ja'], 'ja'), (['zh-TW'], ['zh-CN', 'zh-TW', 'en'], 'zh-TW'),
                 (['pt-BR'], ['pt', 'en'], 'pt'), (['ar-SA'], ['ar', 'en'], 'ar'),
                 (['ja-JP'], ['en', 'ko'], 'en'), (['de-DE'], ['ko'], 'ko'), (['zh-Hant-HK'], ['zh', 'zh-CN', 'zh-TW'], 'zh-TW'), (['zh-Hans'], ['zh', 'zh-CN', 'en'], 'zh-CN')]
        for preferred, available, expected in cases:
            self.assertEqual(l10n.speech_language(preferred, available), expected)

    def test_all_eight_catalogs_and_placeholders(self):
        reference = l10n.CATALOG['strings']['en']
        for language in l10n.SUPPORTED:
            with patch.object(l10n, 'LANGUAGE', language):
                if language != 'ko':
                    self.assertEqual(set(l10n.CATALOG['strings'][language]), set(reference))
                    for key, value in l10n.CATALOG['strings'][language].items():
                        self.assertTrue(value.strip(), (language, key))
                        self.assertEqual(sorted(re.findall(r'\{\d+\}', key)), sorted(re.findall(r'\{\d+\}', value)), (language, key))
                        self.assertFalse(re.search('[가-힣]', value), (language, key))
                for key in ['마이크 함께 보내기', '설정', '시스템 언어', '로봇', '에코', '대본 자동 입력']:
                    self.assertTrue(l10n.tr(key))

    def test_dynamic_messages_preserve_user_arguments(self):
        with patch.object(l10n, 'LANGUAGE', 'en'):
            self.assertEqual(l10n.message('내 파일 재생 중…'), 'Playing 내 파일…')
            self.assertEqual(l10n.message('내 원문 그대로'), '내 원문 그대로')
            self.assertEqual(l10n.tr('시스템 언어 · {0}', '日本語'), 'System language · 日本語')
            self.assertNotRegex(l10n.language_name('ko'), '[가-힣]')


@unittest.skipUnless(sys.platform == 'win32', 'Windows UI integration')
class WindowsLocalizationFlowTests(unittest.TestCase):
    def test_localized_ui_saved_choices_and_tts_request(self):
        from PySide6.QtWidgets import QApplication, QLabel, QAbstractButton, QComboBox
        import app as module
        import audio
        from unittest.mock import Mock
        from widgets import MainWindow
        import os
        qt = QApplication.instance() or QApplication([])
        qt.setStyle('Fusion'); qt.setQuitOnLastWindowClosed(False)
        for language in l10n.SUPPORTED:
            with self.subTest(language=language), tempfile.TemporaryDirectory(prefix='STTS-locale-') as folder, patch.object(module, 'DATA', Path(folder)), patch.object(l10n, 'LANGUAGE', language), patch.dict(os.environ, {'STTS_UI_LANGUAGE': language}):
                root = MainWindow(); app = module.App(root, smoke=True); root.show(); qt.processEvents()
                try:
                    self.assertTrue(app.config['language_follows_system'])
                    self.assertEqual(app.config['language'], l10n.speech_language([language], list(module.SPEECH_LANGUAGES['gtts'])))
                    self.assertEqual(app.language_box.currentData(), 'system')
                    for index in range(4):
                        app.select_tab(index); app.tools.dismiss(animated=False); qt.processEvents()
                        self.assertEqual(app.tab_buttons.button(index).text(), l10n.tr(module.CONTRACT['tabs'][index]))
                        for widget in root.findChildren(QLabel) + root.findChildren(QAbstractButton) + root.findChildren(QComboBox):
                            if not widget.isVisible(): continue
                            value = widget.currentText() if isinstance(widget, QComboBox) else widget.text()
                            if language != 'ko': self.assertNotRegex(value, '[가-힣]', (language, index, value))
                        snapshot = os.environ.get('STTS_L10N_SNAPSHOT_DIR')
                        if snapshot and index in (0, 1):
                            Path(snapshot).mkdir(parents=True, exist_ok=True)
                            self.assertTrue(root.grab().save(str(Path(snapshot) / f'{language}-{index}.png')))
                    app.boxes['microphone_filter'].setCurrentIndex(app.boxes['microphone_filter'].findData('전화'))
                    self.assertEqual(app.live_microphone.effect_settings[1], '전화')
                    app.boxes['close'].setCurrentIndex(app.boxes['close'].findData('백그라운드 실행')) if 'close' in app.boxes else None
                    app.language_box.setCurrentIndex(app.language_box.findData('fr'))
                    self.assertFalse(app.config['language_follows_system'])
                    app.refresh_languages(); self.assertEqual(app.config['language'], 'fr')
                    app.tts_worker.request = Mock(side_effect=RuntimeError('end test before audio playback'))
                    app.post = Mock()
                    field = Mock(preedit=False); field.text.return_value = 'User text stays unchanged.'
                    with patch.object(audio, 'cable_output'), patch.object(module.threading, 'Thread') as thread:
                        app.submit(field)
                        thread.call_args.kwargs['target']()
                    payload = app.tts_worker.request.call_args.args[0]
                    self.assertEqual(payload['language'], 'fr')
                    self.assertEqual(payload['text'], 'User text stays unchanged.')
                finally: app.quit()
                restored_root = MainWindow(); restored = module.App(restored_root, smoke=True)
                try:
                    self.assertFalse(restored.config['language_follows_system'])
                    self.assertEqual(restored.config['language'], 'fr')
                    self.assertEqual(restored.config['microphone_filter'], '전화')
                    restored.language_box.setCurrentIndex(restored.language_box.findData('system'))
                    self.assertTrue(restored.config['language_follows_system'])
                finally: restored.quit()


if __name__ == '__main__': unittest.main()
