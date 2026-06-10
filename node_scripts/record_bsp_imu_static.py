from flowagent.core.script_workflow import WorkflowStep, finish, set_step

from bsp_script_common import (
    begin_bsp_workflow,
    build_dataset_name,
    prompt_bsp_record_context,
    require_bsp_agent,
    run_timed_record_loop,
    start_record_or_fail,
    stop_record,
    unwrap_cmd_result,
)


ALLOWED_STATES = {"static", "none", None}

all_agent_names = ["glasses_bsp_node"]

print("[BSP_IMU_STATIC] record static BSP IMU")

begin_bsp_workflow(
    "BSP IMU 静止定时录制",
    [WorkflowStep.CHECK, WorkflowStep.START_RECORD, WorkflowStep.GET_BSP_RUNTIME_STATE, WorkflowStep.STOP_RECORD, WorkflowStep.DELETE_RECORD],
)
glasses_bsp_node = require_bsp_agent(script_agents, globals().get("unavailable_script_agents"))

set_step(WorkflowStep.CHECK, "running", "正在填写录制信息")
try:
    context = prompt_bsp_record_context(
        dialog,
        title="BSP 静止录制信息",
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

dataset_name, glasses_id = build_dataset_name("still10s_imu", context, glasses_bsp_node)
record_duration_s = float(context["record_duration_s"])

print(f"[BSP_IMU_STATIC] 当前眼镜标识: {glasses_id}")
print(f"[BSP_IMU_STATIC] 实验关键字: {context['experiment_keyword']}")
print(f"[BSP_IMU_STATIC] 录制人: {context['recorder_name']}")
print(f"[BSP_IMU_STATIC] 录制时长: {record_duration_s:.1f} 秒")
print(f"[BSP_IMU_STATIC] 数据将保存到: data/{dataset_name}/")
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
    "正在开始静止录制",
)

recording_success = True
failure_reason = ""


def on_tick(elapsed: float) -> None:
    global recording_success, failure_reason
    set_step(WorkflowStep.GET_BSP_RUNTIME_STATE, "running", "正在检查静止状态")
    state = unwrap_cmd_result(glasses_bsp_node.cmd("get_bsp_runtime_state", {}, timeout=5.0))
    motion = (state.get("motion_status") or {}).get("status")
    print(f"[BSP_IMU_STATIC] 录制中... {elapsed:.1f}/{record_duration_s:.1f}s | 状态: {motion}", flush=True)
    if motion not in ALLOWED_STATES:
        recording_success = False
        failure_reason = f"检测到运动: {motion}"
        set_step(WorkflowStep.GET_BSP_RUNTIME_STATE, "failed", failure_reason)
        raise SystemExit(1)
    set_step(WorkflowStep.GET_BSP_RUNTIME_STATE, "success", f"motion_status={motion}")
    set_step(WorkflowStep.START_RECORD, "running", f"录制中: {elapsed:.1f}/{record_duration_s:.1f}s | 状态: {motion}")


try:
    run_timed_record_loop(record_duration_s, record_timer_func=record_timer, status_formatter=on_tick)
except SystemExit:
    recording_success = False
    if not failure_reason:
        failure_reason = "静止状态检查失败"

stop_result = stop_record(glasses_bsp_node)
if not stop_result.get("success"):
    finish(False, stop_result.get("message", "停止录制失败"))
    raise SystemExit(1)

if not recording_success:
    set_step(WorkflowStep.DELETE_RECORD, "running", "正在删除异常录制数据")
    delete_result = unwrap_cmd_result(glasses_bsp_node.cmd("delete_record", {"dataset_name": dataset_name}, timeout=10.0))
    if delete_result.get("success"):
        set_step(WorkflowStep.DELETE_RECORD, "success", "异常录制数据已删除")
    else:
        set_step(WorkflowStep.DELETE_RECORD, "failed", delete_result.get("message", "删除录制数据失败"))
    finish(False, failure_reason or "静止录制失败")
    raise SystemExit(1)

set_step(WorkflowStep.START_RECORD, "success", "静止录制完成")
set_step(WorkflowStep.DELETE_RECORD, "success", "无需删除")
finish(True, "静止录制完成")
