#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="${ROOT_DIR}/frontend"
DIST_DIR="${FRONTEND_DIR}/dist"

PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv/bin/python}"
APP_HOST="${APP_HOST:-0.0.0.0}"
APP_PORT="${APP_PORT:-5003}"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

ensure_python() {
  if [[ -x "${PYTHON_BIN}" ]] && "${PYTHON_BIN}" -c 'import fastapi, uvicorn, sqlalchemy' >/dev/null 2>&1; then
    return 0
  fi

  if command -v python3 >/dev/null 2>&1 && python3 -c 'import fastapi, uvicorn, sqlalchemy' >/dev/null 2>&1; then
    PYTHON_BIN="python3"
    return 0
  fi

  log "未找到可用的 FastAPI 运行环境。请先安装 backend/requirements.txt 中的依赖。"
  exit 1
}

needs_frontend_build() {
  if [[ ! -f "${DIST_DIR}/index.html" ]]; then
    return 0
  fi

  if [[ "${FRONTEND_DIR}/index.html" -nt "${DIST_DIR}/index.html" ]] || [[ "${FRONTEND_DIR}/package.json" -nt "${DIST_DIR}/index.html" ]] || [[ "${FRONTEND_DIR}/vite.config.js" -nt "${DIST_DIR}/index.html" ]]; then
    return 0
  fi

  if find "${FRONTEND_DIR}/src" "${FRONTEND_DIR}/public" -type f -newer "${DIST_DIR}/index.html" | grep -q .; then
    return 0
  fi

  return 1
}

build_frontend_if_needed() {
  if ! needs_frontend_build; then
    return 0
  fi

  if ! command -v npm >/dev/null 2>&1; then
    log "需要构建前端，但系统中未找到 npm。"
    exit 1
  fi

  if [[ ! -d "${FRONTEND_DIR}/node_modules" ]]; then
    log "需要构建前端，但 ${FRONTEND_DIR}/node_modules 不存在。请先执行 npm install。"
    exit 1
  fi

  log "检测到前端构建产物缺失或过期，开始执行 npm run build..."
  npm --prefix "${FRONTEND_DIR}" run build
}

main() {
  cd "${ROOT_DIR}"
  ensure_python
  build_frontend_if_needed

  export PYTHONUNBUFFERED=1
  export PYTHONPATH="${ROOT_DIR}/backend${PYTHONPATH:+:${PYTHONPATH}}"

  log "使用 uvicorn 启动 FastAPI 服务..."
  exec "${PYTHON_BIN}" -m uvicorn serve:app --host "${APP_HOST}" --port "${APP_PORT}"
}

main "$@"
