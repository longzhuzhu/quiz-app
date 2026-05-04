# 错误处理

> Flask 版和 FastAPI 版使用不同的错误返回模式。前端 Axios 客户端依赖 401 状态码触发登出。

---

## Flask 版：不使用 abort()，全部 `return jsonify({'error': '...'}), 4xx`

```python
# backend/routes/banks.py 行104-106
if not user:
    return jsonify({'error': '用户不存在，请重新登录'}), 401
if not user.is_admin:
    return jsonify({'error': '需要管理员权限'}), 403
```

Flask 路由中不调用 `abort()`，直接 `return jsonify(...) + 状态码`。

---

## FastAPI 版：统一 `raise HTTPException(status_code=4xx, detail='...')`

```python
# backend/app/api/deps.py 行29-31
if payload is None:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
    )

# backend/app/api/deps.py 行64-67
def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
```

---

## 自定义异常：`JobServiceError`

```python
# backend/app/services/job_service.py 行31-35
class JobServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
```

目前仅 `job_service.py` 定义了自定义异常，其他服务层返回 dict 或抛 ValueError。

---

## 四种 try/catch 模式

### 1. Service 抛 ValueError -> Route 转 400

Service 层校验失败抛 ValueError，路由层捕获后返回 400：

```python
# backend/routes/auth.py 行13-17
try:
    user = register_user(data['username'], data['email'], data['password'])
    return jsonify({'message': '注册成功', 'user': user_to_dict(user)}), 201
except ValueError as e:
    return jsonify({'error': str(e)}), 400
```

### 2. 外部调用 Exception -> 500

AI 等外部服务调用失败，路由层捕获返回 500：

```python
# backend/routes/ai.py 行29-33
try:
    result = translate_question(question)
    return jsonify({**result, 'cached': False})
except Exception as e:
    return jsonify({'error': f'翻译失败: {str(e)}'}), 500
```

### 3. DB 操作 + rollback

数据库操作失败时 rollback 后返回 500：

```python
# backend/routes/banks.py 行141-161
try:
    QuizAnswer.query.filter(...).delete(synchronize_session=False)
    ...
    db.session.delete(bank)
    db.session.commit()
except SQLAlchemyError:
    db.session.rollback()
    return jsonify({'error': '删除题库失败，请稍后重试'}), 500
```

### 4. 并发 upsert + savepoint（nested transaction）

高并发场景用 savepoint 处理 IntegrityError：

```python
# backend/routes/quiz.py 行45-61
nested = db.session.begin_nested()
try:
    db.session.add(stat)
    db.session.flush()
    nested.commit()
    return stat.answer_count
except IntegrityError:
    nested.rollback()
    # 回退到更新已有记录
    UserQuestionStat.query.filter_by(...).update({...}, synchronize_session=False)
    return ...
```

---

## 401 vs 403 规则

前端 `client.js` Axios 拦截器在 401 时自动执行登出，因此：

- Token 缺失/无效/过期 -> **401**（触发前端登出）
- Token 有效但用户不存在 -> **401**
- Token 有效、用户存在但非管理员 -> **403**（不触发登出）
