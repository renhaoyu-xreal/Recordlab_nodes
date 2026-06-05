from recordlab_nodes.common.motion_detector import MotionDetector


def imu_message(data_type, timestamp_ns, values):
    return {"type": data_type, "timestamp_ns": timestamp_ns, "data": values}


def test_motion_detector_uses_windowed_statistics_for_static_state():
    detector = MotionDetector()
    status = None
    for i in range(240):
        timestamp_ns = i * 10_000_000
        data_type = 1 if i % 2 == 0 else 2
        status = detector.detect(imu_message(data_type, timestamp_ns, [0.01, 0.01, 0.01, 0, 0, 0]))

    assert status["status"] == "static"


def test_motion_detector_classifies_high_variance_as_motion():
    detector = MotionDetector()
    status = None
    for i in range(240):
        timestamp_ns = i * 10_000_000
        value = 0.0 if i % 2 == 0 else 1.0
        status = detector.detect(imu_message(2, timestamp_ns, [value, -value, value, 0, 0, 0]))

    assert status["status"] in {"moving", "active"}
