import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '../api/client'

export const useExamStore = defineStore('exam', () => {
  const current = ref(null)
  const myExams = ref([])
  const loaded = ref(false)
  const loading = ref(false)

  function persistActiveExam(exam) {
    const user = JSON.parse(localStorage.getItem('user') || 'null')
    if (!user) return
    user.active_exam = exam || null
    localStorage.setItem('user', JSON.stringify(user))
  }

  async function fetchExams() {
    const res = await client.get('/exams')
    myExams.value = Array.isArray(res.data?.items) ? res.data.items : []
    return myExams.value
  }

  async function bootstrap() {
    if (loading.value) return
    loading.value = true
    try {
      const meRes = await client.get('/auth/me')
      localStorage.setItem('user', JSON.stringify(meRes.data))
      current.value = meRes.data?.active_exam || null
      await fetchExams()
      loaded.value = true
    } finally {
      loading.value = false
    }
  }

  async function switchTo(slug) {
    const res = await client.post('/account/active-exam', { slug })
    current.value = res.data?.active_exam || null
    persistActiveExam(current.value)
    await fetchExams()
    return current.value
  }

  async function createExam(payload) {
    const res = await client.post('/exams', {
      ai_profile_mode: 'default',
      ...payload,
    })
    const exam = res.data
    await fetchExams()
    await switchTo(exam.slug)
    return exam
  }

  async function deleteExam(slug) {
    await client.delete(`/exams/${slug}`)
    myExams.value = myExams.value.filter((exam) => exam.slug !== slug)
    if (current.value?.slug === slug) {
      current.value = null
      persistActiveExam(null)
    }
  }

  function setCurrent(exam) {
    current.value = exam
    persistActiveExam(exam)
  }

  function reset() {
    current.value = null
    myExams.value = []
    loaded.value = false
    loading.value = false
  }

  return {
    current,
    myExams,
    loaded,
    loading,
    bootstrap,
    fetchExams,
    switchTo,
    createExam,
    deleteExam,
    setCurrent,
    reset,
  }
})
