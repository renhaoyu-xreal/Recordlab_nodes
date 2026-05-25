#!/usr/bin/env python3
"""新架构 BSP IMU + Camera 录制脚本。

脚本只做编排：启动/发现 node、调用 BSP 生命周期 action、发布 workflow。
目录结构和文件保存由 /recorder_node 的 /record/start、/record/stop 实现。
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
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
        "title": "BSP IMU + Camera 自由录制",
        "steps": steps,
        "message": message,
        "finished": finished,
        "success": success,
    })


class MasterClient:
    def __init__(self, endpoint: str):
        self.endpoint = endpoint
        self.context = zmq.Context.instance()

    def call(self, op: str, data: dict | None = None, timeout_ms: int = 2000) -> dict:
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


def service_call(endpoint: str, payload: dict, timeout_ms: int = 3000) -> dict:
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


def action_call(descriptor: dict, goal: dict, timeout_s: float = 30.0) -> dict:
    ctx = zmq.Context.instance()
    sub = ctx.socket(zmq.SUB)
    sub.setsockopt(zmq.LINGER, 0)
    sub.setsockopt_string(zmq.SUBSCRIBE, descriptor.get("result_topic", "result"))
    sub.connect(descriptor["result"])
    time.sleep(0.05)
    data = service_call(descriptor["send_goal"], {"goal": goal})
    goal_id = int(data["goal_id"])
    deadline = time.time() + timeout_s
    try:
        while time.time() < deadline:
            try:
                text = sub.recv_string(flags=zmq.NOBLOCK)
            except zmq.Again:
                time.sleep(0.02)
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


def ensure_node(master: MasterClient, node_name: str) -> None:
    nodes = master.call("list_nodes")
    if any(item.get("node") == node_name and item.get("state") == "alive" for item in nodes):
        return
    launcher = master.call("lookup_service", {"service": "/launcher/start_node"})
    if not launcher:
        raise RuntimeError(f"缺少 {node_name}，且 /launcher/start_node 未注册")
    service_call(launcher["endpoint"], {"node": node_name}, timeout_ms=5000)


def build_dataset_name(device_info: dict, experiment: str, recorder: str) -> str:
    label = str(device_info.get("catalog_name") or device_info.get("product_id") or "UNKNOWN_GLASSES")
    fsn = str(device_info.get("fsn") or "UNKNOWN_FSN")
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    safe = lambda value: "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(value)).strip("_") or "unknown"
    leaf = f"{safe(label)}_{safe(fsn)}_{safe(experiment)}_{safe(recorder)}_free_record_imu_and_cam_{timestamp}"
    return f"free_record/imu_and_cam/{leaf}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--master", default=os.environ.get("RECORDLAB_MASTER_ENDPOINT", "tcp://127.0.0.1:5590"))
    parser.add_argument("--experiment-keyword", default="test")
    parser.add_argument("--recorder-name", default=os.environ.get("USER", "recordlab"))
    parser.add_argument("--duration", type=float, default=3.0, help="录制秒数；小于等于 0 时一直录到停止脚本")
    args = parser.parse_args()

    steps = [
        {"key": "nodes_check", "label": "节点准备", "status": "pending", "message": ""},
        {"key": "check", "label": "check", "status": "pending", "message": ""},
        {"key": "connect", "label": "connect", "status": "pending", "message": ""},
        {"key": "init", "label": "init", "status": "pending", "message": ""},
        {"key": "start", "label": "start", "status": "pending", "message": ""},
        {"key": "start_record", "label": "start_record", "status": "pending", "message": ""},
        {"key": "stop_record", "label": "stop_record", "status": "pending", "message": ""},
    ]

    def set_step(key: str, status: str, message: str) -> None:
        for step in steps:
            if step["key"] == key:
                step["status"] = status
                step["message"] = message
        workflow(steps, message)

    stopping = False

    def handle_stop(signum, frame):  # noqa: ARG001
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)

    master = MasterClient(args.master)
    record_started = False
    stop_descriptor = None

    try:
        set_step("nodes_check", "running", "正在准备 /bsp_node 与 /recorder_node")
        ensure_node(master, "/bsp_node")
        ensure_node(master, "/recorder_node")
        set_step("nodes_check", "success", "/bsp_node 与 /recorder_node 已就绪")

        set_step("check", "running", "正在执行 /bsp/check")
        check_service = master.call("lookup_service", {"service": "/bsp/check"})
        check_result = service_call(check_service["endpoint"], {}, timeout_ms=8000)
        if not check_result.get("success"):
            raise RuntimeError(check_result.get("message", "BSP check failed"))
        device_info = check_result.get("device_info", {})
        set_step("check", "success", f"设备: {device_info.get('catalog_name')} product_id: {device_info.get('product_id')}")

        def call_action(action_name: str, goal: dict, timeout_s: float = 30.0) -> dict:
            descriptor = master.call("lookup_action", {"action": action_name}).get("endpoints")
            if not descriptor:
                raise RuntimeError(f"缺少 action: {action_name}")
            result = action_call(descriptor, goal, timeout_s=timeout_s)
            if not result.get("success"):
                raise RuntimeError(result.get("message", f"{action_name} failed"))
            return result

        set_step("connect", "running", "正在连接 BSP 眼镜")
        connect_result = call_action("/bsp/connect", {}, timeout_s=60)
        device_info = connect_result.get("device_info", device_info)
        set_step("connect", "success", f"已连接 FSN: {device_info.get('fsn') or 'UNKNOWN_FSN'}")

        set_step("init", "running", "正在初始化 BSP 眼镜")
        init_result = call_action("/bsp/init", {}, timeout_s=30)
        device_info = init_result.get("device_info", device_info)
        set_step("init", "success", f"已初始化 FSN: {device_info.get('fsn') or 'UNKNOWN_FSN'}")

        set_step("start", "running", "正在启动 BSP IMU/Camera 数据流")
        start_result = call_action("/bsp/start", {"sensor_mask": 0x01 | 0x02 | 0x04}, timeout_s=30)
        device_info = start_result.get("device_info", device_info)
        set_step("start", "success", "BSP 数据流已启动")

        dataset_name = build_dataset_name(device_info, args.experiment_keyword, args.recorder_name)
        start_descriptor = master.call("lookup_action", {"action": "/record/start"}).get("endpoints")
        stop_descriptor = master.call("lookup_action", {"action": "/record/stop"}).get("endpoints")

        set_step("start_record", "running", f"开始录制: {dataset_name}")
        start_result = action_call(start_descriptor, {
            "dataset_name": dataset_name,
            "record_profile": "bsp_imu_cam",
            "topics": ["/bsp/imu", "/bsp/rgb/image_raw", "/bsp/slam/image_raw"],
            "metadata": {
                "device_info": device_info,
                "experiment_keyword": args.experiment_keyword,
                "recorder_name": args.recorder_name,
            },
        }, timeout_s=10)
        if not start_result.get("success"):
            raise RuntimeError(start_result.get("message", "start_record failed"))
        record_started = True
        set_step("start_record", "running", "录制中")

        start = time.time()
        while not stopping:
            elapsed = time.time() - start
            emit({"type": "log", "stream": "stdout", "message": f"录制中: {elapsed:.1f}s"})
            set_step("start_record", "running", f"录制中: {elapsed:.1f}s")
            if args.duration > 0 and elapsed >= args.duration:
                break
            time.sleep(1)

        set_step("stop_record", "running", "正在停止录制")
        stop_result = action_call(stop_descriptor, {}, timeout_s=10)
        record_started = False
        if not stop_result.get("success"):
            raise RuntimeError(stop_result.get("message", "stop_record failed"))
        set_step("stop_record", "success", "录制已停止")
        workflow(steps, "BSP IMU + Camera 录制完成", finished=True, success=True)
        return 0
    except Exception as exc:
        if record_started and stop_descriptor:
            try:
                action_call(stop_descriptor, {}, timeout_s=10)
            except Exception:
                pass
        workflow(steps, str(exc), finished=True, success=False)
        emit({"type": "log", "stream": "stderr", "message": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
