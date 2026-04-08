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
