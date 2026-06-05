from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from recordlab_nodes.common.topics import TOPIC_NODE_COOKIE


class BaseNode(ABC):
    """Abstract base for business nodes.

    BaseNode declares the control contract only. Middleware objects are owned by
    node_runtime, not by this abstract class.
    """

    def __init__(self, agent_config: Dict[str, Any]):
        self.agent_config = agent_config
        self.name = agent_config.get("name", self.__class__.__name__)
        self._runtime: Optional[Any] = None

    def bind_runtime(self, runtime: Any) -> None:
        self._runtime = runtime

    def publish(self, topic_name: str, data: Dict[str, Any]) -> None:
        if self._runtime is None:
            raise RuntimeError("Node runtime is not bound")
        self._runtime.publish(topic_name, data)

    def publish_cookie(self, key: str, value: Any, is_display: bool = False) -> None:
        self.publish(TOPIC_NODE_COOKIE, {
            "key": key,
            "value": value,
            "isDisplay": is_display,
        })

    def get_agent_topics(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {"success": True, "topics": self.agent_config.get("topics", [])}

    def get_root_path(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {"success": True, "root_path": self.agent_config.get("root_path", "data")}

    @abstractmethod
    def check(self, params: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def estop(self, params: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def shutdown(self) -> None:
        raise NotImplementedError
