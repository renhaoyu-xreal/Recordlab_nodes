import queue
import struct
import threading
import time
from multiprocessing import shared_memory
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from recordlab_nodes.common.logger_config import get_logger

logger = get_logger(__name__)


CAMERA_SHM_NAME = "recordlab_camera_shm_v1"
CAMERA_SHM_CAM_COUNT = 2
CAMERA_SHM_SLOT_COUNT = 4
CAMERA_SHM_META_SIZE = 64
CAMERA_SHM_SLOT_SIZE = 4 * 1024 * 1024
CAMERA_SHM_SEQ_SIZE = CAMERA_SHM_CAM_COUNT * CAMERA_SHM_SLOT_COUNT * 8
CAMERA_SHM_TOTAL_SIZE = CAMERA_SHM_SEQ_SIZE + CAMERA_SHM_CAM_COUNT * CAMERA_SHM_SLOT_COUNT * CAMERA_SHM_SLOT_SIZE


def exposure_middle_time_ns(cam_info: Dict[str, Any]) -> int:
    return int(
        int(cam_info["exposure_start_time_device"])
        + int(cam_info["exposure_duration"]) / 2
        + int(cam_info["rolling_shutter_time"]) / 2
    )


class SlamImageDataWriter:
    """Writes stereo SLAM grayscale frames as PGM plus sidecar metadata."""

    cam_count = 2

    def __init__(self, buffer_size: int = 100):
        self.buffer_size = buffer_size
        self.folder_path: Optional[Path] = None
        self.is_open = False
        self.cam_counters: Dict[int, int] = {}
        self.save_queue: Optional[queue.Queue] = None
        self.save_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()

    def open(self, folder_path: str) -> bool:
        try:
            self.close()
            self.folder_path = Path(folder_path)
            self.cam_counters = {}
            for idx in range(self.cam_count):
                cam_dir = self.folder_path / f"cam{idx}" / "images"
                cam_dir.mkdir(parents=True, exist_ok=True)
                self.cam_counters[idx] = 0
            self.stop_event.clear()
            self.save_queue = queue.Queue(maxsize=self.buffer_size)
            self.save_thread = threading.Thread(target=self._save_worker, daemon=True)
            self.save_thread.start()
            self.is_open = True
            return True
        except Exception as exc:
            logger.error("[SlamImageDataWriter] open failed: %s", exc, exc_info=True)
            self.close()
            return False

    def write_data(self, image_message: Dict[str, Any]) -> bool:
        if not self.is_open or not self.save_queue:
            return False
        try:
            self.save_queue.put_nowait(image_message)
            return True
        except queue.Full:
            logger.warning("[SlamImageDataWriter] save queue full, dropping frame")
            return False

    def _save_worker(self) -> None:
        while not self.stop_event.is_set() or (self.save_queue and not self.save_queue.empty()):
            try:
                image_message = self.save_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self._save_image_data(image_message)
            except Exception as exc:
                logger.error("[SlamImageDataWriter] save worker failed: %s", exc, exc_info=True)
            finally:
                self.save_queue.task_done()

    def _save_image_data(self, image_message: Dict[str, Any]) -> None:
        if self.folder_path is None:
            return
        cam_data = image_message.get("cam_data", {})
        for idx in range(self.cam_count):
            if idx not in cam_data:
                continue
            data = cam_data[idx]
            qimg = data.get("image")
            if qimg is None:
                continue
            counter = self.cam_counters.get(idx, 0)
            filename = f"m{counter:07d}.pgm"
            self.cam_counters[idx] = counter + 1
            cam_dir = self.folder_path / f"cam{idx}" / "images"
            image_path = cam_dir / filename
            qimg.save(str(image_path))
            middle_ns = exposure_middle_time_ns(data)
            with open(cam_dir / "metadata.txt", "a", encoding="utf-8", newline="") as fh:
                fh.write(
                    f"{filename} {middle_ns} {data['exposure_duration']} {data['gain']} "
                    f"{data['exposure_start_time_system']} {data['exposure_start_time_device']} "
                    f"{data['rolling_shutter_time']} {data['stride']}\n"
                )
            with open(cam_dir / "timestamps.txt", "a", encoding="utf-8", newline="") as fh:
                fh.write(f"{filename} {middle_ns * 1e-9}\n")

    def close(self) -> None:
        if not self.is_open and not self.save_queue:
            return
        if self.save_queue:
            try:
                self.save_queue.join()
            except Exception:
                pass
        self.stop_event.set()
        if self.save_thread and self.save_thread.is_alive():
            self.save_thread.join(timeout=5.0)
        self.save_queue = None
        self.save_thread = None
        self.is_open = False
        self.cam_counters = {}


class CameraSharedMemoryWriter:
    """Writes raw preview frames into POSIX shared memory.

    The echo topic carries only metadata and shm_seq; frame bytes live here.
    Layout matches the C++ host reader:
      seq[camera][slot]: uint64 little-endian
      slot header: width,height,qt_format,data_size,bytes_per_line,encoding
      slot payload: raw QImage bytes
    """

    def __init__(self, name: str = CAMERA_SHM_NAME):
        self.name = name
        self.shm: Optional[shared_memory.SharedMemory] = None
        self.frame_seq = {idx: 0 for idx in range(CAMERA_SHM_CAM_COUNT)}
        self.warned_create_failure = False

    def ensure_open(self) -> bool:
        if self.shm is not None:
            return True
        try:
            try:
                self.shm = shared_memory.SharedMemory(
                    name=self.name,
                    create=True,
                    size=CAMERA_SHM_TOTAL_SIZE,
                )
            except FileExistsError:
                self.shm = shared_memory.SharedMemory(name=self.name, create=False)
                if self.shm.size < CAMERA_SHM_TOTAL_SIZE:
                    self.shm.close()
                    self.shm = None
                    try:
                        stale = shared_memory.SharedMemory(name=self.name, create=False)
                        stale.unlink()
                        stale.close()
                    except Exception:
                        pass
                    self.shm = shared_memory.SharedMemory(
                        name=self.name,
                        create=True,
                        size=CAMERA_SHM_TOTAL_SIZE,
                    )
            self.shm.buf[:CAMERA_SHM_TOTAL_SIZE] = b"\0" * CAMERA_SHM_TOTAL_SIZE
            self.frame_seq = {idx: 0 for idx in range(CAMERA_SHM_CAM_COUNT)}
            logger.info(
                "[CameraSHM] opened name=%s cameras=%s slots=%s slot_size=%s",
                self.name,
                CAMERA_SHM_CAM_COUNT,
                CAMERA_SHM_SLOT_COUNT,
                CAMERA_SHM_SLOT_SIZE,
            )
            return True
        except Exception as exc:
            if not self.warned_create_failure:
                logger.warning("[CameraSHM] open failed: %s", exc, exc_info=True)
                self.warned_create_failure = True
            self.close(unlink=False)
            return False

    def write_qimage(self, cam_idx: int, qimg: Any) -> Tuple[int, Optional[Dict[str, Any]]]:
        if qimg is None or cam_idx < 0 or cam_idx >= CAMERA_SHM_CAM_COUNT:
            return 0, None
        if not self.ensure_open() or self.shm is None:
            return 0, None
        try:
            from PySide6.QtGui import QImage

            gray8 = getattr(QImage, "Format_Grayscale8", None) or QImage.Format.Format_Grayscale8
            rgb888 = getattr(QImage, "Format_RGB888", None) or QImage.Format.Format_RGB888
            target_format = gray8 if qimg.isGrayscale() else rgb888
            image = qimg.convertToFormat(target_format)
            width = int(image.width())
            height = int(image.height())
            bytes_per_line = int(image.bytesPerLine())
            data_size = bytes_per_line * height
            if width <= 0 or height <= 0 or data_size <= 0:
                return 0, None
            if CAMERA_SHM_META_SIZE + data_size > CAMERA_SHM_SLOT_SIZE:
                logger.warning(
                    "[CameraSHM] frame too large cam=%s size=%s slot=%s",
                    cam_idx,
                    data_size,
                    CAMERA_SHM_SLOT_SIZE,
                )
                return 0, None

            seq = self.frame_seq.get(cam_idx, 0) + 1
            slot_idx = seq % CAMERA_SHM_SLOT_COUNT
            slot_offset = (
                CAMERA_SHM_SEQ_SIZE
                + (cam_idx * CAMERA_SHM_SLOT_COUNT + slot_idx) * CAMERA_SHM_SLOT_SIZE
            )
            fmt = image.format()
            fmt_value = int(fmt.value) if hasattr(fmt, "value") else int(fmt)
            struct.pack_into(
                "<IIIIII",
                self.shm.buf,
                slot_offset,
                width,
                height,
                fmt_value,
                data_size,
                bytes_per_line,
                0,
            )

            bits = image.constBits()
            payload_offset = slot_offset + CAMERA_SHM_META_SIZE
            try:
                source = memoryview(bits)[:data_size]
                self.shm.buf[payload_offset:payload_offset + data_size] = source
            except Exception:
                try:
                    bits.setsize(data_size)
                except Exception:
                    pass
                self.shm.buf[payload_offset:payload_offset + data_size] = bytes(bits)[:data_size]

            seq_offset = (cam_idx * CAMERA_SHM_SLOT_COUNT + slot_idx) * 8
            struct.pack_into("<Q", self.shm.buf, seq_offset, seq)
            self.frame_seq[cam_idx] = seq
            return seq, {
                "width": width,
                "height": height,
                "format": fmt_value,
                "bytes_per_line": bytes_per_line,
                "data_size": data_size,
                "encoding": "shm_raw",
                "shm": True,
                "shm_name": self.name,
                "shm_seq": seq,
                "shm_slot_size": CAMERA_SHM_SLOT_SIZE,
            }
        except Exception as exc:
            logger.warning("[CameraSHM] write failed cam=%s: %s", cam_idx, exc, exc_info=True)
            return 0, None

    def close(self, unlink: bool = True) -> None:
        shm = self.shm
        self.shm = None
        if shm is None:
            return
        try:
            shm.close()
        except Exception:
            pass
        if unlink:
            try:
                shm.unlink()
            except FileNotFoundError:
                pass
            except Exception:
                logger.debug("[CameraSHM] unlink skipped", exc_info=True)


def qimage_to_wire(qimg: Any) -> Optional[Dict[str, Any]]:
    if qimg is None:
        return None
    try:
        from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
        from PySide6.QtGui import QImage

        gray8 = getattr(QImage, "Format_Grayscale8", None) or QImage.Format.Format_Grayscale8
        rgb888 = getattr(QImage, "Format_RGB888", None) or QImage.Format.Format_RGB888
        target_format = gray8 if qimg.isGrayscale() else rgb888
        image = qimg.convertToFormat(target_format)
        original_width = int(image.width())
        original_height = int(image.height())
        max_width = 320
        if original_width > max_width:
            image = image.scaled(
                max_width,
                max(1, int(original_height * max_width / original_width)),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
        width = int(image.width())
        height = int(image.height())
        byte_array = QByteArray()
        buffer = QBuffer(byte_array)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        encoding = "jpeg"
        if not image.save(buffer, "JPG", 60):
            buffer.close()
            byte_array = QByteArray()
            buffer = QBuffer(byte_array)
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            encoding = "png"
            if not image.save(buffer, "PNG"):
                return None
        buffer.close()
        fmt = image.format()
        fmt_value = int(fmt.value) if hasattr(fmt, "value") else int(fmt)
        return {
            "width": width,
            "height": height,
            "original_width": original_width,
            "original_height": original_height,
            "format": fmt_value,
            "encoding": encoding,
            "bytes_per_line": 0,
            "data": bytes(byte_array),
        }
    except Exception as exc:
        logger.warning("[qimage_to_wire] failed: %s", exc)
        return None


class CameraSnapshotWorker:
    csv_header = [
        "timestamps_ns",
        "r_left_mean",
        "g_left_mean",
        "b_left_mean",
        "r_right_mean",
        "g_right_mean",
        "b_right_mean",
    ]

    def __init__(self, save_dir: str):
        self.save_dir = Path(save_dir)
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.snapshot_interval_s = 60.0
        self.rgb_log_interval_s = 1.0
        self.latest_frames = {0: None, 1: None}
        self.frame_lock = threading.Lock()
        self.csv_file = None
        self.csv_writer = None
        self.snapshot_count = 0
        self.last_snapshot_time = 0.0
        self.last_rgb_log_time = 0.0

    def update_frame(self, cam_idx: int, qimage: Any) -> None:
        if cam_idx not in (0, 1):
            return
        with self.frame_lock:
            self.latest_frames[cam_idx] = qimage.copy() if qimage else None

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        (self.save_dir / "cam0" / "snapshots").mkdir(parents=True, exist_ok=True)
        (self.save_dir / "cam1" / "snapshots").mkdir(parents=True, exist_ok=True)
        self.csv_file = open(self.save_dir / "camera_rgb.csv", "w", encoding="utf-8", newline="")
        import csv

        self.csv_writer = csv.writer(self.csv_file)
        self.csv_writer.writerow(self.csv_header)
        self.csv_file.flush()
        self.thread = threading.Thread(target=self._main_loop, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if not self.running:
            return
        self.running = False
        self._save_snapshot("cam_end")
        self._log_rgb_values()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5.0)
        if self.csv_file:
            self.csv_file.close()
        self.csv_file = None
        self.csv_writer = None

    def _main_loop(self) -> None:
        self._save_start_snapshot()
        self._log_rgb_values()
        self.last_rgb_log_time = time.monotonic()
        while self.running:
            threading.Event().wait(1.0)
            time_now = time.monotonic()
            if not self.running:
                break
            if time_now - self.last_rgb_log_time >= self.rgb_log_interval_s:
                self._log_rgb_values()
                self.last_rgb_log_time = time_now
            if time_now - self.last_snapshot_time >= self.snapshot_interval_s:
                self.snapshot_count += 1
                if self._save_snapshot(f"cam_{self.snapshot_count}min"):
                    self.last_snapshot_time = time_now

    def _save_start_snapshot(self) -> None:
        deadline = time.time() + 5.0
        while time.time() < deadline:
            with self.frame_lock:
                has_frame = self.latest_frames[0] is not None or self.latest_frames[1] is not None
            if has_frame:
                break
            time.sleep(0.2)
        if self._save_snapshot("cam_start"):
            self.last_snapshot_time = time.monotonic()

    def _save_snapshot(self, name: str) -> bool:
        with self.frame_lock:
            frames = {idx: frame.copy() if frame else None for idx, frame in self.latest_frames.items()}
        saved = False
        for idx, frame in frames.items():
            if frame is None:
                continue
            path = self.save_dir / f"cam{idx}" / "snapshots" / f"{name}.png"
            saved = bool(frame.save(str(path), "PNG")) or saved
        return saved

    def _calculate_rgb_mean(self, qimage: Any):
        import numpy as np
        from PySide6.QtGui import QImage

        rgba = qimage.convertToFormat(QImage.Format.Format_RGBA8888)
        arr = np.array(rgba.bits()).reshape((rgba.height(), rgba.width(), 4))
        return float(np.mean(arr[:, :, 0])), float(np.mean(arr[:, :, 1])), float(np.mean(arr[:, :, 2]))

    def _log_rgb_values(self) -> None:
        if not self.csv_writer:
            return
        with self.frame_lock:
            left = self.latest_frames[0].copy() if self.latest_frames[0] else None
            right = self.latest_frames[1].copy() if self.latest_frames[1] else None
        left_mean = self._calculate_rgb_mean(left) if left else (-1.0, -1.0, -1.0)
        right_mean = self._calculate_rgb_mean(right) if right else (-1.0, -1.0, -1.0)
        self.csv_writer.writerow([time.time_ns(), *[f"{v:.2f}" for v in (*left_mean, *right_mean)]])
        self.csv_file.flush()
