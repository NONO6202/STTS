import contextlib
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import MagicMock, Mock, patch

WINDOWS = Path(__file__).parents[1] / 'Windows'
sys.path.insert(0, str(WINDOWS))
import acceleration
import interaction
spec = importlib.util.spec_from_file_location('windows_worker', WINDOWS / 'worker.py')
worker = importlib.util.module_from_spec(spec); spec.loader.exec_module(worker)


class AccelerationTests(unittest.TestCase):
    def setUp(self):
        worker.MODEL = None; worker.MODEL_KEY = None; worker.CPU_ONLY.clear()
        worker.BACKEND = {'device': 'cpu', 'name': 'CPU'}
        for target, kwargs in [(patch.object(worker, 'prepare_model'), {'return_value': WINDOWS}),
                               (patch.object(worker, 'emit'), {}),
                               (patch.object(acceleration, 'release_cuda'), {})]:
            target.start().configure_mock(**kwargs); self.addCleanup(target.stop)

    def test_cuda_selects_a_working_device_with_the_most_free_memory(self):
        torch = MagicMock()
        torch.cuda.is_available.return_value = True
        torch.cuda.device_count.return_value = 2
        torch.cuda.device.side_effect = lambda index: contextlib.nullcontext()
        torch.cuda.mem_get_info.side_effect = [(2_000, 8_000), (6_000, 8_000)]
        torch.cuda.get_device_name.side_effect = ['GPU A', 'GPU B']
        with patch.dict(sys.modules, {'torch': torch}), patch.object(acceleration.os, 'name', 'posix'):
            self.assertEqual(acceleration.cuda_device(), {'device': 'cuda:1', 'index': 1, 'name': 'GPU B'})
            torch.cuda.is_available.return_value = False
            self.assertIsNone(acceleration.cuda_device())

    def test_whisper_uses_cuda_and_retries_on_cpu_only_for_accelerator_failure(self):
        constructor = Mock(side_effect=[RuntimeError('CUDA out of memory'), Mock()])
        cuda = {'device': 'cuda:1', 'index': 1, 'name': 'GPU B'}
        with patch.object(acceleration, 'cuda_device', return_value=cuda), patch.dict(sys.modules, {'faster_whisper': types.SimpleNamespace(WhisperModel=constructor)}):
            worker.load_model('turbo', '/unused')
            self.assertEqual([call.kwargs['device'] for call in constructor.call_args_list], ['cuda', 'cpu'])
            self.assertEqual(constructor.call_args_list[0].kwargs['device_index'], 1)
            self.assertEqual(worker.BACKEND['device'], 'cpu')
            self.assertIn('turbo', worker.CPU_ONLY)
            constructor.reset_mock(side_effect=True)
            worker.MODEL = None; worker.MODEL_KEY = None; worker.CPU_ONLY.clear()
            constructor.side_effect = ValueError('Invalid model file')
            with self.assertRaises(ValueError): worker.load_model('turbo', '/unused')
            self.assertEqual(constructor.call_count, 1)

    def test_inference_failure_reloads_on_cpu_before_returning_audio_or_text(self):
        gpu = Mock(); gpu.transcribe.side_effect = RuntimeError('CUDA device lost')
        cpu = Mock(); cpu.transcribe.return_value = ([types.SimpleNamespace(text='안녕하세요', no_speech_prob=0, avg_logprob=0)], None)
        constructor = Mock(side_effect=[gpu, cpu])
        import numpy as np, base64
        request = {'action': 'stt', 'model': 'small', 'root': '/unused',
                   'audio': base64.b64encode(np.full(16000, 0.1, dtype='<f4')).decode()}
        with patch.object(acceleration, 'cuda_device', return_value={'device': 'cuda:0', 'index': 0, 'name': 'GPU'}), patch.dict(sys.modules, {'faster_whisper': types.SimpleNamespace(WhisperModel=constructor)}):
            reply = worker.handle(request)
            self.assertEqual(reply['text'], '안녕하세요')
            self.assertEqual(reply['backend']['device'], 'cpu')
            self.assertEqual(constructor.call_count, 2)

    def test_qwen_loads_prequantized_weights_with_device_appropriate_activations(self):
        torch = MagicMock(); model = Mock()
        qwen = types.SimpleNamespace(load=model)
        with patch.dict(sys.modules, {'torch': torch, 'qwen_int8': qwen}), patch.object(acceleration, 'cuda_device', return_value={'device': 'cuda:0', 'index': 0, 'name': 'GPU'}):
            worker.load_model('qwen06Custom', '/unused')
            self.assertEqual(model.call_args.args[1], 'cuda:0')
            self.assertIs(model.call_args.args[2], torch.bfloat16)
            worker.MODEL_KEY = None; worker.CPU_ONLY.add('qwen06Custom')
            worker.load_model('qwen06Custom', '/unused')
            self.assertEqual(model.call_args.args[1], 'cpu')
            self.assertIs(model.call_args.args[2], torch.float32)

    def test_directml_sessions_use_safe_options_and_change_as_a_group(self):
        names = ['dp_ort', 'text_enc_ort', 'vector_est_ort', 'vocoder_ort']
        old = {name: object() for name in names}
        engine = types.SimpleNamespace(model=types.SimpleNamespace(**old))
        ort = MagicMock(); ort.get_available_providers.return_value = ['DmlExecutionProvider', 'CPUExecutionProvider']
        session = Mock(); session.get_providers.return_value = ['DmlExecutionProvider', 'CPUExecutionProvider']
        ort.InferenceSession.side_effect = [session, RuntimeError('DirectML failed')]
        loader = types.SimpleNamespace(DP_ONNX_REL_PATH='dp.onnx', TEXT_ENC_ONNX_REL_PATH='text.onnx', VECTOR_EST_ONNX_REL_PATH='vector.onnx', VOCODER_ONNX_REL_PATH='vocoder.onnx')
        with patch.dict(sys.modules, {'onnxruntime': ort, 'supertonic': types.SimpleNamespace(loader=loader)}):
            with self.assertRaises(RuntimeError): acceleration.enable_directml(engine, WINDOWS, {'index': 2})
            for name in names: self.assertIs(getattr(engine.model, name), old[name])
            self.assertFalse(ort.SessionOptions.return_value.enable_mem_pattern)
            ort.InferenceSession.side_effect = None; ort.InferenceSession.return_value = session
            self.assertTrue(acceleration.enable_directml(engine, WINDOWS, {'index': 2}))
            for name in names: self.assertIs(getattr(engine.model, name), session)
            self.assertEqual(ort.InferenceSession.call_args.kwargs['providers'][0][1], {'device_id': '2'})


class GestureTests(unittest.TestCase):
    def test_motion_needs_reversals_and_respects_sensitivity(self):
        points = [(0, 0, 0), (.04, 35, 0), (.08, 0, 0), (.12, 35, 0)]
        self.assertTrue(interaction.mouse_shaken(points, '보통'))
        self.assertFalse(interaction.mouse_shaken(points, '낮음'))
        self.assertFalse(interaction.mouse_shaken([(i * .04, i * 40, 0) for i in range(6)]))
        self.assertFalse(interaction.mouse_shaken([(i * .04, i % 2, 0) for i in range(6)]))


class CableDeviceTests(unittest.TestCase):
    def test_reenabled_endpoint_is_visible_after_refresh(self):
        import audio
        devices = []
        def reinitialize():
            devices.append({'name': 'CABLE Input(VB-Audio Virtual Cable)',
                            'hostapi': 0, 'max_output_channels': 2})
        with patch.object(audio.sd, 'query_devices', side_effect=lambda: devices), \
             patch.object(audio.sd, 'query_hostapis', return_value=[{'name': 'Windows WASAPI'}]), \
             patch.object(audio.sd, '_terminate') as terminate, \
             patch.object(audio.sd, '_initialize', side_effect=reinitialize):
            with self.assertRaises(RuntimeError): audio.cable_output()
            self.assertEqual(audio.cable_output(refresh=True), 0)
            terminate.assert_called_once()

    def test_existing_cable_is_identified_by_output_direction_and_available_api(self):
        import audio
        apis = [{'name': 'MME'}, {'name': 'Windows WASAPI'}, {'name': 'Windows DirectSound'}]
        def device(name, api, output):
            return {'name': name, 'hostapi': api, 'max_output_channels': output}
        cases = [
            ([device('CABLE Input (VB-Audio Virtual Cable)', 0, 2), device('CABLE Input (VB-Audio Virtual Cable)', 1, 2)], 1),
            ([device('CABLE Output (VB-Audio Virtual Cable)', 1, 0), device('스피커 (VB-Audio Virtual Cable)', 1, 2)], 1),
            ([device('Headphones', 1, 2), device('cable input(VB-Audio Virtual Cable)', 2, 2)], 1),
            ([device('CABLE In 16ch (VB-Audio Virtual Cable)', 1, 16)], 0),
        ]
        for devices, expected in cases:
            with self.subTest(devices=devices), patch.object(audio.sd, 'query_devices', return_value=devices), patch.object(audio.sd, 'query_hostapis', return_value=apis):
                self.assertEqual(audio.cable_output(), expected)
        with patch.object(audio.sd, 'query_devices', return_value=[device('CABLE Output (VB-Audio Virtual Cable)', 1, 0), device('Speakers', 1, 2)]), patch.object(audio.sd, 'query_hostapis', return_value=apis):
            with self.assertRaisesRegex(RuntimeError, 'CABLE Input'): audio.cable_output()


class PlaybackTests(unittest.TestCase):
    def test_volume_changes_apply_during_playback_without_mutating_samples(self):
        import audio
        import numpy as np
        stream = MagicMock(); samples = np.full(4096, .8, dtype='float32')
        with patch.object(audio, 'cable_output', return_value=7), \
             patch.object(audio.sd, 'query_devices', return_value={'default_samplerate': 24000, 'max_output_channels': 2, 'hostapi': 0}), \
             patch.object(audio.sd, 'query_hostapis', return_value={'name': 'Windows WASAPI'}), \
             patch.object(audio.sd, 'WasapiSettings', create=True), \
             patch.object(audio.sd, 'OutputStream', return_value=stream):
            audio.play_cable(samples, 24000, Mock(side_effect=[1., .25]), Mock(is_set=lambda: False))
        chunks = stream.__enter__.return_value.write.call_args_list
        self.assertEqual(len(chunks), 2)
        np.testing.assert_allclose(chunks[0].args[0], .8)
        np.testing.assert_allclose(chunks[1].args[0], .2)
        np.testing.assert_allclose(samples, .8)

    def test_existing_cable_on_directsound_does_not_receive_wasapi_options(self):
        import audio
        import numpy as np
        with patch.object(audio, 'cable_output', return_value=7), \
             patch.object(audio.sd, 'query_devices', return_value={'default_samplerate': 24000, 'max_output_channels': 2, 'hostapi': 0}), \
             patch.object(audio.sd, 'query_hostapis', return_value={'name': 'Windows DirectSound'}), \
             patch.object(audio.sd, 'WasapiSettings', create=True) as wasapi, \
             patch.object(audio.sd, 'OutputStream') as stream:
            audio.play_cable(np.zeros(8, dtype='float32'), 24000, 1., Mock(is_set=lambda: False))
            wasapi.assert_not_called()
            self.assertIsNone(stream.call_args.kwargs['extra_settings'])
            self.assertEqual(stream.call_args.kwargs['device'], 7)


if __name__ == '__main__': unittest.main()
