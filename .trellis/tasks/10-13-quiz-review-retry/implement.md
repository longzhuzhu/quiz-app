# 执行计划：答题复盘与原题重做

规格见 `docs/plans/2026-10-13-quiz-review-retry-design.md`；技术设计见本任务 `design.md`；现状调查见 `research/current-implementation.md`。

**父子结构不是依赖系统。** 本文件描述父任务层面的集成顺序与最终验收；每个子任务在自己的 `implement.md` 里写明前置依赖与自己的验证命令。

## 0. 开始前检查

```bash
git branch --show-current        # 期望 feat/quiz-review-retry
git log --oneline -1             # 基于 origin/main 的提交
python3 ./.trellis/scripts/task.py current
ls backend/alembic/versions/     # 确认 head 仍为 011；若已有 012 则顺延编号
```

- 确认工作区没有他人正在修改 `backend/app/api/routes/quiz.py`、`backend/app/models/quiz.py`、`frontend/src/views/QuizResultView.vue`。
- 若 `.trellis/spec/` 或 `CONTEXT.md` 在规划后被改动，先重读相关章节。

## 1. 任务顺序与依赖

```
snapshot-model ──┬─→ review-api ──┬─→ review-ui
                 │                └─→ result-page
                 └─→ retry-api ───────┘（result-page 的「再来一次」依赖）
```

| 顺序 | 子任务 | 前置条件 | 完成后必须成立 |
| --- | --- | --- | --- |
| 1 | `10-13-snapshot-model` | 无 | `alembic upgrade head` 实际执行通过；新会话写入完整快照 |
| 2 | `10-13-review-api` | 快照列已存在 | 已完成模拟释放对错；进行中仍隐藏；`C+E+U=T` 口径生效 |
| 3 | `10-13-retry-api` | 快照列已存在 | 原题原序重开；任一题不可用整场失败 |
| 4 | `10-13-review-ui` | review-api 响应契约冻结 | 只读复盘页可跑通全部四种筛选 |
| 5 | `10-13-result-page` | review-api 与 retry-api 已可用 | 完成页四入口与统计口径正确 |

`review-ui` 与 `result-page` 都在前端且都触及答题相关视图。若并行推进，必须先约定 `stores/quiz.js` 与 `utils/examRoutes.js` 的改动归属：建议 `result-page` 拥有 store 改动，`review-ui` 只新增页面与组件。

**不要启动父任务。** 父任务只在最后做集成审查时使用；实施从 `10-13-snapshot-model` 开始。

## 2. 集成风险与门禁

### 2.1 最大回归风险：`session_detail` 是双消费方接口

`GET /quiz/session/{id}` 同时服务：

- `QuizView.vue:269` 的刷新恢复（依赖 `questions` 与 `resume_index`）
- `QuizResultView.vue:120` 的结果页

改响应契约时，两处必须同步。检查阶段必须以**真实浏览器**覆盖：

1. 未完成会话刷新 → 仍能恢复答题与进度。
2. 已完成会话打开结果页 → 不白屏，统计正确。

### 2.2 模拟考试隔离不得被绕过

新增复盘分支后，进行中模拟会话的响应必须仍然不含 `is_correct`、`correct_answer`、解析与可推导成绩的统计。任何新增字段都要过一遍「进行中是否会泄露」的判断。

### 2.3 第二个快照写入入口容易漏

`/quiz/start` 与 `/wrong/practice` 都要写快照。跨题库错题会话不能只查 `first_bank_id`。

### 2.4 迁移必须真跑

新增迁移后执行 `alembic upgrade head`，不能只检查 import。同时确认 `downgrade` 可用。

## 3. 子任务验收清单

每个子任务完成时，自己的 `implement.md` 应包含该子任务的最小验证命令。父任务层面要求下列证据在归档前齐备：

- [ ] `alembic upgrade head` 与 `alembic downgrade -1` 均执行成功（快照任务）。
- [ ] 后端新增测试全部通过，且既有回归未破坏：
  - `test_quiz_answer_duration.py`（模拟过程不泄露答案、已完成拒绝提交）
  - `test_quiz_resume_index.py`、`test_quiz_history_order.py`
  - `test_correct_answer.py`、`test_topic_question_selection.py`、`test_practice_day.py`
- [ ] 全量后端回归通过：`python3 backend/tests/run_isolated_suite.py`
- [ ] 前端构建通过：`cd frontend && npm run build`
- [ ] 前端测试通过：`cd frontend && npm test`
- [ ] 端到端场景（真实浏览器 + 隔离 PostgreSQL）覆盖第 5 节全部场景。

## 4. 集成验收（父任务收口）

按 `prd.md` 的验收清单逐条在真实浏览器中执行。**其中三条是 Issue #63 的原始症状，必须优先验证：**

1. 模拟 10 题，7 对 3 错后结束 → 完成页 70%，复盘区分 7 对 3 错，正确答案不为空。（原症状：全部显示错误）
2. 模拟未结束 → 直接访问复盘入口不能提前看到答案与对错。（隔离不能破）
3. 10 题只答 2 题全对 → 普通 100%、模拟 20%，均为 2 对 0 错 8 未答。（新统计口径）

其余场景：跳题改答、只读无操作按钮、桌面手机与长题干、完成后改题/删题、跨题库重做、越权拒绝、清空历史与删除项目。

**验收不通过时**：不修补测试、不放宽断言。回到对应子任务修改实现，必要时回退到规划阶段修 `design.md`。

## 5. 端到端场景（真实浏览器 + 隔离 PostgreSQL）

复用 `frontend/tests/helpers/studyBrowser.js` 与 `studyBackend.js` 的既有链路（参考 `frontend/tests/vocabularyStudyE2E.test.js` 的写法）。

| 场景 | 必须满足 |
| --- | --- |
| 模拟 10 题 7 对 3 错结束 | 完成页 70%；复盘 7 对 3 错；正确答案非空 |
| 未结束模拟直访问复盘 | 不能查看答案、对错或成绩 |
| 10 题只答 2 题全对 | 普通 100% / 模拟 20%；2 对 0 错 8 未答 |
| 零答案结束 | 不崩溃；0%；全部未答；本次错题为空 |
| 跳题、改答、错误筛选 | 最终成功提交结果；原场题号；未答不入错误筛选 |
| 完成页与历史入口 | 同一题目与统计口径；只读、无提交/完成/更正按钮 |
| 桌面与手机、长英文题干、多选题 | 完整可读；导航可用；最终选择与当场正确答案可区分 |
| 完成后改题干/选项/正确答案 | 有快照的会话内容与成绩不变；旧会话显示兼容提示 |
| 删除原题后复盘与重做 | 有快照可复盘；旧记录显示占位；重做整场失败且无部分会话 |
| 原场有额外题/漏答/考点成员已变 | 新场 ID、顺序、模式、题数与原场一致 |
| 跨题库错题重做 | 保留所有原题；已掌握原题不剔除 |
| 新场首次加载与刷新 | 答案与进度不继承原场 |
| 越权与跨项目 | 拒绝访问，不返回题目、快照或新会话 |
| 清空历史 / 删除项目 | 快照同步删除；首页统计与既有规则一致 |

## 6. 提交与回滚点

- 每个子任务独立提交，提交信息说明该子任务交付物与验证命令。
- 快照迁移与应用代码建议同一提交，便于整体回滚。
- 回滚点：`012` 迁移之前；以及每个子任务合并前。
- 回滚方式：应用回滚到上一版即停止写快照（列保留无害）；彻底回滚执行 `alembic downgrade 011`。

## 7. 风险文件与禁止顺手改动

**高风险文件（改动必须四层同步、必须跑浏览器回归）：**

- `backend/app/api/routes/quiz.py`（`session_detail` 双消费方）
- `backend/app/models/quiz.py` + 新迁移
- `frontend/src/views/QuizView.vue`（刷新恢复）
- `frontend/src/views/QuizResultView.vue`
- `frontend/src/stores/quiz.js`
- `backend/app/api/routes/wrong.py` + `backend/app/models/wrong.py`（错题证据列）

**禁止顺手改动：**

- 首页 `recent-accuracy`、练习日、当日作答量、滚动正确率口径（`practice_service.py`）。
- `docs/adr/0002-exam-project-deletion.md` 的删除边界。
- `QuestionCard.vue` 的答题与错题练习复用路径；不给它加只读模式。
- 导入流水线、词汇学习、AI 解析生成链路。
- 与 Issue #63 无关的重构、格式化、命名调整。
