# Simple example: control three agents via ScriptExecutor wrappers
# Available wrappers when Tab4 runs this: imu, delay, shell
# Use print() to stream logs into Tab4's log panel.
# Note: time module is provided by ScriptExecutor, no import needed

# 导入公共函数库
from nviz_ur_base import check_required_script_agents, execute_trajectory_recording, get_script_agent, safe_exit_nviz
from flowagent.core.script_workflow import WorkflowStep, finish, set_step, set_steps

# 定义需要使用的 agent 列表（执行器会读取并初始化这些 agent）
all_agent_names = ['glasses_nviz_node','UR_node','localhost']

print(f"[test_nviz_node] Starting script...")
print(f"[test_nviz_node] Available agents: {all_agent_names}")

cleanup_nviz = False

def update_workflow(event, status, message):
    step_map = {
        "start_device": WorkflowStep.START_DEVICE,
        "move_to_start": WorkflowStep.MOVE_TO_START,
        "execute_trajectory": WorkflowStep.EXECUTE_TRAJECTORY,
        "start_record": WorkflowStep.START_RECORD,
        "play_video": WorkflowStep.PLAY_VIDEO,
        "stop_record": WorkflowStep.STOP_RECORD,
        "stop_device": WorkflowStep.STOP_DEVICE,
        "copy_ur_files": WorkflowStep.COPY_UR_FILES,
    }
    step = step_map.get(event)
    if step:
        set_step(step, status, message)


workflow_steps = [
    WorkflowStep.NODES_CHECK,
    WorkflowStep.START_DEVICE,
    WorkflowStep.MOVE_TO_START,
    WorkflowStep.EXECUTE_TRAJECTORY,
    WorkflowStep.START_RECORD,
    WorkflowStep.PLAY_VIDEO,
    WorkflowStep.STOP_RECORD,
    WorkflowStep.STOP_DEVICE,
    WorkflowStep.COPY_UR_FILES,
]

# 主执行逻辑
try:
    set_steps(workflow_steps, title="3DoF 单条轨迹录制")
    set_step(WorkflowStep.NODES_CHECK, "running", "正在检查节点连接")
    nodes_ready, nodes_message = check_required_script_agents(script_agents, all_agent_names)
    if not nodes_ready:
        set_step(WorkflowStep.NODES_CHECK, "failed", nodes_message)
        finish(False, nodes_message)
        raise SystemExit(1)
    set_step(WorkflowStep.NODES_CHECK, "success", nodes_message)

    # 输入：1. 轨迹id，2. 眼镜sn，3.记录人名称,4.第几次录制,5.是否播放视频,6.视频路径
    # 先获取用户输入参数
    fields = [
        {"name": "traj_id", "label": "轨迹ID", "default": "10"},
        {"name": "glasses_sn", "label": "眼镜标识（空=自动识别）", "default": ""},
        {"name": "recorder_name", "label": "记录人名称", "default": "xlz"},
        {"name": "taker_number", "label": "第几次录制", "default": "1"},
        {"name": "play_video", "label": "是否播放视频 (1=是, 0=否)", "default": "1"},
        {"name": "video_path", "label": "视频路径（空=默认 old_video.mp4）", "default": ""}
    ]
    
    dialog_result = dialog.multi_field_input("录制参数设置", "请输入录制参数", fields)
    
    if not dialog_result:
        print("[test_nviz_node] 用户取消输入")
        # 直接退出，让finally清理
    else:
        # 获取用户输入的参数
        traj_id = int(dialog_result["traj_id"])
        glasses_sn = dialog_result["glasses_sn"]
        recorder_name = dialog_result["recorder_name"]
        taker_number = int(dialog_result["taker_number"])
        enable_video = int(dialog_result["play_video"]) == 1
        video_path = dialog_result.get("video_path", "").strip()
        
        print(f"[test_nviz_node] Video playback: {'Enabled' if enable_video else 'Disabled'}")

        glasses_agent = get_script_agent(script_agents, "glasses_nviz_node")
        ur_agent = get_script_agent(script_agents, "UR_node")
        localhost_agent = get_script_agent(script_agents, "localhost")
        cleanup_nviz = True

        # 执行轨迹录制流程
        run_success = execute_trajectory_recording(
            ur_agent,
            glasses_agent,
            traj_id,
            taker_number,
            glasses_sn,
            recorder_name,
            time_delay,
            record_time,
            localhost_node=localhost_agent,
            enable_video=enable_video,
            progress_callback=update_workflow,
            video_path=video_path or None
        )
        finish(run_success, "3DoF 单条轨迹录制完成" if run_success else "3DoF 单条轨迹录制失败")

except Exception:
    print(f"[test_nviz_node] 脚本执行出错")
    try:
        finish(False, "脚本执行出错")
    except Exception:
        pass
    if cleanup_nviz:
        try:
            safe_exit_nviz(get_script_agent(script_agents, "glasses_nviz_node"), "脚本异常退出")
        except Exception:
            pass
finally:
    if cleanup_nviz:
        try:
            safe_exit_nviz(get_script_agent(script_agents, "glasses_nviz_node"), "脚本结束清理")
        except Exception:
            pass
