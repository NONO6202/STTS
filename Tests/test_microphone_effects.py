from pathlib import Path
import sys
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1] / 'Windows'))
from microphone_effects import MicrophoneEffects, FILTERS


class MicrophoneEffectsTests(unittest.TestCase):
    def test_native_state_handles_empty_and_noncontiguous_input(self):
        dsp = MicrophoneEffects(8000)
        self.assertEqual(dsp.process(np.array([])).shape, (0,))
        source = np.array([.1, 9, -.2, 9, np.nan, 9, np.inf, 9], dtype=np.float32)[::2]
        np.testing.assert_array_equal(dsp.process(source), np.array([.1, -.2, 0, 0], dtype=np.float32))
        with self.assertRaises(ValueError): dsp.process(np.zeros((2, 2)))
        for effect in FILTERS:
            self.assertTrue(np.isfinite(dsp.process(np.ones(257, dtype=np.float32) * .1, 4, effect, 1)).all())

    def render(self, x, pitch=0, effect='기본', strength=1, block=256, rate=48000):
        dsp = MicrophoneEffects(rate)
        return np.concatenate([dsp.process(x[i:i + block], pitch, effect, strength) for i in range(0, len(x), block)])

    def tone(self, frequency, rate=48000):
        return (0.2 * np.sin(2 * np.pi * frequency * np.arange(rate) / rate)).astype(np.float32)

    def test_neutral_is_exact_and_pitch_keeps_duration_at_device_rates(self):
        for rate in (44100, 48000):
            x = self.tone(440, rate)
            np.testing.assert_array_equal(self.render(x, rate=rate), x)
            for pitch, frequency in ((-12, 220), (12, 880)):
                y = self.render(x, pitch, rate=rate)
                self.assertEqual(len(y), len(x))
                tail = y[rate // 4:]
                peak = np.fft.rfftfreq(len(tail), 1 / rate)[np.argmax(abs(np.fft.rfft(tail)))]
                self.assertAlmostEqual(peak, frequency, delta=2)

    def test_variable_blocks_preserve_phase_filter_and_echo(self):
        x = self.tone(440)
        for effect in FILTERS[1:]:
            np.testing.assert_allclose(self.render(x, 7, effect, block=97), self.render(x, 7, effect, block=4096), atol=1e-6)

    def test_telephone_rejects_bass_and_treble(self):
        rms = lambda y: np.sqrt(np.mean(y[12000:] ** 2))
        mid = rms(self.render(self.tone(1000), effect='전화'))
        self.assertLess(rms(self.render(self.tone(60), effect='전화')), mid * 0.1)
        self.assertLess(rms(self.render(self.tone(10000), effect='전화')), mid * 0.1)
        self.assertLess(rms(self.render(self.tone(250), effect='전화')), mid * 0.1)
        self.assertLess(rms(self.render(self.tone(4000), effect='전화')), mid * 0.2)

    def test_robot_modulates_at_80hz(self):
        y = self.render(self.tone(440), effect='로봇')[12000:]
        spectrum = abs(np.fft.rfft(y)); frequencies = np.fft.rfftfreq(len(y), 1 / 48000)
        level = lambda f: spectrum[np.argmin(abs(frequencies - f))]
        self.assertGreater(level(360), level(440) * 100)
        self.assertGreater(level(520), level(440) * 100)

    def test_echo_decays_and_new_stream_has_no_previous_audio(self):
        x = np.zeros(48000, dtype=np.float32); x[12000] = 0.5
        y = self.render(x, effect='에코')
        self.assertAlmostEqual(y[22560], 0.5, places=5)
        self.assertAlmostEqual(y[33120], 0.275, places=5)
        self.assertFalse(self.render(np.zeros(48000), effect='에코').any())

    def test_live_changes_are_finite_bounded_and_smoothed(self):
        dsp = MicrophoneEffects(); x = np.full(48000, 0.1, dtype=np.float32); output = []
        for i in range(0, len(x), 256):
            output.append(dsp.process(x[i:i + 256], 12 if i > 16000 else -12, '에코' if i > 32000 else '로봇', 1))
        y = np.concatenate(output)
        self.assertTrue(np.isfinite(y).all()); self.assertLessEqual(np.max(abs(y)), 1)
        self.assertLess(np.max(abs(np.diff(y[12000:]))), 0.02)
        self.assertTrue(np.isfinite(dsp.process(np.array([np.nan, np.inf, -np.inf]), np.nan, '전화', np.inf)).all())

    def test_new_effects_have_distinct_audible_processing(self):
        y = self.render(self.tone(440), effect='디스토션')[12000:]
        spectrum = abs(np.fft.rfft(y)); frequencies = np.fft.rfftfreq(len(y), 1 / 48000)
        level = lambda f: spectrum[np.argmin(abs(frequencies - f))]
        self.assertGreater(level(1320), level(440) * 0.15)
        quiet = self.render(self.tone(60), effect='확성기')[12000:]
        mid = self.render(self.tone(1000), effect='확성기')[12000:]
        self.assertLess(np.linalg.norm(quiet), np.linalg.norm(mid) * 0.2)
        crushed = self.render(self.tone(440), effect='8비트')[24000:].reshape(-1, 12)
        self.assertLess(np.max(np.ptp(crushed, axis=1)), 1e-6)
        self.assertGreater(np.max(abs(np.diff(crushed[:, 0]))), 0.05)
        tremolo = self.render(self.tone(1000), effect='트레몰로')
        self.assertLess(np.linalg.norm(tremolo[14950:15050]), np.linalg.norm(tremolo[12000:12100]) * 0.001)

    def test_reverb_chorus_and_underwater(self):
        x = np.zeros(48000, dtype=np.float32); x[12000] = 0.5
        tail = self.render(x, effect='리버브')
        self.assertGreater(np.max(abs(tail[16000:24000])), 0.005)
        self.assertLess(np.max(abs(tail[40000:])), np.max(abs(tail[16000:24000])))
        chorus = self.render(x, effect='합창')
        self.assertGreater(np.max(abs(chorus[12800:13600])), 0.1)
        rms = lambda y: np.sqrt(np.mean(y[12000:] ** 2))
        self.assertLess(rms(self.render(self.tone(4000), effect='수중')), rms(self.render(self.tone(300), effect='수중')) * 0.1)

    def test_high_gain_effects_gate_room_noise(self):
        noise = (np.random.default_rng(1).standard_normal(48000) * 0.0005).astype(np.float32)
        for effect in ('로봇', '확성기', '디스토션', '8비트'):
            self.assertLess(np.max(abs(self.render(noise, effect=effect)[12000:])), 0.002, effect)

    def test_strength_zero_is_dry_and_full_strength_remains_finite(self):
        for effect in FILTERS[1:]:
            x = self.tone(440)
            np.testing.assert_array_equal(self.render(x, effect=effect, strength=0), x)
            full = self.render(x, effect=effect)
            partial = self.render(x, effect=effect, strength=0.25)
            self.assertLess(np.linalg.norm(partial-x), np.linalg.norm(full-x) * 0.3)
            self.assertGreater(np.linalg.norm(full[12000:]-x[12000:]), np.linalg.norm(x[12000:]) * 0.25)
            loud = self.render(x * 8, effect=effect)
            self.assertTrue(np.isfinite(loud).all()); self.assertLessEqual(np.max(abs(loud)), 1)


if __name__ == '__main__': unittest.main()
