import csv
import queue
import threading
from pathlib import Path
from typing import Dict, Optional


class CsvDataWriter:
    def __init__(self, filename: str = "imu_data.csv", buffer_size: int = 3500):
        self.filename = filename
        self.buffer_size = buffer_size
        self._file = None
        self._writer: Optional[csv.DictWriter] = None
        self._queue: "queue.Queue[list]" = queue.Queue()
        self._buffer = []
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def open(self, folder_path: str) -> bool:
        folder = Path(folder_path)
        folder.mkdir(parents=True, exist_ok=True)
        self._file = open(folder / self.filename, "w", newline="", encoding="utf-8")
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()
        return True

    def write_data(self, row: Dict) -> bool:
        if self._file is None or self._stop.is_set():
            return False
        self._buffer.append(row)
        if len(self._buffer) >= self.buffer_size:
            self._queue.put(self._buffer.copy())
            self._buffer.clear()
        return True

    def _worker(self) -> None:
        while not self._stop.is_set() or not self._queue.empty():
            try:
                rows = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if rows:
                if self._writer is None:
                    self._writer = csv.DictWriter(self._file, fieldnames=list(rows[0].keys()))
                    self._writer.writeheader()
                self._writer.writerows(rows)
                self._file.flush()
            self._queue.task_done()

    def close(self) -> None:
        if self._buffer:
            self._queue.put(self._buffer.copy())
            self._buffer.clear()
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        if self._file:
            self._file.close()
            self._file = None
        self._writer = None
