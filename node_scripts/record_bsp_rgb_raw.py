from bsp_script_common import AgentClient, build_dataset_name


def main():
    print("[BSP_RGB_RAW] single BSP RGB RAW capture")
    dataset_name, glasses_id = build_dataset_name("slam_rgb_imu")
    print(f"[BSP_RGB_RAW] glasses_id={glasses_id}")
    print(f"[BSP_RGB_RAW] dataset=data/{dataset_name}")
    agent = AgentClient()
    try:
        state = agent.cmd("get_bsp_runtime_state", {}, timeout=5000)
        print(f"[BSP_RGB_RAW] camera_mode={state.get('camera_mode')}")
        result = agent.cmd("capture_raw_frame", {"dataset_name": dataset_name}, timeout=150000)
        if not result.get("success"):
            raise SystemExit(result.get("message", "capture_raw_frame failed"))
    finally:
        agent.close()


if __name__ == "__main__":
    main()
