from abc import abstractmethod
from typing import Any, Dict

from .base_node import BaseNode


class MainNode(BaseNode):
    """Abstract base for acquisition-style nodes."""

    @abstractmethod
    def init_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def start_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def stop_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def release_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def control_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def start_record(self, params: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def stop_record(self, params: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError
