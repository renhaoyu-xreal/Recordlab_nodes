#!/usr/bin/env python3
import json
import os
import sys
import time
from pathlib import Path

nodes_root = Path(__file__).resolve().parents[1]
echo_python = Path(os.environ.get(
    "ECHO_MESSAGE_SYSTEM_PYTHON_ROOT",
    str(nodes_root.parent / "echo_message_system" / "python"),
))
if echo_python.exists() and str(echo_python) not in sys.path:
    sys.path.insert(0, str(echo_python))

from message_system import ActionClient  # noqa: E402


def send(client, cmd, params=None, timeout=5000):
    goal_id = client.send_goal({"cmd": cmd, "params": params or {}})
    result, status = client.wait_for_result(goal_id, timeout=timeout)
    print(f"{cmd}: {status.value if hasattr(status, 'value') else status} {json.dumps(result, ensure_ascii=False)}", flush=True)
    return result


def main():
    config_path = Path(os.environ.get("RECORDLAB_AGENTS_CONFIG", str(nodes_root / "config" / "agents_config.json")))
    agent_name = os.environ.get("RECORDLAB_AGENT", "imu_simulation")
    config = json.loads(config_path.read_text(encoding="utf-8"))["agents"][agent_name]
    client = ActionClient(
        name=f"{agent_name}_script_client",
        action_name=config.get("action_name", f"{agent_name}_actions"),
        goal_host=config.get("subnode_host", "127.0.0.1"),
        goal_port=int(config["goal_port"]),
        feedback_host=config.get("subnode_host", "127.0.0.1"),
        feedback_port=int(config["feedback_port"]),
        timeout=5000,
    )
    if not client.wait_for_server(timeout=5000):
        raise RuntimeError("action server not available")
    client.start_listening()
    time.sleep(0.2)
    send(client, "init_device", config.get("init_device_params", {}))
    dataset_name = time.strftime("ui_script_demo_%Y%m%d_%H%M%S")
    send(client, "start_record", {"dataset_name": dataset_name})
    send(client, "start_device")
    time.sleep(12)
    send(client, "stop_device")
    send(client, "stop_record")
    client.close()


if __name__ == "__main__":
    main()
