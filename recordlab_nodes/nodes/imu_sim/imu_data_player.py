import threading
import time
from typing import Callable, Optional

from recordlab_nodes.common.logger_config import get_logger

from .csv_data_reader import CsvDataReader

logger = get_logger(__name__)


class ImuDataPlayer:
    def __init__(self, reader: CsvDataReader):
        self.reader = reader
        self._callback: Optional[Callable] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def set_callback(self, callback: Callable) -> None:
        self._callback = callback

    def open_file(self, path: str) -> bool:
        ok = self.reader.open(path)
        if not ok:
            logger.error("[ImuPlayer] Failed to open: %s", path)
        return ok

    def play(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("[ImuPlayer] Playing")

    def _loop(self) -> None:
        first_ts = None
        start_ns = None
        self._frame_count = 0
        try:
            while self._running and not self.reader.is_eof():
                row = self.reader.read_and_parse()
                if not row:
                    break
                current_ts = int(row.get("timestamp_ns", time.time_ns()))
                if first_ts is None:
                    first_ts = current_ts
                    start_ns = time.time_ns()
                if self._callback:
                    self._callback(row)
                self._frame_count += 1
                target_ns = start_ns + (current_ts - first_ts)
                sleep_s = (target_ns - time.time_ns()) / 1e9
                if sleep_s > 0:
                    time.sleep(min(sleep_s, 0.05))
        finally:
            self._running = False
            self.reader.close()
            if self._frame_count == 0:
                logger.warning("[ImuPlayer] Playback finished: 0 frames")
            else:
                logger.info("[ImuPlayer] Playback finished: %d frames", self._frame_count)

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self.reader.close()

    def is_running(self) -> bool:
        return self._running
