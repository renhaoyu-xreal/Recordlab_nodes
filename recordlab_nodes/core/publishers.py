import time
from typing import Any, Dict, Optional

import zmq

from recordlab_nodes.common.paths import ensure_echo_python_on_path

ensure_echo_python_on_path()
from message_system import Message  # noqa: E402


class SharedTopicPublisher:
    def __init__(self, node_name: str, port: int, topic_configs):
        self.node_name = node_name
        self.port = int(port)
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        # Topic-level QoS cannot be applied to one shared PUB socket. Keep the
        # socket neutral so a latest-only camera topic does not throttle IMU.
        self.socket.setsockopt(zmq.SNDHWM, 10000)
        self.socket.setsockopt(zmq.SNDTIMEO, 100)
        self.socket.setsockopt(zmq.LINGER, 0)
        self.socket.bind(f"tcp://*:{self.port}")

    def publish(self, topic_name: str, data: Dict[str, Any], encoding: str) -> None:
        payload = Message(data=data, encoding=encoding).serialize()
        self.socket.send_multipart([topic_name.encode("utf-8"), payload])

    def close(self) -> None:
        self.socket.close()
        self.context.term()


class PublisherManager:
    def __init__(self, node_name: str, data_port: int, topic_configs):
        self.node_name = node_name
        self.data_port = int(data_port)
        self.topic_configs = {item["name"]: item for item in topic_configs}
        self.publisher: Optional[SharedTopicPublisher] = None

    def start(self) -> None:
        if self.topic_configs:
            self.publisher = SharedTopicPublisher(self.node_name, self.data_port, self.topic_configs.values())
            time.sleep(0.2)

    def publish(self, topic_name: str, data: Dict[str, Any]) -> None:
        if topic_name not in self.topic_configs:
            raise KeyError(f"Topic not configured: {topic_name}")
        if self.publisher is None:
            raise RuntimeError("PublisherManager has not been started")
        encoding = self.topic_configs[topic_name].get("encoding", "json")
        self.publisher.publish(topic_name, data, encoding)

    def close(self) -> None:
        if self.publisher is not None:
            self.publisher.close()
            self.publisher = None
