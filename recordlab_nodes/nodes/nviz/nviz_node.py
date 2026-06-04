import csv
import os
import queue
import shutil
import subprocess
import threading
import time
from collections import deque
from datetime import datetime
from multiprocessing import Manager
from pathlib import Path
from typing import Any, Dict, Optional

from recordlab_nodes.common.device_checker import LsusbChecker, XrGlassesSSHManager
from recordlab_nodes.common.motion_detector import MotionDetector
from recordlab_nodes.common.topics import TOPIC_IMU, TOPIC_MOTION_STATUS, TOPIC_RECORD_TIMER, TOPIC_TIME_DELAY
from recordlab_nodes.core.main_node import MainNode

from .nviz_assets.nviz_receiver.nreal_link_base import NRealLinkBase, PlotDataMessage
from .nviz_assets.nviz_receiver.nreal_link_tcp import NrealLinkTcpServer
from .nviz_assets.nviz_receiver.payload_parser import PayloadParser


def _ping_glasses(glasses_ip: str = "169.254.2.1") -> tuple[str, bool]:
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "1", glasses_ip],
            capture_output=True,
            text=True,
            timeout=0.5,
        )
        return ("connected", True) if result.returncode == 0 else ("disconnected", False)
    except subprocess.TimeoutExpired:
        return ("timeout", False)
    except Exception:
        return ("error", False)


class XRLinkDevice:
    def __init__(self, asset_root: Path, custom_params: Optional[Dict[str, Any]] = None):
        custom_params = custom_params or {}
        self.asset_root = asset_root
        self.shell_root = asset_root / "shell"
        self.udp_server: Optional[NRealLinkBase] = None
        self.tcp_server: Optional[NrealLinkTcpServer] = None
        self.status_dict = None
        self.initialized = False
        self.started = False
        self.enable_udp = True
        self.enable_tcp = False
        self.device_type = "nviz_ssh_glasses"
        self.lsusb_checker = LsusbChecker()
        self.ssh_manager = XrGlassesSSHManager(
            hostname=str(custom_params.get("ssh_host", "169.254.2.1")),
            port=int(custom_params.get("ssh_port", 22)),
            username=str(custom_params.get("ssh_username", "root")),
            password=str(custom_params.get("ssh_password", "xreal2017")),
        )

    def _shell(self, name: str, *args: str, check: bool = True) -> Dict[str, Any]:
        script = self.shell_root / name
        if not script.exists():
            return {"success": False, "message": f"Shell script not found: {script}"}
        result = subprocess.run(["bash", str(script), *args], capture_output=True, text=True)
        if check and result.returncode != 0:
            return {"success": False, "message": result.stderr.strip() or result.stdout.strip() or f"{name} failed"}
        return {"success": True, "message": result.stdout.strip() or f"{name} executed", "returncode": result.returncode}

    def check_glasses_connectivity(self, glasses_ip: str = "169.254.2.1") -> tuple[bool, str]:
        try:
            result = subprocess.run(
                ["ping", "-c", "1", "-W", "2", glasses_ip],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if result.returncode == 0:
                return True, f"Glasses connected ({glasses_ip})"
            return False, f"Glasses not reachable ({glasses_ip})"
        except subprocess.TimeoutExpired:
            return False, f"Glasses ping timeout ({glasses_ip})"
        except Exception as exc:
            return False, f"Glasses check error: {exc}"

    def check_nviz_capability(self) -> Dict[str, Any]:
        lsusb_info = self.lsusb_checker.check()
        if lsusb_info.get("connected"):
            devices = lsusb_info.get("devices") or []
            blocked = []
            capable = []
            for device in devices:
                catalog = device.get("catalog") or {}
                display_name = catalog.get("display_name") or catalog.get("name") or ",".join(catalog.get("names", [])) or "unknown"
                if catalog.get("supports_nviz"):
                    capable.append(display_name)
                else:
                    color = catalog.get("device_color") or ""
                    reason = "红色/Helen MCU 设备不能使用 nviz" if color == "red" else "该型号未标记为 nviz SSH 设备"
                    blocked.append(f"{display_name}: {reason}")
            if capable:
                return {
                    "success": True,
                    "message": f"NVIZ-capable glasses detected: {', '.join(capable)}",
                    "method": "lsusb",
                    "lsusb": lsusb_info,
                }
            return {
                "success": False,
                "message": "当前连接的眼镜不支持 nviz；所有眼镜可走 BSP，nviz 只支持蓝色/可 SSH 设备。"
                           + (" " + "; ".join(blocked) if blocked else ""),
                "lsusb": lsusb_info,
            }

        if self.ssh_manager.check_connection(timeout_s=2.0):
            return {
                "success": True,
                "message": f"NVIZ-capable glasses detected by SSH: {self.ssh_manager.hostname}",
                "method": "ssh",
            }
        return {
            "success": False,
            "message": "未检测到可 nviz 的蓝色/SSH 眼镜；Helen/红色 MCU 设备不能 nviz，可使用 helen_node 或 BSP。",
            "lsusb": lsusb_info,
        }

    def _wait_for_glasses_reconnect(self, timeout_s: float = 60.0) -> tuple[bool, str]:
        deadline = time.time() + timeout_s
        disconnect_deadline = time.time() + min(5.0, max(1.0, timeout_s / 3.0))
        saw_disconnect = False
        last_connected = False
        last_message = ""
        while time.time() < disconnect_deadline:
            connected, message = self.check_glasses_connectivity()
            last_connected = connected
            last_message = message
            if not connected:
                saw_disconnect = True
                break
            time.sleep(0.5)
        if not saw_disconnect and last_connected:
            return True, f"{last_message} (without observed disconnect)"
        while time.time() < deadline:
            connected, message = self.check_glasses_connectivity()
            if connected:
                phase = "after reboot" if saw_disconnect else "without observed disconnect"
                return True, f"{message} ({phase})"
            time.sleep(0.5)
        return False, "Glasses did not reconnect after pilot start"

    def initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        if self.initialized:
            return {"success": True, "message": "Device already initialized (OK)"}
        connected, message = self.check_glasses_connectivity()
        if not connected:
            return {"success": False, "message": f"Initialize failed: {message}"}
        self.enable_udp = bool(params.get("enable_udp", self.enable_udp))
        self.enable_tcp = bool(params.get("enable_tcp", self.enable_tcp))
        capability = self.check_nviz_capability()
        if not capability.get("success"):
            return capability
        result = self._shell("close_pilot_gf.sh")
        if not result.get("success"):
            return result
        deadline = time.time() + float(params.get("ready_timeout_s", 20.0))
        saw_disconnect = False
        while time.time() < deadline:
            connected, _ = self.check_glasses_connectivity()
            if not connected:
                saw_disconnect = True
                break
            time.sleep(0.5)
        while time.time() < deadline:
            connected, _ = self.check_glasses_connectivity()
            if connected:
                self.initialized = True
                return {"success": True, "message": f"Device initialized ({capability.get('message', 'nviz-capable glasses')})"}
            time.sleep(0.5)
        return {"success": False, "message": "Glasses not ready after initialize" if saw_disconnect else "Glasses did not reboot"}

    def start(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        params = params or {}
        if not self.initialized:
            return {"success": False, "message": "Device not initialized"}
        if self.started:
            return {"success": True, "message": "Device already started"}
        connected, message = self.check_glasses_connectivity()
        if not connected:
            return {"success": False, "message": f"Start failed: {message}"}
        data_type = str(params.get("data_type", "3dof")).lower()
        if data_type != "3dof":
            return {"success": False, "message": f"nviz only supports data_type=3dof, got: {data_type}"}
        config_result = self._shell("gf_3dof_start.sh")
        if not config_result.get("success"):
            return config_result
        pilot_result = self._shell("open_pilot_gf.sh", check=False)
        ready_timeout_s = float(params.get("ready_timeout_s", 60.0))
        ready, ready_message = self._wait_for_glasses_reconnect(ready_timeout_s)
        if not ready:
            return {
                "success": False,
                "message": f"start_device copied 3dof config and ran open_pilot_gf.sh, but device is not ready: {ready_message}",
                "config_message": config_result.get("message", ""),
                "pilot_message": pilot_result.get("message", ""),
            }
        self.started = True
        return {
            "success": True,
            "message": f"start_device ready: 3dof config applied, pilot started, {ready_message}",
            "config_message": config_result.get("message", ""),
            "pilot_message": pilot_result.get("message", ""),
        }

    def stop(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        params = params or {}
        if not self.started:
            return {"success": True, "message": "Device not started"}
        data_type = str(params.get("data_type", "3dof")).lower()
        if data_type != "3dof":
            return {"success": False, "message": f"nviz only supports data_type=3dof, got: {data_type}"}
        script_name = "gf_3dof_end.sh"
        result = self._shell(script_name)
        self.started = False
        return result

    def release(self) -> Dict[str, Any]:
        self.stop({})
        result = self._shell("open_pilot_gf.sh", check=False)
        self.initialized = False
        return {"success": True, "message": result.get("message", "Device released")}


class NvizNode(MainNode):
    def __init__(self, agent_config: Dict[str, Any]):
        super().__init__(agent_config)
        custom = agent_config.get("custom_params", {}) or {}
        self.asset_root = Path(__file__).resolve().parent / "nviz_assets"
        self.device = XRLinkDevice(self.asset_root, custom)
        self.enable_udp = bool(custom.get("enable_udp", custom.get("enable-udp", False)))
        self.enable_tcp = bool(custom.get("enable_tcp", custom.get("enable-tcp", True)))
        self.device_type = "nviz_ssh_glasses"
        self.device.enable_udp = self.enable_udp
        self.device.enable_tcp = self.enable_tcp
        self.device.device_type = self.device_type
        self.recording = False
        self.record_path: Optional[Path] = None
        self.record_dataset_name: Optional[str] = None
        self.record_start_timestamp_ns: Optional[int] = None
        self.connection_info = {"ip": "unknown", "protocol": "unknown"}
        self.motion_detector = MotionDetector(gyro_threshold=0.01, acc_threshold=0.1)
        self.payload_parser = PayloadParser(str(self.asset_root / "plot.json"))
        self.csv_files: Dict[str, Dict[str, Any]] = {}
        self.csv_queue: "queue.Queue[tuple[str, Dict[str, Any]]]" = queue.Queue(maxsize=200000)
        self.csv_writer_running = False
        self.csv_writer_thread: Optional[threading.Thread] = None
        self.queue_full_count = 0
        self.imu_publish_count = 0
        self.stop_device_time = 0.0
        self.start_device_time = 0.0
        self.check_grace_period = 10.0
        self.startup_grace_period = 90.0
        self.last_data_received_time = 0.0
        self.data_timeout_threshold = 3.0
        self.time_delay_window = deque(maxlen=5)
        self._manager = Manager()
        self._start_servers()

    def _start_servers(self) -> None:
        self.device.status_dict = self._manager.dict()
        if self.enable_udp:
            self.device.udp_server = NRealLinkBase(self.device.status_dict)
            self.device.udp_server.start()
            self.device.udp_server.set_plot_data_callback(self._on_plot_data)
            self.connection_info["protocol"] = "UDP"
        if self.enable_tcp:
            self.device.tcp_server = NrealLinkTcpServer(self.device.status_dict)
            self.device.tcp_server.set_connection_callback(self._on_tcp_connection)
            self.device.tcp_server.start()
            self.device.tcp_server.set_plot_data_callback(self._on_plot_data)
            self.connection_info["protocol"] = "TCP"

    def _on_tcp_connection(self, client_address: tuple) -> None:
        if client_address:
            self.connection_info["ip"] = client_address[0]

    def check(self, params: Dict[str, Any]) -> Dict[str, Any]:
        now = time.time()
        if now - self.stop_device_time < self.check_grace_period:
            remaining = self.check_grace_period - (now - self.stop_device_time)
            return {"success": True, "message": f"SubNode running (grace period: {remaining:.1f}s)", "glasses_status": "grace_period"}
        if self.device.started and self.start_device_time > 0 and now - self.start_device_time < self.startup_grace_period:
            if self.last_data_received_time <= self.start_device_time:
                remaining = self.startup_grace_period - (now - self.start_device_time)
                return {"success": True, "message": f"SubNode running (startup grace: {remaining:.1f}s)", "glasses_status": "startup_grace"}
        since_data = now - self.last_data_received_time
        if self.last_data_received_time > 0 and since_data < self.data_timeout_threshold:
            return {"success": True, "message": "SubNode running, Glasses connected [data-based]", "glasses_status": "connected"}
        status, success = _ping_glasses("169.254.2.1") if since_data > 10.0 else ("data_timeout", True)
        return {"success": success, "message": f"SubNode running, Glasses {status}", "glasses_status": status}

    def estop(self, params: Dict[str, Any]) -> Dict[str, Any]:
        self.stop_record({})
        self.device.stop({})
        self.device.initialized = False
        self.device.started = False
        return {"success": True, "message": "Emergency stopped"}

    def shutdown(self) -> None:
        self.estop({})
        self.device.release()
        if self.device.udp_server:
            self.device.udp_server.stop()
        if self.device.tcp_server:
            self.device.tcp_server.stop()
        self._manager.shutdown()

    def init_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(params or {})
        merged.setdefault("enable_udp", self.enable_udp)
        merged.setdefault("enable_tcp", self.enable_tcp)
        merged.setdefault("device_type", self.device_type)
        return self.device.initialize(merged)

    def start_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        result = self.device.start(params or {})
        if result.get("success"):
            self.start_device_time = time.time()
        return result

    def stop_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        if self.recording:
            self.stop_record({})
        self.stop_device_time = time.time()
        return self.device.stop(params or {})

    def release_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        if self.recording:
            self.stop_record({})
        return self.device.release()

    def control_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        command = (params or {}).get("command")
        if command == "restart_tcp" and self.device.tcp_server:
            self.device.tcp_server.stop()
            self.device.tcp_server.start()
            return {"success": True, "message": "TCP server restarted"}
        if command == "restart_udp" and self.device.udp_server:
            self.device.udp_server.stop()
            self.device.udp_server.start()
            return {"success": True, "message": "UDP server restarted"}
        return {"success": False, "message": "Supported commands: restart_tcp, restart_udp"}

    def start_record(self, params: Dict[str, Any]) -> Dict[str, Any]:
        if self.recording:
            return {"success": False, "message": "Already recording"}
        dataset_name = (params or {}).get("dataset_name")
        if not dataset_name:
            return {"success": False, "message": "Missing dataset_name"}
        self.record_dataset_name = str(dataset_name).strip("/\\")
        self.record_path = Path(self.agent_config.get("root_path", "data")) / self.record_dataset_name
        self.record_path.mkdir(parents=True, exist_ok=True)
        result = self.device._shell("gf_3dof_start_record.sh", str(self.record_path), check=True)
        if not result.get("success"):
            return result
        self.recording = True
        self.record_start_timestamp_ns = None
        self._start_csv_writer_thread()
        return {"success": True, "message": f"Recording started: {self.record_dataset_name}", "record_path": str(self.record_path)}

    def stop_record(self, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self.recording:
            return {"success": True, "message": "Not recording"}
        if self.device.tcp_server:
            deadline = time.time() + 10.0
            while time.time() < deadline and self.device.tcp_server.get_total_buffer_size() > 0:
                time.sleep(0.1)
        self.recording = False
        self.record_start_timestamp_ns = None
        self._stop_csv_writer_thread()
        self._close_all_csv_files()
        if self.record_path:
            self.device._shell("gf_3dof_end_record.sh", str(self.record_path), check=False)
        self.queue_full_count = 0
        return {"success": True, "message": "Recording stopped"}

    def _message_key(self, group_id: int, msg_id: int) -> Optional[str]:
        for key, config in self.payload_parser.config.items():
            if config.get("GROUP_ID") == group_id and config.get("MSG_ID") == msg_id:
                return key
        return None

    def _parsed_to_dict(self, plot_msg: PlotDataMessage, parsed: Any) -> Dict[str, Any]:
        if isinstance(parsed, dict):
            return dict(parsed)
        key = self._message_key(plot_msg.group_id, plot_msg.msg_id)
        config = self.payload_parser.config.get(key or "", {})
        fields = config.get("struct", [])
        row: Dict[str, Any] = {}
        idx = 0
        for field in fields:
            parts = field.strip().split()
            if len(parts) < 2:
                continue
            name = parts[1]
            target_name = "timestamp" if name == "ts_us" else name
            if "[" in target_name and "]" in target_name:
                base = target_name.split("[", 1)[0]
                count = int(target_name.split("[", 1)[1].split("]", 1)[0])
                for i in range(count):
                    if idx < len(parsed):
                        row[f"{base}_{i}"] = parsed[idx]
                        idx += 1
            else:
                if idx < len(parsed):
                    row[target_name] = parsed[idx]
                    idx += 1
        return row

    def _on_plot_data(self, plot_msg: PlotDataMessage) -> None:
        self.last_data_received_time = time.time()
        try:
            parsed = self.payload_parser.parse(plot_msg.group_id, plot_msg.msg_id, plot_msg.payload)
        except Exception:
            return
        row = self._parsed_to_dict(plot_msg, parsed)
        if self.recording:
            self._queue_csv(plot_msg, row)
        key = self._message_key(plot_msg.group_id, plot_msg.msg_id)
        if key == "nreal_link":
            self._handle_nreal_link(row)
        self._handle_imu(row)

    def _handle_nreal_link(self, row: Dict[str, Any]) -> None:
        timestamp_ns = int(row.get("timestamp_ns", 0) or time.time_ns())
        delay_0 = float(row.get("delay_seconds_0", 0.0) or 0.0)
        delay_1 = float(row.get("delay_seconds_1", 0.0) or 0.0)
        delay_ns = int(max(delay_0, delay_1) * 1e9)
        self.time_delay_window.append(delay_ns)
        self.publish(TOPIC_TIME_DELAY, {
            "name": TOPIC_TIME_DELAY,
            "timestamp_ns": timestamp_ns,
            "time_delay_ns": max(self.time_delay_window) if self.time_delay_window else delay_ns,
            "status": "valid",
        })

    def _handle_imu(self, row: Dict[str, Any]) -> None:
        try:
            imu_type = int(float(row.get("type", 0)))
        except Exception:
            return
        if imu_type not in {1, 2, 3, 12, 4, 5, 13}:
            return
        imu_msg = {
            "type": imu_type,
            "timestamp_ns": int(float(row.get("timestamp_ns", 0))),
            "data": [float(row.get(f"data{i}", row.get(f"data_{i}", 0.0)) or 0.0) for i in range(6)],
        }
        self.publish(TOPIC_IMU, imu_msg)
        self.imu_publish_count += 1
        if imu_type in {1, 2}:
            self.publish(TOPIC_MOTION_STATUS, self.motion_detector.detect(imu_msg))
        if self.recording and self.record_start_timestamp_ns is None:
            self.record_start_timestamp_ns = int(imu_msg["timestamp_ns"])
        if self.recording and self.record_start_timestamp_ns and self.imu_publish_count % 100 == 0:
            duration_ns = int(imu_msg["timestamp_ns"]) - self.record_start_timestamp_ns
            self.publish(TOPIC_RECORD_TIMER, {
                "name": TOPIC_RECORD_TIMER,
                "timestamp_ns": int(imu_msg["timestamp_ns"]),
                "duration_ns": duration_ns,
                "status": "recording",
            })

    def _generate_filename(self, timestamp_ns: int, key: str) -> str:
        time_str = datetime.fromtimestamp(timestamp_ns / 1e9).strftime("%y_%m_%d_%H_%M_%S")
        return f"{time_str}_{self.connection_info.get('ip', 'unknown')}_{self.connection_info.get('protocol', 'unknown')}_{key}.csv"

    def _queue_csv(self, plot_msg: PlotDataMessage, row: Dict[str, Any]) -> None:
        if not self.record_path:
            return
        key = self._message_key(plot_msg.group_id, plot_msg.msg_id)
        if not key:
            return
        if key not in self.csv_files:
            timestamp_ns = int(float(row.get("timestamp_ns", time.time_ns()) or time.time_ns()))
            path = self.record_path / self._generate_filename(timestamp_ns, key)
            fh = open(path, "w", newline="", encoding="utf-8")
            writer = csv.DictWriter(fh, fieldnames=list(row.keys()))
            writer.writeheader()
            self.csv_files[key] = {"file": fh, "writer": writer, "path": path}
        self.csv_queue.put((key, row))

    def _start_csv_writer_thread(self) -> None:
        if self.csv_writer_running:
            return
        self.csv_writer_running = True
        self.csv_writer_thread = threading.Thread(target=self._csv_writer_worker, name=f"{self.name}_csv_writer", daemon=True)
        self.csv_writer_thread.start()

    def _stop_csv_writer_thread(self) -> None:
        self.csv_writer_running = False
        deadline = time.time() + 10.0
        while not self.csv_queue.empty() and time.time() < deadline:
            time.sleep(0.1)
        if self.csv_writer_thread:
            self.csv_writer_thread.join(timeout=5.0)

    def _csv_writer_worker(self) -> None:
        batch = []
        last_flush = time.time()
        while self.csv_writer_running or not self.csv_queue.empty():
            try:
                batch.append(self.csv_queue.get(timeout=0.1))
            except queue.Empty:
                pass
            should_write = len(batch) >= 5000 or (not self.csv_writer_running and batch)
            should_flush = time.time() - last_flush >= 5.0
            if should_write:
                for key, row in batch:
                    if key in self.csv_files:
                        self.csv_files[key]["writer"].writerow(row)
                batch.clear()
            if should_flush:
                for info in self.csv_files.values():
                    info["file"].flush()
                last_flush = time.time()
        for key, row in batch:
            if key in self.csv_files:
                self.csv_files[key]["writer"].writerow(row)
        for info in self.csv_files.values():
            info["file"].flush()

    def _close_all_csv_files(self) -> None:
        paths = []
        for info in self.csv_files.values():
            info["file"].close()
            paths.append(Path(info["path"]))
        self.csv_files.clear()
        for path in paths:
            sorted_path = Path(str(path).replace("_TCP_", "_").replace("_UDP_", "_"))
            tmp_path = Path(str(sorted_path) + ".tmp")
            try:
                with open(path, "r", encoding="utf-8") as source:
                    lines = source.readlines()
                if len(lines) <= 2:
                    if path != sorted_path:
                        shutil.move(str(path), str(sorted_path))
                    continue
                header, rows = lines[0], lines[1:]
                rows.sort(key=lambda line: float(line.split(",")[1]) if len(line.split(",")) > 1 else 0.0)
                with open(tmp_path, "w", encoding="utf-8") as target:
                    target.write(header)
                    target.writelines(rows)
                shutil.move(str(tmp_path), str(sorted_path))
                if path != sorted_path and path.exists():
                    path.unlink()
            except Exception:
                try:
                    if tmp_path.exists():
                        tmp_path.unlink()
                except Exception:
                    pass
