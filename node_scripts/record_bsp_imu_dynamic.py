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
    print("[BSP_IMU_DYNAMIC] record 10s non-static BSP IMU")
    begin_bsp_workflow("BSP IMU 动态 10s 录制", [WorkflowStep.START_RECORD, WorkflowStep.STOP_RECORD])
    dataset_name, glasses_id = build_dataset_name("nostill10s_imu")
    print(f"[BSP_IMU_DYNAMIC] glasses_id={glasses_id}")
    print(f"[BSP_IMU_DYNAMIC] dataset=data/{dataset_name}")
    agent = None
    guard = None
    try:
        agent = AgentClient()
        mark_bsp_connected()
        guard = RecordingGuard(agent)
        guard.install_signal_handlers()
        set_step(WorkflowStep.START_RECORD, "running", "正在开始动态录制")
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
            elapsed = time.monotonic() - started
            set_step(WorkflowStep.START_RECORD, "running", f"录制中 {elapsed:.1f}/{RECORD_DURATION_S}s")
            print(f"[BSP_IMU_DYNAMIC] recording {elapsed:.1f}/{RECORD_DURATION_S}s", flush=True)
            time.sleep(1)
        set_step(WorkflowStep.STOP_RECORD, "running", "正在停止录制")
        guard.stop()
        set_step(WorkflowStep.STOP_RECORD, "success", "录制已停止")
        set_step(WorkflowStep.START_RECORD, "success", "动态录制完成")
        finish_bsp_workflow(True, "动态录制完成")
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
