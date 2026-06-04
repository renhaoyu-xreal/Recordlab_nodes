import json
import os
import subprocess
import sys
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


def test_script_runtime_reports_missing_nodes_in_workflow(tmp_path):
    script_path = tmp_path / "needs_node.py"
    script_path.write_text(
        "all_agent_names = ['missing_node']\n"
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
    assert final["steps"][0]["key"] == "nodes_check"
    assert final["steps"][0]["status"] == "failed"

