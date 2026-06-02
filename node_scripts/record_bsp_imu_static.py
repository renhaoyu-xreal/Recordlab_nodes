import time

from bsp_script_common import AgentClient, RecordingGuard, build_dataset_name

RECORD_DURATION_S = 10


def main():
    print("[BSP_IMU_STATIC] record 10s static BSP IMU")
    dataset_name, glasses_id = build_dataset_name("still10s_imu")
    print(f"[BSP_IMU_STATIC] glasses_id={glasses_id}")
    print(f"[BSP_IMU_STATIC] dataset=data/{dataset_name}")
    agent = AgentClient()
    guard = RecordingGuard(agent)
    guard.install_signal_handlers()
    success = True
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
            state = agent.cmd("get_bsp_runtime_state", {}, timeout=5000)
            motion_status = (state.get("motion_status") or {}).get("status")
            print(f"[BSP_IMU_STATIC] motion_status={motion_status}", flush=True)
            if motion_status not in ("static", "none", None):
                success = False
                print(f"[BSP_IMU_STATIC] motion detected: {motion_status}", flush=True)
                break
            time.sleep(1)
        guard.stop()
    except Exception:
        success = False
        raise
    finally:
        if guard.recording:
            guard.stop()
        if not success:
            agent.cmd("delete_record", {"dataset_name": dataset_name}, timeout=10000)
        agent.close()


if __name__ == "__main__":
    main()
