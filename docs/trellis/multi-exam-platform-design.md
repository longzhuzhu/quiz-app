# 通用刷题备考平台改造设计（多考试支持）

- 文档版本：v1.0
- 创建日期：2026-05-24
- 状态：待评审 → 实施中
- 关联文档：`quiz-app-fastapi-postgresql-smart-import-design.md`

---

## 0. 文档导读

本文档定义将当前 **CIPT 专用刷题应用** 改造为 **通用刷题备考平台** 的完整设计，覆盖：

- 领域模型变更（数据库 Schema + 迁移脚本）
- 后端 API 契约（路由清单、请求/响应、依赖注入）
- 前端交互设计（组件、路由、Pinia Store、用户流）
- 权限模型与数据可见性规则
- 分阶段交付计划（PR 拆分）
- 兼容性与回滚策略

**本次范围（IN SCOPE）**：

- 引入 `Exam` 一等公民，所有题库/错题/词汇/统计按考试隔离
- 用户级"我的考试"订阅模型（用户主动加入考试才出现在切换器）
- 普通用户可创建私有考试，管理员可上架为公开
- AI Profile 按考试可配置（翻译/解析 prompt）
- 前端考试切换器、考试目录页、首登引导

**本次范围外（OUT OF SCOPE，留作后续 spec）**：

- ImporterProfile 抽象（通用 XLSX/DOCX 导入器）—— 本次保留现有 ExamTopics PDF 解析逻辑，`exam.importer_profile` 字段预留但不发挥作用
- QuizProfile 扩展（填空、题组阅读、AI 评分简答题）—— 本次仍保持单选/多选/判断三种题型
- 题库/考试社区市场、订阅评分

---

## 1. 设计决策摘要（已锁定）

| 编号 | 决策项 | 结论 |
|---|---|---|
| D1 | 多考试切换粒度 | **账号级**（`User.active_exam_id`，URL 带 `examSlug` 自动同步） |
| D2 | 错题本范围 | **按考试隔离**，不提供跨考试合并视图 |
| D3 | 词汇本结构 | **双层**：`exam_id IS NULL` = 个人跨考试单词本；`exam_id != NULL` = 考试专属术语本 |
| D4 | 题目归属 | **唯一归属**，`Question` 通过 `bank_id → exam_id` 单向归属，不支持跨考试复用 |
| D5 | 考试创建权限 | **B 方案**：普通用户可创建**私有考试**自用；管理员可将其上架为**公开考试** |
| D6 | "我的考试"模型 | **A 方案**：用户必须显式"加入"考试才出现在切换器，未加入的在 `/exams` 目录页可订阅 |
| D7 | ImporterProfile | **本次不实现**，字段预留 |
| D8 | QuizProfile / 新题型 | **本次不实现**，保持现状 |

---

## 2. 领域模型

### 2.1 模型关系图

```
┌─────────────┐         ┌────────────────┐
│    User     │────M:N──│    Exam        │  via user_exams
│             │         │                │
│ active_exam │────────►│ id, slug, name │
└─────┬───────┘         │ visibility     │
      │                 │ owner_id       │
      │                 │ ai_profile     │
      │                 └────────┬───────┘
      │                          │ 1:N
      │                          ▼
      │                   ┌──────────────┐
      │                   │ QuestionBank │
      │                   │  exam_id (NN)│
      │                   └──────┬───────┘
      │                          │ 1:N
      │                          ▼
      │                   ┌──────────────┐
      │                   │  Question    │
      │                   └──────┬───────┘
      │                          │ 1:N
      │                          ▼
      │                   ┌──────────────┐
      └──── 1:N ─────────►│ WrongAnswer  │
                          └──────────────┘

┌──────────────┐
│  Vocabulary  │   exam_id (NULL=个人跨考试 / NN=考试术语)
│  user_id     │   user_id  (NULL=系统/管理员维护 / NN=用户私有)
└──────────────┘
```

### 2.2 新增表

#### `exams` —— 考试/科目

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | INT PK | autoinc | |
| slug | VARCHAR(50) | UNIQUE NOT NULL | URL 标识，如 `cipt`、`pmp`、`aws-saa` |
| name | VARCHAR(100) | NOT NULL | 完整名，如"CIPT 信息隐私技术认证" |
| short_name | VARCHAR(30) | NOT NULL | 切换器显示，如"CIPT" |
| description | TEXT | NULL | 简介（Markdown） |
| icon | VARCHAR(50) | NULL | lucide 图标名，如 `Shield` |
| locale | VARCHAR(10) | NOT NULL DEFAULT 'en-US' | 题目原文语言 |
| visibility | VARCHAR(10) | NOT NULL DEFAULT 'private' | `public` / `private` |
| owner_id | INT FK→users.id | NULL | 创建者；`public` 考试可为 NULL（平台官方） |
| is_active | BOOLEAN | NOT NULL DEFAULT true | 下架开关 |
| sort_order | INT | NOT NULL DEFAULT 0 | 目录页排序 |
| importer_profile | VARCHAR(50) | NOT NULL DEFAULT 'examtopics-pdf' | 预留字段（D7） |
| ai_profile | JSONB | NOT NULL DEFAULT '{}' | 见 §2.4 |
| quiz_profile | JSONB | NOT NULL DEFAULT '{}' | 预留字段（D8） |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() | |
| updated_at | TIMESTAMPTZ | NOT NULL DEFAULT now() | |

**索引**：`UNIQUE(slug)`、`INDEX(visibility, is_active, sort_order)`、`INDEX(owner_id)`

**业务约束**：

- `visibility = 'private'` 时 `owner_id` 必须非 NULL
- `visibility = 'public'` 时 `owner_id` 可空（官方考试）或保留首位创建者
- 已有 `QuestionBank` 的 `Exam` 不允许删除（仅可 `is_active = false` 软下架）

#### `user_exams` —— 用户订阅关系（D6）

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| user_id | INT FK→users.id | NOT NULL | |
| exam_id | INT FK→exams.id | NOT NULL | |
| joined_at | TIMESTAMPTZ | NOT NULL DEFAULT now() | |
| role | VARCHAR(20) | NOT NULL DEFAULT 'member' | `member` / `editor` / `owner` |

**主键**：`(user_id, exam_id)`
**索引**：`INDEX(user_id)`、`INDEX(exam_id)`

**业务规则**：

- 创建私有考试时自动插入 `(owner, exam, role='owner')`
- 公开考试需用户主动 `POST /api/exams/{slug}/join` 才落库
- 取消订阅 `DELETE /api/exams/{slug}/leave`，但 `role='owner'` 不可退订
- `active_exam_id` 必须是用户已加入的考试，否则切换接口拒绝

### 2.3 现有表改动

| 表 | 字段变更 | 约束 | 数据迁移 |
|---|---|---|---|
| `users` | `+ active_exam_id INT NULL FK→exams.id` | — | 全量回填为 CIPT id |
| `question_banks` | `+ exam_id INT NOT NULL FK→exams.id` | 一旦设定不可改 | 存量回填 CIPT id，再加 NOT NULL |
| `vocabularies` | `+ exam_id INT NULL FK→exams.id` | — | `is_system = true` 的行回填 CIPT id；其余保持 NULL（变成"个人跨考试单词本"） |
| `wrong_answers` | 不改字段 | 通过 `JOIN questions JOIN question_banks` 推导 exam | 加复合索引 `(user_id, question_id)` |
| `quiz_sessions` | 不改字段 | 通过 `bank_id → exam_id` 推导 | — |

> **关于 `wrong_answers.exam_id` 是否冗余**：评估查询频率与 JOIN 成本后采用**隐式过滤方案**，零数据冗余、迁移最简。如未来出现性能瓶颈再增加冗余字段（不阻塞本次设计）。

### 2.4 `ai_profile` JSONB 结构

```jsonc
{
  "translation_system_prompt": "你是信息隐私领域的专业翻译...",
  "explanation_system_prompt": "你是 IAPP CIPT 认证的专家讲师...",
  "vocab_extract_system_prompt": "从下列题目中识别专业术语...",
  "source_lang": "en",
  "target_lang": "zh-CN",
  "model_override": null,           // null = 使用全局 SystemSetting.default_model
  "enabled_features": ["translate", "explain", "vocab_extract"]
}
```

**校验**：通过 Pydantic `AIProfile` schema 验证；缺失字段使用全局默认。

### 2.5 `quiz_profile` JSONB 结构（预留，D8）

```jsonc
{
  "supported_types": ["single", "multi", "boolean"],
  "scoring": {
    "multi": "all-or-nothing",      // 或 "partial-credit"
    "passing_score": 0.7
  },
  "timer_seconds_per_question": null,
  "allow_skip": true,
  "show_explanation_during_quiz": false
}
```

本次不读取该字段，前端使用全局默认行为。

---

## 3. Alembic 迁移脚本

文件：`backend/alembic/versions/003_add_exams_and_relations.py`

```python
"""add exams and multi-exam relations

Revision ID: 003_multi_exam
Revises: 002_xxx
Create Date: 2026-05-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "003_multi_exam"
down_revision = "002_xxx"  # 替换为实际上一个版本

CIPT_DEFAULT_AI_PROFILE = {
    "translation_system_prompt": "<从现有 ai_service.py 抽出>",
    "explanation_system_prompt": "<从现有 ai_service.py 抽出>",
    "vocab_extract_system_prompt": "<从现有 ai_service.py 抽出>",
    "source_lang": "en",
    "target_lang": "zh-CN",
    "model_override": None,
    "enabled_features": ["translate", "explain", "vocab_extract"],
}

def upgrade():
    # 1. exams 表
    op.create_table(
        "exams",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("slug", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("short_name", sa.String(30), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("icon", sa.String(50), nullable=True),
        sa.Column("locale", sa.String(10), nullable=False, server_default="en-US"),
        sa.Column("visibility", sa.String(10), nullable=False, server_default="private"),
        sa.Column("owner_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("importer_profile", sa.String(50), nullable=False, server_default="examtopics-pdf"),
        sa.Column("ai_profile", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("quiz_profile", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_exams_listing", "exams", ["visibility", "is_active", "sort_order"])
    op.create_index("ix_exams_owner", "exams", ["owner_id"])

    # 2. user_exams 关联表
    op.create_table(
        "user_exams",
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("exam_id", sa.Integer, sa.ForeignKey("exams.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("role", sa.String(20), nullable=False, server_default="member"),
    )
    op.create_index("ix_user_exams_user", "user_exams", ["user_id"])
    op.create_index("ix_user_exams_exam", "user_exams", ["exam_id"])

    # 3. 插入默认 CIPT 公开考试
    conn = op.get_bind()
    cipt_id = conn.execute(sa.text("""
        INSERT INTO exams (slug, name, short_name, description, icon, locale,
                           visibility, owner_id, is_active, sort_order,
                           importer_profile, ai_profile, quiz_profile)
        VALUES ('cipt', 'CIPT 信息隐私技术认证', 'CIPT',
                'IAPP 信息隐私技术认证（Certified Information Privacy Technologist）',
                'Shield', 'en-US', 'public', NULL, true, 0,
                'examtopics-pdf', :ai, '{}'::jsonb)
        RETURNING id
    """), {"ai": sa.text("CAST(:p AS JSONB)").bindparams(p=CIPT_DEFAULT_AI_PROFILE)}).scalar()

    # 4. question_banks.exam_id
    op.add_column("question_banks", sa.Column("exam_id", sa.Integer, nullable=True))
    conn.execute(sa.text(f"UPDATE question_banks SET exam_id = {cipt_id}"))
    op.alter_column("question_banks", "exam_id", nullable=False)
    op.create_foreign_key("fk_banks_exam", "question_banks", "exams",
                          ["exam_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_banks_exam", "question_banks", ["exam_id"])

    # 5. vocabularies.exam_id
    op.add_column("vocabularies", sa.Column("exam_id", sa.Integer, nullable=True))
    op.create_foreign_key("fk_vocab_exam", "vocabularies", "exams",
                          ["exam_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_vocab_scope", "vocabularies", ["user_id", "exam_id"])
    conn.execute(sa.text(f"UPDATE vocabularies SET exam_id = {cipt_id} WHERE is_system = true"))

    # 6. users.active_exam_id
    op.add_column("users", sa.Column("active_exam_id", sa.Integer, nullable=True))
    op.create_foreign_key("fk_users_active_exam", "users", "exams",
                          ["active_exam_id"], ["id"], ondelete="SET NULL")
    conn.execute(sa.text(f"UPDATE users SET active_exam_id = {cipt_id}"))

    # 7. 全量回填 user_exams（所有现存用户都"加入"了 CIPT）
    conn.execute(sa.text(f"""
        INSERT INTO user_exams (user_id, exam_id, role)
        SELECT id, {cipt_id}, 'member' FROM users
        ON CONFLICT DO NOTHING
    """))

    # 8. wrong_answers 索引补强
    op.create_index("ix_wrong_user_question", "wrong_answers", ["user_id", "question_id"])


def downgrade():
    op.drop_index("ix_wrong_user_question", table_name="wrong_answers")
    op.drop_constraint("fk_users_active_exam", "users", type_="foreignkey")
    op.drop_column("users", "active_exam_id")
    op.drop_index("ix_vocab_scope", table_name="vocabularies")
    op.drop_constraint("fk_vocab_exam", "vocabularies", type_="foreignkey")
    op.drop_column("vocabularies", "exam_id")
    op.drop_index("ix_banks_exam", table_name="question_banks")
    op.drop_constraint("fk_banks_exam", "question_banks", type_="foreignkey")
    op.drop_column("question_banks", "exam_id")
    op.drop_table("user_exams")
    op.drop_index("ix_exams_owner", table_name="exams")
    op.drop_index("ix_exams_listing", table_name="exams")
    op.drop_table("exams")
```

---

## 4. 后端 API 契约

### 4.1 新增依赖：`get_active_exam`

`backend/app/api/deps.py`：

```python
async def get_active_exam(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    x_exam_slug: str | None = Header(None, alias="X-Exam-Slug"),
) -> Exam:
    """
    解析当前请求的考试上下文。
    优先级：HTTP Header X-Exam-Slug > User.active_exam_id
    若用户未加入该考试或考试不存在，抛 403/404。
    """
    if x_exam_slug:
        exam = await db.scalar(select(Exam).where(Exam.slug == x_exam_slug))
        if not exam:
            raise HTTPException(404, "Exam not found")
    elif user.active_exam_id:
        exam = await db.get(Exam, user.active_exam_id)
    else:
        raise HTTPException(400, "No active exam. Join an exam first.")

    # 校验加入关系
    membership = await db.scalar(
        select(UserExam).where(UserExam.user_id == user.id, UserExam.exam_id == exam.id)
    )
    if not membership and exam.visibility == "private" and exam.owner_id != user.id:
        raise HTTPException(403, "You have not joined this exam")
    return exam
```

### 4.2 新增路由

#### `/api/exams` —— 考试目录与订阅

| 方法 | 路径 | 权限 | 用途 |
|---|---|---|---|
| GET | `/api/exams` | 已登录 | 列表，query: `?scope=mine` (默认) `\|public` `\|all`(管理员) |
| GET | `/api/exams/{slug}` | 已登录 | 详情；私有考试仅 owner/member 可见 |
| POST | `/api/exams` | 已登录 | 创建考试（默认 `visibility=private`，自动加入并置为 owner） |
| PATCH | `/api/exams/{slug}` | owner/admin | 编辑基本信息与 ai_profile |
| DELETE | `/api/exams/{slug}` | owner/admin | 仅当 `question_banks` 为空时允许，否则返回 409 |
| POST | `/api/exams/{slug}/join` | 已登录 | 订阅公开考试（私有考试 403） |
| DELETE | `/api/exams/{slug}/leave` | 已登录 | 退订；owner 不可退订 |
| POST | `/api/exams/{slug}/publish` | admin | 将私有考试上架为 public |
| POST | `/api/exams/{slug}/unpublish` | admin | 公开降级为 private（owner 仍保留） |

**`POST /api/exams` 请求体**：

```json
{
  "slug": "pmp",
  "name": "PMP 项目管理专业人士",
  "short_name": "PMP",
  "description": "...",
  "icon": "Briefcase",
  "locale": "en-US",
  "ai_profile": { "...": "..." },
  "copy_ai_profile_from": "cipt"   // 可选；若提供则忽略 ai_profile，复制现有 cipt 配置
}
```

**响应（统一 ExamRead）**：

```json
{
  "id": 2,
  "slug": "pmp",
  "name": "PMP 项目管理专业人士",
  "short_name": "PMP",
  "description": "...",
  "icon": "Briefcase",
  "locale": "en-US",
  "visibility": "private",
  "owner": { "id": 5, "username": "alice" },
  "is_active": true,
  "joined": true,
  "role": "owner",
  "stats": { "bank_count": 0, "question_count": 0, "wrong_count": 0, "progress": 0.0 },
  "ai_profile": { "...": "..." },
  "created_at": "2026-05-24T10:00:00Z"
}
```

#### `/api/account/active-exam` —— 切换当前考试

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/account/active-exam` | body: `{ "slug": "pmp" }`；写入 `User.active_exam_id`；返回新的 `ExamRead` |

校验：用户必须已加入该考试，否则 400。

#### `/api/me` —— 增强响应

```json
{
  "id": 1,
  "username": "...",
  "is_admin": false,
  "active_exam": { "...ExamRead..." },     // 可能为 null（新用户尚未选择）
  "joined_exam_count": 3
}
```

完整考试列表通过 `GET /api/exams?scope=mine` 获取，避免 `/api/me` 响应过大。

### 4.3 现有路由改造

| 路由 | 改造 |
|---|---|
| `GET /api/banks` | 注入 `Depends(get_active_exam)`，列表 `WHERE exam_id = active_exam.id` |
| `POST /api/banks/import` | 请求体新增 `exam_id`（必填），落库时绑定；`exam_id` 必须是当前用户加入的考试 |
| `GET /api/banks/{id}` | 加权限校验：bank 所属 exam 是否对当前用户可见 |
| `GET /api/wrong` | `JOIN questions q JOIN question_banks b ON q.bank_id = b.id WHERE b.exam_id = :active` |
| `GET /api/quiz/history` | 同上 |
| `GET /api/vocab` | 见 §4.4 双层过滤逻辑 |
| `POST /api/vocab` | 请求体加可选 `exam_id`（不传 = 个人跨考试本；传 = 当前考试） |
| `POST /api/ai/translate`, `POST /api/ai/explain` | 通过 question→bank→exam 取 `ai_profile`，覆盖全局 prompt |

### 4.4 词汇本双层查询（D3 落地）

**`GET /api/vocab` query 参数**：

| 参数 | 含义 | 默认 |
|---|---|---|
| `scope` | `personal` / `exam_official` / `exam_personal` / `all` | `all` |
| `q` | 搜索词 | — |
| `page`, `page_size` | 分页 | 1, 20 |

**SQL 模板**（`scope=all`）：

```sql
SELECT * FROM vocabularies
WHERE
  (exam_id IS NULL AND user_id = :me)              -- personal
  OR (exam_id = :active AND user_id IS NULL)       -- exam_official
  OR (exam_id = :active AND user_id = :me)         -- exam_personal
ORDER BY updated_at DESC;
```

每条记录响应增加 `scope_label` 字段：`"personal"` / `"exam_official"` / `"exam_personal"`，前端用于 Tab 渲染。

### 4.5 错误码约定

| HTTP | code | 场景 |
|---|---|---|
| 400 | `EXAM_REQUIRED` | 操作需要考试上下文但用户无 active_exam |
| 403 | `EXAM_NOT_JOINED` | 用户未加入访问的考试 |
| 403 | `EXAM_PRIVATE` | 试图访问他人私有考试 |
| 404 | `EXAM_NOT_FOUND` | slug 不存在或已下架 |
| 409 | `EXAM_HAS_BANKS` | 删除时仍存在题库 |
| 409 | `BANK_EXAM_MISMATCH` | 试图把题目从一个考试移到另一个（D4 硬约束） |

---

## 5. 前端设计

### 5.1 路由结构

| 路径 | 组件 | 说明 |
|---|---|---|
| `/` | 重定向到 `/exams/{activeSlug}/dashboard` 或 `/onboarding` | |
| `/onboarding` | `FirstTimeOnboarding.vue` | 新用户首登 |
| `/exams` | `ExamCatalogPage.vue` | 考试目录（我的 + 可订阅 + 创建入口） |
| `/exams/new` | `ExamCreatePage.vue` | 创建私有考试 |
| `/exams/:examSlug/dashboard` | `ExamDashboard.vue` | 当前考试首页 |
| `/exams/:examSlug/banks` | `BankList.vue` | 题库列表 |
| `/exams/:examSlug/banks/:bankId` | `BankDetail.vue` | |
| `/exams/:examSlug/quiz/:bankId` | `QuizSession.vue` | 答题（meta: locked=true） |
| `/exams/:examSlug/wrong` | `WrongBook.vue` | 错题本 |
| `/exams/:examSlug/vocab` | `VocabBook.vue` | 词汇本（三 Tab） |
| `/me/overview` | `GlobalOverview.vue` | 跨考试汇总卡片 |
| `/admin/exams` | `AdminExamList.vue` | 管理员：考试管理 |
| `/admin/exams/:slug/edit` | `AdminExamEditor.vue` | 编辑（基本信息/AI Profile/上下架） |

**兼容性**：旧链接 `/banks`, `/banks/:id`, `/wrong`, `/vocab` 通过路由守卫重定向到带 `examSlug` 的新路径（slug 从 store 取 active 或 `/api/banks/:id` 反查）。

### 5.2 Pinia Store

#### `stores/exam.ts`

```ts
export const useExamStore = defineStore('exam', () => {
  const current = ref<ExamRead | null>(null)
  const myExams = ref<ExamRead[]>([])
  const loaded = ref(false)

  async function bootstrap() {
    const me = await api.get('/me')
    current.value = me.active_exam
    if (me.active_exam) {
      myExams.value = await api.get('/exams?scope=mine')
    }
    loaded.value = true
  }

  async function switchTo(slug: string) {
    const exam = await api.post('/account/active-exam', { slug })
    current.value = exam
    // 失效所有依赖考试上下文的 SWR 缓存
    await mutateMatching(key => Array.isArray(key) && key.includes('exam-scoped'))
    router.push(`/exams/${slug}/dashboard`)
  }

  async function joinExam(slug: string) { /* POST join, 刷新 myExams */ }
  async function leaveExam(slug: string) { /* DELETE leave, 处理 active 失效 */ }
  async function createExam(payload: ExamCreate) { /* POST exams, 自动加入 */ }

  return { current, myExams, loaded, bootstrap, switchTo, joinExam, leaveExam, createExam }
})
```

#### 全局 axios 拦截器

```ts
axios.interceptors.request.use((config) => {
  const exam = useExamStore()
  if (exam.current && config.url && !config.url.startsWith('/exams') && !config.url.startsWith('/admin')) {
    config.headers['X-Exam-Slug'] = exam.current.slug
  }
  return config
})
```

> 后端通过 `X-Exam-Slug` Header 显式确认前端意图，避免"路由切换 + 网络飞行中"出现错配。

### 5.3 路由守卫

```ts
router.beforeEach(async (to) => {
  const exam = useExamStore()
  if (!exam.loaded) await exam.bootstrap()

  // 新用户引导
  if (!exam.current && to.name !== 'onboarding' && to.name !== 'exam-catalog') {
    return { name: 'onboarding' }
  }

  // URL 携带的 slug 优先于 store
  const urlSlug = to.params.examSlug as string | undefined
  if (urlSlug && urlSlug !== exam.current?.slug) {
    try {
      await exam.switchTo(urlSlug)
    } catch {
      return { name: 'exam-catalog' }
    }
  }

  // 旧链接补 slug
  if (!urlSlug && to.meta.examScoped) {
    return { ...to, params: { ...to.params, examSlug: exam.current!.slug } }
  }
})
```

### 5.4 关键组件

#### 5.4.1 `ExamSwitcher.vue`（顶栏）

- shadcn-vue `DropdownMenu`，宽 260px
- 头部：搜索框（≥6 个考试时出现）
- 主体：分组「我的考试」+「最近」（可选）
- 底部：「+ 添加考试」→ `/exams`、「⚙ 管理考试」（管理员）
- 当前选中项左侧 2px `border-l border-primary`，背景 `bg-accent`
- 答题中（`route.meta.locked`）禁用按钮，tooltip「答题中无法切换考试」

#### 5.4.2 `ExamCatalogPage.vue`

布局：
```
┌─────────────────────────────────────────┐
│ 考试目录                                 │
│                                         │
│ 我的考试 (3)                  [+ 创建]  │
│ ┌─────┐ ┌─────┐ ┌─────┐                │
│ │CIPT │ │ PMP │ │ ... │                │
│ └─────┘ └─────┘ └─────┘                │
│                                         │
│ 可订阅 (5)                              │
│ ┌─────┐ ┌─────┐ ...                    │
│ │软考 │ │考研 │                         │
│ │[+加入]│[+加入]│                       │
│ └─────┘ └─────┘                        │
└─────────────────────────────────────────┘
```

- Grid: `grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4`
- 卡片显示：图标、`short_name`、`name`、题量、个人进度、操作按钮（"进入" / "+ 加入"）

#### 5.4.3 `ExamCreatePage.vue`

字段：

- `short_name` *
- `name` *
- `slug` *（自动从 short_name 生成，校验唯一）
- `icon`（lucide 选择器）
- `description`（textarea）
- `locale`（下拉）
- AI Profile 配置：单选「复制 CIPT 配置」/「自定义」
  - 自定义时展开 prompt 编辑器（textarea，字数提示）

提交后跳到 `/exams/{slug}/dashboard`，自动设为 active。

#### 5.4.4 `FirstTimeOnboarding.vue`

- 列出所有 `visibility = public` 考试卡片，单选
- 底部「我要的考试不在这里」→ 跳到 `/exams/new`
- 选中并提交后：调 `join` + `active-exam`，进入 dashboard

#### 5.4.5 `VocabBook.vue`（三 Tab）

```
词汇本                                    [+ 添加]
┌────────────────┬────────────────┬──────────────────┐
│ 我的单词本(跨)  │ CIPT 术语(官方) │ 我在 CIPT 添加的 │
└────────────────┴────────────────┴──────────────────┘
```

- Tab1 调 `?scope=personal`，Tab2 `?scope=exam_official`，Tab3 `?scope=exam_personal`
- 添加弹窗的「保存到」单选：
  - "我的单词本（所有考试可见）" → `exam_id = null`
  - "仅 {currentExam.short_name}" → `exam_id = active_exam.id`
- 题目页"加入生词本"按钮默认绑定到当前考试

#### 5.4.6 `AdminExamEditor.vue`

三 Tab：

| Tab | 字段 |
|---|---|
| 基本信息 | name, short_name, slug（不可改）, icon, description, locale, is_active, sort_order |
| AI Profile | translation_prompt, explanation_prompt, vocab_extract_prompt, source_lang, target_lang, model_override |
| 上下架 | visibility 切换、删除（题库非空时禁用） |

### 5.5 现有页面文案动态化

所有出现 "CIPT" 字样的页面替换为 `{{ examStore.current?.short_name }}`：

- 题库列表标题
- 错题本标题
- 词汇本 Tab 标题（"CIPT 术语" → `${shortName} 术语`）
- 仪表盘欢迎语

### 5.6 视觉设计要点

- **不为每门考试引入新主色**，统一使用 design tokens
- 考试图标用 lucide，染色 `text-muted-foreground`
- 切换器选中项使用 `bg-accent` + 左侧 `border-l-2 border-primary`
- 空状态文案双重描述："{考试名} 还没有题库，立即导入第一份"

---

## 6. 权限与可见性矩阵

| 操作 | 普通用户（未加入） | 普通用户（已加入） | 私有考试 owner | 平台 admin |
|---|---|---|---|---|
| 列表中看到 public exam | ✓ | ✓ | ✓ | ✓ |
| 列表中看到 private exam | ✗ | ✗（除非自己 owner） | ✓ | ✓ |
| 进入 public exam（题库/刷题） | ✗（需先 join） | ✓ | ✓ | ✓ |
| 进入 private exam | ✗ | ✓（已 join 即视为成员） | ✓ | ✓ |
| 创建考试 | ✓（默认 private） | — | — | ✓ |
| 编辑考试基本信息 | ✗ | ✗ | ✓ | ✓ |
| 编辑 AI Profile | ✗ | ✗ | ✓ | ✓ |
| 上架/下架（visibility） | ✗ | ✗ | ✗ | ✓ |
| 删除考试 | ✗ | ✗ | ✓（题库为空） | ✓ |
| 退出考试 | — | ✓ | ✗（owner 不可退） | ✓ |

**RLS 等价的应用层校验**：所有列表/详情接口在 SQL 上加 `WHERE` 条件而非应用层 if，避免漏判。

---

## 7. 兼容性与回滚

### 7.1 老用户体验承诺

| 改动 | 老用户感知 |
|---|---|
| 数据迁移 | 全部存量用户自动加入 CIPT，`active_exam_id` 指向 CIPT |
| 顶栏多了切换器 | 显示 "CIPT"，下拉只有 CIPT 一项 |
| URL 变化 | 旧 URL 301 重定向，收藏夹仍可用 |
| 词汇页多了 Tab | 默认进入"CIPT 术语"，原 `is_system=true` 数据已归类 |
| 错题/题库 | 内容完全相同，仅标题加 "CIPT" 前缀 |
| AI 翻译/解析 | 行为不变（CIPT.ai_profile 直接复用现有 prompt） |

### 7.2 回滚

- Alembic `downgrade` 完整反向
- 前端通过功能开关 `VITE_ENABLE_MULTI_EXAM=false` 隐藏切换器与目录页（路由仍可用）
- 后端 API 兼容期保留旧路由别名 `/banks` → `/exams/{active}/banks`，至少保留一个版本周期

---

## 8. 分阶段交付计划

### PR-1 · 后端基础（数据模型 + 迁移 + Exam CRUD）

**范围**：

- [ ] 新增 `Exam`、`UserExam` 模型与 Pydantic schema
- [ ] 迁移脚本 `003_add_exams_and_relations.py`
- [ ] `/api/exams/*`、`/api/account/active-exam` 路由
- [ ] `get_active_exam` 依赖
- [ ] 现有路由（banks/wrong/vocab/quiz/ai）注入考试上下文与隐式过滤
- [ ] AI Profile 抽取（从代码常量迁到 CIPT 行的 ai_profile）
- [ ] 单元测试覆盖：迁移、权限矩阵、双层词汇查询

**验收**：旧前端零改动情况下接口行为不变（CIPT 用户无感）。

### PR-2 · 前端基础（切换器 + Pinia + 主要页面改造）

**范围**：

- [ ] `useExamStore` + `bootstrap` + axios 拦截器
- [ ] 路由表重构（`/exams/:examSlug/...`），守卫 + 旧链接重定向
- [ ] `ExamSwitcher.vue` 顶栏挂载
- [ ] 题库导入弹窗加"所属考试"下拉
- [ ] 题库/错题本/词汇本/仪表盘标题动态化
- [ ] `VocabBook.vue` 三 Tab + 添加弹窗作用域选择

**验收**：CIPT 用户主流程零行为变化；浏览器 URL 改为带 slug。

### PR-3 · 考试管理与新用户流程

**范围**：

- [ ] `ExamCatalogPage.vue`、`ExamCreatePage.vue`
- [ ] `FirstTimeOnboarding.vue`
- [ ] `AdminExamList.vue`、`AdminExamEditor.vue`（含 AI Profile 编辑）
- [ ] 「+ 加入」 / 「退出」 / 「上架」 / 「下架」 全流程

**验收**：能新建第二门考试 PMP，导入题库，刷题 + AI 解析使用其专属 prompt。

### PR-4（后续 spec）

- ImporterProfile 抽象（D7）
- QuizProfile 扩展、新题型（D8）
- 考试社区市场、订阅评分

---

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 用户在两门考试间切换时旧请求落到错误 exam | 数据错乱 | 全局 axios 拦截器带 `X-Exam-Slug`，后端校验与 active_exam 一致 |
| 创建考试失败但已建关联 | 脏数据 | `POST /api/exams` 整体事务，失败回滚 |
| AI Profile prompt 配置错误导致 AI 输出异常 | 用户体验下降 | AdminEditor 提供"测试 prompt"按钮（输入样例题→预览输出） |
| 老前端调用未带 `X-Exam-Slug` | 接口 400 | 后端兜底用 `User.active_exam_id` |
| owner 退订路径 | 数据孤儿 | 显式禁止 owner 退订；如要让出，先转让 owner |
| 切换考试时 SWR 缓存未失效 | 显示上一门考试数据 | `mutate` matcher 按 `'exam-scoped'` key 全量失效 |

---

## 10. 验收清单

- [ ] 数据库迁移在测试环境成功执行，CIPT 数据完整可查
- [ ] 老 CIPT 用户登录后看到的题库/错题/词汇与改造前完全一致
- [ ] 用户可创建私有考试 PMP，导入题库，独立刷题
- [ ] 切换考试后错题本仅显示当前考试错题（D2 验证）
- [ ] 词汇本三 Tab 数据划分正确（D3 验证）
- [ ] 试图通过 API 把题目移到其他考试返回 409（D4 验证）
- [ ] 普通用户看不到他人私有考试（权限矩阵验证）
- [ ] 管理员能将私有考试上架为 public
- [ ] AI 翻译/解析按 exam.ai_profile 走对应 prompt
- [ ] 切换器在答题中禁用
- [ ] 旧 URL 301 重定向工作正常

---

## 11. 附录

### 11.1 ExamRead Pydantic Schema

```python
class ExamStats(BaseModel):
    bank_count: int
    question_count: int
    wrong_count: int
    progress: float  # 0.0 ~ 1.0

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
    visibility: Literal["public", "private"]
    owner: ExamOwner | None
    is_active: bool
    joined: bool
    role: Literal["member", "editor", "owner"] | None
    stats: ExamStats
    ai_profile: dict
    created_at: datetime
```

### 11.2 文件影响清单

**后端新增**：
- `backend/app/models/exam.py`
- `backend/app/models/user_exam.py`
- `backend/app/schemas/exam.py`
- `backend/app/api/routes/exams.py`
- `backend/alembic/versions/003_add_exams_and_relations.py`

**后端修改**：
- `backend/app/models/__init__.py`、`user.py`、`question_bank.py`、`vocabulary.py`
- `backend/app/api/deps.py`
- `backend/app/api/routes/banks.py`、`wrong.py`、`vocab.py`、`quiz.py`、`ai.py`、`account.py`
- `backend/app/services/ai_service.py`、`smart_import_service.py`
- `backend/app/schemas/auth.py`、`bank.py`、`vocab.py`

**前端新增**：
- `frontend/src/stores/exam.ts`
- `frontend/src/components/ExamSwitcher.vue`
- `frontend/src/views/ExamCatalogPage.vue`、`ExamCreatePage.vue`、`FirstTimeOnboarding.vue`、`ExamDashboard.vue`
- `frontend/src/views/admin/AdminExamList.vue`、`AdminExamEditor.vue`
- `frontend/src/views/me/GlobalOverview.vue`
- `frontend/src/api/exams.ts`

**前端修改**：
- `frontend/src/router/index.ts`
- `frontend/src/App.vue` / `Layout.vue`
- `frontend/src/api/index.ts`（axios 拦截器）
- `frontend/src/views/Banks/*`、`Wrong/*`、`Vocab/*`、`Quiz/*`
- 所有含 "CIPT" 硬编码文案的组件

---

**文档结束**
