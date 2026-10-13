import test from 'node:test'
import assert from 'node:assert/strict'
import {
  normalizeReviewFilter,
  reviewStatusLabel,
  reviewStatusOf,
  visibleReviewQuestions,
} from './quizReview.js'

const questions = [
  { id: 1, index: 1, status: 'correct', status_unknown: false },
  { id: 2, index: 2, status: 'wrong', status_unknown: false },
  { id: 3, index: 3, status: 'unanswered', status_unknown: false },
  { id: 4, index: 4, status: 'unanswered', status_unknown: true },
  { id: 5, index: 5, status: 'correct', status_unknown: true },
]

test('status_unknown 优先于 status：不可核实不当作未答或正确', () => {
  assert.equal(reviewStatusOf(questions[3]), 'unknown')
  assert.equal(reviewStatusOf(questions[4]), 'unknown')
  assert.equal(reviewStatusOf(questions[0]), 'correct')
  assert.equal(reviewStatusOf(questions[2]), 'unanswered')
  assert.equal(reviewStatusOf({ id: 9, index: 9, status: 'unanswered' }), 'unanswered')
  assert.equal(reviewStatusLabel(questions[3]), '未知')
  assert.equal(reviewStatusLabel(questions[2]), '未答')
})

test('未答题不进错误筛选，不可核实题也不进错误筛选', () => {
  const wrong = visibleReviewQuestions(questions, 'wrong')
  assert.deepEqual(wrong.map(q => q.index), [2])
  const unanswered = visibleReviewQuestions(questions, 'unanswered')
  assert.deepEqual(unanswered.map(q => q.index), [3])
  const correct = visibleReviewQuestions(questions, 'correct')
  assert.deepEqual(correct.map(q => q.index), [1])
})

test('筛选保留原场题号，不按可见集合重新编号', () => {
  assert.deepEqual(visibleReviewQuestions(questions, 'wrong').map(q => q.index), [2])
  assert.deepEqual(visibleReviewQuestions(questions, 'all').map(q => q.index), [1, 2, 3, 4, 5])
  assert.deepEqual(visibleReviewQuestions(questions, null).map(q => q.index), [1, 2, 3, 4, 5])
  assert.deepEqual(visibleReviewQuestions(undefined, 'all'), [])
})

test('非法 filter 回落到 all', () => {
  assert.equal(normalizeReviewFilter('wrong'), 'wrong')
  assert.equal(normalizeReviewFilter('unknown'), 'all')
  assert.equal(normalizeReviewFilter(undefined), 'all')
  assert.deepEqual(visibleReviewQuestions(questions, 'nonsense').map(q => q.index), [1, 2, 3, 4, 5])
})

console.log('quizReview tests passed')
