#!/usr/bin/env bash
# Cloud Agent 每次启动时的服务预置：确保 PostgreSQL 在线。
# 后端 / worker / 前端由 environment.json 的 terminals 负责长驻运行。
set -euo pipefail

log() { echo "[start] $*"; }

have() { command -v "$1" >/dev/null 2>&1; }

sudo_run() {
  if have sudo && sudo -n true 2>/dev/null; then
    sudo "$@"
  else
    "$@"
  fi
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
    if sudo_run -u postgres pg_isready -q 2>/dev/null; then
      log "PostgreSQL 就绪"; return 0
    fi
    sleep 1
  done
  log "警告：PostgreSQL 未在预期时间内就绪"
}

start_postgres
log "启动预置完成。"
