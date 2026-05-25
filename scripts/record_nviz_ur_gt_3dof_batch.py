#!/usr/bin/env python3
"""NVIZ + UR 3DoF 批量录制脚本。

这是 RecordLabC `record_ur_gt_3dof_batch.py` 的 ROS 边界迁移版：
- Master 只用于发现 node/service/action。
- 脚本负责多节点编排。
- NVIZ/UR/localhost 设备细节分别留在各自 node 内。
- 录制落盘统一交给 /recorder_node。
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path

import zmq


EVENT_PREFIX = "RECORDLAB_EVENT_JSON "


def emit(payload: dict) -> None:
    print(EVENT_PREFIX + json.dumps(payload, ensure_ascii=False), flush=True)


def workflow(steps: list[dict], message: str, finished: bool = False, success=None) -> None:
    emit({
        "type": "workflow",
        "action": "state",
        "title": "NVIZ + UR 3DoF 批量录制",
        "steps": steps,
        "message": message,
        "finished": finished,
        "success": success,
    })


class MasterClient:
    def __init__(self, endpoint: str):
        self.endpoint = endpoint
        self.context = zmq.Context.instance()

    def call(self, op: str, data: dict | None = None, timeout_ms: int = 3000):
        socket = self.context.socket(zmq.REQ)
        socket.setsockopt(zmq.LINGER, 0)
        socket.setsockopt(zmq.RCVTIMEO, timeout_ms)
        socket.setsockopt(zmq.SNDTIMEO, timeout_ms)
        socket.connect(self.endpoint)
        try:
            socket.send_json({"op": op, "data": data or {}})
            response = socket.recv_json()
            if not response.get("ok"):
                raise RuntimeError(response.get("error") or f"Master call failed: {op}")
            return response.get("data")
        finally:
            socket.close(0)


def service_call(endpoint: str, payload: dict, timeout_ms: int = 5000) -> dict:
    ctx = zmq.Context.instance()
    socket = ctx.socket(zmq.REQ)
    socket.setsockopt(zmq.LINGER, 0)
    socket.setsockopt(zmq.RCVTIMEO, timeout_ms)
    socket.setsockopt(zmq.SNDTIMEO, timeout_ms)
    socket.connect(endpoint)
    try:
        socket.send_json(payload)
        response = socket.recv_json()
        if not response.get("ok"):
            raise RuntimeError(response.get("error") or "service call failed")
        return response.get("data") or {}
    finally:
        socket.close(0)


def action_send(descriptor: dict, goal: dict, timeout_ms: int = 5000) -> int:
    data = service_call(descriptor["send_goal"], {"goal": goal}, timeout_ms=timeout_ms)
    return int(data["goal_id"])


def action_wait(descriptor: dict, goal_id: int, timeout_s: float) -> dict:
    ctx = zmq.Context.instance()
    sub = ctx.socket(zmq.SUB)
    sub.setsockopt(zmq.LINGER, 0)
    sub.setsockopt_string(zmq.SUBSCRIBE, descriptor.get("result_topic", "result"))
    sub.connect(descriptor["result"])
    deadline = time.time() + timeout_s
    try:
        while time.time() < deadline:
            try:
                text = sub.recv_string(flags=zmq.NOBLOCK)
            except zmq.Again:
                time.sleep(0.05)
                continue
            _, raw = text.split(" ", 1)
            result = json.loads(raw)
            if int(result.get("goal_id", 0)) == goal_id:
                if not result.get("ok", False):
                    raise RuntimeError(result.get("data", {}).get("error", "action failed"))
                return result.get("data") or {}
    finally:
        sub.close(0)
    raise TimeoutError("action result timeout")


def action_call(master: MasterClient, name: str, goal: dict, timeout_s: float = 30.0) -> dict:
    item = master.call("lookup_action", {"action": name})
    if not item:
        raise RuntimeError(f"缺少 action: {name}")
    descriptor = item["endpoints"]
    ctx = zmq.Context.instance()
    sub = ctx.socket(zmq.SUB)
    sub.setsockopt(zmq.LINGER, 0)
    sub.setsockopt_string(zmq.SUBSCRIBE, descriptor.get("result_topic", "result"))
    sub.connect(descriptor["result"])
    time.sleep(0.05)
    try:
        goal_id = action_send(descriptor, goal)
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                text = sub.recv_string(flags=zmq.NOBLOCK)
            except zmq.Again:
                time.sleep(0.05)
                continue
            _, raw = text.split(" ", 1)
            envelope = json.loads(raw)
            if int(envelope.get("goal_id", 0)) != goal_id:
                continue
            if not envelope.get("ok", False):
                raise RuntimeError(envelope.get("data", {}).get("error", "action failed"))
            result = envelope.get("data") or {}
            if not result.get("success", False):
                raise RuntimeError(result.get("message", f"{name} failed"))
            return result
    finally:
        sub.close(0)
    raise TimeoutError("action result timeout")


def ensure_node(master: MasterClient, node_name: str) -> None:
    nodes = master.call("list_nodes")
    if any(item.get("node") == node_name and item.get("state") == "alive" for item in nodes):
        return
    launcher = master.call("lookup_service", {"service": "/launcher/start_node"})
    if not launcher:
        raise RuntimeError(f"缺少 {node_name}，且 /launcher/start_node 未注册")
    service_call(launcher["endpoint"], {"node": node_name}, timeout_ms=5000)


def parse_trajectory_list(value: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        left, sep, right = item.partition("-")
        if not sep:
            raise ValueError(f"轨迹格式错误: {item}")
        out.append((int(left.strip()), int(right.strip())))
    return out


def program_config(traj_id: int) -> tuple[str, str]:
    mapping = {
        10: ("3dof_test_3motion_28", "8-3-0"),
        11: ("3dof_front_small_motion_28", "8-3-1"),
        13: ("3dof_left_right_28", "8-3-3"),
        14: ("3dof_up_down_28", "8-3-4"),
        0: ("3dof_test_3motion", "8-3-0"),
        1: ("3dof_front_small_motion", "8-3-1"),
        3: ("3dof_left_right", "8-3-3"),
        4: ("3dof_up_down", "8-3-4"),
        21: ("mag_test1", "9-3-0"),
    }
    return mapping.get(traj_id, ("3dof_test_3motion_28", "8-3-0"))


def token(value: str, default: str) -> str:
    raw = str(value or default)
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in raw).strip("_")
    return safe or default


def dataset_name(program_id: str, taker: int, glasses_label: str, fsn: str, recorder: str) -> tuple[str, str, str]:
    now = datetime.now()
    date = now.strftime("%Y%m%d")
    stamp = now.strftime("%Y%m%d%H%M%S")
    leaf = f"{program_id}-{taker}-{token(glasses_label, 'UNKNOWN_GLASSES')}-{token(fsn, 'UNKNOWN_FSN')}-{token(recorder, 'user')}-{stamp}"
    return date, leaf, f"{date}/{leaf}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--master", default=os.environ.get("RECORDLAB_MASTER_ENDPOINT", "tcp://127.0.0.1:5590"))
    parser.add_argument("--traj-list", default="10-1,11-1,13-1")
    parser.add_argument("--glasses-label", default="")
    parser.add_argument("--recorder-name", default=os.environ.get("USER", "recordlab"))
    parser.add_argument("--play-video", default="1")
    parser.add_argument("--video-path", default="")
    parser.add_argument("--tail-wait-s", type=float, default=2.0)
    args = parser.parse_args()

    steps = [
        {"key": "nodes_check", "label": "节点准备", "status": "pending", "message": ""},
        {"key": "start_device", "label": "启动 NVIZ", "status": "pending", "message": ""},
        {"key": "move_to_start", "label": "移动到起始位", "status": "pending", "message": ""},
        {"key": "execute_trajectory", "label": "执行轨迹", "status": "pending", "message": ""},
        {"key": "start_record", "label": "开始录制", "status": "pending", "message": ""},
        {"key": "play_video", "label": "播放视频", "status": "pending", "message": ""},
        {"key": "stop_record", "label": "停止录制", "status": "pending", "message": ""},
        {"key": "stop_device", "label": "停止 NVIZ", "status": "pending", "message": ""},
        {"key": "copy_ur_files", "label": "复制 UR 文件", "status": "pending", "message": ""},
    ]

    def set_step(key: str, status: str, message: str) -> None:
        for step in steps:
            if step["key"] == key:
                step["status"] = status
                step["message"] = message
        workflow(steps, message)

    master = MasterClient(args.master)
    enable_video = str(args.play_video).strip().lower() in {"1", "true", "yes", "on"}
    pairs = parse_trajectory_list(args.traj_list)
    success_count = 0
    failed_count = 0

    try:
        set_step("nodes_check", "running", "正在准备 /nviz_node /ur_node /recorder_node /localhost_node")
        ensure_node(master, "/nviz_node")
        ensure_node(master, "/ur_node")
        ensure_node(master, "/recorder_node")
        if enable_video:
            ensure_node(master, "/localhost_node")
        set_step("nodes_check", "success", "所需节点已就绪")

        for index, (traj_id, taker) in enumerate(pairs, 1):
            program_name, program_id = program_config(traj_id)
            record_started = False
            record_path = ""
            try:
                emit({"type": "log", "stream": "stdout", "message": f"开始第 {index}/{len(pairs)} 条轨迹: {traj_id}-{taker}"})

                set_step("start_device", "running", "正在 connect/init/start /nviz_node")
                action_call(master, "/nviz/connect", {}, 30)
                init_result = action_call(master, "/nviz/init", {}, 60)
                start_result = action_call(master, "/nviz/start", {"data_type": "3dof"}, 60)
                info = start_result.get("device_info") or init_result.get("device_info") or {}
                glasses_label = args.glasses_label or info.get("label") or "NVIZ"
                fsn = info.get("fsn") or "UNKNOWN_FSN"
                set_step("start_device", "success", f"NVIZ 已启动 FSN={fsn}")

                set_step("move_to_start", "running", f"UR 移动到起始位: {program_name}")
                move_result = action_call(master, "/ur/move_to_start", {"program_name": program_name}, 300)
                set_step("move_to_start", "success", move_result.get("message", "UR 已到起始位"))

                date, leaf, dataset = dataset_name(program_id, taker, glasses_label, fsn, args.recorder_name)
                set_step("execute_trajectory", "running", f"执行轨迹: {program_name}")
                execute_item = master.call("lookup_action", {"action": "/ur/execute_trajectory"})
                if not execute_item:
                    raise RuntimeError("缺少 action: /ur/execute_trajectory")
                execute_desc = execute_item["endpoints"]
                execute_goal = action_send(execute_desc, {
                    "program_name": program_name,
                    "record_data": 1,
                    "save_subpath": leaf,
                })

                set_step("start_record", "running", f"开始 RecorderNode 录制: {dataset}")
                record_result = action_call(master, "/record/start", {
                    "dataset_name": dataset,
                    "record_profile": "nviz_ur_gt_3dof_batch",
                    "topics": [
                        "/nviz/imu",
                        "/nviz/time_delay",
                        "/nviz/motion_status",
                        "/nviz/record_timer",
                        "/nviz/tree_data",
                    ],
                    "metadata": {
                        "program_name": program_name,
                        "program_id": program_id,
                        "trajectory_id": traj_id,
                        "taker": taker,
                        "glasses_label": glasses_label,
                        "fsn": fsn,
                        "recorder_name": args.recorder_name,
                    },
                }, 60)
                record_path = record_result.get("record_path", "")
                record_started = True

                if enable_video:
                    set_step("play_video", "running", "请求 localhost 播放视频")
                    svc = master.call("lookup_service", {"service": "/localhost/run_command"})
                    if not svc:
                        raise RuntimeError("缺少 service: /localhost/run_command")
                    service_call(svc["endpoint"], {
                        "command": "play_video_on_secondary_screen.py",
                        "args": [args.video_path] if args.video_path else [],
                    }, timeout_ms=10000)
                    set_step("play_video", "running", "视频播放中")
                else:
                    set_step("play_video", "success", "未启用视频播放")

                action_wait(execute_desc, execute_goal, 600)
                set_step("execute_trajectory", "success", "UR 轨迹执行完成")
                time.sleep(max(0.0, args.tail_wait_s))

                set_step("stop_record", "running", "停止 RecorderNode 录制")
                stop_result = action_call(master, "/record/stop", {}, 60)
                record_path = stop_result.get("record_path", record_path)
                record_started = False
                set_step("stop_record", "success", "RecorderNode 录制已停止")

                if enable_video:
                    svc = master.call("lookup_service", {"service": "/localhost/run_command"})
                    if svc:
                        service_call(svc["endpoint"], {"command": "stop_video.sh", "args": []}, timeout_ms=10000)
                    set_step("play_video", "success", "视频已停止")

                set_step("stop_device", "running", "停止 NVIZ")
                action_call(master, "/nviz/stop", {}, 60)
                set_step("stop_device", "success", "NVIZ 已停止")

                set_step("copy_ur_files", "running", "请求复制 UR 文件")
                copy_svc = master.call("lookup_service", {"service": "/localhost/copy_folder"})
                if copy_svc:
                    ur_root_svc = master.call("lookup_service", {"service": "/ur/get_root_path"})
                    ur_root = service_call(ur_root_svc["endpoint"], {})["root_path"] if ur_root_svc else ""
                    service_call(copy_svc["endpoint"], {
                        "remote_path": f"{ur_root}/{date}/{leaf}/*",
                        "local_path": record_path,
                    }, timeout_ms=120000)
                    set_step("copy_ur_files", "success", "UR 文件复制完成")
                else:
                    set_step("copy_ur_files", "success", "未发现 /localhost/copy_folder，跳过复制")

                success_count += 1
                workflow(steps, f"第 {index} 条轨迹完成", finished=False, success=True)
            except Exception as exc:
                failed_count += 1
                emit({"type": "log", "stream": "stderr", "message": str(exc)})
                if record_started:
                    try:
                        action_call(master, "/record/stop", {}, 30)
                    except Exception:
                        pass
                try:
                    action_call(master, "/nviz/stop", {}, 30)
                except Exception:
                    pass
                workflow(steps, f"第 {index} 条轨迹失败: {exc}", finished=False, success=False)

        ok = failed_count == 0
        workflow(steps, f"批量录制完成: 成功 {success_count}, 失败 {failed_count}", finished=True, success=ok)
        return 0 if ok else 1
    except Exception as exc:
        workflow(steps, str(exc), finished=True, success=False)
        emit({"type": "log", "stream": "stderr", "message": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
