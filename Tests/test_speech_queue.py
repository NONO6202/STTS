import sys
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'Windows'))
import app as module

class SpeechQueueTests(unittest.TestCase):
    def setUp(self):
        self.app = a = module.App.__new__(module.App)
        a.config = dict(module.DEFAULTS); a.config['language'] = 'en'
        a.tts_enabled = Mock(isChecked=lambda: True)
        a.tts_busy = True; a.voice_busy = False; a.tts_queue = []
        a.soundboard = Mock(clip_for_input=lambda text: None)
        a.profiles = []; a.model_root = a.voice_root = Path('/unused')
        a.live_microphone = types.SimpleNamespace(stream=None)
        a.status = Mock(); a.update_busy = Mock(); a.hide_composer = Mock()
        a.report = Mock(); a.post = lambda fn, *args: fn(*args)
        a.tts_worker = Mock(); a.tts_worker.request.return_value = {'audio': '', 'rate': 24000}
        a.audio_stop = threading.Event(); a.closing = False
        self.work = []
        self.thread_patch = patch.object(module.threading, 'Thread', side_effect=lambda **kw: types.SimpleNamespace(start=lambda: self.work.append(kw['target'])))
        self.thread_patch.start(); self.addCleanup(self.thread_patch.stop)
        self.audio = types.SimpleNamespace(cable_output=Mock(), play_cable=Mock(return_value=None))
        p = patch.dict(sys.modules, {'audio': self.audio}); p.start(); self.addCleanup(p.stop)
        p = patch.object(module.QTimer, 'singleShot'); p.start(); self.addCleanup(p.stop)

    def submit(self, text):
        field = Mock(preedit=False); field.text.return_value = text
        self.app.submit(field)
        return field

    def test_fifo_drains_after_completion_without_resetting_active_audio(self):
        a = self.app; first = a.audio_stop
        for text in ['one', 'two', 'three']: self.submit(text).clear.assert_called_once()
        self.audio.cable_output.assert_not_called()
        self.assertIs(a.audio_stop, first)
        self.assertEqual(len(a.tts_queue), 3)
        a.finish_tts(first, '')
        while self.work: self.work.pop(0)()
        self.assertEqual([c.args[0]['text'] for c in a.tts_worker.request.call_args_list], ['one', 'two', 'three'])
        self.assertFalse(a.tts_busy); self.assertEqual(a.tts_queue, [])
        self.assertEqual(self.audio.play_cable.call_count, 3)

    def test_cancel_and_late_completion_never_start_queued_work(self):
        a = self.app; old = a.audio_stop
        self.submit('pending'); a.make_tts_worker = Mock(return_value=Mock())
        a.cancel_tts(); a.finish_tts(old, '')
        self.assertTrue(old.is_set()); self.assertEqual(a.tts_queue, [])
        self.assertEqual(self.work, [])

    def test_failure_clears_queue_and_preserves_error(self):
        a = self.app; self.submit('pending')
        a.finish_tts(a.audio_stop, 'synthesis failed', True)
        self.assertEqual(a.tts_queue, []); self.assertEqual(self.work, [])
        a.status.setText.assert_called_with('synthesis failed')

    def test_invalid_input_does_not_enter_queue_or_clear_draft(self):
        for text in ['', ' ' * 3, 'a' * 501]: self.submit(text).clear.assert_not_called()
        self.assertEqual(self.app.tts_queue, [])

    def test_saved_settings_take_priority_over_new_defaults(self):
        self.assertTrue(module.DEFAULTS['keep_draft'])
        self.assertEqual(module.DEFAULTS['composer_key'], {'keycode': 192, 'modifiers': 0, 'key': '`'})

if __name__ == '__main__': unittest.main()
