# 用户题目累计答题次数设计

## 概要

本设计为答题系统补充“按当前用户、按题目、跨会话累计的答题次数”能力。

目标是在不改变现有答题流程、会话统计和错题本逻辑的前提下：

- 记录同一用户对同一题目的累计答题次数
- 同一会话内重复提交同一题目时不重复计数
- 在进入答题页面时返回每道题的当前累计次数
- 在答题页面顶部展示“已答 X 次”

本设计优先保证数据边界清晰、对现有逻辑侵入小、接口语义稳定，并与当前项目已有的“按用户记录状态”的建模方式保持一致。

## 背景与现状

当前答题主流程位于 [backend/routes/quiz.py](/home/ubuntu/github/quiz-app/backend/routes/quiz.py)，题目卡片与答题页位于 [frontend/src/components/QuestionCard.vue](/home/ubuntu/github/quiz-app/frontend/src/components/QuestionCard.vue) 和 [frontend/src/views/QuizView.vue](/home/ubuntu/github/quiz-app/frontend/src/views/QuizView.vue)。

当前实现特点：

- `QuizSession` 记录一次答题会话的总题数、已答数、正确数和完成状态
- `QuizAnswer` 通过唯一约束 `session_id + question_id`，保证一个会话内同一道题只保留一条答案记录
- 用户在同一会话内重新提交同一道题时，会覆盖原答案，但不会新增第二条 `QuizAnswer`
- `WrongAnswer` 用于累计错题次数，但只覆盖“答错次数”，不表示“总共答过几次”
- 进入答题页的题目列表接口目前不会返回“当前用户历史上答过该题多少次”

额外约束：

- 当前项目没有正式数据库迁移体系，数据库结构通过 `db.create_all()` 和运行时 schema ensure 维护
- 需求明确要求统计口径为“同一用户 + 同一题目 + 跨所有会话累计”
- 同一会话内重复提交不应重复计数
- 展示位置限定在进入题目页面后的题目卡片顶部

## 目标

### 功能目标

1. 对每个用户、每道题目记录累计答题次数
2. 仅在某题于某会话中首次提交时增加一次计数
3. `POST /api/quiz/start` 返回题目列表时包含当前用户的累计次数
4. `POST /api/wrong/practice` 返回题目列表时包含当前用户的累计次数
5. `GET /api/quiz/session/<session_id>` 恢复会话时包含当前用户的累计次数
6. `POST /api/quiz/answer` 提交答案后返回最新累计次数
7. 前端在 `QuestionCard` 顶部展示“已答 X 次”

### 设计目标

1. 会话答案记录与跨会话累计统计职责分离
2. 不通过运行时聚合历史记录来计算次数，避免接口复杂化
3. 对现有答题、错题、历史记录逻辑保持兼容
4. 改动范围聚焦在答题域，不扩散到无关页面

## 非目标

本次不包含以下范围：

- 回填历史会话数据，旧数据默认从 `0` 开始
- 在历史记录页、错题本页、题目管理页展示累计答题次数
- 区分顺序练习、随机练习、错题练习、模拟考试的不同计数策略
- 记录“答对次数”“答错次数”“正确率”等更细粒度个人题目统计
- 新增后台报表或管理员统计能力

## 数据模型设计

### 1. `user_question_stats`

用途：记录当前用户对某道题目的跨会话累计答题次数。

字段：

- `id`
- `user_id`
- `question_id`
- `answer_count`，默认 `0`
- `first_answered_at`，首次被计入次数的时间
- `last_answered_at`，最近一次被计入次数的时间
- `created_at`
- `updated_at`

约束与索引：

- 唯一约束：`user_id + question_id`
- 索引：`user_id + question_id`

说明：

- 该表不存储用户在某次会话里选择了什么答案
- 该表只存储“这个用户历史上答过这题多少次”
- 同一道题可被不同用户分别累计不同次数

### 2. 与现有表的职责边界

- `QuizSession`：表示一次答题会话的整体统计
- `QuizAnswer`：表示某会话里某题当前保存的最终答案
- `WrongAnswer`：表示某用户对某题累计答错次数
- `UserQuestionStat`：表示某用户对某题累计答题次数

这样可以避免把“会话内最终答案”和“跨会话累计次数”混在同一张表里。

## 计数规则

### 1. 计数口径

仅在以下条件同时满足时，`answer_count + 1`：

- 当前请求命中 `POST /api/quiz/answer`
- 当前用户对该题在当前会话中尚无 `QuizAnswer` 记录

换言之：

- 同一用户在新会话中第一次提交该题：计数 `+1`
- 同一会话里改答案、重复提交：不计数
- 答对和答错都计入“答过一次”
- 跨会话重新遇到该题并首次提交时：再次计数 `+1`

### 2. 时间字段语义

- 首次创建统计记录时：同时写入 `first_answered_at` 和 `last_answered_at`
- 后续新会话首次作答该题时：仅更新 `last_answered_at`
- 同一会话重复提交时：不更新上述统计时间字段

## 数据流设计

### 1. 开始普通答题：`POST /api/quiz/start`

行为：

1. 按现有逻辑生成 `QuizSession`
2. 查询本次题目列表对应的当前用户统计记录
3. 为每道题补充字段 `user_answer_count`
4. 返回给前端

返回字段示例：

```json
{
  "id": 101,
  "question_type": "single",
  "content": "...",
  "options": [],
  "user_answer_count": 3
}
```

### 2. 开始错题练习：`POST /api/wrong/practice`

行为：

1. 按现有逻辑生成 `QuizSession`
2. 为保证答题提交校验一致，补齐 `question_ids`
3. 查询错题列表对应的当前用户统计记录
4. 为每道题补充 `user_answer_count`

说明：

- 当前 `POST /api/quiz/answer` 会校验题目必须属于 `session.question_ids`
- 因此 `wrong_practice` 返回的会话也应补齐 `question_ids`，使错题练习与普通练习共享同一会话边界语义

### 3. 恢复答题会话：`GET /api/quiz/session/<session_id>`

行为：

1. 维持现有会话恢复逻辑
2. 在返回的 `questions` 列表中为每道题补充 `user_answer_count`
3. 保证刷新页面前后次数展示一致

### 4. 提交答案：`POST /api/quiz/answer`

行为分支：

#### 分支 A：当前会话首次提交该题

- 创建 `QuizAnswer`
- 更新 `QuizSession.answered_count` / `correct_count`
- 按现有逻辑维护 `WrongAnswer`
- 创建或更新 `UserQuestionStat`
  - 不存在则创建，`answer_count = 1`
  - 存在则 `answer_count += 1`
- 返回最新 `user_answer_count`
- 返回 `counted_as_new_attempt = true`

#### 分支 B：当前会话重复提交该题

- 更新已有 `QuizAnswer`
- 按现有逻辑修正 `QuizSession.correct_count`
- 继续按现有逻辑维护 `WrongAnswer`
- 不更新 `UserQuestionStat.answer_count`
- 返回当前 `user_answer_count`
- 返回 `counted_as_new_attempt = false`

## API 设计

### 题目列表统一新增字段

以下接口返回的每道题对象统一新增：

- `user_answer_count`

适用接口：

- `POST /api/quiz/start`
- `POST /api/wrong/practice`
- `GET /api/quiz/session/<session_id>` 中的 `questions`

字段语义：

- `0`：当前用户历史上尚未被计入过该题
- `N`：当前用户历史上已被计入该题 `N` 次

### 提交答案接口新增返回字段

`POST /api/quiz/answer` 在现有响应基础上新增：

- `user_answer_count`
- `counted_as_new_attempt`

非模拟考试模式示例：

```json
{
  "is_correct": false,
  "correct_answer": "B",
  "explanation": "...",
  "explanation_zh": "...",
  "user_answer_count": 4,
  "counted_as_new_attempt": true
}
```

模拟考试模式示例：

```json
{
  "submitted": true,
  "user_answer_count": 4,
  "counted_as_new_attempt": true
}
```

说明：

- 即使是模拟考试模式，也可以返回累计答题次数，因为该信息不泄露正确答案
- 前端应以后端返回的 `user_answer_count` 为准，不自行猜测是否加一

## 前端展示设计

### 展示位置

展示于 `QuestionCard` 顶部，与“第 N 题”同一行。

推荐展示结构：

- 左侧：`第 3 / 20 题`
- 右侧：`已答 5 次` + 题型标签

当次数为 `0` 时也显示：

- `已答 0 次`

这样可避免用户误以为字段未加载。

### 页面状态更新

进入答题页时：

- `quizStore.questions` 中每个题目对象带上 `user_answer_count`

提交答案成功后：

- 将当前题的 `user_answer_count` 更新为后端返回值
- 不依赖前端自行判断是否为首次提交

刷新恢复时：

- 从 `GET /api/quiz/session/<session_id>` 返回值重新填充 `user_answer_count`

## 兼容性与实现边界

### 1. 数据库兼容策略

沿用当前项目 schema ensure 模式：

- 应用启动时检查 `user_question_stats` 表是否存在
- 不存在则自动创建

不额外引入迁移框架。

### 2. 对现有逻辑的影响

本次不改变以下语义：

- `QuizSession.answered_count` 仍表示当前会话已答题数
- `QuizSession.correct_count` 仍表示当前会话答对数
- `QuizAnswer` 仍只保留当前会话该题的最终答案
- `WrongAnswer.wrong_count` 仍只统计答错次数

新增统计属于旁路写入，不替代现有字段。

### 3. 最小改动范围

建议改动文件：

- [backend/models.py](/home/ubuntu/github/quiz-app/backend/models.py)
- [backend/app.py](/home/ubuntu/github/quiz-app/backend/app.py)
- [backend/routes/quiz.py](/home/ubuntu/github/quiz-app/backend/routes/quiz.py)
- [backend/routes/wrong.py](/home/ubuntu/github/quiz-app/backend/routes/wrong.py)
- [frontend/src/components/QuestionCard.vue](/home/ubuntu/github/quiz-app/frontend/src/components/QuestionCard.vue)
- [frontend/src/views/QuizView.vue](/home/ubuntu/github/quiz-app/frontend/src/views/QuizView.vue)

## 错误处理

- 若会话不存在或无权限，继续沿用现有 404 / 403 逻辑
- 若题目不属于当前会话，继续沿用现有 400 逻辑
- 若统计记录查询不到，按 `0` 返回，不作为错误
- 若首次计数时统计记录不存在，应自动创建，不要求前置初始化

## 测试与验证建议

### 后端

1. 用户首次在会话中提交某题，`user_answer_count` 从 `0` 变为 `1`
2. 同一会话重复提交同一题，`user_answer_count` 保持不变
3. 新开第二个会话再次提交同一题，`user_answer_count` 再次 `+1`
4. 错题练习入口返回题目时包含 `user_answer_count`
5. 刷新恢复会话时返回题目包含 `user_answer_count`
6. 模拟考试模式提交后也返回 `user_answer_count`

### 前端

1. 进入答题页后顶部显示 `已答 X 次`
2. 首次提交后，无需刷新即可看到次数更新
3. 同一题重复提交时次数不继续增加
4. 刷新页面恢复会话后，显示次数与后端一致

## 实施顺序建议

1. 新增 `UserQuestionStat` 模型
2. 在 `backend/app.py` 增加 schema ensure
3. 在答题与错题练习接口中补齐 `user_answer_count`
4. 在提交答案逻辑中维护计数并返回新字段
5. 前端题目卡片展示次数
6. 前端提交后回写最新次数
7. 手工验证普通练习、错题练习、刷新恢复、模拟考试四条路径

## 结论

本方案采用“独立用户题目统计表”的路线：

- `QuizAnswer` 负责会话内最终答案
- `UserQuestionStat` 负责跨会话累计答题次数
- 题目列表接口负责把当前用户的累计次数带到前端
- 提交接口负责在首次作答时原子更新统计并回传最新值

这样可以在不扰动现有答题结构的前提下，稳定实现“记录并展示每道题目用户累计答题次数”的需求，并为后续扩展个人题目学习统计保留清晰边界。
