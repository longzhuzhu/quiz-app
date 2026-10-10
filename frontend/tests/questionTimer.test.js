import test from 'node:test'
import assert from 'node:assert/strict'

import { createQuestionTimer, formatQuestionDuration } from '../src/utils/questionTimer.js'

test('switching questions only counts the current question and returning resumes it', () => {
  let time = 0
  const timer = createQuestionTimer({ now: () => time })
  timer.setQuestion(101)
  time = 1250
  timer.setQuestion(102)
  time = 3000
  timer.setQuestion(101)
  time = 3750
  assert.equal(timer.elapsedMs(), 2000)
  assert.equal(timer.elapsedMs(102), 1750)
})

test('hidden pages pause and showing the current question resumes without counting the gap', () => {
  let time = 0
  const timer = createQuestionTimer({ now: () => time })
  timer.setQuestion(101)
  time = 1250
  timer.setVisible(false)
  time = 90000
  timer.setQuestion(102)
  time = 100000
  assert.equal(timer.elapsedMs(101), 1250)
  assert.equal(timer.elapsedMs(102), 0)
  timer.setVisible(true)
  time = 101000
  assert.equal(timer.elapsedMs(), 1000)
})

test('successful submission freezes its request snapshot and redo never restarts it', () => {
  let time = 0
  const timer = createQuestionTimer({ now: () => time })
  timer.setQuestion(101)
  time = 2400
  const submission = timer.captureSubmission(101)
  time = 10000
  timer.completeSubmission(submission)
  assert.equal(timer.elapsedMs(), 2400)
  timer.setVisible(false)
  timer.setVisible(true)
  timer.setQuestion(102)
  timer.setQuestion(101)
  time = 20000
  timer.completeSubmission(timer.captureSubmission(101))
  assert.equal(timer.elapsedMs(), 2400)
})

test('restored submitted questions have unknown duration and do not start counting', () => {
  let time = 0
  const timer = createQuestionTimer({ now: () => time })
  timer.setQuestion(101, true)
  time = 20000
  assert.equal(timer.elapsedMs(), null)
  assert.equal(timer.captureSubmission(101).elapsedMs, null)
  timer.setQuestion(102)
  timer.setQuestion(101, true)
  time = 30000
  assert.equal(timer.elapsedMs(), null)
})

test('resetting the page discards durations and rejects late submissions from the old session', () => {
  let time = 0
  const timer = createQuestionTimer({ now: () => time })
  timer.setQuestion(101)
  time = 1000
  const oldSubmission = timer.captureSubmission(101)
  timer.reset()
  timer.setQuestion(101)
  time = 1250
  timer.completeSubmission(oldSubmission)
  assert.equal(timer.elapsedMs(), 250)
})

test('duration labels distinguish unknown submissions and do not wrap at an hour or a day', () => {
  assert.equal(formatQuestionDuration(null), '已提交')
  assert.equal(formatQuestionDuration(0), '00:00')
  assert.equal(formatQuestionDuration(1099), '00:01')
  assert.equal(formatQuestionDuration(3599999), '59:59')
  assert.equal(formatQuestionDuration(3600000), '01:00:00')
  assert.equal(formatQuestionDuration(90000000), '25:00:00')
})

test('a failed request keeps counting and retry captures the later duration', () => {
  let time = 0
  const timer = createQuestionTimer({ now: () => time })
  assert.equal(timer.elapsedMs(), null)
  time = 10000
  timer.setQuestion(101)
  time = 11000
  const failed = timer.captureSubmission(101)
  time = 14000
  assert.equal(failed.elapsedMs, 1000)
  const retry = timer.captureSubmission(101)
  assert.equal(retry.elapsedMs, 4000)
  time = 18000
  timer.completeSubmission(retry)
  assert.equal(timer.elapsedMs(), 4000)
})

test('a response after switching questions only freezes the submitted question', () => {
  let time = 0
  const timer = createQuestionTimer({ now: () => time })
  timer.setQuestion(101)
  time = 1000
  const submission = timer.captureSubmission(101)
  timer.setQuestion(102)
  time = 4000
  timer.completeSubmission(submission)
  assert.equal(timer.elapsedMs(101), 1000)
  assert.equal(timer.elapsedMs(102), 3000)
  time = 5000
  assert.equal(timer.elapsedMs(102), 4000)
})

test('server-confirmed first duration wins over a later local submission snapshot', () => {
  let time = 0
  const timer = createQuestionTimer({ now: () => time })
  timer.setQuestion(101)
  time = 1000
  timer.completeSubmission(timer.captureSubmission(101), 500)
  assert.equal(timer.elapsedMs(), 500)
})

test('server-confirmed unknown duration is not converted into a fake zero', () => {
  let time = 0
  const timer = createQuestionTimer({ now: () => time })
  timer.setQuestion(101)
  time = 1000
  timer.completeSubmission(timer.captureSubmission(101), null)
  assert.equal(timer.elapsedMs(), null)
  timer.setVisible(false)
  timer.setVisible(true)
  time = 2000
  assert.equal(timer.elapsedMs(), null)
})
