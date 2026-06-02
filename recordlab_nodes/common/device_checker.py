"""
Device presence checkers for XREAL glasses.

XrGlassesSSHManager:  SSH-based connectivity check (ping, SSH connection).
LsusbChecker:         lsusb-based USB device detection.

All checkers expose a uniform `check()` → bool interface so BspDevice
can try multiple strategies in order.
"""

import subprocess
import time
from typing import Any, Dict

import paramiko

from recordlab_nodes.common.logger_config import get_logger

logger = get_logger(__name__)


# ── SSH manager (kept from original bsp_device.py) ─────────────

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

    def check(self) -> bool:
        """Return True if the glasses are reachable via SSH."""
        return self.check_connection(timeout_s=5.0)

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
    Detect XREAL glasses via lsusb.

    Typical XREAL VID values:
        - 0x3318  (XR AG)
        - 0x0483  (STMicroelectronics — some dev boards)
    """

    # Known XREAL vendor ids (VID).
    XREAL_VIDS = {0x3318, 0x0483}

    def __init__(self):
        self._last_output: str = ""

    def check(self) -> bool:
        """Return True if any XREAL USB device is present."""
        try:
            result = subprocess.run(
                ["lsusb"], capture_output=True, text=True, timeout=3,
            )
            self._last_output = result.stdout
        except Exception:
            return False

        for vid in self.XREAL_VIDS:
            if f"{vid:04x}:" in self._last_output.lower():
                return True
        return False

    def raw_output(self) -> str:
        """Return the last lsusb output for debugging."""
        return self._last_output or "(not yet executed)"