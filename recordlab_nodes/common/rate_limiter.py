import time
from typing import Any


class RateLimiter:
    def __init__(self, frequency_hz: float = 0.0):
        self.frequency_hz = float(frequency_hz or 0.0)
        self._last_time = 0.0

    def check(self, _: Any = None) -> bool:
        if self.frequency_hz <= 0:
            return True
        now = time.monotonic()
        interval = 1.0 / self.frequency_hz
        if now - self._last_time >= interval:
            self._last_time = now
            return True
        return False
