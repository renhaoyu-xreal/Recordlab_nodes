import csv
import time
from pathlib import Path

from recordlab_nodes.nodes.imu_sim.csv_data_reader import CsvDataReader
from recordlab_nodes.nodes.imu_sim.dataset_device import DatasetDevice
from recordlab_nodes.nodes.imu_sim.imu_data_player import ImuDataPlayer
from recordlab_nodes.nodes.imu_sim.imu_sim_node import ImuSimNode


def make_csv(path: Path, rows: int = 5) -> None:
    base_ns = time.time_ns()
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "timestamp",
            "onsensor_timestamp_us",
            "timestamp_ns",
            "type",
            "data0",
            "data1",
            "data2",
            "data3",
            "data4",
            "data5",
        ])
        for i in range(rows):
            writer.writerow([i * 0.001, i * 1000, base_ns + i * 1_000_000, 1, i, i + 1, i + 2, i + 3, i + 4, i + 5])


def test_dataset_device_converts_csv_rows_to_imu(tmp_path):
    csv_path = tmp_path / "imu.csv"
    make_csv(csv_path, 1)
    received = []
    device = DatasetDevice(ImuDataPlayer(CsvDataReader()))
    device.set_imu_data_callback(received.append)

    assert device.initialize({"read_path": str(csv_path)})["success"]
    assert device.start()["success"]
    time.sleep(0.1)
    device.stop()

    assert received
    assert received[0]["type"] == 1
    assert received[0]["data"] == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]


def test_imu_sim_node_records_rows_without_runtime_publish(tmp_path):
    config = {
        "name": "imu_simulation",
        "root_path": str(tmp_path),
        "topics": [],
    }
    node = ImuSimNode(config)
    published = []

    class Runtime:
        def publish(self, topic, data):
            published.append((topic, data))

    node.bind_runtime(Runtime())
    assert node.start_record({"dataset_name": "case"})["success"]
    node._on_imu({"type": 1, "timestamp_ns": 1, "data": [1, 2, 3, 4, 5, 6]})
    assert node.stop_record({})["success"]

    output = tmp_path / "case" / "imu_data.csv"
    assert output.exists()
    rows = list(csv.DictReader(output.open(encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["data5"] == "6.0"
    assert any(topic == "imu_data" for topic, _ in published)
