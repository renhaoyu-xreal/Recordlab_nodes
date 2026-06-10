from flowagent.core.script_workflow import WorkflowStep, finish, set_step

from bsp_script_common import (
    begin_bsp_workflow,
    build_dataset_name,
    prompt_bsp_record_context,
    require_bsp_agent,
    run_timed_record_loop,
    start_record_or_fail,
    stop_record,
)


all_agent_names = ["glasses_bsp_node"]

print("[BSP_IMU_DYNAMIC] record dynamic BSP IMU")

begin_bsp_workflow("BSP IMU 动态定时录制", [WorkflowStep.CHECK, WorkflowStep.START_RECORD, WorkflowStep.STOP_RECORD])
glasses_bsp_node = require_bsp_agent(script_agents, globals().get("unavailable_script_agents"))

set_step(WorkflowStep.CHECK, "running", "正在填写录制信息")
try:
    context = prompt_bsp_record_context(
        dialog,
        title="BSP 动态录制信息",
        message="请填写实验关键字、录制人和录制时长",
        include_duration=True,
    )
except ValueError as exc:
    set_step(WorkflowStep.CHECK, "failed", str(exc))
    finish(False, str(exc))
    raise SystemExit(1)

if context is None:
    set_step(WorkflowStep.CHECK, "failed", "已取消录制信息输入")
    finish(False, "已取消录制信息输入")
    raise SystemExit(1)

dataset_name, glasses_id = build_dataset_name("nostill10s_imu", context, glasses_bsp_node)
record_duration_s = float(context["record_duration_s"])

print(f"[BSP_IMU_DYNAMIC] 当前眼镜标识: {glasses_id}")
print(f"[BSP_IMU_DYNAMIC] 实验关键字: {context['experiment_keyword']}")
print(f"[BSP_IMU_DYNAMIC] 录制人: {context['recorder_name']}")
print(f"[BSP_IMU_DYNAMIC] 录制时长: {record_duration_s:.1f} 秒")
print(f"[BSP_IMU_DYNAMIC] 数据将保存到: data/{dataset_name}/")
set_step(WorkflowStep.CHECK, "success", f"录制信息已确认: {dataset_name}")

clear_record_timer()
clear_motion_status()
start_record_or_fail(
    glasses_bsp_node,
    {
        "dataset_name": dataset_name,
        "enable_camera_snapshot": True,
        "enable_screen_capture": True,
        "enable_mic_recording": True,
    },
    "正在开始动态录制",
)


def on_tick(elapsed: float) -> None:
    status = motion_status()
    status_text = status if status is not None else "unknown"
    print(f"[BSP_IMU_DYNAMIC] 录制中... {elapsed:.1f}/{record_duration_s:.1f}s | 状态: {status_text}", flush=True)
    set_step(
        WorkflowStep.START_RECORD,
        "running",
        f"录制中: {elapsed:.1f}/{record_duration_s:.1f}s | 状态: {status_text}",
    )


run_timed_record_loop(record_duration_s, record_timer_func=record_timer, status_formatter=on_tick)

stop_result = stop_record(glasses_bsp_node)
if not stop_result.get("success"):
    finish(False, stop_result.get("message", "停止录制失败"))
    raise SystemExit(1)

set_step(WorkflowStep.START_RECORD, "success", "动态录制完成")
finish(True, "动态录制完成")
