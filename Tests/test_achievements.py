from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'Windows'))
import achievements as module


class AchievementTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.calls = []
        def run(command, **kwargs):
            self.calls.append(command[command.index('--steam-achievements') + 1:])
            return type('Result', (), {'returncode': self.result})()
        self.result = 0
        patches = [patch.object(module.subprocess, 'run', side_effect=run),
                   patch.object(module.threading, 'Thread', side_effect=lambda target, args, **kw: type('T', (), {'start': lambda self: target(*args)})())]
        for item in patches: item.start(); self.addCleanup(item.stop)

    def test_goals_unlock_once_and_are_reported_to_steam(self):
        tracker = module.Achievements(self.folder, enabled=True)
        tracker.count('tts')
        self.assertEqual(self.calls, [['FIRST_WORDS']])
        for _ in range(99): tracker.count('tts')
        self.assertEqual(self.calls[-1], ['CHATTERBOX'])
        for language in ['ko', 'en', 'en', 'ja']: tracker.include('languages', language)
        self.assertEqual(self.calls[-1], ['POLYGLOT'])
        saved = json.loads((self.folder / 'achievements.json').read_text())
        self.assertEqual(saved['tts'], 100); self.assertEqual(sorted(saved['reported']), ['CHATTERBOX', 'FIRST_WORDS', 'POLYGLOT'])

    def test_unreported_unlocks_retry_when_steam_was_closed(self):
        tracker = module.Achievements(self.folder, enabled=True)
        self.result = 1; tracker.level('phrases', 5)
        self.result = 0; module.Achievements(self.folder, enabled=True).check()
        self.assertEqual(self.calls, [['CATCHPHRASES'], ['CATCHPHRASES']])

    def test_demo_and_disabled_trackers_never_contact_steam(self):
        tracker = module.Achievements(self.folder, enabled=False)
        tracker.count('tts'); tracker.level('night', 1)
        self.assertEqual(self.calls, [])


if __name__ == '__main__': unittest.main()
