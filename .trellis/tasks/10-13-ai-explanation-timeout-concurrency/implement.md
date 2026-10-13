# 实施计划：AI 解析超时与并发优化并移除历史解析展示

## 前置检查

```bash
# 确认无在途解析任务（重启 worker 会判失败）
psql "$DATABASE_URL" -c "SELECT id, status, job_type FROM background_jobs WHERE status IN ('queued','running') AND job_type='ai_explanation';"
```

预期：无 running 的解析任务，或有心理准备让在途任务在重启后变为失败。

## Step 1 后端配置：超时与并发

**改动**

1. `app/core/config.py`
   - 新增 `AI_EXPLANATION_TIMEOUT_SECONDS: float = Field(default=120.0, gt=0)`
   - `AI_EXPLANATION_CONCURRENCY` 默认 `3` → `10`
2. `app/workers/job_worker.py`：`DEFAULT_CONCURRENCY` `2` → `10`
3. `app/core/database.py`：`pool_size=10, max_overflow=20`

**验证**

```bash
cd backend && python3 -c "
from app.core.config import settings
from app.workers.job_worker import DEFAULT_CONCURRENCY
from app.core.database import engine
assert settings.AI_EXPLANATION_TIMEOUT_SECONDS == 120.0
assert settings.AI_EXPLANATION_CONCURRENCY == 10
assert DEFAULT_CONCURRENCY == 10
assert engine.pool.size() == 10 and engine.pool._max_overflow == 20
print('OK')
"
```

## Step 2 超时参数下传

**改动**

1. `app/services/ai_service.py`：`generate_structured_explanation(question, *, persona, ai_config, reasoning_effort, timeout)` 新增 `timeout: float` 关键字参数，内部两次 `call_ai_api` 均传 `timeout=timeout`
2. `app/services/explanation_service.py`：`execute_explanation` 调用处传 `timeout=settings.AI_EXPLANATION_TIMEOUT_SECONDS`；文件顶部补 `from app.core.config import settings`

**验证**

```bash
cd backend && python3 -c "
import inspect
from app.services import ai_service
sig = inspect.signature(ai_service.generate_structured_explanation)
assert 'timeout' in sig.parameters, sig
print('OK')
"
# 静态断言：解析调用显式带 timeout
grep -n 'timeout=' app/services/ai_service.py | sed -n '1,20p'
```

## Step 3 解析任务租约延长

**改动**（`app/services/job_service.py`）

1. 新增常量 `EXPLANATION_JOB_LEASE_SECONDS = 360`，附注释说明取值依据：单题最坏 2 × 120s 调用 + 余量
2. `try_claim_job_by_id` 中对 `JOB_TYPE_AI_EXPLANATION` 使用该租约：

```python
lease_until = now + timedelta(seconds=lease_seconds if candidate is None or candidate.job_type != JOB_TYPE_AI_EXPLANATION else max(lease_seconds, EXPLANATION_JOB_LEASE_SECONDS))
```

> 注意：现有实现里 `candidate` 可能为 `None`，取值前需判空；保持非解析任务租约不变（180s）。

**验证（关键回归点）**

```bash
cd backend && python3 -c "
from app.services.job_service import EXPLANATION_JOB_LEASE_SECONDS, DEFAULT_JOB_LEASE_SECONDS
assert EXPLANATION_JOB_LEASE_SECONDS > 2 * 120, '解析租约必须覆盖最坏两次调用'
assert EXPLANATION_JOB_LEASE_SECONDS != DEFAULT_JOB_LEASE_SECONDS
print(EXPLANATION_JOB_LEASE_SECONDS)
"
```

## Step 4 移除历史解析展示

**后端**：`explanation_service.read_explanations` 删除 `has_legacy_explanation` 键。

**前端**：
1. `composables/useQuestionExplanations.js`：删除 `legacyAvailable` 的声明、两处赋值、返回项
2. `components/QuestionExplanation.vue`：
   - 删除 `<details>` 折叠块（原 48-51 行）
   - `ExplainButton` 的 `:displayed` 去掉 `|| legacyAvailable`
   - 解构处去掉 `legacyAvailable`

**验证**

```bash
# 仓库内不应再有 legacy 展示相关标识（测试断言除外，Step 5 处理）
grep -rn "legacyAvailable\|has_legacy_explanation\|历史解析" frontend/src backend/app
```

预期：仅 `backend/tests/test_multi_model_explanation_api.py:275` 残留，Step 5 处理。

## Step 5 更新测试

**改动**

1. `backend/tests/test_multi_model_explanation_api.py:275`：删除 `has_legacy_explanation is False` 断言
2. 新增后端测试 `backend/tests/test_explanation_timeout_and_lease.py`，覆盖：
   - `generate_structured_explanation` 把 timeout 透传给 `call_ai_api`（两次调用均为该值）
   - `AI_EXPLANATION_TIMEOUT_SECONDS` 默认 120
   - `EXPLANATION_JOB_LEASE_SECONDS > 2 ×` 解析超时默认值
3. `frontend/tests/multiModelExplanationE2E.test.js`：确认无 legacy 依赖（已核查无），必要时补"无历史解析折叠块"断言

**验证**

```bash
cd backend && python3 tests/run_isolated_suite.py -q
cd ../frontend && node --test
```

预期：全绿。若 `run_isolated_suite.py` 环境不可用，最低限度运行：

```bash
cd backend && python3 -m pytest tests/test_ai_service_call_api_timeout.py tests/test_ai_explanation_refresh.py tests/test_explanation_prompt_structure.py -q
```

## Step 6 生产配置与部署

**改动**

1. `/etc/systemd/system/quiz-app-worker.service`：`[Service]` 下增加 `Environment=JOB_WORKER_CONCURRENCY=10`
2. `backend/.env`：增加 `AI_EXPLANATION_CONCURRENCY=10`（不写超时，走默认 120）
3. `README.md`、`docs/deployment.md`：更新并发默认值（3→10、2→10）、补充解析超时 120s、删除历史解析描述
4. `CONTEXT.md`：删除"来源未知的历史 AI 解析单独折叠展示"不变量

**部署**

```bash
cd frontend && npm run build
sudo systemctl daemon-reload
sudo systemctl restart quiz-app quiz-app-worker
systemctl status quiz-app quiz-app-worker --no-pager
```

**验证**

```bash
# worker 线程数与并发配置生效
grep -c "JOB_WORKER_CONCURRENCY=10" /etc/systemd/system/quiz-app-worker.service
sudo journalctl -u quiz-app-worker -n 30 --no-pager
# 冒烟：前端 AI 解析按钮可用，无历史解析折叠块
```

## Step 7 端到端验收

1. 打开任一题目，点击「AI 解析」，确认多模型卡片并行生成（首屏出现时间明显早于串行叠加）
2. 确认页面上不存在「历史解析（模型来源未知）」
3. `curl` 校验接口响应：

```bash
curl -s -H "Authorization: Bearer $TOKEN" -H "X-Exam-Slug: <slug>" \
  "http://127.0.0.1:5003/api/ai/explanations?question_id=<id>" | python3 -m json.tool
# 断言：无 has_legacy_explanation 键，models 数组正常
```

4. 观察 worker 日志与数据库连接数，确认 10 并发不触发连接池告警：

```bash
psql "$DATABASE_URL" -c "SELECT count(*) FROM pg_stat_activity;"
```

## 回滚点

| 步骤 | 回滚方式 |
|------|---------|
| Step 1-5 | `git revert` 对应提交；配置项有默认值，旧代码可读新 `.env`（多余键被 `extra="ignore"` 忽略） |
| Step 6 | 还原 systemd 配置与 `backend/.env`，`systemctl daemon-reload && restart`，重新构建旧前端产物 |

## 检查清单

- [ ] Step 1 配置默认值与连接池上限断言通过
- [ ] Step 2 超时显式下传，翻译/导入超时未变
- [ ] Step 3 解析租约覆盖最坏 240s
- [ ] Step 4 前后端无 legacy 展示残留
- [ ] Step 5 后端隔离套件与前端 `node --test` 全绿
- [ ] Step 6 生产配置生效并重启
- [ ] Step 7 浏览器端到端验收通过
