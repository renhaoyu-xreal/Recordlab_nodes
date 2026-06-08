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


def main():
    print("[BSP_IMU] free record BSP IMU")
    begin_bsp_workflow("BSP IMU 自由录制", [WorkflowStep.START_RECORD, WorkflowStep.STOP_RECORD])
    dataset_name, glasses_id = build_dataset_name("free_record/only_imu")
    print(f"[BSP_IMU] glasses_id={glasses_id}")
    print(f"[BSP_IMU] dataset=data/{dataset_name}")
    agent = None
    guard = None
    try:
        agent = AgentClient()
        mark_bsp_connected()
        guard = RecordingGuard(agent)
        guard.install_signal_handlers()
        set_step(WorkflowStep.START_RECORD, "running", "正在开始 BSP IMU 录制")
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
        while True:
            time.sleep(1)
            print("[BSP_IMU] recording...", flush=True)
    except Exception as exc:
        mark_bsp_connect_failed(str(exc))
        raise
    finally:
        if guard and guard.recording:
            set_step(WorkflowStep.STOP_RECORD, "running", "正在停止录制")
            guard.stop()
            set_step(WorkflowStep.STOP_RECORD, "success", "录制已停止")
            finish_bsp_workflow(False, "脚本已停止")
        if agent:
            agent.close()


if __name__ == "__main__":
    main()
