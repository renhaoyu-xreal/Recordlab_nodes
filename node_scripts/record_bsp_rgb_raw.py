from bsp_script_common import (
    AgentClient,
    begin_bsp_workflow,
    build_dataset_name,
    finish_bsp_workflow,
    mark_bsp_connect_failed,
    mark_bsp_connected,
)
from flowagent.core.script_workflow import WorkflowStep, set_step


def main():
    print("[BSP_RGB_RAW] single BSP RGB RAW capture")
    begin_bsp_workflow(
        "BSP RGB RAW 单帧捕获",
        [WorkflowStep.GET_BSP_RUNTIME_STATE, WorkflowStep.CAPTURE_RAW_FRAME],
    )
    dataset_name, glasses_id = build_dataset_name("slam_rgb_imu")
    print(f"[BSP_RGB_RAW] glasses_id={glasses_id}")
    print(f"[BSP_RGB_RAW] dataset=data/{dataset_name}")
    agent = None
    try:
        agent = AgentClient()
        mark_bsp_connected()
        set_step(WorkflowStep.GET_BSP_RUNTIME_STATE, "running", "正在获取 BSP 运行状态")
        state = agent.cmd("get_bsp_runtime_state", {}, timeout=5000)
        set_step(WorkflowStep.GET_BSP_RUNTIME_STATE, "success", f"camera_mode={state.get('camera_mode')}")
        print(f"[BSP_RGB_RAW] camera_mode={state.get('camera_mode')}")
        set_step(WorkflowStep.CAPTURE_RAW_FRAME, "running", "正在捕获 RAW 帧")
        result = agent.cmd("capture_raw_frame", {"dataset_name": dataset_name}, timeout=150000)
        if not result.get("success"):
            set_step(WorkflowStep.CAPTURE_RAW_FRAME, "failed", result.get("message", "capture_raw_frame failed"))
            finish_bsp_workflow(False, result.get("message", "capture_raw_frame failed"))
            raise SystemExit(result.get("message", "capture_raw_frame failed"))
        set_step(WorkflowStep.CAPTURE_RAW_FRAME, "success", "RAW 帧捕获完成")
        finish_bsp_workflow(True, "RAW 帧捕获完成")
    except Exception as exc:
        mark_bsp_connect_failed(str(exc))
        raise
    finally:
        if agent:
            agent.close()


if __name__ == "__main__":
    main()
