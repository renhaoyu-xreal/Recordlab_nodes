import csv
import logging
import os
import struct
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from recordlab_nodes.common.topics import TOPIC_ANDROID_IMU, TOPIC_NODE_COOKIE, TOPIC_RECORD_TIMER, TOPIC_TIME_DELAY
from recordlab_nodes.core.main_node import MainNode
from recordlab_nodes.core.record_writers import CsvDataWriter
from recordlab_nodes.protocols.nreal_link.nreal_link_tcp import NrealLinkTcpServer

logger = logging.getLogger(__name__)

ANDROID_TCP_PORT = 8100
ANDROID_RUNTIME_FILES = ("libc++_shared.so", "get_imu_data")
_MOBILE_DATA_STRUCT = struct.Struct("<QQQIffffff")


class AndroidNode(MainNode):
    """Android IMU acquisition node.

    Host commands are exposed as methods because node_runtime dispatches by
    command name. Legacy Android-specific commands are intentionally preserved
    so existing scripts keep working.
    """

    def __init__(self, agent_config: Dict[str, Any]):
        super().__init__(agent_config)
        custom = agent_config.get("custom_params", {}) or {}
        self.tcp_port = int(custom.get("tcp_port", custom.get("tcp-port", ANDROID_TCP_PORT)))
        self.runtime_dir = Path(agent_config.get("android_runtime_dir") or self._default_runtime_dir())
        self.tcp_server: Optional[NrealLinkTcpServer] = None
        self.connection_info = {"ip": "unknown", "protocol": "TCP"}
        self.recording = False
        self.record_csv_path: Optional[str] = None
        self.csv_writer = CsvDataWriter(filename="mobile_data.csv", buffer_size=100)
        self.record_start_ns: Optional[int] = None
        self.record_state_lock = threading.RLock()

        self.adb_imu_process: Optional[subprocess.Popen] = None
        self.adb_load_process: Optional[subprocess.Popen] = None
        self.adb_fan_cycle_process: Optional[subprocess.Popen] = None
        self.adb_gps_cycle_process: Optional[subprocess.Popen] = None

    @staticmethod
    def _default_runtime_dir() -> str:
        return str(Path(__file__).resolve().parents[3] / "resources" / "android_imu" / "arm64-v8a")

    def _run_adb(self, args, timeout=10, allow_failure=False):
        result = subprocess.run(
            ["adb", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0 and not allow_failure:
            message = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(message or f"adb {' '.join(args)} failed")
        return result

    def _check_adb_device(self) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                ["adb", "get-state"],
                capture_output=True,
                text=True,
                timeout=3,
            )
        except FileNotFoundError:
            return False, "adb not found"
        except subprocess.TimeoutExpired:
            return False, "adb get-state timeout"
        state = (result.stdout or result.stderr or "").strip()
        if result.returncode == 0 and state == "device":
            return True, "ADB device connected"
        message = state or f"adb get-state exited {result.returncode}"
        return False, f"ADB device not ready: {message}"

    def _terminate_process(self, attr_name: str) -> None:
        proc = getattr(self, attr_name)
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception as exc:
                logger.warning("[%s] Failed to terminate %s: %s", self.name, attr_name, exc)
        setattr(self, attr_name, None)

    def _set_tcp_port(self, params: Dict[str, Any]) -> None:
        tcp_port = (params or {}).get("tcp_port", (params or {}).get("tcp-port"))
        if tcp_port is None:
            return
        self.tcp_port = int(tcp_port)

    def _start_tcp_server(self) -> None:
        if self.tcp_server is not None:
            return
        self.tcp_server = NrealLinkTcpServer(status_dict={}, port=self.tcp_port)
        self.tcp_server.set_plot_data_callback(self._on_data)
        self.tcp_server.set_connection_callback(self._on_tcp_connection)
        self.tcp_server.start()
        logger.info("[%s] TCP server started on port %s", self.name, self.tcp_port)

    def _stop_tcp_server(self) -> None:
        if self.tcp_server is None:
            return
        self.tcp_server.stop()
        self.tcp_server = None
        logger.info("[%s] TCP server stopped", self.name)

    def _setup_adb_reverse(self) -> None:
        result = subprocess.run(
            ["adb", "reverse", f"tcp:{self.tcp_port}", f"tcp:{self.tcp_port}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"adb reverse failed: {message}")

    def _push_android_runtime_files(self) -> None:
        missing = [
            str(self.runtime_dir / filename)
            for filename in ANDROID_RUNTIME_FILES
            if not (self.runtime_dir / filename).is_file()
        ]
        if missing:
            raise FileNotFoundError("Missing Android runtime files: " + ", ".join(missing))
        for filename in ANDROID_RUNTIME_FILES:
            result = subprocess.run(
                ["adb", "push", str(self.runtime_dir / filename), "/data/local/tmp/"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                message = (result.stderr or result.stdout or "").strip()
                raise RuntimeError(f"adb push {filename} failed: {message}")
        self._run_adb(["shell", "chmod 755 /data/local/tmp/get_imu_data"], timeout=10)

    def _stop_remote_get_imu_data(self) -> None:
        self._terminate_process("adb_imu_process")
        result = subprocess.run(
            ["adb", "shell", "pkill -f get_imu_data"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "").strip()
            logger.info("[%s] pkill get_imu_data returned %s: %s", self.name, result.returncode, message)

    def _start_remote_get_imu_data(self) -> None:
        self._stop_remote_get_imu_data()
        self.adb_imu_process = subprocess.Popen(
            [
                "adb",
                "shell",
                "export LD_LIBRARY_PATH=/data/local/tmp && /data/local/tmp/get_imu_data 127.0.0.1",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.2)
        if self.adb_imu_process.poll() is not None:
            raise RuntimeError("get_imu_data exited immediately after launch")

    def _install_remote_script(self, remote_name: str, content: str) -> None:
        self._run_adb(["root"], timeout=10, allow_failure=True)
        result = subprocess.run(
            ["adb", "shell", f"cat > /data/local/tmp/{remote_name}"],
            input=content,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"install {remote_name} failed: {message}")
        self._run_adb(["shell", f"chmod 755 /data/local/tmp/{remote_name}"], timeout=10)

    def _set_fan_speed(self, speed: int) -> None:
        if speed < 0 or speed > 100:
            raise ValueError("fan speed must be between 0 and 100")
        self._run_adb(["root"], timeout=10, allow_failure=True)
        self._run_adb(["shell", "echo 1 > /sys/class/fan/max31760/speed_fixed_flag"], timeout=10)
        self._run_adb(["shell", f"echo {speed} > /sys/class/fan/max31760/speed_control"], timeout=10)

    def _restore_fan_policy(self) -> None:
        self._run_adb(["root"], timeout=10, allow_failure=True)
        self._run_adb(["shell", "echo 0 > /sys/class/fan/max31760/speed_control"], timeout=10)
        self._run_adb(["shell", "echo 0 > /sys/class/fan/max31760/speed_fixed_flag"], timeout=10)

    def _start_remote_fan_cycle(self) -> None:
        self._stop_remote_fan_cycle()
        script = """#!/system/bin/sh
trap 'echo 0 > /sys/class/fan/max31760/speed_control 2>/dev/null; echo 0 > /sys/class/fan/max31760/speed_fixed_flag 2>/dev/null; exit 0' INT TERM HUP EXIT
echo 1 > /sys/class/fan/max31760/speed_fixed_flag 2>/dev/null
while :; do
  echo 0 > /sys/class/fan/max31760/speed_control 2>/dev/null
  sleep 60
  echo 100 > /sys/class/fan/max31760/speed_control 2>/dev/null
  sleep 60
done
"""
        self._install_remote_script("recordlab_fan_cycle.sh", script)
        self.adb_fan_cycle_process = subprocess.Popen(
            ["adb", "shell", "sh /data/local/tmp/recordlab_fan_cycle.sh"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.2)
        if self.adb_fan_cycle_process.poll() is not None:
            raise RuntimeError("recordlab_fan_cycle.sh exited immediately after launch")

    def _stop_remote_fan_cycle(self) -> None:
        self._terminate_process("adb_fan_cycle_process")
        self._run_adb(["shell", "pkill -f recordlab_fan_cycle.sh"], timeout=10, allow_failure=True)
        try:
            self._restore_fan_policy()
        except Exception as exc:
            logger.warning("[%s] Failed to restore fan policy: %s", self.name, exc)

    def _start_remote_gps_cycle(self) -> None:
        self._stop_remote_gps_cycle()
        script = """#!/system/bin/sh
gps_on() {
  cmd location set-location-enabled true 2>/dev/null
  settings put secure location_providers_allowed +gps 2>/dev/null
}
gps_off() {
  cmd location set-location-enabled false 2>/dev/null
  settings put secure location_providers_allowed -gps 2>/dev/null
}
trap 'gps_off; exit 0' INT TERM HUP EXIT
while :; do
  gps_on
  sleep 60
  gps_off
  sleep 60
done
"""
        self._install_remote_script("recordlab_gps_cycle.sh", script)
        self.adb_gps_cycle_process = subprocess.Popen(
            ["adb", "shell", "sh /data/local/tmp/recordlab_gps_cycle.sh"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.2)
        if self.adb_gps_cycle_process.poll() is not None:
            raise RuntimeError("recordlab_gps_cycle.sh exited immediately after launch")

    def _stop_remote_gps_cycle(self) -> None:
        self._terminate_process("adb_gps_cycle_process")
        self._run_adb(["shell", "pkill -f recordlab_gps_cycle.sh"], timeout=10, allow_failure=True)
        self._run_adb(["shell", "cmd location set-location-enabled false"], timeout=10, allow_failure=True)
        self._run_adb(["shell", "settings put secure location_providers_allowed -gps"], timeout=10, allow_failure=True)

    def _start_remote_load(self, mode: str) -> None:
        if mode not in ("high", "wave"):
            raise ValueError("load mode must be high or wave")
        self._stop_remote_load()
        script = """#!/system/bin/sh
MODE="${1:-high}"
CPU_LOAD='while :; do head -c 1M /dev/urandom | md5sum >/dev/null 2>&1; sleep 0.001; done'
cleanup() { pkill -f recordlab_cpu_load 2>/dev/null; exit 0; }
trap cleanup INT TERM HUP EXIT
if [ "$MODE" = "wave" ]; then
  while :; do sh -c "$CPU_LOAD" recordlab_cpu_load & sleep 60; pkill -f recordlab_cpu_load 2>/dev/null; sleep 60; done
else
  sh -c "$CPU_LOAD" recordlab_cpu_load &
  while :; do sleep 3600; done
fi
"""
        self._install_remote_script("recordlab_load.sh", script)
        self.adb_load_process = subprocess.Popen(
            ["adb", "shell", f"sh /data/local/tmp/recordlab_load.sh {mode}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.2)
        if self.adb_load_process.poll() is not None:
            raise RuntimeError("recordlab_load.sh exited immediately after launch")

    def _stop_remote_load(self) -> None:
        self._terminate_process("adb_load_process")
        self._run_adb(["shell", "pkill -f recordlab_load.sh"], timeout=10, allow_failure=True)
        self._run_adb(["shell", "pkill -f recordlab_cpu_load"], timeout=10, allow_failure=True)

    def _on_tcp_connection(self, client_address: tuple) -> None:
        if client_address:
            self.connection_info["ip"] = client_address[0]
            self.connection_info["protocol"] = "TCP"

    def _generate_mobile_data_filename(self) -> str:
        time_str = datetime.now().strftime("%y_%m_%d_%H_%M_%S")
        ip = self.connection_info.get("ip", "unknown")
        protocol = self.connection_info.get("protocol", "TCP")
        return f"{time_str}_{ip}_{protocol}_mobile_data.csv"

    def _on_data(self, plot_msg) -> None:
        if plot_msg.group_id != 126 or plot_msg.msg_id != 1:
            return
        if len(plot_msg.payload) < _MOBILE_DATA_STRUCT.size:
            logger.warning("[%s] Android payload too short: %s", self.name, len(plot_msg.payload))
            return
        try:
            ts_us, onsensor_ts_ns, timestamp_ns, imu_type, d0, d1, d2, d3, d4, d5 = (
                _MOBILE_DATA_STRUCT.unpack_from(plot_msg.payload)
            )
        except struct.error as exc:
            logger.warning("[%s] Android payload unpack failed: %s", self.name, exc)
            return
        onsensor_ts_us = onsensor_ts_ns / 1000.0
        data = {
            "type": int(imu_type),
            "timestamp": int(ts_us),
            "onsensor_timestamp_us": onsensor_ts_us,
            "timestamp_ns": int(timestamp_ns),
            "data": [float(d0), float(d1), float(d2), float(d3), float(d4), float(d5)],
        }
        self.publish(TOPIC_ANDROID_IMU, data)
        now_ns = time.time_ns()
        payload_timestamp_ns = int(timestamp_ns)
        delay_ns = max(0, now_ns - payload_timestamp_ns) if payload_timestamp_ns > 0 else 0
        self.publish(TOPIC_TIME_DELAY, {
            "name": TOPIC_TIME_DELAY,
            "timestamp_ns": now_ns,
            "time_delay_ns": delay_ns,
            "status": "valid" if payload_timestamp_ns > 0 else "unavailable",
        })
        with self.record_state_lock:
            if self.recording:
                self.csv_writer.write_data({
                    "timestamp": int(ts_us),
                    "onsensor_timestamp_us": onsensor_ts_us,
                    "timestamp_ns": int(timestamp_ns),
                    "type": int(imu_type),
                    "data0": float(d0),
                    "data1": float(d1),
                    "data2": float(d2),
                    "data3": float(d3),
                    "data4": float(d4),
                    "data5": float(d5),
                })
                duration_ns = now_ns - self.record_start_ns if self.record_start_ns else 0
                self.publish(TOPIC_RECORD_TIMER, {
                    "name": TOPIC_RECORD_TIMER,
                    "timestamp_ns": now_ns,
                    "duration_ns": duration_ns,
                    "status": "",
                })

    def _close_all_csv_files(self) -> Optional[str]:
        csv_path = self.record_csv_path
        self.csv_writer.close()
        self.record_csv_path = None
        if not csv_path or not os.path.exists(csv_path):
            return csv_path
        path = Path(csv_path)
        sorted_name = path.name.replace("_TCP_", "_").replace("_UDP_", "_")
        sorted_path = path.with_name(sorted_name)
        try:
            with path.open("r", newline="", encoding="utf-8") as src_file:
                reader = csv.reader(src_file)
                header = next(reader, None)
                rows = list(reader)
            if header:
                rows.sort(key=lambda row: float(row[1]) if len(row) > 1 and row[1] else 0.0)
                tmp_path = sorted_path.with_suffix(sorted_path.suffix + ".tmp")
                with tmp_path.open("w", newline="", encoding="utf-8") as dst_file:
                    writer = csv.writer(dst_file)
                    writer.writerow(header)
                    writer.writerows(rows)
                os.replace(tmp_path, sorted_path)
                if sorted_path != path and path.exists():
                    path.unlink()
                return str(sorted_path)
        except Exception as exc:
            logger.error("[%s] Failed to sort Android CSV %s: %s", self.name, csv_path, exc)
        return csv_path

    def _shutdown(self) -> None:
        with self.record_state_lock:
            if self.recording:
                self.recording = False
                self._close_all_csv_files()
        self._stop_tcp_server()
        for fn in (
            self._stop_remote_gps_cycle,
            self._stop_remote_fan_cycle,
            self._stop_remote_load,
            self._stop_remote_get_imu_data,
        ):
            try:
                fn()
            except Exception as exc:
                logger.warning("[%s] Shutdown cleanup failed: %s", self.name, exc)

    def check(self, params: Dict[str, Any]) -> Dict[str, Any]:
        adb_ok, adb_message = self._check_adb_device()
        if not adb_ok:
            return {"success": False, "message": adb_message}
        if self.tcp_server is None:
            return {"success": True, "message": f"{adb_message}; TCP server not initialized"}
        return {"success": True, "message": f"{adb_message}; TCP server running on {self.tcp_port}"}

    def init_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            self._set_tcp_port(params or {})
            if self.tcp_server is not None:
                self._stop_tcp_server()
            self._setup_adb_reverse()
            self._push_android_runtime_files()
            self._start_tcp_server()
            self.publish_cookie("Android TCP", self.tcp_port, True)
            return {"success": True, "message": f"Android initialized on TCP:{self.tcp_port}"}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def start_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            self._set_tcp_port(params or {})
            if self.tcp_server is None:
                self._start_tcp_server()
            self._start_remote_get_imu_data()
            return {"success": True, "message": "Android IMU device started"}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def restart_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            self._set_tcp_port(params or {})
            with self.record_state_lock:
                if self.recording:
                    self.recording = False
                    self._close_all_csv_files()
            self._stop_tcp_server()
            self._stop_remote_gps_cycle()
            self._stop_remote_fan_cycle()
            self._stop_remote_load()
            self._stop_remote_get_imu_data()
            self._setup_adb_reverse()
            self._push_android_runtime_files()
            self._start_tcp_server()
            self._start_remote_get_imu_data()
            self.publish_cookie("Android TCP", self.tcp_port, True)
            return {"success": True, "message": f"Android device restarted on TCP:{self.tcp_port}"}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def stop_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        if self.recording:
            result = self.stop_record({})
            if not result.get("success"):
                return result
        self._stop_tcp_server()
        for fn in (self._stop_remote_gps_cycle, self._stop_remote_fan_cycle, self._stop_remote_load, self._stop_remote_get_imu_data):
            try:
                fn()
            except Exception as exc:
                logger.warning("[%s] stop_device cleanup failed: %s", self.name, exc)
        return {"success": True, "message": "Android device stopped"}

    def release_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        self._shutdown()
        return {"success": True, "message": "Released"}

    def estop(self, params: Dict[str, Any]) -> Dict[str, Any]:
        self._shutdown()
        return {"success": True, "message": "Emergency stopped"}

    def shutdown(self) -> None:
        self._shutdown()

    def start_record(self, params: Dict[str, Any]) -> Dict[str, Any]:
        dataset_name = (params or {}).get("dataset_name")
        if not dataset_name:
            return {"success": False, "message": "Missing dataset_name"}
        with self.record_state_lock:
            if self.recording:
                return {"success": False, "message": "Already recording"}
            record_path = Path(self.agent_config.get("root_path", "data")) / str(dataset_name).strip("/\\")
            csv_filename = self._generate_mobile_data_filename()
            self.csv_writer = CsvDataWriter(filename=csv_filename, buffer_size=100)
            self.csv_writer.open(str(record_path))
            self.record_csv_path = str(record_path / csv_filename)
            self.recording = True
            self.record_start_ns = time.time_ns()
        return {"success": True, "message": f"Recording started: {dataset_name}", "csv_path": self.record_csv_path}

    def stop_record(self, params: Dict[str, Any]) -> Dict[str, Any]:
        with self.record_state_lock:
            if not self.recording:
                return {"success": True, "message": "Not recording"}
            self.recording = False
            csv_path = self._close_all_csv_files()
            self.record_start_ns = None
        return {"success": True, "message": "Recording stopped", "csv_path": csv_path}

    def set_fan(self, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            speed = int((params or {}).get("speed", 0))
            self._set_fan_speed(speed)
            return {"success": True, "message": f"Fan speed fixed to {speed}"}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def restore_fan(self, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            self._restore_fan_policy()
            return {"success": True, "message": "Fan auto policy restored"}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def start_fan_cycle(self, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            self._start_remote_fan_cycle()
            return {"success": True, "message": "Fan cycle started: 0/100 every 60 seconds"}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def stop_fan_cycle(self, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            self._stop_remote_fan_cycle()
            return {"success": True, "message": "Fan cycle stopped"}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def start_gps_cycle(self, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            self._start_remote_gps_cycle()
            return {"success": True, "message": "GPS cycle started: on/off every 60 seconds"}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def stop_gps_cycle(self, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            self._stop_remote_gps_cycle()
            return {"success": True, "message": "GPS cycle stopped"}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def start_load(self, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            mode = str((params or {}).get("mode", "high")).strip().lower()
            self._start_remote_load(mode)
            return {"success": True, "message": f"Android load started: {mode}"}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def stop_load(self, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            self._stop_remote_load()
            return {"success": True, "message": "Android load stopped"}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def control_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        action = (params or {}).get("action") or (params or {}).get("command")
        if not action:
            return {"success": False, "message": "Missing action"}
        handler = getattr(self, str(action), None)
        if handler is None or not callable(handler) or str(action).startswith("_"):
            return {"success": False, "message": f"Unsupported Android action: {action}"}
        forwarded = dict(params or {})
        forwarded.pop("action", None)
        forwarded.pop("command", None)
        return handler(forwarded)
