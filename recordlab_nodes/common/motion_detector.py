from typing import Dict, List


class MotionDetector:
    def __init__(self, gyro_threshold: float = 0.03, acc_threshold: float = 0.1):
        self.gyro_threshold = gyro_threshold
        self.acc_threshold = acc_threshold

    def detect(self, imu_message: Dict) -> Dict:
        values: List[float] = imu_message.get("data", [])
        data_type = imu_message.get("type")
        if not values:
            status = "none"
        elif data_type == 1:
            status = "moving" if max(abs(v) for v in values[:3]) >= self.gyro_threshold else "static"
        elif data_type == 2:
            status = "moving" if max(abs(v) for v in values[:3]) >= self.acc_threshold else "static"
        else:
            status = "active"
        return {
            "name": "motion_status",
            "timestamp_ns": int(imu_message.get("timestamp_ns", 0)),
            "status": status,
        }
