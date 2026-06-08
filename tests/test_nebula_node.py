import json
from pathlib import Path
from types import SimpleNamespace

from recordlab_nodes.core.node_runtime import load_agent_config
from recordlab_nodes.nodes.nebula.nebula_node import NebulaNode


class FakeRuntime:
    def __init__(self):
        self.published = []

    def publish(self, topic_name, data):
        self.published.append((topic_name, data))


def make_node(tmp_path):
    node = NebulaNode({
        "name": "nebula_trial",
        "root_path": str(tmp_path / "data"),
        "custom_params": {"remote_dir": "/sdcard/3dof_data"},
    })
    runtime = FakeRuntime()
    node.bind_runtime(runtime)
    return node, runtime


def install_adb_mocks(monkeypatch):
    commands = []

    def fake_run(args, **kwargs):
        commands.append(list(args))
        if args[:2] == ["adb", "devices"]:
            return SimpleNamespace(returncode=0, stdout="List of devices attached\nUSB123\tdevice\n", stderr="")
        if args[:2] == ["adb", "connect"]:
            return SimpleNamespace(returncode=0, stdout="connected\n", stderr="")
        if args[:2] == ["adb", "tcpip"]:
            return SimpleNamespace(returncode=0, stdout="restarting in TCP mode\n", stderr="")
        if args[:3] == ["ping", "-c", "1"]:
            return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")
        if "ip -f inet addr show wlan0" in args[-1]:
            return SimpleNamespace(returncode=0, stdout="    inet 192.168.0.10/24 brd 192.168.0.255\n", stderr="")
        if 'pm path "com.xreal.evapro.nebula"' in args[-1]:
            return SimpleNamespace(returncode=0, stdout="package:/data/app/nebula/base.apk\n", stderr="")
        if 'for f in "/sdcard/3dof_data"/*.csv; do [ -e "$f" ] && echo "$f"; done; true' in args[-1]:
            return SimpleNamespace(
                returncode=0,
                stdout="/sdcard/3dof_data/demo_air_data.csv\n/sdcard/3dof_data/demo_mobile_data.csv\n",
                stderr="",
            )
        if 'for f in "/sdcard/3dof_data"/*.csv; do [ -e "$f" ] && wc -l "$f"; done; true' in args[-1]:
            return SimpleNamespace(
                returncode=0,
                stdout="12 /sdcard/3dof_data/demo_air_data.csv\n20 /sdcard/3dof_data/demo_mobile_data.csv\n",
                stderr="",
            )
        if 'tail -n 1 "/sdcard/3dof_data/demo_air_data.csv"' in args[-1]:
            return SimpleNamespace(returncode=0, stdout="air_last_row\n", stderr="")
        if 'tail -n 1 "/sdcard/3dof_data/demo_mobile_data.csv"' in args[-1]:
            return SimpleNamespace(returncode=0, stdout="mobile_last_row\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("recordlab_nodes.nodes.nebula.nebula_node.subprocess.run", fake_run)
    return commands


def test_nebula_config_contract_loads_primary_agent():
    config_path = Path(__file__).resolve().parents[1] / "config" / "agents_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    agent = config["agents"]["nebula_trial"]
    expanded = load_agent_config(str(config_path), "nebula_trial")

    assert "nebula_trial" in config["primary_agents"]
    assert agent["node_class"].endswith(".NebulaNode")
    assert agent["topics"] == "nebula_summary_topics"
    assert agent["sensor_layout"] == "nebula_summary_workspace"
    assert expanded["sensor_layout"]["nebula_latest_csv"]["ui_widget"] == "summary_value"
    assert all("port" not in topic for topic in expanded["topics"])


def test_get_runtime_state_returns_latest_csv_summary(monkeypatch, tmp_path):
    install_adb_mocks(monkeypatch)
    node, _ = make_node(tmp_path)
    node.serial = "USB123"

    result = node.get_runtime_state({})

    assert result["success"]
    assert result["csv_rows"]["/sdcard/3dof_data/demo_air_data.csv"] == 12
    assert result["csv_growing"] is False
    assert result["latest_csv_lines"]["demo_air_data.csv"] == "air_last_row"
    assert result["latest_csv_lines"]["demo_mobile_data.csv"] == "mobile_last_row"
    assert result["latest_update_time"]


def test_check_stays_health_only(monkeypatch, tmp_path):
    install_adb_mocks(monkeypatch)
    node, _ = make_node(tmp_path)
    node.serial = "USB123"

    result = node.check({})

    assert result["success"]
    assert "latest_csv_lines" not in result
    assert result["csv_rows"]["/sdcard/3dof_data/demo_air_data.csv"] == 12


def test_init_and_start_record(monkeypatch, tmp_path):
    install_adb_mocks(monkeypatch)
    node, runtime = make_node(tmp_path)

    init_result = node.init_device({"enable_wifi_adb": False, "require_ping": False})
    start_device_result = node.start_device({})
    start_record_result = node.start_record({"trial_id": "case"})

    assert init_result["success"]
    assert start_device_result["success"]
    assert start_record_result["success"]
    assert node.recording
    assert any(topic == "node_cookie" for topic, _ in runtime.published)
