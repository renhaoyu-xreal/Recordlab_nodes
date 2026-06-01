import time
from typing import Any, Dict

from recordlab_nodes.common.paths import ensure_echo_python_on_path

ensure_echo_python_on_path()
from message_system import Publisher  # noqa: E402


class PublisherManager:
    def __init__(self, node_name: str, topic_configs):
        self.node_name = node_name
        self.topic_configs = {item["name"]: item for item in topic_configs}
        self.publishers: Dict[str, Publisher] = {}

    def start(self) -> None:
        for topic_name, cfg in self.topic_configs.items():
            pub = Publisher(
                name=f"{self.node_name}/{topic_name}",
                topic=topic_name,
                port=int(cfg["port"]),
                encoding=cfg.get("encoding", "json"),
            )
            pub.start()
            self.publishers[topic_name] = pub
        if self.publishers:
            time.sleep(0.2)

    def publish(self, topic_name: str, data: Dict[str, Any]) -> None:
        if topic_name not in self.publishers:
            raise KeyError(f"Topic not configured: {topic_name}")
        self.publishers[topic_name].publish(data)

    def close(self) -> None:
        for pub in self.publishers.values():
            close = getattr(pub, "close", None)
            if close:
                close()
        self.publishers.clear()
