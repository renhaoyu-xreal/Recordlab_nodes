import time

from bsp_script_common import AgentClient, RecordingGuard, build_dataset_name


def main():
    print("[BSP_IMU] free record BSP IMU")
    dataset_name, glasses_id = build_dataset_name("free_record/only_imu")
    print(f"[BSP_IMU] glasses_id={glasses_id}")
    print(f"[BSP_IMU] dataset=data/{dataset_name}")
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
        while True:
            time.sleep(1)
            print("[BSP_IMU] recording...", flush=True)
    finally:
        guard.stop()
        agent.close()


if __name__ == "__main__":
    main()
