import time
from pathlib import Path
from typing import Any, Dict

from recordlab_nodes.common.motion_detector import MotionDetector
from recordlab_nodes.common.topics import TOPIC_IMU, TOPIC_MOTION_STATUS, TOPIC_RECORD_TIMER, TOPIC_TIME_DELAY
from recordlab_nodes.core.main_node import MainNode
from recordlab_nodes.core.record_writers import CsvDataWriter

from .csv_data_reader import CsvDataReader
from .dataset_device import DatasetDevice
from .imu_data_player import ImuDataPlayer


class ImuSimNode(MainNode):
    def __init__(self, agent_config: Dict[str, Any]):
        super().__init__(agent_config)
        self.device = DatasetDevice(ImuDataPlayer(CsvDataReader()))
        self.device.set_imu_data_callback(self._on_imu)
        self.motion_detector = MotionDetector()
        self.recording = False
        self.record_start_ns = None
        self.imu_writer = CsvDataWriter(filename="imu_data.csv", buffer_size=50)

    def check(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return self.device.check()

    def estop(self, params: Dict[str, Any]) -> Dict[str, Any]:
        self.stop_record({})
        self.device.stop()
        return {"success": True, "message": "Emergency stopped"}

    def shutdown(self) -> None:
        self.estop({})
        self.device.release()

    def init_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return self.device.initialize(params)

    def start_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return self.device.start()

    def stop_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        self.stop_record({})
        return self.device.stop()

    def release_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return self.device.release()

    def control_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {"success": False, "message": "control_device is not implemented for ImuSimNode"}

    def start_record(self, params: Dict[str, Any]) -> Dict[str, Any]:
        if self.recording:
            return {"success": False, "message": "Already recording"}
        dataset_name = params.get("dataset_name")
        if not dataset_name:
            return {"success": False, "message": "Missing dataset_name"}
        record_path = Path(self.agent_config.get("root_path", "data")) / dataset_name
        self.imu_writer.open(str(record_path))
        self.recording = True
        self.record_start_ns = time.time_ns()
        return {"success": True, "message": f"Recording started: {record_path}"}

    def stop_record(self, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self.recording:
            return {"success": True, "message": "Not recording"}
        self.recording = False
        self.imu_writer.close()
        return {"success": True, "message": "Recording stopped"}

    def _on_imu(self, imu_msg: Dict[str, Any]) -> None:
        self.publish(TOPIC_IMU, imu_msg)
        now_ns = time.time_ns()
        sample_timestamp_ns = int(imu_msg.get("timestamp_ns", 0) or 0)
        self.publish(TOPIC_TIME_DELAY, {
            "name": TOPIC_TIME_DELAY,
            "timestamp_ns": now_ns,
            "time_delay_ns": max(0, now_ns - sample_timestamp_ns) if sample_timestamp_ns > 0 else 0,
            "status": "valid" if sample_timestamp_ns > 0 else "unavailable",
        })
        self.publish(TOPIC_MOTION_STATUS, self.motion_detector.detect(imu_msg))
        if self.recording:
            row = {
                "timestamp_ns": int(imu_msg["timestamp_ns"]),
                "type": int(imu_msg["type"]),
                "data0": float(imu_msg["data"][0]),
                "data1": float(imu_msg["data"][1]),
                "data2": float(imu_msg["data"][2]),
                "data3": float(imu_msg["data"][3]),
                "data4": float(imu_msg["data"][4]),
                "data5": float(imu_msg["data"][5]),
            }
            self.imu_writer.write_data(row)
            duration_ns = now_ns - self.record_start_ns if self.record_start_ns else 0
            self.publish(TOPIC_RECORD_TIMER, {
                "name": TOPIC_RECORD_TIMER,
                "timestamp_ns": now_ns,
                "duration_ns": duration_ns,
                "status": "",
            })
