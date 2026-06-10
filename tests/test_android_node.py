import csv
import json
import struct
from pathlib import Path
from types import SimpleNamespace

from recordlab_nodes.core.node_runtime import load_agent_config
from recordlab_nodes.nodes.android import android_node
from recordlab_nodes.nodes.android.android_node import AndroidNode


class FakeRuntime:
    def __init__(self):
        self.published = []

    def publish(self, topic_name, data):
        self.published.append((topic_name, data))


class FakeTcpServer:
    instances = []

    def __init__(self, status_dict, port=0):
        self.status_dict = status_dict
        self.port = port
        self.started = False
        self.stopped = False
        self.plot_callback = None
        self.connection_callback = None
        FakeTcpServer.instances.append(self)

    def set_plot_data_callback(self, callback):
        self.plot_callback = callback

    def set_connection_callback(self, callback):
        self.connection_callback = callback

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class FakeProcess:
    def __init__(self, args):
        self.args = args
        self.terminated = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True


def make_node(tmp_path):
    node = AndroidNode({
        "name": "android",
        "root_path": str(tmp_path / "data"),
        "custom_params": {"tcp_port": 8100},
        "android_runtime_dir": str(tmp_path / "runtime"),
    })
    runtime_dir = Path(node.runtime_dir)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    for filename in android_node.ANDROID_RUNTIME_FILES:
        (runtime_dir / filename).write_bytes(b"runtime")
    fake_runtime = FakeRuntime()
    node.bind_runtime(fake_runtime)
    return node, fake_runtime


def install_process_mocks(monkeypatch):
    commands = []
    popens = []

    def fake_run(args, **kwargs):
        commands.append((list(args), kwargs))
        if list(args) == ["adb", "get-state"]:
            return SimpleNamespace(returncode=0, stdout="device\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def fake_popen(args, **kwargs):
        proc = FakeProcess(list(args))
        popens.append(proc)
        return proc

    monkeypatch.setattr(android_node.subprocess, "run", fake_run)
    monkeypatch.setattr(android_node.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(android_node, "NrealLinkTcpServer", FakeTcpServer)
    FakeTcpServer.instances.clear()
    return commands, popens


def mobile_payload(onsensor_ts_ns, imu_type=3):
    return struct.pack(
        "<QQQIffffff",
        100,
        onsensor_ts_ns,
        1_000_000_000 + onsensor_ts_ns,
        imu_type,
        1.0,
        2.0,
        3.0,
        4.0,
        5.0,
        6.0,
    )


def test_android_config_contract_loads_primary_agent():
    config_path = Path(__file__).resolve().parents[1] / "config" / "agents_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    agent = config["agents"]["android"]
    expanded = load_agent_config(str(config_path), "android")

    assert "android" in config["primary_agents"]
    assert agent["node_class"].endswith(".AndroidNode")
    assert agent["topics"] == "android_sensor_topics"
    assert agent["sensor_layout"] == "android_sensor_workspace"
    assert {topic["name"] for topic in expanded["topics"]} >= {
        "android_imu_data",
        "record_timer",
        "time_delay",
        "node_cookie",
    }
    assert all("port" not in topic for topic in expanded["topics"])


def test_init_device_starts_tcp_server_and_pushes_runtime(monkeypatch, tmp_path):
    commands, _ = install_process_mocks(monkeypatch)
    node, runtime = make_node(tmp_path)

    pre_init_check = node.check({})
    assert pre_init_check["success"]
    assert "TCP server not initialized" in pre_init_check["message"]
    result = node.init_device({"tcp_port": 8111})

    assert result["success"]
    post_init_check = node.check({})
    assert post_init_check["success"]
    assert "TCP server running on 8111" in post_init_check["message"]
    assert FakeTcpServer.instances[-1].port == 8111
    assert FakeTcpServer.instances[-1].started
    command_text = " ".join(" ".join(cmd) for cmd, _ in commands)
    assert "adb reverse tcp:8111 tcp:8111" in command_text
    assert "adb push" in command_text
    assert any(topic == "node_cookie" for topic, _ in runtime.published)


def test_mobile_data_publish_and_record_csv_sorted(monkeypatch, tmp_path):
    install_process_mocks(monkeypatch)
    node, runtime = make_node(tmp_path)
    node.init_device({})
    node._on_tcp_connection(("127.0.0.1", 12345))

    start = node.start_record({"dataset_name": "case"})
    assert start["success"]
    node._on_data(SimpleNamespace(group_id=126, msg_id=1, payload=mobile_payload(3000)))
    node._on_data(SimpleNamespace(group_id=126, msg_id=1, payload=mobile_payload(1000)))
    stop = node.stop_record({})

    assert stop["success"]
    assert any(topic == "android_imu_data" for topic, _ in runtime.published)
    assert any(topic == "record_timer" for topic, _ in runtime.published)
    delay_payloads = [data for topic, data in runtime.published if topic == "time_delay"]
    assert delay_payloads
    assert delay_payloads[-1]["status"] == "valid"
    assert delay_payloads[-1]["time_delay_ns"] >= 0
    rows = list(csv.DictReader(open(stop["csv_path"], encoding="utf-8")))
    assert [float(row["onsensor_timestamp_us"]) for row in rows] == [1.0, 3.0]


def test_legacy_commands_and_shutdown_cleanup(monkeypatch, tmp_path):
    commands, popens = install_process_mocks(monkeypatch)
    node, _ = make_node(tmp_path)

    assert node.restart_device({"tcp_port": 8122})["success"]
    assert node.set_fan({"speed": 50})["success"]
    assert node.start_load({"mode": "high"})["success"]
    assert node.start_fan_cycle({})["success"]
    assert node.start_gps_cycle({})["success"]
    assert node.control_device({"action": "stop_load"})["success"]

    node.shutdown()

    assert FakeTcpServer.instances[-1].stopped
    assert any(proc.terminated for proc in popens)
    command_text = " ".join(" ".join(cmd) for cmd, _ in commands)
    assert "pkill -f get_imu_data" in command_text
    assert "recordlab_fan_cycle.sh" in command_text
    assert "recordlab_gps_cycle.sh" in command_text
