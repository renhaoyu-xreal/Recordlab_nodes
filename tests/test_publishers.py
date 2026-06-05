import socket

import zmq

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
