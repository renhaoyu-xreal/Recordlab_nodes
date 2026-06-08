import time

from bsp_script_common import (
    AgentClient,
    RecordingGuard,
    begin_bsp_workflow,
    build_dataset_name,
    finish_bsp_workflow,
    mark_bsp_connect_failed,
    mark_bsp_connected,
)
from flowagent.core.script_workflow import WorkflowStep, set_step

RECORD_DURATION_S = 10


def main():
    print("[BSP_IMU_STATIC] record 10s static BSP IMU")
    begin_bsp_workflow(
        "BSP IMU 静止 10s 录制",
        [WorkflowStep.START_RECORD, WorkflowStep.GET_BSP_RUNTIME_STATE, WorkflowStep.STOP_RECORD, WorkflowStep.DELETE_RECORD],
    )
    dataset_name, glasses_id = build_dataset_name("still10s_imu")
    print(f"[BSP_IMU_STATIC] glasses_id={glasses_id}")
    print(f"[BSP_IMU_STATIC] dataset=data/{dataset_name}")
    agent = None
    guard = None
    success = True
    try:
        agent = AgentClient()
        mark_bsp_connected()
        guard = RecordingGuard(agent)
        guard.install_signal_handlers()
        set_step(WorkflowStep.START_RECORD, "running", "正在开始静止录制")
        result = guard.start({
            "dataset_name": dataset_name,
            "enable_camera_snapshot": True,
            "enable_screen_capture": True,
            "enable_mic_recording": True,
        })
        if not result.get("success"):
            set_step(WorkflowStep.START_RECORD, "failed", result.get("message", "start_record failed"))
            finish_bsp_workflow(False, result.get("message", "start_record failed"))
            raise SystemExit(result.get("message", "start_record failed"))
        set_step(WorkflowStep.START_RECORD, "running", "录制中")
        started = time.monotonic()
        while time.monotonic() - started < RECORD_DURATION_S:
            set_step(WorkflowStep.GET_BSP_RUNTIME_STATE, "running", "正在检查静止状态")
            state = agent.cmd("get_bsp_runtime_state", {}, timeout=5000)
            motion_status = (state.get("motion_status") or {}).get("status")
            set_step(WorkflowStep.GET_BSP_RUNTIME_STATE, "success", f"motion_status={motion_status}")
            print(f"[BSP_IMU_STATIC] motion_status={motion_status}", flush=True)
            if motion_status not in ("static", "none", None):
                success = False
                print(f"[BSP_IMU_STATIC] motion detected: {motion_status}", flush=True)
                set_step(WorkflowStep.GET_BSP_RUNTIME_STATE, "failed", f"检测到运动: {motion_status}")
                break
            time.sleep(1)
        set_step(WorkflowStep.STOP_RECORD, "running", "正在停止录制")
        guard.stop()
        set_step(WorkflowStep.STOP_RECORD, "success", "录制已停止")
        if success:
            set_step(WorkflowStep.START_RECORD, "success", "静止录制完成")
            set_step(WorkflowStep.DELETE_RECORD, "success", "无需删除")
            finish_bsp_workflow(True, "静止录制完成")
    except Exception:
        success = False
        mark_bsp_connect_failed("脚本执行异常")
        raise
    finally:
        if guard and guard.recording:
            set_step(WorkflowStep.STOP_RECORD, "running", "正在停止录制")
            guard.stop()
            set_step(WorkflowStep.STOP_RECORD, "success", "录制已停止")
        if not success:
            if agent:
                set_step(WorkflowStep.DELETE_RECORD, "running", "正在删除异常录制数据")
                agent.cmd("delete_record", {"dataset_name": dataset_name}, timeout=10000)
                set_step(WorkflowStep.DELETE_RECORD, "success", "异常录制数据已删除")
            finish_bsp_workflow(False, "静止录制失败，已清理数据")
        if agent:
            agent.close()


if __name__ == "__main__":
    main()
