"""
Device presence checkers for XREAL glasses.

XrGlassesSSHManager:  SSH-based connectivity check (ping, SSH connection).
LsusbChecker:         lsusb-based USB device detection with product catalog.

The catalog maps (vid, pid) tuples to device metadata so callers can
identify exactly which glasses model is connected and choose an
appropriate agent.

All checkers expose a `check()` → dict interface so BspDevice can try
multiple strategies in order.  The return value is always
{"connected": bool, ...} so callers can uniformly query.
"""

import subprocess
import time
from typing import Any, Dict, List, Optional

import paramiko

from recordlab_nodes.common.logger_config import get_logger

logger = get_logger(__name__)


# ── USB product catalog ────────────────────────────────────────

# Each entry describes one XREAL glasses model.
# Fields:
#   vid, pid   USB vendor/product ids (strings like "0x3318").
#   name       Primary codename.
#   names      List of codenames (for models that share a pid).
#   display_name  Human-readable label.
#   agent_name    Which agent config key to activate for this model.
#   default_connection  "lsusb" | "ssh" — preferred check strategy.
#   supports_bsp  Whether the device can be used by glasses_bsp_node.
#   supports_nviz Whether the device can be used by glasses_nviz_node.
#   device_color  "blue" for SSH-capable nviz glasses, "red" for MCU,
#                 "unknown" for ordinary models without a confirmed nviz path.
#   ssh_preferred  Deprecated alias for default_connection="ssh".
_USB_PRODUCT_CATALOG: List[Dict[str, Any]] = [
    {"vid": "0x3318", "pid": "0x0420", "names": ["Air", "P55", "Flora"],
     "display_name": "Air/P55/Flora", "agent_name": "glasses_bsp_node",
     "default_connection": "lsusb", "supports_bsp": True, "supports_nviz": False,
     "device_color": "red", "device_group": "mcu_like",
     "remarks": ["Air: 7911ux=0x0001, vxr7200=0x0002"]},
    {"vid": "0x0000", "pid": "0x1012", "name": "Ada", "agent_name": "glasses_bsp_node",
     "default_connection": "lsusb", "supports_bsp": True, "supports_nviz": False,
     "device_color": "unknown", "device_group": "ordinary_unknown"},
    {"vid": "0x3318", "pid": "0x0433", "name": "Charlie", "agent_name": "glasses_bsp_node",
     "default_connection": "lsusb", "supports_bsp": True, "supports_nviz": False,
     "device_color": "unknown", "device_group": "ordinary_unknown"},
    {"vid": "0x3318", "pid": "0x0434", "name": "CORE", "agent_name": "glasses_bsp_node",
     "default_connection": "lsusb", "supports_bsp": True, "supports_nviz": False,
     "device_color": "unknown", "device_group": "ordinary_unknown"},
    {"vid": "0x3318", "pid": "0x0436", "name": "Gina",
     "agent_name": "glasses_nviz_node", "default_connection": "ssh",
     "supports_bsp": True, "supports_nviz": True, "device_color": "blue",
     "device_group": "ssh_nviz", "remarks": ["0x0001"]},
    {"vid": "0x3318", "pid": "0x0438", "name": "GF",
     "agent_name": "glasses_nviz_node", "default_connection": "ssh",
     "supports_bsp": True, "supports_nviz": True, "device_color": "blue",
     "device_group": "ssh_nviz", "remarks": ["0x0001"]},
    {"vid": "0x3318", "pid": "0x043a", "name": "Hylla",
     "agent_name": "glasses_nviz_node", "default_connection": "ssh",
     "supports_bsp": True, "supports_nviz": True, "device_color": "blue",
     "device_group": "ssh_nviz", "remarks": ["0x0001"]},
    {"vid": "0x3318", "pid": "0x043c", "name": "Core Pro", "agent_name": "glasses_bsp_node",
     "default_connection": "lsusb", "supports_bsp": True, "supports_nviz": False,
     "device_color": "unknown", "device_group": "ordinary_unknown"},
    {"vid": "0x3318", "pid": "0x043e", "name": "GS",
     "agent_name": "glasses_nviz_node", "default_connection": "ssh",
     "supports_bsp": True, "supports_nviz": True, "device_color": "blue",
     "device_group": "ssh_nviz", "remarks": ["0x0001"]},
    {"vid": "0x0b05", "pid": "0x1d9d", "name": "Glory",
     "agent_name": "glasses_nviz_node", "default_connection": "ssh",
     "supports_bsp": True, "supports_nviz": True, "device_color": "blue",
     "device_group": "ssh_nviz"},
    {"vid": "0x3318", "pid": "0x0440", "names": ["Helen", "Helen Pro"],
     "display_name": "Helen/Helen Pro (MCU)", "agent_name": "mcu_node",
     "default_connection": "lsusb", "supports_bsp": True, "supports_nviz": False,
     "device_color": "red", "device_group": "mcu_like"},
]


def _normalise_hex(s: str) -> int:
    return int(s, 16)


def _find_catalog_entry(vid: int, pid: int) -> Optional[Dict[str, Any]]:
    for entry in _USB_PRODUCT_CATALOG:
        if _normalise_hex(entry["vid"]) == vid and _normalise_hex(entry["pid"]) == pid:
            return entry
    return None


# ── SSH manager ────────────────────────────────────────────────

class XrGlassesSSHManager:
    """Manage connectivity checks via SSH to the glasses."""

    def __init__(self, hostname: str = "172.30.1.3", port: int = 22,
                 username: str = "root", password: str = ""):
        self.hostname = hostname
        self.port = port
        self.username = username
        self.password = password

    def ping(self) -> bool:
        """Return True if the glasses respond to a single ICMP ping."""
        try:
            result = subprocess.run(
                ["ping", "-c", "1", "-W", "1", self.hostname],
                capture_output=True, text=True, timeout=2,
            )
            return result.returncode == 0
        except Exception:
            return False

    def check(self) -> Dict[str, Any]:
        """Return {"connected": bool, ...}."""
        ok = self.check_connection(timeout_s=5.0)
        return {"connected": ok, "method": "ssh", "hostname": self.hostname}

    def connect(self, timeout_s: float = 5.0) -> paramiko.SSHClient:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            self.hostname, port=self.port,
            username=self.username, password=self.password,
            timeout=timeout_s,
        )
        return ssh

    def check_connection(self, timeout_s: float = 5.0) -> bool:
        """Open an SSH connection and immediately close it."""
        try:
            ssh = self.connect(timeout_s)
            ssh.close()
            return True
        except Exception:
            return False

    def check_and_wait_restarted(self, timeout_s: float = 5.0) -> Dict[str, Any]:
        """Wait up to timeout_s for the glasses to come back online."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.check_connection(timeout_s=2.0):
                return {"success": True, "message": ""}
            time.sleep(0.5)
        return {"success": False, "message": "SSH connection failed"}

    def save_getprop(self, record_path) -> None:
        """Save Android getprop output to a recording directory."""
        import pathlib as _pathlib
        try:
            ssh = self.connect(5.0)
            stdin, stdout, stderr = ssh.exec_command(
                "/usr/usrdata/bin/getprop", timeout=10,
            )
            out = stdout.read().decode("utf-8", errors="ignore")
            err = stderr.read().decode("utf-8", errors="ignore")
            ssh.close()
            with open(_pathlib.Path(record_path) / "record_info.txt",
                      "a", encoding="utf-8") as fh:
                fh.write(time.strftime("%Y%m%d%H%M%S") + "\n")
                fh.write(out)
                if err:
                    fh.write("\n[stderr]\n" + err)
        except Exception as exc:
            logger.warning("[XrGlassesSSHManager] save_getprop failed: %s", exc)

    def fetch_glass_config(self, record_path) -> None:
        """Copy factory config files from the glasses."""
        import pathlib as _pathlib
        try:
            ssh = self.connect(5.0)
            sftp = ssh.open_sftp()
            try:
                sftp.get(
                    "/factory/glasses_config.json",
                    str(_pathlib.Path(record_path) / "glasses_config.json"),
                )
                sftp.get(
                    "/factory/glasses_config.json",
                    str(_pathlib.Path(record_path) / "glass_config.json"),
                )
            finally:
                sftp.close()
                ssh.close()
        except Exception as exc:
            logger.warning(
                "[XrGlassesSSHManager] fetch_glass_config failed: %s", exc,
            )


# ── lsusb checker ──────────────────────────────────────────────

class LsusbChecker:
    """
    Detect XREAL glasses via lsusb and the USB product catalog.

    Usage::

        checker = LsusbChecker()
        info = checker.check()
        if info["connected"]:
            print(info["catalog"]["display_name"])   # e.g. "Air/P55/Flora"
            print(info["catalog"]["agent_name"])      # e.g. "glasses_nviz_node"
            print(info["catalog"]["default_connection"])  # e.g. "lsusb"
    """

    def __init__(self):
        self._last_output: str = ""
        self._last_info: Dict[str, Any] = {"connected": False,
                                             "method": "lsusb"}

    def check(self) -> Dict[str, Any]:
        """
        Run lsusb and look up every visible (vid, pid) pair against the
        product catalog.  Returns::

            {
                "connected": bool,
                "method": "lsusb",
                "raw_output": "...",           # full lsusb output
                "devices": [                   # list of matched entries
                    {
                        "vid": "0x3318",
                        "pid": "0x0420",
                        "catalog": {...},      # the matching catalog dict
                    },
                    ...
                ],
                # convenience shortcuts for the *first* matched device:
                "catalog": {...},              # first match
                "agent_name": "...",
                "default_connection": "lsusb"|"ssh",
            }
        """
        self._last_output = ""
        try:
            result = subprocess.run(
                ["lsusb"], capture_output=True, text=True, timeout=3,
            )
            self._last_output = result.stdout
        except Exception:
            self._last_info = {"connected": False, "method": "lsusb",
                               "raw_output": self._last_output}
            return self._last_info

        # Parse lsusb output: each line is "Bus NNN Device NNN: ID vvvv:pppp ..."
        matched: List[Dict[str, Any]] = []
        for line in self._last_output.splitlines():
            # Extract "ID vvvv:pppp"
            if "ID " not in line:
                continue
            id_part = line.split("ID ", 1)[1].split(None, 1)[0]  # "vvvv:pppp"
            try:
                vid_str, pid_str = id_part.split(":")
            except ValueError:
                continue
            try:
                vid = int(vid_str, 16)
                pid = int(pid_str, 16)
            except ValueError:
                continue
            entry = _find_catalog_entry(vid, pid)
            if entry is not None:
                matched.append({
                    "vid": f"0x{vid:04x}",
                    "pid": f"0x{pid:04x}",
                    "catalog": entry,
                })

        info: Dict[str, Any] = {
            "connected": len(matched) > 0,
            "method": "lsusb",
            "raw_output": self._last_output,
            "devices": matched,
        }
        if matched:
            first = matched[0]["catalog"]
            info["catalog"] = first
            info["agent_name"] = first.get("agent_name", "")
            info["default_connection"] = first.get("default_connection", "lsusb")
        else:
            info["catalog"] = None
            info["agent_name"] = ""
            info["default_connection"] = "lsusb"

        self._last_info = info
        return info

    def raw_output(self) -> str:
        """Return the last lsusb output for debugging."""
        return self._last_output or "(not yet executed)"
