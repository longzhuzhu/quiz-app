export function examPath(slug, kind = 'dashboard', params = {}) {
  if (!slug) return '/onboarding'
  const encoded = encodeURIComponent(slug)
  const paths = {
    dashboard: `/exams/${encoded}/dashboard`,
    banks: `/exams/${encoded}/banks`,
    wrong: `/exams/${encoded}/wrong`,
    history: `/exams/${encoded}/history`,
    vocab: `/exams/${encoded}/vocab`,
    importJobs: `/exams/${encoded}/import-jobs`,
  }
  if (kind === 'quiz' && params.sessionId) return `/exams/${encoded}/quiz/${params.sessionId}`
  if (kind === 'quizResult' && params.sessionId) return `/exams/${encoded}/quiz/${params.sessionId}/result`
  if (kind === 'importJobDetail' && params.jobId) return `/exams/${encoded}/import-jobs/${params.jobId}`
  if (kind === 'importReview' && params.jobId) return `/exams/${encoded}/import-jobs/${params.jobId}/review`
  if (kind === 'importAutoHandled' && params.jobId) return `/exams/${encoded}/import-jobs/${params.jobId}/auto-handled`
  return paths[kind] || paths.dashboard
}

export function routeKind(route) {
  const name = String(route.name || '')
  if (name === 'ExamBanks') return 'banks'
  if (name === 'ExamWrongAnswers') return 'wrong'
  if (name === 'ExamHistory') return 'history'
  if (name === 'ExamVocabulary') return 'vocab'
  if (name === 'ExamImportJobs') return 'importJobs'
  if (name === 'ExamImportJobDetail') return 'importJobDetail'
  if (name === 'ExamImportReview') return 'importReview'
  if (name === 'ExamImportAutoHandled') return 'importAutoHandled'
  if (name === 'ExamQuiz' || name === 'ExamQuizResult') return 'dashboard'
  return 'dashboard'
}

export function currentExamPath(route, kind = null, params = {}) {
  return examPath(route.params.examSlug, kind || routeKind(route), { ...route.params, ...params })
}
