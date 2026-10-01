"""Native streaming effects; each capture worker owns its DSP state."""
import ctypes
from pathlib import Path
import sys
import weakref
import numpy as np

FILTERS = ('기본', '로봇', '전화', '에코', '확성기', '디스토션', '8비트', '트레몰로')
_library = None


def _native():
    global _library
    if _library is None:
        if getattr(sys, 'frozen', False):
            path = Path(sys._MEIPASS) / 'STTSAudio.dll'
        elif sys.platform == 'win32':
            path = Path(__file__).parent / 'build/STTSAudio.dll'
        else:
            path = Path(__file__).parents[1] / '.build/STTSAudio.dylib'
        lib = ctypes.CDLL(str(path))
        lib.stts_effects_create.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_double)]
        lib.stts_effects_create.restype = ctypes.c_void_p
        lib.stts_effects_destroy.argtypes = [ctypes.c_void_p]
        lib.stts_effects_destroy.restype = None
        lib.stts_effects_process.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_float),
                                           ctypes.c_size_t, ctypes.c_double, ctypes.c_int, ctypes.c_double]
        lib.stts_effects_process.restype = None
        _library = lib
    return _library


class MicrophoneEffects:
    def __init__(self, rate=48000):
        from scipy.signal import butter
        self.rate = rate = int(rate)
        if not 8000 <= rate <= 384000: raise ValueError('Unsupported microphone sample rate')
        coefficients = np.vstack((butter(4, 550, btype='highpass', fs=rate, output='sos'),
                                  butter(4, 2300, btype='lowpass', fs=rate, output='sos'),
                                  butter(2, 400, btype='highpass', fs=rate, output='sos'),
                                  butter(2, min(4000, rate * .45), btype='lowpass', fs=rate, output='sos')))
        self._lib = _native()
        self._state = self._lib.stts_effects_create(rate, round(rate * .22), round(rate / 4000),
                                                    coefficients.ctypes.data_as(ctypes.POINTER(ctypes.c_double)))
        if not self._state: raise RuntimeError('Cannot initialize microphone effects')
        self._release = weakref.finalize(self, self._lib.stts_effects_destroy, self._state)

    def process(self, samples, pitch=0, effect='기본', strength=.65):
        samples = np.ascontiguousarray(samples, dtype=np.float64)
        if samples.ndim != 1: raise ValueError('Microphone effects require mono samples')
        output = np.empty(len(samples), dtype=np.float32)
        effect_index = FILTERS.index(effect) if effect in FILTERS else 0
        self._lib.stts_effects_process(self._state, samples.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
                                     output.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), len(samples),
                                     pitch, effect_index, strength)
        return output
