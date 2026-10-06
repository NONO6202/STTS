import importlib.util
from pathlib import Path
import sys
import unittest
import threading
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1] / 'Windows'))
import audio


class MicrophonePassthroughTests(unittest.TestCase):
    def test_running_streams_with_stalled_processing_expire_after_startup_grace(self):
        mic = audio.MicrophonePassthrough()
        mic.stream = Mock(active=True); mic._input_stream = Mock(active=True)
        mic._capture_progress_at = mic._render_progress_at = 10
        with patch.object(audio.time, 'monotonic', return_value=12.99): self.assertTrue(mic.active)
        with patch.object(audio.time, 'monotonic', return_value=13): self.assertFalse(mic.active)
        for capture_stalls in (True, False):
            mic._capture_progress_at = 10 if capture_stalls else 14
            mic._render_progress_at = 14 if capture_stalls else 10
            with patch.object(audio.time, 'monotonic', return_value=14): self.assertFalse(mic.active)

    def test_silent_frames_keep_capture_and_render_watchdogs_alive(self):
        mic = audio.MicrophonePassthrough()
        mic.stream = Mock(active=True); mic._input_stream = stream = Mock(active=True)
        mic.effects = audio.MicrophoneEffects()
        stopped = mic._stopped
        data = np.zeros((480, 1), dtype='float32')
        output = np.zeros((480, 2), dtype='float32')
        for tick in range(1, 21):
            reads = iter((False, True))
            def read(frames):
                if next(reads): stopped.set()
                return data, False
            with patch.object(audio.time, 'monotonic', return_value=10 + tick / 2):
                stopped.clear()
                stream.read.side_effect = read
                mic._capture(stream, mic.buffer, mic.effects, stopped, 480)
                mic._render(mic.buffer, output)
                self.assertTrue(mic.active)
                self.assertFalse(output.any())

    def test_callbacks_from_old_stream_do_not_refresh_new_stream_watchdog(self):
        mic = audio.MicrophonePassthrough(); old_buffer = Mock()
        mic._capture_progress_at = mic._render_progress_at = 10
        stopped = threading.Event(); reads = iter((False, True))
        stream = Mock()
        def read(frames):
            if next(reads): stopped.set()
            return np.zeros((480, 1), dtype='float32'), False
        stream.read.side_effect = read
        with patch.object(audio.time, 'monotonic', return_value=20):
            mic._render(old_buffer, np.zeros((480, 2), dtype='float32'))
            mic._capture(stream, old_buffer, audio.MicrophoneEffects(), stopped, 480)
        self.assertEqual(mic._capture_progress_at, 10)
        self.assertEqual(mic._render_progress_at, 10)

    def test_filters_feedback_devices_and_duplicate_host_apis(self):
        def device(name, host=0, inputs=2):
            return dict(name=name, hostapi=host, max_input_channels=inputs)
        devices = [device('USB Mic'), device('USB Mic', 1), device('CABLE Output'),
                   device('STTS (VB-Audio Virtual Cable)'), device('Stereo Mix'),
                   device('마이크 (DroidCam Virtual Audio)'), device('Speakers', inputs=0)]
        with patch.object(audio.sd, 'query_devices', return_value=devices), patch.object(audio.sd, 'query_hostapis', return_value=[{'name': 'Windows WASAPI'}, {'name': 'MME'}]):
            self.assertEqual([d['index'] for d in audio.physical_microphones()], [0, 5])

    def test_live_gain_and_nonfinite_volume(self):
        mic = audio.MicrophonePassthrough(); mic.volume = 0.5
        output = np.zeros((3, 2), dtype='float32')
        buffer = Mock()
        buffer.render.side_effect = lambda out, **kwargs: out.fill(0.6)
        mic._render(buffer, output)
        np.testing.assert_allclose(output, 0.3, atol=1e-6)
        for volume in (0, float('nan')):
            mic.volume = volume; mic._render(buffer, output)
            self.assertFalse(output.any())

    def test_capture_worker_downmixes_and_sanitizes_before_buffering(self):
        mic = audio.MicrophonePassthrough(); stopped = threading.Event()
        mic.effects = audio.MicrophoneEffects()
        stream = Mock(); buffer = Mock()
        stream.read.return_value = (np.array([[0.8, 0.4], [-0.4, -0.8], [np.nan, 0]], dtype='float32'), False)
        buffer.append.side_effect = lambda *args, **kwargs: stopped.set()
        mic._capture(stream, buffer, mic.effects, stopped, 3)
        np.testing.assert_allclose(buffer.append.call_args.args[0], [0.6, -0.6, 0], atol=1e-6)
        self.assertFalse(mic._failed)
        stream.read.side_effect = audio.sd.PortAudioError('disconnected')
        stopped.clear(); mic._capture(stream, buffer, mic.effects, stopped, 3)
        self.assertTrue(mic._failed)

    def test_missing_or_ambiguous_selected_device_never_uses_default(self):
        for devices in ([], [{'id': 'Mic', 'index': 1}] * 2):
            with self.subTest(devices=devices), patch.object(audio, 'physical_microphones', return_value=devices), patch.object(audio.sd, 'OutputStream') as stream, patch.object(audio.sd, 'InputStream') as capture, patch.object(audio.threading, 'Thread'):
                mic = audio.MicrophonePassthrough()
                with self.assertRaises(RuntimeError): mic.start('Mic', 1)
                stream.assert_not_called(); capture.assert_not_called(); self.assertFalse(mic.active)

    def test_shared_streams_target_only_cable_and_close_on_start_failure(self):
        mic = audio.MicrophonePassthrough()
        info = {'default_samplerate': 48000, 'max_input_channels': 1, 'max_output_channels': 2, 'hostapi': 0}
        with patch.object(audio, 'physical_microphones', return_value=[{'id': 'Mic', 'index': 4}]), patch.object(audio, 'cable_output', return_value=8), patch.object(audio.sd, 'query_devices', return_value=info), patch.object(audio.sd, 'query_hostapis', return_value={'name': 'Windows WASAPI'}), patch.object(audio.sd, 'WasapiSettings', return_value='shared'), patch.object(audio.sd, 'OutputStream') as stream, patch.object(audio.sd, 'InputStream') as capture, patch.object(audio.threading, 'Thread'):
            mic.start('Mic', 0.8)
            self.assertEqual(capture.call_args.kwargs['device'], 4)
            self.assertEqual(stream.call_args.kwargs['device'], 8)
            self.assertEqual(stream.call_args.kwargs['extra_settings'], 'shared')
            self.assertEqual(stream.call_args.kwargs['latency'], 0.06)
            self.assertEqual(stream.call_args.kwargs['blocksize'], 480)
            self.assertNotIn('callback', capture.call_args.kwargs)
            mic.stop(); mic.stop()
            stream.return_value.abort.assert_called_once(); stream.return_value.close.assert_called_once()
            stream.reset_mock(); stream.return_value.start.side_effect = RuntimeError('permission denied')
            with self.assertRaises(RuntimeError): mic.start('Mic', 1)
            self.assertIsNone(mic.stream); stream.return_value.close.assert_called_once()

    def test_disconnected_device_still_closes_and_can_stop_twice(self):
        mic = audio.MicrophonePassthrough(); stream = Mock(); mic.stream = stream
        stream.abort.side_effect = audio.sd.PortAudioError('device removed')
        stream.close.side_effect = audio.sd.PortAudioError('device removed')
        mic.stop(); mic.stop()
        self.assertFalse(mic.active); stream.close.assert_called_once()

    def test_native_input_rate_is_kept_and_thread_start_failure_closes_both_streams(self):
        mic = audio.MicrophonePassthrough()
        def info(index):
            return {'default_samplerate': 16000 if index == 4 else 48000,
                    'max_input_channels': 1, 'max_output_channels': 2, 'hostapi': 0}
        with patch.object(audio, 'physical_microphones', return_value=[{'id': 'Mic', 'index': 4}]), \
             patch.object(audio, 'cable_output', return_value=8), patch.object(audio.sd, 'query_devices', side_effect=info), \
             patch.object(audio.sd, 'query_hostapis', return_value={'name': 'Windows WASAPI'}), \
             patch.object(audio.sd, 'WasapiSettings'), patch.object(audio.sd, 'InputStream') as capture, \
             patch.object(audio.sd, 'OutputStream') as output, patch.object(audio.threading, 'Thread') as worker:
            worker.return_value.ident = None
            worker.return_value.start.side_effect = RuntimeError('thread unavailable')
            with self.assertRaises(RuntimeError): mic.start('Mic', 1)
            self.assertEqual(capture.call_args.kwargs['samplerate'], 16000)
            self.assertEqual(output.call_args.kwargs['samplerate'], 48000)
            self.assertEqual((mic.buffer.rate, mic.buffer.output_rate), (16000, 48000))
            worker.return_value.join.assert_not_called()
            capture.return_value.close.assert_called_once(); output.return_value.close.assert_called_once()
            self.assertFalse(mic.active)

    def test_stop_unblocks_and_joins_capture_before_closing_streams(self):
        mic = audio.MicrophonePassthrough(); entered = threading.Event(); aborted = threading.Event()
        capture = Mock(); output = Mock()
        def read(frames):
            entered.set()
            if not aborted.wait(1): raise RuntimeError('capture was not aborted')
            raise audio.sd.PortAudioError('stopped')
        capture.read.side_effect = read; capture.abort.side_effect = aborted.set
        mic._input_stream = capture; mic.stream = output
        worker = threading.Thread(target=mic._capture,
            args=(capture, mic.buffer, mic.effects, mic._stopped, 480))
        mic._thread = worker; worker.start()
        self.assertTrue(entered.wait(1))
        mic.stop()
        self.assertFalse(worker.is_alive())
        self.assertFalse(mic._failed)
        capture.close.assert_called_once(); output.close.assert_called_once()

    def test_refresh_does_not_reset_playback_that_is_still_closing(self):
        mic = audio.MicrophonePassthrough()
        with audio._playback_lock, patch.object(audio.sd, '_terminate') as terminate, \
             patch.object(audio.sd, '_initialize') as initialize, \
             patch.object(audio, 'physical_microphones', return_value=[]):
            with self.assertRaises(RuntimeError): mic.start('USB Mic', 1, refresh=True)
        terminate.assert_not_called(); initialize.assert_not_called()

    def test_refresh_resolves_new_input_and_output_indices_before_retry(self):
        mic = audio.MicrophonePassthrough()
        mic.effect_settings = (3, '전화', 0.9)
        def device(name, inputs=0, outputs=0):
            return dict(name=name, hostapi=0, max_input_channels=inputs,
                        max_output_channels=outputs, default_samplerate=48000)
        old = [device('USB Mic', inputs=1), device('CABLE Input', outputs=2)]
        new = [device('Speakers', outputs=2), device('CABLE Input', outputs=2), device('USB Mic', inputs=1)]
        devices = old
        def initialize():
            nonlocal devices
            devices = new
        with patch.object(audio.sd, 'query_devices', side_effect=lambda index=None: devices if index is None else devices[index]), \
             patch.object(audio.sd, 'query_hostapis', side_effect=lambda index=None: [{'name': 'Windows WASAPI'}] if index is None else {'name': 'Windows WASAPI'}), \
             patch.object(audio.sd, 'WasapiSettings'), patch.object(audio.sd, 'OutputStream') as stream, patch.object(audio.sd, 'InputStream') as capture, patch.object(audio.threading, 'Thread'), \
             patch.object(audio.sd, '_terminate') as terminate, patch.object(audio.sd, '_initialize', side_effect=initialize):
            stream.return_value.start.side_effect = [audio.sd.PortAudioError('device disconnected'), None]
            with self.assertRaises(audio.sd.PortAudioError): mic.start('USB Mic', 0.6)
            self.assertIsNone(mic.stream)
            mic.start('USB Mic', 0.6, refresh=True)
            terminate.assert_called_once()
            self.assertEqual(capture.call_args.kwargs['device'], 2)
            self.assertEqual(stream.call_args.kwargs['device'], 1)
            self.assertEqual(mic.effect_settings, (3, '전화', 0.9))
            self.assertEqual(mic.volume, 0.6)
            self.assertTrue(mic.active)
            mic.stop()


class MicrophoneUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('stts_mic_ui', Path(__file__).parents[1] / 'Windows/app.py')
        cls.module = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.module)

    def setUp(self):
        self.app = self.module.App.__new__(self.module.App)
        app = self.app
        app.config = {'tts_enabled': True, 'microphone_volume': 0.7, 'microphone_device': 'Mic', 'microphone_enabled': False}
        app.closing = False; app.microphone_active = False; app.microphone_retry_at = 0.0
        app.tts_busy = app.voice_busy = False; app.capture = None; app.microphone_error = ''; app.tts_queue = []; app.skipping = None
        app.live_microphone = Mock(); app.microphone_toggle = Mock(); app.microphone_timer = Mock()
        app.live_microphone.active = False
        app.microphone_box = Mock(); app.microphone_box.currentData.return_value = 'Mic'
        app.microphone_status = Mock(); app.status = Mock(); app.update_busy = Mock()
        app.save = Mock()

    def test_successful_toggle_persists_preference(self):
        app = self.app
        app.toggle_microphone(True)
        self.assertTrue(app.config['microphone_enabled'])
        app.save.assert_called_once()
        app.toggle_microphone(False)
        self.assertFalse(app.config['microphone_enabled'])

    def test_enable_failure_preserves_toggle_and_retry_timer(self):
        app = self.app; app.live_microphone.start.side_effect = RuntimeError('permission denied')
        app.toggle_microphone(True)
        app.microphone_toggle.setChecked.assert_not_called()
        app.microphone_timer.start.assert_called_once(); app.microphone_timer.stop.assert_not_called()
        app.live_microphone.stop.assert_called_once()
        self.assertTrue(app.config['microphone_enabled']); self.assertFalse(app.microphone_active)

    def test_permission_failure_then_retry_keeps_tts_on_and_clears_error(self):
        app = self.app
        app.live_microphone.start.side_effect = [RuntimeError('permission denied'), None]
        app.toggle_microphone(True)
        self.assertTrue(app.config['tts_enabled'])
        app.status.text.return_value = app.microphone_error
        with patch.object(self.module.time, 'monotonic', return_value=app.microphone_retry_at):
            app.check_live_microphone()
        self.assertTrue(app.config['microphone_enabled'])
        self.assertTrue(app.config['tts_enabled'])
        app.live_microphone.start.assert_called_with('Mic', 0.7, refresh=True)
        app.status.setText.assert_called_with('')
        app.microphone_timer.start.assert_called_once()

    def test_retry_does_not_reset_portaudio_during_other_audio_work(self):
        app = self.app
        for busy in ('tts_busy', 'voice_busy', 'capture'):
            with self.subTest(busy=busy):
                setattr(app, busy, True)
                app.toggle_microphone(True)
                app.live_microphone.start.assert_called_with('Mic', 0.7, refresh=False)
                setattr(app, busy, False)

    def test_success_does_not_clear_another_operation_status(self):
        app = self.app; app.microphone_error = 'previous microphone error'
        app.status.text.return_value = 'TTS in progress'
        app.toggle_microphone(True)
        app.status.setText.assert_not_called()

    def test_master_off_stops_microphone_and_tts(self):
        app = self.app; app.save = Mock(); app.cancel_tts = Mock(); app.hide_composer = Mock()
        app.toggle_tts_changed(False)
        app.microphone_toggle.setChecked.assert_called_once_with(False)
        app.cancel_tts.assert_called_once()

    def test_tts_cancel_leaves_microphone_stream_running(self):
        app = self.app; app.audio_stop = Mock(); app.tts_worker = Mock(); app.make_tts_worker = Mock()
        app.cancel_tts()
        app.live_microphone.stop.assert_not_called()

    def test_refresh_cannot_terminate_active_microphone_stream(self):
        app = self.app; app.tts_busy = app.voice_busy = False; app.capture = None
        app.microphone_toggle.isChecked.return_value = True
        app.microphone_active = True
        with patch.object(audio.sd, '_terminate') as terminate:
            app.refresh_microphones(refresh=True)
        terminate.assert_not_called(); app.status.setText.assert_called_once()

    def test_disconnect_retries_same_device_after_delay_without_changing_preference(self):
        app = self.app; app.toggle_microphone(True)
        with patch.object(self.module.time, 'monotonic', return_value=10): app.check_live_microphone()
        self.assertEqual(app.microphone_retry_at, 12)
        self.assertTrue(app.config['microphone_enabled']); self.assertFalse(app.microphone_active)
        app.microphone_toggle.setChecked.assert_not_called()
        with patch.object(self.module.time, 'monotonic', return_value=11): app.check_live_microphone()
        self.assertEqual(app.live_microphone.start.call_count, 1)
        app.microphone_box.currentData.return_value = 'Different Mic'
        with patch.object(self.module.time, 'monotonic', return_value=12): app.check_live_microphone()
        app.live_microphone.start.assert_called_with('Mic', 0.7, refresh=True)
        self.assertTrue(app.microphone_active)
        self.assertEqual(app.live_microphone.start.call_count, 2)

    def test_off_master_off_and_shutdown_cancel_pending_retry(self):
        for action in ('off', 'master', 'shutdown'):
            with self.subTest(action=action):
                self.setUp(); app = self.app
                app.live_microphone.start.side_effect = RuntimeError('device missing')
                app.toggle_microphone(True)
                if action == 'off': app.toggle_microphone(False)
                elif action == 'master': app.config['tts_enabled'] = False
                else: app.closing = True
                with patch.object(self.module.time, 'monotonic', return_value=app.microphone_retry_at + 5):
                    app.check_live_microphone()
                self.assertEqual(app.live_microphone.start.call_count, 1)


if __name__ == '__main__': unittest.main()
