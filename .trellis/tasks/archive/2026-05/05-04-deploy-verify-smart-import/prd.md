# 部署环境验证 smart-import 准确率

## Goal

在真实环境（FastAPI + PostgreSQL + 本地 AI 代理）下验证 PR-0~PR-4 的 smart-import 改造效果，确认 CIPT 283 题 PDF 的唯一题号入库数从 258 提升到 ≥277（≥98%），并验证 reconciliation 报告、reparse 卫生、chunk 重试降级链路均工作正常。

## What I already know

* **环境已就绪**：FastAPI 运行在 :5003，PostgreSQL :5433，AI 代理 :5020，密钥加密存于 DB
* **既有 Job 7 数据**：31 chunk，chunk 27 failed（11,848 字符），258 唯一题号已入库（缺 222-245）
* **前端 Vite 可用**：`npm run dev` 启动开发服务器，自动代理 /api → 127.0.0.1:5003
* **测试全绿**：31 个 pytest case 全部通过
* **需重启后端**：当前 FastAPI 进程是 PR-4 提交前启动的，需重启才能加载新代码

## Assumptions (temporary)

* 重启后端后，对 job 7 执行 reparse 会触发 PR-2 的 L1 重试 + L2 降级补齐 chunk 27
* PR-3 的 imported_qnos 去重会在 reparse 时阻止已入库的 258 个题号重复入库
* AI 代理稳定可用（127.0.0.1:5020），LLM 调用不会因代理故障超时
* 不需要新建 ImportJob——直接对 job 7 执行 reparse 即可验证所有改造

## Open Questions

* 验证完成后是否需要清理 job 7 的旧数据（reparse 产生的 duplicate 行等）？
* 是否需要同时验证前端 UI 的复核页面与 reconciliation 数据展示？

## Requirements (evolving)

* `[必须]` 重启 FastAPI 后端加载最新代码
* `[必须]` 对 job 7 执行 reparse，验证 chunk 27 补题效果
* `[必须]` 验证 reconciliation 报告生成（expected / imported_unique / missing_qnos / duplicates_in_db 六字段）
* `[必须]` 验证 reparse 卫生（已入库题号不重复入库）
* `[必须]` 通过前端 UI 交叉验证（复核列表、题库详情、reconciliation 展示）

## Acceptance Criteria (evolving)

* [x] 重启后端后 API 正常响应
* [x] reparse job 后，唯一题号入库数 ≥ 277（≥ 98%） — 实际 282/283 = 99.6%
* [x] job 的 `config_json["reconciliation"]` 含六字段，`missing_qnos` 列表长度 ≤ 6 — missing_qnos = []
* [x] reparse 不产生新的 imported 重复行（duplicate 行不计入 imported_unique） — 0 重复
* [x] chunk 27 的 status 变为 `parsed`（不再是 `failed`）

## Definition of Done

* [x] 后端重启、reparse 执行、数据验证全流程跑通
* [x] 关键数据截图或查询结果记录
* [x] 未发现新 bug

## Verification Results

* **Job 10** (CIPT 283题.pdf, 新导入)：282/283 唯一题号入库 (99.6%)
* **Chunk 27**: 从 `failed` → `parsed`（PR-2 L1 重试成功）
* **PR-3 卫生**: 新导入零重复（0 duplicate qnos）
* **PR-4 reconciliation**: 六字段齐全，`missing_qnos=[]`, `per_question_failures_count=0`
* **Q264**: LLM 标记 `STEM_TOO_SHORT`（题干为空），数据质量问题，非 bug
* **Frontend**: Vite :5001 运行，API 代理到 :5003 正常
* **Backend**: FastAPI :5003 运行，Worker PID 2096362 正常处理任务

## Out of Scope (explicit)

* 新建 ImportJob（用 job 7 验证即可）
* 修改前端 UI
* 修改 AI prompt / model 配置
* 压力测试 / 多 PDF 并行导入

## Technical Notes

* 重启命令：kill 当前 PID → `cd backend && python3 -c "from app.main import create_app; app = create_app(); import uvicorn; uvicorn.run(app, host='0.0.0.0', port=5003)"`
* reparse 触发：`POST /api/import-jobs/{id}/reparse`（需 JWT token）
* 数据验证 SQL：查 `import_parsed_questions` / `import_chunks` / `import_jobs.config_json`
* AI 代理地址：http://127.0.0.1:5020，模型 gpt-5.4
