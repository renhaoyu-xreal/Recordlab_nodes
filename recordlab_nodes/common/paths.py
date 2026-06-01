import os
import sys
from pathlib import Path
from typing import Any, Dict


def recordlab_nodes_root() -> Path:
    return Path(__file__).resolve().parents[2]


def echo_python_root() -> Path:
    env_path = os.environ.get("ECHO_MESSAGE_SYSTEM_PYTHON_ROOT")
    if env_path:
        return Path(env_path).expanduser().resolve()
    return recordlab_nodes_root().parent / "echo_message_system" / "python"


def ensure_echo_python_on_path() -> None:
    path = echo_python_root()
    if path.exists() and str(path) not in sys.path:
        sys.path.insert(0, str(path))


def resolve_path(value: Any, base: Path) -> Any:
    if not isinstance(value, str):
        return value
    path = Path(value).expanduser()
    if path.is_absolute():
        return str(path)
    return str((base / path).resolve())


def resolve_agent_paths(agent_config: Dict[str, Any], base: Path) -> Dict[str, Any]:
    agent_config = dict(agent_config)
    if "root_path" in agent_config:
        agent_config["root_path"] = resolve_path(agent_config["root_path"], base)
    init_params = dict(agent_config.get("init_device_params", {}))
    if "read_path" in init_params:
        init_params["read_path"] = resolve_path(init_params["read_path"], base)
    agent_config["init_device_params"] = init_params
    return agent_config
