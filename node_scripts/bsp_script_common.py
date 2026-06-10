import getpass
from typing import Any, Dict, Iterable, Optional, Tuple

from flowagent.core.script_workflow import WorkflowStep, finish, set_step, set_steps
from scripts.common.record_path_helper import build_bsp_dataset_name, sanitize_record_token
from scripts.common.script_agent_helpers import check_required_script_agents, get_script_agent

DEFAULT_DURATION_S = 10.0
_LAST_EXPERIMENT_KEYWORD = sanitize_record_token("exp", "exp")
_LAST_RECORDER_NAME = sanitize_record_token(getpass.getuser(), "user")
_LAST_DURATION_TEXT = "10"


def begin_bsp_workflow(title: str, steps: Iterable[WorkflowStep]) -> None:
    set_steps([WorkflowStep.NODES_CHECK, *steps], title=title)
    set_step(WorkflowStep.NODES_CHECK, "running", "正在检查 BSP 节点")


def finish_bsp_workflow(success: bool, message: str) -> None:
    finish(success, message)


def fail_bsp_workflow(step: WorkflowStep, message: str, exit_code: int = 1) -> None:
    set_step(step, "failed", message)
    finish(False, message)
    raise SystemExit(exit_code)


def require_bsp_agent(
    script_agents: Dict[str, Any],
    unavailable_script_agents: Optional[Dict[str, str]] = None,
    timeout: float = 2.0,
):
    unavailable = unavailable_script_agents or {}
    if unavailable:
        lines = ["当前脚本缺失以下 node:"]
        for agent_name, reason in unavailable.items():
            lines.append(f"- {agent_name}: {reason}")
        fail_bsp_workflow(WorkflowStep.NODES_CHECK, "\n".join(lines))

    ready, message = check_required_script_agents(
        script_agents,
        ["glasses_bsp_node"],
        timeout=timeout,
        unavailable_script_agents=unavailable,
    )
    if not ready:
        fail_bsp_workflow(WorkflowStep.NODES_CHECK, message)

    agent = get_script_agent(script_agents, "glasses_bsp_node")
    if agent is None:
        fail_bsp_workflow(WorkflowStep.NODES_CHECK, "缺少 node: glasses_bsp_node")

    set_step(WorkflowStep.NODES_CHECK, "success", message)
    return agent


def unwrap_cmd_result(result: Any) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return {"success": False, "message": str(result)}
    payload = result.get("result")
    if isinstance(payload, dict):
        merged = dict(payload)
        merged.setdefault("success", bool(result.get("success", False)))
        merged.setdefault("message", result.get("message", ""))
        return merged
    return result


def prompt_bsp_record_context(
    dialog_api: Any,
    *,
    title: str,
    message: str,
    include_duration: bool = False,
    default_duration_s: float = DEFAULT_DURATION_S,
) -> Optional[Dict[str, Any]]:
    global _LAST_DURATION_TEXT, _LAST_EXPERIMENT_KEYWORD, _LAST_RECORDER_NAME

    fields = [
        {
            "name": "experiment_keyword",
            "label": "实验关键字",
            "default": _LAST_EXPERIMENT_KEYWORD,
        },
        {
            "name": "recorder_name",
            "label": "录制人",
            "default": _LAST_RECORDER_NAME,
        },
    ]
    if include_duration:
        fields.append(
            {
                "name": "record_duration_s",
                "label": "录制时长(秒)",
                "default": _LAST_DURATION_TEXT or str(default_duration_s),
            }
        )

    if dialog_api is None:
        result = {
            "experiment_keyword": _LAST_EXPERIMENT_KEYWORD,
            "recorder_name": _LAST_RECORDER_NAME,
        }
        if include_duration:
            result["record_duration_s"] = _LAST_DURATION_TEXT or str(default_duration_s)
    else:
        result = dialog_api.multi_field_input(title, message, fields)
        if not result:
            return None

    experiment_keyword = sanitize_record_token(result.get("experiment_keyword"), _LAST_EXPERIMENT_KEYWORD)
    recorder_name = sanitize_record_token(result.get("recorder_name"), _LAST_RECORDER_NAME)

    context: Dict[str, Any] = {
        "experiment_keyword": experiment_keyword,
        "recorder_name": recorder_name,
    }

    if include_duration:
        duration_text = str(result.get("record_duration_s") or _LAST_DURATION_TEXT or default_duration_s).strip()
        try:
            duration_s = float(duration_text)
        except ValueError as exc:
            raise ValueError(f"录制时长必须是数字，当前输入: {duration_text or '<empty>'}") from exc
        if duration_s <= 0:
            raise ValueError(f"录制时长必须大于 0，当前输入: {duration_text}")
        context["record_duration_s"] = duration_s
        context["record_duration_text"] = duration_text
        _LAST_DURATION_TEXT = duration_text

    _LAST_EXPERIMENT_KEYWORD = experiment_keyword
    _LAST_RECORDER_NAME = recorder_name
    return context


def build_dataset_name(sub_path: str, context: Dict[str, Any], agent: Any, *, leaf_token_override: Optional[str] = None) -> Tuple[str, str]:
    return build_bsp_dataset_name(
        sub_path,
        experiment_keyword=context.get("experiment_keyword"),
        recorder_name=context.get("recorder_name"),
        leaf_token_override=leaf_token_override,
        agent=agent,
        agent_names=("glasses_bsp_node",),
    )


def start_record_or_fail(agent: Any, params: Dict[str, Any], message: str) -> Dict[str, Any]:
    set_step(WorkflowStep.START_RECORD, "running", message)
    result = unwrap_cmd_result(agent.cmd("start_record", params))
    if not result.get("success"):
        fail_bsp_workflow(WorkflowStep.START_RECORD, result.get("message", "start_record failed"))
    return result


def stop_record(agent: Any, message: str = "正在停止录制") -> Dict[str, Any]:
    set_step(WorkflowStep.STOP_RECORD, "running", message)
    result = unwrap_cmd_result(agent.cmd("stop_record", {}))
    if not result.get("success"):
        set_step(WorkflowStep.STOP_RECORD, "failed", result.get("message", "stop_record failed"))
        return result
    set_step(WorkflowStep.STOP_RECORD, "success", "录制已停止")
    return result


def run_timed_record_loop(
    record_duration_s: float,
    *,
    record_timer_func,
    status_formatter,
    sleep_interval_s: float = 1.0,
) -> float:
    elapsed = 0.0
    while elapsed < record_duration_s:
        timer_value = record_timer_func()
        if timer_value is not None and timer_value >= 0:
            elapsed = float(timer_value)
        else:
            elapsed += sleep_interval_s
        status_formatter(min(elapsed, record_duration_s))
        if elapsed >= record_duration_s:
            break
        import time
        time.sleep(sleep_interval_s)
    return elapsed
