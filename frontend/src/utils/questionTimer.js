/** @typedef {{elapsed: number | null, submitted: boolean}} QuestionTime */
/** @typedef {{questionId: number, elapsedMs: number | null, generation: number}} SubmissionSnapshot */

/**
 * 本次答题页面内的单题秒表，不恢复服务端或浏览器持久化数据。
 * @param {{now?: () => number}} [options]
 */
export function createQuestionTimer({ now = () => performance.now() } = {}) {
  /** @type {Map<number, QuestionTime>} */
  const questions = new Map()
  /** @type {number | null} */
  let currentId = null
  /** @type {number | null} */
  let startedAt = null
  let visible = true
  let generation = 0

  function settle() {
    if (startedAt === null || currentId === null) return
    const question = questions.get(currentId)
    if (question && question.elapsed !== null) {
      question.elapsed += Math.max(0, now() - startedAt)
    }
    startedAt = null
  }

  /** @param {number | null} questionId */
  function setQuestion(questionId, submitted = false) {
    settle()
    currentId = questionId
    if (questionId == null) return
    if (!questions.has(questionId)) {
      questions.set(questionId, { elapsed: submitted ? null : 0, submitted })
    }
    if (visible && questions.get(questionId)?.submitted === false) startedAt = now()
  }

  /** @param {boolean} value */
  function setVisible(value) {
    if (visible === value) return
    settle()
    visible = value
    if (visible && currentId !== null && questions.get(currentId)?.submitted === false) startedAt = now()
  }

  function elapsedMs(questionId = currentId) {
    if (questionId === null) return null
    const question = questions.get(questionId)
    if (!question || question.elapsed === null) return null
    const running = questionId === currentId && startedAt !== null
    return Math.floor(question.elapsed + (running && startedAt !== null ? Math.max(0, now() - startedAt) : 0))
  }

  /** @param {number} questionId */
  function captureSubmission(questionId) {
    return { questionId, elapsedMs: elapsedMs(questionId), generation }
  }

  /** @param {SubmissionSnapshot} snapshot */
  function completeSubmission(snapshot, durationMs = snapshot.elapsedMs) {
    if (snapshot.generation !== generation) return
    const question = questions.get(snapshot.questionId)
    if (!question || question.submitted) return
    question.elapsed = durationMs
    question.submitted = true
    if (snapshot.questionId === currentId) startedAt = null
  }

  function reset() {
    questions.clear()
    currentId = null
    startedAt = null
    generation += 1
  }

  return { setQuestion, setVisible, elapsedMs, captureSubmission, completeSubmission, reset }
}

/** @param {number | null} milliseconds */
export function formatQuestionDuration(milliseconds) {
  if (milliseconds === null) return '已提交'
  const seconds = Math.floor(milliseconds / 1000)
  const parts = [Math.floor(seconds / 60) % 60, seconds % 60]
  if (seconds >= 3600) parts.unshift(Math.floor(seconds / 3600))
  return parts.map(value => String(value).padStart(2, '0')).join(':')
}
