# fix: 移除硬编码数据库凭据

## Goal

将代码中硬编码的 PostgreSQL 明文密码替换为环境变量/配置占位符，防止凭据泄露到 Git 历史。

## Requirements

* `[必须]` `backend/app/core/config.py` 中 `DATABASE_URL` 默认值改为占位符，真实值走 `.env`
* `[必须]` `.trellis/tasks/archive/.../db_diag.py` 中 `DSN` 改为从环境变量或 config 模块读取
* `[必须]` 确保后端仍能正常启动（`.env` 提供真实值）

## Acceptance Criteria

* [ ] `git diff` 中不再出现 `REDACTED_DB_PASSWORD` 明文密码
* [ ] `config.py` 的 `DATABASE_URL` 默认值为无害占位符
* [ ] `db_diag.py` 不含硬编码 DSN
* [ ] 后端可正常启动连接数据库

## Out of Scope

* 修改 `.env` 文件内容（已含真实值，无需改动）
* 清除 Git 历史中的密码（需 `git filter-branch`，不在本任务范围）
* 其他密钥类型（JWT_SECRET_KEY 等暂不改）

## Technical Notes

* 涉及文件：`backend/app/core/config.py`, `.trellis/tasks/archive/2026-05/05-04-smart-import-cipt-283-pdf/research/scripts/db_diag.py`
