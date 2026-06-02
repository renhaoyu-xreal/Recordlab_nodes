from recordlab_nodes.common.paths import ensure_echo_python_on_path

ensure_echo_python_on_path()

from message_system.message import Message  # noqa: E402


def test_json_binary_round_trips_bytes():
    msg = Message(
        {
            "image": {
                "width": 2,
                "height": 1,
                "data": b"\x01\x02\x03\x04",
            }
        },
        encoding="json_binary",
    )

    decoded = Message.deserialize(msg.serialize(), "json_binary").data

    assert decoded["image"]["data"] == b"\x01\x02\x03\x04"
