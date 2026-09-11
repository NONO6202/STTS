import base64
import importlib.util
from pathlib import Path
import sys
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1] / 'Windows'))
from interaction import completion_candidates
spec = importlib.util.spec_from_file_location('effects_worker', Path(__file__).parents[1] / 'Windows/worker.py')
worker = importlib.util.module_from_spec(spec); spec.loader.exec_module(worker)

class CompletionAudioTests(unittest.TestCase):
    def test_prefix_completion_exact_names_collisions_and_limit(self):
        import unicodedata
        phrases = ['인사', '인사말', 'Hello']; sounds = ['인사', '인사음', '중복', '중복 ']
        expected = [('인사', '단축어'), ('인사말', '단축어'), ('인사음', '사운드')]
        self.assertEqual(completion_candidates('인', phrases, sounds), expected)
        self.assertEqual(completion_candidates(unicodedata.normalize('NFD', '인'), phrases, sounds), expected)
        for text in ['', '인사', '문장 인', '중']: self.assertEqual(completion_candidates(text, phrases, sounds), [])
        self.assertEqual(completion_candidates('he', phrases, sounds), [('Hello', '단축어')])
        self.assertEqual(len(completion_candidates('a', [f'a{i}' for i in range(10)], [])), 5)

    def test_speed_and_pitch_change_independently_and_default_is_unchanged(self):
        rate = 24000
        source = (.1 * np.sin(2 * np.pi * 440 * np.arange(rate * 2) / rate)).astype('<f4')
        def render(pitch=0, speed=1):
            result = worker.audio_reply(source, rate, pitch=pitch, speed=speed)
            return np.frombuffer(base64.b64decode(result['audio']), dtype='<f4')
        np.testing.assert_array_equal(render(), source)
        for pitch, speed in [(0, 2), (12, 1), (-12, .5), (6, 1.5)]:
            result = render(pitch, speed)
            self.assertLessEqual(abs(len(result) - round(len(source) / speed)), 2)
            middle = result[len(result)//4:len(result)*3//4]
            peak = np.argmax(abs(np.fft.rfft(middle * np.hanning(len(middle))))) * rate / len(middle)
            self.assertAlmostEqual(peak, 440 * 2 ** (pitch / 12), delta=12)
            self.assertTrue(np.isfinite(result).all())
        for pitch, speed in [(13, 1), (0, .1), (float('nan'), 1), (0, float('inf'))]:
            with self.assertRaises(ValueError): render(pitch, speed)
