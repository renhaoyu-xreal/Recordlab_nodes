import time

from bsp_script_common import AgentClient, RecordingGuard, build_dataset_name

RECORD_DURATION_S = 10


def main():
    print("[BSP_IMU_DYNAMIC] record 10s non-static BSP IMU")
    dataset_name, glasses_id = build_dataset_name("nostill10s_imu")
    print(f"[BSP_IMU_DYNAMIC] glasses_id={glasses_id}")
    print(f"[BSP_IMU_DYNAMIC] dataset=data/{dataset_name}")
    agent = AgentClient()
    guard = RecordingGuard(agent)
    guard.install_signal_handlers()
    try:
        result = guard.start({
            "dataset_name": dataset_name,
            "enable_camera_snapshot": True,
            "enable_screen_capture": True,
            "enable_mic_recording": True,
        })
        if not result.get("success"):
            raise SystemExit(result.get("message", "start_record failed"))
        started = time.monotonic()
        while time.monotonic() - started < RECORD_DURATION_S:
            print(f"[BSP_IMU_DYNAMIC] recording {time.monotonic() - started:.1f}/{RECORD_DURATION_S}s", flush=True)
            time.sleep(1)
        guard.stop()
    finally:
        if guard.recording:
            guard.stop()
        agent.close()


if __name__ == "__main__":
    main()
