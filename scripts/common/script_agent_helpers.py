"""Common helpers for script-side agent lookup and readiness checks."""

from __future__ import annotations


def notify_progress(progress_callback, event, status, message):
    """Forward progress updates to the caller when available."""
    if not progress_callback:
        return
    try:
        progress_callback(event, status, message)
    except Exception as exc:
        print(f"[script_agent_helpers] Warning: progress_callback failed: {exc}")


def get_script_agent(script_agents, agent_name):
    if not script_agents:
        return None
    return script_agents.get(agent_name) or script_agents.get(str(agent_name).lower())


def check_required_script_agents(script_agents, agent_names, timeout=2.0, unavailable_script_agents=None):
    """Check required agents via the Host bridge using their `check` command."""

    def concise_reason(result):
        message = str(result.get("message") or result)
        if "Host bridge command timeout" in message:
            return "连接超时/无响应"
        if "当前没有可用 Agent client" in message:
            return "节点未连接"
        return message

    unavailable = unavailable_script_agents or {}
    errors = []
    checked_agents = {}
    for agent_name in agent_names:
        agent = get_script_agent(script_agents, agent_name)
        if agent is None:
            reason = unavailable.get(agent_name)
            errors.append(f"- {agent_name}: {reason or '未在 agents_config.json 中定义或未注入'}")
            continue
        canonical_name = getattr(agent, "name", agent_name)
        if canonical_name in checked_agents:
            continue
        checked_agents[canonical_name] = agent
        try:
            result = agent.cmd("check", {}, timeout=timeout)
        except Exception as exc:
            errors.append(f"- {agent_name}: check 异常: {exc}")
            continue
        if not result.get("success"):
            errors.append(f"- {agent_name}: {concise_reason(result)}")

    if errors:
        return False, "当前脚本缺失以下 node:\n" + "\n".join(errors)
    return True, "所有节点已连接"
