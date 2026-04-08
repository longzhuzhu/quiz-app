#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv/bin/python}"
WORKER_ID="${JOB_WORKER_ID:-$(hostname)}"
POLL_INTERVAL="${JOB_WORKER_POLL_INTERVAL:-5}"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

ensure_python() {
  if [[ -x "${PYTHON_BIN}" ]] && "${PYTHON_BIN}" -c 'import flask, dotenv, sqlalchemy' >/dev/null 2>&1; then
    return 0
  fi

  if command -v python3 >/dev/null 2>&1 && python3 -c 'import flask, dotenv, sqlalchemy' >/dev/null 2>&1; then
    PYTHON_BIN="python3"
    return 0
  fi

  log "未找到可用的 Python 运行环境。请先安装 backend/requirements.txt 中的依赖。"
  exit 1
}

main() {
  cd "${ROOT_DIR}"
  ensure_python
  export PYTHONUNBUFFERED=1
  exec "${PYTHON_BIN}" "${ROOT_DIR}/backend/workers/job_worker.py" --worker-id "${WORKER_ID}" --poll-interval "${POLL_INTERVAL}" "$@"
}

main "$@"
