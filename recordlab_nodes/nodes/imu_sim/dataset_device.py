from typing import Any, Callable, Dict, Optional

from .imu_data_player import ImuDataPlayer


class DatasetDevice:
    NVIZ_FIELDS = [
        "timestamp",
        "onsensor_timestamp_us",
        "timestamp_ns",
        "type",
        "data0",
        "data1",
        "data2",
        "data3",
        "data4",
        "data5",
    ]

    def __init__(self, player: ImuDataPlayer):
        self.player = player
        self._initialized = False
        self._imu_callback: Optional[Callable[[Dict[str, Any]], None]] = None

    def initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        read_path = params.get("read_path")
        if not read_path:
            return {"success": False, "message": "Missing read_path"}
        self.player.open_file(read_path)
        self._initialized = True
        return {"success": True, "message": "Device initialized"}

    def start(self) -> Dict[str, Any]:
        if not self._initialized:
            return {"success": False, "message": "Device not initialized"}
        if self.player.is_running():
            return {"success": False, "message": "Already running"}
        self.player.play()
        return {"success": True, "message": "Device started"}

    def stop(self) -> Dict[str, Any]:
        self.player.stop()
        return {"success": True, "message": "Device stopped"}

    def release(self) -> Dict[str, Any]:
        self.player.stop()
        self._initialized = False
        return {"success": True, "message": "Device released"}

    def set_imu_data_callback(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        self._imu_callback = callback

        def wrapped(row: Dict[str, Any]) -> None:
            if not all(field in row for field in self.NVIZ_FIELDS):
                return
            msg = {
                "type": int(row["type"]),
                "timestamp_ns": int(row["timestamp_ns"]),
                "data": [
                    float(row["data0"]),
                    float(row["data1"]),
                    float(row["data2"]),
                    float(row["data3"]),
                    float(row["data4"]),
                    float(row["data5"]),
                ],
            }
            if self._imu_callback:
                self._imu_callback(msg)

        self.player.set_callback(wrapped)

    def check(self) -> Dict[str, Any]:
        return {"success": True, "message": ""}
