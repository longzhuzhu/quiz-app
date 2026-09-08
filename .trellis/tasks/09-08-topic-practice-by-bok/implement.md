# 专项练习 — 执行计划

## 实施顺序

分五段，每段结束后系统都处于可运行状态。

### 第 1 段：数据层

- [ ] `backend/app/models/exam_topic.py` — `ExamTopic` 模型（自引用 `parent_id`，`UNIQUE(exam_id, code)`）
- [ ] `backend/app/models/question_topic.py` — `QuestionTopic` 关联模型（复合主键 + `source` 列）
- [ ] `backend/app/models/question.py` — 加 `topics` 关系
- [ ] `backend/app/models/exam.py` — 加 `topics` 关系
- [ ] `backend/app/models/quiz.py:12 QuizSession` — 加 `topic_id` 可空外键
- [ ] `backend/app/models/__init__.py` — 导出新模型
- [ ] `backend/alembic/versions/004_exam_topics.py` — `down_revision = "003"`，建两表 + 加一列，`downgrade()` 完整可逆

验证：`cd backend && alembic upgrade head`，再 `alembic downgrade 003` 后重新 `upgrade head`，确认可逆。

### 第 2 段：考点树数据与灌入

- [ ] `backend/app/data/topic_templates/cipt-bok-4.0.0.json` — 5 域 16 能力项，字段齐备（`code` / `name_en` / `name_zh` / `short_name_zh` / `blueprint_min` / `blueprint_max` / `indicators_en` / `order_index`）。内容逐条对照 `research/bok-4.0.0-taxonomy.md`，英文原文不得改写
- [ ] `backend/scripts/seed_exam_topics.py` — `--exam-slug` 参数，按 `(exam_id, code)` upsert，可重复执行；打印新增/更新计数

验证：对存量 CIPT 考试项目执行两次，第二次应全部为「更新」且总数仍为 21 行（5 + 16）。

### 第 3 段：AI 批量打标

- [ ] `backend/app/services/job_service.py:22` — 加 `JOB_TYPE_QUESTION_TOPIC_TAG = "question_topic_tag"`
- [ ] `backend/app/services/job_service.py:80 count_pending_items` — 加分支：该题库下不存在 `source='ai'` 关联的题目数
- [ ] `backend/app/services/topic_tagging_service.py`（新）— 拼 prompt、调 `ai_service.call_ai_api`、解析响应、校验 code 合法性、落库
- [ ] `backend/app/services/job_handlers.py:35 run_job` — 加分派分支
- [ ] `backend/app/services/job_handlers.py` — `handle_question_topic_tag`，分批 + `heartbeat_job`，形态照 `handle_bank_frequent_translate`（同文件 `:90`）
- [ ] `backend/app/api/routes/admin_banks.py` — `POST /{bank_id}/topic-tagging`

验证：先用 3–5 道题的小题库跑通，确认 `background_jobs` 行的 `progress_done` / `success_count` / `skipped_count` 递增正常，再对 283 题题库全量跑。

### 第 4 段：查询与答题 API

- [ ] `backend/app/api/routes/banks.py` — `GET /{bank_id}/topics`，返回 5 个域 + 每域题数 + 蓝图配额 + `unclassified_count`
- [ ] `backend/app/schemas/quiz.py:8 QuizStartRequest` — 加 `topic_id: int | None = None`
- [ ] `backend/app/api/routes/quiz.py:116 start_quiz` — 加 `mode == "topic"` 分支：按域反查其下能力项关联的题目 id（去重、随机序）；`topic_id` 为空则取无任何关联的题目
- [ ] `backend/app/api/routes/quiz.py:317 history` / `:433 session_detail` — 输出 `topic_short_name`
- [ ] `backend/app/schemas/quiz.py` — `QuizSessionOut` / `HistoryItemOut` 加 `topic_short_name`
- [ ] `backend/app/api/routes/questions.py:94 update_question` — 处理 `topic_ids`，写 `source='manual'`；**不**触发 `clear_question_translation` / `clear_question_explanation`
- [ ] `backend/app/schemas/question.py` — `QuestionUpdateRequest` 加 `topic_ids`
- [ ] `backend/app/api/routes/questions.py:48 list_questions` — 每题带 `topics`

验证：`GET /api/banks/{id}/topics` 的各域题数之和 + `unclassified_count` 应等于题库总题数（跨域题会被重复计入域计数，所以只校验「未分类 + 至少有一个考点的题数 = 总数」）。

### 第 5 段：前端

- [ ] `frontend/src/views/HomeView.vue:107` — 题库卡片加「🎯 专项练习」按钮，`bank.question_count === 0` 时禁用
- [ ] `frontend/src/views/HomeView.vue:125` 附近 — 新增考点选择弹窗，复用 `BaseModal`；每项显示「域短名 · 考试占 X–Y 题 · 本库 N 题」，末尾一项「未分类 · N 题」；`N === 0` 的项禁用
- [ ] `frontend/src/views/HomeView.vue:208 modeLabel` — 加 `topic: '专项练习'`
- [ ] `frontend/src/stores/quiz.js:10 startQuiz` — 透传 `topic_id`
- [ ] `frontend/src/views/HomeView.vue` 继续答题卡片 / `HistoryView.vue` — 有 `topic_short_name` 时显示为「专项练习 · 数据采集」

验证：手动走一遍——选域开练、中途退出、从首页「继续答题」回到同一会话、历史记录里能看出练的是哪个域。

## 测试

沿用 `backend/tests/` 的纯单元测试形态（无 conftest、无 DB、`sys.path` 插入，见 `test_quiz_resume_index.py:1`）：

- [ ] `backend/tests/test_topic_tagging_parse.py` — 打标响应解析：正常多 code、空数组（判不准）、非法 code 被丢弃、JSON 带 markdown 代码围栏（`ai_service.py:21 _strip_code_fence` 已有先例）
- [ ] `backend/tests/test_topic_question_selection.py` — 按域汇总题目 id：跨域题只出现一次、域下无题返回空、未分类分支

运行：`cd backend && python -m pytest tests/ -q`

## 风险点与回滚

| 风险 | 回滚方式 |
|---|---|
| 迁移 004 出问题 | `alembic downgrade 003`，两张新表和一列全部是新增，不影响存量数据 |
| 打标结果大面积不准 | 清空 `question_topics` 中 `source='ai'` 的行后改 prompt 重跑；`source='manual'` 的人工修正不受影响 |
| 打标任务卡死 | 现有 `job_service.py:225 recover_stale_jobs` 的租约回收机制覆盖；`active_scope_key` 唯一约束保证不会重复建任务 |
| 前端入口挤爆题库卡片 | 卡片已有 4 个按钮，加第 5 个后窄屏可能换行。已有 `flex-wrap`（`HomeView.vue:107`），先观察实际效果 |

## 起工前确认

- [ ] `alembic current` 确认本地库已在 `003`
- [ ] 确认存量 CIPT 考试项目的 slug，供第 2 段灌入使用
- [ ] AI 相关环境变量（`AI_API_BASE_URL` / `AI_API_KEY` / `AI_MODEL`）本地可用，否则第 3 段无法验证
