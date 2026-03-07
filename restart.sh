#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="${ROOT_DIR}/frontend"
LOG_DIR="${ROOT_DIR}/logs"

BACKEND_PORT="${BACKEND_PORT:-5003}"
VITE_HOST="${VITE_HOST:-127.0.0.1}"
VITE_PORT="${VITE_PORT:-5173}"

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="${PYTHON_BIN:-python3}"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="${PYTHON_BIN:-python}"
else
  echo "❌ 未找到 python 或 python3，请先安装 Python。"
  exit 1
fi

mkdir -p "${LOG_DIR}"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

is_listening() {
  local port="$1"
  lsof -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1
}

stop_by_port() {
  local port="$1"
  local name="$2"
  local pids

  pids="$(lsof -ti tcp:"${port}" || true)"
  if [[ -z "${pids}" ]]; then
    log "${name} 未运行（端口 ${port} 空闲）"
    return 0
  fi

  log "停止 ${name}（端口 ${port}）..."
  kill ${pids} >/dev/null 2>&1 || true
  sleep 1

  if is_listening "${port}"; then
    log "${name} 未完全退出，执行强制停止..."
    kill -9 ${pids} >/dev/null 2>&1 || true
    sleep 1
  fi

  if is_listening "${port}"; then
    log "❌ ${name} 停止失败，请手动检查。"
    exit 1
  fi

  log "✅ ${name} 已停止"
}

start_backend() {
  log "启动后端..."
  (
    cd "${ROOT_DIR}"
    nohup "${PYTHON_BIN}" run.py > "${LOG_DIR}/backend.log" 2>&1 &
    echo $! > "${LOG_DIR}/backend.pid"
  )

  sleep 1
  if is_listening "${BACKEND_PORT}"; then
    log "✅ 后端已启动：http://127.0.0.1:${BACKEND_PORT}"
  else
    log "❌ 后端启动失败，请查看 ${LOG_DIR}/backend.log"
    exit 1
  fi
}

start_vite() {
  if [[ ! -d "${FRONTEND_DIR}" ]]; then
    log "❌ 未找到前端目录：${FRONTEND_DIR}"
    exit 1
  fi

  log "启动 Vite 前端..."
  (
    cd "${FRONTEND_DIR}"
    nohup npm run dev -- --host "${VITE_HOST}" --port "${VITE_PORT}" > "${LOG_DIR}/vite.log" 2>&1 &
    echo $! > "${LOG_DIR}/vite.pid"
  )

  sleep 1
  if is_listening "${VITE_PORT}"; then
    log "✅ Vite 已启动：http://${VITE_HOST}:${VITE_PORT}"
  else
    log "❌ Vite 启动失败，请查看 ${LOG_DIR}/vite.log"
    exit 1
  fi
}

restart_backend() {
  stop_by_port "${BACKEND_PORT}" "后端"
  start_backend
}

restart_vite() {
  stop_by_port "${VITE_PORT}" "Vite 前端"
  start_vite
}

usage() {
  cat <<EOF
用法：
  ./restart.sh                # 一键重启后端 + Vite
  ./restart.sh all            # 同上
  ./restart.sh backend        # 仅重启后端
  ./restart.sh frontend|vite  # 仅重启前端 Vite

可选环境变量：
  BACKEND_PORT=5003
  VITE_HOST=127.0.0.1
  VITE_PORT=5173
  PYTHON_BIN=python3
EOF
}

target="${1:-all}"
case "${target}" in
all)
  log "开始一键重启后端和 Vite..."
  restart_backend
  restart_vite
  ;;
backend)
  restart_backend
  ;;
frontend | vite)
  restart_vite
  ;;
-h | --help | help)
  usage
  exit 0
  ;;
*)
  log "❌ 不支持的参数：${target}"
  usage
  exit 1
  ;;
esac

log "🎉 重启完成。日志文件：${LOG_DIR}/backend.log, ${LOG_DIR}/vite.log"
