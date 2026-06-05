import argparse
import importlib
import json
import signal
import time
from pathlib import Path
from typing import Any, Dict

from recordlab_nodes.common.paths import ensure_echo_python_on_path, resolve_agent_paths

ensure_echo_python_on_path()

from message_system import ActionServer, GoalStatus  # noqa: E402

from .publishers import PublisherManager


def load_agent_config(config_path: str, agent_name: str) -> Dict[str, Any]:
    config_file = Path(config_path).expanduser().resolve()
    with open(config_file, "r", encoding="utf-8") as fh:
        config = json.load(fh)
    try:
        item = config["agents"][agent_name]
    except KeyError as exc:
        raise KeyError(f"Agent not found in config: {agent_name}") from exc
    config_base = config_file.parent.parent if config_file.parent.name == "config" else config_file.parent
    agent_config = resolve_agent_paths(item, config_base)
    validate_agent_config(agent_config)
    return agent_config


def validate_agent_config(agent_config: Dict[str, Any]) -> None:
    if "data_port" not in agent_config:
        raise KeyError(f"Agent missing data_port: {agent_config.get('name', '<unknown>')}")
    for topic in agent_config.get("topics", []):
        if "port" in topic:
            raise ValueError(
                "topics[].port is no longer supported; use agent data_port instead: "
                f"{agent_config.get('name', '<unknown>')}/{topic.get('name', '<unknown>')}"
            )


def import_node_class(path: str):
    module_name, class_name = path.rsplit(".", 1)
    module = importlib.import_module(module_name)
    return getattr(module, class_name)


def ensure_qcore_application():
    from PySide6.QtCore import QCoreApplication

    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


class NodeRuntime:
    def __init__(self, agent_config: Dict[str, Any]):
        self.agent_config = agent_config
        self.node_class = import_node_class(agent_config["node_class"])
        self.qt_app = ensure_qcore_application() if getattr(self.node_class, "requires_qt_event_loop", False) else None
        self.node = self.node_class(agent_config)
        self.publisher_manager = PublisherManager(
            node_name=agent_config["name"],
            data_port=int(agent_config["data_port"]),
            topic_configs=agent_config.get("topics", []),
        )
        self.node.bind_runtime(self)
        self._action_server = None
        self._stopping = False

    def start(self) -> None:
        self.publisher_manager.start()
        self._action_server = ActionServer(
            name=f"{self.agent_config['name']}/action_server",
            action_name=self.agent_config.get("action_name", f"{self.agent_config['name']}_actions"),
            callback=self._on_goal,
            goal_port=int(self.agent_config["goal_port"]),
            feedback_port=int(self.agent_config["feedback_port"]),
            encoding="json",
        )
        self._action_server.start()

    def publish(self, topic_name: str, data: Dict[str, Any]) -> None:
        self.publisher_manager.publish(topic_name, data)

    def _on_goal(self, goal_id: str, goal_data: Dict[str, Any], server: ActionServer) -> None:
        cmd = goal_data.get("cmd", "")
        params = goal_data.get("params", {})
        handler = getattr(self.node, cmd, None)
        if handler is None or not callable(handler):
            server.send_result(
                goal_id,
                {"success": False, "message": f"Command not found: {cmd}"},
                GoalStatus.FAILED,
            )
            return
        try:
            result = handler(params)
            if not isinstance(result, dict):
                result = {"success": True, "result": result}
            status = GoalStatus.SUCCEEDED if result.get("success", True) else GoalStatus.FAILED
            server.send_result(goal_id, result, status)
        except Exception as exc:
            server.send_result(goal_id, {"success": False, "message": str(exc)}, GoalStatus.FAILED)

    def stop(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        try:
            self.node.shutdown()
        finally:
            if self._action_server:
                self._action_server.close()
            self.publisher_manager.close()
            if self.qt_app is not None:
                self.qt_app.quit()

    def spin(self) -> None:
        if self.qt_app is not None:
            from PySide6.QtCore import QTimer

            timer = QTimer()
            timer.timeout.connect(lambda: None)
            timer.start(500)
            self.qt_app.exec()
            return
        while not self._stopping:
            time.sleep(0.1)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="RecordLab generic Python node runtime")
    parser.add_argument("--config", required=True)
    parser.add_argument("--agent", required=True)
    args = parser.parse_args(argv)

    runtime = NodeRuntime(load_agent_config(args.config, args.agent))

    def _handle_signal(signum, frame):
        runtime.stop()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    runtime.start()
    try:
        runtime.spin()
    finally:
        runtime.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
