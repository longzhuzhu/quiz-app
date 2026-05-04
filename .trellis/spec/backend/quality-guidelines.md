# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

项目没有配置 lint 工具和测试框架。质量保障主要依赖代码审查和手动验证。

---

## Required Patterns

### 1. 使用 Pydantic schema 校验请求体

所有 API 路由的请求体必须使用对应的 Pydantic schema，不允许用 `dict`。

```python
# Correct
@router.post("/banks")
def create_bank(data: BankCreateRequest, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    ...

# Wrong - 绕过 FastAPI 自动校验
@router.post("/banks")
def create_bank(data: dict, ...):
```

### 2. 文件上传必须校验大小

```python
content = await file.read()
if len(content) > settings.upload_max_size_bytes:
    raise HTTPException(status_code=413, detail="File too large")
```

### 3. 权限检查使用依赖注入

```python
# 普通用户接口
def endpoint(user: User = Depends(get_current_user)):

# 管理员接口
def endpoint(admin: User = Depends(require_admin)):
```

### 4. 数据库会话通过依赖注入

```python
def endpoint(db: Session = Depends(get_db)):
```

不要在路由或 service 中创建自己的数据库会话。

---

## Forbidden Patterns

### 1. 死代码条件

```python
# Wrong - 条件永远为 False
if mastered_value is not None and mastered_value is None:
```

检查条件逻辑时必须确认条件可以达到期望的分支。

### 2. 参数顺序与函数签名不匹配

```python
# Wrong - 位置参数传错
create_or_reuse_job(job_type, payload, admin_id, db)
# 当函数签名是 create_or_reuse_job(db, job_type, payload, created_by)

# Correct
create_or_reuse_job(db, job_type, payload, admin_id)
```

### 3. 返回类型注解与实际返回值不一致

```python
# Wrong - 声明返回 dict | None 但下游要求非 None
def _build_payload(...) -> dict | None:
    if error:
        return None, error_msg
    return payload, None

# Correct - 使用元组明确错误路径
def _build_payload(...) -> tuple[dict, str | None]:
    if error:
        return {}, error_msg
    return payload, None
```

---

## BackgroundJob Async Pattern

长时间运行的操作（如批量翻译）必须使用 BackgroundJob 异步模式，不允许同步阻塞。

### 架构

```
Frontend: POST /jobs → 200 OK → poll GET /jobs/active
Backend:  JobService.create_or_reuse_job() → Worker claims → heartbeat → complete/fail
Worker:   job_worker.py (独立进程, cd backend && python3 -m app.workers.job_worker)
```

### 关键约定

1. **防重复提交**: `create_or_reuse_job()` 返回 `result="existing"` 当同 scope 有活跃任务
2. **进度更新**: Worker 通过 `heartbeat_job()` 上报 progress_done / progress_total
3. **Worker 必须从 backend/ 目录启动** (模块路径依赖 `app.*`)
4. **Job scope**: `professional_vocab_translate` (全局) vs `bank_frequent_translate` (需 bank_id)

```python
# 创建任务
job, result, message = create_or_reuse_job(db, job_type, payload, created_by)

# Worker 心跳更新进度
heartbeat_job(db, job, success_increment=10, status_message="已处理 40/662")

# 前端查询活跃任务
GET /api/jobs/active?job_type=professional_vocab_translate
GET /api/jobs/active?job_type=bank_frequent_translate&bank_id=1
```

### Don't: 同步循环批量操作

```python
# Wrong - 阻塞请求直到完成
while True:
    result = translate_batch()
    if result.remaining <= 0:
        break
```

### Do: 异步后台任务

```python
# Correct - 立即返回，Worker 后台处理
job, result, message = create_or_reuse_job(db, job_type, payload, user_id)
return {"result": result, "job": _job_to_dict(job), "message": message}
```

---

## API Compatibility Checklist

迁移 Flask → FastAPI 时，对每个 API 必须验证：

- [ ] URL 路径完全一致（`/api/auth/login` 而非 `/auth/login`）
- [ ] HTTP 方法一致（GET/POST/PUT/DELETE）
- [ ] 请求参数位置一致（query/body/form/path）
- [ ] 响应 JSON 字段名和结构一致
- [ ] 认证方式一致（Bearer token）
- [ ] 错误状态码一致（特别是 401 vs 403）
- [ ] 文件上传接口使用 `multipart/form-data`

---

## JWT Compatibility

FastAPI JWT 实现必须与 Flask-JWT-Extended 保持兼容：

- 相同 `JWT_SECRET_KEY` 和 `JWT_ALGORITHM`（HS256）
- Token payload 中 `sub` 字段存储字符串形式的用户 ID
- 默认过期时间 7 天（1440 分钟）
- 新旧系统使用同一密钥时，Flask 生成的 token 可在 FastAPI 端验证

### 密码兼容

新系统使用 passlib `pbkdf2_sha256` 格式。旧 Flask 系统使用 Werkzeug 格式 `pbkdf2:sha256:iterations$salt$hex_checksum`。`verify_password()` 必须兼容两种格式：

```python
def verify_password(plain_password: str, hashed_password: str) -> bool:
    # 1. 先尝试 passlib 格式
    # 2. 再尝试 Werkzeug 格式
    # 3. 都不匹配返回 False
```

---

## Common Mistakes

### 条件分支逻辑错误

在质量检查中发现 `vocab.py` 的 `is_mastered` 过滤条件写成 `if mastered_value is not None and mastered_value is None`，导致过滤永远不生效。编写条件时需仔细检查逻辑含义。

### FastAPI redirect_slashes 与 catch-all 路由冲突

FastAPI 默认 `redirect_slashes=True`，会将 `/api/banks/` 重定向到 `/api/banks`。但 `/{full_path:path}` catch-all SPA fallback 会吞掉未匹配的 API 请求并返回 200 + HTML 而非 404。

```python
# Wrong - API 404 请求返回 HTML
@app.get("/{full_path:path}")
async def serve_frontend(request: Request, full_path: str):
    # /api/nonexistent 走到这里，返回 index.html (200)

# Correct - 排除 /api 前缀
app = FastAPI(redirect_slashes=False)

@app.get("/{full_path:path}")
async def serve_frontend(request: Request, full_path: str):
    if full_path.startswith("api"):
        raise HTTPException(status_code=404)
```

### 路由尾部斜杠

FastAPI 路由装饰器用 `""` 而非 `"/"` 注册根路径，避免 redirect_slashes 导致双重重定向：

```python
# Preferred
@router.get("")
def list_banks(...):

# Avoid (causes 307 redirect when redirect_slashes is on)
@router.get("/")
def list_banks(...):
```
