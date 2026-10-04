import { createRouter, createWebHistory } from 'vue-router'
import { useExamStore } from '../stores/exam'
import { examPath, routeKind } from '../utils/examRoutes'

const routes = [
  { path: '/login', name: 'Login', component: () => import('../views/LoginView.vue'), meta: { guest: true } },
  { path: '/register', name: 'Register', component: () => import('../views/RegisterView.vue'), meta: { guest: true } },
  { path: '/', name: 'Root', component: { render: () => null }, meta: { auth: true } },
  { path: '/onboarding', name: 'Onboarding', component: () => import('../views/FirstTimeOnboarding.vue'), meta: { auth: true, allowWithoutExam: true } },
  { path: '/exams', name: 'MyExamProjects', component: () => import('../views/MyExamProjectsPage.vue'), meta: { auth: true, allowWithoutExam: true } },
  { path: '/exams/new', name: 'ExamCreate', component: () => import('../views/ExamCreatePage.vue'), meta: { auth: true, allowWithoutExam: true } },
  { path: '/exams/:examSlug/dashboard', name: 'ExamDashboard', component: () => import('../views/HomeView.vue'), meta: { auth: true, examScoped: true } },
  { path: '/exams/:examSlug/banks', name: 'ExamBanks', component: () => import('../views/AdminBanksView.vue'), meta: { auth: true, examScoped: true } },
  { path: '/exams/:examSlug/banks/:bankId', name: 'ExamBankQuestions', component: () => import('../views/AdminQuestionsView.vue'), meta: { auth: true, examScoped: true } },
  { path: '/exams/:examSlug/quiz/:sessionId', name: 'ExamQuiz', component: () => import('../views/QuizView.vue'), meta: { auth: true, examScoped: true } },
  { path: '/exams/:examSlug/quiz/:sessionId/result', name: 'ExamQuizResult', component: () => import('../views/QuizResultView.vue'), meta: { auth: true, examScoped: true } },
  { path: '/exams/:examSlug/wrong', name: 'ExamWrongAnswers', component: () => import('../views/WrongAnswersView.vue'), meta: { auth: true, examScoped: true } },
  { path: '/exams/:examSlug/history', name: 'ExamHistory', component: () => import('../views/HistoryView.vue'), meta: { auth: true, examScoped: true } },
  { path: '/exams/:examSlug/vocab', name: 'ExamVocabulary', component: () => import('../views/VocabularyView.vue'), meta: { auth: true, examScoped: true } },
  { path: '/exams/:examSlug/import-jobs', name: 'ExamImportJobs', component: () => import('../views/ImportJobsView.vue'), meta: { auth: true, admin: true, examScoped: true } },
  { path: '/exams/:examSlug/import-jobs/:jobId', name: 'ExamImportJobDetail', component: () => import('../views/ImportJobDetailView.vue'), meta: { auth: true, admin: true, examScoped: true } },
  { path: '/exams/:examSlug/import-jobs/:jobId/review', name: 'ExamImportReview', component: () => import('../views/ImportReviewView.vue'), meta: { auth: true, admin: true, examScoped: true } },
  { path: '/exams/:examSlug/import-jobs/:jobId/auto-handled', name: 'ExamImportAutoHandled', component: () => import('../views/ImportAutoHandledView.vue'), meta: { auth: true, admin: true, examScoped: true } },
  { path: '/account', name: 'Account', component: () => import('../views/AccountView.vue'), meta: { auth: true, allowWithoutExam: true } },
  { path: '/admin/settings', name: 'AdminSettings', component: () => import('../views/AdminSettingsView.vue'), meta: { auth: true, admin: true, allowWithoutExam: true } },
  { path: '/admin/users', name: 'AdminUsers', component: () => import('../views/AdminUsersView.vue'), meta: { auth: true, admin: true, allowWithoutExam: true } },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  const token = localStorage.getItem('token')
  if (to.meta.auth && !token) return '/login'
  if (to.meta.guest && token) return '/'

  if (to.meta.admin) {
    const user = JSON.parse(localStorage.getItem('user') || 'null')
    if (!user?.is_admin) return '/'
  }

  if (!to.meta.auth) return true

  const examStore = useExamStore()
  if (!examStore.loaded) {
    try {
      await examStore.bootstrap()
    } catch {
      return '/login'
    }
  }

  if (to.name === 'Root') {
    return examStore.current?.slug ? examPath(examStore.current.slug, 'dashboard') : '/onboarding'
  }

  if (!examStore.current && !to.meta.allowWithoutExam) return '/onboarding'

  const urlSlug = to.params.examSlug
  if (urlSlug && urlSlug !== examStore.current?.slug) {
    try {
      await examStore.switchTo(urlSlug)
    } catch {
      return '/exams'
    }
  }

  if (to.name === 'Onboarding' && examStore.current?.slug) {
    return examPath(examStore.current.slug, 'dashboard')
  }

  if (to.meta.examScoped && !to.params.examSlug && examStore.current?.slug) {
    return examPath(examStore.current.slug, routeKind(to), to.params)
  }

  return true
})

export default router
