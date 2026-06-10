# Simple Nebula static recording test.
# It records Nebula CSV files through the nebula_trial agent/subnode.

import json
import time
from time import monotonic, sleep

from flowagent.core.script_workflow import WorkflowStep, finish, set_step, set_steps
from scripts.common.script_agent_helpers import get_script_agent


# Nebula 的 check 依赖弹窗里填写/确认的 ADB 参数。
# 这里不让 runtime 在弹窗前预探测，否则失败后 nebula_trial 不会注入 script_agents。
all_agent_names = []

print("[nebula_simple_test] Starting simple Nebula recording test...")


def _safe_int(value, default):
    try:
        return int(str(value).strip())
    except Exception:
        return default


def _safe_float(value, default):
    try:
        return float(str(value).strip())
    except Exception:
        return default


def _safe_path_part(value, default):
    text = str(value).strip()
    if not text:
        text = default
    safe_chars = []
    for ch in text:
        if ch.isalnum() or ch in ("-", "_"):
            safe_chars.append(ch)
        else:
            safe_chars.append("_")
    cleaned = "".join(safe_chars).strip("_")
    return cleaned or default


def _parse_bool(value, default=False):
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y", "on", "是", "删除", "需要"):
        return True
    if text in ("0", "false", "no", "n", "off", "否", "不删除", "不需要"):
        return False
    return default


def _extract_root_path(result):
    if not isinstance(result, dict):
        return ""
    if result.get("root_path"):
        return result.get("root_path")
    message = result.get("message")
    if isinstance(message, dict):
        return message.get("root_path", "")
    if isinstance(message, str):
        try:
            decoded = json.loads(message)
            if isinstance(decoded, dict):
                return decoded.get("root_path", "")
        except Exception:
            pass
    return ""


def _wait_until_csv_growing(nebula_agent, remote_dir, timeout_seconds):
    deadline = monotonic() + max(1, timeout_seconds)
    next_log_time = 0.0
    last_check = {}
    while True:
        remaining = deadline - monotonic()
        if remaining <= 0:
            return False, last_check

        last_check = nebula_agent.cmd("check", {"remote_dir": remote_dir})
        if last_check.get("success") and last_check.get("csv_growing"):
            return True, last_check

        if monotonic() >= next_log_time:
            rows = last_check.get("csv_rows") if isinstance(last_check, dict) else None
            print(
                f"[nebula_simple_test] Waiting for CSV growth... "
                f"{int(remaining + 0.999)}s left, rows={rows}"
            )
            next_log_time = monotonic() + 1.0
        sleep(0.5)


def _summary_log_text(state_result):
    if not isinstance(state_result, dict):
        return ""
    latest_lines = state_result.get("latest_csv_lines")
    latest_count = len(latest_lines) if isinstance(latest_lines, dict) else 0
    latest_update_time = state_result.get("latest_update_time") or "--"
    return f", latest_files={latest_count}, latest_update_time={latest_update_time}"


def _stop_record_if_needed(nebula_agent, recording_started):
    if not nebula_agent or not recording_started:
        return
    try:
        nebula_agent.cmd("stop_record", {"require_mobile_csv": False, "require_air_csv": False})
    except Exception:
        pass


def _stop_device_if_needed(nebula_agent, device_started):
    if not nebula_agent or not device_started:
        return
    try:
        nebula_agent.cmd("stop_device", {})
    except Exception:
        pass


def _confirm_nebula_first_run_ready():
    message = (
        "<div style='font-size:18pt; line-height:130%;'>"
        "<p><b>如果右上角显示不是 HEALTHY，请先按下面步骤做完。</b></p>"
        "<ol>"
        "<li>手机和电脑连接到<b>同一个 WiFi</b>。</li>"
        "<li>用 <b>USB 线</b> 连接手机和电脑。</li>"
        "<li>手机保持<b>解锁亮屏</b>。</li>"
        "<li>如果手机弹出“是否允许 USB 调试”，请选择<b>允许</b>，并允许无线调试。</li>"
        "</ol>"
        "<p><b>以上 4 步做完后，等待右上角转为 HEALTHY 再继续。</b></p>"
        "<p><b>当右上角显示为 HEALTHY 时，拔掉手机和电脑的连线，"
        "再将手机和眼镜用线连接。</b></p>"
        "</div>"
    )
    fields = [
        {
            "name": "ready",
            "label": "确认状态",
            "default": "还没做完，先退出",
            "choices": ["我已经按上面步骤做完", "还没做完，先退出"],
            "font_size_pt": 32,
            "min_width": 360,
        }
    ]
    result = dialog.multi_field_input(
        "Nebula 测量前确认",
        message,
        fields,
    )
    if not result:
        return False
    return str(result.get("ready", "")).startswith("我已经")


nebula_agent = None
recording_started = False
device_started = False

try:
    if not _confirm_nebula_first_run_ready():
        message = "用户取消：Nebula 测量前确认未完成"
        print(f"[nebula_simple_test] {message}")
        finish(False, message)
        raise SystemExit(0)

    fields = [
        {"name": "duration_seconds", "label": "录制时长(秒)", "default": "10"},
        {"name": "experiment_keyword", "label": "实验关键字", "default": "test"},
        {"name": "operator_name", "label": "实验人员", "default": "xjh"},
        {"name": "phone_ip", "label": "手机IP(可空, 自动读取wlan0)", "default": ""},
        {
            "name": "require_air_csv",
            "label": "要求air CSV",
            "default": "否",
            "choices": ["否", "是"],
        },
        {
            "name": "delete_remote",
            "label": "Pull成功后删除手机CSV",
            "default": "是",
            "choices": ["是", "否"],
        },
    ]

    dialog_result = dialog.multi_field_input(
        "Nebula简单录制测试",
        "请输入本次测量信息",
        fields,
    )

    if not dialog_result:
        print("[nebula_simple_test] 用户取消输入")
    else:
        duration_seconds = _safe_int(dialog_result["duration_seconds"], 10)
        if duration_seconds <= 0:
            duration_seconds = 10

        adb_port = 5555
        experiment_keyword = _safe_path_part(dialog_result["experiment_keyword"], "test")
        operator_name = _safe_path_part(dialog_result["operator_name"], "unknown")
        script_name = "record_nebula_simple_test"
        experiment_time = time.strftime("%Y%m%d_%H%M%S")
        trial_id = (
            "nebula_"
            + experiment_keyword
            + "_"
            + operator_name
            + "_"
            + script_name
            + "_"
            + experiment_time
        )

        serial = ""
        phone_ip = str(dialog_result.get("phone_ip", "")).strip()
        remote_dir = "/sdcard/3dof_data"
        start_timeout_seconds = 20
        enable_wifi_adb = True
        require_air_csv = _parse_bool(dialog_result.get("require_air_csv"), False)
        delete_remote = _parse_bool(dialog_result.get("delete_remote"), True)

        steps = [
            WorkflowStep.NODES_CHECK,
            WorkflowStep.START_DEVICE,
            WorkflowStep.START_RECORD,
            WorkflowStep.STOP_RECORD,
            WorkflowStep.STOP_DEVICE,
            WorkflowStep.GET_ROOT_PATH,
        ]
        set_steps(steps, title="Nebula简单录制测试")

        set_step(WorkflowStep.NODES_CHECK, "running", "正在检查 nebula_trial 节点")
        nebula_agent = get_script_agent(script_agents, "nebula_trial")
        if nebula_agent is None:
            error_message = "当前脚本缺失 nebula_trial agent"
            set_step(WorkflowStep.NODES_CHECK, "failed", error_message)
            finish(False, error_message)
        else:
            check_result = nebula_agent.cmd(
                "check",
                {
                    "serial": serial,
                    "phone_ip": phone_ip,
                    "adb_port": adb_port,
                    "remote_dir": remote_dir,
                },
            )
            if not check_result.get("success"):
                error_message = f"check 失败: {check_result}"
                set_step(WorkflowStep.NODES_CHECK, "failed", error_message)
                finish(False, error_message)
            else:
                set_step(WorkflowStep.NODES_CHECK, "success", "nebula_trial 节点已连接")

                print(f"[nebula_simple_test] Trial: {trial_id}")
                print(f"[nebula_simple_test] Duration: {duration_seconds}s")
                print(f"[nebula_simple_test] Remote dir: {remote_dir}")
                print(f"[nebula_simple_test] Start timeout: {start_timeout_seconds}s")
                print(f"[nebula_simple_test] WiFi ADB: {enable_wifi_adb}, adb_port={adb_port}")
                print(f"[nebula_simple_test] Require air CSV: {require_air_csv}")

                set_step(WorkflowStep.START_DEVICE, "running", "正在初始化并准备 Nebula")
                init_result = nebula_agent.cmd(
                    "init_device",
                    {
                        "serial": serial,
                        "phone_ip": phone_ip,
                        "adb_port": adb_port,
                        "remote_dir": remote_dir,
                        "enable_wifi_adb": enable_wifi_adb,
                    },
                )
                if not init_result.get("success"):
                    error_message = f"init_device 失败: {init_result}"
                    set_step(WorkflowStep.START_DEVICE, "failed", error_message)
                    finish(False, error_message)
                else:
                    start_device_result = nebula_agent.cmd(
                        "start_device",
                        {
                            "serial": init_result.get("serial") or serial,
                            "remote_dir": remote_dir,
                        },
                    )
                    if not start_device_result.get("success"):
                        error_message = f"start_device 失败: {start_device_result}"
                        set_step(WorkflowStep.START_DEVICE, "failed", error_message)
                        finish(False, error_message)
                    else:
                        device_started = True
                        set_step(WorkflowStep.START_DEVICE, "success", "Nebula 已停止并清空旧CSV")

                        set_step(WorkflowStep.START_RECORD, "running", "正在广播启动 Nebula 并开始计时")
                        start_record_result = nebula_agent.cmd(
                            "start_record",
                            {
                                "trial_id": trial_id,
                                "delete_remote": delete_remote,
                            },
                        )
                        if not start_record_result.get("success"):
                            error_message = f"start_record 失败: {start_record_result}"
                            set_step(WorkflowStep.START_RECORD, "failed", error_message)
                            finish(False, error_message)
                        else:
                            recording_started = True
                            set_step(
                                WorkflowStep.START_RECORD,
                                "running",
                                f"已广播启动，等待CSV开始增长，超时 {start_timeout_seconds}s",
                            )

                            csv_started, csv_check = _wait_until_csv_growing(
                                nebula_agent,
                                remote_dir,
                                start_timeout_seconds,
                            )
                            if not csv_started:
                                error_message = f"等待CSV增长超时: {csv_check}"
                                set_step(WorkflowStep.START_RECORD, "failed", error_message)
                                finish(False, error_message)
                                raise RuntimeError(error_message)

                            set_step(
                                WorkflowStep.START_RECORD,
                                "success",
                                f"CSV已开始增长，有效录制中: {duration_seconds}s",
                            )

                            deadline = monotonic() + duration_seconds
                            next_log_time = 0.0
                            while True:
                                remaining_float = deadline - monotonic()
                                if remaining_float <= 0:
                                    break
                                remaining = int(remaining_float + 0.999)
                                if monotonic() >= next_log_time:
                                    state_result = nebula_agent.cmd("get_runtime_state", {})
                                    elapsed = _safe_float(state_result.get("elapsed_seconds"), 0.0)
                                    print(
                                        f"[nebula_simple_test] Recording... {remaining}s remaining, "
                                        f"elapsed={elapsed:.1f}s{_summary_log_text(state_result)}"
                                    )
                                    next_log_time = monotonic() + 1.0
                                sleep(min(0.1, remaining_float))

                            set_step(WorkflowStep.STOP_RECORD, "running", "正在停止 Nebula 并拉取CSV")
                            stop_record_result = nebula_agent.cmd(
                                "stop_record",
                                {
                                    "remote_dir": remote_dir,
                                    "delete_remote": delete_remote,
                                    "require_mobile_csv": True,
                                    "require_air_csv": require_air_csv,
                                },
                            )
                            recording_started = False
                            if not stop_record_result.get("success"):
                                error_message = f"stop_record 失败: {stop_record_result}"
                                set_step(WorkflowStep.STOP_RECORD, "failed", error_message)
                                finish(False, error_message)
                            else:
                                trial_dir = stop_record_result.get("trial_dir", "")
                                pulled_files = stop_record_result.get("pulled_files", [])
                                set_step(WorkflowStep.STOP_RECORD, "success", f"CSV 已保存: {trial_dir}")

                                set_step(WorkflowStep.STOP_DEVICE, "running", "正在停止 Nebula")
                                stop_device_result = nebula_agent.cmd("stop_device", {})
                                device_started = False
                                if not stop_device_result.get("success"):
                                    error_message = f"stop_device 失败: {stop_device_result}"
                                    set_step(WorkflowStep.STOP_DEVICE, "failed", error_message)
                                    finish(False, error_message)
                                else:
                                    set_step(WorkflowStep.STOP_DEVICE, "success", "Nebula 已停止")

                                    set_step(WorkflowStep.GET_ROOT_PATH, "running", "正在获取保存路径")
                                    root_path_result = nebula_agent.cmd("get_root_path", {})
                                    root_path = _extract_root_path(root_path_result)
                                    if trial_dir:
                                        print(f"[nebula_simple_test] Saved dir: {trial_dir}")
                                        for path in pulled_files:
                                            print(f"[nebula_simple_test] Pulled: {path}")
                                        set_step(WorkflowStep.GET_ROOT_PATH, "success", trial_dir)
                                        finish(True, f"录制完成: {trial_dir}")
                                    elif root_path:
                                        set_step(WorkflowStep.GET_ROOT_PATH, "success", root_path)
                                        finish(True, f"录制完成: {root_path}")
                                    else:
                                        set_step(WorkflowStep.GET_ROOT_PATH, "success", "录制完成，未获取到root_path")
                                        finish(True, "录制完成")

except Exception as e:
    print(f"[nebula_simple_test] 脚本执行出错: {e}")
    _stop_record_if_needed(nebula_agent, recording_started)
    recording_started = False
    _stop_device_if_needed(nebula_agent, device_started)
    device_started = False
    finish(False, f"脚本执行出错: {e}")
finally:
    _stop_record_if_needed(nebula_agent, recording_started)
    _stop_device_if_needed(nebula_agent, device_started)
