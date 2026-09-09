# 专项练习：按 CIPT 考点分类答题

## Goal

用户在题库上除了顺序练习、随机练习、模拟考试之外，还能选定一个 CIPT 考点，只练该考点下的题目，从而针对薄弱考点集中突破，并依据官方考试出题配额判断该先攻哪个考点。

## Background

### 当前状态（已核实）

- 答题模式定义在 `backend/app/models/quiz.py:22`，现有四种：`sequential` / `random` / `exam` / `wrong_practice`；前端标签映射在 `frontend/src/views/HomeView.vue:208`。
- `questions` 表（`backend/app/models/question.py:12`）**没有任何标签、考点、分类字段**。
- 题库入口按钮在 `frontend/src/views/HomeView.vue:107-119`，每张题库卡片上并排放着「继续答题 / 顺序练习 / 随机练习 / 模拟考试」。
- 开始答题的后端逻辑在 `backend/app/api/routes/quiz.py:116`，按 `mode` 决定排序，`question_count` 决定截断。
- 题库归属考试项目，考试项目为用户私有隔离边界（`CONTEXT.md`），权限校验走 `app.services.exam_service.get_bank_in_exam_or_404`。
- 已有可复用的后台任务框架（`background_jobs` 表 + `job_service` + `job_handlers` + worker）与 AI 调用封装（`ai_service.call_ai_api`）。
- 迁移使用 Alembic，当前 head 为 `003_user_owned_exams`。

### 考点大纲来源（已核实）

权威来源是 `reference/IAPP_CIPT_BOK_3Dec2025-FINAL.pdf`，内容版本为 **BOK 4.0.0**（2025-09-01 生效，明确 supersedes 3.2.0）。完整分类树已抽取到 [`research/bok-4.0.0-taxonomy.md`](./research/bok-4.0.0-taxonomy.md)。

结构为 **5 个域 / 16 个能力项**，每项带考试出题配额（MIN–MAX）：

| 域 | 配额 | 能力项数 |
|---|---|---|
| I. The privacy technologist's role in the context of the organization | 15–19 | 4（I.A–I.D） |
| II. Data collection, use, dissemination and destruction | 19–23 | 3（II.A–II.C） |
| III. Privacy risk management | 17–21 | 5（III.A–III.E） |
| IV. Privacy by design | 7–9 | 2（IV.A–IV.B） |
| V. Privacy engineering and privacy governance | 9–11 | 2（V.A–V.B） |

`reference/CIPT-BOK-Supplement/README.md` 对应的是**已废止的 3.2.0**（七个域），4.0.0 是结构性改版，两者的域无法一一映射。该文件已在顶部加注版本警示，只保留「延伸阅读链接」的素材价值，不作为分类树来源。

教材 `reference/An Introduction to Privacy for Technology Professionals.pdf`（本次上传）是 BOK 引用的参考书，**不作为分类树来源**，仅作为考点释义与后续「延伸阅读」的证据来源。

## Key Decisions

| # | 决策 | 结论 |
|---|---|---|
| D1 | 功能命名 | 「专项练习」，与现有四字模式并列；「专题练习」列为 Avoid 词，已写入 `CONTEXT.md` |
| D2 | 分类项命名 | 「考点」，非「标签」——它是 BOK 大纲的固定条目，不是用户自由输入的 tag |
| D3 | 参考资料目录 | 沿用仓库既有的 `reference/`（单数），教材 PDF 已放入并随仓库提交 |
| D4 | 分类来源 | BOK **4.0.0** 原件，不用已废止的 3.2.0 supplement，也不用教材章节目录 |
| D5 | 层级 | 数据模型存两层（5 域 + 16 能力项）；AI 打标打在能力项层；**界面按域分组、选择能力项**（2026-09-09 从「只暴露 5 个域」修订：域粒度对 II 域 137 题过粗） |
| D6 | 归属 | 考点归属考试项目（`exam_id`），不是全局也不是题库级 |
| D7 | 题目与考点关系 | 多对多，一道题可挂多个考点 |
| D8 | 答题模式 | 新增 `mode="topic"`，会话上记录所选考点，历史记录中可辨识 |
| D9 | 练习范围 | MVP 限定单题库，复用 `QuizSession.bank_id` |
| D10 | 打标方式 | AI 批量自动打标 |
| D11 | 人工纠错 | 不做复核队列；管理员可在题目管理页改单题考点，重跑打标不覆盖人工修正 |
| D12 | 打不准的题 | 允许零考点，AI「拿不准就不标」；这些题归入「未分类」入口，可练 |
| D13 | 考点选择 | 一次专项练习只选一个考点 |
| D14 | 出题量与顺序 | 默认练该考点下全部题目，随机序，不弹数量输入框 |
| D15 | 入口形态 | 题库卡片加按钮 + 弹窗选考点，与「模拟考试」交互一致；本期不展示做对率 |
| D16 | 新题打标时机 | 不在导入链路自动触发；管理员在题库上手动点「批量打标」 |
| D17 | 考点名称语言 | 三份并存：英文原名（打标 prompt 与溯源）、中文全称、中文短名（窄空间） |
| D18 | 蓝图配额 | 展示。弹窗每项写「域短名 · 考试占 X–Y 题 · 本库 N 题」 |
| D19 | 考点树供给 | 仓库内模板文件 + 幂等脚本对指定考试项目灌入，不在 Alembic 迁移里 seed |

## Requirements

- **R1 考点分类树**：以 BOK 4.0.0 为准建立两层考点树（5 域 / 16 能力项），含中英名称、考试出题配额与表现指标原文，随考试项目存在，可通过可重复执行的脚本对指定考试项目灌入。
- **R2 题目—考点关联**：题目与考点为多对多，关联打在能力项层，并区分 AI 打标与人工修正两种来源。
- **R3 AI 批量打标**：管理员可在题库上手动触发批量打标任务，任务复用现有后台任务框架，可续跑、可重跑；判不准的题不强行归类。
- **R4 人工纠错**：管理员可在题目管理页修改单题的考点；重跑批量打标不覆盖人工修正。
- **R5 专项练习入口**：题库卡片提供「专项练习」按钮，弹窗按 5 个域分组列出 16 个能力项及「未分类」，每项显示考试出题配额与本库题数，题数为 0 的项不可选。
- **R6 专项练习会话**：选定能力项后开始一次 `mode="topic"` 的会话，题目为该能力项关联题目，随机序，不限数量。后端仍接受域级 `topic_id`，以兼容已有的整域会话。
- **R7 会话可辨识**：专项练习会话在答题历史与「继续答题」入口中显示所练考点名称。

## Acceptance Criteria

- [ ] AC1：对存量 CIPT 考试项目执行灌入脚本后，该项目下存在 21 行考点（5 个 `level=1` + 16 个 `level=2`），`code` 与配额逐条匹配 `research/bok-4.0.0-taxonomy.md`；重复执行不产生重复行。
- [ ] AC2：其他考试项目在未执行灌入前查不到任何考点，考点不跨考试项目可见。
- [ ] AC3：对 283 题题库触发批量打标后任务跑完，`background_jobs` 行状态为完成，`progress_done` 等于待打标题数；题目获得的关联全部落在该考试项目的 `level=2` 考点上。
- [ ] AC4：AI 返回不在考点树内的编码时，该编码被丢弃、不产生关联行，并以 WARNING 记录原始编码。（原验收写的是「计入 `skipped_count`」，实现时发现 `skipped_count` 是按题计数、参与 `progress_done = success_count + skipped_count` 的勾稽，把编码级丢弃计入会破坏进度；一道题的编码若全部非法，它作为未归类题仍计入 `skipped_count`。）
- [ ] AC5：管理员改过考点的题目，在重跑批量打标后仍保留人工设定的考点。
- [ ] AC6：`GET /api/banks/{bank_id}/topics` 返回 5 个域，每项含 `blueprint_min` / `blueprint_max` / `question_count` 以及嵌套的 `competencies`（含题数与配额），另含 `unclassified_count`；「至少有一个考点的题数 + unclassified_count」等于题库总题数。
- [ ] AC7：选定某能力项开始练习后，会话内每道题都关联该能力项，且题目不重复。
- [ ] AC8：选定「未分类」开始练习后，会话内每道题都没有任何考点关联。
- [ ] AC9：专项练习中途退出后，首页「继续答题」能回到该会话，且卡片上显示的模式为「专项练习」并带考点名称。
- [ ] AC10：答题历史列表中，专项练习会话与顺序/随机/模拟考试会话可区分，并显示所练考点名称。
- [ ] AC11：存量的非专项会话在前端渲染不受影响，模式标签与改动前一致。
- [ ] AC12：`alembic downgrade 003` 后再 `upgrade head` 可正常完成，存量答题数据不丢失。

## Out of Scope

- 跨题库、跨考试项目的整个考点练习（D9）
- 按考点展示做对率 / 掌握度（D15）
- 导入链路结束后自动触发打标（D16）
- 新建考试项目时从模板列表选考点树的引导流程（D19 的终态，需改 `FirstTimeOnboarding.vue`）
- 按官方蓝图配额抽题的模拟考试（有了配额数据后才成为可能，本期只落数据不做功能）
- 按教材章节的「延伸阅读」推荐
- 修正 `CLAUDE.md` 中「没有测试框架」的过期表述

## Technical Notes

技术设计见 [`design.md`](./design.md)，执行计划见 [`implement.md`](./implement.md)。

两处需要留意的既有事实：

- `backend/tests/` 有 8 个已跟踪测试，但没有 conftest.py、没有 pytest 配置，全部是不连数据库的纯单元测试。新增测试沿用这一形态。
- `003_user_owned_exams.py:20` 有在迁移里写业务数据的先例，但那是一次性历史搬迁；本任务的考点树走模板文件 + 脚本（D19）。
