import json
from pathlib import Path

import pytest

from recordlab_nodes.core.node_runtime import load_agent_config, validate_agent_config


def test_agents_config_uses_node_class_without_command_list():
    config_path = Path(__file__).resolve().parents[1] / "config" / "agents_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    agent = config["agents"]["imu_simulation"]
    expanded = load_agent_config(str(config_path), "imu_simulation")

    assert agent["node_class"].endswith(".ImuSimNode")
    assert "standard_device" in config["shared"]["exposed_commands"]
    assert "standard_sensor_workspace" in config["shared"]["sensor_layouts"]
    assert "standard_device_timeouts" in config["shared"]["commands"]
    assert "standard_recording_status" in config["shared"]["ui_bindings"]
    assert "standard_device_errors" in config["shared"]["error_messages"]
    assert "standard_sensor_topics" in config["shared"]["topic_sets"]
    assert "camera_sensor_topics" in config["shared"]["topic_sets"]
    assert {"goal_port", "feedback_port", "data_port", "topics", "commands", "exposed_commands"} <= set(agent)
    assert agent["exposed_commands"] == "standard_device"
    assert agent["commands"] == "standard_device_timeouts"
    assert agent["sensor_layout"] == "standard_sensor_workspace"
    assert agent["ui_bindings"] == "standard_recording_status"
    assert agent["error_messages"] == "standard_device_errors"
    assert agent["topics"] == "standard_sensor_topics"
    assert expanded["commands"]["default_timeout_ms"] == 5000
    assert "start_device" in expanded["exposed_commands"]
    assert "imu_data" in expanded["sensor_layout"]
    assert "record_timer" in expanded["ui_bindings"]
    for topic in expanded["topics"]:
        assert "port" not in topic


def test_agents_config_contains_bsp_agent_and_scripts():
    config_path = Path(__file__).resolve().parents[1] / "config" / "agents_config.json"
    nodes_root = config_path.parents[1]
    config = json.loads(config_path.read_text(encoding="utf-8"))
    agent = config["agents"]["glasses_bsp_node"]
    expanded = load_agent_config(str(config_path), "glasses_bsp_node")

    assert agent["node_class"].endswith(".BspMainNode")
    assert "commands" in agent
    assert agent["exposed_commands"] == "standard_device"
    assert agent["commands"] == "standard_device_timeouts"
    assert agent["sensor_layout"] == "standard_sensor_workspace"
    assert agent["ui_bindings"] == "standard_recording_status"
    assert agent["error_messages"] == "standard_device_errors"
    assert agent["topics"] == "camera_sensor_topics"
    assert "start_device" in expanded["exposed_commands"]
    assert "imu_data" in expanded["sensor_layout"]
    assert "glasses_bsp_node" in config["primary_agents"]
    scripts = set(agent["default_scripts"])
    assert {
        "record_bsp_imu.py",
        "record_bsp_imu_cam.py",
        "record_bsp_imu_static.py",
        "record_bsp_imu_dynamic.py",
        "record_bsp_rgb_raw.py",
    } <= scripts
    for script in scripts:
        assert (nodes_root / "node_scripts" / script).exists()
    camera_topic = next(item for item in expanded["topics"] if item["name"] == "camera_data")
    assert camera_topic["encoding"] == "json_binary"
    for topic in expanded["topics"]:
        assert "port" not in topic


def test_agents_config_contains_mcu_agent_and_script():
    config_path = Path(__file__).resolve().parents[1] / "config" / "agents_config.json"
    nodes_root = config_path.parents[1]
    config = json.loads(config_path.read_text(encoding="utf-8"))
    agent = config["agents"]["mcu_node"]
    expanded = load_agent_config(str(config_path), "mcu_node")

    assert agent["node_class"].endswith(".McuMainNode")
    assert "commands" in agent
    assert agent["exposed_commands"] == "standard_device"
    assert agent["commands"] == "standard_device_timeouts"
    assert agent["sensor_layout"] == "standard_sensor_workspace"
    assert agent["ui_bindings"] == "standard_recording_status"
    assert agent["error_messages"] == "standard_device_errors"
    assert agent["topics"] == "camera_sensor_topics"
    assert "start_device" in expanded["exposed_commands"]
    assert "imu_data" in expanded["sensor_layout"]
    assert "mcu_node" in config["primary_agents"]
    assert agent["init_device_params"]["allow_ssh_reboot"] is False
    assert agent["custom_params"]["persist_ssh_artifacts"] is False
    scripts = set(agent["default_scripts"])
    assert {"record_mcu_id1088_ur_gt_3dof_batch.py"} <= scripts
    for script in scripts:
        assert (nodes_root / "scripts" / script).exists()
    assert {topic["name"] for topic in expanded["topics"]} >= {
        "imu_data",
        "camera_data",
        "record_timer",
        "time_delay",
        "motion_status",
        "node_cookie",
    }
    for topic in expanded["topics"]:
        assert "port" not in topic


def test_agents_config_contains_android_primary_agent_and_scripts():
    config_path = Path(__file__).resolve().parents[1] / "config" / "agents_config.json"
    nodes_root = config_path.parents[1]
    config = json.loads(config_path.read_text(encoding="utf-8"))
    agent = config["agents"]["android"]
    expanded = load_agent_config(str(config_path), "android")

    assert agent["node_class"].endswith(".AndroidNode")
    assert agent["topics"] == "android_sensor_topics"
    assert agent["sensor_layout"] == "android_sensor_workspace"
    assert "android" in config["primary_agents"]
    assert {topic["name"] for topic in expanded["topics"]} >= {
        "android_imu_data",
        "record_timer",
        "node_cookie",
    }
    scripts = set(agent["default_scripts"])
    assert {
        "scripts/record_android_imu_simple_test.py",
        "scripts/record_ur_android_imu_batch.py",
    } <= scripts
    for script in scripts:
        assert (nodes_root / script).exists()
    for topic in expanded["topics"]:
        assert "port" not in topic


def test_node_runtime_rejects_old_topic_port_config():
    with pytest.raises(KeyError):
        validate_agent_config({"name": "bad", "topics": []})

    with pytest.raises(ValueError):
        validate_agent_config({
            "name": "bad",
            "data_port": 16510,
            "topics": [{"name": "imu_data", "port": 16510, "encoding": "json"}],
        })
