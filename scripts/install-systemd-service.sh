#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="${SERVICE_NAME:-quiz-app}"
DEFAULT_SERVICE_USER="${SUDO_USER:-$(id -un)}"
SERVICE_USER="${SERVICE_USER:-${DEFAULT_SERVICE_USER}}"
SERVICE_GROUP="${SERVICE_GROUP:-$(id -gn "${SERVICE_USER}")}"
APP_PORT="${APP_PORT:-5003}"
APP_HOST="${APP_HOST:-0.0.0.0}"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 sudo 执行此脚本，例如：sudo bash scripts/install-systemd-service.sh"
  exit 1
fi

cat >"${SERVICE_FILE}" <<EOF
[Unit]
Description=CIPT Quiz App
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_GROUP}
WorkingDirectory=${ROOT_DIR}
Environment=APP_HOST=${APP_HOST}
Environment=APP_PORT=${APP_PORT}
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-${ROOT_DIR}/.env
ExecStart=${ROOT_DIR}/scripts/start-prod.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}.service"
systemctl status "${SERVICE_NAME}.service" --no-pager
