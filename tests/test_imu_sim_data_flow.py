"""Test imu_sim data flow: CSV read -> callback -> publish -> record."""
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

# Ensure importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from recordlab_nodes.nodes.imu_sim.csv_data_reader import CsvDataReader
from recordlab_nodes.nodes.imu_sim.imu_data_player import ImuDataPlayer
from recordlab_nodes.nodes.imu_sim.dataset_device import DatasetDevice
from recordlab_nodes.core.record_writers import CsvDataWriter


SAMPLE_CSV = str(Path(__file__).resolve().parents[1] / "data" / "samples" / "imu_0.csv")


def test_csv_reader():
    """Test that CsvDataReader reads and parses the sample CSV correctly."""
    reader = CsvDataReader()
    assert reader.open(SAMPLE_CSV), "Failed to open sample CSV"
    row = reader.read_and_parse()
    assert row is not None, "First row is None"
    print(f"[OK] CSV reader row keys: {sorted(row.keys())}")
    print(f"[OK] First row: {row}")
    required = ["timestamp_ns", "type", "data0", "data1", "data2", "data3", "data4", "data5"]
    for field in required:
        assert field in row, f"Missing required field: {field}"
    print(f"[OK] All required fields present")
    reader.close()


def test_dataset_device_field_check():
    """Test that DatasetDevice's REQUIRED_FIELDS match CSV columns."""
    reader = CsvDataReader()
    assert reader.open(SAMPLE_CSV)
    row = reader.read_and_parse()
    reader.close()

    csv_keys = set(row.keys())
    required = set(DatasetDevice.REQUIRED_FIELDS)
    missing = required - csv_keys
    assert not missing, f"REQUIRED_FIELDS not in CSV: {missing}"
    print(f"[OK] All REQUIRED_FIELDS are present in CSV data")

    # Check what NVIZ_FIELDS are missing (these are optional for sim)
    nviz_only = set(DatasetDevice.NVIZ_FIELDS) - csv_keys
    if nviz_only:
        print(f"[INFO] NVIZ-only fields NOT in CSV (expected for sim): {nviz_only}")


def test_dataset_device_callback():
    """Test that DatasetDevice calls the IMU callback with correct data."""
    reader = CsvDataReader()
    player = ImuDataPlayer(reader)
    device = DatasetDevice(player)

    received = []

    def on_imu(msg):
        received.append(msg)

    device.set_imu_data_callback(on_imu)
    result = device.initialize({"read_path": SAMPLE_CSV})
    assert result["success"], f"Init failed: {result}"
    print(f"[OK] Device initialized")

    result = device.start()
    assert result["success"], f"Start failed: {result}"
    print(f"[OK] Device started, waiting for data...")

    # Wait for some data
    deadline = time.time() + 5.0
    while len(received) < 10 and time.time() < deadline:
        time.sleep(0.1)

    device.stop()

    print(f"[OK] Received {len(received)} IMU messages")
    assert len(received) > 0, "No IMU messages received - DATA FLOW IS BROKEN!"

    # Verify message structure
    msg = received[0]
    assert "type" in msg, "Missing 'type' in IMU message"
    assert "timestamp_ns" in msg, "Missing 'timestamp_ns' in IMU message"
    assert "data" in msg, "Missing 'data' in IMU message"
    assert len(msg["data"]) == 6, f"Expected 6 data values, got {len(msg['data'])}"
    print(f"[OK] Message structure verified: {msg}")


def test_record_writer():
    """Test that CsvDataWriter correctly writes data to files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        writer = CsvDataWriter(filename="test_imu.csv", buffer_size=5)
        writer.open(tmpdir)

        for i in range(20):
            writer.write_data({
                "timestamp_ns": 100000 + i * 1000,
                "type": 1,
                "data0": 0.1 * i,
                "data1": 0.2 * i,
                "data2": 0.3 * i,
                "data3": 0.4 * i,
                "data4": 0.5 * i,
                "data5": 0.6 * i,
            })

        writer.close()

        output_file = Path(tmpdir) / "test_imu.csv"
        assert output_file.exists(), "Output file not created"
        content = output_file.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 21, f"Expected 21 lines (header + 20 rows), got {len(lines)}"
        print(f"[OK] Record writer: {len(lines)} lines written")
        print(f"[OK] Header: {lines[0]}")
        print(f"[OK] First row: {lines[1]}")


def test_end_to_end_with_recording():
    """Full end-to-end test: device reads CSV, fires callback, data gets recorded."""
    reader = CsvDataReader()
    player = ImuDataPlayer(reader)
    device = DatasetDevice(player)

    published = []
    with tempfile.TemporaryDirectory() as tmpdir:
        writer = CsvDataWriter(filename="imu_data.csv", buffer_size=50)

        def on_imu(msg):
            published.append(msg)
            row = {
                "timestamp_ns": int(msg["timestamp_ns"]),
                "type": int(msg["type"]),
                "data0": float(msg["data"][0]),
                "data1": float(msg["data"][1]),
                "data2": float(msg["data"][2]),
                "data3": float(msg["data"][3]),
                "data4": float(msg["data"][4]),
                "data5": float(msg["data"][5]),
            }
            writer.write_data(row)

        device.set_imu_data_callback(on_imu)
        device.initialize({"read_path": SAMPLE_CSV})

        writer.open(tmpdir)
        device.start()

        # Wait for data
        deadline = time.time() + 5.0
        while len(published) < 100 and time.time() < deadline:
            time.sleep(0.1)

        device.stop()
        writer.close()

        output_file = Path(tmpdir) / "imu_data.csv"
        assert output_file.exists(), "Recording file not created"
        content = output_file.read_text()
        lines = content.strip().split("\n")
        data_lines = len(lines) - 1  # minus header
        print(f"[OK] End-to-end: published={len(published)}, recorded={data_lines}")
        assert data_lines > 0, "No data recorded - RECORDING IS BROKEN!"
        assert len(published) > 0, "No data published - PUBLISH IS BROKEN!"
        print(f"[OK] End-to-end test PASSED!")


if __name__ == "__main__":
    tests = [
        ("CSV Reader", test_csv_reader),
        ("Field Check", test_dataset_device_field_check),
        ("Device Callback", test_dataset_device_callback),
        ("Record Writer", test_record_writer),
        ("End-to-End Recording", test_end_to_end_with_recording),
    ]

    passed = 0
    failed = 0
    for name, func in tests:
        print(f"\n{'='*60}")
        print(f"TEST: {name}")
        print(f"{'='*60}")
        try:
            func()
            passed += 1
            print(f"✓ PASSED: {name}")
        except Exception as e:
            failed += 1
            print(f"✗ FAILED: {name}: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*60}")
    print(f"RESULTS: {passed} passed, {failed} failed")
    print(f"{'='*60}")
    sys.exit(1 if failed else 0)
