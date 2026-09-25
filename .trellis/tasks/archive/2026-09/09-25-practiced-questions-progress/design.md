# Design — 已刷题目进度

## 数据流

```
HomeView.vue ── GET /quiz/practiced-summary ──> quiz.py 路由
                                                  └─> practice_service.practiced_questions_for(db, user_id, exam_id)
                                                        └─> COUNT(DISTINCT quiz_answers.question_id)
                                                            JOIN quiz_sessions ON answers.session_id = sessions.id
                                                            JOIN question_banks ON sessions.bank_id = banks.id
                                                            WHERE sessions.user_id = :uid AND banks.exam_id = :exam_id
```

## 后端

- `backend/app/services/practice_service.py` 新增 `practiced_questions_for(db, user_id, exam_id) -> int`：
  - 查询形态对齐同文件 `recent_accuracy_for()`（L142–179）的联表过滤模式：`db.query(func.count(distinct(QuizAnswer.question_id))).join(...)`，`.scalar() or 0`。
  - 不引入新表、不加迁移、不加缓存。
- `backend/app/api/routes/quiz.py` 新增路由，紧跟 `recent-accuracy`（L490）之后：
  ```python
  @router.get("/practiced-summary")
  def practiced_summary(
      current_user: User = Depends(get_current_user),
      exam: Exam = Depends(get_exam_context),
      db: Session = Depends(get_db),
  ):
      return {"practiced_questions": practiced_questions_for(db, current_user.id, exam.id)}
  ```

### 语义对齐（领域规则，来源 CONTEXT.md）

- 清空答题历史：`DELETE /quiz/history` 删会话 → `answers` 级联删除（`models/quiz.py:42` cascade）→ 本统计自动归零，无需改 `clear_history`。
- 改答：同会话同题 `quiz_answers` 仅一行（唯一约束 session_id+question_id），`COUNT(DISTINCT question_id)` 天然去重。
- 更正答案：只改 `questions.correct_answer`，不动作答记录，不影响已刷。
- 考试项目隔离：exam 过滤发生在 `question_banks.exam_id`，与首页其余 3 卡同口径。
- 进度不超过 100%：已答过的题受 FK 约束不会从题库静默消失（`quiz_answers.question_id` FK 无 ondelete，删除被数据库拒绝）。

## 前端（frontend/src/views/HomeView.vue）

- `fetchDashboardData()` 的 `Promise.allSettled` 增加一路 `apiClient.get("/quiz/practiced-summary")`，落到新 ref `practicedQuestions`（默认 0，失败不阻塞其它卡）。
- 总题目卡（L25–37）：
  - 主数值行不变：`{{ totalQuestions }}`。
  - 副行改为 `总题目 · 已刷 {{ practicedQuestions }} · {{ practicedPercent }}%`（保留卡片标题「总题目」，避免主数值失去指代）。
  - 卡片内容底部加进度条：
    ```html
    <div class="mt-2 h-1.5 w-full rounded-full bg-slate-100 dark:bg-slate-700 overflow-hidden">
      <div class="h-full rounded-full bg-sky-500" :style="{ width: practicedPercent + '%' }"></div>
    </div>
    ```
  - computed：`practicedPercent = totalQuestions > 0 ? Math.min(100, Math.round(practicedQuestions / totalQuestions * 100)) : 0`。
  - 配色沿用该卡 sky 色系（顶部色条 `bg-sky-500`），进度条同色；暗色模式用现有 `dark:` 变体。

## CONTEXT.md 术语

Language 区追加（置于「当日作答量」之后，语义相邻）：

> **已刷题目**:
> 当前考试项目里存在至少一条作答记录的不重复题目数；同一题无论跨多少场、改答几次只计 1。与「总题目」相除构成首页的刷题覆盖率。
> _Avoid_: 作答次数、做题量、刷题量、掌握题数

Relationships 区追加：

- 首页**总题目**卡片同屏展示**总题目**与**已刷题目**，进度条按二者之比显示覆盖率。
- **已刷题目**只统计仍存在的作答记录；清空答题历史后归零。
- **已刷题目**是去重覆盖数，不是**当日作答量**的累计，也不是作答次数。

## 兼容与回滚

- 纯新增端点 + 纯前端展示增强，无 schema 变更、无破坏性 API 变更；回滚 = revert 提交即可。
- 端点对无作答用户返回 0，对只读管理员同样可用（走 `get_exam_context` 既有规则）。
