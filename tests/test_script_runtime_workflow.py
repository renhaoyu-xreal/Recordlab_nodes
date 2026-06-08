import json
import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ECHO_PYTHON = Path(os.environ.get("ECHO_MESSAGE_SYSTEM_PYTHON_ROOT", str(ROOT.parent / "echo_message_system" / "python")))


def workflow_events(stdout: str):
    prefix = "__RECORDLAB_EVENT__ "
    events = []
    for line in stdout.splitlines():
        if line.startswith(prefix):
            events.append(json.loads(line[len(prefix):]))
    return [event for event in events if event.get("type") == "workflow"]


def runtime_events(stdout: str):
    prefix = "__RECORDLAB_EVENT__ "
    events = []
    for line in stdout.splitlines():
        if line.startswith(prefix):
            events.append(json.loads(line[len(prefix):]))
    return events


def test_event_channel_cmd_request_times_out(monkeypatch):
    sys.path.insert(0, str(ROOT))
    from scripts.runtime.run_recordlab_script import EventChannel

    read_fd, write_fd = os.pipe()
    reader = os.fdopen(read_fd, "r", encoding="utf-8")
    try:
        monkeypatch.setattr(sys, "stdin", reader)
        started = time.monotonic()
        result = EventChannel().request({"type": "cmd_request", "timeout_s": 0.1})
        elapsed = time.monotonic() - started
    finally:
        reader.close()
        os.close(write_fd)

    assert result["success"] is False
    assert result["cancelled"] is False
    assert result["message"] == "Host bridge command timeout"
    assert elapsed < 2.0


def test_script_runtime_reports_missing_nodes_in_workflow(tmp_path):
    script_path = tmp_path / "needs_node.py"
    script_path.write_text(
        "all_agent_names = ['missing_node']\n"
        "from flowagent.core.script_workflow import WorkflowStep, finish, set_step, set_steps\n"
        "set_steps([WorkflowStep.NODES_CHECK, WorkflowStep.START_DEVICE, WorkflowStep.STOP_RECORD], title='完整流程')\n"
        "unavailable = globals().get('unavailable_script_agents') or {}\n"
        "if unavailable:\n"
        "    message = '\\n'.join(['当前脚本缺失以下 node:'] + [f'- {name}: {reason}' for name, reason in unavailable.items()])\n"
        "    set_step(WorkflowStep.NODES_CHECK, 'failed', message)\n"
        "    finish(False, message)\n"
        "    raise SystemExit(1)\n"
        "print('this line should not execute')\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "agents_config.json"
    config_path.write_text(json.dumps({"agents": {}, "primary_agents": []}), encoding="utf-8")

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT}:{ECHO_PYTHON}:{env.get('PYTHONPATH', '')}"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "runtime" / "run_recordlab_script.py"),
            "--project-root",
            str(ROOT),
            "--config",
            str(config_path),
            "--script",
            str(script_path),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
    )

    assert completed.returncode == 1
    assert "this line should not execute" not in completed.stdout
    events = workflow_events(completed.stdout)
    assert events
    final = events[-1]
    assert final["finished"] is True
    assert final["success"] is False
    assert "missing_node" in final["message"]
    assert [step["key"] for step in final["steps"]] == ["nodes_check", "start_device", "stop_record"]
    assert final["steps"][0]["status"] == "failed"
    assert final["steps"][1]["status"] == "pending"
    assert final["steps"][2]["status"] == "pending"
    required = [event for event in runtime_events(completed.stdout) if event.get("type") == "required_agents"]
    assert required
    assert required[-1]["agent_names"] == ["missing_node"]


def test_script_runtime_fails_nodes_check_when_host_bridge_does_not_reply(tmp_path):
    script_path = tmp_path / "host_bridge_check.py"
    script_path.write_text(
        "all_agent_names = ['glasses_nviz_node', 'UR_node']\n"
        "from flowagent.core.script_workflow import WorkflowStep, finish, set_step, set_steps\n"
        "from nviz_ur_base import check_required_script_agents\n"
        "set_steps([WorkflowStep.NODES_CHECK, WorkflowStep.START_DEVICE, WorkflowStep.STOP_RECORD], title='桥接超时流程')\n"
        "set_step(WorkflowStep.NODES_CHECK, 'running', '正在检查节点连接')\n"
        "ready, message = check_required_script_agents(script_agents, all_agent_names, timeout=0.1)\n"
        "if not ready:\n"
        "    set_step(WorkflowStep.NODES_CHECK, 'failed', message)\n"
        "    finish(False, message)\n"
        "    raise SystemExit(1)\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "agents_config.json"
    config_path.write_text(
        json.dumps(
            {
                "agents": {
                    "glasses_nviz_node": {"goal_port": 15557, "feedback_port": 15558},
                    "UR_node": {"goal_port": 15559, "feedback_port": 15560},
                },
                "primary_agents": [],
            }
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT}:{ECHO_PYTHON}:{env.get('PYTHONPATH', '')}"
    env["RECORDLAB_USE_HOST_BRIDGE"] = "1"
    process = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "scripts" / "runtime" / "run_recordlab_script.py"),
            "--project-root",
            str(ROOT),
            "--config",
            str(config_path),
            "--script",
            str(script_path),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        returncode = process.wait(timeout=5)
        stdout = process.stdout.read()
        stderr = process.stderr.read()
    finally:
        if process.stdin:
            process.stdin.close()
        if process.poll() is None:
            process.kill()

    assert returncode == 1, stderr
    events = workflow_events(stdout)
    assert events
    final = events[-1]
    assert final["finished"] is True
    assert final["success"] is False
    assert "glasses_nviz_node" in final["message"]
    assert "UR_node" in final["message"]
    assert "连接超时/无响应" in final["message"]
    assert final["steps"][0]["status"] == "failed"
    assert final["steps"][1]["status"] == "pending"
    assert final["steps"][2]["status"] == "pending"
