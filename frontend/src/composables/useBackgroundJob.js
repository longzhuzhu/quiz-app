import { onUnmounted, ref } from 'vue'
import client from '../api/client'

export function useBackgroundJob() {
  const job = ref(null)
  const polling = ref(false)
  let timerId = null
  let generation = 0

  function clearTimer() {
    if (timerId) {
      clearTimeout(timerId)
      timerId = null
    }
  }

  function beginGeneration() {
    generation += 1
    clearTimer()
    polling.value = false
    return generation
  }

  function isCurrentGeneration(currentGeneration) {
    return currentGeneration === generation
  }

  function setJobSafely(nextJob, currentGeneration) {
    if (!isCurrentGeneration(currentGeneration)) return null
    job.value = nextJob
    return job.value
  }

  function stopPolling() {
    beginGeneration()
  }

  function clearJob() {
    const currentGeneration = beginGeneration()
    setJobSafely(null, currentGeneration)
  }

  async function fetchJob(jobId, currentGeneration) {
    const res = await client.get(`/jobs/${jobId}`)
    return setJobSafely(res.data.job, currentGeneration)
  }

  function startPolling(jobId, { onFinished } = {}, currentGeneration = beginGeneration()) {
    clearTimer()
    if (!isCurrentGeneration(currentGeneration)) return currentGeneration
    polling.value = true

    const tick = async () => {
      if (!isCurrentGeneration(currentGeneration)) return

      try {
        const current = await fetchJob(jobId, currentGeneration)
        if (!isCurrentGeneration(currentGeneration)) return

        if (!current || ['completed', 'failed'].includes(current.status)) {
          polling.value = false
          if (onFinished) await onFinished(current)
          return
        }

        timerId = window.setTimeout(() => {
          if (isCurrentGeneration(currentGeneration)) {
            tick()
          }
        }, 2000)
      } catch {
        if (!isCurrentGeneration(currentGeneration)) return

        clearTimer()
        polling.value = false
        setJobSafely(
          job.value
            ? {
                ...job.value,
                status: 'unknown',
                status_message: '任务状态获取失败，可刷新页面后重试',
              }
            : null,
          currentGeneration,
        )
      }
    }

    tick()
    return currentGeneration
  }

  async function createJob(payload, options = {}) {
    const currentGeneration = beginGeneration()
    setJobSafely(null, currentGeneration)

    const res = await client.post('/jobs', payload)
    const nextJob = setJobSafely(res.data.job, currentGeneration)
    if (!isCurrentGeneration(currentGeneration)) return null

    if (nextJob && ['queued', 'running'].includes(nextJob.status)) {
      startPolling(nextJob.id, options, currentGeneration)
    } else {
      polling.value = false
    }
    return res.data
  }

  async function restoreActiveJob(params, options = {}) {
    const currentGeneration = beginGeneration()
    setJobSafely(null, currentGeneration)

    const query = new URLSearchParams(params).toString()
    const res = await client.get(`/jobs/active?${query}`)
    const nextJob = setJobSafely(res.data.job, currentGeneration)
    if (!isCurrentGeneration(currentGeneration)) return null

    if (nextJob && ['queued', 'running'].includes(nextJob.status)) {
      startPolling(nextJob.id, options, currentGeneration)
    } else {
      polling.value = false
    }
    return nextJob
  }

  onUnmounted(stopPolling)

  return {
    job,
    polling,
    createJob,
    restoreActiveJob,
    stopPolling,
    clearJob,
  }
}
