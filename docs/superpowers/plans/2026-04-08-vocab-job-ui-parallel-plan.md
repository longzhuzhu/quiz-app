# Vocabulary Background Job UI and Parallel Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除单词本后台任务提示的重复与多行展示，并让不同卡片的后台翻译任务支持并行执行。

**Architecture:** 前端把任务状态文案收敛为一个纯函数输出的一行提示，避免直接叠加后端 `status_message` 和额外进度行；后端把单 worker 串行消费改为固定并发槽位的 worker pool，在保持 `active_scope_key` 互斥语义的前提下允许不同 scope 并行执行。

**Tech Stack:** Vue 3 / Vite、Node 内置 `node:test`、Flask / SQLAlchemy、Python `threading`

---

### Task 1: 前端状态文案收敛为一行

**Files:**
- Create: `frontend/src/utils/jobStatus.js`
- Create: `frontend/tests/jobStatus.test.js`
- Modify: `frontend/src/views/VocabularyView.vue`

- [ ] **Step 1: 写前端 formatter 的失败测试**

```js
import test from 'node:test'
import assert from 'node:assert/strict'
import { formatJobBannerMessage } from '../src/utils/jobStatus.js'

test('running job banner uses a single-line message without duplicated progress', () => {
  const message = formatJobBannerMessage(
    {
      status: 'running',
      status_message: '专业词汇翻译中，已处理 40/542',
      progress_done: 40,
      progress_total: 542,
      attempt_count: 1,
      max_attempts: 3,
    },
    { idleMessage: '任务正在后台执行，可离开页面后稍后回来查看' },
  )

  assert.equal(message, '专业词汇翻译中 · 已处理 40/542 · 第 1/3 次 · 刷新页面不会中断')
})

test('failed job banner keeps resume hint in one line', () => {
  const message = formatJobBannerMessage(
    {
      status: 'failed',
      status_message: '任务已自动执行 3 次仍失败',
      progress_done: 40,
      progress_total: 542,
      attempt_count: 3,
      max_attempts: 3,
    },
    { idleMessage: '任务正在后台执行，可离开页面后稍后回来查看' },
  )

  assert.equal(message, '任务已自动执行 3 次仍失败，可重新点击继续翻译剩余未翻译内容')
})
```

- [ ] **Step 2: 运行测试，确认当前失败**

Run: `node --test frontend/tests/jobStatus.test.js`
Expected: FAIL，因为 `frontend/src/utils/jobStatus.js` 尚不存在。

- [ ] **Step 3: 用最小实现补 formatter**

```js
export function getFailedJobMessage(job) {
  const baseMessage = job?.status_message?.trim() || '任务已自动执行 3 次仍失败'
  if (baseMessage.includes('可重新点击继续翻译剩余未翻译内容')) {
    return baseMessage
  }
  return `${baseMessage}，可重新点击继续翻译剩余未翻译内容`
}

export function formatJobBannerMessage(job, { idleMessage } = {}) {
  const fallback = idleMessage || '任务正在后台执行，可离开页面后稍后回来查看'
  if (!job) return fallback
  if (job.status === 'failed') return getFailedJobMessage(job)

  const statusText = (job.status_message || fallback).replace(/，已处理\s*\d+\s*\/\s*\d+/, '')
  const done = job.progress_done ?? 0
  const total = job.progress_total ?? 0
  const attempt = job.attempt_count ?? 0
  const maxAttempts = job.max_attempts ?? 3
  return `${statusText} · 已处理 ${done}/${total} · 第 ${attempt}/${maxAttempts} 次 · 刷新页面不会中断`
}
```

- [ ] **Step 4: 在 `VocabularyView.vue` 接入 formatter，并把提示改为单行**

```vue
<div
  v-if="professionalJob && ['queued', 'running', 'failed'].includes(professionalJob.status)"
  class="mb-4 rounded-card bg-teal-50 dark:bg-teal-900/20 px-4 py-3 text-sm text-teal-700 dark:text-teal-300"
>
  {{ formatJobBannerMessage(professionalJob) }}
</div>
```

```vue
<div
  v-if="frequentJob && ['queued', 'running', 'failed'].includes(frequentJob.status)"
  class="mb-4 rounded-card bg-amber-50 dark:bg-amber-900/20 px-4 py-3 text-sm text-amber-700 dark:text-amber-300"
>
  {{ formatJobBannerMessage(frequentJob) }}
</div>
```

- [ ] **Step 5: 运行 formatter 测试和前端构建**

Run:
- `node --test frontend/tests/jobStatus.test.js`
- `npm --prefix frontend run build`

Expected:
- `node --test` 全通过
- `vite build` 通过

- [ ] **Step 6: 提交前端改动**

```bash
git add frontend/src/utils/jobStatus.js frontend/tests/jobStatus.test.js frontend/src/views/VocabularyView.vue
git commit -m "feat: simplify vocab job banner messages"
```

### Task 2: 后台 worker 支持有限并发

**Files:**
- Modify: `backend/workers/job_worker.py`
- Modify: `backend/tests/test_background_job_worker.py`
- Modify: `README.md`

- [ ] **Step 1: 先写并发 worker 的失败测试**

```python
def test_run_worker_processes_multiple_jobs_with_configured_concurrency(app, monkeypatch):
    professional = seed_professional_job(app)
    bank = seed_bank_frequency_job(app)
    processed_ids = []

    def fake_run_job(job):
        processed_ids.append(job.id)
        if job.job_type == 'professional_vocab_translate':
            job_service.heartbeat_job(job, success_increment=job.progress_total)
        else:
            job_service.heartbeat_job(job, success_increment=job.progress_total)

    monkeypatch.setattr('workers.job_worker.run_job', fake_run_job)

    from workers.job_worker import run_worker

    run_worker(app, worker_id='test-worker', once=True, concurrency=2)

    with app.app_context():
        jobs = {
            job.id: db.session.get(BackgroundJob, job.id)
            for job in BackgroundJob.query.order_by(BackgroundJob.id).all()
        }

    assert sorted(processed_ids) == sorted([professional['job_id'], bank['job_id']])
    assert jobs[professional['job_id']].status == 'completed'
    assert jobs[bank['job_id']].status == 'completed'
```

- [ ] **Step 2: 运行 worker 测试，确认新增用例失败**

Run: `pytest backend/tests/test_background_job_worker.py -q`
Expected: FAIL，因为当前 `run_worker(..., concurrency=2)` 还不支持多槽位执行。

- [ ] **Step 3: 以最小改动实现有限并发 worker**

```python
import threading

DEFAULT_CONCURRENCY = 2


def worker_loop(app, worker_id, poll_interval, once):
    while True:
        processed = process_one_job(app, worker_id=worker_id)
        if once:
            return processed
        if not processed:
            time.sleep(poll_interval)


def run_worker(app, worker_id=DEFAULT_WORKER_ID, poll_interval=DEFAULT_POLL_INTERVAL, once=False, concurrency=DEFAULT_CONCURRENCY):
    if once or concurrency <= 1:
        while True:
            processed = process_one_job(app, worker_id=worker_id)
            if once:
                return 0
            if not processed:
                time.sleep(poll_interval)
                continue

    threads = []
    for index in range(concurrency):
        thread = threading.Thread(
            target=worker_loop,
            kwargs={
                'app': app,
                'worker_id': f'{worker_id}-{index + 1}',
                'poll_interval': poll_interval,
                'once': False,
            },
            daemon=True,
        )
        thread.start()
        threads.append(thread)

    for thread in threads:
        thread.join()
```

并补充参数解析：

```python
parser.add_argument('--concurrency', type=int, default=int(os.environ.get('JOB_WORKER_CONCURRENCY', str(DEFAULT_CONCURRENCY))))
```

- [ ] **Step 4: 更新 README 的 worker 并发说明**

```md
- worker 默认以 2 个并发槽位持续消费后台任务队列，不同任务作用域可并行执行
- 可通过环境变量 `JOB_WORKER_CONCURRENCY` 调整并发数，例如 `JOB_WORKER_CONCURRENCY=1 bash scripts/start-worker.sh`
```

- [ ] **Step 5: 运行定向后端回归**

Run:
- `pytest backend/tests/test_background_job_worker.py -q`
- `pytest backend/tests/test_background_jobs_api.py backend/tests/test_bank_import_api.py -q`

Expected:
- 所有后台任务相关测试通过

- [ ] **Step 6: 提交 worker 并发改动**

```bash
git add backend/workers/job_worker.py backend/tests/test_background_job_worker.py README.md
git commit -m "feat: allow background workers to process jobs concurrently"
```

### Task 3: 最终集成验证

**Files:**
- Modify: 无（仅验证）

- [ ] **Step 1: 跑完整定向验证**

Run:
- `node --test frontend/tests/jobStatus.test.js`
- `pytest backend/tests/test_background_jobs_api.py backend/tests/test_background_job_worker.py backend/tests/test_bank_import_api.py -q`
- `npm --prefix frontend run build`

Expected:
- formatter 测试通过
- 后台任务相关 pytest 通过
- 前端构建通过

- [ ] **Step 2: 记录验收要点**

验收时手工确认：
- 专业词汇提示为单行且无重复进度
- 高频词提示为单行且无重复进度
- 同时点两个卡片的翻译按钮后，两类任务都能运行，不再严格串行

- [ ] **Step 3: 提交最终验证状态**

```bash
git status --short
git log --oneline -n 5
```
