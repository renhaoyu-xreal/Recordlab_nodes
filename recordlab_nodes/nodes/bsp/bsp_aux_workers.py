import csv
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional, Tuple

import paramiko

from recordlab_nodes.common.logger_config import get_logger

logger = get_logger(__name__)


class XrSshConfig:
    hostname = "169.254.2.1"
    port = 22
    username = "root"
    password = "xreal2017"


class ScreenCaptureHelper:
    width = 3840
    height = 1200
    expected_yuv_size = int(width * height * 1.5)
    display_debug_cmd = "/usr/usrdata/bin/display_debug capture"

    def __init__(self, ssh_config: Optional[XrSshConfig] = None):
        self.ssh_config = ssh_config or XrSshConfig()
        self.ssh: Optional[paramiko.SSHClient] = None

    def close(self) -> None:
        if self.ssh:
            try:
                self.ssh.close()
            except Exception:
                pass
            self.ssh = None

    def _get_ssh(self) -> paramiko.SSHClient:
        if self.ssh is not None:
            transport = self.ssh.get_transport()
            if transport is not None and transport.is_active():
                return self.ssh
            self.close()
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            self.ssh_config.hostname,
            port=self.ssh_config.port,
            username=self.ssh_config.username,
            password=self.ssh_config.password,
            timeout=10,
        )
        self.ssh = ssh
        return ssh

    def _run(self, ssh: paramiko.SSHClient, command: str, timeout: int = 10) -> Tuple[int, str, str]:
        stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="ignore").strip()
        err = stderr.read().decode("utf-8", errors="ignore").strip()
        return stdout.channel.recv_exit_status(), out, err

    def capture_and_process(self):
        import numpy as np

        ssh = self._get_ssh()
        self._run(ssh, "rm -f /usrdata/dump_vi_*.yuv 2>/dev/null", timeout=5)
        code, _, err = self._run(ssh, self.display_debug_cmd, timeout=10)
        if code != 0:
            logger.warning("[ScreenCaptureHelper] display_debug failed: %s", err)
            return None, None
        yuv_path = None
        deadline = time.time() + 3.0
        while time.time() < deadline:
            _, out, _ = self._run(ssh, "ls -t /usrdata/dump_vi_*.yuv 2>/dev/null | head -1", timeout=5)
            if out:
                yuv_path = out
                break
            time.sleep(0.1)
        if not yuv_path:
            return None, None
        stdin, stdout, stderr = ssh.exec_command(f"cat {yuv_path}", timeout=10)
        yuv_data = stdout.read()
        ssh.exec_command(f"rm -f {yuv_path}")
        if len(yuv_data) != self.expected_yuv_size:
            logger.warning("[ScreenCaptureHelper] unexpected yuv size: %s", len(yuv_data))
            return None, None
        y_size = self.width * self.height
        uv_size = y_size // 4
        y = np.frombuffer(yuv_data[:y_size], dtype=np.uint8).reshape((self.height, self.width))
        u = np.frombuffer(yuv_data[y_size:y_size + uv_size], dtype=np.uint8).reshape((self.height // 2, self.width // 2))
        v = np.frombuffer(yuv_data[y_size + uv_size:], dtype=np.uint8).reshape((self.height // 2, self.width // 2))
        u = np.repeat(np.repeat(u, 2, axis=0), 2, axis=1).astype(np.float32) - 128
        v = np.repeat(np.repeat(v, 2, axis=0), 2, axis=1).astype(np.float32) - 128
        y = y.astype(np.float32)
        r = np.clip(y + 1.402 * v, 0, 255).astype(np.uint8)
        g = np.clip(y - 0.344136 * u - 0.714136 * v, 0, 255).astype(np.uint8)
        b = np.clip(y + 1.772 * u, 0, 255).astype(np.uint8)
        rgb = np.stack([r, g, b], axis=-1)
        return (float(np.mean(r)), float(np.mean(g)), float(np.mean(b))), rgb

    def save_screenshot(self, rgb_array, filepath: str) -> bool:
        from PIL import Image

        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(rgb_array, mode="RGB").save(filepath, "PNG")
        return True


class ScreenCaptureWorker:
    def __init__(self, save_dir: str, capture_helper: Optional[ScreenCaptureHelper] = None):
        self.save_dir = Path(save_dir)
        self.capture_helper = capture_helper or ScreenCaptureHelper()
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.capture_interval_s = 10.0
        self.screenshot_interval_s = 60.0
        self.csv_file = None
        self.csv_writer = None
        self.last_screenshot_time = 0.0
        self.screenshot_count = 0

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        (self.save_dir / "screenshots").mkdir(parents=True, exist_ok=True)
        self.csv_file = open(self.save_dir / "record_screen_rgb_info.csv", "w", encoding="utf-8", newline="")
        self.csv_writer = csv.writer(self.csv_file)
        self.csv_writer.writerow(["timestamps_ns", "r_mean", "g_mean", "b_mean"])
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if not self.running:
            return
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=15.0)
        self._capture("screen_end")
        if self.csv_file:
            self.csv_file.close()
        self.capture_helper.close()

    def _capture(self, screenshot_name: Optional[str] = None) -> None:
        rgb_mean, rgb_array = self.capture_helper.capture_and_process()
        if not rgb_mean:
            return
        self.csv_writer.writerow([time.time_ns(), f"{rgb_mean[0]:.4f}", f"{rgb_mean[1]:.4f}", f"{rgb_mean[2]:.4f}"])
        self.csv_file.flush()
        if screenshot_name and rgb_array is not None:
            self.capture_helper.save_screenshot(rgb_array, str(self.save_dir / "screenshots" / f"{screenshot_name}.png"))

    def _loop(self) -> None:
        self._capture("screen_start")
        self.last_screenshot_time = time.monotonic()
        while self.running:
            started = time.monotonic()
            try:
                name = None
                if started - self.last_screenshot_time >= self.screenshot_interval_s:
                    self.screenshot_count += 1
                    name = f"screen_{self.screenshot_count}min"
                    self.last_screenshot_time = started
                self._capture(name)
            except Exception as exc:
                logger.warning("[ScreenCaptureWorker] capture failed: %s", exc)
            time.sleep(max(0.0, self.capture_interval_s - (time.monotonic() - started)))


class MicRecordWorker:
    def __init__(self, save_dir: str):
        self.save_dir = Path(save_dir)
        self.process: Optional[subprocess.Popen] = None
        self.thread: Optional[threading.Thread] = None
        self.running = False

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._record, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.running = False
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5.0)

    def _record(self) -> None:
        output_path = self.save_dir / "mic_record.wav"
        try:
            device, info = self._detect_device()
            self._append_record_info(info)
            if not device:
                return
            fmt, rate, channels = "S16_LE", "16000", "2"
            cmd = ["arecord", "-D", device, "-f", fmt, "-r", rate, "-c", channels, str(output_path)]
            self._append_record_info("record command: " + " ".join(cmd))
            self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.process.communicate()
        except Exception as exc:
            logger.warning("[MicRecordWorker] failed: %s", exc)

    def _detect_device(self):
        try:
            result = subprocess.run(["arecord", "-l"], capture_output=True, text=True, timeout=10)
            card_index = "1"
            for line in result.stdout.splitlines():
                if "XREAL" in line or "Aura" in line:
                    match = re.search(r"card (\d+):", line)
                    if match:
                        card_index = match.group(1)
                        break
            return f"hw:{card_index},0", f"arecord -l:\n{result.stdout}\nselected: hw:{card_index},0"
        except Exception as exc:
            return None, f"detect audio device failed: {exc}"

    def _append_record_info(self, text: str) -> None:
        try:
            with open(self.save_dir / "record_info.txt", "a", encoding="utf-8") as fh:
                fh.write(text + "\n")
        except Exception:
            pass
