# security: pre-commit 密钥扫描 + 配置模板分离 + 诊断脚本规范

## Goal

防止敏感凭据（数据库密码、API Key、JWT Secret）再次被提交进 git 仓库。通过三层防线：pre-commit 钩子自动拦截、配置模板与真实值严格分离、诊断脚本禁止硬编码凭据。

## What I already know

* `backend/app/core/config.py`（FastAPI 版）默认值已修复为占位符 `user:pass@localhost:5432/quiz`
* `backend/config.py`（Flask 版）默认值也用占位符 `sqlite:///quiz.db`
* `backend/.env` 含真实 DATABASE_URL（含密码），已在 `.gitignore` 中
* `.env.example` 已存在但缺少 DATABASE_URL 占位符模板
* `backend/scripts/import_iapp_glossary.py` 硬编码了 Algolia API Key（`05142b663d0923f3d221386f59c9702c`）
* `.trellis/tasks/archive/.../db_diag.py` 已修复为从环境变量读取
* `backend/test_high_frequency_vocab.py` 含测试用硬编码密钥（可接受）
* 项目无 `.pre-commit-config.yaml`，无任何 pre-commit 钩子
* 项目无 pytest、lint 工具配置
* `backend/.env` 使用 pydantic-settings 绝对路径加载

## Assumptions (temporary)

* Algolia API Key 是公开搜索 key（IAPP 网站前端 JS 可见），但仍应移出源码
* 测试文件中的 mock secret 可接受，不在扫描范围内

## Requirements

1. **Pre-commit + gitleaks 密钥扫描**：安装 `pre-commit` 框架 + gitleaks 钩子，`git commit` 前自动检测并拦截敏感值。用 `.gitleaksignore` 白名单处理占位符误报，不自造轮子
2. **配置模板分离**：`.env.example` 补全所有配置项（含 DATABASE_URL、ALGOLIA_*），源码 default 值全部为占位符
3. **诊断脚本规范**：`backend/scripts/` 和 `.trellis/tasks/` 下的脚本必须从环境变量读凭据，不允许硬编码
4. **Algolia API Key 外移**：从 `import_iapp_glossary.py` 移入 `.env` + `.env.example`

## Acceptance Criteria

- [ ] `pre-commit run --all-files` 不报任何密钥泄漏
- [ ] `.env.example` 包含所有后端配置项（DATABASE_URL、AI_API_KEY、ALGOLIA_* 等）
- [ ] 源码中不存在明文密码/真实 API Key（测试 mock 除外）
- [ ] `backend/scripts/import_iapp_glossary.py` 从环境变量读取 Algolia 配置
- [ ] `.trellis/tasks/` 下脚本无硬编码凭据
- [ ] `.gitleaksignore` 已配置，占位符不误报

## Definition of Done

* `pre-commit run --all-files` 通过
* 已有源码中无真实凭据
* Rollback: 删除 `.pre-commit-config.yaml` + `pre-commit uninstall` 即可回退

## Decision (ADR-lite)

**Context**: 需要选择 pre-commit 密钥扫描工具，防止凭据再次泄漏
**Decision**: gitleaks（v8.30.1）+ pre-commit 框架，不自造轮子
**Consequences**: 零运行时依赖（Go 二进制自动下载）、TOML 自定义规则、`.gitleaksignore` 白名单；不选 detect-secrets（维护滞后、自定义规则需写 Python 插件）、不选 git-secrets（已停维、无原生 pre-commit 支持）

## Out of Scope

* 修改 `backend/test_*.py` 中的测试 mock 密钥
* CI/CD 流水线集成（项目无 CI 配置）
* 加密 `.env` 文件本身
* 自造诊断脚本 lint 规则（交给 gitleaks 自定义规则覆盖）

## Research References

* [`research/secret-scanning-tools.md`](research/secret-scanning-tools.md) — gitleaks 推荐：零运行时依赖、TOML 自定义规则、26K+ stars

## Technical Notes

* FastAPI config: `backend/app/core/config.py` — pydantic-settings，env_file 绝对路径
* Flask config: `backend/config.py` — `os.environ.get()` + sqlite 默认值
* `.env.example` 缺 DATABASE_URL / ALGOLIA_* 行
* Algolia key 位于 `backend/scripts/import_iapp_glossary.py:17`
* 项目无 pre-commit 框架，需全新安装
* gitleaks pre-commit hook: `repo: https://github.com/gitleaks/gitleaks`
* 自定义 PostgreSQL 连接串规则需 6 行 TOML
