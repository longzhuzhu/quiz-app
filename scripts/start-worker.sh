#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv/bin/python}"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

ensure_python() {
  if [[ -x "${PYTHON_BIN}" ]] && "${PYTHON_BIN}" -c 'import fastapi, sqlalchemy' >/dev/null 2>&1; then
    return 0
  fi

  if command -v python3 >/dev/null 2>&1 && python3 -c 'import fastapi, sqlalchemy' >/dev/null 2>&1; then
    PYTHON_BIN="python3"
    return 0
  fi

  log "未找到可用的 FastAPI 运行环境。请先安装 backend/requirements.txt 中的依赖。"
  exit 1
}

main() {
  cd "${ROOT_DIR}"
  ensure_python
  export PYTHONUNBUFFERED=1
  export PYTHONPATH="${ROOT_DIR}/backend${PYTHONPATH:+:${PYTHONPATH}}"
  exec "${PYTHON_BIN}" -m app.workers.job_worker "$@"
}

main "$@"
