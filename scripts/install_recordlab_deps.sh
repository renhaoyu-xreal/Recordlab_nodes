#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MASTER_DIR="${ROOT_DIR}/third_party/Recordlab_master"
MASTER_GIT_URL="${RECORDLAB_MASTER_GIT_URL:-}"
FORCE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --master-git-url)
      MASTER_GIT_URL="${2:-}"
      shift 2
      ;;
    --force)
      FORCE=1
      shift
      ;;
    *)
      echo "未知参数: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "${MASTER_GIT_URL}" ]]; then
  echo "请通过 --master-git-url 或 RECORDLAB_MASTER_GIT_URL 指定 Recordlab_master Git 地址。" >&2
  exit 2
fi

echo "[Recordlab] 工程根目录: ${ROOT_DIR}"
mkdir -p "${ROOT_DIR}/third_party"

if [[ -d "${MASTER_DIR}/.git" ]]; then
  echo "[Recordlab] 更新 third_party/Recordlab_master"
  git -C "${MASTER_DIR}" fetch --all --prune
  git -C "${MASTER_DIR}" pull --ff-only
elif [[ -e "${MASTER_DIR}" && "${FORCE}" != "1" ]]; then
  echo "${MASTER_DIR} 已存在但不是 git 仓库；如需覆盖请加 --force。" >&2
  exit 2
else
  rm -rf "${MASTER_DIR}"
  echo "[Recordlab] 克隆 Recordlab_master"
  git clone "${MASTER_GIT_URL}" "${MASTER_DIR}"
fi

echo "[Recordlab] 准备 XREAL runtime"
export RECORDLAB_NODES_ROOT="${ROOT_DIR}"
python3 "${ROOT_DIR}/third_party/xreal/scripts/bootstrap_xreal_runtime.py" --project-root "${ROOT_DIR}"

echo "[Recordlab] 依赖准备完成"
echo "构建示例："
echo "  cmake -S ${ROOT_DIR} -B ${ROOT_DIR}/build"
echo "  cmake --build ${ROOT_DIR}/build"
