import socket
import threading

import zmq

from recordlab_nodes.common.data_registry_client import DataRegistryClient
from recordlab_nodes.core.publishers import SharedTopicPublisher


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_shared_topic_publisher_does_not_apply_camera_qos_to_imu_socket():
    publisher = SharedTopicPublisher(
        "bsp",
        free_port(),
        [
            {"name": "imu_data", "encoding": "json"},
            {
                "name": "camera_data",
                "encoding": "json_binary",
                "qos": {
                    "history": "latest",
                    "depth": 1,
                    "drop_when_busy": True,
                    "send_timeout_ms": 0,
                },
            },
        ],
    )
    try:
        assert publisher.socket.getsockopt(zmq.SNDHWM) > 1
        assert publisher.socket.getsockopt(zmq.SNDTIMEO) > 0
    finally:
        publisher.close()


def test_data_registry_client_registers_topic_shape():
    port = free_port()
    received = {}

    def server():
        context = zmq.Context()
        socket_rep = context.socket(zmq.REP)
        socket_rep.setsockopt(zmq.LINGER, 0)
        socket_rep.bind(f"tcp://127.0.0.1:{port}")
        try:
            request = socket_rep.recv_json()
            received.update(request)
            socket_rep.send_json({"success": True, "stream": request["stream"]})
        finally:
            socket_rep.close()
            context.term()

    thread = threading.Thread(target=server, daemon=True)
    thread.start()
    client = DataRegistryClient(port=port, timeout_ms=1000)
    response = client.register_data(
        data_name="imu_data",
        data_type="topic",
        port=16510,
        node_name="imu_node",
        encoding="json",
        parse_mode="type_vector6_fast",
        ui_max_hz=60.0,
    )
    thread.join(timeout=2.0)
    assert response["success"] is True
    assert received["action"] == "register_data"
    assert received["stream"]["data_name"] == "imu_data"
    assert received["stream"]["parse_mode"] == "type_vector6_fast"
