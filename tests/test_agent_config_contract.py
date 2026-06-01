import json
from pathlib import Path


def test_agents_config_uses_node_class_without_command_list():
    config_path = Path(__file__).resolve().parents[1] / "config" / "agents_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    agent = config["agents"]["imu_simulation"]

    assert agent["node_class"].endswith(".ImuSimNode")
    assert "commands" not in agent
    assert {"goal_port", "feedback_port", "topics"} <= set(agent)
