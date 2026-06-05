import os
from typing import Any, Dict, Iterable

import zmq


class DataRegistryClient:
    """Client for Host DataRegistryServer integration."""

    def __init__(self, host: str | None = None, port: int | None = None, timeout_ms: int = 100):
        self.host = host or os.environ.get("RECORDLAB_DATA_REGISTRY_HOST", "127.0.0.1")
        self.port = int(port or os.environ.get("RECORDLAB_DATA_REGISTRY_PORT", "16600"))
        self.timeout_ms = timeout_ms

    def _call(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        context = zmq.Context()
        socket = context.socket(zmq.REQ)
        socket.setsockopt(zmq.RCVTIMEO, self.timeout_ms)
        socket.setsockopt(zmq.SNDTIMEO, self.timeout_ms)
        socket.setsockopt(zmq.LINGER, 0)
        try:
            socket.connect(f"tcp://{self.host}:{self.port}")
            socket.send_json(payload)
            return socket.recv_json()
        except Exception as exc:
            return {"success": False, "error": str(exc)}
        finally:
            socket.close()
            context.term()

    def register_data(
        self,
        data_name: str,
        data_type: str,
        port: int,
        node_name: str = "",
        host: str = "127.0.0.1",
        encoding: str = "json",
        parse_mode: str = "json",
        ui_max_hz: float = 30.0,
        qos: Dict[str, Any] | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        stream = {
            "data_name": data_name,
            "data_type": data_type,
            "host": host,
            "port": int(port),
            "node_name": node_name,
            "encoding": encoding,
            "parse_mode": parse_mode,
            "ui_max_hz": ui_max_hz,
            "qos": qos or {},
            "metadata": metadata or {},
        }
        return self._call({"action": "register_data", "stream": stream})

    def unregister_data(self, data_name: str, port: int, node_name: str = "") -> Dict[str, Any]:
        return self._call(
            {
                "action": "unregister_data",
                "stream": {"data_name": data_name, "port": int(port), "node_name": node_name},
            }
        )

    def list_data(self) -> Dict[str, Any]:
        return self._call({"action": "list_data"})

    def register_topics(self, node_name: str, data_port: int, topics: Iterable[Dict[str, Any]]) -> list[Dict[str, Any]]:
        results = []
        for topic in topics:
            results.append(
                self.register_data(
                    data_name=topic.get("name", ""),
                    data_type=topic.get("data_type", "topic"),
                    port=data_port,
                    node_name=node_name,
                    host=topic.get("host", "127.0.0.1"),
                    encoding=topic.get("encoding", "json"),
                    parse_mode=topic.get("parse_mode", "json"),
                    ui_max_hz=float(topic.get("ui_max_hz", 30.0)),
                    qos=topic.get("qos") or {},
                    metadata=topic.get("metadata") or {},
                )
            )
        return results
