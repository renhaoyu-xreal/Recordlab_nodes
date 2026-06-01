import csv
from typing import Dict, Optional

from recordlab_nodes.common.logger_config import get_logger

logger = get_logger(__name__)


class CsvDataReader:
    def __init__(self):
        self._file = None
        self._reader = None
        self._eof = False
        self._logged_header = False

    def open(self, path: str) -> bool:
        try:
            self._file = open(path, "r", encoding="utf-8")
            self._reader = csv.DictReader(self._file)
            if self._reader.fieldnames:
                self._reader.fieldnames = [name.strip() for name in self._reader.fieldnames]
                if not self._logged_header:
                    logger.info("[CsvReader] Header: %s", ",".join(self._reader.fieldnames))
                    self._logged_header = True
            else:
                logger.warning("[CsvReader] Missing header row")
            self._eof = False
            logger.info("[CsvReader] Opened: %s", path)
            return True
        except FileNotFoundError:
            logger.error("[CsvReader] File not found: %s", path)
            return False
        except Exception as exc:
            logger.error("[CsvReader] Open error: %s", exc)
            return False

    def read_and_parse(self) -> Optional[Dict[str, float]]:
        if self._reader is None:
            return None
        try:
            row = next(self._reader)
        except StopIteration:
            self._eof = True
            logger.info("[CsvReader] EOF")
            return None
        try:
            return {k: float(v) for k, v in row.items() if v not in ("", None)}
        except (ValueError, TypeError) as exc:
            logger.error("[CsvReader] Parse error: %s", exc)
            return None

    def is_eof(self) -> bool:
        return self._eof

    def close(self) -> None:
        if self._file:
            self._file.close()
        self._file = None
        self._reader = None
