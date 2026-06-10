import shutil
import time
from pathlib import Path
from typing import Any, Dict, Optional

from recordlab_nodes.common.motion_detector import MotionDetector
from recordlab_nodes.common.topics import TOPIC_CAMERA, TOPIC_IMU, TOPIC_MOTION_STATUS, TOPIC_RECORD_TIMER, TOPIC_TIME_DELAY
from recordlab_nodes.core.main_node import MainNode
from recordlab_nodes.core.record_writers import CsvDataWriter

from .bsp_aux_workers import MicRecordWorker, ScreenCaptureWorker
from .bsp_device import BspDevice
from recordlab_nodes.common.device_checker import XrGlassesSSHManager
from .bsp_writers import CameraSharedMemoryWriter, CameraSnapshotWorker, SlamImageDataWriter

IMU_TYPE_TO_INDEX = {
    1: 0,
    2: 0,
    3: 0,
    12: 0,
    4: 1,
    5: 1,
    13: 1,
}


class BspMainNode(MainNode):
    requires_qt_event_loop = True

    def __init__(self, agent_config: Dict[str, Any]):
        super().__init__(agent_config)
        custom = agent_config.get("custom_params", {}) or {}
        self.persist_ssh_artifacts = bool(custom.get("persist_ssh_artifacts", True))
        ssh = XrGlassesSSHManager()
        ssh.hostname = custom.get("ssh_host", ssh.hostname)
        ssh.port = int(custom.get("ssh_port", ssh.port))
        ssh.username = custom.get("ssh_username", ssh.username)
        ssh.password = custom.get("ssh_password", ssh.password)
        self.ssh_manager = ssh
        self.device = BspDevice(ssh)
        self.device.set_imu_data_callback(self._on_imu)
        self.device.set_image_data_callback(self._on_image)
        self.motion_detector = MotionDetector()
        self.recording = False
        self.record_finalizing = False
        self.record_path: Optional[Path] = None
        self.record_start_ns: Optional[int] = None
        self.imu_writers = {
            0: CsvDataWriter(filename="imu_0.csv", buffer_size=50),
            1: CsvDataWriter(filename="imu_1.csv", buffer_size=50),
        }
        self.image_writer = SlamImageDataWriter(buffer_size=50)
        self.camera_shm_writer = CameraSharedMemoryWriter()
        self.camera_snapshot_worker: Optional[CameraSnapshotWorker] = None
        self.screen_capture_worker: Optional[ScreenCaptureWorker] = None
        self.mic_record_worker: Optional[MicRecordWorker] = None
        self.last_time_delay_publish_ns = 0
        self.last_motion_publish_ns = 0
        self.last_record_timer_publish_ns = 0
        self.last_motion_status = None
        self.latest_motion_message = {"status": "none"}
        self.last_camera_snapshot_feed_ns = {0: 0, 1: 0}
        self.sensor_time_offset_ns: Optional[int] = None

    def check(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return self.device.check()

    def estop(self, params: Dict[str, Any]) -> Dict[str, Any]:
        self.stop_record({})
        self.device.stop()
        return {"success": True, "message": "Emergency stopped"}

    def shutdown(self) -> None:
        self.estop({})
        self.device.release()
        self.camera_shm_writer.close(unlink=True)

    def init_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        self.sensor_time_offset_ns = None
        result = self.device.initialize(params or {})
        if result.get("success"):
            self._publish_device_cookies()
        return result

    def start_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        self.sensor_time_offset_ns = None
        result = self.device.start(params or {})
        if result.get("success"):
            self._publish_device_cookies()
        return result

    def stop_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        if self.recording:
            result = self.stop_record({})
            if not result.get("success"):
                return result
        return self.device.stop()

    def release_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        if self.recording:
            result = self.stop_record({})
            if not result.get("success"):
                return result
        return self.device.release()

    def control_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return self.device.control(params or {})

    def start_record(self, params: Dict[str, Any]) -> Dict[str, Any]:
        if self.recording:
            return {"success": False, "message": "Already recording"}
        if self.record_finalizing:
            return {"success": False, "message": "Previous recording is still finalizing"}
        dataset_name = (params or {}).get("dataset_name")
        if not dataset_name:
            return {"success": False, "message": "Missing dataset_name"}
        if (params or {}).get("enable_rgb_recording"):
            return {"success": False, "message": "BSP RGB recording is not migrated"}
        record_path = Path(self.agent_config.get("root_path", "data")) / str(dataset_name).strip("/\\")
        opened = []
        try:
            for writer in self.imu_writers.values():
                writer.open(str(record_path))
                opened.append(writer)
            if (params or {}).get("enable_image_recording", False):
                if not self.image_writer.open(str(record_path)):
                    return {"success": False, "message": f"Failed to open image writer: {record_path}"}
            self.record_path = record_path
            self.recording = True
            self.record_start_ns = time.time_ns()
            self.last_record_timer_publish_ns = 0
            self.last_camera_snapshot_feed_ns = {0: 0, 1: 0}
            if (params or {}).get("enable_camera_snapshot", False):
                self.camera_snapshot_worker = CameraSnapshotWorker(str(record_path))
                self.camera_snapshot_worker.start()
            if (params or {}).get("enable_screen_capture", False):
                self.screen_capture_worker = ScreenCaptureWorker(str(record_path))
                self.screen_capture_worker.start()
            if (params or {}).get("enable_mic_recording", False):
                self.mic_record_worker = MicRecordWorker(str(record_path))
                self.mic_record_worker.start()
            return {"success": True, "message": f"Recording started: {record_path}"}
        except Exception as exc:
            for writer in opened:
                writer.close()
            self.image_writer.close()
            self.recording = False
            return {"success": False, "message": str(exc)}

    def stop_record(self, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self.recording:
            return {"success": True, "message": "Not recording"}
        self.recording = False
        self.record_finalizing = True
        record_path = self.record_path
        camera_worker = self.camera_snapshot_worker
        screen_worker = self.screen_capture_worker
        mic_worker = self.mic_record_worker
        self.camera_snapshot_worker = None
        self.screen_capture_worker = None
        self.mic_record_worker = None
        try:
            for writer in self.imu_writers.values():
                writer.close()
            self.image_writer.close()
            if camera_worker:
                camera_worker.stop()
            if screen_worker:
                screen_worker.stop()
            if mic_worker:
                mic_worker.stop()
            if record_path and self.persist_ssh_artifacts:
                self.ssh_manager.save_getprop(record_path)
                self.ssh_manager.fetch_glass_config(record_path)
            return {"success": True, "message": "Recording stopped"}
        except Exception as exc:
            return {"success": False, "message": str(exc)}
        finally:
            self.record_finalizing = False

    def delete_record(self, params: Dict[str, Any]) -> Dict[str, Any]:
        dataset_name = (params or {}).get("dataset_name")
        if dataset_name:
            target = Path(self.agent_config.get("root_path", "data")) / str(dataset_name).strip("/\\")
        elif self.record_path:
            target = self.record_path
        else:
            return {"success": False, "message": "No dataset_name and no recent record"}
        if not target.exists():
            return {"success": False, "message": f"Path not found: {target}"}
        shutil.rmtree(target)
        return {"success": True, "message": f"Deleted: {target}"}

    def get_bsp_runtime_state(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "success": True,
            "message": "",
            "command": "get_bsp_runtime_state",
            **self.device.get_runtime_state(),
            "record_state": {
                "is_recording": self.recording,
                "record_path": str(self.record_path) if self.record_path else None,
            },
            "motion_status": dict(self.latest_motion_message),
        }

    def capture_raw_frame(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "success": False,
            "message": "BSP RGB raw capture is not migrated in this node",
            "command": "capture_raw_frame",
        }

    def _should_publish(self, now_ns: int, last_ns: int, interval_ns: int) -> bool:
        return last_ns <= 0 or now_ns - last_ns >= interval_ns

    def _publish_device_cookies(self) -> None:
        device_state = self.device.get_runtime_state().get("device", {})
        fsn = device_state.get("fsn")
        if fsn:
            self.publish_cookie("FSN", fsn, True)
        firmware = device_state.get("mcu_firmware_version")
        if firmware:
            self.publish_cookie("mcu_firmware_version", firmware, True)

    def _on_imu(self, imu_msg: Dict[str, Any]) -> None:
        self.publish(TOPIC_IMU, imu_msg)
        now_ns = time.time_ns()
        sensor_timestamp_ns = int(imu_msg.get("timestamp_ns", 0) or 0)
        if sensor_timestamp_ns > 0 and self.sensor_time_offset_ns is None:
            self.sensor_time_offset_ns = now_ns - sensor_timestamp_ns
        if self._should_publish(now_ns, self.last_time_delay_publish_ns, 100_000_000):
            self.last_time_delay_publish_ns = now_ns
            if sensor_timestamp_ns > 0 and self.sensor_time_offset_ns is not None:
                aligned_sensor_time_ns = sensor_timestamp_ns + self.sensor_time_offset_ns
                delay_ns = max(0, now_ns - aligned_sensor_time_ns)
                delay_status = "estimated"
            else:
                delay_ns = 0
                delay_status = "unavailable"
            self.publish(TOPIC_TIME_DELAY, {
                "name": TOPIC_TIME_DELAY,
                "timestamp_ns": now_ns,
                "time_delay_ns": delay_ns,
                "status": delay_status,
            })
        motion_msg = self.motion_detector.detect(imu_msg)
        motion_status = motion_msg.get("status")
        self.latest_motion_message = motion_msg
        if motion_status != self.last_motion_status or self._should_publish(now_ns, self.last_motion_publish_ns, 100_000_000):
            self.last_motion_status = motion_status
            self.last_motion_publish_ns = now_ns
            self.publish(TOPIC_MOTION_STATUS, motion_msg)
        if self.recording:
            imu_type = int(imu_msg["type"])
            values = imu_msg["data"]
            row = {
                "timestamp_ns": int(imu_msg["timestamp_ns"]),
                "type": imu_type,
                "data0": float(values[0]),
                "data1": float(values[1]),
                "data2": float(values[2]),
                "data3": float(values[3]),
                "data4": float(values[4]),
                "data5": float(values[5]),
            }
            writer = self.imu_writers.get(IMU_TYPE_TO_INDEX.get(imu_type, -1))
            status = "" if writer and writer.write_data(row) else "write failed"
            if self.record_start_ns and self._should_publish(now_ns, self.last_record_timer_publish_ns, 200_000_000):
                self.last_record_timer_publish_ns = now_ns
                self.publish(TOPIC_RECORD_TIMER, {
                    "name": TOPIC_RECORD_TIMER,
                    "timestamp_ns": now_ns,
                    "duration_ns": now_ns - self.record_start_ns,
                    "status": status,
                })

    def _on_image(self, image_msg: Dict[str, Any]) -> None:
        publish_msg = {"timestamp": image_msg.get("timestamp"), "cam_data": {}}
        now_ns = time.time_ns()
        for idx, cam_info in image_msg.get("cam_data", {}).items():
            try:
                cam_idx = int(idx)
            except Exception:
                continue
            seq, image_meta = self.camera_shm_writer.write_qimage(cam_idx, cam_info.get("image"))
            if not image_meta:
                continue
            item = {k: v for k, v in cam_info.items() if k != "image"}
            item["image"] = image_meta
            item["image_raw"] = image_meta
            publish_msg["cam_data"][str(idx)] = item
            if self.camera_snapshot_worker and self._should_publish(
                now_ns,
                self.last_camera_snapshot_feed_ns.get(idx, 0),
                200_000_000,
            ):
                self.camera_snapshot_worker.update_frame(idx, cam_info.get("image"))
                self.last_camera_snapshot_feed_ns[idx] = now_ns
        if publish_msg["cam_data"]:
            self.publish(TOPIC_CAMERA, publish_msg)
        if self.recording:
            # Recording keeps the SDK-origin image_msg; preview compression above never touches this path.
            self.image_writer.write_data(image_msg)
