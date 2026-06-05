from collections import deque
from math import sqrt
from typing import Deque, Dict, Iterable, List, Optional, Tuple


MOTION_NONE = "none"
MOTION_STATIC = "static"
MOTION_MOVING = "moving"
MOTION_ACTIVE = "active"


class IncrementalStats:
    def __init__(self) -> None:
        self.window: Deque[Dict] = deque()
        self.mean = [0.0, 0.0, 0.0]
        self.s = [0.0, 0.0, 0.0]

    def push(self, item: Dict) -> None:
        values = vector3(item.get("data", []))
        self.window.append(item)
        n = len(self.window)
        if n == 1:
            self.mean = list(values)
            self.s = [0.0, 0.0, 0.0]
            return
        for i, value in enumerate(values):
            old_mean = self.mean[i]
            self.mean[i] += (value - old_mean) / n
            self.s[i] += (value - old_mean) * (value - self.mean[i])

    def pop(self) -> None:
        if not self.window:
            return
        values = vector3(self.window.popleft().get("data", []))
        n = len(self.window) + 1
        if n <= 1:
            self.clear()
            return
        for i, value in enumerate(values):
            old_mean = self.mean[i]
            self.mean[i] = (old_mean * n - value) / (n - 1)
            self.s[i] -= (value - old_mean) * (value - self.mean[i])
            if self.s[i] < 0.0:
                self.s[i] = 0.0

    def clear(self) -> None:
        self.window.clear()
        self.mean = [0.0, 0.0, 0.0]
        self.s = [0.0, 0.0, 0.0]

    def std(self) -> Tuple[float, float, float]:
        n = len(self.window)
        if n <= 1:
            return 0.0, 0.0, 0.0
        return tuple(sqrt(max(value, 0.0) / (n - 1)) for value in self.s)

    def time_span_ns(self) -> int:
        if len(self.window) < 2:
            return 0
        return int(self.window[-1].get("timestamp_ns", 0)) - int(self.window[0].get("timestamp_ns", 0))

    def __len__(self) -> int:
        return len(self.window)


def vector3(values: Iterable) -> Tuple[float, float, float]:
    result: List[float] = []
    for value in values:
        if len(result) >= 3:
            break
        try:
            result.append(float(value))
        except (TypeError, ValueError):
            result.append(0.0)
    while len(result) < 3:
        result.append(0.0)
    return result[0], result[1], result[2]


class MotionDetector:
    def __init__(
        self,
        time_window: float = 2.0,
        gyro_sigma: float = 0.01,
        acc_sigma: float = 0.1,
        use_gyro: bool = True,
        use_acc: bool = True,
        gyro_threshold: Optional[float] = None,
        acc_threshold: Optional[float] = None,
    ) -> None:
        self.time_window_ns = int(time_window * 1e9)
        self.gyro_sigma = float(gyro_threshold if gyro_threshold is not None else gyro_sigma)
        self.acc_sigma = float(acc_threshold if acc_threshold is not None else acc_sigma)
        self.timestamp_rollback_tolerance_ns = max(self.time_window_ns, 100_000_000)
        self.last_timestamp_ns = 0
        self.gyro_stats = IncrementalStats() if use_gyro else None
        self.acc_stats = IncrementalStats() if use_acc else None

    def add_imu_message(self, imu_message: Dict) -> None:
        current_ts = int(float(imu_message.get("timestamp_ns", 0) or 0))
        if self._has_timestamp_rollback(current_ts):
            self.clear()
        if current_ts > self.last_timestamp_ns:
            self.last_timestamp_ns = current_ts

        data_type = int(imu_message.get("type", 0) or 0)
        if data_type == 1 and self.gyro_stats is not None:
            self.gyro_stats.push(imu_message)
        elif data_type == 2 and self.acc_stats is not None:
            self.acc_stats.push(imu_message)

        self._remove_old_data()

    def detect(self, imu_message: Optional[Dict] = None) -> Dict:
        if imu_message is not None:
            self.add_imu_message(imu_message)

        if self._is_empty() or self._time_span_ns() < self.time_window_ns / 2:
            return {
                "name": "motion_status",
                "timestamp_ns": self.last_timestamp_ns,
                "status": MOTION_NONE,
            }

        states: List[str] = []
        if self.gyro_stats is not None and len(self.gyro_stats) > 0:
            states.append(self._classify(max(self.gyro_stats.std()), self.gyro_sigma))
        if self.acc_stats is not None and len(self.acc_stats) > 0:
            states.append(self._classify(max(self.acc_stats.std()), self.acc_sigma))

        status = self._max_state(states) if states else MOTION_STATIC
        return {
            "name": "motion_status",
            "timestamp_ns": self.last_timestamp_ns,
            "status": status,
        }

    def get_statistics(self) -> Dict:
        result = {"window_size": 0, "time_span": self._time_span_ns() / 1e9}
        if self.gyro_stats is not None and len(self.gyro_stats) > 0:
            result["gyro_mean"] = list(self.gyro_stats.mean)
            result["gyro_std"] = list(self.gyro_stats.std())
            result["window_size"] = len(self.gyro_stats)
        if self.acc_stats is not None and len(self.acc_stats) > 0:
            result["acc_mean"] = list(self.acc_stats.mean)
            result["acc_std"] = list(self.acc_stats.std())
            result["window_size"] = max(result["window_size"], len(self.acc_stats))
        return result

    def clear(self) -> None:
        if self.gyro_stats is not None:
            self.gyro_stats.clear()
        if self.acc_stats is not None:
            self.acc_stats.clear()
        self.last_timestamp_ns = 0

    def _is_empty(self) -> bool:
        return (
            (self.gyro_stats is None or len(self.gyro_stats) == 0)
            and (self.acc_stats is None or len(self.acc_stats) == 0)
        )

    def _time_span_ns(self) -> int:
        spans = []
        if self.gyro_stats is not None:
            spans.append(self.gyro_stats.time_span_ns())
        if self.acc_stats is not None:
            spans.append(self.acc_stats.time_span_ns())
        return max(spans, default=0)

    @staticmethod
    def _classify(std_value: float, sigma: float) -> str:
        if std_value <= 3.0 * sigma:
            return MOTION_STATIC
        if std_value <= 10.0 * sigma:
            return MOTION_MOVING
        return MOTION_ACTIVE

    @staticmethod
    def _max_state(states: List[str]) -> str:
        priority = {MOTION_NONE: 0, MOTION_STATIC: 1, MOTION_MOVING: 2, MOTION_ACTIVE: 3}
        return max(states, key=lambda state: priority.get(state, -1))

    def _has_timestamp_rollback(self, current_timestamp: int) -> bool:
        if current_timestamp <= 0 or self.last_timestamp_ns <= 0:
            return False
        return current_timestamp + self.timestamp_rollback_tolerance_ns < self.last_timestamp_ns

    def _remove_old_data(self) -> None:
        timeout_ns = self.last_timestamp_ns - self.time_window_ns
        for stats in (self.gyro_stats, self.acc_stats):
            while stats is not None and stats.window:
                if int(stats.window[0].get("timestamp_ns", 0)) < timeout_ns:
                    stats.pop()
                else:
                    break
