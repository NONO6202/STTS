import importlib.util
from pathlib import Path
import unittest
import tempfile
import fcntl
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('worker', Path(__file__).parents[1] / 'Support/mlx_worker.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)

class ProtocolTests(unittest.TestCase):
    def test_recorded_voice_transcription_accepts_full_clip_without_expanding_live_stt(self):
        import base64
        import numpy as np
        import soundfile as sf
        from types import SimpleNamespace
        from unittest.mock import Mock
        model = Mock()
        model.generate.return_value = SimpleNamespace(segments=[{'text': '녹음한 대본입니다.', 'start': 0, 'end': 8}])
        samples = (np.sin(np.arange(16000 * 8) * .1) * .1).astype('<f4')
        with tempfile.TemporaryDirectory() as root, patch.object(worker, 'MODEL', model), patch.object(worker, 'MODEL_KEY', 'turbo'):
            path = str(Path(root) / 'recording.wav')
            sf.write(path, samples, 16000)
            result = worker.handle_model_request({'command': 'transcribe_voice', 'audioFile': path, 'language': 'auto'})
            self.assertEqual(result['segments'][0]['text'], '녹음한 대본입니다.')
            self.assertEqual(model.generate.call_args.args[0].size, 16000 * 8)
            self.assertIsNone(model.generate.call_args.kwargs['language'])
            with self.assertRaises(ValueError):
                worker.handle_model_request({'command': 'stt', 'samples': base64.b64encode(samples).decode(), 'language': 'auto'})
            sf.write(path, np.zeros(16000 * 31), 16000)
            with self.assertRaises(ValueError):
                worker.handle_model_request({'command': 'transcribe_voice', 'audioFile': path})
            with self.assertRaises(ValueError):
                worker.handle_model_request({'command': 'transcribe_voice', 'audioFile': 'https://example.com/recording.wav'})

    def test_qwen_presets_use_the_chosen_speaker_and_reject_clone_inputs(self):
        import numpy as np
        from types import SimpleNamespace
        from unittest.mock import Mock
        model = Mock()
        model.get_supported_speakers.return_value = ['Sohee', 'Ryan']
        model.generate_custom_voice.return_value = [SimpleNamespace(audio=np.array([.1, -.1]), token_count=2, sample_rate=24000)]
        with tempfile.TemporaryDirectory(prefix='STTS-presets-') as root:
            for key in ['qwen06Custom', 'qwen17Custom']:
                with patch.object(worker, 'MODEL', model), patch.object(worker, 'MODEL_KEY', key):
                    request = {'command': 'tts', 'text': 'hello', 'language': 'en', 'voice': 'Ryan', 'output': str(Path(root) / (key + '.wav'))}
                    self.assertTrue(worker.handle_model_request(request)['ok'])
                    self.assertEqual(model.generate_custom_voice.call_args.kwargs['speaker'], 'Ryan')
                    model.generate.assert_not_called()
                    with self.assertRaises(ValueError):
                        worker.handle_model_request(dict(request, voice='F1'))
                    with self.assertRaises(ValueError):
                        worker.handle_model_request(dict(request, referenceText='hello'))

    def test_reference_audio_is_local_bounded_and_requires_transcript(self):
        import numpy as np
        import soundfile as sf
        self.assertEqual(worker.reference_prompt({}), {})
        with self.assertRaises(ValueError):
            worker.reference_prompt({'referenceAudio': 'https://example.com/voice.wav', 'referenceText': 'hello'})
        with tempfile.TemporaryDirectory() as root:
            path = str(Path(root) / 'voice.wav')
            sf.write(path, np.sin(np.arange(48000) * .1) * .1, 16000)
            self.assertEqual(worker.reference_prompt({'referenceAudio': path, 'referenceText': ' hello '}), {'ref_audio': path, 'ref_text': 'hello'})
            for text in ['', 'x' * 1001, None]:
                with self.assertRaises(ValueError):
                    worker.reference_prompt({'referenceAudio': path, 'referenceText': text})
            for samples in [np.zeros(48000), np.ones(16000) * .1, np.ones(496000) * .1]:
                sf.write(path, samples, 16000)
                with self.assertRaises(ValueError):
                    worker.reference_prompt({'referenceAudio': path, 'referenceText': 'hello'})

    def test_large_prepare_uses_catalog_precision(self):
        with patch.object(worker, 'prepare_model') as prepare:
            result = worker.handle_model_request({'command': 'prepare', 'model': 'large', 'root': '/unused'})
        prepare.assert_called_once_with('large', '/unused')
        self.assertEqual(result, {'ok': True, 'bits': 16})
    def test_model_download_and_load_hold_shared_storage_lock(self):
        with tempfile.TemporaryDirectory() as root:
            def checked(request):
                with open(Path(root) / '.model-access.lock', 'rb') as lock:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return {'ok': True}
            with patch.object(worker, 'handle_model_request', side_effect=checked):
                for command in ('prepare', 'load'):
                    self.assertEqual(worker.handle({'command': command, 'root': root}), {'ok': True})
            with open(Path(root) / '.model-access.lock', 'rb') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    def test_captions_cannot_outlive_the_received_audio(self):
        segments = [{'text': '안녕하세요.', 'start': -0.1, 'end': 4},
                    {'text': '환각', 'start': 10, 'end': 12},
                    {'text': '잘못된 시간', 'start': float('nan'), 'end': 2}]
        self.assertEqual(worker.caption_segments(segments, 3), [{'text': '안녕하세요.', 'start': 0, 'end': 3}])
    def test_punctuation_only_and_high_no_speech_results_are_discarded(self):
        segments = [{'text': '!', 'start': 0, 'end': 1},
                    {'text': '환각', 'start': 1, 'end': 2, 'no_speech_prob': 0.9},
                    {'text': '왼쪽!', 'start': 2, 'end': 3}]
        self.assertEqual(worker.caption_segments(segments, 3), [{'text': '왼쪽!', 'start': 2, 'end': 3}])
    def test_delayed_newline_does_not_create_an_empty_request(self):
        with patch.object(worker.os, 'read', side_effect=[b'{"command":"ping"}', b'\n{"command":', b'"ping"}\n', b'']):
            self.assertEqual(list(worker.read_requests()), [b'{"command":"ping"}', b'{"command":"ping"}'])
    def test_unterminated_input_is_bounded(self):
        with patch.object(worker.os, 'read', return_value=b'x' * (worker.LIMIT + 1)):
            with self.assertRaises(ValueError):
                list(worker.read_requests())
    def test_incomplete_request_is_rejected_at_eof(self):
        with patch.object(worker.os, 'read', side_effect=[b'{"command":', b'']):
            with self.assertRaises(ValueError):
                list(worker.read_requests())

if __name__ == '__main__':
    unittest.main()
