from flowagent.core.script_workflow import WorkflowStep, finish, set_step

from bsp_script_common import (
    begin_bsp_workflow,
    build_dataset_name,
    prompt_bsp_record_context,
    require_bsp_agent,
    unwrap_cmd_result,
)


DEFAULT_RAW_RESOLUTION = 8
DEFAULT_RAW_EXPOSURE_MODE = 0
DEFAULT_RAW_EXPOSURE_VALUE = 1
DEFAULT_RAW_GAIN = 1
RAW_CAPTURE_TIMEOUT_S = 150.0

all_agent_names = ["glasses_bsp_node"]

print("[BSP_RGB_RAW] single BSP RGB RAW capture")

begin_bsp_workflow(
    "BSP RGB RAW 单帧捕获",
    [WorkflowStep.GET_BSP_RUNTIME_STATE, WorkflowStep.CHECK, WorkflowStep.CAPTURE_RAW_FRAME],
)
glasses_bsp_node = require_bsp_agent(script_agents, globals().get("unavailable_script_agents"))

set_step(WorkflowStep.GET_BSP_RUNTIME_STATE, "running", "正在检查 BSP RGB 运行状态")
runtime_state = unwrap_cmd_result(glasses_bsp_node.cmd("get_bsp_runtime_state", {}, timeout=5.0))
if not runtime_state.get("success"):
    set_step(WorkflowStep.GET_BSP_RUNTIME_STATE, "failed", runtime_state.get("message", "获取 BSP 运行状态失败"))
    finish(False, runtime_state.get("message", "获取 BSP 运行状态失败"))
    raise SystemExit(1)

if not (runtime_state.get("device") or {}).get("started"):
    set_step(WorkflowStep.GET_BSP_RUNTIME_STATE, "failed", "设备未启动，请先启动 BSP 设备")
    finish(False, "设备未启动，请先启动 BSP 设备")
    raise SystemExit(1)

camera_mode = runtime_state.get("camera_mode")
latest_frame = runtime_state.get("latest_frame") or {}
if camera_mode != "rgb":
    set_step(WorkflowStep.GET_BSP_RUNTIME_STATE, "failed", f"当前相机模式不是 RGB: {camera_mode}")
    finish(False, f"当前相机模式不是 RGB: {camera_mode}")
    raise SystemExit(1)
if not latest_frame:
    set_step(WorkflowStep.GET_BSP_RUNTIME_STATE, "failed", "当前没有可用的 RGB 最新帧元数据")
    finish(False, "当前没有可用的 RGB 最新帧元数据")
    raise SystemExit(1)
set_step(WorkflowStep.GET_BSP_RUNTIME_STATE, "success", "BSP RGB 运行状态已确认")

set_step(WorkflowStep.CHECK, "running", "正在填写抓取参数")
try:
    context = prompt_bsp_record_context(
        dialog,
        title="BSP RGB RAW 抓取信息",
        message="请填写实验关键字和录制人",
        include_duration=False,
    )
except ValueError as exc:
    set_step(WorkflowStep.CHECK, "failed", str(exc))
    finish(False, str(exc))
    raise SystemExit(1)

if context is None:
    set_step(WorkflowStep.CHECK, "failed", "已取消录制信息输入")
    finish(False, "已取消录制信息输入")
    raise SystemExit(1)

raw_params = dialog.multi_field_input(
    "RAW 抓取参数",
    "请输入 raw 抓取参数",
    [
        {"name": "resolution", "label": "分辨率参数", "default": str(DEFAULT_RAW_RESOLUTION)},
        {"name": "exposure_mode", "label": "曝光模式", "default": str(DEFAULT_RAW_EXPOSURE_MODE)},
        {"name": "exposure_value", "label": "曝光值", "default": str(DEFAULT_RAW_EXPOSURE_VALUE)},
        {"name": "gain", "label": "增益", "default": str(DEFAULT_RAW_GAIN)},
    ],
)
if not raw_params:
    set_step(WorkflowStep.CHECK, "failed", "已取消 RAW 抓取参数输入")
    finish(False, "已取消 RAW 抓取参数输入")
    raise SystemExit(1)

try:
    raw_resolution = int(str(raw_params.get("resolution", DEFAULT_RAW_RESOLUTION)).strip())
    raw_exposure_mode = int(str(raw_params.get("exposure_mode", DEFAULT_RAW_EXPOSURE_MODE)).strip())
    raw_exposure_value = int(str(raw_params.get("exposure_value", DEFAULT_RAW_EXPOSURE_VALUE)).strip())
    raw_gain = int(str(raw_params.get("gain", DEFAULT_RAW_GAIN)).strip())
except ValueError as exc:
    set_step(WorkflowStep.CHECK, "failed", f"RAW 参数必须是整数: {exc}")
    finish(False, f"RAW 参数必须是整数: {exc}")
    raise SystemExit(1)

dataset_name, glasses_id = build_dataset_name(
    "slam_rgb_imu",
    context,
    glasses_bsp_node,
    leaf_token_override="free_record_rgb_raw",
)
set_step(WorkflowStep.CHECK, "success", f"抓取参数已确认: {dataset_name}")

print(f"[BSP_RGB_RAW] 当前眼镜标识: {glasses_id}")
print(f"[BSP_RGB_RAW] 数据将保存到: data/{dataset_name}/")
print(
    "[BSP_RGB_RAW] RAW 参数: "
    f"resolution={raw_resolution}, exposure_mode={raw_exposure_mode}, "
    f"exposure_value={raw_exposure_value}, gain={raw_gain}"
)

set_step(WorkflowStep.CAPTURE_RAW_FRAME, "running", "正在捕获 RAW 帧")
capture_result = unwrap_cmd_result(
    glasses_bsp_node.cmd(
        "capture_raw_frame",
        {
            "dataset_name": dataset_name,
            "target_subdir": "rgb0/raw_data",
            "raw_resolution": raw_resolution,
            "raw_exposure_mode": raw_exposure_mode,
            "raw_exposure_value": raw_exposure_value,
            "raw_gain": raw_gain,
        },
        timeout=RAW_CAPTURE_TIMEOUT_S,
    )
)

if not capture_result.get("success"):
    set_step(WorkflowStep.CAPTURE_RAW_FRAME, "failed", capture_result.get("message", "RAW 抓取失败"))
    finish(False, capture_result.get("message", "RAW 抓取失败"))
    raise SystemExit(1)

set_step(WorkflowStep.CAPTURE_RAW_FRAME, "success", f"RAW 帧捕获完成: {capture_result.get('raw_file', '--')}")
finish(True, "RAW 帧捕获完成")
