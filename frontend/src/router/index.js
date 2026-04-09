import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/login', name: 'Login', component: () => import('../views/LoginView.vue'), meta: { guest: true } },
  { path: '/register', name: 'Register', component: () => import('../views/RegisterView.vue'), meta: { guest: true } },
  { path: '/', name: 'Home', component: () => import('../views/HomeView.vue'), meta: { auth: true } },
  { path: '/quiz/:sessionId', name: 'Quiz', component: () => import('../views/QuizView.vue'), meta: { auth: true } },
  { path: '/quiz/:sessionId/result', name: 'QuizResult', component: () => import('../views/QuizResultView.vue'), meta: { auth: true } },
  { path: '/wrong', name: 'WrongAnswers', component: () => import('../views/WrongAnswersView.vue'), meta: { auth: true } },
  { path: '/history', name: 'History', component: () => import('../views/HistoryView.vue'), meta: { auth: true } },
  { path: '/vocabulary', name: 'Vocabulary', component: () => import('../views/VocabularyView.vue'), meta: { auth: true } },
  { path: '/account', name: 'Account', component: () => import('../views/AccountView.vue'), meta: { auth: true } },
  { path: '/admin/banks', name: 'AdminBanks', component: () => import('../views/AdminBanksView.vue'), meta: { auth: true, admin: true } },
  { path: '/admin/banks/:bankId', name: 'AdminQuestions', component: () => import('../views/AdminQuestionsView.vue'), meta: { auth: true, admin: true } },
  { path: '/admin/settings', name: 'AdminSettings', component: () => import('../views/AdminSettingsView.vue'), meta: { auth: true, admin: true } },
  { path: '/admin/users', name: 'AdminUsers', component: () => import('../views/AdminUsersView.vue'), meta: { auth: true, admin: true } },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('token')
  if (to.meta.auth && !token) {
    next('/login')
  } else if (to.meta.guest && token) {
    next('/')
  } else if (to.meta.admin) {
    const user = JSON.parse(localStorage.getItem('user') || 'null')
    if (!user?.is_admin) {
      next('/')
    } else {
      next()
    }
  } else {
    next()
  }
})

export default router
