import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import client from '../api/client'
import { isGenerating, responseError } from '../utils/explanationPresentation'

export function useQuestionExplanations(question, autoReveal) {
  const models = ref([])
  const bodies = reactive(new Map())
  const opened = ref(false)
  const dispatching = ref(false)
  const reading = ref(false)
  const updatingModelId = ref(null)
  const error = ref('')
  const stale = ref(false)
  let inputStamp = null
  let correctAnswer = null
  const legacyAvailable = ref(false)
  let epoch = 0, sequence = 0, timer = null, disposed = false
  const current = generation => !disposed && generation === epoch
  const busy = computed(() => dispatching.value || reading.value || models.value.some(isGenerating))

  function stopPolling() {
    clearTimeout(timer)
    timer = null
  }

  function schedule(generation) {
    if (!current(generation)) return
    stopPolling()
    if (opened.value && models.value.some(isGenerating)) {
      timer = setTimeout(() => refresh(generation), 2000)
    }
  }

  function markStale(message = '题目已变化，请刷新页面后重新解析') {
    stale.value = true
    models.value = []
    bodies.clear()
    error.value = message
  }

  async function loadBodies(generation) {
    await Promise.all(models.value.filter(m => m.result && bodies.get(m.model_id)?.generation_id !== m.result.generation_id).map(async model => {
      const version = model.result.generation_id
      try {
        const { data } = await client.get('/ai/explanation', { params: { question_id: question().id, model_id: model.model_id } })
        if (!current(generation)) return
        const latest = models.value.find(m => m.model_id === model.model_id)
        if (data.input_fingerprint !== inputStamp) {
          markStale()
          return
        }
        if (data.correct_answer !== correctAnswer) {
          await refresh(generation)
          return
        }
        if (latest && data.result && data.result.generation_id >= (latest.result?.generation_id || version)) {
          const { explanation, explanation_zh, analysis, ...summary } = data.result
          latest.result = summary
          if (!latest.generation?.id || (data.generation?.id || 0) >= latest.generation.id) latest.generation = data.generation
          bodies.set(model.model_id, data.result)
        }
      } catch (e) {
        if (current(generation)) error.value = responseError(e, '正文加载失败，已保留已有解析，可重新读取')
      }
    }))
  }

  async function refresh(generation = epoch) {
    if (!current(generation) || !question()?.id) return
    const readSequence = ++sequence
    try {
      const { data } = await client.get('/ai/explanations', { params: { question_id: question().id } })
      if (!current(generation) || readSequence !== sequence) return
      if (inputStamp && data.input_fingerprint !== inputStamp) {
        markStale()
        return
      }
      inputStamp = data.input_fingerprint
      correctAnswer = data.correct_answer
      models.value = data.models
      legacyAvailable.value = data.has_legacy_explanation
      for (const id of bodies.keys()) {
        if (!data.models.some(m => m.model_id === id && m.result)) bodies.delete(id)
      }
      error.value = ''
      if (opened.value) await loadBodies(generation)
    } catch (e) {
      if (current(generation)) error.value = responseError(e, '读取状态失败，已保留已有解析，可重新读取')
    } finally {
      schedule(generation)
    }
  }

  async function generate(force, ids) {
    const generation = epoch
    const qid = question().id
    const queue = ids ? [...ids] : models.value.filter(m => force || (!m.result && !isGenerating(m) && m.generation?.status !== 'failed')).map(m => m.model_id)
    dispatching.value = true
    const worker = async () => {
      while (queue.length && current(generation) && !stale.value) {
        const id = queue.shift()
        try {
          const { data } = await client.post('/ai/explain', { question_id: qid, model_id: id, force, input_fingerprint: inputStamp })
          if (!current(generation)) return
          sequence += 1 // 更早发出的状态读取不能覆盖本次生成响应。
          const index = models.value.findIndex(m => m.model_id === id)
          if (index !== -1) models.value[index] = data
        } catch (e) {
          if (!current(generation)) return
          if (e.response?.status === 409) {
            markStale(responseError(e, '题目已变化，请刷新页面后重新解析'))
            return
          }
          const model = models.value.find(m => m.model_id === id)
          if (model) model.generation = { status: 'failed', error: responseError(e, '解析请求失败，请手动重试') }
        }
      }
    }
    try {
      await Promise.all(Array.from({ length: Math.min(3, queue.length) }, worker))
    } finally {
      if (current(generation)) {
        dispatching.value = false
        await refresh(generation)
      }
    }
  }

  async function act() {
    if (reading.value || dispatching.value || stale.value) return
    const generation = epoch
    const force = opened.value
    opened.value = true
    reading.value = true
    try {
      await refresh(generation)
      if (current(generation) && !stale.value) await generate(force)
    } finally {
      if (current(generation)) reading.value = false
    }
  }

  async function updateModel(id) {
    if (reading.value || dispatching.value || stale.value || isGenerating(models.value.find(m => m.model_id === id) || {})) return
    const generation = epoch
    reading.value = true
    updatingModelId.value = id
    try {
      await refresh(generation)
      if (current(generation) && !stale.value && models.value.some(m => m.model_id === id)) await generate(true, [id])
    } finally {
      if (current(generation)) {
        reading.value = false
        updatingModelId.value = null
      }
    }
  }

  watch(() => [question()?.id, question()?.ai_input_fingerprint], () => {
    epoch += 1
    sequence += 1
    stopPolling()
    models.value = (question()?.ai_explanations || []).map(m => ({ ...m }))
    for (const id of bodies.keys()) bodies.delete(id)
    opened.value = !!autoReveal()
    dispatching.value = false
    reading.value = false
    updatingModelId.value = null
    error.value = ''
    stale.value = false
    inputStamp = question()?.ai_input_fingerprint || null
    correctAnswer = question()?.correct_answer || null
    legacyAvailable.value = !!(question()?.explanation_zh || question()?.explanation)
    if (opened.value) refresh(epoch)
  }, { immediate: true })

  watch(autoReveal, reveal => {
    if (reveal) { opened.value = true; refresh(epoch) }
  })

  onBeforeUnmount(() => { disposed = true; epoch += 1; stopPolling() })
  return { models, bodies, opened, busy, dispatching, reading, updatingModelId, error, stale, legacyAvailable, act, updateModel, refresh }
}
