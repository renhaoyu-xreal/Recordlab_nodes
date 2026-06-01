import csv
from typing import Dict, Optional


class CsvDataReader:
    def __init__(self):
        self._file = None
        self._reader = None
        self._eof = False

    def open(self, path: str) -> bool:
        self._file = open(path, "r", encoding="utf-8")
        self._reader = csv.DictReader(self._file)
        if self._reader.fieldnames:
            self._reader.fieldnames = [name.strip() for name in self._reader.fieldnames]
        self._eof = False
        return True

    def read_and_parse(self) -> Optional[Dict[str, float]]:
        if self._reader is None:
            return None
        try:
            row = next(self._reader)
        except StopIteration:
            self._eof = True
            return None
        return {k: float(v) for k, v in row.items() if v not in ("", None)}

    def is_eof(self) -> bool:
        return self._eof

    def close(self) -> None:
        if self._file:
            self._file.close()
        self._file = None
        self._reader = None
