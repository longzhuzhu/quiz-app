# Error Handling

> How errors are handled in this project.

---

## Overview

FastAPI 使用 `HTTPException` 返回错误响应。前端 Axios 客户端依赖 401 状态码触发登出，因此认证错误必须返回 401 而非 403。

---

## HTTP Error Codes

| Code | Usage |
|------|-------|
| 400 | 请求参数错误（校验失败、业务逻辑拒绝） |
| 401 | 未认证或 token 无效/过期 — **必须用于所有认证失败场景** |
| 403 | 已认证但权限不足（如非管理员访问管理接口） |
| 404 | 资源不存在 |
| 413 | 文件上传超过大小限制 |
| 500 | 服务端未预期错误 |

---

## Error Response Format

```python
# FastAPI HTTPException 格式
raise HTTPException(status_code=401, detail="Invalid or expired token")
```

返回给前端：

```json
{"detail": "Invalid or expired token"}
```

---

## Authentication Error Handling

### Critical: 401 vs 403

前端 `client.js` 的 Axios 拦截器在收到 401 时自动执行登出。因此：

- Token 缺失/无效/过期 → **401**（`get_current_user` 依赖）
- Token 有效但用户不存在 → **401**
- Token 有效、用户存在但不是管理员 → **403**（`require_admin` 依赖）

```python
# deps.py
def get_current_user(...):
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")  # 401, NOT 403
    ...

def require_admin(current_user: User = Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")  # 403 here
```

---

## Validation Errors

FastAPI 自动返回 422 for Pydantic 校验失败。如果前端不处理 422，可在路由中 try-except 并转为 400：

```python
from pydantic import ValidationError

try:
    parsed = SomeSchema(**data)
except ValidationError as e:
    raise HTTPException(status_code=400, detail=str(e))
```

---

## Common Mistakes

### Don't: 对认证失败返回 403

```python
# Wrong - 前端不会触发登出
if not token:
    raise HTTPException(status_code=403, detail="Not authenticated")
```

### Do: 认证失败一律 401

```python
# Correct
if not token:
    raise HTTPException(status_code=401, detail="Not authenticated")
```

### Don't: 吞掉异常不做处理

```python
# Wrong
try:
    result = some_operation()
except Exception:
    pass  # 静默失败
```

### Do: 记录错误并返回有意义的信息

```python
# Correct
try:
    result = some_operation()
except SpecificError as e:
    raise HTTPException(status_code=400, detail=str(e))
```
