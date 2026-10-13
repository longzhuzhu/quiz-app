/**
 * 复盘展示的状态归类与筛选。
 *
 * `status_unknown` 优先于 `status`：后端在无法核实判定时返回
 * `status="unanswered"` + `status_unknown=true`，此处的 `status` 只是占位，
 * 不代表「确实未答」。渲染与筛选都必须先看 `status_unknown`。
 */

export const REVIEW_FILTERS = ['all', 'correct', 'wrong', 'unanswered']

/** 单题复查分类：correct / wrong / unanswered / unknown */
export function reviewStatusOf(question) {
  if (question?.status_unknown === true) return 'unknown'
  if (question?.status === 'correct' || question?.status === 'wrong') return question.status
  return 'unanswered'
}

/** 题号徽标文案：未答用中性「未答」，不可核实用「未知」 */
export function reviewStatusLabel(question) {
  const status = reviewStatusOf(question)
  if (status === 'correct') return '正确'
  if (status === 'wrong') return '错误'
  if (status === 'unknown') return '未知'
  return '未答'
}

/** 非法或缺失的 query filter 一律回落到 all */
export function normalizeReviewFilter(value) {
  return REVIEW_FILTERS.includes(value) ? value : 'all'
}

/** 筛选只改变可见集合；题号始终取元素自带的原场 index，不按筛选下标重编号 */
export function visibleReviewQuestions(questions, filter) {
  const list = Array.isArray(questions) ? questions : []
  const normalized = normalizeReviewFilter(filter)
  if (normalized === 'all') return list
  if (normalized === 'unanswered') {
    return list.filter(question => reviewStatusOf(question) === 'unanswered')
  }
  return list.filter(question => reviewStatusOf(question) === normalized)
}
