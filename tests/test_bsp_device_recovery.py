import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST_ROOT = ROOT.parents[1]
XREAL_ROOT = HOST_ROOT / "third_party" / "xreal_glasses"
if str(XREAL_ROOT) not in sys.path:
    sys.path.insert(0, str(XREAL_ROOT))

from recordlab_nodes.nodes.bsp.bsp_device import BspDevice  # noqa: E402


class FakeBridge:
    def __init__(self, open_results=None, create_results=None):
        self.open_results = list(open_results or [True])
        self.create_results = list(create_results or [True])
        self.glasses = None
        self.create_count = 0
        self.open_count = 0
        self.stop_count = 0
        self.close_count = 0

    def create_glasses(self):
        self.create_count += 1
        ok = self.create_results.pop(0) if self.create_results else True
        if ok:
            self.glasses = object()
            return {"success": True, "message": ""}
        return {"success": False, "message": "No glasses found"}

    def open_glasses(self):
        self.open_count += 1
        ok = self.open_results.pop(0) if self.open_results else True
        return {"success": bool(ok), "message": "" if ok else "Failed to open glasses"}

    def stop_sensors(self, sensors):
        self.stop_count += 1
        return {"success": True, "message": ""}

    def close_glasses(self):
        self.close_count += 1
        self.glasses = None
        return {"success": True, "message": ""}

    def disconnect_callbacks(self):
        pass

    def set_callbacks(self, imu_callback, image_callback):
        pass

    def get_glasses_state(self):
        return {"success": True, "message": "", "state": {"is_opened": True}}


class FakeLsusb:
    def __init__(self, connected=True):
        self.connected = connected

    def check(self):
        return {"connected": self.connected, "default_connection": "lsusb"}


class FakeSSHClient:
    def __init__(self):
        self.commands = []
        self.closed = False

    def exec_command(self, command, timeout=None):
        self.commands.append(command)
        return None, None, None

    def close(self):
        self.closed = True


class FakeSSHManager:
    def __init__(self, can_connect=True):
        self.can_connect = can_connect
        self.client = FakeSSHClient()

    def connect(self, timeout_s=5.0):
        if not self.can_connect:
            raise RuntimeError("ssh unavailable")
        return self.client

    def check_connection(self, timeout_s=5.0):
        return self.can_connect


def make_device(bridge, lsusb=None, ssh=None):
    device = BspDevice(ssh_manager=ssh or FakeSSHManager())
    device.bridge = bridge
    device.lsusb_checker = lsusb or FakeLsusb()
    return device


def test_initialize_recovers_with_sdk_handle():
    bridge = FakeBridge(open_results=[True, True])
    device = make_device(bridge)

    result = device.initialize({})

    assert result["success"]
    assert result["recovered"]
    assert result["recovery_method"] == "sdk"
    assert bridge.stop_count >= 1
    assert bridge.close_count == 0
    assert bridge.create_count == 1
    assert bridge.open_count == 1


def test_initialize_falls_back_to_ssh_reboot_when_sdk_open_fails():
    bridge = FakeBridge(open_results=[False, True])
    ssh = FakeSSHManager(can_connect=True)
    device = make_device(bridge, lsusb=FakeLsusb(connected=True), ssh=ssh)

    result = device.initialize({"recovery_timeout_s": 1})

    assert result["success"]
    assert result["recovered"]
    assert result["recovery_method"] == "ssh_reboot"
    assert "sync; reboot" in ssh.client.commands
    assert bridge.open_count == 2


def test_initialize_reports_recovery_failure_when_sdk_and_ssh_fail():
    bridge = FakeBridge(create_results=[False])
    device = make_device(bridge, lsusb=FakeLsusb(connected=False), ssh=FakeSSHManager(can_connect=False))

    result = device.initialize({"recovery_timeout_s": 1})

    assert not result["success"]
    assert "Device recovery failed" in result["message"]
