import os
import re
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from recordlab_nodes.common.topics import TOPIC_RECORD_TIMER, TOPIC_TIME_DELAY
from recordlab_nodes.core.main_node import MainNode

PACKAGE = "com.xreal.evapro.nebula"
REMOTE_DIR = "/sdcard/3dof_data"
BROADCAST_ACTION = "com.xreal.action.SETUP_WIZARD_FINISH"
BROADCAST_RECEIVER = (
    "com.xreal.evapro.nebula/"
    "ai.nreal.nebula.receiver.OOBECompleteReceiver"
)


def now_ns() -> int:
    return time.time_ns()


def default_trial_id() -> str:
    return "nebula_static_" + datetime.now().strftime("%Y%m%d_%H%M%S")


def clean_path_part(value: Any, fallback: str) -> str:
    text = str(value or "").strip() or fallback
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in text)
    return cleaned.strip("_") or fallback


def parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "是", "删除"}


class NebulaNode(MainNode):
    def __init__(self, agent_config: Dict[str, Any]):
        super().__init__(agent_config)
        custom = agent_config.get("custom_params", {}) or {}
        self.remote_dir = str(custom.get("remote_dir", REMOTE_DIR)).strip() or REMOTE_DIR
        self.package_name = str(custom.get("package_name", PACKAGE)).strip() or PACKAGE
        self.serial: Optional[str] = None
        self.phone_ip = ""
        self.recording = False
        self.nebula_started = False
        self.record_start_ns = 0
        self.trial_id = ""
        self.trial_dir: Optional[Path] = None
        self.delete_remote = False
        self.last_pulled_files: list[str] = []
        self._last_csv_rows: dict[str, int] = {}
        self._record_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._timer_thread: Optional[threading.Thread] = None

    def run_adb(
        self,
        args: list[str],
        serial: Optional[str] = None,
        timeout: int = 30,
        allow_failure: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        cmd = ["adb"]
        if serial:
            cmd.extend(["-s", serial])
        cmd.extend(args)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0 and not allow_failure:
            detail = (result.stderr or result.stdout or f"exit code {result.returncode}").strip()
            raise RuntimeError(f"{' '.join(cmd)} failed: {detail}")
        return result

    def shell(
        self,
        serial: Optional[str],
        command: str,
        timeout: int = 30,
        allow_failure: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        return self.run_adb(["shell", command], serial=serial, timeout=timeout, allow_failure=allow_failure)

    def online_devices(self) -> list[str]:
        result = self.run_adb(["devices"], timeout=10)
        devices: list[str] = []
        for line in result.stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                devices.append(parts[0])
        return devices

    def resolve_device(self, serial: Optional[str]) -> str:
        devices = self.online_devices()
        if serial:
            if serial not in devices:
                raise RuntimeError(f"ADB device is not online: {serial}")
            return serial
        if self.serial and self.serial in devices:
            return self.serial
        if not devices:
            raise RuntimeError("No online ADB device")
        if len(devices) > 1:
            raise RuntimeError("Multiple ADB devices online; pass serial")
        return devices[0]

    def get_phone_wlan_ip(self, serial: str) -> str:
        result = self.shell(serial, "ip -f inet addr show wlan0", timeout=10)
        for line in result.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) >= 2 and parts[0] == "inet":
                return parts[1].split("/", 1)[0]
        return ""

    def ping_phone_ip(self, phone_ip: str) -> tuple[bool, str]:
        if not phone_ip:
            return False, "empty phone IP"
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "2", phone_ip],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return True, "ok"
        detail = (result.stderr or result.stdout or "").strip()
        return False, detail or f"ping exited {result.returncode}"

    @staticmethod
    def wifi_serial(phone_ip: str, adb_port: int) -> str:
        return f"{phone_ip}:{adb_port}"

    def connect_wifi_adb(self, phone_ip: str, adb_port: int) -> str:
        serial = self.wifi_serial(phone_ip, adb_port)
        self.run_adb(["connect", serial], timeout=15)
        time.sleep(1.0)
        devices = self.online_devices()
        if serial not in devices:
            raise RuntimeError(f"ADB Wi-Fi device did not come online: {serial}")
        return serial

    def prepare_wifi_adb(self, usb_serial: str, phone_ip: str, adb_port: int) -> str:
        if not phone_ip:
            raise RuntimeError("Cannot prepare Wi-Fi ADB without phone_ip")
        self.run_adb(["tcpip", str(adb_port)], serial=usb_serial, timeout=15)
        time.sleep(2.0)
        return self.connect_wifi_adb(phone_ip, adb_port)

    def ensure_remote_dir(self, serial: str, remote_dir: str) -> None:
        self.shell(serial, f'test -d "{remote_dir}" || mkdir -p "{remote_dir}"')

    def list_remote_csv(self, serial: str, remote_dir: str) -> list[str]:
        command = f'for f in "{remote_dir}"/*.csv; do [ -e "$f" ] && echo "$f"; done; true'
        result = self.shell(serial, command)
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def list_remote_csv_rows(self, serial: str, remote_dir: str) -> dict[str, int]:
        command = f'for f in "{remote_dir}"/*.csv; do [ -e "$f" ] && wc -l "$f"; done; true'
        result = self.shell(serial, command, timeout=10)
        rows: dict[str, int] = {}
        for line in result.stdout.splitlines():
            parts = line.strip().split(maxsplit=1)
            if len(parts) == 2:
                try:
                    rows[parts[1]] = int(parts[0])
                except ValueError:
                    pass
        return rows

    def read_remote_latest_csv_lines(self, serial: str, remote_dir: str) -> dict[str, str]:
        latest_lines: dict[str, str] = {}
        for remote_file in self.list_remote_csv(serial, remote_dir):
            result = self.shell(serial, f'tail -n 1 "{remote_file}"', timeout=10, allow_failure=True)
            latest_lines[os.path.basename(remote_file)] = (result.stdout or "").strip() or "--"
        return latest_lines

    def clear_remote_csv(self, serial: str, remote_dir: str) -> None:
        self.shell(serial, f'rm -f "{remote_dir}"/*.csv')

    def force_stop_nebula(self, serial: str) -> None:
        self.run_adb(["shell", "am", "force-stop", self.package_name], serial=serial, timeout=10)
        self.nebula_started = False

    def broadcast_start_nebula(self, serial: str) -> None:
        self.run_adb(
            ["shell", "am", "broadcast", "-a", BROADCAST_ACTION, "-n", BROADCAST_RECEIVER],
            serial=serial,
            timeout=10,
        )
        self.nebula_started = True

    def _ensure_timer_thread(self) -> None:
        if self._timer_thread and self._timer_thread.is_alive():
            return
        self._timer_thread = threading.Thread(target=self._record_timer_loop, daemon=True)
        self._timer_thread.start()

    def _record_timer_loop(self) -> None:
        while not self._stop_event.is_set():
            with self._record_lock:
                recording = self.recording
                start_ns = self.record_start_ns
            if recording and start_ns > 0:
                ts = now_ns()
                self.publish(TOPIC_RECORD_TIMER, {
                    "name": TOPIC_RECORD_TIMER,
                    "timestamp_ns": ts,
                    "duration_ns": ts - start_ns,
                    "status": "recording",
                })
            time.sleep(0.2)

    def _runtime_state(self) -> dict[str, Any]:
        with self._record_lock:
            elapsed = (now_ns() - self.record_start_ns) / 1e9 if self.recording and self.record_start_ns else 0.0
            return {
                "serial": self.serial or "",
                "phone_ip": self.phone_ip,
                "remote_dir": self.remote_dir,
                "recording": self.recording,
                "elapsed_seconds": elapsed,
                "trial_id": self.trial_id,
                "trial_dir": str(self.trial_dir) if self.trial_dir else "",
                "pulled_files": list(self.last_pulled_files),
                "nebula_started": self.nebula_started,
            }

    def _summary_state(self) -> dict[str, Any]:
        base = self._runtime_state()
        try:
            phone_ip_hint = self.phone_ip.strip()
            serial_hint = self.serial
            if serial_hint is None and phone_ip_hint:
                try:
                    serial_hint = self.connect_wifi_adb(phone_ip_hint, 5555)
                except Exception:
                    serial_hint = None
            serial = self.resolve_device(serial_hint)
            self.ensure_remote_dir(serial, self.remote_dir)
            csv_rows = self.list_remote_csv_rows(serial, self.remote_dir)
            csv_growing = False
            if csv_rows and self._last_csv_rows:
                csv_growing = any(rows > self._last_csv_rows.get(path, -1) for path, rows in csv_rows.items())
            self._last_csv_rows = csv_rows
            latest_lines = self.read_remote_latest_csv_lines(serial, self.remote_dir)
            latest_update_time = datetime.now().strftime("%H:%M:%S") if latest_lines else ""
            self._publish_time_delay(latest_lines)
            return {
                **base,
                "success": True,
                "message": "runtime state",
                "csv_rows": csv_rows,
                "csv_growing": csv_growing,
                "latest_csv_lines": latest_lines,
                "latest_update_time": latest_update_time,
            }
        except Exception as exc:
            self._publish_time_delay({})
            return {
                **base,
                "success": True,
                "message": str(exc),
                "csv_rows": {},
                "csv_growing": False,
                "latest_csv_lines": {},
                "latest_update_time": "",
            }

    def pull_remote_files(self, serial: str, remote_files: list[str], trial_dir: Path) -> list[Path]:
        pulled: list[Path] = []
        for remote_file in remote_files:
            self.run_adb(["pull", remote_file, str(trial_dir)], serial=serial, timeout=60)
            pulled.append(trial_dir / os.path.basename(remote_file))
        return pulled

    def validate_pulled_files(
        self,
        paths: list[Path],
        require_mobile_csv: bool = True,
        require_air_csv: bool = True,
    ) -> tuple[bool, list[str]]:
        errors: list[str] = []
        names = [path.name for path in paths]
        if require_mobile_csv and not any(name.endswith("_mobile_data.csv") for name in names):
            errors.append("Missing *_mobile_data.csv")
        if require_air_csv and not any(name.endswith("_air_data.csv") for name in names):
            errors.append("Missing *_air_data.csv")
        for path in paths:
            if not path.exists():
                errors.append(f"Missing local file: {path}")
            elif path.stat().st_size <= 0:
                errors.append(f"Empty local file: {path}")
        return not errors, errors

    def delete_remote_files(self, serial: str, remote_files: list[str]) -> None:
        if not remote_files:
            return
        quoted = " ".join(f'"{path}"' for path in remote_files)
        self.shell(serial, f"rm -f {quoted}")

    def check(self, params: Dict[str, Any]) -> Dict[str, Any]:
        serial_hint = str((params or {}).get("serial") or self.serial or "").strip() or None
        try:
            phone_ip_hint = str((params or {}).get("phone_ip") or self.phone_ip or "").strip()
            adb_port = int((params or {}).get("adb_port") or 5555)
            if serial_hint is None and phone_ip_hint:
                try:
                    self.connect_wifi_adb(phone_ip_hint, adb_port)
                    serial_hint = self.wifi_serial(phone_ip_hint, adb_port)
                except Exception:
                    serial_hint = None
            serial = self.resolve_device(serial_hint)
            remote_dir = str((params or {}).get("remote_dir") or self.remote_dir or REMOTE_DIR).strip() or REMOTE_DIR
            self.ensure_remote_dir(serial, remote_dir)
            package = self.shell(serial, f'pm path "{self.package_name}"', timeout=10, allow_failure=True)
            package_visible = package.returncode == 0 and bool(package.stdout.strip())
            if not package_visible:
                return {
                    "success": False,
                    "message": f"Nebula package not found: {self.package_name}",
                    "serial": serial,
                    "remote_dir": remote_dir,
                    "package_visible": False,
                    "recording": self.recording,
                }
            csv_rows = self.list_remote_csv_rows(serial, remote_dir)
            csv_growing = False
            if csv_rows and self._last_csv_rows:
                csv_growing = any(rows > self._last_csv_rows.get(path, -1) for path, rows in csv_rows.items())
            self._last_csv_rows = csv_rows
            return {
                "success": True,
                "message": "Nebula check ok",
                "serial": serial,
                "remote_dir": remote_dir,
                "package_visible": package_visible,
                "recording": self.recording,
                "csv_rows": csv_rows,
                "csv_growing": csv_growing,
            }
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def estop(self, params: Dict[str, Any]) -> Dict[str, Any]:
        with self._record_lock:
            self.recording = False
        if self.serial:
            self.force_stop_nebula(self.serial)
        return {"success": True, "message": "Emergency stop executed"}

    def shutdown(self) -> None:
        self._stop_event.set()
        with self._record_lock:
            self.recording = False
        if self.serial:
            try:
                self.force_stop_nebula(self.serial)
            except Exception:
                pass
        if self._timer_thread and self._timer_thread.is_alive():
            self._timer_thread.join(timeout=2.0)

    def init_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        adb_port = int((params or {}).get("adb_port") or 5555)
        enable_wifi_adb = parse_bool((params or {}).get("enable_wifi_adb"), True)
        serial = self.resolve_device(str((params or {}).get("serial") or "").strip() or None)
        remote_dir = str((params or {}).get("remote_dir") or REMOTE_DIR).strip() or REMOTE_DIR
        phone_ip = str((params or {}).get("phone_ip") or "").strip() or self.get_phone_wlan_ip(serial)
        if parse_bool((params or {}).get("require_ping"), True):
            ping_ok, ping_detail = self.ping_phone_ip(phone_ip)
            if not ping_ok:
                raise RuntimeError(f"Phone IP is not reachable: {phone_ip}. {ping_detail}")
        if enable_wifi_adb:
            if ":" in serial and serial.startswith(phone_ip):
                wifi_serial = serial
            else:
                wifi_serial = self.prepare_wifi_adb(serial, phone_ip, adb_port)
            serial = wifi_serial
        self.ensure_remote_dir(serial, remote_dir)
        self.serial = serial
        self.phone_ip = phone_ip
        self.remote_dir = remote_dir
        self.publish_cookie("Nebula serial", serial, True)
        if phone_ip:
            self.publish_cookie("Nebula phone_ip", phone_ip, True)
        return {
            "success": True,
            "message": "Nebula device initialized",
            "serial": serial,
            "phone_ip": phone_ip,
            "adb_port": adb_port,
            "wifi_adb": enable_wifi_adb,
            "remote_dir": remote_dir,
        }

    def start_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        serial = self.resolve_device(str((params or {}).get("serial") or self.serial or "").strip() or None)
        remote_dir = str((params or {}).get("remote_dir") or self.remote_dir or REMOTE_DIR).strip() or REMOTE_DIR
        stop_delay = float((params or {}).get("stop_delay_seconds", 5.0))
        self.force_stop_nebula(serial)
        time.sleep(max(0.0, stop_delay))
        self.ensure_remote_dir(serial, remote_dir)
        self.clear_remote_csv(serial, remote_dir)
        remaining = self.list_remote_csv(serial, remote_dir)
        if remaining:
            raise RuntimeError("Remote CSV directory is not empty after cleanup: " + ", ".join(remaining))
        self.serial = serial
        self.remote_dir = remote_dir
        self._last_csv_rows = {}
        return {"success": True, "message": "Nebula prepared", "serial": serial, "remote_dir": remote_dir}

    def stop_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        with self._record_lock:
            self.recording = False
        if self.serial:
            self.force_stop_nebula(self.serial)
        return {"success": True, "message": "Nebula stopped", **self._runtime_state()}

    def release_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        self.stop_device(params)
        self.serial = None
        self.phone_ip = ""
        self.nebula_started = False
        return {"success": True, "message": "Nebula released"}

    def control_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {"success": False, "message": "Nebula control_device is not implemented"}

    def start_record(self, params: Dict[str, Any]) -> Dict[str, Any]:
        with self._record_lock:
            if self.recording:
                return {"success": True, "message": "Already recording", **self._runtime_state()}
            self.trial_id = clean_path_part((params or {}).get("trial_id"), default_trial_id())
            out_root = Path(str((params or {}).get("out_root") or self.agent_config.get("root_path", "data")))
            self.trial_dir = out_root / self.trial_id
            self.delete_remote = parse_bool((params or {}).get("delete_remote"), False)
            serial = self.resolve_device(str((params or {}).get("serial") or self.serial or "").strip() or None)
            self.broadcast_start_nebula(serial)
            self.serial = serial
            self.record_start_ns = now_ns()
            self.last_pulled_files = []
            self.recording = True
            self._last_csv_rows = {}
        self._ensure_timer_thread()
        return {"success": True, "message": "Nebula record timer started", **self._runtime_state()}

    def stop_record(self, params: Dict[str, Any]) -> Dict[str, Any]:
        serial = self.resolve_device(str((params or {}).get("serial") or self.serial or "").strip() or None)
        remote_dir = str((params or {}).get("remote_dir") or self.remote_dir or REMOTE_DIR).strip() or REMOTE_DIR
        flush_wait = float((params or {}).get("flush_wait_seconds", 3.0))

        with self._record_lock:
            was_recording = self.recording
            self.recording = False

        self.force_stop_nebula(serial)
        time.sleep(max(0.0, flush_wait))
        remote_files = self.list_remote_csv(serial, remote_dir)
        if not remote_files:
            raise RuntimeError(f"No CSV files found in {remote_dir}")

        trial_dir = self.trial_dir or (Path(self.agent_config.get("root_path", "data")) / clean_path_part((params or {}).get("trial_id"), default_trial_id()))
        if trial_dir.exists():
            if not trial_dir.is_dir():
                raise RuntimeError(f"Trial path exists and is not a directory: {trial_dir}")
        else:
            trial_dir.mkdir(parents=True)

        pulled = self.pull_remote_files(serial, remote_files, trial_dir)
        require_mobile_csv = parse_bool((params or {}).get("require_mobile_csv"), True)
        require_air_csv = parse_bool((params or {}).get("require_air_csv"), True)
        ok, errors = self.validate_pulled_files(
            pulled,
            require_mobile_csv=require_mobile_csv,
            require_air_csv=require_air_csv,
        )
        if not ok:
            raise RuntimeError("Pulled files failed validation: " + "; ".join(errors))

        delete_remote = parse_bool((params or {}).get("delete_remote"), self.delete_remote)
        if delete_remote:
            self.delete_remote_files(serial, remote_files)

        self.trial_dir = trial_dir
        self.last_pulled_files = [str(path) for path in pulled]
        return {
            "success": True,
            "message": "Nebula record stopped",
            "was_recording": was_recording,
            "trial_dir": str(trial_dir),
            "pulled_files": self.last_pulled_files,
            "deleted_remote": delete_remote,
        }

    def get_runtime_state(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return self._summary_state()

    def _publish_time_delay(self, latest_lines: dict[str, str]) -> None:
        now = now_ns()
        latest_timestamp_ns = self._extract_latest_timestamp_ns(latest_lines)
        if latest_timestamp_ns is None:
            self.publish(TOPIC_TIME_DELAY, {
                "name": TOPIC_TIME_DELAY,
                "timestamp_ns": now,
                "time_delay_ns": 0,
                "status": "unavailable",
            })
            return
        self.publish(TOPIC_TIME_DELAY, {
            "name": TOPIC_TIME_DELAY,
            "timestamp_ns": now,
            "time_delay_ns": max(0, now - latest_timestamp_ns),
            "status": "estimated",
        })

    @staticmethod
    def _extract_latest_timestamp_ns(latest_lines: dict[str, str]) -> Optional[int]:
        candidates: list[int] = []
        for line in latest_lines.values():
            for token in re.findall(r"\d+", str(line)):
                try:
                    value = int(token)
                except ValueError:
                    continue
                if value >= 10**16:
                    candidates.append(value)
                elif value >= 10**13:
                    candidates.append(value * 1000)
        if not candidates:
            return None
        return max(candidates)
