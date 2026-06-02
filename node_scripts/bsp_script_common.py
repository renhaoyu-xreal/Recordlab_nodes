import getpass
import json
import os
import re
import signal
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

import paramiko

nodes_root = Path(__file__).resolve().parents[1]
echo_python = Path(os.environ.get("ECHO_MESSAGE_SYSTEM_PYTHON_ROOT", str(nodes_root.parent / "echo_message_system" / "python")))
if echo_python.exists() and str(echo_python) not in sys.path:
    sys.path.insert(0, str(echo_python))

from message_system import ActionClient  # noqa: E402

UNKNOWN_GLASSES_ID = "UNKNOWN_GLASSES"


def sanitize_token(value: Optional[str], fallback: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[\\/\\s]+", "_", text)
    text = re.sub(r"[^0-9A-Za-z._\\-\u4e00-\u9fa5]+", "_", text)
    text = text.strip("._-")
    return text or fallback


def read_glasses_id_via_ssh(timeout_s: float = 3.0) -> Optional[str]:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect("169.254.2.1", port=22, username="root", password="xreal2017", timeout=timeout_s)
        for command in ("/usr/usrdata/bin/getprop ro.bsp.glasses_id", "cat /factory/glasses_config.json 2>/dev/null"):
            stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout_s)
            output = stdout.read().decode("utf-8", errors="ignore").strip()
            if not output:
                continue
            if output.startswith("{"):
                try:
                    config = json.loads(output)
                    value = config.get("FSN") or config.get("glasses_id")
                    if value:
                        return sanitize_token(value, UNKNOWN_GLASSES_ID)
                except Exception:
                    pass
            return sanitize_token(output, UNKNOWN_GLASSES_ID)
    except Exception:
        return None
    finally:
        try:
            ssh.close()
        except Exception:
            pass
    return None


def build_dataset_name(sub_path: str, experiment_keyword: Optional[str] = None, recorder_name: Optional[str] = None) -> Tuple[str, str]:
    glasses_id = read_glasses_id_via_ssh() or UNKNOWN_GLASSES_ID
    exp = sanitize_token(experiment_keyword or os.environ.get("RECORDLAB_BSP_EXPERIMENT_KEYWORD", "exp"), "exp")
    recorder = sanitize_token(recorder_name or os.environ.get("RECORDLAB_BSP_RECORDER_NAME") or os.environ.get("USER") or getpass.getuser(), "user")
    clean_path = str(sub_path).strip("/\\")
    leaf_token = sanitize_token(clean_path.replace("/", "_"), "record")
    timestamp = time.strftime("%Y%m%d%H%M%S")
    leaf = f"{glasses_id}_{exp}_{recorder}_{leaf_token}_{timestamp}"
    return f"{clean_path}/{leaf}", glasses_id


class AgentClient:
    def __init__(self):
        config_path = Path(os.environ.get("RECORDLAB_AGENTS_CONFIG", str(nodes_root / "config" / "agents_config.json")))
        agent_name = os.environ.get("RECORDLAB_AGENT", "glasses_bsp_node")
        config = json.loads(config_path.read_text(encoding="utf-8"))["agents"][agent_name]
        self.client = ActionClient(
            name=f"{agent_name}_script_client",
            action_name=config.get("action_name", f"{agent_name}_actions"),
            goal_host=config.get("subnode_host", "127.0.0.1"),
            goal_port=int(config["goal_port"]),
            feedback_host=config.get("subnode_host", "127.0.0.1"),
            feedback_port=int(config["feedback_port"]),
            timeout=5000,
        )
        if not self.client.wait_for_server(timeout=5000):
            raise RuntimeError("action server not available")
        self.client.start_listening()
        time.sleep(0.2)

    def cmd(self, name: str, params=None, timeout=10000):
        goal_id = self.client.send_goal({"cmd": name, "params": params or {}})
        result, status = self.client.wait_for_result(goal_id, timeout=timeout)
        print(f"{name}: {json.dumps(result, ensure_ascii=False)}", flush=True)
        return result or {"success": False, "message": str(status)}

    def close(self):
        self.client.close()


class RecordingGuard:
    def __init__(self, agent: AgentClient):
        self.agent = agent
        self.recording = False

    def start(self, params):
        result = self.agent.cmd("start_record", params)
        if result.get("success"):
            self.recording = True
        return result

    def stop(self):
        if self.recording:
            result = self.agent.cmd("stop_record", {}, timeout=30000)
            self.recording = False
            return result
        return {"success": True, "message": "Not recording"}

    def install_signal_handlers(self):
        def handle_signal(signum, frame):
            print(f"received signal {signum}, stopping recording", flush=True)
            self.stop()
            raise SystemExit(0)

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)
