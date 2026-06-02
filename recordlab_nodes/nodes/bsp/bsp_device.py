import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import paramiko
from PySide6.QtCore import QObject, QMutex, Qt, QWaitCondition, Signal
from xrglasses import XrGlasses as Xr

from recordlab_nodes.common.logger_config import get_logger
from recordlab_nodes.common.device_checker import XrGlassesSSHManager

from .bsp_aux_workers import XrSshConfig

logger = get_logger(__name__)

CAMERA_MODE_SLAM = "slam"
CAMERA_MODE_RGB = "rgb"
DEFAULT_SLAM_FPS = 30.0


def coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


class GlassesQtBridge(QObject):
    create_signal = Signal()
    open_signal = Signal()
    start_signal = Signal(object)
    stop_signal = Signal(object)
    configure_signal = Signal(object)
    query_state_signal = Signal()
    close_signal = Signal()

    def __init__(self):
        super().__init__()
        self.glasses = None
        self.product_ids = []
        self.result: Optional[Dict[str, Any]] = None
        self.operation_lock = threading.Lock()
        self.mutex = QMutex()
        self.wait_condition = QWaitCondition()
        self.imu_callback: Optional[Callable] = None
        self.image_callback: Optional[Callable] = None
        self.create_signal.connect(self._create_slot, Qt.AutoConnection)
        self.open_signal.connect(self._open_slot, Qt.AutoConnection)
        self.start_signal.connect(self._start_slot, Qt.AutoConnection)
        self.stop_signal.connect(self._stop_slot, Qt.AutoConnection)
        self.configure_signal.connect(self._configure_slot, Qt.AutoConnection)
        self.query_state_signal.connect(self._query_state_slot, Qt.AutoConnection)
        self.close_signal.connect(self._close_slot, Qt.AutoConnection)

    def set_callbacks(self, imu_callback: Optional[Callable], image_callback: Optional[Callable]) -> None:
        self.imu_callback = imu_callback
        self.image_callback = image_callback
        if not self.glasses:
            return
        if imu_callback:
            self.glasses.imuUpdated.connect(self._on_imu_slot, Qt.QueuedConnection)
        if image_callback:
            self.glasses.camUpdated.connect(self._on_cam_slot, Qt.QueuedConnection)

    def disconnect_callbacks(self) -> None:
        if not self.glasses:
            return
        try:
            if self.imu_callback:
                self.glasses.imuUpdated.disconnect(self._on_imu_slot)
            if self.image_callback:
                self.glasses.camUpdated.disconnect(self._on_cam_slot)
        except RuntimeError:
            pass

    def create_glasses(self) -> Dict[str, Any]:
        return self._invoke(self.create_signal)

    def open_glasses(self) -> Dict[str, Any]:
        return self._invoke(self.open_signal)

    def start_sensors(self, mask) -> Dict[str, Any]:
        return self._invoke(self.start_signal, mask)

    def stop_sensors(self, mask) -> Dict[str, Any]:
        return self._invoke(self.stop_signal, mask)

    def configure_glasses(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return self._invoke(self.configure_signal, params)

    def get_glasses_state(self) -> Dict[str, Any]:
        return self._invoke(self.query_state_signal)

    def close_glasses(self) -> Dict[str, Any]:
        return self._invoke(self.close_signal)

    def _invoke(self, signal_obj, *args) -> Dict[str, Any]:
        with self.operation_lock:
            self.mutex.lock()
            try:
                self.result = None
                signal_obj.emit(*args)
                if not self.wait_condition.wait(self.mutex, 5000):
                    return {"success": False, "message": "Qt bridge operation timeout"}
                result = self.result
                self.result = None
                return result or {"success": False, "message": "No result"}
            finally:
                self.mutex.unlock()

    def _set_result(self, result: Dict[str, Any]) -> None:
        self.mutex.lock()
        try:
            self.result = result
            self.wait_condition.wakeAll()
        finally:
            self.mutex.unlock()

    def _create_slot(self) -> None:
        try:
            factory = Xr.GlassesFactory.instance()
            self.product_ids = factory.enumerateDevices()
            if not self.product_ids:
                self._set_result({"success": False, "message": "No glasses found"})
                return
            self.glasses = factory.createGlasses(self.product_ids[0])
            self._set_result({"success": True, "message": ""})
        except Exception as exc:
            self._set_result({"success": False, "message": str(exc)})

    def _open_slot(self) -> None:
        try:
            if not self.glasses:
                self._set_result({"success": False, "message": "Glasses not created"})
                return
            if not self.glasses.open():
                self._set_result({"success": False, "message": "Failed to open glasses"})
                return
            self._set_result({"success": True, "message": ""})
        except Exception as exc:
            self._set_result({"success": False, "message": str(exc)})

    def _start_slot(self, mask) -> None:
        try:
            if not self.glasses:
                self._set_result({"success": False, "message": "Glasses not created"})
                return
            if self.glasses.startSensors(mask) is False:
                self._set_result({"success": False, "message": "Failed to start sensors"})
                return
            self._set_result({"success": True, "message": ""})
        except Exception as exc:
            self._set_result({"success": False, "message": str(exc)})

    def _stop_slot(self, mask) -> None:
        try:
            if self.glasses and self.glasses.stopSensors(mask) is False:
                self._set_result({"success": False, "message": "Failed to stop sensors"})
                return
            self._set_result({"success": True, "message": ""})
        except Exception as exc:
            self._set_result({"success": False, "message": str(exc)})

    def _configure_slot(self, params: Dict[str, Any]) -> None:
        try:
            if not self.glasses:
                self._set_result({"success": False, "message": "Glasses not created"})
                return
            if (fps := params.get("slam_fps")) is not None:
                self.glasses.setFrameRate(Xr.SensorType.Slam, float(fps))
            if (exposure := params.get("exposure")) is not None:
                self.glasses.setExposure(Xr.SensorType.Slam, int(float(exposure)))
            if (auto_exposure := params.get("auto_exposure")) is not None:
                self.glasses.setAutoExposure(Xr.SensorType.Slam, coerce_bool(auto_exposure))
            if (enable := params.get("enable_display")) is not None:
                if coerce_bool(enable):
                    self.glasses.startSensors({Xr.SensorType.Display})
                else:
                    self.glasses.startSensors({Xr.SensorType.Display})
                    self.glasses.stopSensors({Xr.SensorType.Display})
            self._set_result({"success": True, "message": ""})
        except Exception as exc:
            self._set_result({"success": False, "message": str(exc)})

    def _query_state_slot(self) -> None:
        try:
            if not self.glasses:
                self._set_result({"success": False, "message": "Glasses not created"})
                return
            active_sensors = []
            try:
                active_sensors = [
                    getattr(sensor, "name", str(sensor))
                    for sensor in sorted(self.glasses.activeSensors(), key=lambda sensor: getattr(sensor, "value", 0))
                ]
            except Exception:
                pass
            state = {
                "is_opened": bool(self.glasses.isOpened()),
                "glasses_type": getattr(self.glasses.type(), "name", str(self.glasses.type())),
                "fsn": self.glasses.fsn(),
                "mcu_firmware_version": self.glasses.mcuFirmwareVersion(),
                "active_sensors": active_sensors,
            }
            self._set_result({"success": True, "message": "", "state": state})
        except Exception as exc:
            self._set_result({"success": False, "message": str(exc)})

    def _close_slot(self) -> None:
        try:
            if self.glasses:
                self.glasses.close()
                self.glasses = None
            self._set_result({"success": True, "message": ""})
        except Exception as exc:
            self._set_result({"success": False, "message": str(exc)})

    def _on_imu_slot(self, imu_data) -> None:
        if self.imu_callback:
            self.imu_callback(imu_data)

    def _on_cam_slot(self, sensor_type, image_pair) -> None:
        if self.image_callback:
            self.image_callback(sensor_type, image_pair)


class BspDevice:
    def __init__(self, ssh_manager: Optional[XrGlassesSSHManager] = None):
        self.imu_callback: Optional[Callable] = None
        self.image_callback: Optional[Callable] = None
        self.ssh_manager = ssh_manager or XrGlassesSSHManager()
        self.bridge = GlassesQtBridge()
        self.initialized = False
        self.started = False
        self.display_enabled = False
        self.camera_mode = CAMERA_MODE_SLAM
        self.slam_config = {"fps": DEFAULT_SLAM_FPS, "auto_exposure": None, "exposure": None}
        self.start_sensors = {Xr.SensorType.Imu, Xr.SensorType.Slam}
        self.device_state_cache: Dict[str, Any] = {}
        self.latest_temperatures = {"imu0_temperature": None, "imu1_temperature": None}
        self.latest_frame_state: Dict[str, Any] = {}

    def set_imu_data_callback(self, callback: Callable) -> None:
        self.imu_callback = callback

    def set_image_data_callback(self, callback: Callable) -> None:
        self.image_callback = callback

    def initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        params = params or {}
        self.release()
        if not coerce_bool(params.get("skip_restart_check")):
            ssh_result = self.ssh_manager.check_and_wait_restarted()
            if not ssh_result.get("success"):
                return ssh_result
        result = self.bridge.create_glasses()
        if not result.get("success"):
            return result
        self.bridge.set_callbacks(
            self._on_imu_data if self.imu_callback else None,
            self._on_cam_data if self.image_callback else None,
        )
        result = self.bridge.open_glasses()
        if not result.get("success"):
            self.release()
            return result
        self.initialized = True
        self._refresh_state()
        return {"success": True, "message": ""}

    def start(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.initialized:
            return {"success": False, "message": "Not initialized"}
        if self.started:
            return {"success": False, "message": "Already started"}
        params = params or {}
        camera_mode = params.get("camera_mode", CAMERA_MODE_SLAM)
        if camera_mode != CAMERA_MODE_SLAM:
            return {"success": False, "message": "BSP RGB mode is not migrated in this node"}
        sensors = {Xr.SensorType.Imu, Xr.SensorType.Slam}
        if self.display_enabled:
            sensors.add(Xr.SensorType.Display)
        result = self.bridge.start_sensors(sensors)
        if not result.get("success"):
            return result
        result = self.bridge.configure_glasses(self._startup_config())
        if not result.get("success"):
            self.bridge.stop_sensors(sensors)
            return result
        self.camera_mode = CAMERA_MODE_SLAM
        self.start_sensors = sensors
        self.started = True
        self._refresh_state()
        return {"success": True, "message": ""}

    def stop(self) -> Dict[str, Any]:
        result = self.bridge.stop_sensors(self.start_sensors)
        if not result.get("success"):
            return result
        self.started = False
        self._refresh_state()
        return {"success": True, "message": ""}

    def release(self) -> Dict[str, Any]:
        try:
            if self.bridge.glasses:
                self.bridge.disconnect_callbacks()
                self.bridge.close_glasses()
            self.initialized = False
            self.started = False
            self.camera_mode = CAMERA_MODE_SLAM
            self.start_sensors = {Xr.SensorType.Imu, Xr.SensorType.Slam}
            self.device_state_cache = {}
            self.latest_frame_state = {}
            return {"success": True, "message": ""}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def control(self, params: Dict[str, Any]) -> Dict[str, Any]:
        config: Dict[str, Any] = {}
        if (fps := params.get("slam_fps")) is not None:
            self.slam_config["fps"] = float(fps)
            config["slam_fps"] = self.slam_config["fps"]
        if (exposure := params.get("exposure")) is not None:
            self.slam_config["exposure"] = int(float(exposure))
            config["exposure"] = self.slam_config["exposure"]
        if (auto_exposure := params.get("auto_exposure")) is not None:
            self.slam_config["auto_exposure"] = coerce_bool(auto_exposure)
            config["auto_exposure"] = self.slam_config["auto_exposure"]
        if (enable := params.get("enable_display")) is not None:
            self.display_enabled = coerce_bool(enable)
            config["enable_display"] = self.display_enabled
            if self.display_enabled:
                self.start_sensors.add(Xr.SensorType.Display)
            else:
                self.start_sensors.discard(Xr.SensorType.Display)
        if config and self.initialized:
            result = self.bridge.configure_glasses(config)
            if not result.get("success"):
                return result
        self._refresh_state()
        return {"success": True, "message": ""}

    def check(self) -> Dict[str, Any]:
        if self.ssh_manager.ping() or self.ssh_manager.check_connection(timeout_s=2.0):
            return {"success": True, "message": ""}
        return {"success": False, "message": "SSH connection failed"}

    def get_runtime_state(self) -> Dict[str, Any]:
        if self.initialized:
            self._refresh_state()
        return {
            "device": {
                "connected": self.initialized,
                "initialized": self.initialized,
                "started": self.started,
                "is_opened": self.device_state_cache.get("is_opened", False),
                "glasses_type": self.device_state_cache.get("glasses_type", ""),
                "fsn": self.device_state_cache.get("fsn", ""),
                "mcu_firmware_version": self.device_state_cache.get("mcu_firmware_version", ""),
                "active_sensors": self.device_state_cache.get("active_sensors", []),
            },
            "temperatures": dict(self.latest_temperatures),
            "camera_mode": self.camera_mode,
            "latest_frame": dict(self.latest_frame_state),
        }

    def _startup_config(self) -> Dict[str, Any]:
        config = {"slam_fps": self.slam_config["fps"]}
        if self.slam_config.get("auto_exposure") is not None:
            config["auto_exposure"] = self.slam_config["auto_exposure"]
        if self.slam_config.get("exposure") is not None:
            config["exposure"] = self.slam_config["exposure"]
        return config

    def _refresh_state(self) -> None:
        result = self.bridge.get_glasses_state()
        if result.get("success"):
            self.device_state_cache = result.get("state", {})

    def _on_imu_data(self, imu_data) -> None:
        try:
            data = imu_data.data()
            timestamp_ns = int(data.hmd_time_ns)
            imu_idx = getattr(data, "imu_idx", 0)
            self.latest_temperatures[f"imu{imu_idx}_temperature"] = float(data.temperature)
            if imu_idx == 1:
                gyro_type, acc_type, mag_type, temp_type = 4, 5, None, 13
            else:
                gyro_type, acc_type, mag_type, temp_type = 1, 2, 3, 12
            messages = []
            if data.hasGyro():
                messages.append({"type": gyro_type, "timestamp_ns": timestamp_ns, "data": [float(data.gyro[0]), float(data.gyro[1]), float(data.gyro[2]), 0.0, 0.0, 0.0]})
                messages.append({"type": temp_type, "timestamp_ns": timestamp_ns, "data": [float(data.temperature), 0.0, 0.0, 0.0, 0.0, 0.0]})
            if data.hasAcc():
                messages.append({"type": acc_type, "timestamp_ns": timestamp_ns, "data": [float(data.acc[0]), float(data.acc[1]), float(data.acc[2]), 0.0, 0.0, 0.0]})
            if data.hasMag() and mag_type is not None:
                messages.append({"type": mag_type, "timestamp_ns": timestamp_ns, "data": [float(data.mag[0]), float(data.mag[1]), float(data.mag[2]), 0.0, 0.0, 0.0]})
            for msg in messages:
                if self.imu_callback:
                    self.imu_callback(msg)
        except Exception as exc:
            logger.error("[BspDevice] IMU callback failed: %s", exc, exc_info=True)

    def _on_cam_data(self, sensor_type, image_pair) -> None:
        try:
            if not self.image_callback or sensor_type != Xr.SensorType.Slam:
                return
            from PySide6.QtGui import QImage

            gray_format = getattr(QImage, "Format_Grayscale8", None) or QImage.Format.Format_Grayscale8
            timestamp = int(image_pair.timestamp())
            cam_data = {}
            for idx in range(2):
                bsp_img = image_pair.bspImageAt(idx)
                if bsp_img.isNull():
                    continue
                qimg = bsp_img.image.convertToFormat(gray_format)
                cam_data[idx] = {
                    "image": qimg,
                    "exposure_start_time_device": int(bsp_img.exposure_start_time_device),
                    "exposure_start_time_system": int(bsp_img.exposure_start_time_system),
                    "exposure_duration": int(bsp_img.exposure_duration),
                    "rolling_shutter_time": int(bsp_img.rolling_shutter_time),
                    "stride": int(bsp_img.stride),
                    "gain": float(bsp_img.gain),
                }
            if cam_data:
                first = cam_data[min(cam_data.keys())]
                self.latest_frame_state = {
                    "timestamp_ns": timestamp,
                    "width": int(first["image"].width()),
                    "height": int(first["image"].height()),
                    "exposure_start_time_device": first.get("exposure_start_time_device"),
                    "exposure_start_time_system": first.get("exposure_start_time_system"),
                    "exposure_duration": first.get("exposure_duration"),
                    "rolling_shutter_time": first.get("rolling_shutter_time"),
                    "stride": first.get("stride"),
                    "gain": first.get("gain"),
                }
                self.image_callback({"timestamp": timestamp, "cam_data": cam_data})
        except Exception as exc:
            logger.error("[BspDevice] camera callback failed: %s", exc, exc_info=True)
