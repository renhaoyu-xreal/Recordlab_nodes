import csv
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ECHO_PYTHON = Path(os.environ.get("ECHO_MESSAGE_SYSTEM_PYTHON_ROOT", str(ROOT.parent / "echo_message_system" / "python")))
if str(ECHO_PYTHON) not in sys.path:
    sys.path.insert(0, str(ECHO_PYTHON))

from message_system import ActionClient, GoalStatus, Subscriber  # noqa: E402


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def make_csv(path: Path, rows: int = 20) -> None:
    base_ns = time.time_ns()
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "timestamp",
            "onsensor_timestamp_us",
            "timestamp_ns",
            "type",
            "data0",
            "data1",
            "data2",
            "data3",
            "data4",
            "data5",
        ])
        for i in range(rows):
            writer.writerow([i * 0.001, i * 1000, base_ns + i * 1_000_000, 1, i, i + 1, i + 2, i + 3, i + 4, i + 5])


def send_and_wait(client: ActionClient, goal: dict, timeout: int = 3000):
    goal_id = client.send_goal(goal)
    result, status = client.wait_for_result(goal_id, timeout=timeout)
    return result, status


def test_node_runtime_imu_action_topic_and_recording(tmp_path):
    csv_path = tmp_path / "imu.csv"
    make_csv(csv_path)
    goal_port = free_port()
    feedback_port = free_port()
    imu_port = free_port()
    record_port = free_port()
    delay_port = free_port()
    motion_port = free_port()
    config_path = tmp_path / "agents_config.json"
    root_path = tmp_path / "data"
    config_path.write_text(json.dumps({
        "agents": {
            "imu_test": {
                "name": "imu_test",
                "node_class": "recordlab_nodes.nodes.imu_sim.imu_sim_node.ImuSimNode",
                "process_type": "python_node",
                "subnode_host": "127.0.0.1",
                "action_name": "imu_test_actions",
                "goal_port": goal_port,
                "feedback_port": feedback_port,
                "root_path": str(root_path),
                "topics": [
                    {"name": "imu_data", "port": imu_port, "encoding": "json"},
                    {"name": "record_timer", "port": record_port, "encoding": "json"},
                    {"name": "time_delay", "port": delay_port, "encoding": "json"},
                    {"name": "motion_status", "port": motion_port, "encoding": "json"}
                ],
                "custom_params": {}
            }
        },
        "primary_agents": ["imu_test"]
    }), encoding="utf-8")

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT}:{ECHO_PYTHON}:{env.get('PYTHONPATH', '')}"
    proc = subprocess.Popen(
        [sys.executable, "-m", "recordlab_nodes.core.node_runtime", "--config", str(config_path), "--agent", "imu_test"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        client = ActionClient(
            name="runtime_test_client",
            action_name="imu_test_actions",
            goal_host="127.0.0.1",
            goal_port=goal_port,
            feedback_host="127.0.0.1",
            feedback_port=feedback_port,
            timeout=3000,
        )
        assert client.wait_for_server(timeout=5000)
        client.start_listening()
        time.sleep(0.2)

        messages = []
        sub = Subscriber("imu_test_sub", "imu_data", lambda topic, data: messages.append(data), port=imu_port)
        sub.start()

        result, status = send_and_wait(client, {"cmd": "init_device", "params": {"read_path": str(csv_path)}})
        assert status == GoalStatus.SUCCEEDED
        assert result["success"]

        result, status = send_and_wait(client, {"cmd": "init_device", "params": {"read_path": str(tmp_path / "missing.csv")}})
        assert status == GoalStatus.FAILED
        assert not result["success"]

        result, status = send_and_wait(client, {"cmd": "init_device", "params": {"read_path": str(csv_path)}})
        assert status == GoalStatus.SUCCEEDED
        assert result["success"]

        result, status = send_and_wait(client, {"cmd": "not_a_configured_command", "params": {}})
        assert status == GoalStatus.FAILED
        assert not result["success"]
        assert "Command not found" in result["message"]

        result, status = send_and_wait(client, {"cmd": "start_record", "params": {"dataset_name": "case"}})
        assert status == GoalStatus.SUCCEEDED
        assert result["success"]

        result, status = send_and_wait(client, {"cmd": "start_device", "params": {}})
        assert status == GoalStatus.SUCCEEDED
        assert result["success"]

        deadline = time.time() + 4
        while time.time() < deadline and len(messages) < 3:
            time.sleep(0.05)
        assert messages, "Expected at least one IMU topic message"

        result, status = send_and_wait(client, {"cmd": "stop_device", "params": {}})
        assert status == GoalStatus.SUCCEEDED
        assert result["success"]

        output = root_path / "case" / "imu_data.csv"
        assert output.exists()
        rows = list(csv.DictReader(output.open(encoding="utf-8")))
        assert rows
        sub.close()
        client.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        if proc.returncode not in (0, -15):
            stdout, stderr = proc.communicate(timeout=1)
            raise AssertionError(f"node_runtime exited unexpectedly: {proc.returncode}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}")


def test_two_node_runtimes_are_isolated(tmp_path):
    csv_a = tmp_path / "imu_a.csv"
    csv_b = tmp_path / "imu_b.csv"
    make_csv(csv_a, rows=10)
    make_csv(csv_b, rows=10)
    agents = {}
    for name in ("imu_a", "imu_b"):
        agents[name] = {
            "name": name,
            "node_class": "recordlab_nodes.nodes.imu_sim.imu_sim_node.ImuSimNode",
            "process_type": "python_node",
            "subnode_host": "127.0.0.1",
            "action_name": f"{name}_actions",
            "goal_port": free_port(),
            "feedback_port": free_port(),
            "root_path": str(tmp_path / f"data_{name}"),
            "topics": [
                {"name": "imu_data", "port": free_port(), "encoding": "json"},
                {"name": "record_timer", "port": free_port(), "encoding": "json"},
                {"name": "time_delay", "port": free_port(), "encoding": "json"},
                {"name": "motion_status", "port": free_port(), "encoding": "json"}
            ],
            "custom_params": {}
        }
    config_path = tmp_path / "agents_config.json"
    config_path.write_text(json.dumps({"agents": agents, "primary_agents": ["imu_a", "imu_b"]}), encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT}:{ECHO_PYTHON}:{env.get('PYTHONPATH', '')}"
    procs = []
    clients = []
    try:
        for name in ("imu_a", "imu_b"):
            proc = subprocess.Popen(
                [sys.executable, "-m", "recordlab_nodes.core.node_runtime", "--config", str(config_path), "--agent", name],
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            procs.append(proc)
            cfg = agents[name]
            client = ActionClient(
                name=f"{name}_client",
                action_name=f"{name}_actions",
                goal_host="127.0.0.1",
                goal_port=cfg["goal_port"],
                feedback_host="127.0.0.1",
                feedback_port=cfg["feedback_port"],
                timeout=3000,
            )
            assert client.wait_for_server(timeout=5000)
            client.start_listening()
            time.sleep(0.2)
            clients.append((name, client))

        for name, client in clients:
            csv_path = csv_a if name == "imu_a" else csv_b
            assert send_and_wait(client, {"cmd": "init_device", "params": {"read_path": str(csv_path)}})[0]["success"]
            assert send_and_wait(client, {"cmd": "start_record", "params": {"dataset_name": "case"}})[0]["success"]
            assert send_and_wait(client, {"cmd": "start_device", "params": {}})[0]["success"]

        time.sleep(0.4)

        for name, client in clients:
            assert send_and_wait(client, {"cmd": "stop_device", "params": {}})[0]["success"]
            output = Path(agents[name]["root_path"]) / "case" / "imu_data.csv"
            assert output.exists()
            assert list(csv.DictReader(output.open(encoding="utf-8")))
            client.close()
    finally:
        for proc in procs:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
