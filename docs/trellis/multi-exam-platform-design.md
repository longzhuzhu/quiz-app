# 通用刷题备考平台改造设计（用户自有考试项目）

- 文档版本：v2.0
- 更新日期：2026-05-24
- 状态：已评审，待实施
- 关联文档：`quiz-app-fastapi-postgresql-smart-import-design.md`
- 关联领域语言：`CONTEXT.md`
- 关联 ADR：
  - `docs/adr/0002-exam-project-deletion.md`
  - `docs/adr/0003-url-exam-slug-and-active-exam.md`
  - `docs/adr/0004-no-legacy-routes-for-multi-exam.md`

---

## 0. 文档导读

本文档定义将当前 **CIPT 专用刷题应用** 改造为 **通用刷题备考平台** 的设计。核心模型从“平台公开考试目录 + 用户订阅”收敛为：

> 每个用户拥有自己的 **考试项目**；题库、题目、错题、词汇、练习进度和 AI Profile 都在考试项目内隔离。

**本次范围（IN SCOPE）**：

- 引入 `Exam` 一等公民，中文领域术语为 **考试项目**。
- 所有考试项目由单个用户拥有，通过 `exams.owner_id` 表达归属。
- 所有题库唯一归属于一个考试项目，不跨考试项目复用或迁移。
- 题库导入必须发生在当前考试项目上下文中。
- 错题、历史、词汇、统计按考试项目隔离。
- 保留跨考试项目个人词汇。
- AI Profile 按考试项目配置。
- 前端增加“我的项目”、考试项目切换器、首登创建项目引导。
- 管理员可只读查看所有用户的考试项目、题库、题目内容和基础统计，用于支持排查。

**本次范围外（OUT OF SCOPE）**：

- 公开考试项目、私有考试项目区分。
- 加入/退出考试项目、订阅关系、公开目录、可订阅项目。
- `user_exams` 成员关系表。
- 上架/下架/停用、`visibility`、`is_listed`、`is_enabled`。
- 管理员编辑或删除其他用户的考试项目、题库、题目。
- 管理员查看其他用户答题历史。
- 旧 URL 兼容重定向。
- ImporterProfile 抽象。
- QuizProfile 扩展、新题型。
- 跨考试项目全局概览。

---

## 1. 设计决策摘要（已锁定）

| 编号 | 决策项 | 结论 |
|---|---|---|
| D1 | `Exam` 中文术语 | **考试项目**；空间有限的 UI 可短写为“我的项目” |
| D2 | 项目归属模型 | 所有考试项目都是用户自有项目，`exams.owner_id` 表示所有者 |
| D3 | 公开/私有与订阅 | 不做公开/私有区分；不做加入、退出、订阅、上架、下架、停用 |
| D4 | Slug 唯一性 | `slug` 在同一 owner 范围内唯一，允许 owner 修改；旧 URL 不兼容 |
| D5 | 当前考试项目 | `users.active_exam_id` 仅作为默认项目和切换器状态，不作为 API 隐式上下文 |
| D6 | API 考试项目上下文 | 考试项目范围 API 必须显式传 `X-Exam-Slug`，与当前认证用户共同解析 |
| D7 | 题库归属 | `QuestionBank` 唯一归属一个 `Exam`，不跨项目复用或迁移 |
| D8 | 题库/题目 owner 字段 | 不在题库和题目重复存 `owner_id`，从 `exam.owner_id` 推导 |
| D9 | 词汇结构 | 保留跨考试项目个人词汇；项目专属词汇只表示用户个人词汇 |
| D10 | AI Profile | 按考试项目配置；owner 可编辑，管理员只读查看他人项目配置 |
| D11 | 存量 CIPT 迁移 | 当前存量 CIPT 数据只迁移到当前管理员用户的自有 CIPT 考试项目 |
| D12 | 管理员能力 | 管理员可只读查看其他用户项目/题库/题目/基础统计，不编辑、不删除、不看答题历史 |
| D13 | 删除语义 | owner 可删除整个考试项目及项目内数据；跨考试项目个人词汇保留 |
| D14 | 路由兼容 | 不保留 `/banks`、`/wrong`、`/vocab` 等旧路由兼容重定向 |

---

## 2. 领域模型

### 2.1 模型关系图

```text
┌─────────────┐       1:N       ┌──────────────┐
│    User     │────────────────▶│     Exam     │
│             │                 │ owner_id     │
│ active_exam │────────────────▶│ slug, name   │
└─────┬───────┘                 │ ai_profile   │
      │                         └──────┬───────┘
      │                                │ 1:N
      │                                ▼
      │                         ┌──────────────┐
      │                         │ QuestionBank │
      │                         │ exam_id      │
      │                         └──────┬───────┘
      │                                │ 1:N
      │                                ▼
      │                         ┌──────────────┐
      │                         │  Question    │
      │                         └──────┬───────┘
      │                                │ 1:N
      │                                ▼
      └─────────────── 1:N ─────│ WrongAnswer  │
                                └──────────────┘

┌──────────────┐
│  Vocabulary  │
│  user_id     │  必填：词汇归属用户
│  exam_id     │  NULL = 跨考试项目个人词汇；非 NULL = 考试项目专属词汇
└──────────────┘
```

### 2.2 新增表：`exams` —— 考试项目

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | INT PK | autoinc | |
| owner_id | INT FK→users.id | NOT NULL | 考试项目所有者 |
| slug | VARCHAR(50) | NOT NULL | owner 范围内唯一短标识，如 `cipt`、`pmp` |
| name | VARCHAR(100) | NOT NULL | 完整名称 |
| short_name | VARCHAR(30) | NOT NULL | UI 短名称 |
| description | TEXT | NULL | 简介 |
| icon | VARCHAR(50) | NULL | lucide 图标名 |
| locale | VARCHAR(10) | NOT NULL DEFAULT 'en-US' | 题目原文语言 |
| sort_order | INT | NOT NULL DEFAULT 0 | 用户自己的项目排序 |
| importer_profile | VARCHAR(50) | NOT NULL DEFAULT 'examtopics-pdf' | 预留字段，本次不读取 |
| ai_profile | JSONB | NOT NULL DEFAULT '{}' | 考试项目 AI Profile |
| quiz_profile | JSONB | NOT NULL DEFAULT '{}' | 预留字段，本次不读取 |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() | |
| updated_at | TIMESTAMPTZ | NOT NULL DEFAULT now() | |

**索引与约束**：

- `UNIQUE(owner_id, slug)`
- `INDEX(owner_id, sort_order)`

**业务规则**：

- 用户只能在自己的 owner 范围内创建、编辑、删除考试项目。
- 同一用户不能有两个相同 slug 的考试项目。
- 不同用户可以使用相同 slug。
- owner 可以修改 slug；修改后旧 URL 不保留兼容重定向。
- owner 删除考试项目时，删除项目内题库、题目、错题、历史、项目专属词汇；跨考试项目个人词汇不删除。

### 2.3 现有表改动

| 表 | 字段变更 | 约束 | 数据迁移 |
|---|---|---|---|
| `users` | `+ active_exam_id INT NULL FK→exams.id` | active exam 必须属于该用户 | 当前管理员用户回填为 CIPT 项目 id；其他用户为 NULL |
| `question_banks` | `+ exam_id INT NOT NULL FK→exams.id` | 一旦创建后不允许跨项目迁移 | 存量题库回填到管理员 CIPT 项目 |
| `vocabularies` | `+ exam_id INT NULL FK→exams.id` | `user_id` 应为非 NULL | 存量系统词汇迁移为管理员 CIPT 项目专属词汇 |
| `wrong_answers` | 不改字段 | 通过 question→bank→exam 推导项目 | 加复合索引 `(user_id, question_id)` |
| `quiz_sessions` | 不改字段 | 通过 `bank_id → exam_id` 推导项目 | — |

> 不新增 `user_exams`。本设计没有加入、退出、成员、订阅关系。

### 2.4 AI Profile

`ai_profile` 是考试项目级配置，不支持题库级或题目级覆盖。

```jsonc
{
  "translation_system_prompt": "你是专业考试题目的翻译助手...",
  "explanation_system_prompt": "你是专业考试题目的解析助手...",
  "vocab_extract_system_prompt": "从下列题目中识别专业术语...",
  "source_lang": "en",
  "target_lang": "zh-CN",
  "model_override": null,
  "enabled_features": ["translate", "explain", "vocab_extract"]
}
```

**规则**：

- 新建考试项目默认使用平台通用 AI Profile。
- 创建时可选择复制 owner 已有考试项目的 AI Profile。
- owner 可编辑自己考试项目的 AI Profile。
- 管理员只读查看其他用户考试项目的 AI Profile，用于支持排查。
- 存量 CIPT prompt 迁移到管理员 CIPT 项目的 AI Profile。

### 2.5 Quiz Profile

`quiz_profile` 字段仅预留，本次不读取。

```jsonc
{
  "supported_types": ["single", "multiple", "truefalse"],
  "scoring": {
    "multiple": "all-or-nothing",
    "passing_score": 0.7
  },
  "timer_seconds_per_question": null,
  "allow_skip": true,
  "show_explanation_during_quiz": false
}
```

---

## 3. Alembic 迁移设计

文件：`backend/alembic/versions/003_add_user_owned_exams.py`

### 3.1 升级步骤

1. 创建 `exams` 表。
2. 找到当前存量管理员用户。
3. 为该管理员创建 `slug='cipt'` 的 CIPT 考试项目。
4. 为 `question_banks` 增加 `exam_id`，将存量题库回填到管理员 CIPT 项目，再设置 NOT NULL 和 FK。
5. 为 `vocabularies` 增加 `exam_id`：
   - 存量 `is_system = true` 词汇：设置 `user_id = 管理员用户 id`，`exam_id = 管理员 CIPT 项目 id`。
   - 存量非系统个人词汇：保留为 `exam_id = NULL` 的跨考试项目个人词汇。
6. 为 `users` 增加 `active_exam_id`：
   - 管理员用户回填为 CIPT 项目 id。
   - 其他用户保持 NULL，登录后通过引导创建第一个考试项目。
7. 为 `wrong_answers` 增加 `(user_id, question_id)` 索引。

### 3.2 关键约束

```python
op.create_table(
    "exams",
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("owner_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    sa.Column("slug", sa.String(50), nullable=False),
    sa.Column("name", sa.String(100), nullable=False),
    sa.Column("short_name", sa.String(30), nullable=False),
    sa.Column("description", sa.Text, nullable=True),
    sa.Column("icon", sa.String(50), nullable=True),
    sa.Column("locale", sa.String(10), nullable=False, server_default="en-US"),
    sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
    sa.Column("importer_profile", sa.String(50), nullable=False, server_default="examtopics-pdf"),
    sa.Column("ai_profile", postgresql.JSONB, nullable=False, server_default="{}"),
    sa.Column("quiz_profile", postgresql.JSONB, nullable=False, server_default="{}"),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
)
op.create_unique_constraint("uq_exams_owner_slug", "exams", ["owner_id", "slug"])
op.create_index("ix_exams_owner_sort", "exams", ["owner_id", "sort_order"])
```

### 3.3 迁移风险

- 如果不存在管理员用户，迁移应失败并提示先创建管理员用户。
- 存量 `is_system=true` 词汇如果没有 `user_id`，必须回填为管理员用户 id，避免后续继续存在系统/官方词汇语义。
- 存量题库只迁移到当前管理员项目，不复制给其他用户。

---

## 4. 后端 API 契约

### 4.1 考试项目解析依赖

`backend/app/api/deps.py`：

```python
async def get_exam_context(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    x_exam_slug: str = Header(..., alias="X-Exam-Slug"),
) -> Exam:
    """解析当前请求显式声明的考试项目上下文。"""
    exam = await db.scalar(
        select(Exam).where(
            Exam.owner_id == user.id,
            Exam.slug == x_exam_slug,
        )
    )
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    return exam
```

**规则**：

- 考试项目范围 API 必须传 `X-Exam-Slug`。
- 不使用 `users.active_exam_id` 作为 API 隐式兜底。
- `active_exam_id` 只用于默认进入哪个项目、切换器状态和 `/` 跳转。
- 管理员只读后台接口使用单独依赖，不复用普通用户的 owner-scoped 解析。

### 4.2 `/api/exams` —— 我的项目

| 方法 | 路径 | 权限 | 用途 |
|---|---|---|---|
| GET | `/api/exams` | 已登录 | 列出当前用户拥有的考试项目 |
| POST | `/api/exams` | 已登录 | 创建考试项目，自动设为当前用户拥有 |
| GET | `/api/exams/{slug}` | owner | 获取自己的考试项目详情 |
| PATCH | `/api/exams/{slug}` | owner | 编辑基本信息、slug、AI Profile |
| DELETE | `/api/exams/{slug}` | owner | 删除考试项目及项目内数据 |

**`POST /api/exams` 请求体**：

```json
{
  "slug": "pmp",
  "name": "PMP 项目管理专业人士",
  "short_name": "PMP",
  "description": "...",
  "icon": "Briefcase",
  "locale": "en-US",
  "ai_profile_mode": "default",
  "copy_ai_profile_from": null,
  "ai_profile": null
}
```

`ai_profile_mode`：

- `default`：使用平台通用 AI Profile。
- `copy`：复制当前用户已有考试项目的 AI Profile。
- `custom`：使用请求体里的自定义 AI Profile。

**响应（ExamRead）**：

```json
{
  "id": 2,
  "slug": "pmp",
  "name": "PMP 项目管理专业人士",
  "short_name": "PMP",
  "description": "...",
  "icon": "Briefcase",
  "locale": "en-US",
  "sort_order": 0,
  "owner": { "id": 5, "username": "alice" },
  "stats": { "bank_count": 0, "question_count": 0, "wrong_count": 0, "progress": 0.0 },
  "ai_profile": { "...": "..." },
  "created_at": "2026-05-24T10:00:00Z"
}
```

### 4.3 `/api/account/active-exam` —— 切换默认项目

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/account/active-exam` | body: `{ "slug": "pmp" }`；校验该 slug 属于当前用户后写入 `users.active_exam_id` |

删除当前 active 考试项目时，清空 `active_exam_id`，不自动选择其他项目。

### 4.4 `/api/me` —— 增强响应

```json
{
  "id": 1,
  "username": "...",
  "is_admin": false,
  "active_exam": { "...ExamRead..." },
  "exam_count": 3
}
```

### 4.5 管理员只读接口

| 方法 | 路径 | 权限 | 用途 |
|---|---|---|---|
| GET | `/api/admin/exams` | admin | 只读列出所有用户考试项目和基础统计 |
| GET | `/api/admin/exams/{id}` | admin | 只读查看某个考试项目详情 |
| GET | `/api/admin/exams/{id}/banks` | admin | 只读查看题库列表 |
| GET | `/api/admin/banks/{id}/questions` | admin | 只读查看题目内容 |

本阶段不提供：

- 管理员编辑/删除他人考试项目。
- 管理员编辑/删除他人题库或题目。
- 管理员查看用户答题历史。

### 4.6 现有路由改造

| 路由 | 改造 |
|---|---|
| `GET /api/banks` | 注入 `get_exam_context`，列表 `WHERE question_banks.exam_id = exam.id` |
| `POST /api/banks/import` | 必须在 `X-Exam-Slug` 指定的考试项目中导入 |
| `GET /api/banks/{id}` | 校验 bank 属于当前用户解析出的 exam |
| `PATCH/DELETE /api/banks/{id}` | 只允许 owner 管理自己项目内题库 |
| `GET /api/questions` | 通过 bank→exam 校验 owner 边界 |
| `GET /api/wrong` | 通过 question→bank→exam 过滤当前考试项目 |
| `GET /api/quiz/history` | 通过 bank→exam 过滤当前考试项目 |
| `GET /api/vocab` | 见 §4.7 双层个人词汇查询 |
| `POST /api/vocab` | 默认添加到当前考试项目专属词汇；可显式保存为跨考试项目个人词汇 |
| `POST /api/ai/translate`, `POST /api/ai/explain` | 通过 question→bank→exam 取考试项目 AI Profile |

### 4.7 词汇本双层查询

**`GET /api/vocab` query 参数**：

| 参数 | 含义 | 默认 |
|---|---|---|
| `scope` | `personal` / `exam_personal` / `all` | `all` |
| `q` | 搜索词 | — |
| `page`, `page_size` | 分页 | 1, 20 |

**SQL 模板（scope=all）**：

```sql
SELECT * FROM vocabularies
WHERE
  user_id = :me
  AND (
    exam_id IS NULL
    OR exam_id = :current_exam
  )
ORDER BY updated_at DESC;
```

每条记录响应增加 `scope_label`：

- `personal`：跨考试项目个人词汇。
- `exam_personal`：当前考试项目专属词汇。

### 4.8 错误码约定

| HTTP | code | 场景 |
|---|---|---|
| 400 | `EXAM_REQUIRED` | 考试项目范围 API 缺少 `X-Exam-Slug` |
| 403 | `EXAM_FORBIDDEN` | 当前用户无权访问该考试项目 |
| 404 | `EXAM_NOT_FOUND` | 当前用户范围内找不到该 slug |
| 409 | `EXAM_SLUG_EXISTS` | 同一 owner 下 slug 重复 |
| 409 | `BANK_EXAM_MISMATCH` | 试图把题库或题目移动到另一个考试项目 |

---

## 5. 前端设计

### 5.1 路由结构

| 路径 | 组件 | 说明 |
|---|---|---|
| `/` | 重定向到 `/exams/{activeSlug}/dashboard` 或 `/onboarding` | |
| `/onboarding` | `FirstTimeOnboarding.vue` | 创建第一个考试项目 |
| `/exams` | `MyExamProjectsPage.vue` | 我的项目列表 |
| `/exams/new` | `ExamCreatePage.vue` | 新建考试项目 |
| `/exams/:examSlug/dashboard` | `ExamDashboard.vue` | 当前考试项目首页 |
| `/exams/:examSlug/banks` | `BankList.vue` | 题库列表 |
| `/exams/:examSlug/banks/:bankId` | `BankDetail.vue` | 题库详情 |
| `/exams/:examSlug/quiz/:bankId` | `QuizSession.vue` | 答题 |
| `/exams/:examSlug/wrong` | `WrongBook.vue` | 错题本 |
| `/exams/:examSlug/vocab` | `VocabBook.vue` | 词汇本 |
| `/admin/exams` | `AdminExamList.vue` | 管理员只读：所有用户项目 |
| `/admin/exams/:id` | `AdminExamDetail.vue` | 管理员只读：项目、题库、题目 |

**不保留旧路由兼容**：

- `/banks`
- `/banks/:id`
- `/wrong`
- `/vocab`

### 5.2 Pinia Store

项目使用纯 JavaScript，store 文件使用 `.js`。

`frontend/src/stores/exam.js`：

```js
export const useExamStore = defineStore('exam', () => {
  const current = ref(null)
  const myExams = ref([])
  const loaded = ref(false)

  async function bootstrap() {
    const me = await api.get('/me')
    current.value = me.active_exam
    myExams.value = await api.get('/exams')
    loaded.value = true
  }

  async function switchTo(slug, targetRouteKind = null) {
    const exam = await api.post('/account/active-exam', { slug })
    current.value = exam
    await refreshExamScopedData()
    navigateToExam(slug, targetRouteKind)
  }

  async function createExam(payload) {
    const exam = await api.post('/exams', payload)
    await switchTo(exam.slug, 'dashboard')
    return exam
  }

  async function deleteExam(slug) {
    await api.delete(`/exams/${slug}`)
    myExams.value = myExams.value.filter(exam => exam.slug !== slug)
    if (current.value?.slug === slug) current.value = null
  }

  return { current, myExams, loaded, bootstrap, switchTo, createExam, deleteExam }
})
```

### 5.3 Axios 拦截器

```js
axios.interceptors.request.use((config) => {
  const exam = useExamStore()
  if (isExamScopedApi(config.url) && exam.current) {
    config.headers['X-Exam-Slug'] = exam.current.slug
  }
  return config
})
```

### 5.4 路由守卫

```js
router.beforeEach(async (to) => {
  const exam = useExamStore()
  if (!exam.loaded) await exam.bootstrap()

  if (!exam.current && to.name !== 'onboarding' && to.name !== 'my-exams') {
    return { name: 'onboarding' }
  }

  const urlSlug = to.params.examSlug
  if (urlSlug && urlSlug !== exam.current?.slug) {
    try {
      await exam.switchTo(urlSlug, routeKind(to))
    } catch {
      return { name: 'my-exams' }
    }
  }
})
```

### 5.5 切换考试项目

- 普通页面切换：保留当前页面类型，例如从 CIPT 错题本切换到 PMP 错题本。
- 答题页切换：离开当前答题页，进入目标项目 dashboard，不在原答题页热切换上下文。
- 切换后写入 `active_exam_id`。

### 5.6 “我的项目”页面

`/exams` 页面只显示当前用户拥有的考试项目。

布局：

```text
┌─────────────────────────────────────────┐
│ 我的项目                         [+ 新建] │
│                                         │
│ ┌─────┐ ┌─────┐ ┌─────┐                │
│ │CIPT │ │ PMP │ │ ... │                │
│ │进入 │ │进入 │ │进入 │                │
│ └─────┘ └─────┘ └─────┘                │
└─────────────────────────────────────────┘
```

卡片显示：

- 图标
- `short_name`
- `name`
- 题库数量
- 题目数量
- 当前项目进度
- 操作：进入、编辑、删除

### 5.7 首登引导

新用户没有 active exam 时进入 `/onboarding`。

引导目标：创建第一个考试项目。

字段：

- `short_name` 必填
- `name` 必填
- `slug` 必填，可自动从 `short_name` 生成
- `icon`
- `description`
- `locale`
- AI Profile：使用平台通用配置；如果当前用户已有其他考试项目，可选择复制已有项目配置；也可自定义

创建完成后进入 `/exams/{slug}/dashboard`。

### 5.8 词汇本

```text
词汇本                                    [+ 添加]
┌────────────────────┬────────────────────┐
│ 我的单词本（跨项目） │ 当前项目词汇        │
└────────────────────┴────────────────────┘
```

- Tab1：`scope=personal`
- Tab2：`scope=exam_personal`
- 从题目页“加入生词本”默认保存到当前项目词汇。
- 添加弹窗可选择保存到跨考试项目个人词汇。

### 5.9 管理员只读页面

`/admin/exams`：

- 列出所有用户的考试项目。
- 支持按 owner、项目名、slug 搜索。
- 展示基础统计：题库数、题目数、更新时间。
- 不提供编辑、删除、停用、下架操作。

`/admin/exams/:id`：

- 只读查看项目信息、AI Profile、题库列表、题目内容。
- 不展示用户答题历史。

---

## 6. 权限与可见性矩阵

| 操作 | 普通用户 owner | 普通用户非 owner | 管理员访问自己项目 | 管理员访问他人项目 |
|---|---:|---:|---:|---:|
| 查看考试项目 | ✓ | ✗ | ✓ | ✓（只读） |
| 创建考试项目 | ✓ | — | ✓ | — |
| 编辑考试项目基本信息 | ✓ | ✗ | ✓ | ✗ |
| 修改 slug | ✓ | ✗ | ✓ | ✗ |
| 编辑 AI Profile | ✓ | ✗ | ✓ | ✗ |
| 删除考试项目 | ✓ | ✗ | ✓ | ✗ |
| 查看题库/题目 | ✓ | ✗ | ✓ | ✓（只读） |
| 导入题库 | ✓ | ✗ | ✓ | ✗ |
| 编辑/删除题库 | ✓ | ✗ | ✓ | ✗ |
| 查看错题/历史 | ✓ | ✗ | ✓ | ✗ |
| 查看基础统计 | ✓ | ✗ | ✓ | ✓（只读） |

---

## 7. 兼容性与迁移体验

### 7.1 存量管理员体验

| 改动 | 结果 |
|---|---|
| 数据迁移 | 存量 CIPT 题库、题目、系统词汇迁移到管理员用户自有 CIPT 项目 |
| 登录后默认项目 | 管理员 `active_exam_id` 指向 CIPT 项目 |
| 题库/错题/词汇 | 在 `/exams/cipt/...` 下继续使用 |
| 系统词汇 | 变为管理员 CIPT 项目的项目专属词汇 |
| AI 翻译/解析 | CIPT 项目 AI Profile 复用现有 CIPT prompt |

### 7.2 新用户体验

| 场景 | 结果 |
|---|---|
| 首次登录 | 进入创建第一个考试项目引导 |
| 没有项目 | 无法进入题库、错题、词汇等项目范围页面 |
| 创建项目后 | 自动进入项目 dashboard，并写入 active exam |
| 导入题库 | 必须在当前考试项目中导入 |

### 7.3 不兼容项

- 旧路由不重定向。
- 旧的全局题库概念消失。
- 旧的系统词汇/官方术语语义消失。
- 不提供公开考试项目目录。

---

## 8. 分阶段交付计划

### PR-1 · 后端基础（数据模型 + 迁移 + Exam CRUD）

**范围**：

- [ ] 新增 `Exam` 模型与 Pydantic schema。
- [ ] 迁移脚本 `003_add_user_owned_exams.py`。
- [ ] `users.active_exam_id`。
- [ ] `question_banks.exam_id`。
- [ ] `vocabularies.exam_id`。
- [ ] 存量 CIPT 数据迁移到当前管理员用户的 CIPT 项目。
- [ ] `/api/exams` CRUD。
- [ ] `/api/account/active-exam`。
- [ ] `get_exam_context` 依赖。
- [ ] banks/questions/wrong/vocab/quiz/ai 注入考试项目上下文。
- [ ] AI Profile 抽取到考试项目配置。
- [ ] 管理员只读 API。

**验收**：管理员登录后可进入 `/exams/cipt/...` 查看和使用存量 CIPT 数据；新用户需要创建第一个项目。

### PR-2 · 前端基础（我的项目 + 切换器 + 主要页面改造）

**范围**：

- [ ] `useExamStore`。
- [ ] Axios `X-Exam-Slug` 拦截器。
- [ ] 路由表改为 `/exams/:examSlug/...`。
- [ ] 不保留旧路由兼容。
- [ ] `ExamSwitcher.vue`。
- [ ] `/exams` 我的项目页面。
- [ ] `/onboarding` 创建第一个项目。
- [ ] 题库、错题、词汇、仪表盘标题动态化。
- [ ] 词汇本双 Tab。

**验收**：用户可创建第二个项目、切换项目、导入题库、项目间数据隔离。

### PR-3 · 项目管理与管理员只读后台

**范围**：

- [ ] 编辑考试项目基本信息、slug、AI Profile。
- [ ] 删除考试项目及项目内数据。
- [ ] 管理员 `/admin/exams` 只读列表。
- [ ] 管理员只读查看项目、题库、题目内容、基础统计。

**验收**：owner 可完整管理自己的项目；管理员可只读排查他人项目但不能修改。

### 后续 spec

- ImporterProfile 抽象。
- QuizProfile 扩展、新题型。
- 协作/共享/公开项目能力。
- 跨考试项目全局概览。

---

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 请求缺少 `X-Exam-Slug` | 后端无法判断项目上下文 | 考试项目范围 API 返回 `EXAM_REQUIRED` |
| 用户修改 slug 后旧链接失效 | 旧 URL 404 | 产品明确不保留旧 URL 兼容，保持模型简单 |
| 删除考试项目误删项目内数据 | 数据不可逆 | UI 必须展示项目级数据删除确认；跨项目个人词汇不删除 |
| 管理员只读越权变成可编辑 | 用户数据所有权被破坏 | 后台接口只提供 GET；服务层明确禁止跨 owner 写操作 |
| 存量系统词汇语义残留 | 继续出现官方/系统词汇概念 | 迁移时回填为管理员项目专属词汇，后续查询不再使用 `is_system` 语义 |
| 答题中切换项目导致上下文错乱 | 页面显示旧题但新项目上下文 | 答题页切换项目时离开当前答题页，进入目标项目 dashboard |
| 管理员用户不存在导致迁移失败 | 存量 CIPT 无 owner | 迁移前检查管理员用户；不存在则失败并提示先创建管理员 |

---

## 10. 验收清单

- [ ] 数据库迁移成功创建管理员自有 CIPT 考试项目。
- [ ] 存量题库全部绑定到管理员 CIPT 项目。
- [ ] 存量系统词汇变为管理员 CIPT 项目专属词汇。
- [ ] 管理员登录后 active exam 指向 CIPT。
- [ ] 新用户首次登录进入创建第一个考试项目引导。
- [ ] 用户只能看到自己的考试项目。
- [ ] 管理员只读后台能看到所有用户项目和题库/题目内容。
- [ ] 管理员不能编辑或删除他人项目、题库、题目。
- [ ] 题库导入必须绑定当前考试项目。
- [ ] 切换项目后题库、错题、词汇只显示当前项目数据。
- [ ] 跨考试项目个人词汇在所有用户自有项目中可见。
- [ ] 题目页添加词汇默认保存到当前项目专属词汇。
- [ ] AI 翻译/解析按当前项目 AI Profile 执行。
- [ ] 删除项目会删除项目内数据但保留跨考试项目个人词汇。
- [ ] 旧 URL 不再可用，不做重定向。

---

## 11. 附录

### 11.1 ExamRead Pydantic Schema

```python
class ExamStats(BaseModel):
    bank_count: int
    question_count: int
    wrong_count: int
    progress: float

class ExamOwner(BaseModel):
    id: int
    username: str

class ExamRead(BaseModel):
    id: int
    slug: str
    name: str
    short_name: str
    description: str | None
    icon: str | None
    locale: str
    sort_order: int
    owner: ExamOwner
    stats: ExamStats
    ai_profile: dict
    created_at: datetime
```

### 11.2 文件影响清单

**后端新增**：

- `backend/app/models/exam.py`
- `backend/app/schemas/exam.py`
- `backend/app/api/routes/exams.py`
- `backend/app/api/routes/admin_exams.py`
- `backend/alembic/versions/003_add_user_owned_exams.py`

**后端修改**：

- `backend/app/models/__init__.py`
- `backend/app/models/user.py`
- `backend/app/models/question_bank.py`
- `backend/app/models/vocabulary.py`
- `backend/app/api/deps.py`
- `backend/app/api/routes/banks.py`
- `backend/app/api/routes/questions.py`
- `backend/app/api/routes/wrong.py`
- `backend/app/api/routes/vocab.py`
- `backend/app/api/routes/quiz.py`
- `backend/app/api/routes/ai.py`
- `backend/app/api/routes/account.py`
- `backend/app/services/ai_service.py`
- `backend/app/services/import_service.py`
- `backend/app/services/smart_import_service.py`
- `backend/app/schemas/auth.py`
- `backend/app/schemas/bank.py`
- `backend/app/schemas/vocab.py`

**前端新增**：

- `frontend/src/stores/exam.js`
- `frontend/src/components/ExamSwitcher.vue`
- `frontend/src/views/MyExamProjectsPage.vue`
- `frontend/src/views/ExamCreatePage.vue`
- `frontend/src/views/FirstTimeOnboarding.vue`
- `frontend/src/views/ExamDashboard.vue`
- `frontend/src/views/admin/AdminExamList.vue`
- `frontend/src/views/admin/AdminExamDetail.vue`
- `frontend/src/api/exams.js`

**前端修改**：

- `frontend/src/router/index.js`
- `frontend/src/App.vue` 或布局组件
- `frontend/src/api/client.js`
- `frontend/src/views/BankList.vue`
- `frontend/src/views/BankDetail.vue`
- `frontend/src/views/WrongBook.vue`
- `frontend/src/views/VocabBook.vue`
- `frontend/src/views/QuizSession.vue`
- 所有含 “CIPT” 硬编码文案的组件

---

**文档结束**
