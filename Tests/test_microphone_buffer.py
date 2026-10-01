from pathlib import Path
import sys
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1] / 'Windows'))
from microphone_buffer import MicrophoneBuffer


class MicrophoneBufferTests(unittest.TestCase):
    def render(self, buffer, frames):
        output = np.full((frames, 2), np.nan, dtype=np.float32)
        buffer.render(output)
        self.assertTrue(np.isfinite(output).all())
        np.testing.assert_array_equal(output[:, 0], output[:, 1])
        return output[:, 0]

    def test_preroll_and_starvation_recover_smoothly(self):
        buffer = MicrophoneBuffer()
        buffer.append(np.ones(480))
        self.assertFalse(self.render(buffer, 480).any())
        buffer.append(np.ones(buffer.target))
        self.render(buffer, 480)
        output = self.render(buffer, 7000)
        self.assertEqual(buffer.underruns, 1)
        self.assertEqual(output[-1], 0)
        self.assertLess(np.max(np.abs(np.diff(output))), 0.021)
        buffer.append(-np.ones(buffer.target))
        recovered = self.render(buffer, 480)
        self.assertAlmostEqual(recovered[-1], -1)
        self.assertLess(np.max(np.abs(np.diff(recovered))), 0.009)

    def test_pending_overflow_discards_stale_audio_and_preserves_fresh_input(self):
        buffer = MicrophoneBuffer()
        buffer.append(np.ones(buffer.capacity))
        buffer.append(-np.ones(buffer.target))
        output = self.render(buffer, 480)
        self.assertEqual(buffer.overflows, 1)
        self.assertLessEqual(buffer.queued_frames, buffer.target)
        self.assertAlmostEqual(output[-1], -1)

    def test_large_output_request_does_not_drain_preroll_immediately(self):
        buffer = MicrophoneBuffer()
        buffer.append(np.full(buffer.target, 0.25))
        self.assertFalse(self.render(buffer, 2880).any())
        buffer.append(np.full(2400, 0.25))
        output = self.render(buffer, 2880)
        self.assertGreater(output[-1], 0.2)
        self.assertEqual(buffer.underruns, 0)

    def test_output_does_not_wait_for_capture_lock(self):
        buffer = MicrophoneBuffer()
        buffer.append(np.full(buffer.target, 0.25))
        self.render(buffer, 480)
        with buffer._lock:
            output = self.render(buffer, 480)
        self.assertTrue((output > 0.2).all())
        self.assertEqual(buffer.underruns, 0)

    def test_input_overflow_and_nonfinite_samples_are_contained(self):
        buffer = MicrophoneBuffer()
        buffer.append(np.ones(buffer.target))
        self.render(buffer, 480)
        buffer.append(np.full(buffer.target, np.nan), discontinuity=True)
        self.assertFalse(self.render(buffer, 480).any())
        self.assertEqual(buffer.overflows, 1)

    def test_native_microphone_rates_convert_without_pitch_or_duration_changes(self):
        for input_rate, output_rate in ((16000, 48000), (44100, 48000), (48000, 44100)):
            with self.subTest(input_rate=input_rate, output_rate=output_rate):
                buffer = MicrophoneBuffer(input_rate, output_rate=output_rate)
                frames_in, frames_out = round(input_rate * 0.01), round(output_rate * 0.01)
                output = np.zeros((frames_out, 1), dtype=np.float32)
                previous = 0.; crossings = 0
                for block in range(1000):
                    samples = 0.25 * np.sin(2 * np.pi * 440 * (block * frames_in + np.arange(frames_in)) / input_rate)
                    buffer.append(samples); buffer.render(output)
                    if block >= 100:
                        values = output[:, 0]
                        crossings += int(previous < 0 <= values[0]) + np.count_nonzero((values[:-1] < 0) & (values[1:] >= 0))
                    previous = output[-1, 0]
                self.assertLess(abs(crossings / 9 - 440), 1)
                self.assertEqual((buffer.underruns, buffer.overflows), (0, 0))

    def test_effects_accept_narrowband_bluetooth_microphone_rate(self):
        from microphone_effects import MicrophoneEffects, FILTERS
        for effect in FILTERS:
            processor = MicrophoneEffects(8000)
            output = processor.process(np.full(160, 0.25), pitch=3, effect=effect, strength=1)
            self.assertTrue(np.isfinite(output).all())

    def test_independent_clocks_and_delivery_jitter_for_ten_minutes(self):
        for rate, drift in ((48000, -0.001), (44100, 0.001)):
            with self.subTest(rate=rate, drift=drift):
                buffer = MicrophoneBuffer(rate); frames = round(rate * 0.01)
                output = np.zeros((frames, 1), dtype=np.float32)
                next_capture = 0.; capture_block = sample = 0
                previous = max_jump = 0.; max_queue = 0
                for block in range(60000):
                    while next_capture <= block * 0.01:
                        samples = 0.25 * np.sin(2 * np.pi * 440 * (sample + np.arange(frames)) / rate)
                        buffer.append(samples); sample += frames
                        next_capture += (0.01 + (0.008 if capture_block % 2 == 0 else -0.008)) / (1 + drift)
                        capture_block += 1
                    max_queue = max(max_queue, buffer.queued_frames)
                    buffer.render(output)
                    max_jump = max(max_jump, abs(output[0, 0] - previous), np.max(np.abs(np.diff(output[:, 0]))))
                    previous = output[-1, 0]
                self.assertEqual((buffer.underruns, buffer.overflows), (0, 0))
                self.assertLess(max_queue, buffer.target + 4 * frames)
                self.assertGreater(buffer.queued_frames, frames)
                self.assertLess(max_jump, 0.025)


if __name__ == '__main__': unittest.main()
