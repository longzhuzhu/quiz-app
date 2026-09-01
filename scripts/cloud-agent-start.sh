#!/usr/bin/env bash
# Cloud Agent 每次启动脚本：确保 PostgreSQL 在线，并在后台拉起
# 后端 API、后台 worker、前端 Vite 开发服务器。脚本幂等：已在运行的服务会被跳过，
# 启动后台进程后立即返回。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

LOG_DIR="${ROOT_DIR}/logs"
mkdir -p "${LOG_DIR}"

BACKEND_PORT="${APP_PORT:-5003}"
FRONTEND_PORT="${FRONTEND_PORT:-5001}"
WORKER_MATCH="${ROOT_DIR}/.venv/bin/python -m app.workers.job_worker"

log() { echo "[start] $*"; }
have() { command -v "$1" >/dev/null 2>&1; }

sudo_run() {
  if have sudo && sudo -n true 2>/dev/null; then
    sudo "$@"
  else
    "$@"
  fi
}

port_listening() {
  local port="$1"
  (exec 3<>"/dev/tcp/127.0.0.1/${port}") 2>/dev/null && { exec 3>&- 3<&-; return 0; } || return 1
}

wait_for_port() {
  local port="$1" name="$2"
  for _ in $(seq 1 40); do
    if port_listening "${port}"; then log "${name} 就绪 (127.0.0.1:${port})"; return 0; fi
    sleep 1
  done
  log "警告：${name} 未在预期时间内监听端口 ${port}"
  return 1
}

start_postgres() {
  local vc version cluster
  vc="$(pg_lsclusters -h 2>/dev/null | awk 'NR==1{print $1, $2; exit}')"
  version="$(echo "${vc}" | awk '{print $1}')"
  cluster="$(echo "${vc}" | awk '{print $2}')"
  if [[ -z "${version}" ]]; then
    log "未找到 PostgreSQL 集群，跳过"; return 0
  fi
  if pg_lsclusters "${version}" "${cluster}" 2>/dev/null | grep -q online; then
    log "PostgreSQL ${version}/${cluster} 已在线"
  else
    log "启动 PostgreSQL ${version}/${cluster}..."
    sudo_run pg_ctlcluster "${version}" "${cluster}" start || true
  fi
  for _ in $(seq 1 30); do
    if sudo_run -u postgres pg_isready -q 2>/dev/null; then log "PostgreSQL 就绪"; return 0; fi
    sleep 1
  done
  log "警告：PostgreSQL 未在预期时间内就绪"
}

start_backend() {
  if port_listening "${BACKEND_PORT}"; then
    log "后端已在运行 (端口 ${BACKEND_PORT})"; return 0
  fi
  log "启动后端 API..."
  ( cd "${ROOT_DIR}" && nohup "${ROOT_DIR}/.venv/bin/python" run.py >"${LOG_DIR}/backend.log" 2>&1 & )
}

start_worker() {
  # 用完整的 venv python 路径匹配，避免误匹配到其它脚本/命令行。
  if pgrep -f -- "${WORKER_MATCH}" >/dev/null 2>&1; then
    log "后台 worker 已在运行 (pid $(pgrep -f -- "${WORKER_MATCH}" | tr '\n' ' '))"; return 0
  fi
  log "启动后台 worker..."
  ( cd "${ROOT_DIR}" && nohup bash scripts/start-worker.sh >"${LOG_DIR}/worker.log" 2>&1 & )
}

start_frontend() {
  if port_listening "${FRONTEND_PORT}"; then
    log "前端已在运行 (端口 ${FRONTEND_PORT})"; return 0
  fi
  log "启动前端 Vite 开发服务器..."
  ( cd "${ROOT_DIR}/frontend" && nohup npm run dev -- --host 0.0.0.0 >"${LOG_DIR}/frontend.log" 2>&1 & )
}

main() {
  start_postgres
  start_backend
  start_worker
  start_frontend
  wait_for_port "${BACKEND_PORT}" "后端 API" || true
  wait_for_port "${FRONTEND_PORT}" "前端 Vite" || true
  log "启动完成。日志目录：${LOG_DIR}"
}

main "$@"
