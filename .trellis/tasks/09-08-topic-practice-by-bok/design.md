# 专项练习 — 技术设计

## 架构与边界

四块改动，自下而上：

1. **考点分类树**：新表 `exam_topics`，两层自引用，随考试项目存在，由仓库内的模板文件 + 幂等脚本灌入。
2. **题目—考点关联**：新表 `question_topics`，多对多，区分 AI 打标与人工修正两种来源。
3. **AI 批量打标**：复用现有 `background_jobs` 框架新增一个 job type，管理员在题库上手动触发。
4. **专项练习答题**：`quiz_sessions` 增加 `topic_id`，新增 `mode="topic"`，题库卡片加入口。

## 数据模型

### `exam_topics`（新表）

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | Integer PK | |
| `exam_id` | Integer FK → `exams.id`，NOT NULL | 考点归属考试项目（D6） |
| `parent_id` | Integer FK → `exam_topics.id`，NULL | 一级域为 NULL |
| `level` | SmallInteger NOT NULL | `1`=域，`2`=能力项 |
| `code` | String(16) NOT NULL | `II` / `II.A` |
| `name_en` | Text NOT NULL | BOK 原文，用于打标 prompt 与溯源 |
| `name_zh` | Text NOT NULL | 中文全称 |
| `short_name_zh` | String(40) NOT NULL | 窄空间用短名 |
| `blueprint_min` | Integer NOT NULL | 考试出题数下限 |
| `blueprint_max` | Integer NOT NULL | 考试出题数上限 |
| `indicators_en` | JSONB NOT NULL default `[]` | 表现指标原文列表，仅供打标 prompt |
| `order_index` | Integer NOT NULL default 0 | 展示顺序 |
| `source_version` | String(20) NOT NULL | `4.0.0`，供日后换版识别 |
| `created_at` | DateTime | |

约束：`UNIQUE (exam_id, code)`；索引 `(exam_id, level, order_index)`。

`indicators_en` 存表现指标（第三层）但**不建模为考点**——它不可选、不可关联题目，只是打标 prompt 的输入。存 JSONB 而不是拆表，是因为除了拼 prompt 没有任何查询需求。

### `question_topics`（新表）

| 列 | 类型 | 说明 |
|---|---|---|
| `question_id` | Integer FK → `questions.id`，PK 之一，`ON DELETE CASCADE` | |
| `topic_id` | Integer FK → `exam_topics.id`，PK 之一，`ON DELETE CASCADE` | |
| `source` | String(10) NOT NULL | `ai` / `manual` |
| `created_at` | DateTime | |

复合主键 `(question_id, topic_id)`，反向索引 `(topic_id, question_id)` 供按考点选题。

`source` 是为了让重跑打标不会推翻人工修正：重跑只删除并重建 `source='ai'` 的行，`source='manual'` 的行原样保留。没有这一列的话，Q11 的人工纠错会在下一次批量打标时被静默冲掉。

**关联只打在 level=2 的能力项上**，域级不直接关联。域的题目集合 = 其下所有能力项关联题目的并集（去重）。这样做的理由是：即使 AI 把 `III.B` 判成了 `III.C`，域级展示仍然正确，域内混淆不影响本期唯一暴露的那一层；同时 level=2 的数据不是死数据，日后要放开能力项选择无需重新打标。

### `quiz_sessions` 增列

新增 `topic_id: Integer FK → exam_topics.id, NULL`。

语义约定：`mode='topic'` 且 `topic_id` 非空 = 练该考点；`mode='topic'` 且 `topic_id` 为空 = 练**未分类**题目。其他 mode 下 `topic_id` 恒为空。不为「未分类」造一行伪考点记录，避免它混进考点树的各种查询里。

## 数据流

### 灌入考点树

```
backend/app/data/topic_templates/cipt-bok-4.0.0.json   （随仓库提交）
        │
        └─ python -m backend.scripts.seed_exam_topics --exam-slug <slug>
                └─ 按 (exam_id, code) upsert，可重复执行
```

不在 Alembic 迁移里 seed（D-Q18）。`003_user_owned_exams.py:20` 确实有在迁移里写业务数据的先例（`CIPT_AI_PROFILE`），但那是一次性的历史数据搬迁；考纲是会出新版的，绑进迁移意味着每次改版都要追加一条迁移，而且无法对新建的考试项目补灌。

### AI 批量打标

```
管理员点「批量打标」
  → POST /api/admin/banks/{bank_id}/topic-tagging
      → job_service.create_or_reuse_job(JOB_TYPE_QUESTION_TOPIC_TAG, {bank_id, exam_id}, user.id)
          （active_scope_key 天然保证同题库同时只有一个打标任务在跑）
  → worker: job_handlers.run_job → handle_question_topic_tag
      → 分批取未打标题目（不存在 source='ai' 关联的）
      → ai_service.call_ai_api(messages, db, scene=...) 每批 N 题
      → 解析返回的 code 列表 → 写入 question_topics(source='ai')
      → heartbeat_job 上报进度
```

接入点已核实：
- job type 常量加在 `backend/app/services/job_service.py:22` 那一组旁边
- `count_pending_items`（`job_service.py:80`）要加一个分支，返回该题库下未打标题目数——`create_or_reuse_job` 在 `pending_total <= 0` 时会直接返回 `no_work`，这正好实现「没有待打标题目就不建任务」
- 分派表在 `job_handlers.py:35 run_job`，加一个 `if job.job_type == JOB_TYPE_QUESTION_TOPIC_TAG`
- 批处理与心跳可照抄 `handle_bank_frequent_translate`（`job_handlers.py:90`），它已经是「分批 + 每批后 heartbeat」的成熟形态

打标 prompt 的输入是全部 16 个能力项的 `code + name_en + indicators_en`。表现指标里的 `e.g.` 举例（如 II.B 的 anonymization / pseudonymization / differential privacy，III.C 的 cookies / chatbots / biometrics）是把真题归位的最强信号，必须完整给出。

输出契约：每题返回 `{"question_no": N, "codes": ["II.B", "III.C"]}`，`codes` 允许为空数组表示判不准（Q12 的「拿不准就不标」出口）。空数组不写任何关联行，该题自然落入「未分类」。返回的 code 不在该考试项目的 level=2 考点集合里就丢弃并计入 `skipped_count`，不让模型幻觉出来的编码污染数据。

### 专项练习答题

```
HomeView 题库卡片「🎯 专项练习」
  → GET /api/banks/{bank_id}/topics
      → 返回 5 个域：code / short_name_zh / blueprint_min / blueprint_max / question_count
        外加 unclassified_count
  → 用户选一个域（或「未分类」）
  → POST /api/quiz/start { bank_id, mode: "topic", topic_id }
      → quiz.py:116 start_quiz 增加 topic 分支：
         按 question_topics → exam_topics(parent_id=topic_id) 反查题目 id，随机排序，不截断
  → 落库 QuizSession(mode='topic', topic_id=...)
```

出题不设数量上限（D-Q14），未完成会话由现有「继续答题」承接（`HomeView.vue:69`）。

## 契约变更

| 端点 | 变更 |
|---|---|
| `GET /api/banks/{bank_id}/topics` | 新增。返回域列表（含蓝图配额与本库题数）与未分类题数 |
| `POST /api/quiz/start` | `QuizStartRequest` 增加 `topic_id: int \| None`；`mode` 接受 `"topic"` |
| `GET /api/quiz/history` | 每项增加 `topic_short_name: str \| None` |
| `GET /api/quiz/session/{id}` | `session` 增加 `topic_short_name` |
| `PUT /api/questions/{id}` | `QuestionUpdateRequest` 增加 `topic_ids: list[int] \| None`，写入时 `source='manual'` |
| `GET /api/banks/{bank_id}/questions` | 每题增加 `topics: [{id, code, short_name_zh}]` |
| `POST /api/jobs` | 复用既有通用任务入口，新增 `job_type="question_topic_tag"`；该类型限管理员 |
| `GET /api/jobs/active` `GET /api/jobs/{id}` | 无需改动，新任务类型自动纳入进度轮询 |

`questions.py:94 update_question` 现有的「内容变了就清空翻译和解析」逻辑（`clear_question_translation` / `clear_question_explanation`）**不扩展到考点**：题干改动不应该清掉考点关联，考点比翻译稳定得多，清掉反而要重跑打标。

## 权限

- 读考点树、开专项练习会话：`get_current_user` + `get_exam_context`，题库归属校验走 `exam_service.get_bank_in_exam_or_404`（与 `quiz.py:128` 一致）
- 触发批量打标、人工改考点：管理员，与 `admin_banks` / `questions` 现有校验一致
- 考点树按 `exam_id` 过滤，天然不跨考试项目泄漏

## 兼容与迁移

- Alembic `004_exam_topics`，`down_revision = "003"`（链见 `003_user_owned_exams.py:15`）
- 两张新表 + `quiz_sessions.topic_id` 一列，全部是新增，无破坏性变更
- 存量会话 `topic_id` 为 NULL，`mode` 不受影响；前端 `modeLabel()` 加 `topic` 键后，旧会话渲染不变
- 回滚：`downgrade()` 删两表并 drop 列即可，不丢历史答题数据

## 权衡记录

- **多对多而非单选**：真题跨域普遍，单选会逼 AI 在两个都对的答案里挑一个。代价是「某考点做对率」的分母会重叠，这在本期不展示做对率的前提下不构成问题。
- **打在能力项、界面按域分组选择能力项**：2026-09-09 从「只暴露 5 个域」放开。数据本来就打在能力项层，II 域 137 题过粗，弹窗改为按域分组列出 16 个能力项。后端仍接受域级 `topic_id`，已有整域会话可继续恢复。
- **手动触发而非导入时自动**：导入链路（解析 → 复核 → 入库）已经够长，串上 AI 批量任务会放大失败面；打标不是题目可用的前提。
- **未分类不建伪考点行**：用 `topic_id IS NULL` 表达，避免伪行混进考点树查询和蓝图统计。

## 实现期偏离设计的地方

- **打标触发端点**：原计划新开 `POST /api/admin/banks/{bank_id}/topic-tagging`。实现时发现 `app/api/routes/jobs.py` 已经是通用的任务创建 + 轮询入口（`/api/jobs`、`/api/jobs/active`、`/api/jobs/{id}`），前端还有配套的 `useBackgroundJob` composable。改为在 `VALID_JOB_TYPES` 里注册新类型，并新增 `ADMIN_ONLY_JOB_TYPES` 做权限收口，省掉一整套重复的进度轮询代码。
- **多出一个 `topic_service.py`**：设计只列了 `topic_tagging_service.py`。考点树的灌入与查询（域概览、按域选题、未分类选题、人工设定考点）被路由、脚本、任务三处共用，放在打标服务里名不副实，单独成文件。
- **`list_untagged_question_ids` 的判定条件**：设计写的是「不存在 `source='ai'` 关联的题目」。这样人工设过考点的题会被当成待打标，下一轮打标会在人工结果之上再叠加 AI 标签，与 D11 冲突。改为「不存在任何关联的题目」；要用新 prompt 重打，先清掉 `source='ai'` 的行。
- **`strip_code_fence` 由私有转公开**：`ai_service._strip_code_fence` 是解析 LLM JSON 响应的既有工具，打标同样需要。与其复制一份，不如去掉下划线前缀（3 处内部调用同步改名）。
- **`GET /api/banks/{bank_id}/topics` 额外返回 `competencies`**：管理端人工设定考点需要 16 个能力项的列表，复用同一端点比新开一个省事。2026-09-09 起每个域还嵌套 `competencies`（含题数与配额），专项练习弹窗按域分组选能力项。
- **前端多改了 `AdminQuestionsView.vue`**：R4 要求管理员能改单题考点，执行计划的第 5 段漏列了这个页面。补上了考点展示、编辑弹窗里的能力项多选，以及「批量打标」按钮与进度显示。
- **`modeLabel` 抽成共享工具**：`HomeView.vue` 有一份映射表，`HistoryView.vue` 有一段三元表达式且漏了 `exam`。新增 `frontend/src/utils/quizMode.js` 统一，顺带修好了历史页把模拟考试显示成「错题练习」的老问题。

## 质量检查阶段修掉的缺陷

- **打标 prompt 的考纲顺序被打散**：`order_index` 在每个域内都从 1 重新开始，只按它排序会把 16 个能力项串成 `I.A → II.A → III.A → …`，域分组这一最强的归类信号消失，且同值之间没有 tie-breaker，每次重跑的 prompt 都可能不同。改为先按父域序、再按域内序、最后以 `code` 兜底。发现时首轮 282 题已在乱序 prompt 下打完标，已清空 `source='ai'` 的行重跑。
- **编辑题干会把 AI 标签静默转成人工修正**：管理端保存时无条件带上 `topic_ids`，而 `set_question_topics_manually` 无条件删光重建为 `manual`。改成考点集合未变时直接返回、保留原 `source`，否则「清空 AI 标签重打」这条回滚路径会逐渐失效。
- **`list_unclassified_question_ids` 与 `list_untagged_question_ids` 是同一条 SQL**：两个领域词汇保留，实现合并为一份。
- **答题历史的 N+1**：`bank` 和 `topic` 都是懒加载，`per_page=100` 时最坏多出上百次单行查询，加 `joinedload`。
- **重试会重复处理「AI 判不准」的题**：这些题没有关联行，无法与「从没处理过」区分，重试时会被再次提交给 AI 并二次计数，`progress_done` 超出实际题数。改为每次尝试开始时把计数归零、`progress_total` 重设为当次快照大小。
- **租约窗口不足**：单批 AI 调用最长 120s，租约 180s，而续租只发生在批次结束后。慢响应时任务可能被另一个 worker 判为陈旧抢走并重复打标。改为批次开始前也续一次租约。

## 迁移撞号（合并 main 时发现）

本分支的 `exam_topics` 迁移原本编号 004，而 main 上已有 `004_structured_explanation_prompt`，两者都 `revises 003`。git 合并干净，但 alembic 会出现两个 head，`upgrade head` 直接失败。已改号为 005 并 revises 004。

**已执行过旧 004 的数据库需要手工修版本记录**，否则 main 的 004 会因版本号相同被当成已执行而永远跳过（实测 CIPT 项目的解析 prompt 一直停在旧版）：

```bash
alembic stamp 003      # 退回到两个 004 之前
alembic upgrade 004    # 跑 main 的解析 prompt 数据迁移
alembic stamp 005      # 本分支的表结构已存在，只补记录，不重跑
```

教训：**不要在生产库上跑 `downgrade` 做往返验证**。005 的 downgrade 会 drop `exam_topics` 和 `question_topics`，一次这样的验证清掉了已灌入的 21 条考点和 269 条打标关联，考点树能用脚本重灌，打标关联只能重跑 AI。往返验证应该在一次性的临时库上做。

## 部署注意

新增 job type 后，**必须重启 worker 服务**（`sudo systemctl restart quiz-app-worker`），否则运行中的旧 worker 会认领任务并抛「不支持的任务类型」，重试三次后把任务判死。实测过这个失败路径。

## 未决/已知风险

- 283 题一次性打标的耗时与 API 成本未实测。缓解：分批 + 心跳上报，任务可中断续跑；`max_attempts` 默认 3（`background_job.py`）。
- 打标准确率无自动化验收手段，只能人工抽样。缓解是 Q11 的人工修正入口 + `source` 列保证重跑不覆盖。
- `backend/tests/` 有 8 个已跟踪测试，但**没有 conftest.py、没有 pytest 配置**，全部是不连数据库的纯单元测试（见 `test_quiz_resume_index.py:1` 的 `sys.path` 写法）。新增测试沿用这一形态，只覆盖可纯函数化的逻辑（打标响应解析、按考点选题的 id 计算）。
- `CLAUDE.md` 声称「没有测试框架和 lint 工具配置」，与 `backend/tests/` 的现状不符，属文档过期，不在本任务修正。
