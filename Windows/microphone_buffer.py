"""Bounded microphone buffering between a capture worker and audio output."""
from collections import deque
import threading
import numpy as np


class MicrophoneBuffer:
    def __init__(self, rate=48000, *, output_rate=None):
        self.rate = rate
        self.output_rate = output_rate or rate
        self.target = round(rate * 0.060)
        self.capacity = max(self.target * 4, round(rate * 0.35))
        self._pending = deque()
        self._pending_frames = 0
        self._lock = threading.Lock()
        self._reset = False
        self._ring = np.zeros(self.capacity, dtype=np.float32)
        self._written = self._position = 0
        self._fraction = self._gain = self._last = 0.0
        self._primed = False
        self._depth = float(self.target)
        self.underruns = self.device_underruns = 0
        self._capture_overflows = self._render_overflows = 0

    @property
    def overflows(self):
        return self._capture_overflows + self._render_overflows

    @property
    def queued_frames(self):
        return self._written - self._position + self._pending_frames

    def append(self, samples, *, discontinuity=False):
        # Publish owned samples. No DSP or copies happen while holding the lock.
        samples = np.nan_to_num(np.asarray(samples, dtype=np.float32), copy=True,
                                nan=0, posinf=0, neginf=0)
        with self._lock:
            if discontinuity or self._pending_frames + len(samples) > self.capacity:
                self._pending.clear(); self._pending_frames = 0; self._reset = True
                self._capture_overflows += 1
            if len(samples) > self.capacity: return False
            self._pending.append(samples); self._pending_frames += len(samples)
        return True

    def _rebuffer(self):
        self._position = self._written
        self._fraction = self._gain = 0.0
        self._primed = False

    def render(self, output, *, discontinuity=False):
        # The audio callback never waits for the capture/effects worker. If the
        # handoff is busy, it continues playing its already buffered samples.
        packets = ()
        if discontinuity:
            self.device_underruns += 1; self._rebuffer()
        if self._lock.acquire(blocking=False):
            try:
                packets, self._pending = self._pending, deque()
                self._pending_frames = 0
                if self._reset: self._rebuffer(); self._reset = False
            finally: self._lock.release()
        for packet in packets:
            if len(packet) > self.capacity - (self._written - self._position):
                self._rebuffer(); self._render_overflows += 1
            start = self._written % self.capacity
            first = min(len(packet), self.capacity - start)
            self._ring[start:start + first] = packet[:first]
            self._ring[:len(packet) - first] = packet[first:]
            self._written += len(packet)
        count = len(output)
        if not count: return
        available = self._written - self._position
        # A large host request must not consume the entire preroll in one go.
        ratio = self.rate / self.output_rate
        goal = min(self.capacity, max(self.target, int(np.ceil(count * ratio)) + round(self.rate * 0.03) + 1))
        if not self._primed and available >= goal:
            self._primed = True; self._depth = float(goal)
        self._depth += (available - self._depth) * min(1, count / self.output_rate)
        step = ratio * (1 + min(0.003, max(-0.003, (self._depth - goal) / (2 * self.rate))))
        valid = min(count, max(0, int(np.ceil((available - 1 - self._fraction) / step)))) if self._primed else 0
        if valid:
            positions = self._fraction + np.arange(valid) * step
            offsets = positions.astype(np.int64)
            a = self._ring[(self._position + offsets) % self.capacity]
            b = self._ring[(self._position + offsets + 1) % self.capacity]
            gains = np.minimum(1, self._gain + np.arange(1, valid + 1) / 128)
            mono = (a + (b - a) * (positions - offsets)) * gains
            output[:valid] = mono[:, None]
            self._gain = gains[-1]; self._last = float(mono[-1])
            advance = self._fraction + valid * step
            self._position += int(advance); self._fraction = advance - int(advance)
        if valid < count:
            if self._primed: self.underruns += 1; self._rebuffer()
            tail = self._last * 0.98 ** np.arange(1, count - valid + 1)
            tail[np.abs(tail) < 0.000001] = 0
            output[valid:] = tail[:, None]
            self._last = float(tail[-1])
