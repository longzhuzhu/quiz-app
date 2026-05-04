# Quiz App 智能题库导入方案（FastAPI + PostgreSQL + Python Worker）

## 1. 方案定位

本文档基于当前最终技术选型，重新设计题库导入模块。

最终技术选型：

```text
后端框架：FastAPI
语言：Python
数据库：PostgreSQL
向量能力：pgvector
任务调度：PostgreSQL 任务表 + Python Worker
ORM：SQLAlchemy 2.x
迁移：Alembic
数据校验：Pydantic
PDF 解析：PyMuPDF / pdfplumber
DOCX 解析：python-docx
XLSX 解析：openpyxl
LLM：OpenAI-compatible API
Embedding：Embedding API
文件存储：本地文件系统
```

明确不使用：

```text
Flask
SQLite
Redis
MQ
Celery
RQ
ARQ
Dramatiq
RabbitMQ
Kafka
Qdrant
Milvus
Java
```

核心目标：

```text
废弃旧的快速同步导入 / 规则导入；
统一改为 FastAPI + PostgreSQL + Python Worker 驱动的 LLM 智能导入。
```

---

## 2. 背景与问题

当前旧导入模块存在的问题：

1. 规则解析依赖固定格式；
2. 不同 PDF 题库格式兼容性差；
3. 场景题、跨页题、答案表分离题容易解析失败；
4. PDF 页眉页脚、广告、水印容易混入题干；
5. 同步导入体验差，用户无法清楚看到进度；
6. 解析失败后缺少复核和重试机制；
7. 后续扩展向量去重、相似样例召回、自动标签困难。

因此，新方案不再维护旧规则导入，而是统一走：

```text
文件上传
→ 创建导入任务
→ Python Worker 异步处理
→ 文档抽取
→ Chunk 切片
→ 向量召回相似样例
→ LLM 结构化解析
→ Pydantic / 程序校验
→ 高置信度自动入库
→ 低置信度人工复核
```

---

## 3. 总体架构

```mermaid
flowchart TD
    A[Vue 前端上传文件] --> B[FastAPI 创建 ImportJob]
    B --> C[PostgreSQL 写入 background_jobs]
    C --> D[Python Worker 轮询任务]
    D --> E[FOR UPDATE SKIP LOCKED 抢任务]
    E --> F[文件文本抽取 PDF/DOCX/XLSX]
    F --> G[文档清洗与 Chunk 切片]
    G --> H[Embedding 生成]
    H --> I[pgvector 召回相似解析样例]
    I --> J[LLM 结构化解析]
    J --> K[Pydantic JSON 校验]
    K --> L[质量评分/答案证据校验/去重]
    L --> M{置信度是否足够}
    M -- 是 --> N[自动写入 Question]
    M -- 否 --> O[进入人工复核]
    O --> P[人工确认后入库]
    N --> Q[生成导入报告]
    P --> Q
```

---

## 4. 核心设计原则

### 4.1 FastAPI 只负责 API，不直接执行长任务

FastAPI 负责用户认证、文件上传、创建导入任务、查询任务状态、查询待复核题目、提交复核结果和查询导入报告。

FastAPI 不负责长时间执行 PDF/LLM 解析，避免请求超时和进程阻塞。

### 4.2 PostgreSQL 同时承担业务库和任务调度库

PostgreSQL 负责业务数据、导入任务、Worker 抢任务、Worker 心跳、失败重试、LLM 缓存、pgvector 向量检索、人工复核和导入报告。

### 4.3 Python Worker 是唯一后台任务执行器

Worker 负责轮询 `background_jobs`、抢占任务、执行智能导入、定期心跳、失败重试和任务状态更新。

### 4.4 LLM 负责理解，程序负责校验

LLM 负责识别题目结构、题干、选项、答案、解析、场景题，修复 PDF 换行并输出标准 JSON。

程序负责 JSON Schema 校验、答案是否在选项内、答案证据是否来自原文、选项数量是否合理、重复题检测、置信度评分和入库事务。

---

## 5. 新旧导入对比

| 项目 | 旧规则导入 | 新智能导入 |
|---|---|---|
| API 框架 | Flask | FastAPI |
| 数据库 | SQLite | PostgreSQL |
| 解析方式 | 正则 / 固定格式 | LLM + 程序校验 |
| 任务方式 | 同步 / 简单后台 | PostgreSQL Worker |
| 是否支持多格式 | 弱 | 强 |
| 是否支持复核 | 弱 | 强 |
| 是否支持向量去重 | 无 | pgvector |
| 是否支持相似样例召回 | 无 | 支持 |
| 是否可恢复 | 弱 | 支持 heartbeat / lease |
| 是否可观测 | 弱 | 任务状态 / 导入报告 |

---

## 6. 推荐项目目录结构

```text
backend/
├── app/
│   ├── main.py
│   ├── core/
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── security.py
│   │   └── storage.py
│   ├── api/
│   │   ├── deps.py
│   │   └── routes/
│   │       ├── auth.py
│   │       ├── banks.py
│   │       ├── questions.py
│   │       ├── import_jobs.py
│   │       ├── import_review.py
│   │       └── background_jobs.py
│   ├── models/
│   │   ├── user.py
│   │   ├── question_bank.py
│   │   ├── question.py
│   │   ├── background_job.py
│   │   ├── import_job.py
│   │   ├── import_chunk.py
│   │   ├── import_parsed_question.py
│   │   ├── import_review_item.py
│   │   ├── llm_parse_cache.py
│   │   └── vector_index.py
│   ├── schemas/
│   │   ├── auth.py
│   │   ├── bank.py
│   │   ├── question.py
│   │   ├── import_job.py
│   │   ├── import_review.py
│   │   └── llm_parse.py
│   ├── services/
│   │   ├── auth_service.py
│   │   ├── bank_service.py
│   │   ├── question_service.py
│   │   ├── job_service.py
│   │   └── smart_import/
│   │       ├── orchestrator.py
│   │       ├── file_extractor.py
│   │       ├── pdf_extractor.py
│   │       ├── docx_extractor.py
│   │       ├── xlsx_extractor.py
│   │       ├── normalizer.py
│   │       ├── chunker.py
│   │       ├── prompt_builder.py
│   │       ├── llm_parser.py
│   │       ├── schema_validator.py
│   │       ├── quality_checker.py
│   │       ├── duplicate_detector.py
│   │       ├── vector_service.py
│   │       ├── cache_service.py
│   │       └── import_writer.py
│   └── workers/
│       ├── job_worker.py
│       └── job_runner.py
├── alembic/
├── requirements.txt
├── run_api.py
└── run_worker.py
```

---

## 7. FastAPI API 设计

### 7.1 创建智能导入任务

```http
POST /api/banks/{bank_id}/import
Content-Type: multipart/form-data
```

旧同步导入接口废弃，该接口统一创建异步智能导入任务。

请求参数：

| 参数 | 类型 | 说明 |
|---|---|---|
| file | File | PDF / DOCX / XLSX |
| auto_import | bool | 高置信度题目是否自动入库 |
| use_vector | bool | 是否使用 pgvector 召回样例 |
| use_llm_cache | bool | 是否使用 LLM 缓存 |

返回：

```json
{
  "import_job_id": 123,
  "background_job_id": 456,
  "status": "pending"
}
```

FastAPI 示例：

```python
@router.post("/{bank_id}/import", response_model=ImportJobCreateResponse)
async def create_import_job(
    bank_id: int,
    file: UploadFile = File(...),
    auto_import: bool = Form(True),
    use_vector: bool = Form(True),
    use_llm_cache: bool = Form(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return create_smart_import_job(
        db=db,
        bank_id=bank_id,
        file=file,
        user_id=current_user.id,
        auto_import=auto_import,
        use_vector=use_vector,
        use_llm_cache=use_llm_cache,
    )
```

### 7.2 查询导入任务状态

```http
GET /api/import-jobs/{import_job_id}
```

返回：

```json
{
  "id": 123,
  "bank_id": 1,
  "file_name": "CIPT.pdf",
  "status": "review_required",
  "total_chunks": 80,
  "parsed_questions": 210,
  "imported_questions": 168,
  "review_questions": 42,
  "failed_chunks": 0,
  "summary": {}
}
```

### 7.3 查询导入 Chunk

```http
GET /api/import-jobs/{import_job_id}/chunks
```

### 7.4 查询待复核题目

```http
GET /api/import-jobs/{import_job_id}/review-items
```

### 7.5 接受复核题目并入库

```http
POST /api/import-review/{parsed_question_id}/accept
```

请求：

```json
{
  "content": "Which of the following...",
  "options": [
    {"label": "A", "text": "..."},
    {"label": "B", "text": "..."}
  ],
  "correct_answer": ["A"],
  "explanation": "..."
}
```

### 7.6 跳过复核题目

```http
POST /api/import-review/{parsed_question_id}/skip
```

### 7.7 重新解析 Chunk

```http
POST /api/import-chunks/{chunk_id}/reparse
```

---

## 8. PostgreSQL 表设计

### 8.1 background_jobs

用于替代 MQ / Redis / Celery。

```sql
CREATE TABLE background_jobs (
    id BIGSERIAL PRIMARY KEY,
    job_type VARCHAR(64) NOT NULL,
    payload_json JSONB NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',

    progress_total INT DEFAULT 0,
    progress_done INT DEFAULT 0,
    status_message TEXT,

    worker_id VARCHAR(128),
    locked_at TIMESTAMP,
    locked_until TIMESTAMP,
    heartbeat_at TIMESTAMP,

    attempt_count INT DEFAULT 0,
    max_attempt_count INT DEFAULT 3,
    error_message TEXT,

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_background_jobs_status ON background_jobs(status);
CREATE INDEX idx_background_jobs_locked_until ON background_jobs(locked_until);
CREATE INDEX idx_background_jobs_job_type ON background_jobs(job_type);
```

状态：

```text
pending
running
succeeded
failed
cancelled
```

### 8.2 import_jobs

一次文件导入对应一个 ImportJob。

```sql
CREATE TABLE import_jobs (
    id BIGSERIAL PRIMARY KEY,
    bank_id BIGINT NOT NULL,
    background_job_id BIGINT REFERENCES background_jobs(id),

    file_name VARCHAR(300) NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    file_hash CHAR(64) NOT NULL,
    file_type VARCHAR(32) NOT NULL,

    status VARCHAR(32) NOT NULL DEFAULT 'pending',

    total_pages INT DEFAULT 0,
    total_chunks INT DEFAULT 0,
    parsed_questions INT DEFAULT 0,
    imported_questions INT DEFAULT 0,
    review_questions INT DEFAULT 0,
    failed_chunks INT DEFAULT 0,

    config_json JSONB,
    summary_json JSONB,
    error_message TEXT,

    created_by BIGINT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_import_jobs_bank_id ON import_jobs(bank_id);
CREATE INDEX idx_import_jobs_status ON import_jobs(status);
CREATE INDEX idx_import_jobs_file_hash ON import_jobs(file_hash);
```

状态：

```text
pending
extracting
chunking
embedding
parsing
validating
importing
review_required
imported
partial_imported
failed
cancelled
```

### 8.3 import_chunks

保存文档切片。

```sql
CREATE TABLE import_chunks (
    id BIGSERIAL PRIMARY KEY,
    import_job_id BIGINT NOT NULL REFERENCES import_jobs(id),

    chunk_no INT NOT NULL,
    start_page INT,
    end_page INT,

    chunk_text TEXT NOT NULL,
    normalized_text TEXT,
    chunk_hash CHAR(64) NOT NULL,

    status VARCHAR(32) DEFAULT 'pending',

    llm_request_json JSONB,
    llm_response_json JSONB,
    issues_json JSONB,

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_import_chunks_job_id ON import_chunks(import_job_id);
CREATE INDEX idx_import_chunks_status ON import_chunks(status);
CREATE INDEX idx_import_chunks_hash ON import_chunks(chunk_hash);
```

### 8.4 import_parsed_questions

保存 LLM 解析后的题目草稿。

```sql
CREATE TABLE import_parsed_questions (
    id BIGSERIAL PRIMARY KEY,
    import_job_id BIGINT NOT NULL REFERENCES import_jobs(id),
    chunk_id BIGINT REFERENCES import_chunks(id),

    source_question_no VARCHAR(64),
    question_type VARCHAR(32),

    scenario_text TEXT,
    content TEXT NOT NULL,
    options_json JSONB NOT NULL,
    correct_answer JSONB,
    explanation TEXT,
    references_json JSONB,

    source_evidence_json JSONB,

    llm_confidence NUMERIC(5,4),
    final_confidence NUMERIC(5,4),

    issues_json JSONB,
    duplicate_json JSONB,

    review_status VARCHAR(32) DEFAULT 'pending',
    import_status VARCHAR(32) DEFAULT 'waiting',

    imported_question_id BIGINT,

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_import_parsed_questions_job_id ON import_parsed_questions(import_job_id);
CREATE INDEX idx_import_parsed_questions_review_status ON import_parsed_questions(review_status);
CREATE INDEX idx_import_parsed_questions_import_status ON import_parsed_questions(import_status);
```

### 8.5 import_review_items

保存复核记录。

```sql
CREATE TABLE import_review_items (
    id BIGSERIAL PRIMARY KEY,
    import_job_id BIGINT NOT NULL REFERENCES import_jobs(id),
    parsed_question_id BIGINT NOT NULL REFERENCES import_parsed_questions(id),

    review_type VARCHAR(64),
    severity VARCHAR(32),

    before_json JSONB,
    after_json JSONB,

    status VARCHAR(32) DEFAULT 'pending',
    reviewer_id BIGINT,
    reviewed_at TIMESTAMP,

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### 8.6 llm_parse_cache

使用 PostgreSQL 替代 Redis 缓存。

```sql
CREATE TABLE llm_parse_cache (
    id BIGSERIAL PRIMARY KEY,
    cache_key CHAR(64) UNIQUE NOT NULL,

    model_name VARCHAR(128),
    prompt_version VARCHAR(64),
    chunk_hash CHAR(64),

    request_json JSONB,
    response_json JSONB,

    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_llm_parse_cache_chunk_hash ON llm_parse_cache(chunk_hash);
```

### 8.7 vector_index

使用 pgvector 做相似样例召回、重复题检测、标签推荐。

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE vector_index (
    id BIGSERIAL PRIMARY KEY,

    vector_type VARCHAR(64) NOT NULL,
    ref_id VARCHAR(128) NOT NULL,
    bank_id BIGINT,

    text_content TEXT NOT NULL,
    metadata_json JSONB,

    embedding VECTOR(1536),

    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_vector_index_type ON vector_index(vector_type);
CREATE INDEX idx_vector_index_bank_id ON vector_index(bank_id);
CREATE INDEX idx_vector_index_embedding
ON vector_index
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```

`vector_type`：

```text
DOCUMENT_STYLE
PARSED_EXAMPLE
QUESTION
KNOWLEDGE_TAG
```

---

## 9. Worker 设计

### 9.1 Worker 主循环

```python
def worker_loop():
    worker_id = build_worker_id()

    while True:
        job = claim_next_job(worker_id)

        if not job:
            time.sleep(3)
            continue

        try:
            run_job(job, worker_id)
            mark_job_succeeded(job.id)
        except Exception as exc:
            mark_job_failed_or_retry(job.id, str(exc), worker_id)
```

### 9.2 PostgreSQL 抢任务 SQL

```sql
WITH picked AS (
    SELECT id
    FROM background_jobs
    WHERE status = 'pending'
       OR (
            status = 'running'
            AND locked_until < NOW()
          )
    ORDER BY created_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
UPDATE background_jobs j
SET
    status = 'running',
    worker_id = :worker_id,
    locked_at = NOW(),
    locked_until = NOW() + INTERVAL '10 minutes',
    heartbeat_at = NOW(),
    updated_at = NOW()
FROM picked
WHERE j.id = picked.id
RETURNING j.*;
```

### 9.3 Worker 心跳

```sql
UPDATE background_jobs
SET
    heartbeat_at = NOW(),
    locked_until = NOW() + INTERVAL '10 minutes',
    progress_done = :progress_done,
    progress_total = :progress_total,
    status_message = :status_message,
    updated_at = NOW()
WHERE id = :job_id
  AND worker_id = :worker_id;
```

### 9.4 任务类型

```python
JOB_TYPE_QUESTION_IMPORT_LLM = "question_import_llm"
```

payload：

```json
{
  "import_job_id": 123,
  "bank_id": 1,
  "file_path": "storage/imports/xxx.pdf",
  "file_name": "xxx.pdf",
  "file_type": "pdf",
  "auto_import": true,
  "use_vector": true,
  "use_llm_cache": true
}
```

---

## 10. 智能导入主流程

### 10.1 流程步骤

1. Worker 领取 `question_import_llm` 任务；
2. 读取 `import_job`；
3. 更新状态 `extracting`；
4. 根据 `file_type` 调用对应 extractor；
5. 得到 `DocumentText`；
6. 清洗文本；
7. 切 chunk；
8. 保存 `import_chunks`；
9. 更新状态 `parsing`；
10. 遍历 chunk；
11. 生成 chunk embedding；
12. pgvector 召回相似解析样例；
13. 构建 Prompt；
14. 调用 LLM；
15. Pydantic 校验 LLM JSON；
16. 运行质量检查；
17. 运行重复题检测；
18. 保存 `import_parsed_questions`；
19. 高置信度自动写入 `questions`；
20. 低置信度生成 review item；
21. 汇总导入结果；
22. 更新 import_job 状态。

### 10.2 orchestrator 伪代码

```python
def run_smart_import(db: Session, background_job: BackgroundJob) -> None:
    payload = background_job.payload_json
    import_job = get_import_job(db, payload["import_job_id"])

    update_import_job_status(db, import_job, "extracting")

    document = extract_file_text(
        file_path=import_job.file_path,
        file_type=import_job.file_type,
    )

    update_import_job_status(db, import_job, "chunking")

    chunks = chunk_document(document)
    save_import_chunks(db, import_job, chunks)

    update_import_job_status(db, import_job, "parsing")

    for index, chunk in enumerate(chunks, start=1):
        parse_and_save_chunk(db, import_job, chunk)

        heartbeat_job(
            db=db,
            job=background_job,
            progress_done=index,
            progress_total=len(chunks),
            message=f"解析 Chunk {index}/{len(chunks)}",
        )

    update_import_job_status(db, import_job, "validating")

    summary = validate_and_finalize_import(db, import_job)

    if summary["review_questions"] > 0:
        update_import_job_status(db, import_job, "review_required", summary)
    else:
        update_import_job_status(db, import_job, "imported", summary)
```

---

## 11. 文件抽取设计

统一输出 `DocumentText`。

```python
class DocumentPage(BaseModel):
    page_no: int | None = None
    text: str
    metadata: dict = {}


class DocumentText(BaseModel):
    file_type: str
    pages: list[DocumentPage]
    full_text: str
```

PDF 优先使用 PyMuPDF，辅助使用 pdfplumber。DOCX 使用 python-docx。XLSX 使用 openpyxl，行转文本时保留 sheet、row 信息，便于复核。

---

## 12. Chunk 切片策略

不要整份文档一次性丢给 LLM。

推荐策略：

```text
先按页 / sheet / paragraph 粗切
再按疑似题号切题块
最后按 token 限制合并或拆分
```

疑似题号信号：

```regex
^\s*\d{1,4}\.\s+
^\s*Question\s*:\s*\d+
^\s*Question\s+\d+
^\s*QUESTION\s+\d+
^\s*NEW\s+QUESTION\s+\d+
^\s*NO\.\s*\d+
```

这些规则只用于粗切，不负责最终题目解析。

---

## 13. LLM 输出 Schema

```python
class ParsedOption(BaseModel):
    label: str
    text: str


class ParsedQuestion(BaseModel):
    source_question_no: str | None = None
    question_type: Literal["single", "multiple", "truefalse", "unknown"] = "single"
    scenario: str | None = None
    content: str
    options: list[ParsedOption]
    correct_answer: list[str] = Field(default_factory=list)
    explanation: str = ""
    references: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    issues: list[str] = Field(default_factory=list)


class LlmParseResult(BaseModel):
    questions: list[ParsedQuestion]
    chunk_issues: list[str] = Field(default_factory=list)
```

LLM 必须只输出符合该结构的 JSON。

---

## 14. Prompt 核心要求

```text
你是一个 PDF / DOCX / XLSX 题库结构化解析器。

要求：
1. 只根据原文抽取，不要编造。
2. 一个 chunk 可能包含一道题或多道题。
3. 识别题干、选项、答案、解析、参考资料。
4. 如果是场景题，把案例背景放入 scenario。
5. answer 必须来自原文中的 Answer / Correct Answer / Answer Key。
6. 如果原文没有答案，correct_answer 输出空数组。
7. 忽略页眉、页脚、广告、水印。
8. 输出必须是 JSON，不要输出 Markdown。
```

---

## 15. 质量校验

LLM 输出后必须运行程序校验。

| 校验项 | 规则 |
|---|---|
| JSON 合法 | 必须通过 Pydantic |
| 题干 | 不为空 |
| 选项 | 至少 2 个 |
| 答案 | 必须在选项 label 中 |
| 答案证据 | 原文中能找到答案标记 |
| 解析 | 可为空 |
| 场景 | 可为空 |
| 置信度 | 0-1 |
| 噪声 | 不应包含明显广告词 |

常见 issue：

```text
ANSWER_MISSING
ANSWER_NOT_IN_OPTIONS
ANSWER_EVIDENCE_NOT_FOUND
OPTION_COUNT_ABNORMAL
STEM_TOO_SHORT
NOISE_DETECTED
POSSIBLE_DUPLICATE
ANSWER_CONFLICT
LOW_CONFIDENCE
```

---

## 16. 置信度评分

```text
final_confidence =
  0.25 * llm_confidence
+ 0.20 * schema_score
+ 0.20 * answer_evidence_score
+ 0.15 * option_quality_score
+ 0.10 * duplicate_safety_score
+ 0.10 * noise_clean_score
```

自动入库条件：

```text
final_confidence >= 0.90
且无 HIGH severity issue
且无答案冲突
且答案证据存在
```

否则进入人工复核。

---

## 17. pgvector 使用场景

### 17.1 相似解析样例召回

```text
当前 chunk → embedding → 找 3 个类似题块 → 放入 prompt
```

### 17.2 重复题检测

```text
解析后的题目 → embedding → 找已有相似题 → 判断是否重复
```

### 17.3 标签推荐

```text
题干 + 解析 → embedding → 召回知识点标签
```

---

## 18. LLM 缓存

使用 PostgreSQL 表 `llm_parse_cache`。

cache key：

```text
sha256(model_name + prompt_version + chunk_hash + retrieved_example_ids)
```

命中缓存时不再请求 LLM。

---

## 19. 入库策略

### 19.1 自动入库

高置信度题目直接写入 `questions` 表。

```python
Question(
    bank_id=bank_id,
    question_type=parsed.question_type,
    content=parsed.content,
    options=parsed.options,
    correct_answer=parsed.correct_answer,
    explanation=parsed.explanation,
)
```

### 19.2 人工复核入库

低置信度题目进入 `import_review_items`，用户确认后再写入 `questions`。

### 19.3 重复题策略

| 情况 | 处理 |
|---|---|
| 完全重复 | 默认跳过 |
| 高相似但答案一致 | 可合并来源 |
| 高相似但答案冲突 | 强制复核 |
| 疑似重复 | 复核提示 |

---

## 20. 前端改造

### 20.1 废弃旧同步导入 UI

旧按钮“导入题目”改为“智能导入”。

### 20.2 新增导入任务页面

```text
/import-jobs
/import-jobs/:id
```

展示：

- 文件名；
- 导入状态；
- 进度；
- 总 chunk；
- 解析题数；
- 自动入库题数；
- 待复核题数；
- 失败 chunk；
- 导入报告。

### 20.3 新增复核页面

左侧展示原始 chunk / 原始页码。右侧展示题干、选项、答案、解析、问题提示、相似题提示，以及接受 / 跳过 / 重新解析按钮。

---

## 21. requirements.txt

```txt
fastapi>=0.115
uvicorn[standard]>=0.30
sqlalchemy>=2.0
psycopg[binary]>=3.2
alembic>=1.13
pydantic>=2.7
pydantic-settings>=2.3
python-multipart>=0.0.9
python-jose[cryptography]>=3.3
passlib[bcrypt]>=1.7
pymupdf>=1.24
pdfplumber>=0.11
python-docx>=1.1
openpyxl>=3.1
pgvector>=0.3
httpx>=0.27
tenacity>=8.3
rapidfuzz>=3.9
```

OCR 后续再加：

```txt
paddleocr
paddlepaddle
```

---

## 22. .env 示例

```env
DATABASE_URL=postgresql+psycopg://quiz_user:quiz_pass@localhost:5432/quiz_app

JWT_SECRET_KEY=change-me
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

STORAGE_ROOT=./storage

LLM_BASE_URL=https://api.example.com/v1
LLM_API_KEY=change-me
LLM_MODEL=gpt-4.1-mini

EMBEDDING_BASE_URL=https://api.example.com/v1
EMBEDDING_API_KEY=change-me
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIM=1536

WORKER_LEASE_SECONDS=600
WORKER_POLL_INTERVAL_SECONDS=3
```

---

## 23. 迁移步骤

### 阶段 1：FastAPI 骨架

- 创建 `app/main.py`
- 创建 `core/config.py`
- 创建 `core/database.py`
- 接入 PostgreSQL
- 初始化 Alembic

### 阶段 2：迁移核心业务表

- users
- question_banks
- questions
- system_settings
- background_jobs

### 阶段 3：新增智能导入表

- import_jobs
- import_chunks
- import_parsed_questions
- import_review_items
- llm_parse_cache
- vector_index

### 阶段 4：废弃旧规则导入

- 移除或隐藏旧同步导入按钮；
- `/api/banks/{bank_id}/import` 改为创建异步智能导入任务；
- 旧 `import_service` 不再扩展。

### 阶段 5：实现 Python Worker

- 轮询 background_jobs；
- `FOR UPDATE SKIP LOCKED` 抢任务；
- 心跳续租；
- 失败重试；
- 支持 `question_import_llm`。

### 阶段 6：实现智能导入链路

- 文件抽取；
- 文档清洗；
- chunk 切片；
- LLM 解析；
- Pydantic 校验；
- 自动入库 / 人工复核。

### 阶段 7：加入 pgvector 增强

- embedding 生成；
- 相似样例召回；
- 重复题检测；
- 自动标签推荐。

---

## 24. 开发任务拆解

### Task 1：FastAPI 基础框架

- 创建 FastAPI app；
- 配置 CORS；
- 配置 PostgreSQL；
- 配置 JWT；
- 实现 get_db / get_current_user。

### Task 2：PostgreSQL 数据模型

- 迁移 users / banks / questions；
- 新增 background_jobs；
- 新增 import_jobs / chunks / parsed_questions；
- 新增 vector_index。

### Task 3：智能导入接口

- `POST /api/banks/{bank_id}/import`；
- 保存上传文件；
- 计算 file_hash；
- 创建 import_job；
- 创建 background_job。

### Task 4：Worker

- 实现 PostgreSQL 抢任务；
- 实现 heartbeat；
- 实现 retry；
- 实现 question_import_llm 分发。

### Task 5：文件抽取

- PDF 抽取；
- DOCX 抽取；
- XLSX 抽取；
- 输出统一 DocumentText。

### Task 6：LLM 解析

- chunker；
- prompt_builder；
- llm_parser；
- Pydantic schema 校验；
- LLM cache。

### Task 7：质量控制

- 答案合法性校验；
- 答案证据校验；
- 选项数量校验；
- 噪声检测；
- 置信度评分。

### Task 8：入库与复核

- 高置信度自动写入 Question；
- 低置信度写入 ReviewItem；
- 复核接口；
- 复核页面。

### Task 9：pgvector 增强

- vector_index；
- embedding 生成；
- 相似样例召回；
- 重复题检测；
- 标签推荐。

---

## 25. 最终结论

最新方案固定为：

```text
Vue 前端
+
FastAPI 后端
+
PostgreSQL / pgvector
+
Python Worker
+
LLM 智能导入
```

导入模块最终统一为：

```text
文件上传
→ ImportJob
→ BackgroundJob
→ Worker 异步执行
→ 文本抽取
→ Chunk 切片
→ pgvector 召回相似样例
→ LLM 结构化解析
→ Pydantic / 程序校验
→ 自动入库 / 人工复核
```

这套方案的优势：

1. 不再维护脆弱的规则导入；
2. 不使用 Redis / MQ，部署简单；
3. PostgreSQL 统一承载业务、任务、缓存、向量；
4. LLM 能兼容更多不同格式的题库文件；
5. Worker 支持任务恢复、失败重试和进度展示；
6. 低置信度题目可人工复核，保证题库质量；
7. 后续可继续扩展自动标签、重复题合并、错题归因。
