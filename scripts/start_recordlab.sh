#!/usr/bin/env bash
set -euo pipefail

MASTER_BIN="${RECORDLAB_MASTER_BIN:-/home/hyren/Recordlab_master/build/recordlab_master}"
MASTER_CLI="${RECORDLAB_MASTER_CLI:-/home/hyren/Recordlab_master/build/recordlab_master_cli}"
SCRIPT_RUNNER_BIN="${RECORDLAB_SCRIPT_RUNNER_BIN:-/home/hyren/Recordlab_master/build/recordlab_script_runner}"
WATCHDOG_BIN="${RECORDLAB_WATCHDOG_BIN:-/home/hyren/Recordlab_nodes/build/watchdog_node}"
LAUNCHER_BIN="${RECORDLAB_LAUNCHER_BIN:-/home/hyren/Recordlab_nodes/build/recordlab_launcher}"
GUI_BIN="${RECORDLAB_GUI_BIN:-/home/hyren/Recordlab_nodes/build/recordlab_gui}"

pids=()

cleanup() {
  for ((i=${#pids[@]}-1; i>=0; i--)); do
    pid="${pids[$i]}"
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
  done
}
trap cleanup EXIT INT TERM

require_bin() {
  if [[ ! -x "$1" ]]; then
    echo "缺少可执行文件: $1" >&2
    exit 1
  fi
}

require_bin "$MASTER_BIN"
require_bin "$MASTER_CLI"
require_bin "$SCRIPT_RUNNER_BIN"
require_bin "$WATCHDOG_BIN"
require_bin "$LAUNCHER_BIN"
require_bin "$GUI_BIN"

echo "[Recordlab] 启动 master"
"$MASTER_BIN" &
pids+=("$!")

echo "[Recordlab] 等待 master 可用"
for _ in {1..50}; do
  if "$MASTER_CLI" list nodes >/dev/null 2>&1; then
    break
  fi
  sleep 0.1
done
"$MASTER_CLI" list nodes >/dev/null

echo "[Recordlab] 启动 script_runner"
"$SCRIPT_RUNNER_BIN" &
pids+=("$!")
sleep 0.2

echo "[Recordlab] 启动 watchdog"
"$WATCHDOG_BIN" &
pids+=("$!")
sleep 0.2

echo "[Recordlab] 启动 launcher"
"$LAUNCHER_BIN" &
pids+=("$!")
sleep 0.2

echo "[Recordlab] 启动 GUI"
"$GUI_BIN"
