import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '../api/client'

export const useQuizStore = defineStore('quiz', () => {
  const session = ref(null)
  const questions = ref([])
  const currentIndex = ref(0)

  async function startQuiz(bankId, mode, questionCount) {
    const res = await client.post('/quiz/start', {
      bank_id: bankId,
      mode,
      question_count: questionCount,
    })
    session.value = res.data.session
    questions.value = res.data.questions
    currentIndex.value = 0
  }

  async function submitAnswer(questionId, userAnswer) {
    const res = await client.post('/quiz/answer', {
      session_id: session.value.id,
      question_id: questionId,
      user_answer: userAnswer,
    })
    return res.data
  }

  async function finishQuiz() {
    const res = await client.post('/quiz/finish', {
      session_id: session.value.id,
    })
    session.value = res.data.session
    return res.data
  }

  function nextQuestion() {
    if (currentIndex.value < questions.value.length - 1) {
      currentIndex.value++
    }
  }

  function prevQuestion() {
    if (currentIndex.value > 0) {
      currentIndex.value--
    }
  }

  function reset() {
    session.value = null
    questions.value = []
    currentIndex.value = 0
  }

  return { session, questions, currentIndex, startQuiz, submitAnswer, finishQuiz, nextQuestion, prevQuestion, reset }
})
