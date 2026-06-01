from typing import Dict


class DataRegistryClient:
    """Placeholder client for Host DataRegistryServer integration.

    The MVP does not require dynamic registration. Keeping this small class lets
    concrete nodes depend on a stable API without pulling Host code into Nodes.
    """

    def register_data(self, data_name: str, data_type: str, port: int, node_name: str = "") -> Dict:
        return {
            "success": True,
            "data_name": data_name,
            "data_type": data_type,
            "port": port,
            "node_name": node_name,
        }
