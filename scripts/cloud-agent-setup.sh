#!/usr/bin/env bash
# Cloud Agent 环境安装脚本（幂等）。
# 负责：系统依赖、PostgreSQL、Python venv、后端依赖、前端依赖、.env、数据库迁移引导。
# 该脚本可重复执行；已完成的步骤会被跳过。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

DB_NAME="${DB_NAME:-quiz}"
DB_USER="${DB_USER:-quiz}"
DB_PASSWORD="${DB_PASSWORD:-quizpass}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"
ADMIN_USERNAME="${ADMIN_USERNAME:-nianyu}"
ADMIN_EMAIL="${ADMIN_EMAIL:-nianyu@example.com}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-Admin12345}"

log() { echo "[setup] $*"; }

have() { command -v "$1" >/dev/null 2>&1; }

# 尝试非交互 sudo；无 sudo 时回退为直接执行（例如 root 环境）。
sudo_run() {
  if have sudo && sudo -n true 2>/dev/null; then
    sudo "$@"
  else
    "$@"
  fi
}

pg_cluster() {
  # 输出 "版本 集群名"，例如 "16 main"
  pg_lsclusters -h 2>/dev/null | awk 'NR==1{print $1, $2; exit}'
}

install_system_deps() {
  local need_pg=0 need_venv=0
  have pg_lsclusters || need_pg=1
  python3 -c 'import ensurepip' >/dev/null 2>&1 || need_venv=1

  if [[ "${need_pg}" -eq 0 && "${need_venv}" -eq 0 ]]; then
    log "系统依赖已就绪（PostgreSQL + python venv）"
    return 0
  fi

  log "安装系统依赖 (postgresql / python venv)..."
  sudo_run apt-get update -qq || true
  local pkgs=()
  [[ "${need_pg}" -eq 1 ]] && pkgs+=(postgresql postgresql-contrib)
  local pyver
  pyver="$(python3 -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  [[ "${need_venv}" -eq 1 ]] && pkgs+=("python${pyver}-venv")
  sudo_run apt-get install -y -qq "${pkgs[@]}"
}

start_postgres() {
  local vc version cluster
  vc="$(pg_cluster)"
  version="$(echo "${vc}" | awk '{print $1}')"
  cluster="$(echo "${vc}" | awk '{print $2}')"
  if [[ -z "${version}" ]]; then
    log "未找到 PostgreSQL 集群"; return 1
  fi
  if pg_lsclusters "${version}" "${cluster}" 2>/dev/null | grep -q online; then
    log "PostgreSQL ${version}/${cluster} 已在线"
  else
    log "启动 PostgreSQL ${version}/${cluster}..."
    sudo_run pg_ctlcluster "${version}" "${cluster}" start || true
  fi
  # 等待可连接
  for _ in $(seq 1 30); do
    if sudo_run -u postgres pg_isready -q 2>/dev/null; then return 0; fi
    sleep 1
  done
  log "警告：PostgreSQL 未在预期时间内就绪"
}

ensure_database() {
  log "确保数据库角色与库存在..."
  sudo_run -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" | grep -q 1 \
    || sudo_run -u postgres psql -c "CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';"
  sudo_run -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1 \
    || sudo_run -u postgres psql -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"
}

setup_python() {
  if [[ ! -x "${ROOT_DIR}/.venv/bin/python" ]]; then
    log "创建 Python venv..."
    python3 -m venv "${ROOT_DIR}/.venv"
  fi
  log "安装后端依赖..."
  "${ROOT_DIR}/.venv/bin/pip" install --upgrade pip -q
  "${ROOT_DIR}/.venv/bin/pip" install -r "${ROOT_DIR}/backend/requirements.txt" -q
}

setup_frontend() {
  log "安装前端依赖..."
  ( cd "${ROOT_DIR}/frontend" && npm install --no-audit --no-fund )
}

write_env() {
  local env_file="${ROOT_DIR}/backend/.env"
  if [[ -f "${env_file}" ]]; then
    log "backend/.env 已存在，跳过"
    return 0
  fi
  log "生成 backend/.env..."
  cat > "${env_file}" <<EOF
SECRET_KEY=dev-secret-key-local-cloud-agent
JWT_SECRET_KEY=dev-jwt-secret-key-local-cloud-agent
DATABASE_URL=postgresql+psycopg://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}
CORS_ALLOWED_ORIGINS=http://localhost:5001,http://127.0.0.1:5001
ENABLE_OPENAPI=true
AI_API_BASE_URL=https://api.openai.com
AI_API_KEY=
AI_MODEL=gpt-4o-mini
EOF
}

bootstrap_migrations() {
  # 迁移 003 要求管理员用户 '${ADMIN_USERNAME}' 预先存在，
  # 因此先迁移到 002，创建管理员，再迁移到 head。全部步骤幂等。
  log "执行数据库迁移引导..."
  ( cd "${ROOT_DIR}/backend" && "${ROOT_DIR}/.venv/bin/python" -m alembic upgrade 002 )
  ADMIN_USERNAME="${ADMIN_USERNAME}" ADMIN_EMAIL="${ADMIN_EMAIL}" ADMIN_PASSWORD="${ADMIN_PASSWORD}" \
  "${ROOT_DIR}/.venv/bin/python" - <<'PY'
import os, sys
sys.path.insert(0, os.path.join(os.getcwd(), "backend"))
from app.core.security import get_password_hash
from app.core.database import engine
from sqlalchemy import text
u = os.environ["ADMIN_USERNAME"]; e = os.environ["ADMIN_EMAIL"]; p = os.environ["ADMIN_PASSWORD"]
with engine.begin() as c:
    exists = c.execute(text("SELECT 1 FROM users WHERE username=:u"), {"u": u}).first()
    if exists:
        print(f"[setup] 管理员 {u} 已存在")
    else:
        c.execute(
            text("INSERT INTO users (username, email, password_hash, is_admin, created_at) "
                 "VALUES (:u, :e, :p, true, now())"),
            {"u": u, "e": e, "p": get_password_hash(p)},
        )
        print(f"[setup] 已创建管理员 {u}")
PY
  ( cd "${ROOT_DIR}/backend" && "${ROOT_DIR}/.venv/bin/python" -m alembic upgrade head )
}

main() {
  install_system_deps
  start_postgres
  ensure_database
  setup_python
  setup_frontend
  write_env
  bootstrap_migrations
  log "安装完成。"
}

main "$@"
