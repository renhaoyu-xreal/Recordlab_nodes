import json
from pathlib import Path


def test_agents_config_uses_node_class_without_command_list():
    config_path = Path(__file__).resolve().parents[1] / "config" / "agents_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    agent = config["agents"]["imu_simulation"]

    assert agent["node_class"].endswith(".ImuSimNode")
    assert "commands" not in agent
    assert {"goal_port", "feedback_port", "topics"} <= set(agent)


def test_agents_config_contains_bsp_agent_and_scripts():
    config_path = Path(__file__).resolve().parents[1] / "config" / "agents_config.json"
    nodes_root = config_path.parents[1]
    config = json.loads(config_path.read_text(encoding="utf-8"))
    agent = config["agents"]["glasses_bsp_node"]

    assert agent["node_class"].endswith(".BspMainNode")
    assert "commands" not in agent
    assert "glasses_bsp_node" in config["primary_agents"]
    scripts = set(agent["default_scripts"])
    assert {
        "record_bsp_imu.py",
        "record_bsp_imu_cam.py",
        "record_bsp_imu_static.py",
        "record_bsp_imu_dynamic.py",
        "record_bsp_rgb.py",
        "record_bsp_rgb_raw.py",
    } <= scripts
    for script in scripts:
        assert (nodes_root / "node_scripts" / script).exists()
    camera_topic = next(item for item in agent["topics"] if item["name"] == "camera_data")
    assert camera_topic["encoding"] == "json_binary"
