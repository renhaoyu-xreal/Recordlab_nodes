from abc import ABC

from recordlab_nodes.core.base_node import BaseNode
from recordlab_nodes.core.main_node import MainNode


def test_base_node_is_abstract_contract():
    assert issubclass(BaseNode, ABC)
    assert BaseNode.__abstractmethods__ >= {"check", "estop", "shutdown"}


def test_main_node_is_abstract_contract():
    assert issubclass(MainNode, BaseNode)
    assert MainNode.__abstractmethods__ >= {
        "init_device",
        "start_device",
        "stop_device",
        "release_device",
        "control_device",
        "start_record",
        "stop_record",
    }
