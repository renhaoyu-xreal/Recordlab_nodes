from typing import Any, Dict

from recordlab_nodes.nodes.bsp.bsp_main_node import BspMainNode


class HelenMainNode(BspMainNode):
    """MCU/Helen glasses node using the shared XREAL SDK capture pipeline.

    Helen devices expose the same SDK IMU data path used by the BSP node, but
    they are not SSH/nviz devices. Keep the business contract identical while
    disabling SSH-only recording artifacts by default.
    """

    def __init__(self, agent_config: Dict[str, Any]):
        agent_config = dict(agent_config)
        custom = dict(agent_config.get("custom_params", {}) or {})
        custom.setdefault("persist_ssh_artifacts", False)
        agent_config["custom_params"] = custom
        super().__init__(agent_config)
