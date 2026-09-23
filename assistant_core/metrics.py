"""Bounded, transcript-free performance measurements for diagnostics."""
from collections import defaultdict, deque
import threading
import time


class Metrics:
    def __init__(self):
        self._lock = threading.Lock()
        self._values = defaultdict(lambda: deque(maxlen=100))
        self._counts = defaultdict(int)
        self._request = None

    def begin(self):
        with self._lock:
            self._request = time.monotonic()

    def first_audio(self):
        with self._lock:
            if self._request is not None:
                self._values['request_to_audio_ms'].append((time.monotonic() - self._request) * 1000)
                self._request = None

    def record(self, name, value):
        with self._lock:
            self._values[name].append(float(value))

    def count(self, name):
        with self._lock:
            self._counts[name] += 1

    def summary(self):
        with self._lock:
            result = dict(self._counts)
            for name, values in self._values.items():
                ordered = sorted(values)
                if ordered:
                    result[name] = {'samples': len(ordered), 'median': round(ordered[len(ordered)//2], 1),
                                    'p95': round(ordered[min(len(ordered)-1, int(len(ordered)*.95))], 1)}
            return result
